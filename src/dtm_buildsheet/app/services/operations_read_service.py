"""Read-only operations queries and browser-facing summary projection."""
from __future__ import annotations

from ...domain.calendar_planning import acceptance_day

from collections import Counter

from ...domain.operations_models import (
    OperationsActor,
    OperationsEvent,
    ProjectState,
    VehicleOperations,
    calculate_commitment_dates,
    is_ready_to_build,
    qbo_observation_is_stale,
    schedule_bucket,
)
from ...domain.operations_policy import Capability, has_capability
from ..adapters.interfaces import OperationsRepository
from .operations_service import (
    OperationsAuthorizationError,
    OperationsNotFoundError,
    OperationsValidationError,
)


class OperationsReadService:
    def __init__(self, repository: OperationsRepository) -> None:
        self._repository = repository

    def list_vehicle_summaries(
        self,
        actor: OperationsActor,
        *,
        hidden_project_ids: frozenset[str] = frozenset(),
        projects=(),
    ) -> dict:
        self._require_view(actor)

        from ...domain.project_types import with_project_work
        by_id = {p.project_id: p for p in projects}
        records = sorted(
            (
                with_project_work(record, by_id.get(record.project_id))
                for record in self._repository.list_vehicles()
                if record.project_id not in hidden_project_ids
            ),
            key=_vehicle_sort_key,
        )
        vehicles = [_vehicle_summary(record) for record in records]
        state_counts = Counter(vehicle["project_state"] for vehicle in vehicles)
        schedule_counts = Counter(vehicle["schedule_bucket"] for vehicle in vehicles)
        return {
            "ok": True,
            "read_only": True,
            "vehicles": vehicles,
            "counts": {
                "total": len(vehicles),
                "active": state_counts[ProjectState.ACTIVE.value],
                "inactive": state_counts[ProjectState.INACTIVE.value],
                "completed": state_counts[ProjectState.COMPLETED.value],
                "prospective": schedule_counts["prospective"],
                "unscheduled": schedule_counts["unscheduled"],
                "scheduled": schedule_counts["scheduled"],
            },
        }

    def list_vehicle_history(self, vehicle_id: str, actor: OperationsActor) -> dict:
        """Return the complete applied event history as a browser-safe projection."""

        self._require_view(actor)
        vehicle_id = str(vehicle_id or "").strip()
        if not vehicle_id:
            raise OperationsValidationError("vehicle_id is required")
        events = self._repository.list_events(vehicle_id)
        if not events:
            raise OperationsNotFoundError(
                f"Operations history not found for vehicle {vehicle_id}"
            )
        return {
            "ok": True,
            "vehicle_id": vehicle_id,
            "count": len(events),
            "events": [
                _event_summary(event)
                for event in reversed(events)
            ],
        }

    @staticmethod
    def _require_view(actor: OperationsActor) -> None:
        if not str(actor.user_id or "").strip():
            raise OperationsAuthorizationError("A verified actor is required")
        if not has_capability(actor.roles, Capability.OPERATIONS_VIEW):
            raise OperationsAuthorizationError(
                f"Missing capability: {Capability.OPERATIONS_VIEW.value}"
            )


def _vehicle_sort_key(record: VehicleOperations) -> tuple:
    state_rank = {
        ProjectState.ACTIVE: 0,
        ProjectState.INACTIVE: 1,
        ProjectState.COMPLETED: 2,
    }
    bucket = schedule_bucket(record).value
    bucket_rank = {"unscheduled": 0, "scheduled": 1, "prospective": 2}
    _, effective_deadline = _display_commitment(record)
    return (
        state_rank.get(record.project_state, 9),
        bucket_rank.get(bucket, 9),
        str(record.scheduled_week_of or "9999-12-31"),
        str(effective_deadline or "9999-12-31"),
        str(record.agency_name).casefold(),
        str(record.vehicle_label or record.title).casefold(),
        record.vehicle_id,
    )


