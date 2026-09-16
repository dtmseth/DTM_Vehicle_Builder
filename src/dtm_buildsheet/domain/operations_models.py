"""Domain models for the shared production-operations workflow.

These models contain no SharePoint, Graph, Power Apps, or browser behavior. The
machine values are the durable contract; clients map them to friendly labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable


OPERATIONS_SCHEMA_VERSION = 5
QBO_OBSERVATION_STALE_HOURS = 24


class OperationsWorkstream(StrEnum):
    RECORD = "record"
    ACCEPTANCE = "acceptance"
    AVAILABILITY = "availability"
    SCHEDULE = "schedule"
    PARTS = "parts"
    SHOP = "shop"
    TRAY = "tray"
    PROGRAMMING_QC = "programming_qc"
    FINAL_FINISH = "final_finish"
    DELIVERY = "delivery"
    QBO = "qbo"


class OperationsEventType(StrEnum):
    RECORD_CREATED = "record_created"
    PROJECTION_REFRESHED = "projection_refreshed"
    STATUS_CHANGED = "status_changed"
    ACCEPTANCE_CHANGED = "acceptance_changed"
    AVAILABILITY_CHANGED = "availability_changed"
    SCHEDULE_CHANGED = "schedule_changed"
    DELIVERY_CHANGED = "delivery_changed"
    QBO_OBSERVED = "qbo_observed"


class OperationsSource(StrEnum):
    BUILDER_DESKTOP = "builder_desktop"
    POWER_APPS_MOBILE = "power_apps_mobile"
    MIGRATION = "migration"
    SYSTEM = "system"


class ProjectState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    COMPLETED = "completed"


class AcceptanceStatus(StrEnum):
    NOT_ACCEPTED = "not_accepted"
    ACCEPTED = "accepted"


class ProjectAcceptanceTag(StrEnum):
    NOT_ACCEPTED = "not_accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    ACCEPTED = "accepted"


class ScheduleBucket(StrEnum):
    PROSPECTIVE = "prospective"
    UNSCHEDULED = "unscheduled"
    SCHEDULED = "scheduled"


class AcceptanceSource(StrEnum):
    QBO = "qbo"
    MANUAL = "manual"
    MIGRATION = "migration"


class VehicleAvailabilityStatus(StrEnum):
    AWAITING_DETAILS = "awaiting_details"
    WAITING_ON_DEALER = "waiting_on_dealer"
    WAITING_ON_AGENCY = "waiting_on_agency"
    READY_FOR_PICKUP = "ready_for_pickup"
    AT_DTM = "at_dtm"
    DELIVERED = "delivered"


class PartsStatus(StrEnum):
    ORDERED = "ordered"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    PARTS_READY = "parts_ready"


class ShopStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


class TrayStatus(StrEnum):
    NOT_READY = "not_ready"
    READY = "ready"
    COMPLETE = "complete"


class ProgrammingQcStatus(StrEnum):
    NOT_READY = "not_ready"
    READY = "ready"
    COMPLETE = "complete"


class FinalFinishStatus(StrEnum):
    NOT_READY = "not_ready"
    READY_FOR_WASH_CLEAN_PHOTOS = "ready_for_wash_clean_photos"
    READY_FOR_DELIVERY = "ready_for_delivery"
    DELIVERED = "delivered"


@dataclass(frozen=True)
class OperationsActor:
    user_id: str
    display_name: str
    roles: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BuilderVehicleProjection:
    """Builder-owned facts copied into the shared Operations record.

    Keeping this as a narrow value object prevents a project save from
    replacing scheduling, production, delivery, or QBO-observation state.
    ``vehicle_id`` is the opaque IndividualUnit ID and remains authoritative
    when any human-readable name, unit number, or VIN changes.
    """

    vehicle_id: str
    project_id: str
    title: str = ""
    agency_id: str = ""
    agency_name: str = ""
    build_year: str = ""
    unit_number: str = ""
    vin: str = ""
    vehicle_label: str = ""
    assigned_salesperson_id: str = ""
    assigned_salesperson_name: str = ""
    build_finalized: bool = False
    build_finalized_at: str = ""
    project_state: ProjectState = ProjectState.ACTIVE


@dataclass
class VehicleOperations:
    """Current query-friendly projection for one individual vehicle."""

    vehicle_id: str
    project_id: str
    # Read-time Builder metadata; not new SharePoint columns.
    project_type: str = "build"
    service_details: dict = field(default_factory=dict)
    schema_version: int = OPERATIONS_SCHEMA_VERSION
    revision: int = 0

    title: str = ""
    agency_id: str = ""
    agency_name: str = ""
    build_year: str = ""
    unit_number: str = ""
    vin: str = ""
    vehicle_label: str = ""
    assigned_salesperson_id: str = ""
    assigned_salesperson_name: str = ""
    build_finalized: bool = False
    build_finalized_at: str = ""
    shop_folder_url: str = ""
    build_sheet_url: str = ""
    parts_list_url: str = ""
    project_state: ProjectState = ProjectState.ACTIVE

    acceptance_status: AcceptanceStatus = AcceptanceStatus.NOT_ACCEPTED
    accepted_at: str = ""
    acceptance_source: str = ""
    acceptance_changed_at: str = ""

    # This describes where/when the physical customer vehicle is available.
    # Build progress and delivery readiness remain in their own workstreams so
    # users do not have to maintain duplicate statuses.
    vehicle_availability_status: VehicleAvailabilityStatus = (
        VehicleAvailabilityStatus.AWAITING_DETAILS
    )
    vehicle_availability_status_changed_at: str = ""
    vehicle_available_date: str = ""
    vehicle_at_dtm_date: str = ""

    scheduled_week_of: str = ""
    planned_start_date: str = ""
    target_finish_date: str = ""
    schedule_changed_at: str = ""
    commitment_start_date: str = ""
    must_deliver_override_date: str = ""
    must_deliver_by_date: str = ""

    ready_to_build_override: bool = False
    ready_to_build_override_reason: str = ""
    ready_to_build_override_at: str = ""
    ready_to_build_override_by_id: str = ""
    ready_to_build_override_by_name: str = ""

    # Blank means receiving has not begun. It is intentionally not another
    # user-facing status value.
    parts_status: str = ""
    parts_status_changed_at: str = ""
    parts_ordered_at: str = ""
    parts_partially_received_at: str = ""
    parts_received_at: str = ""
    parts_ready_at: str = ""

    # Blank means the build has not started. The first explicit action changes
    # it to in_progress and stamps shop_started_at.
    shop_status: str = ""
    shop_status_changed_at: str = ""
    shop_started_at: str = ""
    shop_completed_at: str = ""

    tray_status: TrayStatus = TrayStatus.NOT_READY
    tray_status_changed_at: str = ""
    tray_ready_at: str = ""
    tray_completed_at: str = ""

    programming_qc_status: ProgrammingQcStatus = ProgrammingQcStatus.NOT_READY
    programming_qc_status_changed_at: str = ""
    programming_qc_ready_at: str = ""
    programming_qc_completed_at: str = ""

    final_finish_status: FinalFinishStatus = FinalFinishStatus.NOT_READY
    final_finish_status_changed_at: str = ""
    final_finish_ready_at: str = ""
    ready_for_delivery_at: str = ""

    delivered_date: str = ""
    delivery_method: str = ""

    # Shared QBO observation only. Estimate lines and financial payloads never
    # belong on this model.
    qbo_project_id: str = ""
    qbo_project_name: str = ""
    qbo_estimate_id: str = ""
    qbo_estimate_number: str = ""
    qbo_estimate_status: str = ""
    qbo_estimate_sent_status: str = ""
    qbo_estimate_sent_at: str = ""
    qbo_estimate_accepted_at: str = ""
    qbo_estimate_last_modified_at: str = ""
    qbo_checked_at: str = ""
    qbo_checked_by_id: str = ""
    qbo_checked_by_name: str = ""
    qbo_diff_status: str = "not_linked"

    created_at: str = ""
    created_by_id: str = ""
    created_by_name: str = ""
    updated_at: str = ""
    updated_by_id: str = ""
    updated_by_name: str = ""
    source_client: OperationsSource = OperationsSource.SYSTEM
    last_event_id: str = ""


@dataclass(frozen=True)
class OperationsEvent:
    """One immutable, idempotent mutation in a vehicle's timeline."""

    event_id: str
    request_id: str
    vehicle_id: str
    project_id: str
    workstream: OperationsWorkstream
    event_type: OperationsEventType
    previous_value: str
    new_value: str
    occurred_at: str
    actor_id: str
    actor_display_name: str
    source_client: OperationsSource
    performed_by_name: str = ""
    source_app_version: str = ""
    effective_date: str = ""
    reason: str = ""
    record_revision: int = 0
    schema_version: int = OPERATIONS_SCHEMA_VERSION


