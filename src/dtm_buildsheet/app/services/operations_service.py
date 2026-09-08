"""Application service for authorized, timestamped operations mutations."""
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Callable

from ...domain.operations_models import (
    OPERATIONS_SCHEMA_VERSION,
    AcceptanceSource,
    AcceptanceStatus,
    BuilderVehicleProjection,
    FinalFinishStatus,
    OperationsActor,
    OperationsEvent,
    OperationsEventType,
    OperationsMutationResult,
    OperationsSource,
    OperationsWorkstream,
    PartsStatus,
    ProgrammingQcStatus,
    ProjectState,
    ShopStatus,
    TrayStatus,
    VehicleAvailabilityStatus,
    VehicleOperations,
    calculate_commitment_dates,
)
from ...domain.operations_policy import Capability, has_capability
from ..adapters.interfaces import OperationsConflictError, OperationsRepository


class OperationsServiceError(RuntimeError):
    """Base error for a rejected operations command."""


class OperationsNotFoundError(OperationsServiceError):
    pass


class OperationsAuthorizationError(OperationsServiceError):
    pass


class OperationsValidationError(OperationsServiceError):
    pass


_Clock = Callable[[], datetime]
_IdFactory = Callable[[], str]
_UNSET = object()


_BUILDER_PROJECTION_FIELDS = (
    "title",
    "agency_id",
    "agency_name",
    "build_year",
    "unit_number",
    "vin",
    "vehicle_label",
    "assigned_salesperson_id",
    "assigned_salesperson_name",
    "build_finalized",
    "build_finalized_at",
    "project_state",
)


_STATUS_ATTR = {
    OperationsWorkstream.PARTS: "parts_status",
    OperationsWorkstream.SHOP: "shop_status",
    OperationsWorkstream.TRAY: "tray_status",
    OperationsWorkstream.PROGRAMMING_QC: "programming_qc_status",
    OperationsWorkstream.FINAL_FINISH: "final_finish_status",
}

_STATUS_ENUM = {
    OperationsWorkstream.TRAY: TrayStatus,
    OperationsWorkstream.PROGRAMMING_QC: ProgrammingQcStatus,
    OperationsWorkstream.FINAL_FINISH: FinalFinishStatus,
}

_STATUS_CHANGED_ATTR = {
    OperationsWorkstream.PARTS: "parts_status_changed_at",
    OperationsWorkstream.SHOP: "shop_status_changed_at",
    OperationsWorkstream.TRAY: "tray_status_changed_at",
    OperationsWorkstream.PROGRAMMING_QC: "programming_qc_status_changed_at",
    OperationsWorkstream.FINAL_FINISH: "final_finish_status_changed_at",
}

_STREAM_CAPABILITY = {
    OperationsWorkstream.PARTS: Capability.OPERATIONS_PARTS_UPDATE,
    OperationsWorkstream.SHOP: Capability.OPERATIONS_SHOP_UPDATE,
    OperationsWorkstream.TRAY: Capability.OPERATIONS_TRAY_UPDATE,
    OperationsWorkstream.PROGRAMMING_QC: Capability.OPERATIONS_PROGRAMMING_QC_UPDATE,
    OperationsWorkstream.FINAL_FINISH: Capability.OPERATIONS_FINAL_FINISH_UPDATE,
}

_STATE_ORDER = {
    OperationsWorkstream.PARTS: [
        "",
        PartsStatus.ORDERED.value,
        PartsStatus.PARTIALLY_RECEIVED.value,
        PartsStatus.RECEIVED.value,
        PartsStatus.PARTS_READY.value,
    ],
    OperationsWorkstream.SHOP: ["", ShopStatus.IN_PROGRESS.value, ShopStatus.COMPLETE.value],
    OperationsWorkstream.TRAY: [
        TrayStatus.NOT_READY.value,
        TrayStatus.READY.value,
        TrayStatus.COMPLETE.value,
    ],
    OperationsWorkstream.PROGRAMMING_QC: [
        ProgrammingQcStatus.NOT_READY.value,
        ProgrammingQcStatus.READY.value,
        ProgrammingQcStatus.COMPLETE.value,
    ],
    OperationsWorkstream.FINAL_FINISH: [
        FinalFinishStatus.NOT_READY.value,
        FinalFinishStatus.READY_FOR_WASH_CLEAN_PHOTOS.value,
        FinalFinishStatus.READY_FOR_DELIVERY.value,
        FinalFinishStatus.DELIVERED.value,
    ],
}

