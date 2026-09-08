"""Stable dict codec for operations current records and timeline events."""
from __future__ import annotations

from dataclasses import fields
from enum import Enum
from typing import Any, TypeVar

from .operations_models import (
    AcceptanceStatus,
    FinalFinishStatus,
    OperationsEvent,
    OperationsEventType,
    OperationsSource,
    OperationsWorkstream,
    ProgrammingQcStatus,
    ProjectState,
    TrayStatus,
    VehicleAvailabilityStatus,
    VehicleOperations,
)


_EnumT = TypeVar("_EnumT", bound=Enum)


def _enum_value(enum_type: type[_EnumT], value: Any, default: _EnumT) -> _EnumT:
    try:
        return enum_type(str(value))
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _plain_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def vehicle_operations_to_dict(record: VehicleOperations) -> dict[str, Any]:
    return {
        field.name: _plain_value(getattr(record, field.name))
        for field in fields(VehicleOperations)
    }


def vehicle_operations_from_dict(payload: Any) -> VehicleOperations:
    if not isinstance(payload, dict):
        raise ValueError("VehicleOperations must be a dict")
    vehicle_id = str(payload.get("vehicle_id", "") or "").strip()
    project_id = str(payload.get("project_id", "") or "").strip()
    if not vehicle_id:
        raise ValueError("vehicle_id is required")
    if not project_id:
        raise ValueError("project_id is required")

    values: dict[str, Any] = {}
    for field in fields(VehicleOperations):
        if field.name in {"vehicle_id", "project_id"}:
            continue
        raw = payload.get(field.name, field.default)
        if field.name in {"schema_version", "revision"}:
            values[field.name] = max(0, _integer(raw, int(field.default)))
        elif field.name in {"build_finalized", "ready_to_build_override"}:
            values[field.name] = raw if isinstance(raw, bool) else str(raw).lower() == "true"
        else:
            values[field.name] = str(raw or "")

    values["project_state"] = _enum_value(
        ProjectState, payload.get("project_state", ProjectState.ACTIVE), ProjectState.ACTIVE,
    )
    values["acceptance_status"] = _enum_value(
        AcceptanceStatus,
        payload.get("acceptance_status", AcceptanceStatus.NOT_ACCEPTED),
        AcceptanceStatus.NOT_ACCEPTED,
    )
    values["vehicle_availability_status"] = _enum_value(
        VehicleAvailabilityStatus,
        payload.get(
            "vehicle_availability_status",
            VehicleAvailabilityStatus.AWAITING_DETAILS,
        ),
        VehicleAvailabilityStatus.AWAITING_DETAILS,
    )
    values["tray_status"] = _enum_value(
        TrayStatus, payload.get("tray_status", TrayStatus.NOT_READY), TrayStatus.NOT_READY,
    )
    values["programming_qc_status"] = _enum_value(
        ProgrammingQcStatus,
        payload.get("programming_qc_status", ProgrammingQcStatus.NOT_READY),
        ProgrammingQcStatus.NOT_READY,
    )
    values["final_finish_status"] = _enum_value(
        FinalFinishStatus,
        payload.get("final_finish_status", FinalFinishStatus.NOT_READY),
        FinalFinishStatus.NOT_READY,
    )
    values["source_client"] = _enum_value(
        OperationsSource,
        payload.get("source_client", OperationsSource.SYSTEM),
        OperationsSource.SYSTEM,
    )
    allowed_parts = {"", "ordered", "partially_received", "received", "parts_ready"}
    if values["parts_status"] not in allowed_parts:
        values["parts_status"] = ""
    allowed_shop = {"", "in_progress", "complete"}
    if values["shop_status"] not in allowed_shop:
        values["shop_status"] = ""

    return VehicleOperations(vehicle_id=vehicle_id, project_id=project_id, **values)


def operations_event_to_dict(event: OperationsEvent) -> dict[str, Any]:
    return {
        field.name: _plain_value(getattr(event, field.name))
        for field in fields(OperationsEvent)
    }


def operations_event_from_dict(payload: Any) -> OperationsEvent:
    if not isinstance(payload, dict):
        raise ValueError("OperationsEvent must be a dict")
    required = ("event_id", "request_id", "vehicle_id", "project_id")
    values = {name: str(payload.get(name, "") or "").strip() for name in required}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing operations event field: {missing[0]}")
    return OperationsEvent(
        **values,
        workstream=_enum_value(
            OperationsWorkstream,
            payload.get("workstream", OperationsWorkstream.RECORD),
            OperationsWorkstream.RECORD,
        ),
        event_type=_enum_value(
            OperationsEventType,
            payload.get("event_type", OperationsEventType.RECORD_CREATED),
            OperationsEventType.RECORD_CREATED,
        ),
        previous_value=str(payload.get("previous_value", "") or ""),
        new_value=str(payload.get("new_value", "") or ""),
        occurred_at=str(payload.get("occurred_at", "") or ""),
        actor_id=str(payload.get("actor_id", "") or ""),
        actor_display_name=str(payload.get("actor_display_name", "") or ""),
        source_client=_enum_value(
            OperationsSource,
            payload.get("source_client", OperationsSource.SYSTEM),
            OperationsSource.SYSTEM,
        ),
        performed_by_name=str(payload.get("performed_by_name", "") or ""),
        source_app_version=str(payload.get("source_app_version", "") or ""),
        effective_date=str(payload.get("effective_date", "") or ""),
        reason=str(payload.get("reason", "") or ""),
        record_revision=max(0, _integer(payload.get("record_revision", 0))),
        schema_version=max(0, _integer(payload.get("schema_version", 1), 1)),
    )