def _vehicle_summary(record: VehicleOperations) -> dict:
    from ...domain.project_types import applicable_workstreams, physical_readiness
    commitment_start, effective_deadline = _display_commitment(record)
    return {
        "project_type": record.project_type,
        "service_details": record.service_details,
        "applicable_workstreams": sorted(applicable_workstreams(record)),
        "parts_and_vehicle_ready": all(physical_readiness(record)),
        "vehicle_id": record.vehicle_id,
        "project_id": record.project_id,
        "revision": record.revision,
        "title": record.title,
        "agency_name": record.agency_name,
        "build_year": record.build_year,
        "unit_number": record.unit_number,
        "vin": record.vin,
        "vehicle_label": record.vehicle_label,
        "project_state": record.project_state.value,
        "acceptance_status": record.acceptance_status.value,
        "accepted_at": record.accepted_at,
        "accepted_date": acceptance_day(record),
        "acceptance_source": record.acceptance_source,
        "qbo_estimate_accepted_at": record.qbo_estimate_accepted_at,
        "shop_started_at": record.shop_started_at,
        "shop_completed_at": record.shop_completed_at,
        "schedule_bucket": schedule_bucket(record).value,
        "scheduled_week_of": record.scheduled_week_of,
        "planned_start_date": record.planned_start_date,
        "target_finish_date": record.target_finish_date,
        "commitment_start_date": commitment_start,
        "must_deliver_override_date": record.must_deliver_override_date,
        "must_deliver_by_date": effective_deadline,
        "vehicle_availability_status": record.vehicle_availability_status.value,
        "parts_status": record.parts_status,
        "parts_ready_at": record.parts_ready_at,
        "shop_status": record.shop_status,
        "tray_status": record.tray_status.value,
        "tray_ready_at": record.tray_ready_at,
        "tray_completed_at": record.tray_completed_at,
        "programming_qc_status": record.programming_qc_status.value,
        "programming_qc_ready_at": record.programming_qc_ready_at,
        "programming_qc_completed_at": record.programming_qc_completed_at,
        "final_finish_status": record.final_finish_status.value,
        "final_finish_ready_at": record.final_finish_ready_at,
        "ready_for_delivery_at": record.ready_for_delivery_at,
        "delivered_date": record.delivered_date,
        "ready_to_build": is_ready_to_build(record),
        "qbo_estimate_id": record.qbo_estimate_id,
        "qbo_estimate_sent_status": record.qbo_estimate_sent_status,
        "qbo_estimate_sent_at": record.qbo_estimate_sent_at,
        "qbo_estimate_number": record.qbo_estimate_number,
        "qbo_estimate_status": record.qbo_estimate_status,
        "qbo_checked_at": record.qbo_checked_at,
        "qbo_observation_stale": qbo_observation_is_stale(record.qbo_checked_at),
        "updated_at": record.updated_at,
        "updated_by_name": record.updated_by_name,
    }


def _display_commitment(record: VehicleOperations) -> tuple[str, str]:
    """Derive legacy Parts Ready rows without mutating read-only SharePoint state."""

    start, automatic_deadline = calculate_commitment_dates(
        record.vehicle_available_date,
        record.parts_received_at or record.parts_ready_at,
    )
    return start, record.must_deliver_override_date or (automatic_deadline if record.project_type == "build" else "")


def _event_summary(event: OperationsEvent) -> dict:
    return {
        "event_id": event.event_id,
        "workstream": event.workstream.value,
        "event_type": event.event_type.value,
        "previous_value": event.previous_value,
        "new_value": event.new_value,
        "occurred_at": event.occurred_at,
        "effective_date": event.effective_date,
        "actor_display_name": event.actor_display_name,
        "performed_by_name": event.performed_by_name,
        "source_client": event.source_client.value,
        "reason": event.reason,
        "revision": event.record_revision,
    }
