"""Deterministic labor-capacity planning. No storage, HTTP, or browser behavior."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

from .operations_models import AcceptanceStatus, ProjectState, VehicleOperations, calculate_commitment_dates

ZONE = ZoneInfo("America/Chicago")


def default_calendar_settings() -> dict:
    return {
        "schema_version": 1, "buffer_percent": 10, "hours_per_day": 8,
        "finishing_hours": 4, "holidays": [],
        "teams": [
            {"id": "team-david", "name": "David's Team", "people": 2,
             "build_hours": 60, "strip_hours": 6, "color": "blue", "active": True, "days_off": []},
            {"id": "team-josh", "name": "Josh's Team", "people": 2,
             "build_hours": 60, "strip_hours": 6, "color": "purple", "active": True, "days_off": []},
            {"id": "team-michelle", "name": "Michelle", "people": 1,
             "build_hours": 40, "strip_hours": 6, "color": "teal", "active": True, "days_off": []},
        ],
    }


def valid_day(value: object, label: str, *, optional: bool = True) -> str:
    if value in ("", None) and optional:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a date")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} must be a valid date") from None
    if day.isoformat() != value or not 2000 <= day.year <= 2100:
        raise ValueError(f"{label} must be a date between 2000 and 2100")
    return value


def number(value: object, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{label} must be between {low:g} and {high:g}")
    return result


def validate_settings(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema_version", 1) != 1:
        raise ValueError("Unsupported Calendar settings")
    result = deepcopy(data)
    for key, low, high in (("buffer_percent", 0, 50), ("hours_per_day", 1, 12), ("finishing_hours", 0, 40)):
        result[key] = number(data.get(key), key.replace("_", " "), low, high)
    teams = result.get("teams")
    if not isinstance(teams, list) or not 1 <= len(teams) <= 50:
        raise ValueError("Keep between 1 and 50 teams, including retired teams")
    ids = set()
    for team in teams:
        if not isinstance(team, dict):
            raise ValueError("Each team must be an object")
        ident = team.get("id")
        if not isinstance(ident, str) or not ident or len(ident) > 80 or ident in ids:
            raise ValueError("Each team needs a unique ID")
        ids.add(ident)
        if not isinstance(team.get("name"), str) or not 1 <= len(team["name"].strip()) <= 80:
            raise ValueError("Each team needs a name of 1–80 characters")
        team["name"] = team["name"].strip()
        people = number(team.get("people"), "People per team", 1, 12)
        if not people.is_integer():
            raise ValueError("People per team must be a whole number")
        team["people"] = int(people)
        for key in ("build_hours", "strip_hours"):
            team[key] = number(team.get(key), key.replace("_", " "), 0 if key == "strip_hours" else 1, 2000)
        if team.get("color") not in {"blue", "purple", "teal", "orange", "rose", "slate"}:
            raise ValueError("Choose a team color from the list")
        if not isinstance(team.get("active"), bool):
            raise ValueError("Team active setting must be true or false")
        team["days_off"] = _days(team.get("days_off", []), "Team days off")
    if not any(team["active"] for team in teams):
        raise ValueError("Keep at least one active team")
    result["holidays"] = _days(result.get("holidays", []), "Shop closed dates")
    return result


def _days(values: object, label: str) -> list[str]:
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError(f"{label} must be a list of dates")
    return sorted(set(valid_day(d, label, optional=False) for d in values))


def acceptance_day(record: VehicleOperations) -> str:
    """Preserve actual acceptance evidence; never substitute observation time."""
    if record.acceptance_source == 'qbo':
        return _acceptance_day(record.qbo_estimate_accepted_at[:10])
    return _acceptance_day(record.accepted_at or record.qbo_estimate_accepted_at)


def _acceptance_day(raw: str) -> str:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.replace(tzinfo=ZONE).date().isoformat() if dt.tzinfo is None else dt.astimezone(ZONE).date().isoformat()
    except (ValueError, AttributeError):
        return ""


def acceptance_details(record: VehicleOperations, spec: dict) -> dict:
    recorded = acceptance_day(record)
    qbo = _acceptance_day(record.qbo_estimate_accepted_at[:10]) if record.qbo_estimate_status.casefold() in {'accepted', 'closed'} else ''
    source = record.acceptance_source or 'manual'
    chosen = recorded
    return {'accepted_date': chosen, 'accepted_date_source': source,
            'recorded_accepted_date': recorded, 'qbo_accepted_date': qbo}


def _work_start(day: date) -> datetime:
    return datetime.combine(day, time(8))


def work_segments(start: datetime, hours: float, daily_capacity: float, closed: set[str], workday: float) -> tuple[list[dict], datetime]:
    """Allocate labor against real working dates, retaining partial-day capacity."""
    if hours <= 0:
        return [], start
    cursor = start
    remaining = hours
    segments = []
    for _ in range(6000):
        if cursor.weekday() >= 5 or cursor.date().isoformat() in closed:
            cursor = _work_start(cursor.date() + timedelta(days=1))
            continue
        day_start = _work_start(cursor.date())
        cursor = max(cursor, day_start)
        elapsed = (cursor - day_start).total_seconds() / 3600
        room = max(0, workday - elapsed)
        if room < 1e-7:
            cursor = _work_start(cursor.date() + timedelta(days=1))
            continue
        used = min(remaining, room * daily_capacity / workday)
        end = cursor + timedelta(hours=used * workday / daily_capacity)
        if used > 0:
            segments.append({"date": cursor.date().isoformat(), "start_hour": round(8 + elapsed, 4),
                             "end_hour": round(8 + elapsed + used * workday / daily_capacity, 4)})
        remaining -= used
        cursor = end
        if remaining < 1e-7:
            return segments, cursor
    raise ValueError("The schedule exceeds the supported planning horizon")


def _team(settings, ids):
    teams = {t['id']: t for t in settings['teams']}
    if not ids or any(i not in teams for i in ids):
        raise ValueError('Choose a team before scheduling')
    members = [teams[i] for i in ids]
    return {**members[0], 'team_ids': ids, 'name': ' + '.join(t['name'] for t in members),
            'people': sum(t['people'] for t in members),
            'days_off': sorted({d for t in members for d in t['days_off']}),
            'build_hours': max(t['build_hours'] for t in members),
            'strip_hours': max(t['strip_hours'] for t in members)}


def _hours(spec, team):
    if spec.get('hours') is not None:
        return number(spec['hours'], 'Labor hours', .25, 4000) + spec.get('travel_hours', 0) + (team['strip_hours'] if spec.get('include_strip') else 0)
    if spec.get('kind') in ('service', 'offsite'):
        raise ValueError('Enter estimated labor hours for service work')
    kind = spec.get('kind', 'strip_build')
    return team['strip_hours'] if kind == 'strip' else team['build_hours'] if kind == 'build' else team['build_hours'] + team['strip_hours']


def _blocked(record, kind):
    if not record or record.shop_status in ('in_progress', 'complete'):
        return []
    from .project_types import physical_readiness
    parts, vehicle = physical_readiness(record)
    return (["Waiting on parts"] if not parts and kind != 'strip' else []) + (
        ["Waiting on vehicle"] if not vehicle else []) + (
        ["Design not finalized"] if record.project_type == 'build' and not record.build_finalized and kind != 'strip' else [])


def _overlaps(segments, team_ids, jobs):
    return [j for j in jobs if not j.get('historical') and j.get('shop_status') != 'complete'
            and set(team_ids).intersection(j['team_ids']) and any(
                a['date'] == b['date'] and a['start_hour'] < b['end_hour'] - .0001
                and b['start_hour'] < a['end_hour'] - .0001
                for a in segments for b in j['segments'])]


def _reserved_start(last):
    if last.get('segments'):
        first = last['segments'][0]
        return datetime.combine(date.fromisoformat(first['date']), time()) + timedelta(hours=first['start_hour'])
    return datetime.fromisoformat(last['start'])


def calculate_opening(settings, spec, jobs, *, earliest):
    """Find a contiguous working-time gap; never modify an existing reservation."""
    # Only the visible, saved work intervals reserve a team. Advisory forecasts
    # must not silently extend a booking's capacity beyond its displayed dates.
    team = _team(settings, spec.get('team_ids') or [spec.get('team_id')])
    if any(not t['active'] for t in settings['teams'] if t['id'] in team['team_ids']):
        raise ValueError('Choose active teams')
    hours = _hours(spec, team)
    rate = team['people'] * settings['hours_per_day'] * (1 - settings['buffer_percent'] / 100)
    closed = set(settings['holidays']) | set(team['days_off'])
    cursor = earliest
    for _ in range(10000):
        segments, end = work_segments(cursor, hours, rate, closed, settings['hours_per_day'])
        hits = _overlaps(segments, team['team_ids'], jobs)
        if not hits:
            first = segments[0]
            return datetime.combine(date.fromisoformat(first['date']), time()) + timedelta(hours=first['start_hour'])
        # Advance beyond the earliest overlapping occupied segment, preserving earlier gaps.
        collision = min((b for j in hits for b in j['segments'] if any(
            a['date'] == b['date'] and a['start_hour'] < b['end_hour'] - .0001
            and b['start_hour'] < a['end_hour'] - .0001 for a in segments)),
            key=lambda b: (b['date'], b['end_hour']))
        cursor = datetime.combine(date.fromisoformat(collision['date']), time()) + timedelta(hours=collision['end_hour'])
    raise ValueError('No opening within the supported horizon')


def plan_calendar(records: list[VehicleOperations], settings: dict, saved: dict, *, today: date,
                  hidden_projects: set[str] | None = None) -> dict:
    """Display stable reservations and a separate acceptance queue.

    Only service-validated `_stage` entries calculate a new booking. Reads refresh
    status and risk metadata, never move a saved interval or reserve the queue.
    """
    settings = validate_settings(settings)
    specs = saved.get('jobs', {})
    visible = [r for r in records if r.project_id not in (hidden_projects or set())
               and r.project_state != ProjectState.INACTIVE]
    counts = Counter(r.project_id for r in visible)
    numbers = {r.vehicle_id: i + 1 for p in counts
               for i, r in enumerate(sorted((r for r in visible if r.project_id == p), key=lambda r: r.vehicle_id))}
    output, queue, missing, staged, released = [], [], [], [], []
    warnings = []
    for record, ident, spec in [(r, r.vehicle_id, deepcopy(specs.get(r.vehicle_id, {}))) for r in visible] + [
            (None, i, deepcopy(s)) for i, s in specs.items() if s.get('custom')]:
        if spec.get('cancelled') or spec.get('released'):
            spec.pop('last_plan', None)
            if not record:
                continue
        spec.setdefault('kind', record.project_type if record and record.project_type != 'build' else 'strip_build')
        historical = bool(spec.get('completed') or (record and (
            record.project_state == ProjectState.COMPLETED or record.final_finish_status in ('delivered', 'ready_for_delivery'))))
        accepted = acceptance_day(record) if record else spec.get('accepted_date', '')
        base = {'id': ident, 'project_id': record.project_id if record else ident,
                'title': (record.title or record.vehicle_label) if record else spec.get('title', 'Job'),
                'agency_name': record.agency_name if record else '', 'unit_number': record.unit_number if record else '',
                'vin': record.vin if record else '', 'accepted_date': accepted,
                'project_type': record.project_type if record else spec.get('kind', 'service'),
                'service_details': record.service_details if record else {},
                'vehicle_label': record.vehicle_label if record else '',
                'parts_status': str(record.parts_status) if record else '',
                'vehicle_availability_status': str(record.vehicle_availability_status) if record else '',
                'deadline': (record.must_deliver_override_date or calculate_commitment_dates(
                    record.vehicle_available_date, record.parts_received_at or record.parts_ready_at)[1] if record.project_type == 'build' else record.must_deliver_override_date) if record else spec.get('promised_date', ''),
                'build_number': numbers.get(ident, 1), 'build_count': counts.get(record.project_id, 1) if record else 1,
                'remaining_hours': spec.get('remaining_hours'), 'forecast_edited': bool(spec.get('_forecast_edit')),
                'acceptance_confirmed': record is None or (record.acceptance_status == AcceptanceStatus.ACCEPTED and bool(accepted)),
                'custom': record is None, 'revision': record.revision if record else None,
                'shop_status': str(record.shop_status) if record else '', 'kind': spec.get('kind', 'strip_build'),
                'warnings': [], 'blocked': _blocked(record, spec.get('kind', 'strip_build')),
                'accepted_at': record.accepted_at if record else '', 'acceptance_source': record.acceptance_source if record else '',
                'qbo_estimate_accepted_at': record.qbo_estimate_accepted_at if record else '',
                'qbo_estimate_status': record.qbo_estimate_status if record else ''}
        if record and spec.get('released'):
            released.append({**base, 'released': True, 'historical': False, 'start': '', 'ready': '',
                'change_reason': spec.get('change_reason', 'Removed from Calendar'),
                'operations_dates': {'planned_start_date': record.planned_start_date,
                    'target_finish_date': record.target_finish_date, 'scheduled_week_of': record.scheduled_week_of}})
        job = {'id': ident, 'record': record, 'spec': spec, 'project': base['project_id'], 'accepted': accepted}
        if spec.get('_stage'):
            staged.append((job, base))
            continue
        last = spec.get('last_plan')
        if last:
            team = _team(settings, last.get('team_ids') or [last['team_id']])
            # Calculate current evidence independently; the approved segments below remain intact.
            reasons = _blocked(record, spec.get('kind', last['kind']))
            forecast_spec = {**spec, 'kind': last['kind']}
            forecast_hours = spec.get('remaining_hours') if record and record.shop_status == 'in_progress' else None
            hours = forecast_hours if forecast_hours is not None else spec.get('hours') or last['hours']
            forecast_job = {**job, 'spec': forecast_spec}
            start = _reserved_start(last)
            if forecast_hours is not None and not historical:
                start = max(start, _work_start(today))
            rate = team['people'] * settings['hours_per_day'] * (1 - settings['buffer_percent'] / 100)
            current, _ = _scheduled_job(forecast_job, team, hours, start, rate,
                set(settings['holidays']) | set(team['days_off']), settings, reasons, last['start'][:10])
            out = {**last, **{k:v for k,v in base.items() if k not in ('kind',)}, **{k: current[k] for k in (
                'team_name', 'color', 'blocked', 'warnings', 'deadline', 'operations_dates', 'actual_start', 'actual_finish',
                'shop_status', 'acceptance_source', 'accepted_at', 'qbo_estimate_accepted_at', 'qbo_estimate_status')},
                'saved': True, 'pinned': True, 'historical': historical,
                'promised_start': spec.get('promised_start', ''), 'promised_ready': spec.get('promised_ready', ''),
                'forecast_start': current['start'], 'forecast_ready': current['ready'], 'forecast_segments': current['segments'], 'conflicts': []}
            if not historical and not (record and record.shop_status == 'complete'):
                if record and not base['acceptance_confirmed']:
                    reason = 'Acceptance date needed' if not accepted else 'Acceptance no longer confirmed; review held booking'
                    out['warnings'].append(reason)
                    missing.append({**base, 'reason': reason})
                if current['start'] != last['start'] or current['ready'] != last['ready']:
                    out['warnings'].append('Working forecast differs from reserved dates')
                if any(not t['active'] for t in settings['teams'] if t['id'] in out['team_ids']):
                    out['warnings'].append('Reserved team is retired')
                closed = set(settings['holidays']) | set(team['days_off'])
                if any(s['date'] in closed for s in out['segments']):
                    out['warnings'].append('Reservation includes a team absence or shop closure')
            if historical or (record and record.shop_status == 'complete'):
                out['warnings'] = []
            if record:
                out.update(acceptance_details(record, spec))
            output.append(out)
        elif record and not historical:
            existing_start = record.planned_start_date or record.scheduled_week_of or spec.get('start_date')
            if existing_start and not spec.get('released'):
                missing.append({**base, 'reason': 'Existing booking needs team/date reconciliation',
                                'legacy_booking': True, 'original_start': existing_start})
            elif record.acceptance_status == AcceptanceStatus.ACCEPTED:
                if accepted:
                    queue.append({**base, 'unscheduled': True, **acceptance_details(record, spec), 'blocked': _blocked(record, spec.get('kind', 'strip_build'))})
                else:
                    missing.append({**base, 'reason': 'Acceptance date needed'})
    # A reviewed set is placed in acceptance order. All unaffected reservations stay occupied.
    for job, base in sorted(staged, key=lambda pair: (pair[0]['accepted'], pair[0]['project'], pair[0]['id'])):
        spec, record = job['spec'], job['record']
        team = _team(settings, spec.get('team_ids') or [spec.get('team_id')])
        hours = spec.get('remaining_hours') if record and record.shop_status == 'in_progress' else None
        hours = hours if hours is not None else _hours(spec, team)
        rate = team['people'] * settings['hours_per_day'] * (1 - settings['buffer_percent'] / 100)
        closed = set(settings['holidays']) | set(team['days_off'])
        last = spec.get('last_plan', {})
        requested = spec.get('start_date')
        if requested:
            if last.get('start', '')[:10] == requested and last.get('team_ids', [last.get('team_id')]) == team['team_ids']:
                start = _reserved_start(last)
            else:
                start = _work_start(date.fromisoformat(requested))
                # A date-only request can use the hours after another build ends.
                # Keep the requested day: if no full-duration gap starts that day,
                # expose the conflict for explicit overlap confirmation instead.
                opening = calculate_opening(settings, {**spec, 'hours': hours}, output, earliest=start)
                if opening.date() == start.date():
                    start = opening
        else:
            start = calculate_opening(settings, {**spec, 'hours': hours}, output, earliest=_work_start(max(today, date.fromisoformat(spec.get('_earliest') or today.isoformat()))))
        out, _ = _scheduled_job(job, team, hours, start, rate, closed, settings,
                                _blocked(record, spec.get('kind', 'strip_build')), requested)
        out.update({k:v for k,v in base.items() if k not in ('warnings','blocked','kind')}, pinned=True, historical=False, staged=True, conflicts=[],
                   promised_start=spec.get('promised_start', ''), promised_ready=spec.get('promised_ready', ''))
        out['forecast_start'], out['forecast_ready'] = out['start'], out['ready']
        if requested and out['start'][:10] != requested:
            out['conflicts'].append('Requested start is not a working day for this team')
        if missing and any(m.get('legacy_booking') for m in missing):
            out['conflicts'].append('Reconcile existing bookings before reserving new capacity')
        output.append(out)
    for out in output:
        out['hard_conflicts'] = list(out.get('conflicts', [])) if out.get('staged') else []
        out['overlaps'] = []
        hits = _overlaps(out['segments'], out['team_ids'], [j for j in output if j['id'] != out['id']]) if not out.get('historical') and out.get('shop_status') != 'complete' else []
        out.setdefault('conflicts', []).extend('Overlaps ' + j['title'] + ' (' + j['start'][:10] + '–' + j['end'][:10] + ')' for j in hits)
        out['overlaps'].extend({k: j.get(k) for k in ('id', 'project_id', 'title', 'agency_name', 'start', 'end')} for j in hits)
        out['warnings'].extend(out['conflicts'])
        if not out.get('historical') and out.get('shop_status') != 'complete':
            risk_hits = _overlaps(out.get('forecast_segments', out['segments']), out['team_ids'], [j for j in output if j['id'] != out['id']])
            out['warnings'].extend('Working forecast threatens ' + j['title'] for j in risk_hits if j not in hits)
        out['calendar_label'] = out['title'] if out['custom'] else out['agency_name']
    queue.sort(key=lambda j: (j['accepted_date'], j['project_id'], j['id']))
    output.sort(key=lambda j: (j['start'], j['id']))
    accepted_ids = {r.vehicle_id for r in visible if r.acceptance_status == AcceptanceStatus.ACCEPTED}
    accepted_queue = sorted(queue + [j for j in output if j['id'] in accepted_ids and j['accepted_date'] and not j.get('historical')],
                            key=lambda j: (j['accepted_date'], j['project_id'], j['id']))
    return {'jobs': output, 'released': released, 'queue': queue, 'accepted_queue': accepted_queue, 'needs_review': missing, 'warnings': warnings,
            'start_date': saved.get('start_date') or today.isoformat(), 'as_of': today.isoformat()}


def _scheduled_job(job, team, hours, start, rate, closed, settings, reasons, original):
    r, spec = job["record"], job["spec"]
    if hours:
        segments, end = work_segments(start, hours, rate, closed, settings["hours_per_day"])
        first_day = date.fromisoformat(segments[0]['date'])
        start = max(start, _work_start(first_day))
    else:
        segments, end = [], start
    finishing = 0 if spec.get("kind") == "strip" or (spec.get("kind") in ("service", "offsite") and not spec.get("include_finishing")) else settings["finishing_hours"]
    finish_segments, ready = work_segments(end, finishing, settings["hours_per_day"], set(settings["holidays"]), settings["hours_per_day"])
    automatic_deadline = calculate_commitment_dates(r.vehicle_available_date, r.parts_received_at or r.parts_ready_at)[1] if r and r.project_type == "build" else ""
    deadline = (r.must_deliver_override_date or automatic_deadline) if r else spec.get("promised_date", "")
    warnings = []
    if deadline and ready.date().isoformat() > deadline:
        warnings.append("Past delivery deadline")
    return {"id": job["id"], "project_id": job["project"], "title": (r.title or r.vehicle_label) if r else spec["title"],
            "agency_name": r.agency_name if r else spec.get("agency_name", ""),
            "team_id": team["id"], "team_ids": team.get('team_ids',[team['id']]), "team_name": team["name"], "color": team["color"],
            "hours": hours, "kind": spec.get("kind", "strip_build"), "accepted_date": job["accepted"],
            "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"),
            "ready": ready.isoformat(timespec="minutes"), "segments": segments, "finish_segments": finish_segments,
            "pinned": spec.get("pinned", False), "original_start": original or "", "blocked": reasons,
            "warnings": warnings, "deadline": deadline, "custom": r is None, "unit_number": r.unit_number if r else "",
            "revision": r.revision if r else None, "saved": bool(spec),
            "vin": r.vin if r else '', "vehicle_label": r.vehicle_label if r else '',
            "shop_status": str(r.shop_status) if r else '',
            "acceptance_source": r.acceptance_source if r else '',
            "accepted_at": r.accepted_at if r else '',
            "qbo_estimate_accepted_at": r.qbo_estimate_accepted_at if r else '',
            "qbo_estimate_status": r.qbo_estimate_status if r else '',
            "vehicle_id": job['id'],
            "operations_dates": {"planned_start_date": r.planned_start_date, "target_finish_date": r.target_finish_date,
                                  "scheduled_week_of": r.scheduled_week_of} if r else {},
            "actual_start": r.shop_started_at if r else spec.get("actual_start", ""),
            "actual_finish": r.shop_completed_at if r else spec.get("actual_finish", ""),
            "actual_hours": spec.get("actual_hours"),
            **(acceptance_details(r, spec) if r else {})}, end
