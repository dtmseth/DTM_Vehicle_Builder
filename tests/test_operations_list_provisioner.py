from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from dtm_buildsheet.app.adapters.cloud.msal_client import (
    MsalClient,
    _SessionPersistedTokenCache,
)
from dtm_buildsheet.app.adapters.cloud.operations_list_provisioner import (
    OperationsListProvisioner,
    OperationsListProvisioningError,
)
from dtm_buildsheet.app.adapters.cloud.operations_list_schema import (
    DEADLINE_OVERRIDE_SCHEMA_COLUMN_NAMES,
    DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION,
    EVENTS_LIST_NAME,
    FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION,
    OPERATIONS_LIST_NAME,
    OPERATIONS_LIST_SPECS,
    OPERATIONS_REQUESTS_LIST,
    PARTS_ORDERED_SCHEMA_COLUMN_NAMES,
    PARTS_ORDERED_SCHEMA_CONFIRMATION,
    PROVISION_CONFIRMATION,
    PHONE_REQUESTS_PROVISION_CONFIRMATION,
    REQUESTS_LIST_NAME,
    RECOVERY_SCHEMA_COLUMN_NAMES,
    RECOVERY_SCHEMA_CONFIRMATION,
    VEHICLE_EVENTS_LIST,
    VEHICLE_OPERATIONS_LIST,
)


