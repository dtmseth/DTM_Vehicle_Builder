from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.adapters.cloud.m365_identity_provider import M365IdentityProvider
from dtm_buildsheet.app.adapters.interfaces import UserIdentity
from dtm_buildsheet.app.adapters.memory_operations_repository import (
    InMemoryOperationsRepository,
)
from dtm_buildsheet.app.adapters.wiring import build_local_bundle, set_active_bundle
from dtm_buildsheet.app.routes.operations import route_operations
from dtm_buildsheet.app.services.operations_access_service import (
    actor_from_access_session,
    describe_access_session,
)
from dtm_buildsheet.app.services.operations_read_service import OperationsReadService
from dtm_buildsheet.app.services.operations_service import (
    OperationsAuthorizationError,
    OperationsService,
)
from dtm_buildsheet.domain.operations_models import (
    AcceptanceStatus,
    OperationsActor,
    OperationsSource,
    ProjectState,
    VehicleOperations,
)
from dtm_buildsheet.domain.operations_policy import AppRole
from dtm_buildsheet.domain.project_models import (
    BuildUnit,
    CustomerInfo,
    IndividualUnit,
    ProjectRecord,
)
from dtm_buildsheet.inputs.project_entry import load_project, save_project
from dtm_buildsheet.paths import AppPaths
from tests.contract.harness import call_route


NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)


class _Identity:
    def __init__(self, user: UserIdentity | None, *, raises: bool = False) -> None:
        self.user = user
        self.raises = raises

    def current_user(self):
        if self.raises:
            raise RuntimeError("identity offline")
        return self.user

    def is_signed_in(self):
        return self.user is not None

    def signin(self, *, force_account_picker=False):
        del force_account_picker
        return self.user

    def signout(self):
        self.user = None


def _user(*roles: str, provider: str = "m365") -> UserIdentity:
    return UserIdentity(
        user_id="entra-1",
        display_name="Test User",
        email="test@example.invalid",
        provider=provider,
        roles=frozenset(roles),
    )


def _bundle(*, user: UserIdentity | None, operations=None):
    repository = operations if operations is not None else InMemoryOperationsRepository()
    return replace(
        build_local_bundle(),
        identity=_Identity(user),
        operations=repository,
        operations_writer=repository,
    )


def _builder_project() -> ProjectRecord:
    return ProjectRecord(
        project_id="project-1",
        created_at="2026-09-01T12:00:00+00:00",
        updated_at="2026-09-04T12:00:00+00:00",
        customer=CustomerInfo(
            agency="Example PD",
            agency_abbreviation="EPD",
            build_year="2027",
        ),
        build_units=[BuildUnit(
            unit_id="group-1",
            vehicle_model="PIU",
            build_type="Patrol",
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                unit_number="21",
                vin="1FTFW1E50NFA12345",
            )],
        )],
    )


@pytest.fixture(autouse=True)
def _reset_bundle():
    yield
    wiring._active_bundle = None  # noqa: SLF001


def test_access_session_maps_known_roles_and_ignores_unknown_values():
    session = describe_access_session(
        bundle=_bundle(user=_user("PartsEditor", "FutureRole")),
        cloud_enabled=True,
    )

    assert session["authenticated"] is True
    assert session["roles"] == ["PartsEditor"]
    assert "operations.view" in session["capabilities"]
    assert "operations.parts.update" in session["capabilities"]
    assert "operations.shop.update" not in session["capabilities"]
    assert "projects.view" in session["capabilities"]
    assert session["default_workspace"] == "operations"


def test_access_session_fails_closed_for_cloud_fallback_identity():
    session = describe_access_session(
        bundle=_bundle(user=_user("AppAdmin", provider="local")),
        cloud_enabled=True,
    )

    assert session["authenticated"] is False
    assert session["capabilities"] == []
    assert session["reason"] == "identity_unavailable"


def test_cloud_off_local_identity_is_admin_for_development():
    session = describe_access_session(
        bundle=build_local_bundle(),
        cloud_enabled=False,
    )

    assert session["authenticated"] is True
    assert session["roles"] == ["AppAdmin"]
    assert "operations.view" in session["capabilities"]


