from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime

import pytest

from dtm_buildsheet.app.adapters.calendar_store import CalendarConflictError, CalendarStore
from dtm_buildsheet.app.adapters.wiring import build_local_bundle
from dtm_buildsheet.app.services.calendar_service import CalendarService
from dtm_buildsheet.app.services.operations_service import OperationsAuthorizationError
from dtm_buildsheet.domain.calendar_planning import default_calendar_settings, plan_calendar, validate_settings, work_segments
from dtm_buildsheet.domain.operations_models import AcceptanceStatus, OperationsActor, VehicleOperations, VehicleAvailabilityStatus
from dtm_buildsheet.paths import AppPaths

TODAY = date(2026, 9, 14)
ADMIN = OperationsActor('owner', 'Owner', frozenset({'AppAdmin'}))
SALES = OperationsActor('sales', 'Sales', frozenset({'BuilderEditor'}))


def vehicle(ident='v1', project='p1', **kw):
    return VehicleOperations(vehicle_id=ident, project_id=project, title=ident, agency_name='Agency',
        acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at='2026-09-01T12:00:00Z',
        parts_status='parts_ready', vehicle_availability_status=VehicleAvailabilityStatus.AT_DTM,
        build_finalized=True, **kw)


def plan(records, saved=None, settings=None):
    return plan_calendar(records, settings or default_calendar_settings(), saved or {}, today=TODAY)


def reservation(ident='v1', team='team-david', **kw):
    return {'id':ident, 'team_id':team, '_stage':True, **kw}


def staged(records, jobs, settings=None):
    return plan(records, {'jobs': {j['id']:j for j in jobs}}, settings)


def test_reads_show_acceptance_queue_without_reserving_or_assigning():
    early=replace(vehicle('z'),accepted_at='2026-08-01T12:00:00Z')
    late=replace(vehicle('a','p2'),accepted_at='2026-09-05T12:00:00Z')
    missing=replace(vehicle('missing'),accepted_at='')
    r=plan([late,missing,early])
    assert r['jobs']==[]
    assert [j['id'] for j in r['queue']]==['z','a']
    assert all('team_id' not in j for j in r['queue'])
    assert r['needs_review'][0]['id']=='missing'


def test_observation_time_never_supplies_missing_acceptance():
    r=replace(vehicle(),accepted_at='',qbo_checked_at='2026-09-04T00:00:00Z')
    assert not plan([r])['queue']
    r.qbo_estimate_accepted_at='2026-07-01T12:00:00Z'
    assert plan([r])['queue'][0]['accepted_date']=='2026-07-01'


def test_capacity_and_finishing_are_separate():
    j=staged([vehicle()], [reservation(hours=14.4)])['jobs'][0]
    assert j['end']=='2026-09-14T16:00'
    assert j['ready']=='2026-09-15T12:00'
    assert j['promised_start']==j['promised_ready']==''
    segments,end=work_segments(datetime(2026,9,18,15),4,8,set(),8)
    assert [s['date'] for s in segments]==['2026-09-18','2026-09-21']
    assert end==datetime(2026,9,21,11)


def test_fixed_overlap_stays_visible_instead_of_moving_booking():
    r=staged([vehicle('a'),vehicle('b')],[reservation('a',hours=16,start_date='2026-09-14'),reservation('b',hours=16,start_date='2026-09-14')])
    assert {j['start'] for j in r['jobs']}=={'2026-09-14T08:00'}
    assert all(j['conflicts'] for j in r['jobs'])


def test_next_opening_uses_gap_before_later_fixed_booking():
    from dtm_buildsheet.domain.calendar_planning import calculate_opening
    fixed=staged([vehicle()], [reservation(hours=14.4,start_date='2026-09-18')])['jobs']
    start=calculate_opening(default_calendar_settings(),{'team_id':'team-david','hours':14.4},fixed,earliest=datetime(2026,9,14,8))
    assert start==datetime(2026,9,14,8)


def test_joint_work_occupies_both_teams_and_retains_partial_day_opening():
    r=staged([vehicle('a'),vehicle('b')],[reservation('a',team_ids=['team-david','team-josh'],hours=28.8),reservation('b',team='team-josh',hours=7.2)])
    a,b=r['jobs']
    assert a['end']=='2026-09-14T16:00'
    assert b['start']=='2026-09-15T08:00'
    assert not b['conflicts']


def test_readiness_does_not_yield_or_assign_a_different_team():
    blocked=replace(vehicle(),parts_status='ordered')
    j=staged([blocked],[reservation(hours=8)])['jobs'][0]
    assert j['start'].startswith('2026-09-14')
    assert 'Waiting on parts' in j['blocked']
    assert j['team_id']=='team-david'


def test_delivery_deadline_remains_independent():
    r=vehicle(vehicle_available_date='2026-06-01',parts_received_at='2026-06-05T12:00:00Z')
    original=deepcopy(r)
    j=staged([r],[reservation(start_date='2026-12-01')])['jobs'][0]
    assert j['deadline']=='2026-08-04' and 'Past delivery deadline' in j['warnings']
    assert r==original


def test_unassigned_legacy_booking_blocks_quoteable_capacity():
    r=plan([vehicle(planned_start_date='2026-10-01')])
    assert not r['jobs'] and r['needs_review'][0]['legacy_booking']


@pytest.mark.parametrize('key,value', [('buffer_percent',float('nan')),('hours_per_day',0),('finishing_hours',-1)])
def test_invalid_capacity_rejected(key,value):
    s=default_calendar_settings();s[key]=value
    with pytest.raises(ValueError):validate_settings(s)


@pytest.fixture
def service(tmp_path):
    paths=replace(AppPaths(),workspace_dir=tmp_path,workspace_projects_dir=tmp_path/'projects')
    bundle=build_local_bundle();bundle.operations._records['v1']=vehicle()
    return CalendarService(paths,bundle,clock=lambda:TODAY)


