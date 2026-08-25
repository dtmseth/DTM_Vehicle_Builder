from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CustomerInfo:
    name: str = ""
    agency: str = ""
    agency_id: str = ""
    quote_number: str = ""
    build_year: str = ""
    sales_rep: str = ""
    sales_rep_id: str = ""
    contact: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class EquipmentPreferences:
    lighting_brands: list[str] = field(default_factory=list)
    lighting_mode: str = "duo"
    camera_brand: str = ""
    push_bumper_brand: str = ""
    cage_brand: str = ""
    console_brand: str = ""
    slick_top: bool = False
    mixed_brands: bool = False
    notes: str = ""
    lens: str = ""              # agency default lens type: "clear", "colored", "smoked"


@dataclass
class IndividualUnit:
    individual_id: str
    unit_number: str = ""
    year: str = ""
    make: str = ""
    model: str = ""
    color: str = ""
    vin: str = ""
    existing_unit_number: str = ""
    existing_vin: str = ""
    notes: str = ""
    draft_id: str | None = None
    output_path: str = ""
    confirmed: bool = False
    confirmed_at: str = ""
    status: str = "draft"
    finalized_at: str = ""
    finalized_by: str = ""
    finalized_draft_fingerprint: str = ""
    final_check_version: str = ""
    finalization_acknowledgements: list[dict[str, Any]] = field(default_factory=list)
    reopened_at: str = ""
    reopened_by: str = ""
    reopen_reason: str = ""
    # ISO timestamp of the last successful PPTX render. Compared against
    # max(project.updated_at, draft.updated_at) to detect a stale output,
    # and against the PPTX file's mtime to detect a manual PowerPoint edit.
    last_rendered_at: str = ""
    last_rendered_by: str = ""  # display name of the signed-in M365 user
    pdf_path: str = ""
    last_exported_at: str = ""
    last_exported_by: str = ""
    # QuickBooks document links. Each individual vehicle can be linked to a
    # true QBO Project (created in QBO's UI while the app remains on the free
    # Accounting API tier). New estimates use both the agency Customer and
    # this ProjectRef; qb_job_id is retained only for older sub-customer work.
    qb_job_id: str = ""
    qb_project_id: str = ""
    qb_project_name: str = ""
    qb_estimate_id: str = ""
    qb_estimate_snapshot: dict[str, Any] = field(default_factory=dict)
    qb_estimate_snapshot_at: str = ""
    qb_invoice_id: str = ""


@dataclass
class BuildUnit:
    unit_id: str
    vehicle_model: str = ""
    build_type: str = ""
    preset_id: str = ""
    quantity: int = 1
    draft_id: str | None = None
    output_path: str = ""
    individuals: list[IndividualUnit] = field(default_factory=list)
    last_rendered_at: str = ""
    last_rendered_by: str = ""
    pdf_path: str = ""
    last_exported_at: str = ""
    last_exported_by: str = ""
    status: str = "draft"
    finalized_at: str = ""
    finalized_by: str = ""
    finalized_draft_fingerprint: str = ""
    final_check_version: str = ""
    finalization_acknowledgements: list[dict[str, Any]] = field(default_factory=list)
    reopened_at: str = ""
    reopened_by: str = ""
    reopen_reason: str = ""


@dataclass
class ProjectRecord:
    project_id: str
    created_at: str
    updated_at: str
    customer: CustomerInfo = field(default_factory=CustomerInfo)
    preferences: EquipmentPreferences = field(default_factory=EquipmentPreferences)
    build_units: list[BuildUnit] = field(default_factory=list)
    # A short instruction that belongs on every build sheet generated for this
    # project (and therefore this project build year).  Unit-specific final
    # page notes remain on the BuildDraft instead of being duplicated here.
    project_notes: str = ""