def test_m365_identity_uses_only_known_validated_role_claims(monkeypatch):
    class _Msal:
        roles = frozenset({"ShopEditor", "UnknownFutureRole"})

        def acquire_token(self, **kwargs):
            del kwargs
            return "TOKEN"

        def get_app_roles(self):
            return self.roles

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "entra-1",
                "displayName": "Shop User",
                "mail": "shop@example.invalid",
            }

    msal = _Msal()
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.m365_identity_provider.requests.get",
        lambda *args, **kwargs: _Response(),
    )
    provider = M365IdentityProvider(msal)

    user = provider.signin()
    assert user.roles == frozenset({"ShopEditor"})

    msal.roles = frozenset({"OperationsViewer"})
    assert provider.current_user().roles == frozenset({"OperationsViewer"})


def test_actor_requires_authenticated_session():
    assert actor_from_access_session({"authenticated": False}) is None
    actor = actor_from_access_session({
        "authenticated": True,
        "user": {"user_id": "u1", "display_name": "Person"},
        "roles": ["OperationsViewer"],
    })
    assert actor == OperationsActor(
        user_id="u1",
        display_name="Person",
        roles=frozenset({"OperationsViewer"}),
    )


def test_read_service_returns_derived_compact_summaries_and_counts():
    repository = InMemoryOperationsRepository()
    service = OperationsService(
        repository,
        clock=lambda: NOW,
        event_id_factory=lambda: "event-1",
    )
    actor = OperationsActor(
        user_id="entra-1",
        display_name="Test User",
        roles=frozenset({AppRole.APP_ADMIN.value}),
    )
    service.create_vehicle(
        vehicle_id="vehicle-1",
        project_id="project-1",
        actor=actor,
        request_id="create-1",
        source_client=OperationsSource.BUILDER_DESKTOP,
        agency_name="Example PD",
        vehicle_label="2027 Example PD PIU - Unit 21",
    )
    record = repository.get_vehicle("vehicle-1")
    assert record is not None
    record.acceptance_status = AcceptanceStatus.ACCEPTED
    record.vin = "1FTFW1E50NFA12345"
    record.project_state = ProjectState.ACTIVE
    repository._records["vehicle-1"] = record  # noqa: SLF001 - focused projection fixture

    payload = OperationsReadService(repository).list_vehicle_summaries(actor)

    assert payload["read_only"] is True
    assert payload["counts"]["active"] == 1
    assert payload["counts"]["unscheduled"] == 1
    assert payload["vehicles"][0]["vin"] == "1FTFW1E50NFA12345"
    assert payload["vehicles"][0]["schedule_bucket"] == "unscheduled"
    assert "created_by_id" not in payload["vehicles"][0]


def test_read_service_rejects_actor_without_view_capability():
    actor = OperationsActor(
        user_id="entra-1",
        display_name="Test User",
        roles=frozenset(),
    )
    with pytest.raises(OperationsAuthorizationError, match="operations.view"):
        OperationsReadService(InMemoryOperationsRepository()).list_vehicle_summaries(actor)


def test_read_service_hides_projects_excluded_by_builder_lifecycle():
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    actor = OperationsActor(
        user_id="entra-1",
        display_name="Test User",
        roles=frozenset({AppRole.APP_ADMIN.value}),
    )

    payload = OperationsReadService(repository).list_vehicle_summaries(
        actor,
        hidden_project_ids=frozenset({"project-1"}),
    )

    assert payload["vehicles"] == []
    assert payload["counts"]["total"] == 0


def test_read_service_derives_deadline_for_legacy_direct_to_parts_ready_row():
    repository = InMemoryOperationsRepository()
    repository._records["vehicle-1"] = VehicleOperations(  # noqa: SLF001
        vehicle_id="vehicle-1",
        project_id="project-1",
        vehicle_available_date="2026-09-07T07:00:00Z",
        parts_status="parts_ready",
        parts_ready_at="2026-09-07T19:57:41Z",
    )
    actor = OperationsActor(
        user_id="entra-1",
        display_name="Test User",
        roles=frozenset({AppRole.APP_ADMIN.value}),
    )

    payload = OperationsReadService(repository).list_vehicle_summaries(actor)

    assert payload["vehicles"][0]["commitment_start_date"] == "2026-09-07"
    assert payload["vehicles"][0]["must_deliver_by_date"] == "2026-11-06"