def reviewed(service,edit=None,**extra):
    view=service.view(ADMIN)
    body={'revision':view['revision'],'source_revision':view['source_revision'], 'reason':'Reviewed fixture change', **extra}
    if edit is not None:
        body['edit']=edit
    elif 'settings' not in extra:
        # Test convenience submits explicit vehicle choices, never a bulk auto-plan save.
        queue=view['plan']['queue']+[j for j in view['plan']['needs_review'] if j.get('legacy_booking')]
        body['edits']=[{'id':j['id'],'team_id':'team-michelle'} for j in queue]
    p=service.preview(ADMIN,body)
    return {**body,'preview_token':p['preview_token']}


def settings_save(service,settings):
    return service.save_settings(ADMIN,reviewed(service,settings=settings))


def test_view_and_preview_do_not_write(service):
    service.view(SALES)
    service.preview(ADMIN,{k:v for k,v in reviewed(service).items() if k!='preview_token'})
    assert not service.store.path.exists()
    assert service.bundle.operations.get_vehicle('v1').revision==0


def test_settings_cannot_rename_team_identity_or_delete_history(service):
    data=service.view(ADMIN);s=data['settings'];s['teams'][2]['name']='Michelle updated'
    settings_save(service,s)
    data=service.view(ADMIN);assert data['settings']['teams'][2]['name']=='Michelle updated'
    s['teams'].pop()
    with pytest.raises(ValueError,match='Retire'):
        settings_save(service,s)


def test_saved_hours_survive_team_default_changes(service):
    saved=service.save(ADMIN,reviewed(service))
    s=saved['settings'];s['teams'][2]['build_hours']=80
    settings_save(service,s)
    assert service.view(ADMIN)['plan']['jobs'][0]['hours']==46


def test_reassigned_team_default_is_frozen_when_hours_are_left_blank(service):
    service.save(ADMIN,reviewed(service))
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':None}))
    assert saved['plan']['jobs'][0]['hours']==66
    settings=saved['settings'];settings['teams'][0]['build_hours']=100
    settings_save(service,settings)
    assert service.view(ADMIN)['plan']['jobs'][0]['hours']==66


def test_calendar_cannot_create_a_separate_vehicle_delivery_promise(service):
    with pytest.raises(ValueError,match='Operations delivery deadline'):
        reviewed(service,{'id':'v1','team_id':'team-michelle','promised_date':'2026-12-31'})


def test_stale_edits_and_changed_operations_rejected(service):
    body=reviewed(service)
    service.save(ADMIN,body)
    with pytest.raises(CalendarConflictError):service.save(ADMIN,body)
    body=reviewed(service);service.bundle.operations._records['v1'].must_deliver_override_date='2026-10-30'
    with pytest.raises(CalendarConflictError):service.save(ADMIN,body)


def test_poll_metadata_does_not_invalidate_booking_ticket_and_publish_uses_fresh_revision(service):
    body=reviewed(service)
    service.bundle.operations._records['v1'].qbo_checked_at='2026-09-14T20:00:00Z'
    service.bundle.operations._records['v1'].revision+=1
    saved=service.save(ADMIN,body)
    assert saved['plan']['jobs'][0]['revision']==1
    service.publish_dates(ADMIN,saved,'metadata-refresh',on_progress=lambda _:None)
    assert service.bundle.operations.get_vehicle('v1').revision==2


@pytest.mark.parametrize('field,value', [('shop_status','in_progress'),('parts_status','ordered'),
    ('vehicle_availability_status','waiting_on_agency'),('target_finish_date','2026-10-15'),
    ('must_deliver_override_date','2026-10-20'),('accepted_at','2026-08-20')])
def test_booking_ticket_still_protects_material_operations_changes(service,field,value):
    body=reviewed(service);before=service.store.read()
    setattr(service.bundle.operations._records['v1'],field,value)
    with pytest.raises(CalendarConflictError):service.save(ADMIN,body)
    assert service.store.read()==before


def test_refreshing_preview_reads_current_operations_but_keeps_save_protection(service):
    view=service.view(ADMIN)
    body={'revision':view['revision'],'source_revision':view['source_revision'],
          'edit':{'id':'v1','team_id':'team-david'},'reason':'Booking confirmed','refresh_operations':True}
    service.bundle.operations._records['v1'].must_deliver_override_date='2026-10-20'
    preview=service.preview(ADMIN,body)
    assert preview['source_revision']!=view['source_revision']
    assert preview['plan']['jobs'][0]['deadline']=='2026-10-20'
    service.bundle.operations._records['v1'].must_deliver_override_date='2026-10-21'
    with pytest.raises(CalendarConflictError):service.save(ADMIN,{**body,'preview_token':preview['preview_token']})


def test_preview_token_is_bound_to_job_changes(service):
    body=reviewed(service)
    body.pop('edits',None)
    body['edit']={'id':'v1','team_id':'team-david','hours':10}
    with pytest.raises(CalendarConflictError):service.save(ADMIN,body)


def test_sales_can_read_but_cannot_edit_or_apply_dates(service):
    assert service.view(SALES)['ok']
    for method,body in [('preview',{}),('save_settings',{}),('apply_dates',{})]:
        with pytest.raises(OperationsAuthorizationError):getattr(service,method)(SALES,body)


def test_apply_date_keeps_deadline_and_uses_operations_event(service):
    service.bundle.operations._records['v1'].must_deliver_override_date='2026-12-01'
    saved=service.save(ADMIN,reviewed(service));j=saved['plan']['jobs'][0]
    service.apply_dates(ADMIN,{'revision':saved['revision'],'vehicle_id':'v1','expected_revision':j['revision'],
                              'dates':[j['start'][:10],j['ready'][:10]],'request_id':'apply-1'})
    record=service.bundle.operations.get_vehicle('v1')
    assert record.planned_start_date==j['start'][:10]
    assert record.target_finish_date==j['ready'][:10]
    assert record.must_deliver_override_date=='2026-12-01'
    assert len(service.bundle.operations.list_events('v1'))==1


