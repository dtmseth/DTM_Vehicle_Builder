"""Local Calendar replica and durable, coalescing outbox.

Foreground planning never waits for a provider after the initial snapshot. A
single worker publishes immutable snapshots with shared ETags; later local
edits remain visible while that snapshot travels to the provider.
"""
from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

from ...domain.calendar_planning import plan_calendar
from ...domain.operations_models import VehicleOperations
from ...domain.operations_policy import Capability
from ..adapters.calendar_store import CalendarConflictError
from .calendar_service import _fingerprint

_REGISTRY = {}
_REGISTRY_LOCK = threading.RLock()
_MISSING = object()
_DATE_FIELDS = ('planned_start_date', 'scheduled_week_of', 'target_finish_date')


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _write(path, state):
    """One fsynced replacement owns both the visible document and its outbox."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _merge(base, local, remote, *, reviewed=False):
    """Rebase disjoint edits; never choose a winner for a concurrent booking."""
    result = deepcopy(remote)
    for field in ('settings', 'start_date', 'jobs', 'project_teams'):
        if field in ('jobs', 'project_teams'):
            value = deepcopy(remote.get(field, {}))
            for key in set(base.get(field, {})) | set(local.get(field, {})):
                before, after = base.get(field, {}).get(key, _MISSING), local.get(field, {}).get(key, _MISSING)
                other = remote.get(field, {}).get(key, _MISSING)
                if before == after:
                    continue
                if other != before and other != after and not reviewed:
                    raise CalendarConflictError('A shared booking changed on another device. Your local changes are retained; resolve the shared booking before retrying sync.')
                if after is _MISSING:
                    value.pop(key, None)
                else:
                    value[key] = deepcopy(after)
            result[field] = value
        elif local.get(field) != base.get(field):
            if remote.get(field) != base.get(field) and remote.get(field) != local.get(field) and not reviewed:
                raise CalendarConflictError('Shared team settings changed on another device. Your local changes are retained; review the settings before retrying sync.')
            result[field] = deepcopy(local.get(field))
    history = {_hash(h): h for h in remote.get('history', [])}
    history.update({_hash(h): h for h in local.get('history', [])})
    result['history'] = sorted(history.values(), key=lambda h: h['at'])
    for field in ('schema_version', 'updated_at', 'updated_by'):
        if field in local:
            result[field] = local[field]
    return result


class _SnapshotStore:
    def __init__(self, document, revision):
        self.document, self.revision = deepcopy(document), revision

    def read(self):
        return deepcopy(self.document), self.revision

    def write(self, document, expected):
        if expected != self.revision:
            raise CalendarConflictError('This booking changed locally. Check its current details and confirm again.')
        self.document, self.revision = deepcopy(document), 'local-' + uuid.uuid4().hex
        return self.revision

    def current_revision(self):
        return self.revision


def _dates(job):
    from datetime import date, timedelta
    if not job or not job.get('start'):
        return dict.fromkeys(_DATE_FIELDS, '')
    start = date.fromisoformat(job['start'][:10])
    return {'planned_start_date': start.isoformat(), 'target_finish_date': job['ready'][:10],
            'scheduled_week_of': (start - timedelta(days=start.weekday())).isoformat()}


class CalendarWorkspace:
    def __init__(self, remote, actor, path):
        self.remote, self.actor, self.path = remote, actor, Path(path)
        self.lock = threading.RLock()
        self.worker = None
        self.last_refresh = 0.0
        self.retry_at = 0.0
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if self.state.get('version') != 1 or self.state.get('owner') != actor.user_id:
                raise ValueError('This local Calendar cache belongs to a different session')
        else:
            # The only provider read required to start editing is the initial load.
            document, revision = remote.store.read()
            records = remote._read()
            visible = deepcopy(document)
            visible.pop('_desktop_sync_id', None)
            self.state = {'version': 1, 'owner': actor.user_id, 'document': visible,
                          'revision': 'local-' + uuid.uuid4().hex, 'base': document,
                          'remote_revision': revision, 'records': [asdict(r) for r in records],
                          'sequence': 0, 'pending': [], 'receipts': [], 'inflight': None, 'error': None}
            _write(self.path, self.state)
            self.last_refresh = time.monotonic()

    def _persist(self, state):
        _write(self.path, state)
        self.state = state

    def _local_service(self):
        service = copy(self.remote)
        service.store = _SnapshotStore(self.state['document'], self.state['revision'])
        records = [VehicleOperations(**r) for r in deepcopy(self.state['records'])]
        # Dates shown locally follow acknowledged local bookings, even while an
        # earlier version is uploading. They never become a stale legacy booking.
        for record in records:
            spec = self.state['document'].get('jobs', {}).get(record.vehicle_id, {})
            if spec.get('last_plan') or spec.get('released'):
                for key, value in _dates(None if spec.get('released') else spec['last_plan']).items():
                    setattr(record, key, value)
        # Calendar's durable outbox intentionally caches Operations rows, but
        # Builder-owned names and vehicle facts must always come from the live
        # project files.  This prevents the cache from resurrecting an old
        # agency name while an upload or Operations projection is pending.
        records = self.remote.with_current_builder_data(records)
        service._read = lambda: deepcopy(records)
        return service

    def _status(self):
        count = len(self.state['pending'])
        error = self.state['error']
        state = error['kind'] if error else 'syncing' if count else 'complete'
        message = error['message'] if error else f'Saved on this device · {count} change{"s" if count != 1 else ""} waiting to sync.' if count else ''
        return {'id': str(self.state['sequence']), 'state': state, 'pending_count': count,
                'completed': 0, 'total': count, 'locally_saved': True, 'message': message,
                'local_revision': self.state['revision']}

    def _payload(self, service=None):
        result = (service or self._local_service()).view(self.actor)
        actual = plan_calendar([VehicleOperations(**r) for r in self.state['records']],
                               self.state['document']['settings'], self.state['document'], today=self.remote.today())
        result['pending_date_count'] = len(self.remote.date_changes(actual['jobs'], actual['released']))
        result['save'] = self._status()
        return result

    def view(self):
        self.remote._require(self.actor, Capability.OPERATIONS_VIEW)
        with self.lock:
            # Local/test Operations is memory backed, so refresh it directly.
            # Real provider reads always run outside this lock in the worker.
            if not self.remote.cloud:
                self.state['records'] = [asdict(r) for r in self.remote._read()]
            result = self._payload()
        self.kick(refresh=True)
        return result

    def preview(self, body):
        with self.lock:
            service = self._local_service()
            if body.get('availability') is not None:
                return service.availability(self.actor, body)
            if body.get('opening') is not None:
                return service.opening(self.actor, body)
            return service.preview(self.actor, body)

    def commit(self, body):
        self.remote._require(self.actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        request_id = body.get('request_id')
        if not isinstance(request_id, str) or not request_id or len(request_id) > 100:
            raise ValueError('A local save request ID is required')
        digest = _hash(body)
        with self.lock:
            receipt = next((r for r in self.state['receipts'] if r['id'] == request_id), None)
            if receipt:
                if receipt['digest'] != digest:
                    raise ValueError('That save request ID was already used for a different change')
                return self._payload()
            service = self._local_service()
            service.save(self.actor, body)
            document, revision = service.store.read()
            state = deepcopy(self.state)
            state['document'], state['revision'] = document, revision
            # Persist the read-time Builder join into this pending snapshot so
            # a stale cache value cannot create a false provider conflict or
            # be republished while the Calendar change is in flight.
            state['records'] = [asdict(record) for record in service._read()]
            state['sequence'] += 1
            affected = {key for key in set(document.get('jobs', {})) | set(self.state['document'].get('jobs', {}))
                        if document.get('jobs', {}).get(key) != self.state['document'].get('jobs', {}).get(key)}
            if document['settings'] != self.state['document']['settings']:
                affected.update(document['jobs'])
            state['pending'].append({'sequence': state['sequence'], 'id': request_id,
                                     'sources': [r for r in state['records'] if r['vehicle_id'] in affected]})
            state['receipts'] = (state['receipts'] + [{'id': request_id, 'digest': digest}])[-500:]
            self._persist(state)
            result = self._payload()
        self.kick()
        return result

    def status(self):
        self.remote._require(self.actor, Capability.OPERATIONS_VIEW)
        with self.lock:
            result = {'ok': True, 'save': self._status()}
        self.kick()
        return result

    def retry(self):
        self.remote._require(self.actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        with self.lock:
            state = deepcopy(self.state)
            state['error'] = None
            self._persist(state)
            self.retry_at = 0
        self.kick(refresh=True)
        return self.status()

    def _resolution(self):
        self.remote._require(self.actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        with self.lock:
            snapshot = deepcopy(self.state)
        remote, revision = self.remote.store.read()
        records = self.remote._read()
        merged = _merge(snapshot['base'], snapshot['document'], remote, reviewed=True)
        proposed = plan_calendar(records, merged['settings'], merged, today=self.remote.today())
        shared = plan_calendar(records, remote['settings'], remote, today=self.remote.today())
        before = {j['id']: j for j in shared['jobs']}
        after = {j['id']: j for j in proposed['jobs']}
        changed = {key for key in set(remote.get('jobs', {})) | set(merged.get('jobs', {}))
                   if remote.get('jobs', {}).get(key) != merged.get('jobs', {}).get(key)}
        if remote['settings'] != merged['settings']:
            changed.update(merged.get('jobs', {}))
        blocked, overlaps, changes = [], {}, []
        for ident in changed:
            job = after.get(ident)
            source = next((r for r in records if r.vehicle_id == ident), None)
            spec = merged.get('jobs', {}).get(ident, {})
            if source is None and not spec.get('custom') and not spec.get('released') and spec:
                blocked.append(f'{ident} is no longer available in Operations. Remove its local booking before resolving sync.')
            if job and not job.get('historical') and source and (source.acceptance_status != 'accepted' or not job['accepted_date']
                                   or source.project_state != 'active' or source.shop_status == 'complete'
                                   or source.final_finish_status in ('delivered', 'ready_for_delivery')):
                blocked.append(f'{job["title"]} is no longer available for scheduling. Remove its local booking before resolving sync.')
            for hit in (job or {}).get('overlaps', []):
                overlaps[hit['id']] = hit
            changes.append({'id': ident, 'title': (job or before.get(ident) or {}).get('title', ident),
                            'before': self.remote._summary(before.get(ident)), 'after': self.remote._summary(job)})
        public = {'ok': True, 'changes': changes, 'settings': merged['settings'],
                  'settings_before': remote['settings'], 'settings_changed': remote['settings'] != merged['settings'],
                  'blocking_conflicts': blocked, 'overlaps': list(overlaps.values())}
        public['review_token'] = _hash([snapshot['revision'], revision, merged, _fingerprint(records), public, self.remote.today().isoformat()])
        return public, snapshot, remote, revision, records, merged

    def review_sync(self):
        return self._resolution()[0]

    def resolve_sync(self, body):
        public, snapshot, remote, revision, records, merged = self._resolution()
        if body.get('review_token') != public['review_token']:
            raise CalendarConflictError('The shared schedule changed during this review. Review the current changes again.')
        if public['blocking_conflicts'] or (public['overlaps'] and body.get('allow_overlap') is not True):
            raise ValueError('Resolve the booking conflicts or explicitly confirm the listed overlapping work')
        from datetime import datetime, timezone
        with self.lock:
            if self.worker is not None or snapshot['revision'] != self.state['revision']:
                raise CalendarConflictError('Calendar changed during this review. Review the current changes again.')
            state = deepcopy(self.state)
            merged.pop('_desktop_sync_id', None)
            merged.setdefault('history', []).append({'at': datetime.now(timezone.utc).isoformat(),
                'actor_id': self.actor.user_id, 'actor': self.actor.display_name,
                'reason': 'Reviewed shared sync conflict' + (' with overlapping work' if public['overlaps'] else ''),
                'changes': public['changes']})
            state.update(document=merged, revision='local-' + uuid.uuid4().hex, base=remote,
                         remote_revision=revision, records=[asdict(r) for r in records], inflight=None, error=None)
            state['sequence'] += 1
            state['pending'] = [{'sequence': state['sequence'], 'id': uuid.uuid4().hex, 'sources': state['records']}]
            self._persist(state)
            result = self._payload()
        self.kick()
        return result

    def kick(self, *, refresh=False):
        with self.lock:
            if self.worker is not None:
                return
            error = self.state['error']
            if error and (error['kind'] == 'conflict' or time.monotonic() < self.retry_at):
                return
            if not self.state['pending'] and (not refresh or time.monotonic() - self.last_refresh < 5):
                return
            self.worker = threading.Thread(target=self._run, daemon=True, name='calendar-outbox')
            self.worker.start()

    def _snapshot(self):
        with self.lock:
            if self.state['inflight']:
                return deepcopy(self.state['inflight'])
            if not self.state['pending']:
                return None
            snapshot = {key: deepcopy(self.state[key]) for key in ('document', 'base', 'records', 'sequence')}
            sources = {r['vehicle_id']: r for r in snapshot['records']}
            for pending in self.state['pending']:
                sources.update({r['vehicle_id']: r for r in pending['sources']})
            snapshot['records'] = list(sources.values())
            snapshot['id'] = uuid.uuid4().hex
            state = deepcopy(self.state)
            state['inflight'] = snapshot
            self._persist(state)
            return snapshot

    def _validate(self, snapshot, merged, records):
        affected = {key for key in set(snapshot['base'].get('jobs', {})) | set(snapshot['document'].get('jobs', {}))
                    if snapshot['base'].get('jobs', {}).get(key) != snapshot['document'].get('jobs', {}).get(key)}
        if snapshot['base']['settings'] != snapshot['document']['settings']:
            affected.update(merged['jobs'])
        before = {r['vehicle_id']: VehicleOperations(**r) for r in snapshot['records']}
        fresh = {r.vehicle_id: r for r in records}
        for ident in affected:
            if ident not in before:
                continue  # Calendar-only custom booking.
            old, new = before[ident], fresh.get(ident)
            if new is None or _fingerprint([replace(old, **dict.fromkeys(_DATE_FIELDS, ''))]) != _fingerprint([replace(new, **dict.fromkeys(_DATE_FIELDS, ''))]):
                raise CalendarConflictError('Vehicle scheduling details changed while your edit was waiting to sync. Your local changes are retained; review the vehicle before retrying sync.')
            actual_dates = {key: getattr(new, key) for key in _DATE_FIELDS}
            expected_dates = [{key: getattr(old, key) for key in _DATE_FIELDS}]
            for doc in (snapshot['base'], merged):
                spec = doc.get('jobs', {}).get(ident, {})
                if spec.get('last_plan') or spec.get('released'):
                    expected_dates.append(_dates(None if spec.get('released') else spec['last_plan']))
            if actual_dates not in expected_dates:
                raise CalendarConflictError('Operations dates changed on another device. Your local changes are retained; review the vehicle before retrying sync.')
        planned = plan_calendar(records, merged['settings'], merged, today=self.remote.today())
        approved = plan_calendar(records, snapshot['document']['settings'], snapshot['document'], today=self.remote.today())
        def overlaps(plan, ident):
            job = next((j for j in plan['jobs'] if j['id'] == ident), {})
            ids = {j['id'] for j in job.get('overlaps', [])}
            return {_hash({k: j[k] for k in ('id', 'team_ids', 'segments')}) for j in plan['jobs'] if j['id'] in ids}
        for ident in affected:
            if overlaps(planned, ident) - overlaps(approved, ident):
                raise CalendarConflictError('Another device booked this team during the same hours. Your local changes are retained; review the overlapping bookings before retrying sync.')

    def _sync(self, snapshot, *, retry_race=True):
        self.remote._require(self.actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        remote_document, revision = self.remote.store.read()
        records = self.remote._read()
        if remote_document.get('_desktop_sync_id') == snapshot['id']:
            merged = remote_document  # Recover a write whose acknowledgement was lost.
        else:
            merged = _merge(snapshot['base'], snapshot['document'], remote_document)
        self._validate(snapshot, merged, records)
        if remote_document.get('_desktop_sync_id') != snapshot['id']:
            merged['_desktop_sync_id'] = snapshot['id']
            try:
                revision = self.remote.store.write(merged, revision)
            except CalendarConflictError:
                if not retry_race:
                    raise
                # One bounded reread/rebase for a write racing another device.
                # The same field/occupancy checks run again; never drop If-Match.
                return self._sync(snapshot, retry_race=False)
        publisher = copy(self.remote)
        if not self.remote.cloud:
            publisher.store = _SnapshotStore(merged, revision)
        payload = publisher._payload(merged, revision, records)
        publisher.publish_dates(self.actor, payload, 'calendar-outbox-' + snapshot['id'], on_progress=lambda _: None)
        records = self.remote._read()
        with self.lock:
            state = deepcopy(self.state)
            # Rebase edits accepted DURING upload onto the successfully shared
            # snapshot. Never replace a newer local delete with an older upload.
            state['document'] = _merge(snapshot['document'], state['document'], merged)
            state['document'].pop('_desktop_sync_id', None)
            if state['document'] != self.state['document']:
                state['revision'] = 'local-' + uuid.uuid4().hex
            state['base'], state['remote_revision'] = merged, revision
            state['records'] = [asdict(r) for r in records]
            state['pending'] = [p for p in state['pending'] if p['sequence'] > snapshot['sequence']]
            state['inflight'], state['error'] = None, None
            self._persist(state)

    def _refresh(self):
        document, revision = self.remote.store.read()
        records = self.remote._read()
        with self.lock:
            # A user may have committed while this provider read was in flight.
            # Leave the outbox's base intact; its guarded merge handles that case.
            if self.state['pending']:
                return
            state = deepcopy(self.state)
            visible = deepcopy(document)
            visible.pop('_desktop_sync_id', None)
            if state['document'] != visible:
                state['revision'] = 'local-' + uuid.uuid4().hex
            state.update(document=visible, base=document, remote_revision=revision,
                         records=[asdict(r) for r in records], error=None)
            self._persist(state)

    def _run(self):
        try:
            while True:
                snapshot = self._snapshot()
                if snapshot is None:
                    self._refresh()
                    break
                self._sync(snapshot)
        except CalendarConflictError as exc:
            with self.lock:
                state = deepcopy(self.state)
                state['error'] = {'kind': 'conflict', 'message': str(exc)}
                self._persist(state)
        except Exception:
            with self.lock:
                state = deepcopy(self.state)
                state['error'] = {'kind': 'failed', 'message': 'Changes are saved on this device. Sync could not finish; it will retry automatically. You can keep editing.'}
                self._persist(state)
                self.retry_at = time.monotonic() + 15
        finally:
            with self.lock:
                self.worker = None
                self.last_refresh = time.monotonic()


def workspace(service, actor):
    config = getattr(service.bundle.storage, '_config', None)
    binding = [service.cloud, actor.user_id] + [getattr(config, key, '') for key in
        ('tenant_id', 'sharepoint_site_id', 'sharepoint_drive_id', 'operations_list_id')]
    name = ('cloud-' if service.cloud else 'local-') + _hash(binding)[:20] + '.json'
    path = service.paths.workspace_dir / 'calendar' / 'outbox' / name
    with _REGISTRY_LOCK:
        result = _REGISTRY.get(str(path))
        if result is None:
            result = CalendarWorkspace(service, actor, path)
            _REGISTRY[str(path)] = result
        else:
            with result.lock:
                result.remote, result.actor = service, actor
        return result