def test_read_service_returns_complete_browser_safe_history_newest_first():
    repository = InMemoryOperationsRepository()
    event_ids = iter(("event-1", "event-2"))
    service = OperationsService(
        repository,
        clock=lambda: NOW,
        event_id_factory=lambda: next(event_ids),
    )
    actor = OperationsActor(
        user_id="entra-1",
        display_name="Test User",
        roles=frozenset({AppRole.APP_ADMIN.value}),
    )
    service.create_vehicle(
        vehicle_id="vehicle-1",
        project_id="project-1",
        actor=actor,
        request_id="create-request",
        source_client=OperationsSource.BUILDER_DESKTOP,
    )
    service.change_status(
        vehicle_id="vehicle-1",
        workstream="parts",
        new_status="received",
        actor=actor,
        request_id="status-request",
        source_client=OperationsSource.BUILDER_DESKTOP,
        expected_revision=0,
    )

    payload = OperationsReadService(repository).list_vehicle_history("vehicle-1", actor)

    assert payload["count"] == 2
    assert [event["event_type"] for event in payload["events"]] == [
        "status_changed",
        "record_created",
    ]
    assert payload["events"][0]["previous_value"] == ""
    assert payload["events"][0]["new_value"] == "received"
    assert payload["events"][0]["actor_display_name"] == "Test User"
    assert "actor_id" not in payload["events"][0]
    assert "request_id" not in payload["events"][0]


def test_operations_routes_gate_the_list_server_side(monkeypatch, tmp_path):
    bundle = _bundle(user=_user("OperationsViewer"))
    set_active_bundle(bundle)
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    paths = AppPaths(workspace_dir=tmp_path)

    status, session, handled = call_route(
        route_operations, "GET", "/api/operations/session", {}, paths,
    )
    assert (status, handled) == (200, True)
    assert session["capabilities"] == ["operations.view", "projects.view"]

    status, payload, handled = call_route(
        route_operations, "GET", "/api/operations/vehicles", {}, paths,
    )
    assert (status, handled) == (200, True)
    assert payload == {
        "ok": True,
        "read_only": True,
        "vehicles": [],
        "counts": {
            "total": 0,
            "active": 0,
            "inactive": 0,
            "completed": 0,
            "prospective": 0,
            "unscheduled": 0,
            "scheduled": 0,
        },
    }


