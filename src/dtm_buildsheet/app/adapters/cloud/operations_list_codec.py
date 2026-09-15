"""SharePoint field mapping for operations records and timeline events."""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from ....domain.operations_codec import (
    operations_event_from_dict,
    vehicle_operations_from_dict,
    vehicle_operations_to_dict,
)
from ....domain.operations_models import OperationsEvent, VehicleOperations
from .operations_list_schema import VEHICLE_EVENTS_LIST, VEHICLE_OPERATIONS_LIST


MAX_RECORD_SNAPSHOT_BYTES = 60_000


CURRENT_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("title", "Title"),
    ("schema_version", "SchemaVersion"),
    ("vehicle_id", "BuilderVehicleId"),
    ("project_id", "BuilderProjectId"),
    ("agency_id", "AgencyId"),
    ("agency_name", "AgencyName"),
    ("build_year", "BuildYear"),
    ("unit_number", "UnitNumber"),
    ("vin", "Vin"),
    ("vehicle_label", "VehicleLabel"),
    ("assigned_salesperson_id", "AssignedSalespersonId"),
    ("assigned_salesperson_name", "AssignedSalespersonName"),
    ("build_finalized", "BuildFinalized"),
    ("build_finalized_at", "BuildFinalizedAtUtc"),
    ("shop_folder_url", "ShopFolderUrl"),
    ("build_sheet_url", "BuildSheetUrl"),
    ("parts_list_url", "PartsListUrl"),
    ("project_state", "ProjectState"),
    ("acceptance_status", "AcceptanceStatus"),
    ("accepted_at", "AcceptedAtUtc"),
    ("acceptance_source", "AcceptanceSource"),
    ("acceptance_changed_at", "AcceptanceChangedAtUtc"),
    ("vehicle_availability_status", "VehicleAvailabilityStatus"),
    ("vehicle_availability_status_changed_at", "VehicleAvailabilityStatusChanged"),
    ("vehicle_available_date", "VehicleAvailableDate"),
    ("vehicle_at_dtm_date", "VehicleAtDtmDate"),
    ("scheduled_week_of", "ScheduledWeekOf"),
    ("planned_start_date", "PlannedStartDate"),
    ("target_finish_date", "TargetFinishDate"),
    ("schedule_changed_at", "ScheduleChangedAtUtc"),
    ("commitment_start_date", "CommitmentStartDate"),
    ("must_deliver_override_date", "MustDeliverOverrideDate"),
    ("must_deliver_by_date", "MustDeliverByDate"),
    ("ready_to_build_override", "ReadyToBuildOverride"),
    ("ready_to_build_override_reason", "ReadyToBuildOverrideReason"),
    ("ready_to_build_override_at", "ReadyToBuildOverrideAtUtc"),
    ("ready_to_build_override_by_id", "ReadyToBuildOverrideByEntraId"),
    ("ready_to_build_override_by_name", "ReadyToBuildOverrideByName"),
    ("parts_status", "PartsStatus"),
    ("parts_status_changed_at", "PartsStatusChangedAtUtc"),
    ("parts_ordered_at", "PartsOrderedAtUtc"),
    ("parts_partially_received_at", "PartsPartiallyReceivedAtUtc"),
    ("parts_received_at", "PartsReceivedAtUtc"),
    ("parts_ready_at", "PartsReadyAtUtc"),
    ("shop_status", "ShopStatus"),
    ("shop_status_changed_at", "ShopStatusChangedAtUtc"),
    ("shop_started_at", "ShopStartedAtUtc"),
    ("shop_completed_at", "ShopCompletedAtUtc"),
    ("tray_status", "TrayStatus"),
    ("tray_status_changed_at", "TrayStatusChangedAtUtc"),
    ("tray_ready_at", "TrayReadyAtUtc"),
    ("tray_completed_at", "TrayCompletedAtUtc"),
    ("programming_qc_status", "ProgrammingQcStatus"),
    ("programming_qc_status_changed_at", "ProgrammingQcStatusChangedAtUtc"),
    ("programming_qc_ready_at", "ProgrammingQcReadyAtUtc"),
    ("programming_qc_completed_at", "ProgrammingQcCompletedAtUtc"),
    ("final_finish_status", "FinalFinishStatus"),
    ("final_finish_status_changed_at", "FinalFinishStatusChangedAtUtc"),
    ("final_finish_ready_at", "FinalFinishReadyAtUtc"),
    ("ready_for_delivery_at", "ReadyForDeliveryAtUtc"),
    ("delivered_date", "DeliveredDate"),
    ("delivery_method", "DeliveryMethod"),
    ("qbo_project_id", "QboProjectId"),
    ("qbo_project_name", "QboProjectName"),
    ("qbo_estimate_id", "QboEstimateId"),
    ("qbo_estimate_number", "QboEstimateNumber"),
    ("qbo_estimate_status", "QboEstimateStatus"),
    ("qbo_estimate_accepted_at", "QboEstimateAcceptedAtUtc"),
    ("qbo_estimate_last_modified_at", "QboEstimateLastModifiedAtUtc"),
    ("qbo_checked_at", "QboCheckedAtUtc"),
    ("qbo_checked_by_id", "QboCheckedByEntraId"),
    ("qbo_checked_by_name", "QboCheckedByName"),
    ("qbo_diff_status", "QboDiffStatus"),
    ("revision", "Revision"),
    ("last_event_id", "LastEventId"),
    ("created_at", "CreatedAtUtc"),
    ("created_by_id", "CreatedByEntraId"),
    ("created_by_name", "CreatedByName"),
    ("updated_at", "UpdatedAtUtc"),
    ("updated_by_id", "UpdatedByEntraId"),
    ("updated_by_name", "UpdatedByName"),
    ("source_client", "SourceClient"),
)