def _response(payload: dict, status: int = 200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(str(status))
    else:
        response.raise_for_status.return_value = None
    return response


def _actual_columns(spec):
    return [
        {"name": "Title", "required": True, "text": {"allowMultipleLines": False}},
        {
            "name": "Modified",
            "columnGroup": "Custom Columns",
            "readOnly": True,
            "hidden": False,
        },
        {
            "name": "Attachments",
            "columnGroup": "Custom Columns",
            "readOnly": False,
            "hidden": False,
        },
        *[
            {
                **column.graph_payload(),
                "id": f"{column.name}-id",
                "columnGroup": "Custom Columns",
            }
            for column in spec.columns
        ],
    ]


def _existing_lists():
    return {
        "value": [
            {"id": "operations-id", "name": OPERATIONS_LIST_NAME},
            {"id": "events-id", "displayName": EVENTS_LIST_NAME},
        ]
    }


def _existing_lists_with_requests():
    payload = _existing_lists()
    payload["value"].append({"id": "requests-id", "name": REQUESTS_LIST_NAME})
    return payload


def test_manifest_has_exact_names_and_safe_index_budget():
    assert [spec.name for spec in OPERATIONS_LIST_SPECS] == [
        "DTMVehicleOperations",
        "DTMVehicleEvents",
    ]
    assert VEHICLE_OPERATIONS_LIST.indexed_column_count == 19
    assert VEHICLE_EVENTS_LIST.indexed_column_count == 12
    assert OPERATIONS_REQUESTS_LIST.name == "DTMOperationsRequests"
    assert OPERATIONS_REQUESTS_LIST.indexed_column_count == 6
    assert all(
        len(column.name) <= 32
        for spec in (*OPERATIONS_LIST_SPECS, OPERATIONS_REQUESTS_LIST)
        for column in spec.columns
    )

    operations = {column.name: column for column in VEHICLE_OPERATIONS_LIST.columns}
    assert operations["BuilderVehicleId"].unique is True
    assert operations["Vin"].indexed is True
    assert operations["VehicleAvailabilityStatus"].choices == (
        "awaiting_details",
        "waiting_on_dealer",
        "waiting_on_agency",
        "ready_for_pickup",
        "at_dtm",
        "delivered",
    )
    assert operations["PartsStatus"].choices == (
        "ordered",
        "partially_received",
        "received",
        "parts_ready",
    )
    assert operations["FinalFinishStatus"].choices == (
        "not_ready",
        "ready_for_wash_clean_photos",
        "ready_for_delivery",
        "delivered",
    )
    assert "PartsOrderedAtUtc" in operations
    assert "OperationsNote" not in operations
    assert "NeedByDate" not in operations

    requests = {column.name: column for column in OPERATIONS_REQUESTS_LIST.columns}
    assert requests["RequestId"].unique is True
    assert requests["Workstream"].choices == (
        "shop", "tray", "programming_qc", "final_finish",
    )
    assert "not_ready" not in requests["RequestedStatus"].choices


def test_schema_document_and_executable_manifest_have_identical_column_names():
    document = (
        Path(__file__).resolve().parents[1] / "docs" / "OPERATIONS.md"
    ).read_text(encoding="utf-8")
    current_section, remainder = document.split("### List: `DTMVehicleEvents`", maxsplit=1)
    current_section = current_section.split("### List: `DTMVehicleOperations`", maxsplit=1)[1]
    event_section, remainder = remainder.split("### List: `DTMOperationsRequests`", maxsplit=1)
    request_section = remainder.split("### Domain values", maxsplit=1)[0]
    document_current = set(re.findall(r"^\| `([^`]+)` \|", current_section, re.MULTILINE))
    document_events = set(re.findall(r"^\| `([^`]+)` \|", event_section, re.MULTILINE))
    document_requests = set(re.findall(r"^\| `([^`]+)` \|", request_section, re.MULTILINE))

    assert document_current == {
        "Title", *(column.name for column in VEHICLE_OPERATIONS_LIST.columns),
    }
    assert document_events == {
        "Title", *(column.name for column in VEHICLE_EVENTS_LIST.columns),
    }
    assert document_requests == {
        "Title", *(column.name for column in OPERATIONS_REQUESTS_LIST.columns),
    }


def test_graph_create_payload_uses_permanent_machine_name_and_all_columns():
    payload = VEHICLE_OPERATIONS_LIST.graph_create_payload()

    assert payload["displayName"] == OPERATIONS_LIST_NAME
    assert payload["list"] == {"template": "genericList"}
    assert [column["name"] for column in payload["columns"]] == [
        column.name for column in VEHICLE_OPERATIONS_LIST.columns
    ]
    assert next(
        column for column in payload["columns"]
        if column["name"] == "BuilderVehicleId"
    )["enforceUniqueValues"] is True


def test_inspect_reports_missing_without_posting():
    session = MagicMock()
    session.get.return_value = _response({"value": []})
    provisioner = OperationsListProvisioner(
        token="TOKEN",
        site_id="tenant.sharepoint.com,site-id,web-id",
        session=session,
    )

    report = provisioner.inspect()

    assert [item.state for item in report.lists] == ["missing", "missing"]
    assert report.ready is False
    session.post.assert_not_called()


def test_inspect_accepts_exact_existing_schema():
    session = MagicMock()
    session.get.side_effect = [
        _response(_existing_lists()),
        _response({"value": _actual_columns(VEHICLE_OPERATIONS_LIST)}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
    ]
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.inspect()

    assert report.ready is True
    assert [item.list_id for item in report.lists] == ["operations-id", "events-id"]


def test_phone_request_inspection_accepts_exact_schema():
    session = MagicMock()
    session.get.side_effect = [
        _response(_existing_lists_with_requests()),
        _response({"value": _actual_columns(OPERATIONS_REQUESTS_LIST)}),
    ]
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.inspect_phone_requests()

    assert report.ready is True
    assert report.lists[0].list_id == "requests-id"


def test_phone_request_provisioning_requires_exact_confirmation_without_network():
    session = MagicMock()
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="exactly equal"):
        provisioner.apply_phone_requests_list(confirmation="yes")

    session.get.assert_not_called()
    session.post.assert_not_called()


def test_phone_request_provisioning_creates_only_request_list_after_core_validation():
    session = MagicMock()
    session.get.side_effect = [
        _response(_existing_lists()),
        _response({"value": _actual_columns(VEHICLE_OPERATIONS_LIST)}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
        _response(_existing_lists()),
        _response(_existing_lists_with_requests()),
        _response({"value": _actual_columns(OPERATIONS_REQUESTS_LIST)}),
    ]
    session.post.return_value = _response({}, status=201)
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.apply_phone_requests_list(
        confirmation=PHONE_REQUESTS_PROVISION_CONFIRMATION,
    )

    assert report.ready is True
    assert session.post.call_count == 1
    assert session.post.call_args.kwargs["json"]["displayName"] == REQUESTS_LIST_NAME


def test_inspect_rejects_unexpected_editable_visible_custom_column():
    session = MagicMock()
    columns = _actual_columns(VEHICLE_OPERATIONS_LIST)
    columns.append({
        "name": "SurpriseField",
        "columnGroup": "Custom Columns",
        "readOnly": False,
        "hidden": False,
    })
    session.get.side_effect = [
        _response({
            "value": [{"id": "operations-id", "name": OPERATIONS_LIST_NAME}],
        }),
        _response({"value": columns}),
    ]
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.inspect()

    assert report.has_mismatch is True
    assert report.lists[0].issues == (
        "Unexpected custom column: SurpriseField",
    )


def test_apply_refuses_existing_mismatch_before_any_creation():
    session = MagicMock()
    session.get.side_effect = [
        _response({"value": [{"id": "operations-id", "name": OPERATIONS_LIST_NAME}]}),
        _response({"value": [{"name": "Title", "text": {}}]}),
    ]
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="mismatch"):
        provisioner.apply(confirmation=PROVISION_CONFIRMATION)

    session.post.assert_not_called()


def test_apply_refuses_confusingly_similar_list_name():
    session = MagicMock()
    session.get.return_value = _response({
        "value": [{"id": "maybe-operations", "name": "DTM-Vehicle-Operations"}],
    })
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="mismatch"):
        provisioner.apply(confirmation=PROVISION_CONFIRMATION)

    session.post.assert_not_called()


