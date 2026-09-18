"""Calendar reads, reviewed planning changes, and existing Operations date writes."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
import hashlib
import json

from ...config.schemas import validate_config_payload
from ...domain.calendar_planning import ZONE, acceptance_day, calculate_opening, number, plan_calendar, shop_closed_dates, valid_day, validate_settings, work_segments, _scheduled_job, _team, _hours, _work_start
from ...domain.operations_policy import Capability, has_capability
from ...domain.operations_models import AcceptanceStatus, ProjectState
from ...inputs.project_entry import list_projects
from ..adapters.calendar_store import CalendarConflictError, CalendarStore
from .operations_service import OperationsAuthorizationError, OperationsService


def _fingerprint(records):
    # Bind review to scheduling evidence, not polling timestamps or unrelated
    # Operations notes. Save still reads fresh rows and publication uses their
    # exact revisions through the existing audited Operations commands.
    fields = ('vehicle_id', 'project_id', 'project_type', 'service_details', 'project_state', 'acceptance_status',
              'accepted_at', 'acceptance_source', 'qbo_estimate_accepted_at', 'qbo_estimate_status',
              'parts_status', 'parts_received_at', 'parts_ready_at', 'vehicle_availability_status',
              'vehicle_available_date', 'build_finalized', 'shop_status', 'shop_started_at',
              'shop_completed_at', 'ready_for_delivery_at', 'delivered_date', 'final_finish_status', 'must_deliver_override_date',
              'planned_start_date', 'scheduled_week_of', 'target_finish_date',
              'title', 'vehicle_label', 'agency_name', 'unit_number', 'vin')
    return hashlib.sha256(json.dumps(sorted(tuple(getattr(r, key) for key in fields) for r in records)).encode()).hexdigest()


class CalendarService:
    def __init__(self, paths, bundle, *, cloud=False, clock=None, authorize=None):
        self.paths, self.bundle = paths, bundle
        self.cloud = cloud
        self.authorize = authorize
        self.store = CalendarStore(paths, cloud_storage=bundle.storage if cloud else None)
        self.today = clock or (lambda: datetime.now(ZONE).date())

    def _require(self, actor, capability):
        if (not actor.user_id or not has_capability(actor.roles, capability)
                or (self.authorize is not None and not self.authorize(actor, capability))):
            raise OperationsAuthorizationError("Your role cannot change this Calendar setting")

    def _read(self):
        if self.bundle.operations is None:
            raise ValueError("Operations connection is not configured")
        projects = list_projects(self.paths)
        hidden = {p.project_id for p in projects if p.project_status == "inactive"}
        completed = {p.project_id for p in projects if p.project_status == "completed"}
        records = [replace(r, project_state=ProjectState.COMPLETED) if r.project_id in completed else r
                   for r in self.bundle.operations.list_vehicles() if r.project_id not in hidden]
        from ...domain.project_types import with_project_work
        by_id = {p.project_id: p for p in projects}
        return [with_project_work(r, by_id.get(r.project_id)) for r in records]

    def view(self, actor):
        self._require(actor, Capability.OPERATIONS_VIEW)
        data, revision = self.store.read()
        records = self._read()
        return self._payload(data, revision, records)

    def _payload(self, data, revision, records):
        plan = plan_calendar(records, data['settings'], data, today=self.today())
        openings = []
        opening_note = 'Standard strip + build'
        if any(j.get('legacy_booking') for j in plan['needs_review']):
            opening_note = 'Reconcile existing bookings to calculate the next opening'
        else:
            for team in data['settings']['teams']:
                if not team['active']:
                    continue
                try:
                    start = calculate_opening(data['settings'], {'team_id': team['id'], 'kind': 'strip_build'},
                        plan['jobs'], earliest=_work_start(self.today()))
                    openings.append({'team_id': team['id'], 'team_name': team['name'], 'start': start.isoformat(timespec='minutes')})
                except ValueError:
                    continue  # No usable opening in the bounded search horizon.
        return {"ok": True, "revision": revision, "source_revision": _fingerprint(records), "local_only": not self.cloud,
                "split_projects": [pid for pid in sorted({j['project_id'] for j in plan['jobs']})
                                   if self._project_split(plan, data['settings'], pid)],
                "settings": data["settings"], "plan": plan, "closed_dates": sorted(shop_closed_dates(validate_settings(data["settings"]))), "next_openings": openings, "opening_note": opening_note,
                "pending_date_count": len(self.date_changes(plan['jobs'], plan['released'])),
                "saved_jobs": data["jobs"], "project_teams": data.get('project_teams', {}),
                "history": data.get("history", []), "schema_version": data["schema_version"]}

    def preview(self, actor, body):
        self._require(actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        data, revision = self.store.read()
        if body.get("revision") != revision:
            raise CalendarConflictError("Calendar changed. Refresh before editing.")
        records = self._read()
        if body.get("source_revision") != _fingerprint(records) and body.get('refresh_operations') is not True:
            raise CalendarConflictError("Operations changed. Refresh before editing.")
        proposed = self._edit(data, body, records)
        result = self._payload(proposed, revision, records)
        # A content-bound ticket is checked again on save; the client never
        # supplies computed dates or authority to overwrite an Operations row.
        result['changes'] = self._changes(data, proposed, result['plan'])
        staged = [j for j in result['plan']['jobs'] if j.get('staged')]
        result['migration_required'] = data['schema_version'] == 1
        result['settings_changed'] = data['settings'] != proposed['settings']
        result['settings_impacts'] = [{'id':j['id'], 'title':j['title'], 'start':j['start'], 'ready':j['ready'], 'forecast_ready':j['forecast_ready'], 'warnings':j['warnings']} for j in result['plan']['jobs'] if not j.get('historical') and j['warnings']] if result['settings_changed'] else []
        result['requires_reason'] = self._needs_reason(result['changes'], staged) or bool(result['settings_impacts'])
        result['conflicts'] = list(dict.fromkeys(c for j in staged for c in j.get('conflicts', [])))
        result['blocking_conflicts'] = list(dict.fromkeys(c for j in staged for c in j.get('hard_conflicts', [])))
        result['overlaps'] = list({j['id']: j for row in staged for j in row.get('overlaps', [])}.values())
        result['publication'] = [{'id': j['id'], 'title': j['title'], 'before': j['operations_dates'], 'start': j['start'][:10], 'ready': j['ready'][:10]} for j in self.date_changes(result['plan']['jobs'], result['plan']['released'])]
        result['preview_token'] = self._token(proposed, records)
        return result

    def save(self, actor, body):
        self._require(actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        data, revision = self.store.read()
        records = self._read()
        proposed = self._edit(data, body, records)
        if revision != body.get('revision') or body.get('preview_token') != self._token(proposed, records):
            raise CalendarConflictError('The plan changed since the preview. Review the new dates.')
        preview = self._payload(proposed, revision, records)
        selected = {i for i, s in proposed['jobs'].items() if s.get('_stage')}
        staged = [j for j in preview['plan']['jobs'] if j['id'] in selected]
        conflicts = [c for j in staged for c in j.get('conflicts', [])]
        hard_conflicts = [c for j in staged for c in j.get('hard_conflicts', [])]
        if hard_conflicts or (conflicts and (proposed.get('_reordered') or not proposed.get('_allow_overlap'))):
            raise ValueError('Resolve booking conflicts before saving: ' + '; '.join(dict.fromkeys(conflicts)))
        reason = self._reason(body)
        changes = self._changes(data, proposed, preview['plan'])
        if (self._needs_reason(changes, staged) or (data['settings'] != proposed['settings'] and any(j['warnings'] for j in preview['plan']['jobs'] if not j.get('historical')))) and not reason:
            raise ValueError('Explain the booking change or acknowledged risk before saving')
        for j in staged:
            spec = proposed['jobs'][j['id']]
            spec.update(team_id=j['team_id'], team_ids=j['team_ids'], hours=_hours(spec, _team(proposed['settings'], j['team_ids'])) if spec.get('remaining_hours') is not None else j['hours'],
                        kind=j['kind'], pinned=True, start_date=j['start'][:10],
                        promised_start=j['promised_start'], promised_ready=j['promised_ready'])
            spec.pop('_stage', None)
            spec.pop('_earliest', None)
            spec.pop('_forecast_edit', None)
            spec['change_reason'] = reason or 'Initial reservation'
            spec['last_plan'] = deepcopy(j)
            spec['last_plan']['change_reason'] = spec['change_reason']
            spec['last_plan'].pop('staged', None)
        for spec in proposed['jobs'].values():
            for key in ('_sequence', '_not_before', '_after'):
                spec.pop(key, None)
            if spec.pop('_release', False):
                for key in ('last_plan', 'team_id', 'team_ids', 'start_date', 'pinned', 'team_assignment_manual'):
                    spec.pop(key, None)
                spec['change_reason'] = reason or 'Removed from Calendar'
            spec.pop('_stage', None)
            spec.pop('_earliest', None)
            spec.pop('_forecast_edit', None)
        proposed.pop('_reason', None)
        proposed.pop('_allow_overlap', None)
        proposed.pop('_reordered', None)
        proposed['schema_version'] = 2
        now = datetime.now(ZONE).isoformat()
        if data['settings'] != proposed['settings']:
            proposed.setdefault('history', []).append({'at': now, 'actor_id': actor.user_id, 'actor': actor.display_name, 'reason': reason or 'Team settings updated', 'settings_before': data['settings'], 'settings_after': proposed['settings'], 'changes': []})
        if changes:
            proposed.setdefault('history', []).append({'at': now, 'actor_id': actor.user_id,
                'actor': actor.display_name, 'reason': reason or 'Initial reservation',
                'changes': changes})
        proposed['updated_at'], proposed['updated_by'] = now, actor.display_name
        revision = self.store.write(proposed, revision)
        return self._payload(proposed, revision, records)

    @staticmethod
    def _reason(body):
        reason = body.get('reason', '')
        if not isinstance(reason, str) or len(reason.strip()) > 1000:
            raise ValueError('Use an explanation of at most 1000 characters')
        return reason.strip()

    @staticmethod
    def _summary(job):
        if not job:
            return None
        return {k: job.get(k) for k in ('team_ids', 'start', 'end', 'ready', 'hours', 'kind',
                                      'promised_start', 'promised_ready', 'remaining_hours')}

    def _changes(self, old, proposed, plan):
        changes = []
        by_id = {j['id']: j for j in plan['jobs']}
        for ident, spec in proposed['jobs'].items():
            before = old['jobs'].get(ident, {})
            if not spec.get('_stage') and not spec.get('_forecast_edit') and not spec.get('_release') and spec.get('cancelled') == before.get('cancelled') and spec.get('completed') == before.get('completed'):
                continue
            prior = deepcopy(before.get('last_plan'))
            if prior:
                prior.update(promised_start=before.get('promised_start', ''), promised_ready=before.get('promised_ready', ''), remaining_hours=before.get('remaining_hours'))
            after = None if spec.get('cancelled') or spec.get('released') else by_id.get(ident)
            if self._summary(prior) != self._summary(after) or spec.get('completed') != before.get('completed'):
                changes.append({'id': ident, 'title': (after or prior or {}).get('title', ident),
                    'before': self._summary(prior), 'after': self._summary(after),
                    'completed': bool(spec.get('completed'))})
        return changes

    @staticmethod
    def _needs_reason(changes, staged):
        return any(c['before'] for c in changes) or any(j['blocked'] or j['warnings'] for j in staged)

    def opening(self, actor, body):
        self._require(actor, Capability.OPERATIONS_VIEW)
        data, revision = self.store.read()
        records = self._read()
        plan = plan_calendar(records, data['settings'], data, today=self.today())
        if any(j.get('legacy_booking') for j in plan['needs_review']):
            raise ValueError('Reconcile existing bookings before quoting an opening')
        spec = body.get('opening')
        if not isinstance(spec, dict):
            raise ValueError('Choose team, job type and labor assumptions')
        ids = spec.get('team_ids')
        active = {t['id'] for t in data['settings']['teams'] if t['active']}
        if not isinstance(ids, list) or len(ids) != 1 or any(not isinstance(i, str) or i not in active for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Choose one active team')
        spec = {'team_id': ids[0], 'team_ids': ids, 'kind': spec.get('kind', 'strip_build'), 'hours': spec.get('hours'), 'title': 'Calculated opening'}
        if spec['kind'] not in ('strip_build', 'strip', 'build', 'service', 'offsite'):
            raise ValueError('Choose a job type')
        if spec['kind'] in ('service', 'offsite') and spec['hours'] is None:
            raise ValueError('Enter total labor hours for this job')
        earliest = valid_day(body.get('earliest') or self.today().isoformat(), 'Earliest start', optional=False)
        count = number(body.get('vehicle_count', 1), 'Vehicle count', 1, 50)
        if not count.is_integer():
            raise ValueError('Vehicle count must be a whole number')
        occupied, openings = list(plan['jobs']), []
        team = _team(data['settings'], ids)
        settings = data['settings']
        for i in range(int(count)):
            start = calculate_opening(settings, spec, occupied,
                earliest=_work_start(max(self.today(), date.fromisoformat(earliest))))
            job, _ = _scheduled_job({'id': f'opening-{i}', 'record': None, 'project': '', 'accepted': '', 'spec': spec},
                team, _hours(spec, team), start, team['people'] * settings['hours_per_day'] * (1-settings['buffer_percent']/100),
                shop_closed_dates(settings) | set(team['days_off']), settings, [], '')
            openings.append(job)
            occupied.append(job)
        return {'ok': True, 'reserved': False, 'opening': {**openings[0], 'ready': openings[-1]['ready']},
                'vehicles': openings, 'revision': revision,
                'assumptions': {'people': team['people'], 'hours_per_day': settings['hours_per_day'],
                                'vehicle_count': int(count), 'buffer_percent': settings['buffer_percent'],
                                'finishing_hours': settings['finishing_hours']}}

    def availability(self, actor, body):
        self._require(actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        data, revision = self.store.read()
        records = self._read()
        edit = body.get('availability')
        if not isinstance(edit, dict):
            raise ValueError('Choose a vehicle and date')
        choices = []
        for team in data['settings']['teams']:
            if not team['active']:
                continue
            proposal = self._edit(data, {'edit': {**edit, 'team_id': team['id'], 'team_ids': [team['id']]},
                'include_project': body.get('include_project', False), 'move_project': body.get('move_project', False)}, records)
            plan = plan_calendar(records, data['settings'], proposal, today=self.today())
            jobs = [j for j in plan['jobs'] if j.get('staged')]
            selected = next(j for j in jobs if j['id'] == edit['id'])
            overlaps = list({j['id']: j for row in jobs for j in row.get('overlaps', [])}.values())
            choices.append({'team_id': team['id'], 'busy': bool(overlaps), 'overlaps': overlaps,
                'blocking_conflicts': list(dict.fromkeys(c for j in jobs for c in j.get('hard_conflicts', []))),
                'start': selected['start'], 'end': selected['end'], 'ready': selected['ready'], 'warnings': selected['warnings'],
                'vehicles': [{'id': j['id'], 'title': j['title'], 'start': j['start'], 'ready': j['ready']} for j in jobs]})
        return {'ok': True, 'revision': revision, 'source_revision': _fingerprint(records), 'choices': choices}

    @staticmethod
    def date_changes(jobs, released=()):
        clears = [j for j in released if any(j['operations_dates'].values())]
        return clears + [j for j in jobs if not j['custom'] and not j.get('historical') and j.get('acceptance_confirmed', True) and (
            j['operations_dates']['planned_start_date'] != j['start'][:10]
            or j['operations_dates']['target_finish_date'] != j['ready'][:10]
            or j['operations_dates']['scheduled_week_of'] != (
                date.fromisoformat(j['start'][:10]) - timedelta(days=date.fromisoformat(j['start'][:10]).weekday())
            ).isoformat())]

    def publish_dates(self, actor, saved, request_id, *, on_progress):
        """Publish the saved snapshot without rereading the whole backlog per car."""
        self._require(actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        if self.bundle.operations_writer is None:
            raise ValueError('Schedule writes are unavailable')
        for count, job in enumerate(self.date_changes(saved['plan']['jobs'], saved['plan']['released']), 1):
            self._require(actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
            if self.store.current_revision() != saved['revision']:
                raise CalendarConflictError('Calendar changed while dates were uploading.')
            start = date.fromisoformat(job['start'][:10]) if job['start'] else None
            OperationsService(self.bundle.operations_writer).change_schedule(
                vehicle_id=job['id'], planned_start_date=start.isoformat() if start else '',
                scheduled_week_of=(start-timedelta(days=start.weekday())).isoformat() if start else '',
                target_finish_date=job['ready'][:10], actor=actor,
                request_id=f'{request_id}:{job["id"]}', expected_revision=job['revision'],
                source_client='builder_desktop', reason=job.get('change_reason', 'Reviewed Calendar dates'))
            on_progress(count)

    def save_settings(self, actor, body):
        # Settings participate in the same preview ticket and impact review.
        return self.save(actor, body)

    def apply_dates(self, actor, body):
        """Idempotent one-vehicle mirror into the existing Operations timeline."""
        self._require(actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        data, revision = self.store.read()
        if revision != body.get("revision"):
            raise CalendarConflictError("Calendar changed. Refresh before saving dates.")
        records = self._read()
        plan = plan_calendar(records, data["settings"], data, today=self.today())
        job = next((j for j in plan["jobs"] if j["id"] == body.get("vehicle_id") and not j["custom"] and not j.get("historical")), None)
        if job is None:
            raise ValueError("That vehicle is no longer in the Calendar")
        if body.get("expected_revision") != job["revision"]:
            raise CalendarConflictError("This vehicle changed. Refresh before saving dates.")
        if body.get("dates") != [job["start"][:10], job["ready"][:10]]:
            raise CalendarConflictError("These dates changed. Review the current plan.")
        if self.bundle.operations_writer is None:
            raise ValueError("Schedule writes are unavailable")
        start = date.fromisoformat(job["start"][:10])
        result = OperationsService(self.bundle.operations_writer).change_schedule(
            vehicle_id=job["id"], planned_start_date=start.isoformat(),
            scheduled_week_of=(start - timedelta(days=start.weekday())).isoformat(),
            target_finish_date=job["ready"][:10], actor=actor,
            request_id=body.get("request_id") or "", expected_revision=job["revision"], source_client="builder_desktop", reason=job.get("change_reason", "Reviewed Calendar dates"))
        return {"ok": True, "revision": result.record.revision}

    def _token(self, data, records):
        material = {"data": data, "source": _fingerprint(records), "today": self.today().isoformat()}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def _edit(self, data, body, records):
        result = deepcopy(data)
        result['_reason'] = self._reason(body)
        if body.get('schedule_action') is not None:
            if any(body.get(key) for key in ('edit', 'edits', 'settings', 'project_assignment', 'remove_project', 'remove_vehicle', 'fill_gap', 'include_project', 'move_project')):
                raise ValueError('Review one scheduling action at a time')
            return self._reorder(result, body['schedule_action'], records)
        if not isinstance(body.get('move_project', False), bool):
            raise ValueError('Group mode must be true or false')
        if not isinstance(body.get('allow_overlap', False), bool):
            raise ValueError('Overlap confirmation must be true or false')
        result['_allow_overlap'] = body.get('allow_overlap', False)
        if not isinstance(body.get('include_project', False), bool):
            raise ValueError('Project scheduling selection must be true or false')
        removal = body.get('remove_project') or body.get('remove_vehicle')
        if removal is not None:
            if not isinstance(removal, str) or (body.get('remove_project') and body.get('remove_vehicle')) or any(body.get(k) for k in ('edit', 'edits', 'settings', 'project_assignment')):
                raise ValueError('Choose one project to remove')
            if not isinstance(body.get('fill_gap', False), bool):
                raise ValueError('Choose whether to fill the gap')
            current = plan_calendar(records, data['settings'], data, today=self.today())
            key = 'project_id' if body.get('remove_project') else 'id'
            jobs = [j for j in current['jobs'] if j[key] == removal and not j.get('historical') and j.get('shop_status') != 'complete']
            if not jobs:
                raise ValueError('This project has no current bookings to remove')
            for job in jobs:
                result['jobs'][job['id']].update(released=True, _release=True)
            if body.get('remove_project'):
                result.setdefault('project_teams', {}).pop(removal, None)
            if body.get('fill_gap'):
                result = self._fill_gap(result, current, jobs, records)
            return result
        if 'settings' in body:
            settings = validate_config_payload('calendar_settings.json', body['settings'])
            if not {t['id'] for t in data['settings']['teams']}.issubset({t['id'] for t in settings['teams']}):
                raise ValueError('Retire a team instead of deleting it, so past assignments remain readable')
            result['settings'] = settings
        edits = body.get('edits')
        if edits is not None and body.get('edit') is not None:
            raise ValueError('Use one reviewed set of edits')
        if edits is None:
            edits = [body['edit']] if body.get('edit') is not None else []
        assignment = body.get('project_assignment')
        if assignment is not None:
            if edits or not isinstance(assignment, dict):
                raise ValueError('Choose one project assignment')
            project_id, selected = assignment.get('project_id'), assignment.get('team_ids')
            active = {t['id'] for t in data['settings']['teams'] if t['active']}
            if not isinstance(selected, list) or len(selected) != 1 or any(not isinstance(t, str) or t not in active for t in selected) or len(set(selected)) != len(selected):
                raise ValueError('Choose one active project team')
            vehicles = sorted((r for r in records if r.project_id == project_id and r.project_state == ProjectState.ACTIVE
                               and r.acceptance_status == AcceptanceStatus.ACCEPTED and acceptance_day(r)
                               and r.shop_status not in ('in_progress', 'complete')
                               and r.final_finish_status not in ('delivered', 'ready_for_delivery')
                               and not data['jobs'].get(r.vehicle_id, {}).get('last_plan')),
                              key=lambda r: (acceptance_day(r), r.vehicle_id))
            if not vehicles:
                raise ValueError('No accepted, unscheduled vehicles with dates in this project')
            # Select the nearest gap within the scheduler's explicit pool, reserving each
            # staged vehicle before calculating the next one. Never reassign saved bookings.
            earliest = valid_day(assignment.get('start_date') or self.today().isoformat(), 'Start date', optional=False)
            for record in vehicles:
                occupied = plan_calendar(records, result['settings'], result, today=self.today())['jobs']
                team = min(selected, key=lambda ident: calculate_opening(result['settings'],
                    {**result['jobs'].get(record.vehicle_id, {}), 'team_id': ident, 'team_ids': [ident]}, occupied, earliest=_work_start(max(self.today(), date.fromisoformat(earliest)))))
                result = self._edit_one(result, {'edit': {'id': record.vehicle_id, 'team_id': team,
                    'start_date': '', '_earliest': earliest}}, records)
            edits = []
            result.setdefault('project_teams', {})[project_id] = selected
        if not isinstance(edits, list) or len(edits) > 500:
            raise ValueError('Choose at most 500 vehicle changes')
        ids = []
        for edit in edits:
            if not isinstance(edit, dict) or not isinstance(edit.get('id'), str) or edit['id'] in ids:
                raise ValueError('Each reviewed change needs a unique vehicle ID')
            ids.append(edit['id'])
            result = self._edit_one(result, {'edit': edit}, records)
        if body.get('move_project', False):
            if not isinstance(body['move_project'], bool) or len(edits) != 1 or assignment is not None:
                raise ValueError('Group move requires one scheduled vehicle')
            selected = next((record for record in records if record.vehicle_id == edits[0]['id']), None)
            selected_spec = result['jobs'].get(edits[0]['id'], {})
            if selected is None or not selected_spec.get('last_plan'):
                raise ValueError('Choose an existing scheduled vehicle to move its project as a group')
            result = self._reorder(result, {'id': selected.vehicle_id, 'mode': 'insert', 'group': True,
                'team_id': selected_spec['team_id'], 'start_date': selected_spec.get('start_date') or self.today().isoformat()}, records)
        if body.get('include_project'):
            if len(edits) != 1 or assignment is not None:
                raise ValueError('Select one vehicle to schedule its project')
            selected = next((r for r in records if r.vehicle_id == edits[0]['id']), None)
            if selected is None:
                raise ValueError('Choose a project vehicle')
            team = edits[0]['team_id']
            earliest = edits[0].get('start_date') or self.today().isoformat()
            siblings = sorted((r for r in records if r.project_id == selected.project_id and r.vehicle_id != selected.vehicle_id
                and r.project_state == ProjectState.ACTIVE and r.acceptance_status == AcceptanceStatus.ACCEPTED
                and acceptance_day(r) and r.shop_status != 'complete'
                and r.final_finish_status not in ('delivered', 'ready_for_delivery')
                and not data['jobs'].get(r.vehicle_id, {}).get('last_plan')), key=lambda r: (acceptance_day(r), r.vehicle_id))
            for record in siblings:
                service_estimate = {k: edits[0][k] for k in ('hours', 'hours_manual') if k in edits[0]} if selected.project_type != 'build' else {}
                result = self._edit_one(result, {'edit': {'id': record.vehicle_id, 'team_id': team,
                    'start_date': '', '_earliest': earliest, **service_estimate}}, records)
        return result

    @staticmethod
    def _project_split(plan, settings, project_id):
        rows = sorted((j for j in plan['jobs'] if j['project_id'] == project_id
                       and not j.get('historical') and j.get('shop_status') != 'complete'), key=lambda j: j['start'])
        if rows and any(j['project_id'] == project_id for j in plan['queue']):
            return True
        for prior, row in zip(rows, rows[1:]):
            if prior['team_ids'] != row['team_ids']:
                return True
            team = _team(settings, row['team_ids'])
            segments, _ = work_segments(datetime.fromisoformat(prior['end']), .25,
                team['people'] * settings['hours_per_day'] * (1-settings['buffer_percent']/100),
                shop_closed_dates(settings) | set(team['days_off']), settings['hours_per_day'])
            first = segments[0]
            expected = _work_start(date.fromisoformat(first['date'])) + timedelta(hours=first['start_hour']-8)
            if abs((datetime.fromisoformat(row['start'])-expected).total_seconds()) > 60:
                return True
        return False

    def _fill_gap(self, data, current, removed, records):
        removed_ids = {j['id'] for j in removed}
        result = deepcopy(data)
        result['_reordered'] = True
        sequence = 0
        for team_id in sorted({team for j in removed for team in j['team_ids']}):
            start = min(j['start'] for j in removed if team_id in j['team_ids'])
            rows = sorted((j for j in current['jobs'] if j['id'] not in removed_ids
                and team_id in j['team_ids'] and j['start'] >= start
                and not j.get('historical') and j.get('shop_status') != 'complete'), key=lambda j: (j['start'], j['id']))
            previous = None
            for row in rows:
                if len(row['team_ids']) != 1:
                    raise ValueError('Reconcile legacy joint-team bookings before filling the gap')
                result = self._edit_one(result, {'edit': {'id':row['id'], 'team_id':team_id, 'start_date':''}}, records)
                spec = result['jobs'][row['id']]
                spec.update(_sequence=sequence, _not_before=start)
                if previous:
                    spec['_after'] = previous
                previous = row['id']
                sequence += 1
        return result

    def _reorder(self, data, action, records):
        """Stage a server-computed queue; never accept computed dates from the UI.

        Every moved reservation is reviewed and published by the usual save flow.
        Downstream bookings keep their earliest held time and may only move forward.
        """
        if not isinstance(action, dict) or action.get('mode') not in ('new', 'next_ready', 'insert', 'before', 'after', 'swap', 'replace'):
            raise ValueError('Choose insert, replace, or swap')
        if not isinstance(action.get('group', False), bool):
            raise ValueError('Group mode must be true or false')
        if not isinstance(action.get('include_project', False), bool):
            raise ValueError('Project scheduling selection must be true or false')
        if any(not isinstance(action.get(key, False), bool) for key in ('whole_project', 'confirm_consolidation')):
            raise ValueError('Project consolidation selections must be true or false')
        if action.get('include_project') and (action.get('group') or action.get('whole_project')):
            raise ValueError('Choose either unscheduled project units or a scheduled project move')
        baseline = deepcopy(data)
        for spec in baseline['jobs'].values():
            spec.pop('_stage', None)
        current = plan_calendar(records, data['settings'], baseline, today=self.today())
        jobs = {j['id']: j for j in current['jobs'] if not j.get('historical') and j.get('shop_status') != 'complete'}
        ident, target_id, mode = action.get('id'), action.get('target_id'), action['mode']
        if not isinstance(ident, str) or (target_id is not None and not isinstance(target_id, str)):
            raise ValueError('Choose vehicle IDs')
        source = jobs.get(ident) or next((j for j in current['queue'] if j['id'] == ident), None)
        if mode == 'next_ready':
            candidates = (source or {}).get('recovery_candidates', [])
            if action.get('whole_project'):
                candidates = [candidate for candidate in candidates if all(
                    not row['blocked'] and row['team_ids'] == source['team_ids'] and row['start'] > source['start']
                    and row.get('shop_status') != 'in_progress'
                    for row in jobs.values() if row['project_id'] == jobs[candidate['id']]['project_id'])]
            if not candidates:
                raise ValueError('No later ready build is scheduled on this team')
            target_id, mode = candidates[0]['id'], 'swap'
        target = jobs.get(target_id)
        if not source or (mode not in ('insert', 'new') and not target) or ident == target_id:
            raise ValueError('Choose current, distinct bookings')
        if mode == 'swap' and ident not in jobs:
            raise ValueError('Only scheduled builds can swap; insert or replace this build instead')
        if mode == 'replace' and ident in jobs:
            raise ValueError('Use swap for two scheduled builds')

        def block(job):
            rows = [job]
            if (action.get('group') or action.get('whole_project')) and not job['custom']:
                rows = sorted([j for j in jobs.values() if j['project_id'] == job['project_id']], key=lambda j: (j['start'], j['id']))
                if action.get('whole_project') and job['id'] == ident:
                    rows += [j for j in current['queue'] if j['project_id'] == job['project_id']]
                elif job['id'] not in jobs:
                    rows.append(job)
            if any(len(j.get('team_ids', [])) > 1 for j in rows):
                raise ValueError('Reconcile legacy joint-team bookings before inserting or swapping them')
            return rows

        sources, targets = block(source), block(target) if target else []
        if action.get('whole_project') and not action.get('confirm_consolidation') and any(
                self._project_split(current, data['settings'], j['project_id']) for j in (source, target) if j):
            raise ValueError('This project is split across the schedule. Confirm placing all its units together, or reschedule units individually.')
        if action.get('include_project'):
            if ident in jobs or source['custom']:
                raise ValueError('Choose an unscheduled project card')
            sources = [row for row in current['queue'] if row['project_id'] == source['project_id']]
        source_ids, target_ids = {j['id'] for j in sources}, {j['id'] for j in targets}
        if source_ids & target_ids:
            raise ValueError('Choose a build outside the moving project block')
        team = target['team_id'] if target else action.get('team_id')
        if target:
            start = max(j['end'] for j in targets) if mode == 'after' else min(j['start'] for j in targets)
        else:
            start_day = valid_day(action.get('start_date'), 'Start date', optional=False)
            start = _work_start(date.fromisoformat(start_day)).isoformat(timespec='minutes')
            if mode == 'new':
                # Open-space drops append after work already occupying that day;
                # only an explicit insertion edge goes before existing work.
                start = max([start] + [j['end'] for j in jobs.values() if j['id'] not in source_ids
                    and team in j['team_ids'] and j['start'][:10] <= start_day <= j['end'][:10]])
        lanes = [(team, start, sources)]
        removed = set(source_ids)
        if mode in ('swap', 'replace'):
            removed |= target_ids
        if mode == 'swap':
            lanes.append((source['team_id'], min(j['start'] for j in sources), targets))
        result = deepcopy(data)
        result['_reordered'] = True
        if mode == 'replace':
            for row in targets:
                result['jobs'][row['id']].update(released=True, _release=True)
        # Combine insertion anchors with existing reservations in chronological order.
        sequence = 0
        for team_id in dict.fromkeys(lane[0] for lane in lanes):
            anchors = [(at, 0, rows) for team, at, rows in lanes if team == team_id]
            first = min(at for at, _, _ in anchors)
            entries = anchors + [(j['start'], 1, [j]) for j in jobs.values()
                if team_id in j['team_ids'] and j['id'] not in removed and j['start'] >= first]
            previous = None
            for at, _, rows in sorted(entries, key=lambda entry: (entry[0], entry[1])):
                for row in rows:
                    if len(row.get('team_ids', [])) > 1:
                        raise ValueError('Reconcile legacy joint-team bookings before shifting later work')
                    edit = {'id': row['id'], 'team_id': team_id, 'start_date': ''}
                    result = self._edit_one(result, {'edit': edit}, records)
                    spec = result['jobs'][row['id']]
                    spec.update(_sequence=sequence, _not_before=at)
                    if previous:
                        spec['_after'] = previous
                    sequence += 1
                    previous = row['id']
        return result

    def _edit_one(self, data, body, records):
        result = deepcopy(data)
        edit = body.get("edit")
        if edit is None:
            return result
        if not isinstance(edit, dict):
            raise ValueError("Job details must be an object")
        ident = edit.get("id")
        valid_ids = {r.vehicle_id for r in records}
        if not isinstance(ident, str) or len(ident) > 100 or not ident:
            raise ValueError("A job ID is required")
        old = result["jobs"].get(ident, {})
        custom = old.get("custom", False) or (ident.startswith("job-") and ident not in valid_ids)
        if not custom and ident not in valid_ids:
            raise ValueError("Vehicle not found")
        record = next((r for r in records if r.vehicle_id == ident), None)
        if not custom and (record.project_state != ProjectState.ACTIVE or record.acceptance_status != AcceptanceStatus.ACCEPTED
                           or not acceptance_day(record)):
            raise ValueError('Accept the vehicle and record its actual acceptance date before scheduling')
        if not custom and (record.shop_status == 'complete' or record.final_finish_status in ('delivered', 'ready_for_delivery')):
            raise ValueError('Completed bookings cannot be rescheduled')
        spec = deepcopy(old)
        spec.pop('released', None)
        if '_earliest' in edit:
            spec['_earliest'] = valid_day(edit['_earliest'], 'Earliest date', optional=False)
        spec['_stage'] = not (edit.get('cancelled') or edit.get('completed'))
        if not old.get('last_plan') and not old.get('released') and record and (record.planned_start_date or record.scheduled_week_of):
            spec['legacy_booking'] = True
            spec.setdefault('start_date', record.planned_start_date or record.scheduled_week_of)
        elif old.get('last_plan'):
            spec.setdefault('start_date', old['last_plan']['start'][:10])
        spec["custom"] = custom
        teams = {t["id"]: t for t in result["settings"]["teams"]}
        team_id = edit.get("team_id", old.get("team_id"))
        if team_id not in teams or (not teams[team_id]["active"] and team_id != old.get("team_id")):
            raise ValueError("Choose an active team")
        spec["team_id"] = team_id
        selected = edit.get('team_ids', [team_id] if 'team_id' in edit else old.get('team_ids', [team_id]))
        if (not isinstance(selected, list) or len(selected) != 1 or selected[0] != team_id
                or len(set(selected)) != len(selected) or any(t not in teams for t in selected)):
            raise ValueError('Choose one team for this vehicle')
        if any(not teams[t]['active'] and t not in old.get('team_ids', [old.get('team_id')]) for t in selected):
            raise ValueError('Choose active teams')
        spec['team_ids'] = selected
        spec['team_assignment_manual'] = edit.get('team_assignment_manual', old.get('team_assignment_manual', True))
        default_kind = record.project_type if record and record.project_type != 'build' else 'strip_build'
        kind = edit.get("kind", old.get("kind", default_kind))
        if record and record.project_type != 'build' and kind != record.project_type:
            raise ValueError('Service bookings must use their project type')
        if kind not in {"build", "strip", "strip_build", "service", "offsite"}:
            raise ValueError("Choose a job type")
        spec["kind"] = kind
        if record and record.project_type != 'build':
            spec['travel_hours'] = record.service_details.get('travel_hours', 0) if kind == 'offsite' else 0
            spec['include_strip'] = record.service_details.get('requires_strip', False)
            spec['include_finishing'] = record.service_details.get('requires_finishing', False)
        if 'accepted_date_source' in edit:
            source = edit['accepted_date_source']
            if source not in {'recorded', 'qbo', 'manual'}:
                raise ValueError('Choose where the accepted date comes from')
            spec['accepted_date_source'] = source
            if source != 'manual':
                spec.pop('accepted_date', None)
        for key in ("hours", "actual_hours", "remaining_hours"):
            if key in edit:
                spec[key] = None if edit[key] is None else number(edit[key], "Total labor hours", 0.25, 4000)
        if kind in {"service", "offsite"} and spec.get("hours") is None:
            raise ValueError("Enter total labor hours for this job")
        for key in ("start_date", "accepted_date", "promised_date", "promised_start", "promised_ready", "actual_start", "actual_finish"):
            if key in edit:
                if key == "promised_date" and not custom:
                    raise ValueError("Use the Operations delivery deadline editor for this vehicle")
                spec[key] = valid_day(edit[key], key.replace("_", " "))
        if 'accepted_date_source' in edit and spec.get('accepted_date_source') == 'manual':
            valid_day(spec.get('accepted_date'), 'Accepted on', optional=False)
            if spec['accepted_date'] > self.today().isoformat():
                raise ValueError('Accepted on cannot be in the future')
        elif 'accepted_date_source' in edit:
            spec.pop('accepted_date', None)
            if spec['accepted_date_source'] == 'qbo':
                record = next((r for r in records if r.vehicle_id == ident), None)
                if record is None or not record.qbo_estimate_accepted_at or record.qbo_estimate_status.casefold() not in {'accepted', 'closed'}:
                    raise ValueError('Link an accepted Estimate with an Accepted Date first, or enter a date manually')
        for key in ("pinned", "cancelled", "completed", "hours_manual", "team_assignment_manual"):
            if key in edit:
                if not isinstance(edit[key], bool):
                    raise ValueError(f"{key} must be true or false")
                if key in {"cancelled", "completed"} and not custom:
                    raise ValueError("Use Operations to complete a vehicle")
                spec[key] = edit[key]
        if spec.get('promised_start') and spec.get('promised_ready') and spec['promised_ready'] < spec['promised_start']:
            raise ValueError('Agreed ready date must not precede agreed start')
        if custom:
            title = edit.get("title", old.get("title", ""))
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= 150:
                raise ValueError("Enter a job name of 1–150 characters")
            spec["title"] = title.strip()
        if old.get('last_plan') and spec.get('remaining_hours') != old.get('remaining_hours'):
            baseline = {**old, 'start_date': old.get('start_date') or old['last_plan']['start'][:10]}
            keys = ('team_id', 'team_ids', 'kind', 'hours', 'start_date', 'promised_start', 'promised_ready')
            if all(spec.get(k) == baseline.get(k) for k in keys):
                # Remaining labor is a progress/forecast correction, not permission to move
                # the held interval. A separate date/team change still requires placement review.
                spec['_stage'] = False
                spec['_forecast_edit'] = True
        if (spec.get('_stage') and record and record.shop_status == 'in_progress'
                and spec.get('remaining_hours') is not None and spec.get('start_date')
                and spec['start_date'] < self.today().isoformat()):
            raise ValueError('Choose a current or future start for remaining work, or clear the date for the nearest opening')
        result["jobs"][ident] = spec
        return result
