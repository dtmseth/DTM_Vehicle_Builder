from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

from dtm_buildsheet.app.adapters.wiring import build_local_bundle
from dtm_buildsheet.app.services.qb_acceptance_service import refresh_linked_acceptance
from dtm_buildsheet.domain.operations_models import VehicleOperations, OperationsActor, AcceptanceStatus

ACTOR=OperationsActor('owner','Owner',frozenset({'AppAdmin'}))


def run(record, estimate):
    bundle=build_local_bundle();bundle.operations._records[record.vehicle_id]=record
    client=Mock();client.read_estimate.return_value=estimate
    result=refresh_linked_acceptance(bundle.operations,bundle.operations_writer,client,ACTOR)
    return result,bundle,client


def test_newly_accepted_estimate_uses_actual_qbo_date_and_no_duplicate_writes():
    r=VehicleOperations(vehicle_id='v',project_id='p',qbo_estimate_id='123')
    estimate={'TxnStatus':'Accepted','AcceptedDate':'2026-03-27'}
    result,bundle,client=run(r,estimate)
    current=bundle.operations.get_vehicle('v')
    assert current.accepted_at=='2026-03-27'
    assert current.acceptance_source=='qbo'
    assert current.acceptance_status==AcceptanceStatus.ACCEPTED
    again=refresh_linked_acceptance(bundle.operations,bundle.operations_writer,client,ACTOR)
    assert again['updated']==0
    assert len(bundle.operations.list_events('v'))==1
    client.create_estimate.assert_not_called()


def test_missing_qbo_date_is_blank_not_observation_time():
    _,bundle,_=run(VehicleOperations(vehicle_id='v',project_id='p',qbo_estimate_id='123'),{'TxnStatus':'Accepted'})
    current=bundle.operations.get_vehicle('v')
    assert current.acceptance_status==AcceptanceStatus.ACCEPTED
    assert current.accepted_at==''
    assert current.qbo_checked_at


def test_manual_acceptance_survives_different_or_pending_qbo_status():
    r=VehicleOperations(vehicle_id='v',project_id='p',qbo_estimate_id='123',
        acceptance_status=AcceptanceStatus.ACCEPTED,accepted_at='2026-01-12',acceptance_source='manual')
    for estimate in ({'TxnStatus':'Accepted','AcceptedDate':'2026-02-01'},{'TxnStatus':'Pending'}):
        _,bundle,_=run(r,estimate)
        current=bundle.operations.get_vehicle('v')
        assert current.accepted_at=='2026-01-12' and current.acceptance_source=='manual'


def test_qbo_owned_legacy_observation_date_is_corrected():
    r=VehicleOperations(vehicle_id='v',project_id='p',qbo_estimate_id='123',
        acceptance_status=AcceptanceStatus.ACCEPTED,accepted_at='2026-09-09T12:00:00Z',acceptance_source='qbo')
    _,bundle,_=run(r,{'TxnStatus':'Accepted','AcceptedDate':'2026-07-29'})
    assert bundle.operations.get_vehicle('v').accepted_at=='2026-07-29'


def test_shop_cannot_run_acceptance_monitor():
    bundle=build_local_bundle();client=Mock()
    result=refresh_linked_acceptance(bundle.operations,bundle.operations_writer,client,
        OperationsActor('shop','Shop',frozenset({'ShopEditor'})))
    assert result['skipped']=='role'
    client.read_estimate.assert_not_called()


def test_sharepoint_date_roundtrip_does_not_repeat_acceptance_writes():
    from dtm_buildsheet.app.adapters.cloud.operations_list_codec import (
        vehicle_operations_to_fields, vehicle_operations_from_fields)
    _, bundle, client = run(VehicleOperations(vehicle_id='v', project_id='p', qbo_estimate_id='123'),
                            {'TxnStatus': 'Accepted', 'AcceptedDate': '2026-03-27'})
    fields = vehicle_operations_to_fields(bundle.operations.get_vehicle('v'))
    fields['AcceptedAtUtc'] = '2026-03-27T00:00:00Z'
    fields['QboEstimateAcceptedAtUtc'] = '2026-03-27T00:00:00Z'
    bundle.operations._records['v'] = vehicle_operations_from_fields(fields)
    result = refresh_linked_acceptance(bundle.operations, bundle.operations_writer, client, ACTOR)
    assert result['updated'] == 0
    assert len(bundle.operations.list_events('v')) == 1