def test_apply_requires_exact_confirmation_without_network_access():
    session = MagicMock()
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="exactly equal"):
        provisioner.apply(confirmation="yes")

    session.get.assert_not_called()
    session.post.assert_not_called()


def test_apply_creates_both_missing_lists_and_validates_result():
    session = MagicMock()
    session.get.side_effect = [
        _response({"value": []}),
        _response(_existing_lists()),
        _response({"value": _actual_columns(VEHICLE_OPERATIONS_LIST)}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
    ]
    session.post.side_effect = [_response({}, status=201), _response({}, status=201)]
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.apply(confirmation=PROVISION_CONFIRMATION)

    assert report.ready is True
    assert session.post.call_count == 2
    assert [
        call.kwargs["json"]["displayName"] for call in session.post.call_args_list
    ] == [OPERATIONS_LIST_NAME, EVENTS_LIST_NAME]


def test_recovery_upgrade_adds_only_reviewed_missing_columns_then_validates():
    session = MagicMock()
    old_operations = [
        column for column in _actual_columns(VEHICLE_OPERATIONS_LIST)
        if column["name"] not in RECOVERY_SCHEMA_COLUMN_NAMES[OPERATIONS_LIST_NAME]
    ]
    old_events = [
        column for column in _actual_columns(VEHICLE_EVENTS_LIST)
        if column["name"] not in RECOVERY_SCHEMA_COLUMN_NAMES[EVENTS_LIST_NAME]
    ]
    session.get.side_effect = [
        _response(_existing_lists()),
        _response({"value": old_operations}),
        _response({"value": old_events}),
        _response(_existing_lists()),
        _response({"value": _actual_columns(VEHICLE_OPERATIONS_LIST)}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
    ]
    session.post.side_effect = [_response({}, status=201) for _ in range(5)]
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.apply_recovery_schema_upgrade(
        confirmation=RECOVERY_SCHEMA_CONFIRMATION,
    )

    assert report.ready is True
    assert [call.kwargs["json"]["name"] for call in session.post.call_args_list] == [
        "CreatedAtUtc",
        "CreatedByEntraId",
        "CreatedByName",
        "CommitStatus",
        "RecordSnapshotJson",
    ]
    assert all(call.args[0].endswith("/columns") for call in session.post.call_args_list)


def test_recovery_upgrade_refuses_any_unreviewed_schema_mismatch():
    session = MagicMock()
    old_operations = [
        column for column in _actual_columns(VEHICLE_OPERATIONS_LIST)
        if column["name"] not in RECOVERY_SCHEMA_COLUMN_NAMES[OPERATIONS_LIST_NAME]
    ]
    old_operations.append({
        "name": "SurpriseField",
        "columnGroup": "Custom Columns",
        "readOnly": False,
        "hidden": False,
    })
    session.get.side_effect = [
        _response(_existing_lists()),
        _response({"value": old_operations}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
    ]
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="non-upgrade mismatch"):
        provisioner.apply_recovery_schema_upgrade(
            confirmation=RECOVERY_SCHEMA_CONFIRMATION,
        )

    session.post.assert_not_called()


def test_recovery_upgrade_requires_exact_confirmation_without_network():
    session = MagicMock()
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="exactly equal"):
        provisioner.apply_recovery_schema_upgrade(confirmation="yes")

    session.get.assert_not_called()
    session.post.assert_not_called()


def test_deadline_override_upgrade_adds_only_reviewed_column_then_validates():
    session = MagicMock()
    old_operations = [
        column for column in _actual_columns(VEHICLE_OPERATIONS_LIST)
        if column["name"] not in DEADLINE_OVERRIDE_SCHEMA_COLUMN_NAMES[OPERATIONS_LIST_NAME]
    ]
    session.get.side_effect = [
        _response(_existing_lists()),
        _response({"value": old_operations}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
        _response(_existing_lists()),
        _response({"value": _actual_columns(VEHICLE_OPERATIONS_LIST)}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
    ]
    session.post.return_value = _response({}, status=201)
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.apply_deadline_override_schema_upgrade(
        confirmation=DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION,
    )

    assert report.ready is True
    assert [call.kwargs["json"]["name"] for call in session.post.call_args_list] == [
        "MustDeliverOverrideDate",
    ]


def test_deadline_override_upgrade_requires_exact_confirmation_without_network():
    session = MagicMock()
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="exactly equal"):
        provisioner.apply_deadline_override_schema_upgrade(confirmation="yes")

    session.get.assert_not_called()
    session.post.assert_not_called()


def test_parts_ordered_upgrade_adds_milestone_and_extends_reviewed_choices():
    session = MagicMock()
    old_operations = [
        column for column in _actual_columns(VEHICLE_OPERATIONS_LIST)
        if column["name"] not in PARTS_ORDERED_SCHEMA_COLUMN_NAMES[OPERATIONS_LIST_NAME]
    ]
    parts_status = next(column for column in old_operations if column["name"] == "PartsStatus")
    parts_status["choice"]["choices"] = [
        "partially_received", "received", "parts_ready",
    ]
    session.get.side_effect = [
        _response(_existing_lists()),
        _response({"value": old_operations}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
        _response({"value": old_operations}),
        _response(_existing_lists()),
        _response({"value": _actual_columns(VEHICLE_OPERATIONS_LIST)}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
    ]
    session.post.return_value = _response({}, status=201)
    session.patch.return_value = _response({}, status=200)
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.apply_parts_ordered_schema_upgrade(
        confirmation=PARTS_ORDERED_SCHEMA_CONFIRMATION,
    )

    assert report.ready is True
    assert session.post.call_args.kwargs["json"]["name"] == "PartsOrderedAtUtc"
    assert session.patch.call_args.args[0].endswith("/columns/PartsStatus-id")
    assert session.patch.call_args.kwargs["json"]["choice"]["choices"] == [
        "ordered", "partially_received", "received", "parts_ready",
    ]


def test_parts_ordered_upgrade_refuses_unreviewed_choice_values():
    session = MagicMock()
    old_operations = [
        column for column in _actual_columns(VEHICLE_OPERATIONS_LIST)
        if column["name"] != "PartsOrderedAtUtc"
    ]
    parts_status = next(column for column in old_operations if column["name"] == "PartsStatus")
    parts_status["choice"]["choices"] = ["ordered_elsewhere", "received"]
    session.get.side_effect = [
        _response(_existing_lists()),
        _response({"value": old_operations}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
        _response({"value": old_operations}),
    ]
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="reviewed pre-upgrade"):
        provisioner.apply_parts_ordered_schema_upgrade(
            confirmation=PARTS_ORDERED_SCHEMA_CONFIRMATION,
        )

    session.post.assert_not_called()
    session.patch.assert_not_called()


def test_parts_ordered_upgrade_requires_exact_confirmation_without_network():
    session = MagicMock()
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="exactly equal"):
        provisioner.apply_parts_ordered_schema_upgrade(confirmation="yes")

    session.get.assert_not_called()
    session.post.assert_not_called()
    session.patch.assert_not_called()


def test_final_finish_delivered_upgrade_extends_only_reviewed_choices():
    session = MagicMock()
    old_operations = _actual_columns(VEHICLE_OPERATIONS_LIST)
    final_finish = next(
        column for column in old_operations if column["name"] == "FinalFinishStatus"
    )
    final_finish["choice"]["choices"] = [
        "not_ready",
        "ready_for_wash_clean_photos",
        "ready_for_delivery",
    ]
    session.get.side_effect = [
        _response(_existing_lists()),
        _response({"value": old_operations}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
        _response({"value": old_operations}),
        _response(_existing_lists()),
        _response({"value": _actual_columns(VEHICLE_OPERATIONS_LIST)}),
        _response({"value": _actual_columns(VEHICLE_EVENTS_LIST)}),
    ]
    session.patch.return_value = _response({}, status=200)
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    report = provisioner.apply_final_finish_delivered_schema_upgrade(
        confirmation=FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION,
    )

    assert report.ready is True
    assert session.post.call_count == 0
    assert session.patch.call_args.args[0].endswith("/columns/FinalFinishStatus-id")
    assert session.patch.call_args.kwargs["json"]["choice"]["choices"] == [
        "not_ready",
        "ready_for_wash_clean_photos",
        "ready_for_delivery",
        "delivered",
    ]


def test_final_finish_delivered_upgrade_requires_exact_confirmation_without_network():
    session = MagicMock()
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError, match="exactly equal"):
        provisioner.apply_final_finish_delivered_schema_upgrade(confirmation="yes")

    session.get.assert_not_called()
    session.patch.assert_not_called()
    session.post.assert_not_called()


def test_create_sends_one_complete_list_payload():
    session = MagicMock()
    session.post.return_value = _response({}, status=201)
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    provisioner._create_list(VEHICLE_EVENTS_LIST)

    request = session.post.call_args
    assert request.args[0].endswith("/sites/site-id/lists")
    assert request.kwargs["json"] == VEHICLE_EVENTS_LIST.graph_create_payload()
    assert request.kwargs["headers"]["Authorization"] == "Bearer TOKEN"


def test_graph_exception_does_not_expose_request_url():
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError(
        "failed at https://example.invalid/?token=do-not-leak"
    )
    provisioner = OperationsListProvisioner(
        token="TOKEN", site_id="site-id", session=session,
    )

    with pytest.raises(OperationsListProvisioningError) as raised:
        provisioner.inspect()

    assert "do-not-leak" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_msal_client_accepts_one_time_scope_without_changing_defaults():
    client = object.__new__(MsalClient)
    client._last_id_token_claims = {}
    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "account-1"}]
    app.acquire_token_silent.return_value = {"access_token": "TOKEN"}
    client._app = app

    assert client.acquire_token(
        scopes=("Sites.Manage.All",),
        interactive_ok=False,
    ) == "TOKEN"
    assert app.acquire_token_silent.call_args.kwargs["scopes"] == ["Sites.Manage.All"]


def test_macos_msal_cache_coalesces_mutations_into_one_keychain_save(tmp_path):
    class _Persistence:
        is_encrypted = True

        def __init__(self):
            self.loads = 0
            self.saved: list[str] = []

        def get_location(self):
            return str(tmp_path / "msal_token_cache.bin")

        def load(self):
            self.loads += 1
            return "{}"

        def save(self, content):
            self.saved.append(content)

    persistence = _Persistence()
    cache = _SessionPersistedTokenCache(persistence)

    with cache.batch():
        cache.has_state_changed = True
        with cache.batch():
            cache.has_state_changed = True

    with cache.batch():
        pass

    assert persistence.loads == 1
    assert len(persistence.saved) == 1
    assert cache.is_encrypted is True


def test_msal_client_batches_one_complete_token_operation():
    class _Cache:
        batches = 0

        @contextmanager
        def batch(self):
            self.batches += 1
            yield

    client = object.__new__(MsalClient)
    client._last_id_token_claims = {}
    client._cache = _Cache()
    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "account-1"}]
    app.acquire_token_silent.return_value = {"access_token": "TOKEN"}
    client._app = app

    assert client.acquire_token(interactive_ok=False) == "TOKEN"
    assert client._cache.batches == 1