@dataclass(frozen=True)
class OperationsMutationResult:
    record: VehicleOperations
    event: OperationsEvent | None
    unchanged: bool = False
    duplicate: bool = False


def project_acceptance_tag(
    statuses: Iterable[AcceptanceStatus | str],
) -> ProjectAcceptanceTag:
    """Summarize per-vehicle acceptance for one active project card."""

    normalized = [
        value.value if isinstance(value, AcceptanceStatus) else str(value)
        for value in statuses
    ]
    if not normalized or not any(value == AcceptanceStatus.ACCEPTED for value in normalized):
        return ProjectAcceptanceTag.NOT_ACCEPTED
    if all(value == AcceptanceStatus.ACCEPTED for value in normalized):
        return ProjectAcceptanceTag.ACCEPTED
    return ProjectAcceptanceTag.PARTIALLY_ACCEPTED


def calculate_commitment_dates(
    vehicle_available_date: str,
    parts_received_at: str,
) -> tuple[str, str]:
    """Return commitment start and Must Deliver By dates under the 60-day rule.

    The business clock starts on the later of the vehicle-available date and
    the date all required DTM parts were received. Invalid or incomplete input
    deliberately yields no derived dates instead of inventing a deadline.
    """

    try:
        available = date.fromisoformat(str(vehicle_available_date).strip()[:10])
        parts_received = date.fromisoformat(str(parts_received_at).strip()[:10])
    except (TypeError, ValueError):
        return "", ""
    commitment_start = max(available, parts_received)
    return commitment_start.isoformat(), (commitment_start + timedelta(days=60)).isoformat()