_NORMAL_NEXT = {
    OperationsWorkstream.PARTS: {
        "": {
            PartsStatus.ORDERED.value,
            PartsStatus.PARTIALLY_RECEIVED.value,
            PartsStatus.RECEIVED.value,
        },
        PartsStatus.ORDERED.value: {
            PartsStatus.PARTIALLY_RECEIVED.value,
            PartsStatus.RECEIVED.value,
        },
        PartsStatus.PARTIALLY_RECEIVED.value: {PartsStatus.RECEIVED.value},
        PartsStatus.RECEIVED.value: {PartsStatus.PARTS_READY.value},
        PartsStatus.PARTS_READY.value: set(),
    },
    OperationsWorkstream.SHOP: {
        "": {ShopStatus.IN_PROGRESS.value},
        ShopStatus.IN_PROGRESS.value: {ShopStatus.COMPLETE.value},
        ShopStatus.COMPLETE.value: set(),
    },
    OperationsWorkstream.TRAY: {
        TrayStatus.NOT_READY.value: {TrayStatus.READY.value},
        TrayStatus.READY.value: {TrayStatus.COMPLETE.value},
        TrayStatus.COMPLETE.value: set(),
    },
    OperationsWorkstream.PROGRAMMING_QC: {
        ProgrammingQcStatus.NOT_READY.value: {ProgrammingQcStatus.READY.value},
        ProgrammingQcStatus.READY.value: {ProgrammingQcStatus.COMPLETE.value},
        ProgrammingQcStatus.COMPLETE.value: set(),
    },
    OperationsWorkstream.FINAL_FINISH: {
        FinalFinishStatus.NOT_READY.value: {
            FinalFinishStatus.READY_FOR_WASH_CLEAN_PHOTOS.value,
        },
        FinalFinishStatus.READY_FOR_WASH_CLEAN_PHOTOS.value: {
            FinalFinishStatus.READY_FOR_DELIVERY.value,
        },
        FinalFinishStatus.READY_FOR_DELIVERY.value: {
            FinalFinishStatus.DELIVERED.value,
        },
        FinalFinishStatus.DELIVERED.value: set(),
    },
}

_MILESTONE_ATTR = {
    OperationsWorkstream.PARTS: {
        PartsStatus.ORDERED.value: "parts_ordered_at",
        PartsStatus.PARTIALLY_RECEIVED.value: "parts_partially_received_at",
        PartsStatus.RECEIVED.value: "parts_received_at",
        PartsStatus.PARTS_READY.value: "parts_ready_at",
    },
    OperationsWorkstream.SHOP: {
        ShopStatus.IN_PROGRESS.value: "shop_started_at",
        ShopStatus.COMPLETE.value: "shop_completed_at",
    },
    OperationsWorkstream.TRAY: {
        TrayStatus.READY.value: "tray_ready_at",
        TrayStatus.COMPLETE.value: "tray_completed_at",
    },
    OperationsWorkstream.PROGRAMMING_QC: {
        ProgrammingQcStatus.READY.value: "programming_qc_ready_at",
        ProgrammingQcStatus.COMPLETE.value: "programming_qc_completed_at",
    },
    OperationsWorkstream.FINAL_FINISH: {
        FinalFinishStatus.READY_FOR_WASH_CLEAN_PHOTOS.value: "final_finish_ready_at",
        FinalFinishStatus.READY_FOR_DELIVERY.value: "ready_for_delivery_at",
        FinalFinishStatus.DELIVERED.value: "delivered_date",
    },
}


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _status_string(value: object) -> str:
    return str(getattr(value, "value", value) or "").strip()