def test_msal_client_retains_validated_app_role_claims_in_memory():
    client = object.__new__(MsalClient)
    client._last_id_token_claims = {}
    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "account-1"}]
    app.acquire_token_silent.return_value = {
        "access_token": "TOKEN",
        "id_token_claims": {"roles": ["OperationsViewer", "PartsEditor"]},
    }
    client._app = app

    assert client.acquire_token(interactive_ok=False) == "TOKEN"
    assert client.get_app_roles() == frozenset({"OperationsViewer", "PartsEditor"})

    client.signout()
    assert client.get_app_roles() == frozenset()


def test_msal_client_recovers_roles_from_encrypted_cache_hit(monkeypatch):
    client = object.__new__(MsalClient)
    client._last_id_token_claims = {}
    client._config = SimpleNamespace(client_id="client-id")
    app = MagicMock()
    account = {
        "home_account_id": "account-1",
        "environment": "login.microsoftonline.com",
        "realm": "tenant-id",
    }
    app.get_accounts.return_value = [account]
    app.acquire_token_silent.return_value = {"access_token": "TOKEN"}
    client._app = app
    cache = MagicMock()
    cache.CredentialType.ID_TOKEN = "IdToken"
    cache.search.return_value = [{"secret": "cached-id-token"}]
    client._cache = cache
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.msal_client.decode_id_token",
        lambda token, *, client_id: {
            "aud": client_id,
            "roles": ["OperationsViewer"],
        } if token == "cached-id-token" else {},
    )

    assert client.acquire_token(interactive_ok=False) == "TOKEN"
    assert client.get_app_roles() == frozenset({"OperationsViewer"})
    cache.search.assert_called_once_with("IdToken", query={
        "home_account_id": "account-1",
        "environment": "login.microsoftonline.com",
        "realm": "tenant-id",
        "client_id": "client-id",
    })
