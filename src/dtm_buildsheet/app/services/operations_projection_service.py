"""Builder-to-Operations projection planning and synchronization.

The preview remains read-only and the pilot remains available for legacy data.
Ordinary project saves now synchronize only Builder-owned projection fields.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from ...domain.operations_models import (
    BuilderVehicleProjection,
    OperationsActor,
    OperationsMutationResult,
    ProjectState,
    VehicleOperations,
)
from ...domain.operations_policy import Capability, has_capability
from ...domain.project_models import BuildUnit, IndividualUnit, ProjectRecord
from ...domain.vehicle_naming import vehicle_display_name
from ..adapters.interfaces import OperationsRepository
from .operations_service import (
    OperationsAuthorizationError,
    OperationsNotFoundError,
    OperationsService,
    OperationsValidationError,
)


_FIELD_LABELS = {
    "title": "vehicle name",
    "agency_id": "agency",
    "agency_name": "agency name",
    "build_year": "build year",
    "unit_number": "unit number",
    "vin": "VIN",
    "vehicle_label": "vehicle label",
    "assigned_salesperson_id": "salesperson",
    "assigned_salesperson_name": "salesperson name",
    "build_finalized": "build finalized",
    "build_finalized_at": "finalized date",
    "project_state": "project state",
}


def _canonical_sharepoint_datetime(value: str) -> str:
    """Match Graph's UTC, whole-second representation for stable comparisons."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationsValidationError(
            "Builder finalization date is not a valid timestamp"
        ) from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (
        moment.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def builder_vehicle_projection(
    project: ProjectRecord,
    build_unit: BuildUnit,
    individual: IndividualUnit,
    *,
    ordinal: int,
) -> BuilderVehicleProjection:
    """Map only Builder-owned data for one physical vehicle."""

    try:
        project_state = ProjectState(str(project.project_status or "active"))
    except ValueError:
        project_state = ProjectState.ACTIVE
    finalized = str(individual.status or "").strip() == "finalized"
    label = vehicle_display_name(project, build_unit, individual, ordinal=ordinal)
    return BuilderVehicleProjection(
        vehicle_id=str(individual.individual_id or "").strip(),
        project_id=str(project.project_id or "").strip(),
        title=label,
        agency_id=str(project.customer.agency_id or "").strip(),
        agency_name=str(project.customer.agency or "").strip(),
        build_year=str(project.customer.build_year or individual.year or "").strip(),
        unit_number=str(individual.unit_number or "").strip(),
        vin=str(individual.vin or "").strip().upper(),
        vehicle_label=label,
        assigned_salesperson_id=str(project.customer.sales_rep_id or "").strip(),
        assigned_salesperson_name=str(project.customer.sales_rep or "").strip(),
        build_finalized=finalized,
        build_finalized_at=(
            _canonical_sharepoint_datetime(individual.finalized_at)
            if finalized else ""
        ),
        project_state=project_state,
    )


def project_vehicle_projections(
    projects: Iterable[ProjectRecord],
) -> list[BuilderVehicleProjection]:
    """Return deterministic projections and reject duplicate opaque IDs."""

    projections: list[BuilderVehicleProjection] = []
    seen: set[str] = set()
    for project in projects:
        for build_unit in project.build_units:
            for ordinal, individual in enumerate(build_unit.individuals, start=1):
                projection = builder_vehicle_projection(
                    project,
                    build_unit,
                    individual,
                    ordinal=ordinal,
                )
                if not projection.vehicle_id:
                    raise OperationsValidationError(
                        "Builder vehicle ID is required for an Operations projection"
                    )
                if projection.vehicle_id in seen:
                    raise OperationsValidationError(
                        "Duplicate Builder vehicle ID prevents a safe Operations projection"
                    )
                seen.add(projection.vehicle_id)
                projections.append(projection)
    return sorted(projections, key=_projection_sort_key)


class OperationsProjectionPreviewService:
    """Compare Builder vehicles to Operations without repairing or writing."""

    def __init__(self, repository: OperationsRepository) -> None:
        self._repository = repository

    def preview(
        self,
        projects: Iterable[ProjectRecord],
        actor: OperationsActor,
    ) -> dict:
        if not str(actor.user_id or "").strip():
            raise OperationsAuthorizationError("A verified actor is required")
        if not has_capability(actor.roles, Capability.PROJECTS_EDIT):
            raise OperationsAuthorizationError(
                f"Missing capability: {Capability.PROJECTS_EDIT.value}"
            )

        projections = project_vehicle_projections(projects)
        current_records = {
            record.vehicle_id: record for record in self._repository.list_vehicles()
        }
        vehicles = [
            _preview_vehicle(projection, current_records.get(projection.vehicle_id))
            for projection in projections
        ]
        counts = {
            "builder_vehicles": len(vehicles),
            "new": sum(item["projection_state"] == "new" for item in vehicles),
            "updates": sum(item["projection_state"] == "update" for item in vehicles),
            "current": sum(item["projection_state"] == "current" for item in vehicles),
            "operations_only": len(set(current_records) - {
                projection.vehicle_id for projection in projections
            }),
        }
        return {
            "ok": True,
            "read_only": True,
            "writes_enabled": False,
            "vehicles": vehicles,
            "counts": counts,
        }


class OperationsProjectionPilotService:
    """Create one confirmed Operations record from current Builder data."""

    def __init__(self, repository: OperationsRepository) -> None:
        self._repository = repository

    def create_one(
        self,
        projects: Iterable[ProjectRecord],
        actor: OperationsActor,
        *,
        vehicle_id: str,
        confirmation: str,
        request_id: str,
        source_app_version: str = "",
    ) -> OperationsMutationResult:
        if not str(actor.user_id or "").strip():
            raise OperationsAuthorizationError("A verified actor is required")
        if not has_capability(actor.roles, Capability.PROJECTS_EDIT):
            raise OperationsAuthorizationError(
                f"Missing capability: {Capability.PROJECTS_EDIT.value}"
            )
        vehicle_id = str(vehicle_id or "").strip()
        if not vehicle_id:
            raise OperationsValidationError("Builder vehicle ID is required")
        if str(confirmation or "") != f"add:{vehicle_id}":
            raise OperationsValidationError(
                "The selected Builder vehicle must be explicitly confirmed"
            )
        request_id = str(request_id or "").strip()
        if not request_id:
            raise OperationsValidationError("A one-use request ID is required")

        projections = project_vehicle_projections(projects)
        projection = next(
            (item for item in projections if item.vehicle_id == vehicle_id),
            None,
        )
        if projection is None:
            raise OperationsNotFoundError(
                "The selected vehicle is no longer present in Builder"
            )

        # Deliberately use the create-only command. Existing Operations rows
        # cannot be refreshed through this pilot endpoint.
        return OperationsService(self._repository).create_vehicle(
            vehicle_id=projection.vehicle_id,
            project_id=projection.project_id,
            actor=actor,
            request_id=request_id,
            source_client="builder_desktop",
            title=projection.title,
            agency_id=projection.agency_id,
            agency_name=projection.agency_name,
            build_year=projection.build_year,
            unit_number=projection.unit_number,
            vin=projection.vin,
            vehicle_label=projection.vehicle_label,
            assigned_salesperson_id=projection.assigned_salesperson_id,
            assigned_salesperson_name=projection.assigned_salesperson_name,
            build_finalized=projection.build_finalized,
            build_finalized_at=projection.build_finalized_at,
            project_state=projection.project_state,
            source_app_version=source_app_version,
        )


class OperationsProjectSyncService:
    """Keep Builder-owned project facts synchronized without touching workstreams."""

    def __init__(self, repository: OperationsRepository) -> None:
        self._repository = repository

    def sync_project(
        self,
        project: ProjectRecord,
        actor: OperationsActor,
    ) -> dict:
        if not has_capability(actor.roles, Capability.PROJECTS_EDIT):
            raise OperationsAuthorizationError(
                f"Missing capability: {Capability.PROJECTS_EDIT.value}"
            )
        service = OperationsService(self._repository)
        current = {
            record.vehicle_id: record
            for record in self._repository.list_vehicles()
        }
        created = 0
        updated = 0
        unchanged = 0
        for projection in project_vehicle_projections([project]):
            existing = current.get(projection.vehicle_id)
            result = service.upsert_builder_projection(
                projection,
                actor=actor,
                request_id=str(uuid.uuid4()),
                source_client="builder_desktop",
                expected_revision=existing.revision if existing is not None else None,
            )
            current[projection.vehicle_id] = result.record
            if result.unchanged:
                unchanged += 1
            elif existing is None:
                created += 1
            else:
                updated += 1
        return {
            "ok": True,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
        }

    def sync_lifecycle(
        self,
        project: ProjectRecord,
        actor: OperationsActor,
        *,
        reason: str = "",
    ) -> dict:
        if not has_capability(actor.roles, Capability.PROJECTS_LIFECYCLE_UPDATE):
            raise OperationsAuthorizationError(
                f"Missing capability: {Capability.PROJECTS_LIFECYCLE_UPDATE.value}"
            )
        records = [
            record
            for record in self._repository.list_vehicles()
            if record.project_id == project.project_id
        ]
        service = OperationsService(self._repository)
        updated = 0
        unchanged = 0
        for record in records:
            result = service.change_project_state(
                vehicle_id=record.vehicle_id,
                new_state=project.project_status,
                actor=actor,
                request_id=str(uuid.uuid4()),
                source_client="builder_desktop",
                expected_revision=record.revision,
                reason=reason,
            )
            if result.unchanged:
                unchanged += 1
            else:
                updated += 1
        return {"ok": True, "updated": updated, "unchanged": unchanged}

    def delete_project(
        self,
        project_id: str,
        actor: OperationsActor,
    ) -> dict:
        if not has_capability(actor.roles, Capability.PROJECTS_EDIT):
            raise OperationsAuthorizationError(
                f"Missing capability: {Capability.PROJECTS_EDIT.value}"
            )
        records, events = self._repository.delete_project(project_id)
        return {"ok": True, "records_deleted": records, "events_deleted": events}


def _preview_vehicle(
    projection: BuilderVehicleProjection,
    current: VehicleOperations | None,
) -> dict:
    changes = (
        OperationsService.projection_changes(current, projection)
        if current is not None
        else {}
    )
    state = "new" if current is None else "update" if changes else "current"
    return {
        "vehicle_id": projection.vehicle_id,
        "project_id": projection.project_id,
        "vehicle_label": projection.vehicle_label,
        "agency_name": projection.agency_name,
        "build_year": projection.build_year,
        "unit_number": projection.unit_number,
        "vin": projection.vin,
        "project_state": projection.project_state.value,
        "build_finalized": projection.build_finalized,
        "build_finalized_at": projection.build_finalized_at,
        "projection_state": state,
        "current_revision": current.revision if current is not None else None,
        "changed_fields": [
            _FIELD_LABELS.get(field_name, field_name.replace("_", " "))
            for field_name in changes
        ],
    }


def _projection_sort_key(projection: BuilderVehicleProjection) -> tuple:
    state_rank = {
        ProjectState.ACTIVE: 0,
        ProjectState.INACTIVE: 1,
        ProjectState.COMPLETED: 2,
    }
    return (
        state_rank.get(projection.project_state, 9),
        projection.agency_name.casefold(),
        projection.vehicle_label.casefold(),
        projection.vehicle_id,
    )
