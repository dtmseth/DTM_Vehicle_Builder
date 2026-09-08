from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dtm_buildsheet.app.adapters import OperationsConflictError
from dtm_buildsheet.app.adapters.memory_operations_repository import (
    InMemoryOperationsRepository,
)
from dtm_buildsheet.app.services.operations_projection_service import (
    OperationsProjectSyncService,
    OperationsProjectionPreviewService,
    builder_vehicle_projection,
    project_vehicle_projections,
)
from dtm_buildsheet.app.services.operations_service import (
    OperationsAuthorizationError,
    OperationsService,
    OperationsValidationError,
)
from dtm_buildsheet.domain.operations_models import (
    BuilderVehicleProjection,
    OperationsActor,
    OperationsEventType,
    OperationsSource,
    ProjectState,
)
from dtm_buildsheet.domain.operations_policy import AppRole
from dtm_buildsheet.domain.project_models import (
    BuildUnit,
    CustomerInfo,
    IndividualUnit,
    ProjectRecord,
)


NOW = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)


def _actor(*roles: AppRole) -> OperationsActor:
    return OperationsActor(
        user_id="entra-1",
        display_name="Test User",
        roles=frozenset(role.value for role in roles),
    )


def _project(
    *,
    project_id: str = "project-1",
    vehicle_id: str = "vehicle-1",
    unit_number: str = "21",
    vin: str = "1ftfw1e50nfa12345",
    status: str = "finalized",
    project_status: str = "active",
) -> ProjectRecord:
    return ProjectRecord(
        project_id=project_id,
        created_at="2026-09-01T12:00:00+00:00",
        updated_at="2026-09-07T12:00:00+00:00",
        project_status=project_status,
        customer=CustomerInfo(
            agency="Example Police Department",
            agency_id="agency-1",
            agency_abbreviation="EPD",
            build_year="2027",
            sales_rep="Alex Sales",
            sales_rep_id="sales-1",
        ),
        build_units=[BuildUnit(
            unit_id="group-1",
            vehicle_model="Police Interceptor Utility",
            build_type="Patrol",
            individuals=[IndividualUnit(
                individual_id=vehicle_id,
                unit_number=unit_number,
                vin=vin,
                status=status,
                finalized_at="2026-09-06T18:30:00+00:00",
            )],
        )],
    )


def _projection(project: ProjectRecord | None = None) -> BuilderVehicleProjection:
    source = project or _project()
    return builder_vehicle_projection(
        source,
        source.build_units[0],
        source.build_units[0].individuals[0],
        ordinal=1,
    )


def _service(repository: InMemoryOperationsRepository) -> OperationsService:
    counter = iter(range(20))
    return OperationsService(
        repository,
        clock=lambda: NOW,
        event_id_factory=lambda: f"event-{next(counter)}",
    )


def test_builder_projection_uses_opaque_id_full_vin_and_current_finalization():
    projection = _projection()

    assert projection.vehicle_id == "vehicle-1"
    assert projection.vin == "1FTFW1E50NFA12345"
    assert projection.vehicle_label == "2027 EPD PIU - Patrol - Unit 21 - VIN A12345"
    assert projection.assigned_salesperson_id == "sales-1"
    assert projection.build_finalized is True
    assert projection.build_finalized_at == "2026-09-06T18:30:00Z"

    reopened = _projection(_project(status="reopened"))
    assert reopened.build_finalized is False
    assert reopened.build_finalized_at == ""

    completed = _projection(_project(project_status="completed"))
    assert completed.project_state.value == "completed"


def test_builder_projection_normalizes_graph_datetime_precision():
    project = _project()
    individual = project.build_units[0].individuals[0]
    individual.finalized_at = "2026-09-02T01:28:03.842674+00:00"

    projection = _projection(project)

    assert projection.build_finalized_at == "2026-09-02T01:28:03Z"
    repository = InMemoryOperationsRepository()
    service = _service(repository)
    service.upsert_builder_projection(
        projection,
        actor=_actor(AppRole.APP_ADMIN),
        request_id="create-normalized",
        source_client="builder_desktop",
    )
    assert service.projection_changes(repository.get_vehicle("vehicle-1"), projection) == {}


def test_projection_upsert_preserves_operations_fields_and_records_exact_changes():
    repository = InMemoryOperationsRepository()
    service = _service(repository)
    created = service.upsert_builder_projection(
        _projection(),
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="projection-create",
        source_client=OperationsSource.BUILDER_DESKTOP,
    )
    service.change_status(
        vehicle_id="vehicle-1",
        workstream="parts",
        new_status="received",
        actor=_actor(AppRole.PARTS_EDITOR),
        request_id="parts-received",
        source_client=OperationsSource.BUILDER_DESKTOP,
    )

    changed = _projection(_project(unit_number="22"))
    refreshed = service.upsert_builder_projection(
        changed,
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="projection-refresh",
        source_client=OperationsSource.BUILDER_DESKTOP,
        expected_revision=1,
    )

    assert created.record.revision == 0
    assert refreshed.record.revision == 2
    assert refreshed.record.unit_number == "22"
    assert refreshed.record.parts_status == "received"
    assert refreshed.event is not None
    assert refreshed.event.event_type == OperationsEventType.PROJECTION_REFRESHED
    assert '"unit_number":"21"' in refreshed.event.previous_value
    assert '"unit_number":"22"' in refreshed.event.new_value
    assert [event.event_type for event in repository.list_events("vehicle-1")] == [
        OperationsEventType.RECORD_CREATED,
        OperationsEventType.STATUS_CHANGED,
        OperationsEventType.PROJECTION_REFRESHED,
    ]