def test_operations_vehicle_route_hides_builder_inactive_project_even_when_projection_is_stale(
    monkeypatch,
    tmp_path,
):
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    project = _builder_project()
    project.project_status = "inactive"
    set_active_bundle(_bundle(user=_user("OperationsViewer"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    monkeypatch.setattr(
        "dtm_buildsheet.app.routes.operations.list_projects",
        lambda paths: [project],
    )

    status, payload, handled = call_route(
        route_operations,
        "GET",
        "/api/operations/vehicles",
        {},
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (200, True)
    assert payload["vehicles"] == []
    assert payload["counts"]["total"] == 0


def test_operations_history_route_is_viewer_accessible_and_read_only(monkeypatch, tmp_path):
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    bundle = replace(
        _bundle(user=_user("OperationsViewer"), operations=repository),
        operations_writer=None,
    )
    set_active_bundle(bundle)
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations,
        "GET",
        "/api/operations/history?vehicle_id=vehicle-1",
        {},
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (200, True)
    assert payload["vehicle_id"] == "vehicle-1"
    assert payload["count"] == 1
    assert payload["events"][0]["event_type"] == "record_created"


@pytest.mark.parametrize(
    ("query", "expected_status"),
    [("", 400), ("?vehicle_id=missing", 404)],
)
def test_operations_history_route_rejects_missing_or_unknown_vehicle(
    monkeypatch,
    tmp_path,
    query,
    expected_status,
):
    repository = InMemoryOperationsRepository()
    set_active_bundle(_bundle(user=_user("OperationsViewer"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations,
        "GET",
        f"/api/operations/history{query}",
        {},
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (expected_status, True)
    assert "vehicle" in payload["error"].lower()


def test_operations_vehicle_route_denies_unassigned_user(monkeypatch, tmp_path):
    set_active_bundle(_bundle(user=_user()))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations,
        "GET",
        "/api/operations/vehicles",
        {},
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (403, True)
    assert "not been assigned" in payload["error"]


def test_projection_preview_route_maps_builder_vehicles_without_writing(
    monkeypatch,
    tmp_path,
):
    repository = InMemoryOperationsRepository()
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    project = _builder_project()
    monkeypatch.setattr(
        "dtm_buildsheet.app.routes.operations.list_projects",
        lambda paths: [project],
    )

    status, payload, handled = call_route(
        route_operations,
        "GET",
        "/api/operations/projection-preview",
        {},
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (200, True)
    assert payload["read_only"] is True
    assert payload["writes_enabled"] is True
    assert payload["write_mode"] == "single_vehicle_create_pilot"
    assert payload["counts"]["new"] == 1
    assert payload["vehicles"][0]["vin"] == "1FTFW1E50NFA12345"
    assert repository.list_vehicles() == []


def test_projection_preview_route_requires_project_edit_capability(monkeypatch, tmp_path):
    set_active_bundle(_bundle(user=_user("OperationsViewer")))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations,
        "GET",
        "/api/operations/projection-preview",
        {},
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (403, True)
    assert "cannot preview" in payload["error"]


def test_projection_pilot_creates_exactly_one_confirmed_builder_vehicle(
    monkeypatch,
    tmp_path,
):
    repository = InMemoryOperationsRepository()
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    monkeypatch.setattr(
        "dtm_buildsheet.app.routes.operations.list_projects",
        lambda paths: [_builder_project()],
    )

    status, payload, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/projection-pilot",
        {
            "vehicle_id": "vehicle-1",
            "confirmation": "add:vehicle-1",
            "request_id": "pilot-request-1",
        },
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (200, True)
    assert payload == {
        "ok": True,
        "created": True,
        "duplicate": False,
        "vehicle_id": "vehicle-1",
        "vehicle_label": "2027 EPD PIU - Patrol - Unit 21 - VIN A12345",
        "project_state": "active",
        "revision": 0,
    }
    record = repository.get_vehicle("vehicle-1")
    assert record is not None
    assert record.vin == "1FTFW1E50NFA12345"
    assert len(repository.list_events("vehicle-1")) == 1

    # Retrying the exact browser request is idempotent.
    status, retry, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/projection-pilot",
        {
            "vehicle_id": "vehicle-1",
            "confirmation": "add:vehicle-1",
            "request_id": "pilot-request-1",
        },
        AppPaths(workspace_dir=tmp_path),
    )
    assert (status, handled) == (200, True)
    assert retry["duplicate"] is True
    assert retry["created"] is False
    assert len(repository.list_events("vehicle-1")) == 1


def test_projection_pilot_rejects_missing_confirmation_and_existing_row(
    monkeypatch,
    tmp_path,
):
    repository = InMemoryOperationsRepository()
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    monkeypatch.setattr(
        "dtm_buildsheet.app.routes.operations.list_projects",
        lambda paths: [_builder_project()],
    )
    paths = AppPaths(workspace_dir=tmp_path)

    status, payload, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/projection-pilot",
        {
            "vehicle_id": "vehicle-1",
            "request_id": "pilot-request-1",
        },
        paths,
    )
    assert (status, handled) == (400, True)
    assert "explicitly confirmed" in payload["error"]
    assert repository.list_vehicles() == []

    confirmed = {
        "vehicle_id": "vehicle-1",
        "confirmation": "add:vehicle-1",
        "request_id": "pilot-request-1",
    }
    assert call_route(
        route_operations,
        "POST",
        "/api/operations/projection-pilot",
        confirmed,
        paths,
    )[0] == 200
    confirmed["request_id"] = "different-request"
    status, payload, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/projection-pilot",
        confirmed,
        paths,
    )
    assert (status, handled) == (409, True)
    assert "already has" in payload["error"]
    assert len(repository.list_events("vehicle-1")) == 1


def test_projection_pilot_requires_project_edit_capability(monkeypatch, tmp_path):
    repository = InMemoryOperationsRepository()
    set_active_bundle(_bundle(user=_user("OperationsViewer"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    monkeypatch.setattr(
        "dtm_buildsheet.app.routes.operations.list_projects",
        lambda paths: [_builder_project()],
    )

    status, payload, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/projection-pilot",
        {
            "vehicle_id": "vehicle-1",
            "confirmation": "add:vehicle-1",
            "request_id": "pilot-request-1",
        },
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (403, True)
    assert "cannot add" in payload["error"]
    assert repository.list_vehicles() == []


def _seed_operations_vehicle(repository: InMemoryOperationsRepository) -> None:
    OperationsService(repository).create_vehicle(
        vehicle_id="vehicle-1",
        project_id="project-1",
        actor=OperationsActor(
            user_id="seed-user",
            display_name="Seed User",
            roles=frozenset({AppRole.APP_ADMIN.value}),
        ),
        request_id="seed-request",
        source_client=OperationsSource.BUILDER_DESKTOP,
        agency_name="Example PD",
        vehicle_label="2027 Example PD PIU - Unit 21",
    )


def test_status_route_updates_one_vehicle_with_revision_and_history(monkeypatch, tmp_path):
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/status",
        {
            "vehicle_id": "vehicle-1",
            "workstream": "parts",
            "new_status": "received",
            "expected_revision": 0,
            "request_id": "status-request-1",
        },
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (200, True)
    assert payload == {
        "ok": True,
        "vehicle_id": "vehicle-1",
        "workstream": "parts",
        "status": "received",
        "revision": 1,
        "changed": True,
        "unchanged": False,
        "duplicate": False,
    }
    assert repository.get_vehicle("vehicle-1").parts_status == "received"
    assert len(repository.list_events("vehicle-1")) == 2


def test_status_route_dispatches_acceptance_and_availability(monkeypatch, tmp_path):
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    paths = AppPaths(workspace_dir=tmp_path)

    status, accepted, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/status",
        {
            "vehicle_id": "vehicle-1",
            "workstream": "acceptance",
            "new_status": "accepted",
            "expected_revision": 0,
            "request_id": "accept-request",
        },
        paths,
    )
    assert (status, handled) == (200, True)
    assert accepted["status"] == "accepted"
    assert accepted["revision"] == 1

    status, availability, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/status",
        {
            "vehicle_id": "vehicle-1",
            "workstream": "availability",
            "new_status": "ready_for_pickup",
            "effective_date": "2026-09-07",
            "expected_revision": 1,
            "request_id": "availability-request",
        },
        paths,
    )
    assert (status, handled) == (200, True)
    assert availability["status"] == "ready_for_pickup"
    record = repository.get_vehicle("vehicle-1")
    assert record.vehicle_available_date == "2026-09-07"
    assert record.revision == 2


def test_schedule_route_updates_an_accepted_vehicle(monkeypatch, tmp_path):
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    actor = OperationsActor(
        user_id="seed-user",
        display_name="Seed User",
        roles=frozenset({AppRole.APP_ADMIN.value}),
    )
    accepted = OperationsService(repository).change_acceptance(
        vehicle_id="vehicle-1",
        new_status="accepted",
        acceptance_source="manual",
        actor=actor,
        request_id="accept-before-schedule",
        source_client=OperationsSource.BUILDER_DESKTOP,
        expected_revision=0,
    )
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/schedule",
        {
            "vehicle_id": "vehicle-1",
            "scheduled_week_of": "2026-09-07",
            "planned_start_date": "2026-09-08",
            "target_finish_date": "2026-09-18",
            "expected_revision": accepted.record.revision,
            "request_id": "schedule-request",
        },
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (200, True)
    assert payload["scheduled_week_of"] == "2026-09-07"
    assert payload["planned_start_date"] == "2026-09-08"
    assert payload["target_finish_date"] == "2026-09-18"
    assert payload["schedule_bucket"] == "scheduled"
    assert payload["revision"] == 2
    assert len(repository.list_events("vehicle-1")) == 3


def test_schedule_route_allows_partial_pre_acceptance_edit_and_enforces_capability(monkeypatch, tmp_path):
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    paths = AppPaths(workspace_dir=tmp_path)
    body = {
        "vehicle_id": "vehicle-1",
        "scheduled_week_of": "2026-09-07",
        "planned_start_date": "",
        "target_finish_date": "",
        "expected_revision": 0,
        "request_id": "schedule-request",
    }
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations, "POST", "/api/operations/schedule", body, paths,
    )
    assert (status, handled) == (200, True)
    assert payload["scheduled_week_of"] == "2026-09-07"

    set_active_bundle(_bundle(user=_user("OperationsViewer"), operations=repository))
    body = {
        "vehicle_id": "vehicle-1",
        "target_finish_date": "2026-09-18",
        "expected_revision": 1,
        "request_id": "schedule-denied",
    }
    status, payload, handled = call_route(
        route_operations, "POST", "/api/operations/schedule", body, paths,
    )
    assert (status, handled) == (403, True)
    assert "cannot update" in payload["error"]


def test_status_route_rejects_stale_revision_and_unauthorized_role(monkeypatch, tmp_path):
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    paths = AppPaths(workspace_dir=tmp_path)
    body = {
        "vehicle_id": "vehicle-1",
        "workstream": "parts",
        "new_status": "partially_received",
        "expected_revision": 9,
        "request_id": "stale-request",
    }

    status, payload, handled = call_route(
        route_operations, "POST", "/api/operations/status", body, paths,
    )
    assert (status, handled) == (409, True)
    assert "another device" in payload["error"]
    assert repository.get_vehicle("vehicle-1").revision == 0

    set_active_bundle(_bundle(user=_user("OperationsViewer"), operations=repository))
    body["expected_revision"] = 0
    body["request_id"] = "unauthorized-request"
    status, payload, handled = call_route(
        route_operations, "POST", "/api/operations/status", body, paths,
    )
    assert (status, handled) == (403, True)
    assert "cannot update" in payload["error"]
    assert repository.get_vehicle("vehicle-1").revision == 0


@pytest.mark.parametrize("workstream", ["unknown", "schedule"])
def test_status_route_rejects_invalid_workstream(monkeypatch, tmp_path, workstream):
    repository = InMemoryOperationsRepository()
    _seed_operations_vehicle(repository)
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/status",
        {
            "vehicle_id": "vehicle-1",
            "workstream": workstream,
            "new_status": "scheduled",
            "expected_revision": 0,
            "request_id": "invalid-request",
        },
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled) == (400, True)
    assert "status" in payload["error"].lower()
    assert repository.get_vehicle("vehicle-1").revision == 0


def test_operations_unknown_post_route_is_not_handled(monkeypatch, tmp_path):
    set_active_bundle(_bundle(user=_user("AppAdmin")))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    status, payload, handled = call_route(
        route_operations,
        "POST",
        "/api/operations/unknown",
        {"vehicle_id": "should-not-write"},
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, payload, handled) == (None, None, False)


def test_final_finish_delivering_every_vehicle_moves_project_and_operations_to_completed(
    monkeypatch, tmp_path,
):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    paths = AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=projects_dir,
    )
    project = _builder_project()
    project.build_units[0].individuals.append(IndividualUnit(
        individual_id="vehicle-2",
        unit_number="22",
        vin="1FTFW1E50NFA12346",
    ))
    save_project(project, paths)

    repository = InMemoryOperationsRepository()
    actor = OperationsActor(
        user_id="seed-user",
        display_name="Seed User",
        roles=frozenset({AppRole.APP_ADMIN.value}),
    )
    for vehicle_id in ("vehicle-1", "vehicle-2"):
        OperationsService(repository).create_vehicle(
            vehicle_id=vehicle_id,
            project_id="project-1",
            actor=actor,
            request_id=f"seed-{vehicle_id}",
            source_client=OperationsSource.BUILDER_DESKTOP,
        )
    set_active_bundle(_bundle(user=_user("AppAdmin"), operations=repository))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)

    for index, vehicle_id in enumerate(("vehicle-1", "vehicle-2"), start=1):
        status, payload, handled = call_route(
            route_operations,
            "POST",
            "/api/operations/status",
            {
                "vehicle_id": vehicle_id,
                "workstream": "final_finish",
                "new_status": "delivered",
                "expected_revision": 0,
                "request_id": f"deliver-{vehicle_id}",
                "correction_reason": "Historical delivery entry",
            },
            paths,
        )
        assert (status, handled) == (200, True)
        assert bool(payload.get("project_auto_completed")) is (index == 2)

    assert load_project("project-1", paths).project_status == "completed"
    assert {
        record.project_state.value
        for record in repository.list_vehicles()
    } == {"completed"}
