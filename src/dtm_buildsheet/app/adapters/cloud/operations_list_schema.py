"""Exact SharePoint schema for production operations and phone requests.

The machine-facing names in this module are creation-time contracts.  The
provisioner sends them to Graph exactly once and all runtime adapters resolve
the resulting lists by GUID.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ....domain.operations_models import (
    AcceptanceSource,
    AcceptanceStatus,
    FinalFinishStatus,
    OperationsEventType,
    OperationsSource,
    OperationsWorkstream,
    ProgrammingQcStatus,
    ProjectState,
    PartsStatus,
    TrayStatus,
    VehicleAvailabilityStatus,
)


ColumnKind = Literal["text", "multiline", "choice", "date", "datetime", "number", "boolean"]

OPERATIONS_LIST_NAME = "DTMVehicleOperations"
EVENTS_LIST_NAME = "DTMVehicleEvents"
ESTIMATE_SEND_SCHEMA_CONFIRMATION = "ADD ESTIMATE SEND EVIDENCE"
ESTIMATE_SEND_SCHEMA_COLUMN_NAMES = {
    OPERATIONS_LIST_NAME: ("QboEstimateSentStatus", "QboEstimateSentAtUtc"),
}
REQUESTS_LIST_NAME = "DTMOperationsRequests"
OPERATIONS_LIST_READ_SCOPES = ("Sites.Read.All",)
OPERATIONS_LIST_INSPECTION_SCOPES = OPERATIONS_LIST_READ_SCOPES
OPERATIONS_LIST_PROVISIONING_SCOPES = ("Sites.Manage.All",)
OPERATIONS_LIST_RUNTIME_SCOPES = ("Sites.ReadWrite.All",)
PROVISION_CONFIRMATION = f"CREATE {OPERATIONS_LIST_NAME} AND {EVENTS_LIST_NAME}"
PHONE_REQUESTS_PROVISION_CONFIRMATION = f"CREATE {REQUESTS_LIST_NAME}"
RECOVERY_SCHEMA_CONFIRMATION = "ADD OPERATIONS RECOVERY COLUMNS"
DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION = "ADD OPERATIONS DEADLINE OVERRIDE"
PARTS_ORDERED_SCHEMA_CONFIRMATION = "ADD PARTS ORDERED STATUS"
LEGACY_PARTS_STATUS_CHOICES = ("partially_received", "received", "parts_ready")
FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION = "ADD FINAL FINISH DELIVERED STATUS"
LEGACY_FINAL_FINISH_STATUS_CHOICES = (
    "not_ready",
    "ready_for_wash_clean_photos",
    "ready_for_delivery",
)


@dataclass(frozen=True)
class SharePointColumnSpec:
    name: str
    kind: ColumnKind
    required: bool = False
    indexed: bool = False
    unique: bool = False
    choices: tuple[str, ...] = ()

    def graph_payload(self) -> dict:
        payload: dict = {
            "name": self.name,
            "required": self.required,
            "indexed": self.indexed,
            "enforceUniqueValues": self.unique,
        }
        if self.kind == "text":
            payload["text"] = {"allowMultipleLines": False}
        elif self.kind == "multiline":
            payload["text"] = {
                "allowMultipleLines": True,
                "appendChangesToExistingText": False,
                "linesForEditing": 6,
            }
        elif self.kind == "choice":
            payload["choice"] = {
                "allowTextEntry": False,
                "choices": list(self.choices),
                "displayAs": "dropDownMenu",
            }
        elif self.kind in {"date", "datetime"}:
            payload["dateTime"] = {
                "format": "dateOnly" if self.kind == "date" else "dateTime",
            }
        elif self.kind == "number":
            payload["number"] = {"decimalPlaces": "none"}
        elif self.kind == "boolean":
            payload["boolean"] = {}
        else:  # pragma: no cover - Literal plus manifest validation prevent this
            raise ValueError(f"Unsupported SharePoint column kind: {self.kind}")
        return payload


@dataclass(frozen=True)
class SharePointListSpec:
    name: str
    description: str
    columns: tuple[SharePointColumnSpec, ...]

    @property
    def indexed_column_count(self) -> int:
        return sum(column.indexed for column in self.columns)

    def graph_create_payload(self) -> dict:
        # Creating with the permanent machine name avoids relying on how
        # SharePoint sanitizes spaces in a friendly title. The Builder owns
        # all user-facing labels and later addresses the list by GUID.
        return {
            "displayName": self.name,
            "description": self.description,
            "columns": [column.graph_payload() for column in self.columns],
            "list": {"template": "genericList"},
        }


def _col(
    name: str,
    kind: ColumnKind = "text",
    *,
    required: bool = False,
    indexed: bool = False,
    unique: bool = False,
    choices: tuple[str, ...] = (),
) -> SharePointColumnSpec:
    return SharePointColumnSpec(
        name=name,
        kind=kind,
        required=required,
        indexed=indexed,
        unique=unique,
        choices=choices,
    )


_SOURCE_CHOICES = tuple(value.value for value in OperationsSource)


VEHICLE_OPERATIONS_LIST = SharePointListSpec(
    name=OPERATIONS_LIST_NAME,
    description="Current DTM production-operations projection, one row per Builder vehicle.",
    columns=(
        _col("SchemaVersion", "number", required=True),
        _col("BuilderVehicleId", required=True, indexed=True, unique=True),
        _col("BuilderProjectId", required=True, indexed=True),
        _col("AgencyId", indexed=True),
        _col("AgencyName"),
        _col("BuildYear", indexed=True),
        _col("UnitNumber"),
        _col("Vin", indexed=True),
        _col("VehicleLabel"),
        _col("AssignedSalespersonId"),
        _col("AssignedSalespersonName"),
        _col("BuildFinalized", "boolean", required=True),
        _col("BuildFinalizedAtUtc", "datetime"),
        _col("ShopFolderUrl"),
        _col("BuildSheetUrl"),
        _col("PartsListUrl"),
        _col(
            "ProjectState", "choice", required=True, indexed=True,
            choices=tuple(value.value for value in ProjectState),
        ),
        _col(
            "AcceptanceStatus", "choice", required=True, indexed=True,
            choices=tuple(value.value for value in AcceptanceStatus),
        ),
        _col("AcceptedAtUtc", "datetime"),
        _col(
            "AcceptanceSource", "choice",
            choices=tuple(value.value for value in AcceptanceSource),
        ),
        _col("AcceptanceChangedAtUtc", "datetime"),
        _col(
            "VehicleAvailabilityStatus", "choice", required=True, indexed=True,
            choices=tuple(value.value for value in VehicleAvailabilityStatus),
        ),
        # SharePoint internal field names are limited to 32 characters. Keep
        # this permanent machine name explicit instead of relying on Graph's
        # silent truncation of a longer display name.
        _col("VehicleAvailabilityStatusChanged", "datetime"),
        _col("VehicleAvailableDate", "date", indexed=True),
        _col("VehicleAtDtmDate", "date"),
        _col("ScheduledWeekOf", "date", indexed=True),
        _col("PlannedStartDate", "date"),
        _col("TargetFinishDate", "date", indexed=True),
        _col("ScheduleChangedAtUtc", "datetime"),
        _col("CommitmentStartDate", "date"),
        _col("MustDeliverOverrideDate", "date"),
        _col("MustDeliverByDate", "date", indexed=True),
        _col("ReadyToBuildOverride", "boolean", required=True),
        _col("ReadyToBuildOverrideReason", "multiline"),
        _col("ReadyToBuildOverrideAtUtc", "datetime"),
        _col("ReadyToBuildOverrideByEntraId"),
        _col("ReadyToBuildOverrideByName"),
        _col(
            "PartsStatus", "choice", indexed=True,
            choices=tuple(value.value for value in PartsStatus),
        ),
        _col("PartsStatusChangedAtUtc", "datetime"),
        _col("PartsOrderedAtUtc", "datetime"),
        _col("PartsPartiallyReceivedAtUtc", "datetime"),
        _col("PartsReceivedAtUtc", "datetime"),
        _col("PartsReadyAtUtc", "datetime"),
        _col(
            "ShopStatus", "choice", indexed=True,
            choices=("in_progress", "complete"),
        ),
        _col("ShopStatusChangedAtUtc", "datetime"),
        _col("ShopStartedAtUtc", "datetime"),
        _col("ShopCompletedAtUtc", "datetime"),
        _col(
            "TrayStatus", "choice", required=True, indexed=True,
            choices=tuple(value.value for value in TrayStatus),
        ),
        _col("TrayStatusChangedAtUtc", "datetime"),
        _col("TrayReadyAtUtc", "datetime"),
        _col("TrayCompletedAtUtc", "datetime"),
        _col(
            "ProgrammingQcStatus", "choice", required=True, indexed=True,
            choices=tuple(value.value for value in ProgrammingQcStatus),
        ),
        _col("ProgrammingQcStatusChangedAtUtc", "datetime"),
        _col("ProgrammingQcReadyAtUtc", "datetime"),
        _col("ProgrammingQcCompletedAtUtc", "datetime"),
        _col(
            "FinalFinishStatus", "choice", required=True, indexed=True,
            choices=tuple(value.value for value in FinalFinishStatus),
        ),
        _col("FinalFinishStatusChangedAtUtc", "datetime"),
        _col("FinalFinishReadyAtUtc", "datetime"),
        _col("ReadyForDeliveryAtUtc", "datetime"),
        _col("DeliveredDate", "date", indexed=True),
        _col(
            "DeliveryMethod", "choice",
            choices=("dtm_delivery", "customer_pickup"),
        ),
        _col("QboProjectId"),
        _col("QboProjectName"),
        _col("QboEstimateId"),
        _col("QboEstimateNumber"),
        _col("QboEstimateStatus"),
        _col("QboEstimateSentStatus"),
        _col("QboEstimateSentAtUtc", "datetime"),
        _col("QboEstimateAcceptedAtUtc", "datetime"),
        _col("QboEstimateLastModifiedAtUtc", "datetime"),
        _col("QboCheckedAtUtc", "datetime"),
        _col("QboCheckedByEntraId"),
        _col("QboCheckedByName"),
        _col(
            "QboDiffStatus", "choice",
            choices=("not_linked", "untracked", "unchanged", "modified", "missing"),
        ),
        _col("Revision", "number", required=True),
        _col("LastEventId"),
        _col("CreatedAtUtc", "datetime", required=True),
        _col("CreatedByEntraId"),
        _col("CreatedByName"),
        _col("UpdatedAtUtc", "datetime", required=True, indexed=True),
        _col("UpdatedByEntraId"),
        _col("UpdatedByName"),
        _col("SourceClient", "choice", choices=_SOURCE_CHOICES),
    ),
)


VEHICLE_EVENTS_LIST = SharePointListSpec(
    name=EVENTS_LIST_NAME,
    description="Immutable DTM production-operations vehicle timeline.",
    columns=(
        _col("SchemaVersion", "number", required=True),
        _col("EventId", required=True, indexed=True, unique=True),
        _col("RequestId", required=True, indexed=True, unique=True),
        _col("BuilderVehicleId", required=True, indexed=True),
        _col("BuilderProjectId", required=True, indexed=True),
        _col(
            "Workstream", "choice", required=True, indexed=True,
            choices=tuple(value.value for value in OperationsWorkstream),
        ),
        _col(
            "EventType", "choice", required=True, indexed=True,
            choices=tuple(value.value for value in OperationsEventType),
        ),
        _col("PreviousValue", "multiline"),
        _col("NewValue", "multiline"),
        _col("OccurredAtUtc", "datetime", required=True, indexed=True),
        _col("EffectiveDate", "date", indexed=True),
        _col("ActorEntraId", indexed=True),
        _col("ActorDisplayName"),
        _col("PerformedByName", indexed=True),
        _col("SourceClient", "choice", required=True, indexed=True, choices=_SOURCE_CHOICES),
        _col("SourceAppVersion"),
        _col("Reason", "multiline"),
        _col("RecordRevision", "number", required=True),
        _col(
            "CommitStatus", "choice", required=True, indexed=True,
            choices=("pending", "applied", "conflict"),
        ),
        _col("RecordSnapshotJson", "multiline", required=True),
    ),
)


# The phone client can create rows here, but it never edits the authoritative
# current or event lists. A standard-connector Power Automate flow validates a
# normal forward transition, applies it with the expected revision, and writes
# its result back to this request row for the phone to display.
OPERATIONS_REQUESTS_LIST = SharePointListSpec(
    name=REQUESTS_LIST_NAME,
    description="Append-only DTM phone status requests and processor results.",
    columns=(
        _col("SchemaVersion", "number", required=True),
        _col("RequestId", required=True, indexed=True, unique=True),
        _col("BuilderVehicleId", required=True, indexed=True),
        _col("ExpectedRevision", "number", required=True),
        _col(
            "Workstream", "choice", required=True, indexed=True,
            choices=("shop", "tray", "programming_qc", "final_finish"),
        ),
        _col(
            "RequestedStatus", "choice", required=True,
            choices=(
                "in_progress",
                "complete",
                "ready",
                "ready_for_wash_clean_photos",
                "ready_for_delivery",
                "delivered",
            ),
        ),
        _col("PerformedByName"),
        _col("SourceAppVersion"),
        _col(
            "ProcessingStatus", "choice", required=True, indexed=True,
            choices=(
                "pending",
                "processing",
                "applied",
                "unchanged",
                "conflict",
                "rejected",
                "failed",
            ),
        ),
        _col("ProcessingStartedAtUtc", "datetime"),
        _col("ProcessedAtUtc", "datetime", indexed=True),
        _col("ActorEntraId", indexed=True),
        _col("ActorDisplayName"),
        _col("ResultRevision", "number"),
        _col("ResultEventId"),
        _col("ResultMessage", "multiline"),
        _col("ProcessorRunId"),
    ),
)


OPERATIONS_LIST_SPECS = (VEHICLE_OPERATIONS_LIST, VEHICLE_EVENTS_LIST)
ALL_OPERATIONS_LIST_SPECS = (*OPERATIONS_LIST_SPECS, OPERATIONS_REQUESTS_LIST)

RECOVERY_SCHEMA_COLUMN_NAMES = {
    OPERATIONS_LIST_NAME: (
        "CreatedAtUtc",
        "CreatedByEntraId",
        "CreatedByName",
    ),
    EVENTS_LIST_NAME: (
        "CommitStatus",
        "RecordSnapshotJson",
    ),
}

DEADLINE_OVERRIDE_SCHEMA_COLUMN_NAMES = {
    OPERATIONS_LIST_NAME: ("MustDeliverOverrideDate",),
    EVENTS_LIST_NAME: (),
}

PARTS_ORDERED_SCHEMA_COLUMN_NAMES = {
    OPERATIONS_LIST_NAME: ("PartsOrderedAtUtc",),
    EVENTS_LIST_NAME: (),
}


def _validate_manifest() -> None:
    if len({spec.name for spec in ALL_OPERATIONS_LIST_SPECS}) != len(
        ALL_OPERATIONS_LIST_SPECS
    ):
        raise ValueError("Operations SharePoint list names must be unique")
    for spec in ALL_OPERATIONS_LIST_SPECS:
        names = [column.name for column in spec.columns]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate SharePoint column name in {spec.name}")
        if spec.indexed_column_count > 20:
            raise ValueError(f"SharePoint index budget exceeded for {spec.name}")
        for column in spec.columns:
            if len(column.name) > 32:
                raise ValueError(
                    f"SharePoint column name exceeds 32 characters: {column.name}"
                )
            if column.unique and not column.indexed:
                raise ValueError(f"Unique SharePoint column must be indexed: {column.name}")
            if column.kind == "choice" and not column.choices:
                raise ValueError(f"SharePoint choice column has no values: {column.name}")


_validate_manifest()
