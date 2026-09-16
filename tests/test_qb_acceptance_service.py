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


def test_pending_is_not_sent_and_send_evidence_survives_sparse_refresh():
    from dtm_buildsheet.app.services.operations_read_service import OperationsReadService
    r = VehicleOperations(vehicle_id='v', project_id='p', qbo_estimate_id='123')
    _, bundle, client = run(r, {'TxnStatus': 'Pending', 'EmailStatus': 'NeedToSend'})
    assert bundle.operations.get_vehicle('v').qbo_estimate_sent_status == 'not_confirmed'
    client.read_estimate.return_value = {'TxnStatus': 'Pending', 'EmailStatus': 'EmailSent',
        'DeliveryInfo': {'DeliveryTime': '2026-09-15T10:00:00-05:00'}}
    result = refresh_linked_acceptance(bundle.operations, bundle.operations_writer, client, ACTOR)
    assert result['updated'] == 1
    row = OperationsReadService(bundle.operations).list_vehicle_summaries(ACTOR)['vehicles'][0]
    assert row['qbo_estimate_id'] == '123'
    assert row['qbo_estimate_sent_status'] == 'sent'
    assert row['qbo_estimate_sent_at'] == '2026-09-15T10:00:00-05:00'
    assert row['acceptance_status'] == 'not_accepted'
    client.read_estimate.return_value = {'TxnStatus': 'Pending'}
    assert refresh_linked_acceptance(bundle.operations, bundle.operations_writer, client, ACTOR)['updated'] == 0
    assert len(bundle.operations.list_events('v')) == 2
    assert 'sent_status' in bundle.operations.list_events('v')[-1].new_value


def test_send_evidence_roundtrip_and_replaced_link_reset():
    from dtm_buildsheet.app.adapters.cloud.operations_list_codec import vehicle_operations_to_fields, vehicle_operations_from_fields
    from dtm_buildsheet.app.services.operations_service import OperationsService
    _, bundle, _ = run(VehicleOperations(vehicle_id='v', project_id='p', qbo_estimate_id='123'),
                       {'TxnStatus': 'Pending', 'EmailStatus': 'EmailSent'})
    current = vehicle_operations_from_fields(vehicle_operations_to_fields(bundle.operations.get_vehicle('v')))
    assert current.qbo_estimate_sent_status == 'sent'
    assert current.qbo_estimate_sent_at == ''  # Do not use the observation time.
    bundle.operations._records['v'] = current
    result = OperationsService(bundle.operations_writer).observe_qbo_estimate(vehicle_id='v', actor=ACTOR,
        request_id='replace', source_client='builder_desktop', expected_revision=current.revision,
        qbo_estimate_id='456', qbo_estimate_status='Pending')
    assert result.record.qbo_estimate_sent_status == ''
    assert result.record.qbo_estimate_sent_at == ''


def test_sending_does_not_use_created_modified_or_delivery_time_alone():
    from dtm_buildsheet.domain.estimate_status import estimate_send_evidence
    for status in ('', 'NotSet', 'NeedToSend', 'Unknown'):
        evidence = estimate_send_evidence({'EmailStatus': status, 'TxnStatus': 'Pending',
            'MetaData': {'CreateTime': '2026-01-01', 'LastUpdatedTime': '2026-02-01'},
            'DeliveryInfo': {'DeliveryTime': '2026-09-15T10:00:00Z'}})
        assert evidence['qbo_estimate_sent_status'] != 'sent'
        assert evidence['qbo_estimate_sent_at'] == ''
    assert estimate_send_evidence({'EmailStatus': 'EmailSent', 'DeliveryInfo': {'DeliveryTime': 'invalid'}}) == {
        'qbo_estimate_sent_status': 'sent', 'qbo_estimate_sent_at': ''}


def test_shared_estimate_badges_and_partial_project_data():
    import subprocess
    from pathlib import Path
    root = Path(__file__).parents[1] / 'src/dtm_buildsheet/ui/js'
    script = 'const window = {}; const document = {addEventListener(){}};\n' + (root / 'estimate_status.js').read_text() + (root / 'projects/list_view.js').read_text()
    script += r"""
const assert = require('node:assert/strict');
assert.equal(estimateStatus().label, 'No Estimate Connected');
const linked = {qbo_estimate_id:'1', qbo_estimate_status:'Pending'};
assert.equal(estimateStatus(linked).label, 'Estimate Created');
const sent = {...linked, qbo_estimate_sent_status:'sent'};
assert.equal(estimateStatus(sent).label, 'Estimate Sent');
assert.equal(estimateStatus({...sent,qbo_estimate_status:'Rejected'}).label, 'Estimate Declined');
assert.equal(estimateStatus({acceptance_status:'accepted'}).label, 'Accepted');
assert.equal(estimateGroupStatus([sent, linked]).label, '1/2 Estimate Sent · 1/2 Estimate Created');
const _PT = {operationsByProject:{p:[{...sent, vehicle_id:'a'}]}};
const project = {project_id:'p',build_units:[{individuals:[{individual_id:'a', qb_estimate_id:'1'}, {individual_id:'b'}]}]};
assert.equal(_ptProjectProgress(project).label, '1/2 Estimate Sent · 1/2 No Estimate Connected');
project.build_units[0].individuals[0].qb_estimate_id = '2';
assert.equal(_ptProjectProgress(project).label, '1/2 Estimate Created · 1/2 No Estimate Connected');
_PT.operationsByProject = {};
assert.equal(_ptProjectProgress(project).label, '1/2 Estimate Created · 1/2 No Estimate Connected');
"""
    result = subprocess.run(['node'], input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_send_schema_upgrade_adds_only_missing_columns():
    from dtm_buildsheet.app.adapters.cloud.operations_list_provisioner import OperationsListProvisioner, ProvisioningReport, ListInspection
    from dtm_buildsheet.app.adapters.cloud.operations_list_schema import ESTIMATE_SEND_SCHEMA_CONFIRMATION, OPERATIONS_LIST_NAME, EVENTS_LIST_NAME
    provisioner = OperationsListProvisioner(token='fake', site_id='fake')
    provisioner.inspect = Mock(side_effect=[
        ProvisioningReport(lists=(ListInspection(name=OPERATIONS_LIST_NAME, list_id='o', state='mismatch',
            issues=('Missing column: QboEstimateSentStatus', 'Missing column: QboEstimateSentAtUtc')),
            ListInspection(name=EVENTS_LIST_NAME, list_id='e', state='valid'))),
        ProvisioningReport(lists=(ListInspection(name=OPERATIONS_LIST_NAME, list_id='o', state='valid'),
            ListInspection(name=EVENTS_LIST_NAME, list_id='e', state='valid')))])
    provisioner._create_column = Mock()
    assert provisioner.apply_estimate_send_schema_upgrade(confirmation=ESTIMATE_SEND_SCHEMA_CONFIRMATION).ready
    assert [call.kwargs['column'].name for call in provisioner._create_column.call_args_list] == [
        'QboEstimateSentStatus', 'QboEstimateSentAtUtc']