def schedule_bucket(record: VehicleOperations) -> ScheduleBucket:
    """Derive the scheduling queue without another user-maintained status."""

    if record.acceptance_status != AcceptanceStatus.ACCEPTED:
        return ScheduleBucket.PROSPECTIVE
    if str(record.scheduled_week_of or "").strip():
        return ScheduleBucket.SCHEDULED
    return ScheduleBucket.UNSCHEDULED


def is_ready_to_build(record: VehicleOperations) -> bool:
    """Derive physical build readiness, honoring a reasoned manager override."""

    if record.project_type != 'build':
        from .project_types import physical_readiness
        return all(physical_readiness(record))
    if record.ready_to_build_override:
        return True
    return (
        record.build_finalized
        and record.parts_status == PartsStatus.PARTS_READY.value
        and record.vehicle_availability_status == VehicleAvailabilityStatus.AT_DTM
    )


def qbo_observation_is_stale(
    checked_at: str,
    *,
    as_of: datetime | None = None,
    stale_after_hours: int = QBO_OBSERVATION_STALE_HOURS,
) -> bool:
    """Return whether the shared QBO snapshot should show a stale warning."""

    raw = str(checked_at or "").strip()
    if not raw:
        return True
    try:
        observed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    reference = as_of or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age = reference.astimezone(timezone.utc) - observed.astimezone(timezone.utc)
    return age >= timedelta(hours=max(0, stale_after_hours))