class OperationsService:
    def __init__(
        self,
        repository: OperationsRepository,
        *,
        clock: _Clock | None = None,
        event_id_factory: _IdFactory | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._event_id_factory = event_id_factory or (lambda: str(uuid.uuid4()))

    def create_vehicle(
        self,
        *,
        vehicle_id: str,
        project_id: str,
        actor: OperationsActor,
        request_id: str,
        source_client: OperationsSource | str,
        title: str = "",
        agency_id: str = "",
        agency_name: str = "",
        build_year: str = "",
        unit_number: str = "",
        vin: str = "",
        vehicle_label: str = "",
        assigned_salesperson_id: str = "",
        assigned_salesperson_name: str = "",
        build_finalized: bool = False,
        build_finalized_at: str = "",
        project_state: ProjectState | str = ProjectState.ACTIVE,
        source_app_version: str = "",
    ) -> OperationsMutationResult:
        self._require(actor, Capability.PROJECTS_EDIT)
        request_id = self._required(request_id, "request_id")
        vehicle_id = self._required(vehicle_id, "vehicle_id")
        project_id = self._required(project_id, "project_id")
        duplicate = self._duplicate_result(request_id, vehicle_id)
        if duplicate is not None:
            return duplicate
        now = _utc_iso(self._clock())
        source = self._source(source_client)
        event_id = self._event_id_factory()
        record = VehicleOperations(
            vehicle_id=vehicle_id,
            project_id=project_id,
            title=str(title),
            agency_id=str(agency_id),
            agency_name=str(agency_name),
            build_year=str(build_year),
            unit_number=str(unit_number),
            vin=str(vin),
            vehicle_label=str(vehicle_label),
            assigned_salesperson_id=str(assigned_salesperson_id),
            assigned_salesperson_name=str(assigned_salesperson_name),
            build_finalized=bool(build_finalized),
            build_finalized_at=str(build_finalized_at),
            project_state=self._project_state(project_state),
            vehicle_availability_status_changed_at=now,
            tray_status_changed_at=now,
            programming_qc_status_changed_at=now,
            final_finish_status_changed_at=now,
            created_at=now,
            created_by_id=actor.user_id,
            created_by_name=actor.display_name,
            updated_at=now,
            updated_by_id=actor.user_id,
            updated_by_name=actor.display_name,
            source_client=source,
            last_event_id=event_id,
        )
        event = OperationsEvent(
            event_id=event_id,
            request_id=request_id,
            vehicle_id=vehicle_id,
            project_id=project_id,
            workstream=OperationsWorkstream.RECORD,
            event_type=OperationsEventType.RECORD_CREATED,
            previous_value="",
            new_value="created",
            occurred_at=now,
            actor_id=actor.user_id,
            actor_display_name=actor.display_name,
            source_client=source,
            source_app_version=str(source_app_version),
            record_revision=0,
        )
        saved = self._repository.create_vehicle(record, event)
        return OperationsMutationResult(record=saved, event=event)

    def upsert_builder_projection(
        self,
        projection: BuilderVehicleProjection,
        *,
        actor: OperationsActor,
        request_id: str,
        source_client: OperationsSource | str,
        expected_revision: int | None = None,
        source_app_version: str = "",
    ) -> OperationsMutationResult:
        """Create or refresh only the fields that Builder owns.

        Production workstream fields are deliberately absent from
        ``BuilderVehicleProjection`` and therefore survive every Builder save.
        Moving an existing vehicle to a different opaque project ID is rejected
        rather than silently relinking historical operations.
        """

        self._require(actor, Capability.PROJECTS_EDIT)
        request_id = self._required(request_id, "request_id")
        normalized = self._normalize_projection(projection)
        duplicate = self._duplicate_result(request_id, normalized.vehicle_id)
        if duplicate is not None:
            return duplicate

        current = self._repository.get_vehicle(normalized.vehicle_id)
        if current is None:
            return self.create_vehicle(
                vehicle_id=normalized.vehicle_id,
                project_id=normalized.project_id,
                actor=actor,
                request_id=request_id,
                source_client=source_client,
                title=normalized.title,
                agency_id=normalized.agency_id,
                agency_name=normalized.agency_name,
                build_year=normalized.build_year,
                unit_number=normalized.unit_number,
                vin=normalized.vin,
                vehicle_label=normalized.vehicle_label,
                assigned_salesperson_id=normalized.assigned_salesperson_id,
                assigned_salesperson_name=normalized.assigned_salesperson_name,
                build_finalized=normalized.build_finalized,
                build_finalized_at=normalized.build_finalized_at,
                project_state=normalized.project_state,
                source_app_version=source_app_version,
            )
        if current.project_id != normalized.project_id:
            raise OperationsConflictError(
                "Builder vehicle is already linked to a different project"
            )
        self._check_expected_revision(current, expected_revision)
        changes = self.projection_changes(current, normalized)
        if not changes:
            return OperationsMutationResult(record=current, event=None, unchanged=True)

        updated = replace(current)
        for field_name in _BUILDER_PROJECTION_FIELDS:
            setattr(updated, field_name, getattr(normalized, field_name))
        previous_value = json.dumps(
            {name: values[0] for name, values in changes.items()},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        new_value = json.dumps(
            {name: values[1] for name, values in changes.items()},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        now = _utc_iso(self._clock())
        return self._commit(
            current=current,
            updated=updated,
            request_id=request_id,
            actor=actor,
            source=self._source(source_client),
            workstream=OperationsWorkstream.RECORD,
            event_type=OperationsEventType.PROJECTION_REFRESHED,
            previous_value=previous_value,
            new_value=new_value,
            reason="",
            source_app_version=source_app_version,
            occurred_at=now,
        )

    @classmethod
    def projection_changes(
        cls,
        current: VehicleOperations,
        projection: BuilderVehicleProjection,
    ) -> dict[str, tuple[object, object]]:
        """Return the Builder-owned differences in browser-safe plain values."""

        normalized = cls._normalize_projection(projection)
        changes: dict[str, tuple[object, object]] = {}
        for field_name in _BUILDER_PROJECTION_FIELDS:
            previous = cls._plain(getattr(current, field_name))
            incoming = cls._plain(getattr(normalized, field_name))
            if previous != incoming:
                changes[field_name] = (previous, incoming)
        return changes

    def change_project_state(
        self,
        *,
        vehicle_id: str,
        new_state: ProjectState | str,
        actor: OperationsActor,
        request_id: str,
        source_client: OperationsSource | str,
        expected_revision: int | None = None,
        reason: str = "",
        source_app_version: str = "",
    ) -> OperationsMutationResult:
        """Mirror one Builder lifecycle change without touching shop statuses."""

        self._require(actor, Capability.PROJECTS_LIFECYCLE_UPDATE)
        request_id = self._required(request_id, "request_id")
        vehicle_id = self._required(vehicle_id, "vehicle_id")
        duplicate = self._duplicate_result(request_id, vehicle_id)
        if duplicate is not None:
            return duplicate
        current = self._get(vehicle_id)
        self._check_expected_revision(current, expected_revision)
        target = self._project_state(new_state)
        if current.project_state == target:
            return OperationsMutationResult(record=current, event=None, unchanged=True)

        updated = replace(current)
        updated.project_state = target
        now = _utc_iso(self._clock())
        return self._commit(
            current=current,
            updated=updated,
            request_id=request_id,
            actor=actor,
            source=self._source(source_client),
            workstream=OperationsWorkstream.RECORD,
            event_type=OperationsEventType.PROJECTION_REFRESHED,
            previous_value=current.project_state.value,
            new_value=target.value,
            reason=str(reason or "").strip(),
            source_app_version=source_app_version,
            occurred_at=now,
        )

    def change_status(
        self,
        *,
        vehicle_id: str,
        workstream: OperationsWorkstream | str,
        new_status: object,
        actor: OperationsActor,
        request_id: str,
        source_client: OperationsSource | str,
        expected_revision: int | None = None,
        correction_reason: str = "",
        source_app_version: str = "",
        performed_by_name: str = "",
    ) -> OperationsMutationResult:
        stream = self._workstream(workstream)
        if stream not in _STATUS_ATTR:
            raise OperationsValidationError(f"{stream.value} is not a status workstream")
        self._require(actor, _STREAM_CAPABILITY[stream])
        request_id = self._required(request_id, "request_id")
        vehicle_id = self._required(vehicle_id, "vehicle_id")
        duplicate = self._duplicate_result(request_id, vehicle_id)
        if duplicate is not None:
            return duplicate
        current = self._get(vehicle_id)
        self._check_expected_revision(current, expected_revision)
        status_attr = _STATUS_ATTR[stream]
        previous = _status_string(getattr(current, status_attr))
        target = _status_string(new_status)
        if target not in _STATE_ORDER[stream]:
            raise OperationsValidationError(f"Invalid {stream.value} status: {target or '(blank)'}")
        if target == previous:
            return OperationsMutationResult(record=current, event=None, unchanged=True)

        normal = target in _NORMAL_NEXT[stream].get(previous, set())
        reason = str(correction_reason or "").strip()
        if not normal:
            self._require(actor, Capability.OPERATIONS_CORRECT)
            if not reason:
                raise OperationsValidationError("A correction reason is required")

        now = _utc_iso(self._clock())
        source = self._source(source_client)
        updated = replace(current)
        status_enum = _STATUS_ENUM.get(stream)
        stored_target = status_enum(target) if status_enum is not None else target
        setattr(updated, status_attr, stored_target)
        setattr(updated, _STATUS_CHANGED_ATTR[stream], now)
        self._apply_milestone_dates(updated, stream, previous, target, now)
        if stream == OperationsWorkstream.PARTS:
            self._recompute_commitment(updated)
        return self._commit(
            current=current,
            updated=updated,
            request_id=request_id,
            actor=actor,
            source=source,
            workstream=stream,
            event_type=OperationsEventType.STATUS_CHANGED,
            previous_value=previous,
            new_value=target,
            reason=reason,
            source_app_version=source_app_version,
            occurred_at=now,
            performed_by_name=performed_by_name,
        )

    def change_vehicle_availability(
        self,
        *,
        vehicle_id: str,
        new_status: VehicleAvailabilityStatus | str,
        actor: OperationsActor,
        request_id: str,
        source_client: OperationsSource | str,
        effective_date: str = "",
        expected_revision: int | None = None,
        correction_reason: str = "",
        source_app_version: str = "",
        performed_by_name: str = "",
    ) -> OperationsMutationResult:
        """Update physical vehicle availability and its business-effective date."""

        self._require(actor, Capability.OPERATIONS_AVAILABILITY_UPDATE)
        request_id = self._required(request_id, "request_id")
        vehicle_id = self._required(vehicle_id, "vehicle_id")
        duplicate = self._duplicate_result(request_id, vehicle_id)
        if duplicate is not None:
            return duplicate
        current = self._get(vehicle_id)
        self._check_expected_revision(current, expected_revision)
        try:
            target = (
                new_status
                if isinstance(new_status, VehicleAvailabilityStatus)
                else VehicleAvailabilityStatus(str(new_status))
            )
        except ValueError as exc:
            raise OperationsValidationError(
                f"Invalid vehicle availability status: {new_status}"
            ) from exc
        previous = current.vehicle_availability_status
        if (
            target == VehicleAvailabilityStatus.DELIVERED
            and previous != VehicleAvailabilityStatus.DELIVERED
        ):
            raise OperationsValidationError(
                "Delivered is a Final Finish status; Vehicle Availability ends at At DTM"
            )
        available_states = {
            VehicleAvailabilityStatus.READY_FOR_PICKUP,
        }
        milestone_field = (
            "vehicle_available_date"
            if target in available_states
            else "vehicle_at_dtm_date"
            if target == VehicleAvailabilityStatus.AT_DTM
            else "delivered_date"
            if target == VehicleAvailabilityStatus.DELIVERED
            else ""
        )
        if target == previous:
            if not str(effective_date or "").strip() or not milestone_field:
                return OperationsMutationResult(record=current, event=None, unchanged=True)
            corrected_date = self._business_date(effective_date, "")
            previous_date = str(getattr(current, milestone_field) or "")
            if corrected_date == previous_date:
                return OperationsMutationResult(record=current, event=None, unchanged=True)
            self._require(actor, Capability.OPERATIONS_CORRECT)
            reason = str(correction_reason or "").strip()
            if not reason:
                raise OperationsValidationError("A correction reason is required")
            now = _utc_iso(self._clock())
            source = self._source(source_client)
            updated = replace(current)
            setattr(updated, milestone_field, corrected_date)
            updated.vehicle_availability_status_changed_at = now
            self._recompute_commitment(updated)
            return self._commit(
                current=current,
                updated=updated,
                request_id=request_id,
                actor=actor,
                source=source,
                workstream=OperationsWorkstream.AVAILABILITY,
                event_type=OperationsEventType.AVAILABILITY_CHANGED,
                previous_value=previous_date,
                new_value=corrected_date,
                reason=reason,
                source_app_version=source_app_version,
                occurred_at=now,
                effective_date=corrected_date,
                performed_by_name=performed_by_name,
            )

        reason = str(correction_reason or "").strip()
        if previous == VehicleAvailabilityStatus.DELIVERED:
            self._require(actor, Capability.OPERATIONS_CORRECT)
            if not reason:
                raise OperationsValidationError("A correction reason is required")

        now = _utc_iso(self._clock())
        source = self._source(source_client)
        business_date = self._business_date(effective_date, now)
        updated = replace(current)
        updated.vehicle_availability_status = target
        updated.vehicle_availability_status_changed_at = now

        if target in available_states:
            updated.vehicle_available_date = business_date
        elif target == VehicleAvailabilityStatus.AT_DTM:
            updated.vehicle_at_dtm_date = business_date
            if not updated.vehicle_available_date:
                updated.vehicle_available_date = business_date
        if previous == VehicleAvailabilityStatus.DELIVERED and target != previous:
            updated.delivered_date = ""
        self._recompute_commitment(updated)

        event_effective_date = business_date if (
            target in available_states
            or target in {
                VehicleAvailabilityStatus.AT_DTM,
                VehicleAvailabilityStatus.DELIVERED,
            }
        ) else ""
        return self._commit(
            current=current,
            updated=updated,
            request_id=request_id,
            actor=actor,
            source=source,
            workstream=OperationsWorkstream.AVAILABILITY,
            event_type=OperationsEventType.AVAILABILITY_CHANGED,
            previous_value=previous.value,
            new_value=target.value,
            reason=reason,
            source_app_version=source_app_version,
            occurred_at=now,
            effective_date=event_effective_date,
            performed_by_name=performed_by_name,
        )

    def change_acceptance(
        self,
        *,
        vehicle_id: str,
        new_status: AcceptanceStatus | str,
        acceptance_source: AcceptanceSource | str,
        actor: OperationsActor,
        request_id: str,
        source_client: OperationsSource | str,
        expected_revision: int | None = None,
        correction_reason: str = "",
        source_app_version: str = "",
        performed_by_name: str = "",
    ) -> OperationsMutationResult:
        self._require(actor, Capability.ESTIMATES_MANAGE)
        request_id = self._required(request_id, "request_id")
        vehicle_id = self._required(vehicle_id, "vehicle_id")
        duplicate = self._duplicate_result(request_id, vehicle_id)
        if duplicate is not None:
            return duplicate
        current = self._get(vehicle_id)
        self._check_expected_revision(current, expected_revision)
        try:
            target = (
                new_status
                if isinstance(new_status, AcceptanceStatus)
                else AcceptanceStatus(str(new_status))
            )
            accepted_source = (
                acceptance_source
                if isinstance(acceptance_source, AcceptanceSource)
                else AcceptanceSource(str(acceptance_source))
            )
        except ValueError as exc:
            raise OperationsValidationError("Invalid acceptance status or source") from exc
        previous = current.acceptance_status
        if target == previous:
            return OperationsMutationResult(record=current, event=None, unchanged=True)
        reason = str(correction_reason or "").strip()
        if previous == AcceptanceStatus.ACCEPTED and target == AcceptanceStatus.NOT_ACCEPTED:
            self._require(actor, Capability.OPERATIONS_CORRECT)
            if not reason:
                raise OperationsValidationError("A correction reason is required")

        now = _utc_iso(self._clock())
        source = self._source(source_client)
        updated = replace(current)
        updated.acceptance_status = target
        updated.acceptance_changed_at = now
        if target == AcceptanceStatus.ACCEPTED:
            updated.accepted_at = now
            updated.acceptance_source = accepted_source.value
        else:
            updated.accepted_at = ""
            updated.acceptance_source = ""
        return self._commit(
            current=current,
            updated=updated,
            request_id=request_id,
            actor=actor,
            source=source,
            workstream=OperationsWorkstream.ACCEPTANCE,
            event_type=OperationsEventType.ACCEPTANCE_CHANGED,
            previous_value=previous.value,
            new_value=target.value,
            reason=reason,
            source_app_version=source_app_version,
            occurred_at=now,
            performed_by_name=performed_by_name,
        )

    def change_schedule(
        self,
        *,
        vehicle_id: str,
        scheduled_week_of: object = _UNSET,
        planned_start_date: object = _UNSET,
        target_finish_date: object = _UNSET,
        must_deliver_override_date: object = _UNSET,
        actor: OperationsActor,
        request_id: str,
        source_client: OperationsSource | str,
        expected_revision: int | None = None,
        source_app_version: str = "",
        performed_by_name: str = "",
    ) -> OperationsMutationResult:
        """Patch any supplied human-directed schedule dates for one vehicle."""

        self._require(actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
        request_id = self._required(request_id, "request_id")
        vehicle_id = self._required(vehicle_id, "vehicle_id")
        duplicate = self._duplicate_result(request_id, vehicle_id)
        if duplicate is not None:
            return duplicate
        current = self._get(vehicle_id)
        self._check_expected_revision(current, expected_revision)
        previous = {
            "scheduled_week_of": current.scheduled_week_of,
            "planned_start_date": current.planned_start_date,
            "target_finish_date": current.target_finish_date,
            "must_deliver_override_date": current.must_deliver_override_date,
        }
        supplied = {
            "scheduled_week_of": scheduled_week_of,
            "planned_start_date": planned_start_date,
            "target_finish_date": target_finish_date,
            "must_deliver_override_date": must_deliver_override_date,
        }
        changed = dict(previous)
        provided = False
        for field_name, raw_value in supplied.items():
            if raw_value is _UNSET:
                continue
            provided = True
            changed[field_name] = self._optional_date(raw_value, field_name)
        if not provided:
            raise OperationsValidationError("At least one schedule field is required")
        if changed == previous:
            return OperationsMutationResult(record=current, event=None, unchanged=True)

        now = _utc_iso(self._clock())
        updated = replace(current)
        updated.scheduled_week_of = changed["scheduled_week_of"]
        updated.planned_start_date = changed["planned_start_date"]
        updated.target_finish_date = changed["target_finish_date"]
        updated.must_deliver_override_date = changed["must_deliver_override_date"]
        updated.schedule_changed_at = now
        self._recompute_commitment(updated)
        return self._commit(
            current=current,
            updated=updated,
            request_id=request_id,
            actor=actor,
            source=self._source(source_client),
            workstream=OperationsWorkstream.SCHEDULE,
            event_type=OperationsEventType.SCHEDULE_CHANGED,
            previous_value=json.dumps(
                previous,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            new_value=json.dumps(
                changed,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            reason="",
            source_app_version=source_app_version,
            occurred_at=now,
            performed_by_name=performed_by_name,
        )

    def _commit(
        self,
        *,
        current: VehicleOperations,
        updated: VehicleOperations,
        request_id: str,
        actor: OperationsActor,
        source: OperationsSource,
        workstream: OperationsWorkstream,
        event_type: OperationsEventType,
        previous_value: str,
        new_value: str,
        reason: str,
        source_app_version: str,
        occurred_at: str,
        effective_date: str = "",
        performed_by_name: str = "",
    ) -> OperationsMutationResult:
        event_id = self._event_id_factory()
        updated.schema_version = OPERATIONS_SCHEMA_VERSION
        updated.revision = current.revision + 1
        updated.updated_at = occurred_at
        updated.updated_by_id = actor.user_id
        updated.updated_by_name = actor.display_name
        updated.source_client = source
        updated.last_event_id = event_id
        event = OperationsEvent(
            event_id=event_id,
            request_id=request_id,
            vehicle_id=updated.vehicle_id,
            project_id=updated.project_id,
            workstream=workstream,
            event_type=event_type,
            previous_value=previous_value,
            new_value=new_value,
            occurred_at=occurred_at,
            actor_id=actor.user_id,
            actor_display_name=actor.display_name,
            source_client=source,
            performed_by_name=str(performed_by_name or "").strip(),
            source_app_version=str(source_app_version),
            effective_date=effective_date,
            reason=reason,
            record_revision=updated.revision,
        )
        saved = self._repository.commit_transition(
            updated,
            event,
            expected_revision=current.revision,
        )
        return OperationsMutationResult(record=saved, event=event)

    def _apply_milestone_dates(
        self,
        record: VehicleOperations,
        stream: OperationsWorkstream,
        previous: str,
        target: str,
        now: str,
    ) -> None:
        order = _STATE_ORDER[stream]
        previous_index = order.index(previous)
        target_index = order.index(target)
        milestone_fields = _MILESTONE_ATTR[stream]
        if target_index < previous_index:
            for state in order[target_index + 1:]:
                field = milestone_fields.get(state)
                if field:
                    setattr(record, field, "")
        target_field = milestone_fields.get(target)
        if target_field:
            setattr(record, target_field, now[:10] if target_field == "delivered_date" else now)
        if (
            stream == OperationsWorkstream.PARTS
            and target == "parts_ready"
            and not record.parts_received_at
        ):
            record.parts_received_at = now

    @staticmethod
    def _recompute_commitment(record: VehicleOperations) -> None:
        start, must_deliver_by = calculate_commitment_dates(
            record.vehicle_available_date,
            record.parts_received_at or record.parts_ready_at,
        )
        record.commitment_start_date = start
        record.must_deliver_by_date = record.must_deliver_override_date or must_deliver_by

    def _duplicate_result(
        self,
        request_id: str,
        vehicle_id: str,
    ) -> OperationsMutationResult | None:
        event = self._repository.find_event_by_request_id(request_id)
        if event is None:
            return None
        if event.vehicle_id != vehicle_id:
            raise OperationsConflictError("Request ID was already used for another vehicle")
        record = self._get(vehicle_id)
        return OperationsMutationResult(record=record, event=event, duplicate=True)

    def _get(self, vehicle_id: str) -> VehicleOperations:
        record = self._repository.get_vehicle(vehicle_id)
        if record is None:
            raise OperationsNotFoundError(f"Operations not found for vehicle {vehicle_id}")
        return record

    @staticmethod
    def _check_expected_revision(
        record: VehicleOperations,
        expected_revision: int | None,
    ) -> None:
        if expected_revision is not None and record.revision != expected_revision:
            raise OperationsConflictError(
                f"Expected revision {expected_revision}; found {record.revision}"
            )

    @staticmethod
    def _required(value: object, label: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise OperationsValidationError(f"{label} is required")
        return cleaned

    @staticmethod
    def _business_date(value: object, fallback_timestamp: str) -> str:
        cleaned = str(value or "").strip() or fallback_timestamp[:10]
        try:
            return date.fromisoformat(cleaned).isoformat()
        except ValueError as exc:
            raise OperationsValidationError(
                "effective_date must be an ISO date (YYYY-MM-DD)"
            ) from exc

    @staticmethod
    def _optional_date(value: object, label: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            return ""
        try:
            return date.fromisoformat(cleaned).isoformat()
        except ValueError as exc:
            raise OperationsValidationError(
                f"{label} must be an ISO date (YYYY-MM-DD)"
            ) from exc

    @classmethod
    def _normalize_projection(
        cls,
        projection: BuilderVehicleProjection,
    ) -> BuilderVehicleProjection:
        if not isinstance(projection, BuilderVehicleProjection):
            raise OperationsValidationError("A Builder vehicle projection is required")
        finalized = (
            projection.build_finalized
            if isinstance(projection.build_finalized, bool)
            else str(projection.build_finalized).strip().casefold() == "true"
        )
        return BuilderVehicleProjection(
            vehicle_id=cls._required(projection.vehicle_id, "vehicle_id"),
            project_id=cls._required(projection.project_id, "project_id"),
            title=str(projection.title or "").strip(),
            agency_id=str(projection.agency_id or "").strip(),
            agency_name=str(projection.agency_name or "").strip(),
            build_year=str(projection.build_year or "").strip(),
            unit_number=str(projection.unit_number or "").strip(),
            vin=str(projection.vin or "").strip().upper(),
            vehicle_label=str(projection.vehicle_label or "").strip(),
            assigned_salesperson_id=str(
                projection.assigned_salesperson_id or ""
            ).strip(),
            assigned_salesperson_name=str(
                projection.assigned_salesperson_name or ""
            ).strip(),
            build_finalized=finalized,
            build_finalized_at=(
                str(projection.build_finalized_at or "").strip() if finalized else ""
            ),
            project_state=cls._project_state(projection.project_state),
        )

    @staticmethod
    def _plain(value: object) -> object:
        return getattr(value, "value", value)

    @staticmethod
    def _project_state(value: ProjectState | str) -> ProjectState:
        try:
            return value if isinstance(value, ProjectState) else ProjectState(str(value))
        except ValueError as exc:
            raise OperationsValidationError(f"Invalid project state: {value}") from exc

    @staticmethod
    def _source(value: OperationsSource | str) -> OperationsSource:
        try:
            return value if isinstance(value, OperationsSource) else OperationsSource(str(value))
        except ValueError as exc:
            raise OperationsValidationError(f"Invalid source client: {value}") from exc

    @staticmethod
    def _workstream(value: OperationsWorkstream | str) -> OperationsWorkstream:
        try:
            return value if isinstance(value, OperationsWorkstream) else OperationsWorkstream(str(value))
        except ValueError as exc:
            raise OperationsValidationError(f"Invalid workstream: {value}") from exc

    @staticmethod
    def _require(actor: OperationsActor, capability: Capability) -> None:
        if not str(actor.user_id or "").strip():
            raise OperationsAuthorizationError("A verified actor is required")
        if not has_capability(actor.roles, capability):
            raise OperationsAuthorizationError(f"Missing capability: {capability.value}")