def test_custom_job_and_retired_team_validation(service):
    edit={'id':'job-custom','title':'Off-site repair','team_id':'team-michelle','kind':'offsite','hours':12}
    saved=service.save(ADMIN,reviewed(service,edit))
    assert any(j['custom'] for j in saved['plan']['jobs'])
    with pytest.raises(ValueError):reviewed(service,{**edit,'hours':None})


def test_multi_vehicle_date_mirror_does_not_reorder_queue(service):
    service.bundle.operations._records={f'v{i}':vehicle(f'v{i}') for i in range(3)}
    edit={'id':'v0','team_id':'team-david','hours':66,'start_date':'2031-01-06','pinned':True}
    saved=service.save(ADMIN,reviewed(service,edit))
    for j in saved['plan']['jobs']:
        service.apply_dates(ADMIN,{'revision':saved['revision'],'vehicle_id':j['id'],'expected_revision':j['revision'],
                                  'dates':[j['start'][:10],j['ready'][:10]],'request_id':'mirror-'+j['id']})
    after=service.view(ADMIN)['plan']['jobs']
    assert [(j['id'],j['start'],j['ready']) for j in after]==[(j['id'],j['start'],j['ready']) for j in saved['plan']['jobs']]


def test_existing_manual_start_remains_fixed_after_first_save(service):
    service.bundle.operations._records['v1'].planned_start_date='2026-10-01'
    saved=service.save(ADMIN,reviewed(service))
    assert saved['plan']['jobs'][0]['pinned']
    assert saved['plan']['jobs'][0]['start'].startswith('2026-10-01')


def test_cloud_calendar_save_never_retries_without_revision():
    from dtm_buildsheet.app.adapters.cloud.config import CloudConfig
    from dtm_buildsheet.app.adapters.cloud.sharepoint_graph_provider import SharePointGraphProvider
    from unittest.mock import Mock
    http=Mock();http.put.return_value.status_code=412
    config=Mock(spec=CloudConfig);config.sharepoint_site_id='site';config.sharepoint_drive_id='drive'
    provider=SharePointGraphProvider(config,lambda:'test-token',session=http)
    with pytest.raises(CalendarConflictError):
        provider.write_versioned_text('Settings/calendar_plan.json','{}','old-etag')
    assert http.put.call_count==1
    assert http.put.call_args.kwargs['headers']['If-Match']=='old-etag'


def test_cloud_calendar_read_rejects_mixed_versions():
    from dtm_buildsheet.app.adapters.cloud.config import CloudConfig
    from dtm_buildsheet.app.adapters.cloud.sharepoint_graph_provider import SharePointGraphProvider
    from unittest.mock import Mock
    http=Mock();responses=[]
    for payload in [{'eTag':'before'}, {}, {'eTag':'after'}]:
        r=Mock();r.status_code=200;r.json.return_value=payload;r.content=b'{}';responses.append(r)
    http.get.side_effect=responses
    config=Mock(spec=CloudConfig);config.sharepoint_site_id='site';config.sharepoint_drive_id='drive'
    provider=SharePointGraphProvider(config,lambda:'test-token',session=http)
    with pytest.raises(CalendarConflictError):provider.read_versioned_text('Settings/calendar_plan.json')


def test_calendar_route_denies_sales_mutation(service, monkeypatch):
    from dtm_buildsheet.app.adapters import wiring
    from dtm_buildsheet.app.adapters.interfaces import UserIdentity
    from dtm_buildsheet.app.routes.calendar import route_calendar
    from tests.contract.harness import call_route
    from unittest.mock import Mock
    identity=Mock();identity.current_user.return_value=UserIdentity('sales','Sales','sales@example.invalid','local',roles=frozenset({'BuilderEditor'}))
    monkeypatch.setattr(wiring,'get_active_bundle',lambda:replace(service.bundle,identity=identity))
    monkeypatch.setattr(wiring,'_cloud_flag_enabled',lambda:False)
    response=call_route(route_calendar,'POST','/api/calendar/settings',{},service.paths)
    assert response[0]==403


def test_completed_jobs_keep_their_calendar_history_without_using_capacity(service):
    from dtm_buildsheet.domain.operations_models import ProjectState
    saved=service.save(ADMIN,reviewed(service))
    original=saved['plan']['jobs'][0]
    service.bundle.operations._records['v1'].project_state=ProjectState.COMPLETED
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    jobs=service.view(ADMIN)['plan']['jobs']
    historical=next(j for j in jobs if j['id']=='v1')
    assert historical['historical']
    assert historical['start']==original['start']
    assert service.view(ADMIN)['plan']['queue'][0]['id']=='v2'


def test_custom_job_can_be_cancelled_without_deleting_saved_record(service):
    edit={'id':'job-custom','title':'Service','team_id':'team-michelle','kind':'service','hours':8}
    service.save(ADMIN,reviewed(service,edit))
    saved=service.save(ADMIN,reviewed(service,{'id':'job-custom','team_id':'team-michelle','cancelled':True}))
    assert not any(j['id']=='job-custom' for j in saved['plan']['jobs'])
    assert saved['saved_jobs']['job-custom']['cancelled']


def test_qbo_acceptance_without_date_does_not_use_observation_timestamp():
    r=replace(vehicle(),acceptance_source='qbo',qbo_estimate_status='Accepted',qbo_estimate_accepted_at='')
    assert plan([r])['needs_review'][0]['reason']=='Acceptance date needed'
    r.qbo_estimate_accepted_at='2026-08-03'
    assert plan([r])['queue'][0]['accepted_date']=='2026-08-03'