EVENT_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("schema_version", "SchemaVersion"),
    ("event_id", "EventId"),
    ("request_id", "RequestId"),
    ("vehicle_id", "BuilderVehicleId"),
    ("project_id", "BuilderProjectId"),
    ("workstream", "Workstream"),
    ("event_type", "EventType"),
    ("previous_value", "PreviousValue"),
    ("new_value", "NewValue"),
    ("occurred_at", "OccurredAtUtc"),
    ("effective_date", "EffectiveDate"),
    ("actor_id", "ActorEntraId"),
    ("actor_display_name", "ActorDisplayName"),
    ("performed_by_name", "PerformedByName"),
    ("source_client", "SourceClient"),
    ("source_app_version", "SourceAppVersion"),
    ("reason", "Reason"),
    ("record_revision", "RecordRevision"),
)


_CURRENT_KINDS = {
    "Title": "text",
    **{column.name: column.kind for column in VEHICLE_OPERATIONS_LIST.columns},
}
_EVENT_KINDS = {column.name: column.kind for column in VEHICLE_EVENTS_LIST.columns}


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _to_sharepoint(value: Any, kind: str) -> Any:
    value = _plain(value)
    if kind == "boolean":
        return bool(value)
    if kind == "number":
        return int(value or 0)
    if kind in {"date", "datetime"}:
        return str(value or "") or None
    if kind == "choice":
        return str(value or "") or None
    return str(value or "")


def _from_sharepoint(value: Any, kind: str) -> Any:
    if kind == "date":
        return str(value or "").strip()[:10]
    return value


def vehicle_operations_to_fields(record: VehicleOperations) -> dict[str, Any]:
    fields = {
        field_name: _to_sharepoint(getattr(record, attribute), _CURRENT_KINDS[field_name])
        for attribute, field_name in CURRENT_FIELD_MAP
    }
    fields["Title"] = record.title or record.vehicle_label or record.vehicle_id
    return fields


def vehicle_operations_from_fields(fields: Any) -> VehicleOperations:
    if not isinstance(fields, dict):
        raise ValueError("SharePoint operations fields must be an object")
    payload = {
        attribute: (str(fields.get(field_name) or '')[:10] if attribute == 'qbo_estimate_accepted_at'
                    else _from_sharepoint(fields.get(field_name), _CURRENT_KINDS[field_name]))
        for attribute, field_name in CURRENT_FIELD_MAP
    }
    return vehicle_operations_from_dict(payload)


def record_snapshot_to_json(record: VehicleOperations) -> str:
    encoded = json.dumps(
        vehicle_operations_to_dict(record),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(encoded.encode("utf-8")) > MAX_RECORD_SNAPSHOT_BYTES:
        raise ValueError("Operations record snapshot exceeds the safe SharePoint field limit")
    return encoded


def record_snapshot_from_json(value: Any) -> VehicleOperations:
    try:
        payload = json.loads(str(value or ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("Operations event has an invalid record snapshot") from exc
    # Desktop-authored snapshots use the canonical domain keys. The standard-
    # connector phone flow starts from a SharePoint Get item result, so it may
    # persist the equivalent internal-field shape instead. Accept both, then
    # immediately normalize to the same domain model. Extra SharePoint
    # metadata is ignored by the explicit field map.
    if "BuilderVehicleId" in payload:
        return vehicle_operations_from_fields(payload)
    return vehicle_operations_from_dict(payload)


def operations_event_to_fields(
    event: OperationsEvent,
    record: VehicleOperations,
    *,
    commit_status: str = "pending",
) -> dict[str, Any]:
    fields = {
        field_name: _to_sharepoint(getattr(event, attribute), _EVENT_KINDS[field_name])
        for attribute, field_name in EVENT_FIELD_MAP
    }
    fields.update({
        "Title": (
            f"{event.event_type.value}: "
            f"{record.vehicle_label or record.title or record.vehicle_id}"
        ),
        "CommitStatus": str(commit_status),
        "RecordSnapshotJson": record_snapshot_to_json(record),
    })
    return fields


def operations_event_from_fields(fields: Any) -> OperationsEvent:
    if not isinstance(fields, dict):
        raise ValueError("SharePoint event fields must be an object")
    payload = {
        attribute: _from_sharepoint(fields.get(field_name), _EVENT_KINDS[field_name])
        for attribute, field_name in EVENT_FIELD_MAP
    }
    return operations_event_from_dict(payload)


def validate_operations_field_maps() -> None:
    current_expected = {"Title", *(column.name for column in VEHICLE_OPERATIONS_LIST.columns)}
    current_mapped = {field_name for _, field_name in CURRENT_FIELD_MAP}
    if current_mapped != current_expected:
        raise ValueError("Vehicle operations SharePoint field map does not match the schema")
    event_expected = {"Title", *(column.name for column in VEHICLE_EVENTS_LIST.columns)}
    event_mapped = {
        "Title", "CommitStatus", "RecordSnapshotJson",
        *(field_name for _, field_name in EVENT_FIELD_MAP),
    }
    if event_mapped != event_expected:
        raise ValueError("Operations event SharePoint field map does not match the schema")


validate_operations_field_maps()