def test_unchanged_projection_is_noop_and_different_project_is_rejected():
    repository = InMemoryOperationsRepository()
    service = _service(repository)
    projection = _projection()
    service.upsert_builder_projection(
        projection,
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="create",
        source_client="builder_desktop",
    )

    unchanged = service.upsert_builder_projection(
        projection,
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="same-data",
        source_client="builder_desktop",
    )
    assert unchanged.unchanged is True
    assert len(repository.list_events("vehicle-1")) == 1

    moved = BuilderVehicleProjection(
        **{**projection.__dict__, "project_id": "another-project"}
    )
    with pytest.raises(OperationsConflictError, match="different project"):
        service.upsert_builder_projection(
            moved,
            actor=_actor(AppRole.BUILDER_EDITOR),
            request_id="move",
            source_client="builder_desktop",
        )


def test_reviewed_project_merge_can_rebind_vehicle_without_losing_status_history():
    repository = InMemoryOperationsRepository()
    service = _service(repository)
    projection = _projection()
    service.upsert_builder_projection(
        projection,
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="create-before-merge",
        source_client="builder_desktop",
    )
    service.change_status(
        vehicle_id="vehicle-1",
        workstream="parts",
        new_status="received",
        actor=_actor(AppRole.PARTS_EDITOR),
        request_id="parts-before-merge",
        source_client="builder_desktop",
    )
    moved = BuilderVehicleProjection(
        **{**projection.__dict__, "project_id": "completed-project"}
    )

    rebound = service.upsert_builder_projection(
        moved,
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="reviewed-project-merge",
        source_client="builder_desktop",
        expected_revision=1,
        allow_project_rebind=True,
    )

    assert rebound.record.project_id == "completed-project"
    assert rebound.record.parts_status == "received"
    assert rebound.event.project_id == "completed-project"
    assert len(repository.list_events("vehicle-1")) == 3


def test_preview_is_read_only_and_classifies_new_update_and_current():
    repository = InMemoryOperationsRepository()
    service = _service(repository)
    current_project = _project(vehicle_id="current-vehicle")
    update_project = _project(vehicle_id="update-vehicle", unit_number="10")
    service.upsert_builder_projection(
        _projection(current_project),
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="current-create",
        source_client="builder_desktop",
    )
    service.upsert_builder_projection(
        _projection(update_project),
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="update-create",
        source_client="builder_desktop",
    )
    update_project.build_units[0].individuals[0].unit_number = "11"
    new_project = _project(vehicle_id="new-vehicle")
    event_counts = {
        vehicle_id: len(repository.list_events(vehicle_id))
        for vehicle_id in ("current-vehicle", "update-vehicle")
    }

    payload = OperationsProjectionPreviewService(repository).preview(
        [current_project, update_project, new_project],
        _actor(AppRole.APP_ADMIN),
    )

    assert payload["read_only"] is True
    assert payload["writes_enabled"] is False
    assert payload["counts"] == {
        "builder_vehicles": 3,
        "new": 1,
        "updates": 1,
        "current": 1,
        "operations_only": 0,
    }
    by_id = {item["vehicle_id"]: item for item in payload["vehicles"]}
    assert by_id["new-vehicle"]["projection_state"] == "new"
    assert by_id["update-vehicle"]["changed_fields"] == [
        "vehicle name", "unit number", "vehicle label",
    ]
    assert by_id["current-vehicle"]["projection_state"] == "current"
    assert event_counts == {
        vehicle_id: len(repository.list_events(vehicle_id))
        for vehicle_id in event_counts
    }


def test_preview_requires_builder_authority_and_duplicate_ids_fail_closed():
    repository = InMemoryOperationsRepository()
    with pytest.raises(OperationsAuthorizationError, match="projects.edit"):
        OperationsProjectionPreviewService(repository).preview(
            [_project()],
            _actor(AppRole.OPERATIONS_VIEWER),
        )

    with pytest.raises(OperationsValidationError, match="Duplicate"):
        project_vehicle_projections([
            _project(project_id="project-1", vehicle_id="same-id"),
            _project(project_id="project-2", vehicle_id="same-id"),
        ])


def test_project_sync_preserves_workstreams_updates_lifecycle_and_deletes():
    repository = InMemoryOperationsRepository()
    actor = _actor(AppRole.APP_ADMIN)
    project = _project()
    sync = OperationsProjectSyncService(repository)

    first = sync.sync_project(project, actor)
    assert first == {"ok": True, "created": 1, "updated": 0, "unchanged": 0}
    OperationsService(repository).change_status(
        vehicle_id="vehicle-1",
        workstream="parts",
        new_status="ordered",
        actor=actor,
        request_id="parts-ordered",
        source_client="builder_desktop",
    )
    project.build_units[0].individuals[0].unit_number = "22"
    second = sync.sync_project(project, actor)

    record = repository.get_vehicle("vehicle-1")
    assert second == {"ok": True, "created": 0, "updated": 1, "unchanged": 0}
    assert record.unit_number == "22"
    assert record.parts_status == "ordered"

    project.project_status = "inactive"
    assert sync.sync_lifecycle(project, actor)["updated"] == 1
    assert repository.get_vehicle("vehicle-1").project_state == ProjectState.INACTIVE

    deleted = sync.delete_project(project.project_id, actor)
    assert deleted["records_deleted"] == 1
    assert deleted["events_deleted"] == 4
    assert repository.get_vehicle("vehicle-1") is None