def test_legacy_calendar_dates_do_not_override_shared_acceptance_record(service):
    r=service.bundle.operations._records['v1'];r.qbo_estimate_status='Accepted';r.qbo_estimate_accepted_at='2026-08-10'
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-michelle',
        'accepted_date_source':'manual','accepted_date':'2026-07-02'}))
    assert saved['plan']['jobs'][0]['accepted_date']=='2026-09-01'
    assert service.bundle.operations.get_vehicle('v1').accepted_at=='2026-09-01T12:00:00Z'
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-michelle','accepted_date_source':'qbo'}))
    assert saved['plan']['jobs'][0]['accepted_date']=='2026-09-01'
    assert 'accepted_date' not in saved['saved_jobs']['v1']


def test_new_acceptances_join_saved_queue_without_a_save_on_read(service):
    service.save(ADMIN,reviewed(service))
    before=service.store.read()[1]
    service.bundle.operations._records['v2']=replace(vehicle('v2','p2'),accepted_at='2026-09-10T12:00:00Z')
    view=service.view(ADMIN)
    assert [j['id'] for j in view['plan']['jobs']]==['v1']
    assert [j['id'] for j in view['plan']['queue']]==['v2']
    assert service.store.read()[1]==before


def test_background_save_returns_before_slow_upload_and_reports_progress(service,monkeypatch):
    from threading import Event
    from dtm_buildsheet.app.services import calendar_save_jobs as jobs
    entered,release=Event(),Event()
    original=service.store.write
    def slow_write(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(service.store,'write',slow_write)
    body={**reviewed(service),'request_id':'background-1'}
    try:
        result=jobs.start(service,ADMIN,body)
        assert result['save']['state']=='saving'
        assert entered.wait(2)
        assert jobs.status(service,ADMIN)['save']['completed']==0
        assert jobs.start(service,ADMIN,body)['save']['id']==result['save']['id']
        with pytest.raises(CalendarConflictError):
            jobs.start(service,ADMIN,{**body,'request_id':'another'})
        worker=jobs._THREADS[str(jobs._path(service))]
    finally:
        release.set()
    worker.join(5)
    final=jobs.status(service,ADMIN)['save']
    assert final['state']=='complete'
    assert final['completed']==final['total']==1
    assert service.bundle.operations.get_vehicle('v1').planned_start_date


def test_background_failure_preserves_prior_updates_and_retry_only_publishes_remaining(service,monkeypatch):
    from dtm_buildsheet.app.services import calendar_save_jobs as jobs
    from dtm_buildsheet.app.services.operations_service import OperationsService
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    original=OperationsService.change_schedule
    def fail_second(self,**kwargs):
        if kwargs['vehicle_id']=='v2':raise RuntimeError('must not expose private error')
        return original(self,**kwargs)
    monkeypatch.setattr(OperationsService,'change_schedule',fail_second)
    body={**reviewed(service),'request_id':'failure-1'}
    jobs.start(service,ADMIN,body)
    worker=jobs._THREADS.get(str(jobs._path(service)))
    if worker:worker.join(5)
    final=jobs.status(service,ADMIN)['save']
    assert final['state']=='failed' and final['completed']==1
    assert 'private' not in final['message']
    assert len(service.bundle.operations.list_events('v1'))==1
    monkeypatch.setattr(OperationsService,'change_schedule',original)
    jobs.start(service,ADMIN,{**reviewed(service),'request_id':'recovery-1'})
    worker=jobs._THREADS.get(str(jobs._path(service)))
    if worker:worker.join(5)
    assert jobs.status(service,ADMIN)['save']['state']=='complete'
    assert len(service.bundle.operations.list_events('v1'))==1
    assert len(service.bundle.operations.list_events('v2'))==1


def test_background_restart_does_not_silently_resume_old_writes(service):
    from dtm_buildsheet.app.services import calendar_save_jobs as jobs
    jobs._write(jobs._path(service),{'state':'syncing','completed':2})
    assert jobs.status(service,ADMIN)['save']['state']=='interrupted'
    assert not service.store.path.exists()


def test_publish_reads_backlog_once_and_stops_if_calendar_changes(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    saved=service.save(ADMIN,reviewed(service))
    def change_calendar(count):
        settings_save(service,saved['settings'])
    with pytest.raises(CalendarConflictError):
        service.publish_dates(ADMIN,saved,'concurrent',on_progress=change_calendar)
    assert len(service.bundle.operations.list_events('v1'))==1
    assert not service.bundle.operations.list_events('v2')


def test_background_writer_uses_silent_provider_and_separate_http_session():
    from unittest.mock import Mock
    from dtm_buildsheet.app.adapters.cloud.sharepoint_operations_repository import SharePointOperationsRepository
    interactive,silent=Mock(),Mock()
    writer=SharePointOperationsRepository(token_provider=interactive,background_token_provider=silent,
        site_id='site',operations_list_id='vehicles',events_list_id='events')
    background=writer.for_background()
    assert background._token_provider is silent
    assert background._session is not writer._session
    interactive.assert_not_called()


def test_background_upload_stops_if_initiating_user_loses_access(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    saved=service.save(ADMIN,reviewed(service))
    def revoke(_count):service.authorize=lambda _actor,_capability:False
    with pytest.raises(OperationsAuthorizationError):
        service.publish_dates(ADMIN,saved,'role-change',on_progress=revoke)
    assert len(service.bundle.operations.list_events('v1'))==1
    assert not service.bundle.operations.list_events('v2')



def test_project_uses_one_team_and_saved_numbering_is_stable(service):
    service.bundle.operations._records={f'v{i}':vehicle(f'v{i}') for i in range(3)}
    view=service.view(ADMIN)
    body={'revision':view['revision'],'source_revision':view['source_revision'],
          'project_assignment':{'project_id':'p1','team_ids':['team-david']}}
    preview=service.preview(ADMIN,body)
    saved=service.save(ADMIN,{**body,'preview_token':preview['preview_token']})
    jobs=saved['plan']['jobs']
    assert {j['team_id'] for j in jobs}=={'team-david'}
    assert sorted(j['build_number'] for j in jobs)==[1,2,3]
    assert all(j['build_count']==3 for j in jobs)
    assert jobs[0]['end']<=jobs[1]['start']


def test_acceptance_date_shared_command_keeps_deadline_and_is_visible_in_calendar(service):
    from dtm_buildsheet.app.services.operations_service import OperationsService
    r=service.bundle.operations._records['v1'];r.must_deliver_override_date='2026-12-01'
    # Legacy Calendar-only date must not override a later explicit shared correction.
    service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-michelle','accepted_date_source':'manual','accepted_date':'2026-08-01'}))
    OperationsService(service.bundle.operations_writer).change_acceptance_date(vehicle_id='v1',
        accepted_date='2026-07-02',acceptance_source='manual',actor=SALES,request_id='accepted-date',
        source_client='builder_desktop',expected_revision=0)
    assert service.view(ADMIN)['plan']['jobs'][0]['accepted_date']=='2026-07-02'
    current=service.bundle.operations.get_vehicle('v1')
    assert current.must_deliver_override_date=='2026-12-01'
    event=service.bundle.operations.list_events('v1')[0]
    assert event.effective_date=='2026-07-02'
    with pytest.raises(OperationsAuthorizationError):
        OperationsService(service.bundle.operations_writer).change_acceptance_date(vehicle_id='v1',
            accepted_date='2026-07-03',acceptance_source='manual',actor=OperationsActor('shop','Shop',frozenset({'ShopEditor'})),
            request_id='denied',source_client='builder_desktop',expected_revision=1)






def test_sharepoint_qbo_date_roundtrip_does_not_shift_to_previous_business_day():
    from dtm_buildsheet.app.adapters.cloud.operations_list_codec import vehicle_operations_from_fields,vehicle_operations_to_fields
    from dtm_buildsheet.domain.calendar_planning import acceptance_day
    r=replace(vehicle(),acceptance_source='qbo',qbo_estimate_accepted_at='2026-07-29')
    fields=vehicle_operations_to_fields(r);fields['QboEstimateAcceptedAtUtc']='2026-07-29T00:00:00Z'
    assert acceptance_day(vehicle_operations_from_fields(fields))=='2026-07-29'


def test_booking_and_promises_survive_next_day_reads_and_readiness_changes(service):
    saved=service.save(ADMIN,reviewed(service))
    original=saved['plan']['jobs'][0]
    revision=saved['revision']
    service.today=lambda:date(2026,9,15)
    service.bundle.operations._records['v1'].parts_status='ordered'
    view=service.view(ADMIN);current=view['plan']['jobs'][0]
    for key in ('start','end','ready','segments','team_ids','promised_start','promised_ready'):
        assert current[key]==original[key]
    assert 'Waiting on parts' in current['blocked']
    assert current['forecast_start']==current['start']
    assert current['forecast_ready']==current['ready']
    assert view['revision']==revision


def test_saving_one_booking_does_not_reserve_other_accepted_vehicles(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david'}))
    assert [j['id'] for j in saved['plan']['jobs']]==['v1']
    assert [j['id'] for j in saved['plan']['queue']]==['v2']
    assert set(saved['saved_jobs'])=={'v1'}


def test_conflict_preview_names_vehicle_and_save_does_not_double_book(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','start_date':'2026-09-14'}))
    body=reviewed(service,{'id':'v2','team_id':'team-david','start_date':'2026-09-14'})
    preview=service.preview(ADMIN,body)
    assert any('v1' in c for c in preview['conflicts'])
    before=service.store.read()
    with pytest.raises(ValueError,match='Resolve booking conflicts'):service.save(ADMIN,body)
    assert service.store.read()==before


def test_opening_is_read_only_and_respects_selected_team_occupancy(service):
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-josh','team_ids':['team-josh'],'hours':14.4}))
    before=service.store.read()
    opening=service.opening(SALES,{'opening':{'team_ids':['team-josh'],'hours':7.2}})
    assert opening['reserved'] is False
    assert opening['opening']['start']=='2026-09-15T08:00'
    assert service.store.read()==before
    assert service.bundle.operations.get_vehicle('v1').revision==0


def test_only_accepted_vehicles_with_known_dates_can_be_reserved(service):
    service.bundle.operations._records['v1'].acceptance_status=AcceptanceStatus.NOT_ACCEPTED
    with pytest.raises(ValueError,match='Accept the vehicle'):
        reviewed(service,{'id':'v1','team_id':'team-david'})
    service.bundle.operations._records['v1'].acceptance_status=AcceptanceStatus.ACCEPTED
    service.bundle.operations._records['v1'].accepted_at=''
    with pytest.raises(ValueError,match='actual acceptance date'):
        reviewed(service,{'id':'v1','team_id':'team-david'})


def test_explained_team_change_updates_ready_date_and_history(service):
    first=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':28.8,'hours_manual':True}))
    old=first['plan']['jobs'][0]
    edit={'id':'v1','team_id':'team-michelle'}
    body=reviewed(service,edit,reason='')
    with pytest.raises(ValueError,match='Explain'):service.save(ADMIN,body)
    changed=service.save(ADMIN,reviewed(service,edit,reason='Covering the team absence; customer dates retained'))
    job=changed['plan']['jobs'][0]
    assert job['promised_ready']==old['promised_ready']
    assert job['promised_start']==old['promised_start']
    assert job['hours']==28.8
    assert job['ready']>old['ready']
    assert not any('Agreed' in w for w in job['warnings'])
    history=changed['history'][-1]
    assert history['actor_id']==ADMIN.user_id and history['reason'].startswith('Covering')
    assert history['changes'][0]['before']['team_ids']==['team-david']
    assert history['changes'][0]['after']['team_ids']==['team-michelle']


def test_capacity_settings_review_keeps_segments_and_exposes_impacts(service):
    first=service.save(ADMIN,reviewed(service))
    original=first['plan']['jobs'][0]
    settings=deepcopy(first['settings']);settings['teams'][2]['days_off']=['2026-09-14']
    body=reviewed(service,settings=settings)
    preview=service.preview(ADMIN,body)
    assert preview['settings_impacts'] and preview['requires_reason']
    result=service.save_settings(ADMIN,body)
    j=result['plan']['jobs'][0]
    assert j['segments']==original['segments']
    assert j['promised_ready']==original['promised_ready']
    assert 'Reservation includes a team absence or shop closure' in j['warnings']
    assert result['history'][-1]['settings_before']!=result['history'][-1]['settings_after']


def test_two_clients_cannot_reserve_same_snapshot(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    first=reviewed(service,{'id':'v1','team_id':'team-david'})
    second=reviewed(service,{'id':'v2','team_id':'team-david'})
    service.save(ADMIN,first)
    with pytest.raises(CalendarConflictError):service.save(ADMIN,second)
    assert list(service.store.read()[0]['jobs'])==['v1']


def test_legacy_saved_dates_are_preserved_without_inventing_customer_promise(service):
    first=service.save(ADMIN,reviewed(service))
    data,rev=service.store.read();data['schema_version']=1
    for spec in data['jobs'].values():
        spec.pop('promised_start');spec.pop('promised_ready')
    service.store.write(data,rev)
    j=service.view(ADMIN)['plan']['jobs'][0]
    assert j['start']==first['plan']['jobs'][0]['start']
    assert j['promised_start']==j['promised_ready']==''
    assert service.store.read()[0]['schema_version']==1  # read never migrates


def test_remaining_hours_do_not_erase_original_labor_estimate(service):
    original=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':60,'hours_manual':True}))['plan']['jobs'][0]
    service.today=lambda:date(2026,9,15)
    service.bundle.operations._records['v1'].shop_status='in_progress'
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','remaining_hours':8}))
    spec=service.store.read()[0]['jobs']['v1']
    assert spec['hours']==60
    assert spec['remaining_hours']==8
    current=saved['plan']['jobs'][0]
    assert (current['start'],current['ready'],current['segments'])==(original['start'],original['ready'],original['segments'])
    assert current['forecast_ready'] < original['ready']
    assert saved['history'][-1]['changes'][0]['after']['remaining_hours']==8


def test_partial_day_reservation_can_be_reviewed_without_a_false_overlap(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    first=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':16}))
    second=service.save(ADMIN,reviewed(service,{'id':'v2','team_id':'team-david','hours':8}))
    body=reviewed(service,{'id':'v2','team_id':'team-david'})
    preview=service.preview(ADMIN,body)
    assert preview['conflicts']==[]
    assert preview['changes']==[]
    assert second['plan']['jobs'][1]['start'].startswith('2026-09-15T08:53')


def test_multi_vehicle_opening_and_early_completion_never_move_other_bookings(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    service.save(ADMIN,reviewed(service))
    before=service.view(ADMIN)['plan']['jobs']
    service.bundle.operations._records['v1'].shop_status='complete'
    after=service.view(ADMIN)['plan']['jobs']
    assert [(j['id'],j['start'],j['ready']) for j in before]==[(j['id'],j['start'],j['ready']) for j in after]
    view=service.opening(SALES,{'opening':{'team_ids':['team-michelle'],'hours':7.2},'vehicle_count':2})
    assert len(view['vehicles'])==2
    assert view['vehicles'][0]['start']=='2026-09-14T08:00'
    assert view['vehicles'][1]['start']=='2026-09-15T08:00'


def test_schedule_publication_records_explanation_and_repairs_missing_week(service):
    saved=service.save(ADMIN,reviewed(service,reason='Customer agreed to these dates'))
    service.publish_dates(ADMIN,saved,'publish-reason',on_progress=lambda _:None)
    record=service.bundle.operations._records['v1']
    assert service.bundle.operations.list_events('v1')[0].reason=='Customer agreed to these dates'
    record.scheduled_week_of=''
    refreshed=service.view(ADMIN)
    assert len(service.date_changes(refreshed['plan']['jobs']))==1
    service.publish_dates(ADMIN,refreshed,'repair-week',on_progress=lambda _:None)
    assert record.planned_start_date==saved['plan']['jobs'][0]['start'][:10]
    assert service.bundle.operations.get_vehicle('v1').scheduled_week_of=='2026-09-14'


def test_opening_refuses_unknown_legacy_capacity_and_invalid_counts(service):
    service.bundle.operations._records['v1'].planned_start_date='2026-10-01'
    with pytest.raises(ValueError,match='Reconcile'):
        service.opening(SALES,{'opening':{'team_ids':['team-david']}})
    service.bundle.operations._records['v1'].planned_start_date=''
    with pytest.raises(ValueError,match='whole number'):
        service.opening(SALES,{'opening':{'team_ids':['team-david']},'vehicle_count':1.5})


def test_review_ticket_binds_explanation_and_settings_cannot_bypass_review(service):
    body=reviewed(service);body['reason']='Changed after preview'
    with pytest.raises(CalendarConflictError):service.save(ADMIN,body)
    view=service.view(ADMIN)
    with pytest.raises(CalendarConflictError):
        service.save_settings(ADMIN,{'revision':view['revision'],'settings':view['settings']})


def test_all_accepted_order_includes_reserved_and_queued_without_assigning_queue(service):
    service.bundle.operations._records['v2']=replace(vehicle('v2','p2'),accepted_at='2026-08-01')
    service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david'}))
    view=service.view(ADMIN)
    assert [j['id'] for j in view['plan']['accepted_queue']]==['v2','v1']
    assert [j['id'] for j in view['plan']['queue']]==['v2']


@pytest.mark.parametrize('remaining', [None, 43.2])
def test_forecast_never_reserves_hidden_capacity_after_saved_build_end(service, remaining):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':14.4}))
    service.today=lambda:date(2026,9,15)
    record=service.bundle.operations._records['v1'];record.shop_status='in_progress'
    if remaining is not None:
        # Legacy remaining-hour corrections are advisory until explicitly rebooked.
        service.save(ADMIN,reviewed(service,{'id':'v1','remaining_hours':remaining}))
    held=service.view(ADMIN)
    assert held['plan']['jobs'][0]['ready']=='2026-09-15T12:00'
    opening=service.opening(SALES,{'opening':{'team_ids':['team-david'],'hours':14.4}})
    assert opening['opening']['start']=='2026-09-15T08:00'
    choices=service.availability(ADMIN,{'availability':{'id':'v2','hours':14.4,'start_date':'2026-09-15'}})
    assert not next(c for c in choices['choices'] if c['team_id']=='team-david')['busy']
    body=reviewed(service,{'id':'v2','team_id':'team-david','hours':14.4,'start_date':'2026-09-15'})
    preview=service.preview(ADMIN,body)
    assert not preview['conflicts']
    saved=service.save(ADMIN,body)
    assert saved['plan']['jobs'][0]['segments']==held['plan']['jobs'][0]['segments']
    assert saved['plan']['jobs'][1]['start']=='2026-09-15T08:00'


def test_opening_can_start_exactly_at_saved_build_end_after_day_rollover(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    first=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':21.6}))
    service.today=lambda:date(2026,9,15)
    service.bundle.operations._records['v1'].shop_status='in_progress'
    opening=service.opening(SALES,{'opening':{'team_ids':['team-david'],'hours':7.2}})
    assert opening['opening']['start']==first['plan']['jobs'][0]['end']=='2026-09-15T12:00'
    second=service.save(ADMIN,reviewed(service,{'id':'v2','team_id':'team-david','hours':7.2}))
    assert second['plan']['jobs'][1]['start']=='2026-09-15T12:00'
    assert not second['plan']['jobs'][1]['conflicts']


def test_date_only_booking_uses_remaining_hours_on_the_requested_day(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    first=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':21.6}))
    edit={'id':'v2','kind':'build','team_id':'team-david','hours':14.4,'start_date':'2026-09-15'}
    before=service.store.read()
    choice=service.availability(ADMIN,{'availability':edit})['choices'][0]
    assert choice['start']==first['plan']['jobs'][0]['end']=='2026-09-15T12:00'
    assert not choice['busy'] and not choice['blocking_conflicts']
    assert service.store.read()==before
    result=service.save(ADMIN,reviewed(service,edit))
    assert result['plan']['jobs'][0]['segments']==first['plan']['jobs'][0]['segments']
    assert result['plan']['jobs'][1]['start']=='2026-09-15T12:00'
    assert result['plan']['jobs'][1]['end']=='2026-09-16T12:00'
    assert not result['plan']['jobs'][1]['conflicts']


def test_full_requested_day_stays_busy_instead_of_silently_moving(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':14.4}))
    choice=service.availability(ADMIN,{'availability':{'id':'v2','hours':7.2,'start_date':'2026-09-14'}})['choices'][0]
    assert choice['busy'] and choice['overlaps'][0]['id']=='v1'
    assert choice['start']=='2026-09-14T08:00'


def test_buffer_reserves_headroom_without_rounding_partial_days():
    settings=default_calendar_settings()
    buffered=staged([vehicle()],[reservation(hours=7.2)],settings)['jobs'][0]
    settings['buffer_percent']=0
    unbuffered=staged([vehicle()],[reservation(hours=7.2)],settings)['jobs'][0]
    assert buffered['end']=='2026-09-14T12:00'  # 14.4 usable labor hours per day.
    assert unbuffered['end']=='2026-09-14T11:36'  # 16 labor hours per day.


def test_lost_acceptance_requires_review_without_releasing_or_publishing_booking(service):
    saved=service.save(ADMIN,reviewed(service))
    service.bundle.operations._records['v1'].acceptance_status=AcceptanceStatus.NOT_ACCEPTED
    view=service.view(ADMIN)
    assert view['plan']['jobs'][0]['segments']==saved['plan']['jobs'][0]['segments']
    assert view['plan']['needs_review'][0]['reason'].startswith('Acceptance no longer confirmed')
    assert not service.date_changes(view['plan']['jobs'])


def test_queue_exposes_readiness_and_delivery_context_without_duplicate_identity(service):
    record=service.bundle.operations._records['v1']
    record.vehicle_label='2026 Explorer - Patrol - VIN UNKNOWN'
    record.must_deliver_override_date='2026-11-10'
    job=service.view(ADMIN)['plan']['queue'][0]
    assert job['vehicle_label']==record.vehicle_label
    assert job['parts_status']=='parts_ready'
    assert job['vehicle_availability_status']=='at_dtm'
    assert job['deadline']=='2026-11-10'


def test_second_team_is_rejected_for_booking_project_and_opening(service):
    view=service.view(ADMIN)
    selected=['team-david','team-josh']
    with pytest.raises(ValueError,match='Choose one team'):
        reviewed(service,{'id':'v1','team_id':'team-david','team_ids':selected})
    with pytest.raises(ValueError,match='Choose one active project team'):
        service.preview(ADMIN,{'revision':view['revision'],'source_revision':view['source_revision'],
            'project_assignment':{'project_id':'p1','team_ids':selected}})
    with pytest.raises(ValueError,match='Choose one active team'):
        service.opening(SALES,{'opening':{'team_ids':selected}})
    assert service.store.read()[1]==view['revision']


def test_legacy_promise_metadata_does_not_add_hidden_scheduling_constraints(service):
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david'}))
    doc,revision=service.store.read()
    doc['jobs']['v1'].update(promised_start='2020-01-01',promised_ready='2020-01-02')
    service.store.write(doc,revision)
    job=service.view(ADMIN)['plan']['jobs'][0]
    assert job['start']==saved['plan']['jobs'][0]['start']
    assert not any('Agreed' in w for w in job['warnings'])


def test_confirm_project_includes_unscheduled_siblings_and_keeps_other_bookings(service):
    service.bundle.operations._records.update(v2=vehicle('v2'), v3=vehicle('v3','p2'))
    first=service.save(ADMIN,reviewed(service,{'id':'v3','team_id':'team-josh'}))
    old=first['plan']['jobs'][0]
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david'},include_project=True))
    assert {j['id'] for j in saved['plan']['jobs']}=={'v1','v2','v3'}
    assert next(j for j in saved['plan']['jobs'] if j['id']=='v3')['segments']==old['segments']
    assert not saved['plan']['queue']


def test_availability_checks_full_duration_and_does_not_write(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','start_date':'2026-09-15','hours':14.4}))
    before=service.store.read()
    choices=service.availability(ADMIN,{'availability':{'id':'v2','kind':'build','hours':28.8,'start_date':'2026-09-14'}})['choices']
    assert choices[0]['team_id']=='team-david' and choices[0]['busy']
    assert choices[0]['overlaps'][0]['id']=='v1'
    assert not choices[1]['busy']
    assert service.store.read()==before
    with pytest.raises(OperationsAuthorizationError):service.availability(SALES,{'availability':{'id':'v2'}})


def test_overlap_requires_exact_confirmed_ticket_and_preserves_occupied_booking(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    first=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','start_date':'2026-09-14'}))
    edit={'id':'v2','team_id':'team-david','start_date':'2026-09-14'}
    denied=reviewed(service,edit)
    with pytest.raises(CalendarConflictError):service.save(ADMIN,{**denied,'allow_overlap':True})
    confirmed=reviewed(service,edit,allow_overlap=True,reason='Booking confirmed with overlapping work')
    saved=service.save(ADMIN,confirmed)
    assert len(saved['plan']['jobs'])==2
    assert next(j for j in saved['plan']['jobs'] if j['id']=='v1')['segments']==first['plan']['jobs'][0]['segments']
    assert saved['history'][-1]['reason']=='Booking confirmed with overlapping work'
    assert all(j['overlaps'] for j in saved['plan']['jobs'])


def test_overlap_confirmation_cannot_override_nonworking_start(service):
    body=reviewed(service,{'id':'v1','team_id':'team-david','start_date':'2026-09-19'},allow_overlap=True)
    with pytest.raises(ValueError,match='working day'):service.save(ADMIN,body)


def test_project_removal_clears_only_planning_dates_and_can_be_rebooked(service):
    service.bundle.operations._records['v2']=vehicle('v2','p2')
    saved=service.save(ADMIN,reviewed(service))
    service.publish_dates(ADMIN,saved,'initial',on_progress=lambda _:None)
    before=deepcopy(service.bundle.operations.get_vehicle('v1'))
    body=reviewed(service,remove_project='p1',edits=[])
    removed=service.save(ADMIN,body)
    assert [j['id'] for j in removed['plan']['jobs']]==['v2']
    assert [j['id'] for j in removed['plan']['queue']]==['v1']
    assert removed['history'][-1]['changes'][0]['after'] is None
    assert not any(k in removed['saved_jobs']['v1'] for k in ('team_id','team_ids','last_plan','start_date'))
    service.publish_dates(ADMIN,removed,'remove',on_progress=lambda _:None)
    after=service.bundle.operations.get_vehicle('v1')
    assert not after.planned_start_date and not after.target_finish_date and not after.scheduled_week_of
    for key in ('accepted_at','parts_status','shop_status','shop_started_at','shop_completed_at','must_deliver_by_date','must_deliver_override_date'):
        assert getattr(after,key)==getattr(before,key)
    assert service.bundle.operations.get_vehicle('v2').planned_start_date
    refreshed=service.view(ADMIN)
    assert not service.date_changes(refreshed['plan']['jobs'],refreshed['plan']['released'])
    rebooked=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david'}))
    assert not rebooked['saved_jobs']['v1'].get('released')
    assert len(rebooked['plan']['jobs'])==2


def test_interrupted_removal_remains_pending_for_fresh_publication(service):
    saved=service.save(ADMIN,reviewed(service))
    service.publish_dates(ADMIN,saved,'initial',on_progress=lambda _:None)
    removed=service.save(ADMIN,reviewed(service,remove_project='p1',edits=[]))
    fresh=service.view(ADMIN)
    pending=service.date_changes(fresh['plan']['jobs'],fresh['plan']['released'])
    assert [j['id'] for j in pending]==['v1']
    service.publish_dates(ADMIN,fresh,'resume-removal',on_progress=lambda _:None)
    assert not service.bundle.operations.get_vehicle('v1').planned_start_date


def test_next_openings_use_standard_duration_and_do_not_reserve(service):
    saved=service.save(ADMIN,reviewed(service,{'id':'v1','team_id':'team-david','hours':14.4,'start_date':'2026-09-14'}))
    before=service.store.read()
    view=service.view(SALES)
    openings={o['team_id']:o['start'] for o in view['next_openings']}
    assert openings['team-david']=='2026-09-15T08:00'
    assert openings['team-josh']=='2026-09-14T08:00'
    assert view['opening_note']=='Standard strip + build'
    assert service.store.read()==before
    assert view['plan']['jobs'][0]['segments']==saved['plan']['jobs'][0]['segments']


def test_next_opening_is_unavailable_until_legacy_dates_reconciled(service):
    service.bundle.operations._records['v1'].planned_start_date='2026-09-14'
    view=service.view(SALES)
    assert not view['next_openings']
    assert 'Reconcile existing bookings' in view['opening_note']


def test_pending_date_count_disappears_after_normal_publication(service):
    assert service.view(ADMIN)['pending_date_count']==0
    saved=service.save(ADMIN,reviewed(service))
    assert saved['pending_date_count']==1
    service.publish_dates(ADMIN,saved,'publish-count',on_progress=lambda _:None)
    assert service.view(ADMIN)['pending_date_count']==0
    removed=service.save(ADMIN,reviewed(service,remove_project='p1',edits=[]))
    assert removed['pending_date_count']==1
    service.publish_dates(ADMIN,removed,'clear-count',on_progress=lambda _:None)
    assert service.view(ADMIN)['pending_date_count']==0
