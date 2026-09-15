"""Replica/outbox contracts, with slow and conflicting fake providers."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
import threading
import time
import uuid

import pytest

from dtm_buildsheet.app.adapters.calendar_store import CalendarConflictError
from dtm_buildsheet.app.adapters.wiring import build_local_bundle
from dtm_buildsheet.app.services.calendar_service import CalendarService
from dtm_buildsheet.app.services.calendar_workspace import CalendarWorkspace
from dtm_buildsheet.domain.operations_models import AcceptanceStatus, OperationsActor, VehicleOperations
from dtm_buildsheet.paths import AppPaths

ACTOR = OperationsActor('owner', 'Owner', frozenset({'AppAdmin'}))


class SharedCalendar:
    def __init__(self):
        self.content = None
        self.revision = ''
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.error_after_write = False
        self.lock = threading.RLock()

    def read_versioned_text(self, path):
        with self.lock:
            if self.content is None:
                raise FileNotFoundError(path)
            return self.content, self.revision

    def read_revision(self, path):
        return self.read_versioned_text(path)[1]

    def write_versioned_text(self, path, content, expected):
        self.entered.set()
        assert self.release.wait(5), 'fake provider remained blocked'
        with self.lock:
            self.calls += 1
            if expected != self.revision:
                raise CalendarConflictError('Shared ETag changed')
            self.content, self.revision = content, str(int(self.revision or '0') + 1)
            if self.error_after_write:
                self.error_after_write = False
                raise OSError('Provider acknowledgement was lost; do not expose secret URL')
            return self.revision


@pytest.fixture
def setup(tmp_path):
    paths = replace(AppPaths(), workspace_dir=tmp_path, workspace_projects_dir=tmp_path / 'projects')
    shared = SharedCalendar()
    bundle = replace(build_local_bundle(), storage=shared)
    for ident in ('v1', 'v2'):
        bundle.operations._records[ident] = VehicleOperations(vehicle_id=ident, project_id=ident,
            title=ident, agency_name=ident, acceptance_status=AcceptanceStatus.ACCEPTED,
            accepted_at='2026-09-01', parts_status='parts_ready', vehicle_availability_status='at_dtm', build_finalized=True)
    service = CalendarService(paths, bundle, cloud=True, clock=lambda: date(2026, 9, 14))
    local = CalendarWorkspace(service, ACTOR, tmp_path / 'outbox.json')
    yield local, service, shared
    shared.release.set()
    if local.worker:
        local.worker.join(5)


def request(local, edit=None, **extra):
    view = local.view()
    body = {'revision': view['revision'], 'source_revision': view['source_revision'],
            'edit': edit, 'reason': 'Booking confirmed', **extra}
    preview = local.preview(body)
    return {**body, 'preview_token': preview['preview_token'], 'request_id': uuid.uuid4().hex}


def book(local, ident='v1', **extra):
    return request(local, {'id': ident, 'team_id': 'team-david', 'hours': 14.4, **extra})


def finish(local):
    worker = local.worker
    if worker:
        worker.join(5)
    assert not local.worker or not local.worker.is_alive()
    assert local.status()['save']['state'] == 'complete', local.state['error']


def test_book_remove_rebook_is_fast_and_durable_while_cloud_is_blocked(setup):
    local, remote, shared = setup
    shared.release.clear()
    first = local.commit(book(local))
    assert shared.entered.wait(2)
    begin = time.monotonic()
    removed = local.commit(request(local, remove_project='v1', reason='Removed from schedule'))
    assert not removed['plan']['jobs']
    assert next(j for j in removed['plan']['queue'] if j['id'] == 'v1')['unscheduled']
    final = local.commit(book(local, team_id='team-josh'))
    assert time.monotonic() - begin < .5  # Provider is still blocked for up to 5 seconds.
    assert final['plan']['jobs'][0]['team_id'] == 'team-josh'
    assert final['save']['pending_count'] == 3
    disk = json.loads(local.path.read_text())
    assert len(disk['pending']) == 3 and disk['document']['jobs']['v1']['team_id'] == 'team-josh'
    assert shared.content is None
    shared.release.set()
    finish(local)
    assert remote.view(ACTOR)['plan']['jobs'][0]['team_id'] == 'team-josh'
    assert len(remote.view(ACTOR)['history']) == 3
    assert first['revision'] != final['revision']


def test_older_upload_never_restores_a_locally_deleted_booking(setup):
    local, remote, shared = setup
    shared.release.clear()
    local.commit(book(local))
    assert shared.entered.wait(2)
    local.commit(request(local, remove_project='v1', reason='Removed from schedule'))
    shared.release.set()
    finish(local)
    assert not local.view()['plan']['jobs'] and not remote.view(ACTOR)['plan']['jobs']
    assert not remote.bundle.operations.get_vehicle('v1').planned_start_date
    assert not remote.bundle.operations.get_vehicle('v1').target_finish_date


def test_duplicate_delivery_does_not_apply_a_local_edit_twice(setup):
    local, _, shared = setup
    shared.release.clear()
    body = book(local)
    first = local.commit(body)
    again = local.commit(body)
    assert first['revision'] == again['revision']
    assert len(local.state['pending']) == 1
    with pytest.raises(ValueError, match='different change'):
        local.commit({**body, 'reason': 'different'})


def test_restart_preserves_queued_changes_and_revalidates_before_publishing(setup, monkeypatch):
    local, remote, shared = setup
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    resumed = CalendarWorkspace(remote, ACTOR, local.path)
    assert resumed.view()['plan']['jobs'][0]['id'] == 'v1'
    finish(resumed)
    assert shared.calls == 1


def test_lost_shared_acknowledgement_recovers_without_duplicate_publication(setup):
    local, remote, shared = setup
    shared.error_after_write = True
    local.commit(book(local))
    worker = local.worker
    if worker:
        worker.join(5)
    assert local.state['error']['kind'] == 'failed'
    assert 'secret' not in local.state['error']['message']
    resumed = CalendarWorkspace(remote, ACTOR, local.path)
    resumed.retry()
    finish(resumed)
    assert shared.calls == 1
    assert len(remote.bundle.operations.list_events('v1')) == 1


def remote_book(remote, ident, team='team-josh'):
    view = remote.view(ACTOR)
    body = {'revision': view['revision'], 'source_revision': view['source_revision'],
            'edit': {'id': ident, 'team_id': team, 'hours': 14.4}, 'reason': 'Other scheduler'}
    preview = remote.preview(ACTOR, body)
    return remote.save(ACTOR, {**body, 'preview_token': preview['preview_token']})


def test_disjoint_shared_change_is_merged_without_losing_either_booking(setup, monkeypatch):
    local, remote, shared = setup
    real_kick = local.kick
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    remote_book(remote, 'v2')
    monkeypatch.setattr(local, 'kick', real_kick)
    local.kick()
    finish(local)
    assert {j['id'] for j in remote.view(ACTOR)['plan']['jobs']} == {'v1', 'v2'}
    assert {j['id'] for j in local.view()['plan']['jobs']} == {'v1', 'v2'}


def test_concurrent_shared_occupancy_conflict_keeps_local_change_visible(setup, monkeypatch):
    local, remote, _ = setup
    real_kick = local.kick
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    remote_book(remote, 'v2', 'team-david')
    monkeypatch.setattr(local, 'kick', real_kick)
    local.kick()
    worker = local.worker
    if worker:
        worker.join(5)
    assert local.status()['save']['state'] == 'conflict'
    assert [j['id'] for j in local.view()['plan']['jobs']] == ['v1']
    assert [j['id'] for j in remote.view(ACTOR)['plan']['jobs']] == ['v2']
    assert len(local.state['pending']) == 1


def test_material_operations_change_does_not_publish_an_outdated_booking(setup, monkeypatch):
    local, remote, shared = setup
    real_kick = local.kick
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    remote.bundle.operations._records['v1'].acceptance_status = AcceptanceStatus.NOT_ACCEPTED
    monkeypatch.setattr(local, 'kick', real_kick)
    local.kick()
    worker = local.worker
    if worker:
        worker.join(5)
    assert local.status()['save']['state'] == 'conflict'
    assert shared.content is None and local.view()['plan']['jobs']


def test_disk_failure_is_not_reported_as_a_successful_local_save(setup, monkeypatch):
    import dtm_buildsheet.app.services.calendar_workspace as module
    local, _, _ = setup
    body = book(local)
    old = deepcopy(local.state)
    monkeypatch.setattr(module, '_write', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        local.commit(body)
    assert local.state == old


def test_sync_conflict_can_be_reviewed_and_explicitly_resolved(setup, monkeypatch):
    local, remote, _ = setup
    real_kick = local.kick
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    remote_book(remote, 'v2', 'team-david')
    monkeypatch.setattr(local, 'kick', real_kick)
    local.kick()
    worker = local.worker
    if worker:
        worker.join(5)
    review = local.review_sync()
    assert review['overlaps'] and not review['blocking_conflicts']
    with pytest.raises(ValueError, match='explicitly confirm'):
        local.resolve_sync({'review_token': review['review_token']})
    local.resolve_sync({'review_token': review['review_token'], 'allow_overlap': True})
    finish(local)
    assert len(remote.view(ACTOR)['plan']['jobs']) == 2
    assert remote.view(ACTOR)['history'][-1]['reason'].endswith('with overlapping work')


def test_resolution_ticket_cannot_overwrite_a_new_local_change(setup, monkeypatch):
    local, _, _ = setup
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    review = local.review_sync()
    local.commit(request(local, remove_project='v1', reason='Removed'))
    with pytest.raises(CalendarConflictError, match='changed during'):
        local.resolve_sync({'review_token': review['review_token']})
    assert not local.view()['plan']['jobs']


def test_authorization_is_rechecked_before_queued_publication(setup, monkeypatch):
    local, remote, shared = setup
    real_kick = local.kick
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    remote.authorize = lambda actor, capability: False
    monkeypatch.setattr(local, 'kick', real_kick)
    local.kick()
    worker = local.worker
    if worker:
        worker.join(5)
    assert shared.content is None and len(local.state['pending']) == 1
    assert local.state['error']


def test_partial_date_publication_resumes_without_duplicate_events(setup, monkeypatch):
    from dtm_buildsheet.app.services.operations_service import OperationsService
    local, remote, shared = setup
    real_kick = local.kick
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    local.commit(book(local, 'v2', team_id='team-josh'))
    original = OperationsService.change_schedule

    def fail_second(self, **kwargs):
        if kwargs['vehicle_id'] == 'v2':
            raise OSError('temporary provider outage')
        return original(self, **kwargs)

    monkeypatch.setattr(OperationsService, 'change_schedule', fail_second)
    monkeypatch.setattr(local, 'kick', real_kick)
    local.kick()
    worker = local.worker
    if worker:
        worker.join(5)
    assert local.state['error']['kind'] == 'failed'
    assert len(remote.bundle.operations.list_events('v1')) == 1
    assert not remote.bundle.operations.list_events('v2')
    monkeypatch.setattr(OperationsService, 'change_schedule', original)
    local.retry()
    finish(local)
    assert shared.calls == 1
    assert len(remote.bundle.operations.list_events('v1')) == 1
    assert len(remote.bundle.operations.list_events('v2')) == 1


def test_missing_operations_record_requires_removal_before_resolution(setup, monkeypatch):
    local, remote, _ = setup
    real_kick = local.kick
    monkeypatch.setattr(local, 'kick', lambda **kwargs: None)
    local.commit(book(local))
    del remote.bundle.operations._records['v1']
    assert local.review_sync()['blocking_conflicts']
    local.commit(request(local, remove_project='v1', reason='Removed missing vehicle'))
    review = local.review_sync()
    assert not review['blocking_conflicts']
    local.resolve_sync({'review_token': review['review_token']})
    monkeypatch.setattr(local, 'kick', real_kick)
    local.kick()
    finish(local)
    assert not remote.view(ACTOR)['plan']['jobs']
