from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CustomerInfo:
    name: str = ""
    agency: str = ""
    agency_id: str = ""
    agency_abbreviation: str = ""
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
class BuildReferenceAssignment:
    """One use of a reference asset within a project hierarchy.

    ``scope`` is project, unit_group, or individual. Project assignments use an
    empty target_id; the other scopes point at a stable BuildUnit/IndividualUnit
    ID. Notes and order belong to the assignment so a reused historical image
    can carry instructions specific to the new build.
    """

    scope: str = "project"
    target_id: str = ""
    note: str = ""
    sort_order: int = 0


@dataclass
class BuildReferenceAsset:
    """Portable identity for a Company/Shop reference photo or video."""

    reference_id: str
    file_name: str = ""
    media_type: str = "photo"
    source_kind: str = "company_reference"
    source_drive_id: str = ""
    source_item_id: str = ""
    source_path: str = ""
    source_web_url: str = ""
    source_etag: str = ""
    source_size: int = 0
    assignments: list[BuildReferenceAssignment] = field(default_factory=list)


@dataclass
class IndividualUnit:
    individual_id: str
    unit_number: str = ""
    year: str = ""
    make: str = ""
    model: str = ""
    color: str = ""
    vin: str = ""
    existing_year: str = ""
    existing_make: str = ""
    existing_model: str = ""
    existing_build_type: str = ""
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
    # Durable SharePoint package identity. Folder/item IDs remain authoritative
    # when the readable year/model/build-type/unit/VIN label changes.
    company_vehicle_folder_id: str = ""
    company_vehicle_folder_name: str = ""
    company_vehicle_folder_path: str = ""
    company_folder_status: str = "not_provisioned"
    company_folder_error: str = ""
    company_pdf_item_id: str = ""
    company_pdf_path: str = ""
    company_publication_fingerprint: str = ""
    company_publication_status: str = "not_published"
    company_publication_error: str = ""
    shop_vehicle_folder_id: str = ""
    shop_vehicle_folder_name: str = ""
    shop_vehicle_folder_path: str = ""
    shop_folder_status: str = "not_provisioned"
    shop_folder_error: str = ""
    shop_pdf_item_id: str = ""
    shop_pdf_path: str = ""
    shop_publication_fingerprint: str = ""
    shop_published_at: str = ""
    shop_publication_status: str = "not_published"
    shop_publication_error: str = ""
    shop_reference_items: list[dict[str, Any]] = field(default_factory=list)


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
    # Durable group-folder identity lets year/agency/abbreviation/model/build
    # naming changes move the whole subtree instead of leaving empty parents.
    company_group_folder_id: str = ""
    company_group_folder_path: str = ""
    shop_group_folder_id: str = ""
    shop_group_folder_path: str = ""


@dataclass
class ProjectRecord:
    project_id: str
    created_at: str
    updated_at: str
    customer: CustomerInfo = field(default_factory=CustomerInfo)
    preferences: EquipmentPreferences = field(default_factory=EquipmentPreferences)
    build_units: list[BuildUnit] = field(default_factory=list)
    # Project lifecycle controls active-list vs archive placement. Completion
    # is organizational and reversible; sparse imported projects use the same
    # schema as current work.
    project_status: str = "active"
    completed_at: str = ""
    completed_by: str = ""
    reactivated_at: str = ""
    reactivated_by: str = ""
    # A short instruction that belongs on every build sheet generated for this
    # project (and therefore this project build year).  Unit-specific final
    # page notes remain on the BuildDraft instead of being duplicated here.
    project_notes: str = ""
    # A project is one agency build year. Quote/reference numbers are metadata,
    # not project identity; retain the legacy singular CustomerInfo field while
    # allowing every related quote to remain discoverable on the merged record.
    quote_numbers: list[str] = field(default_factory=list)
    # Source assets live in SharePoint and are referenced here by portable item
    # identity. Assignment scope determines which vehicle PDFs receive a photo.
    reference_assets: list[BuildReferenceAsset] = field(default_factory=list)
    # A removed year-folder photo stays removed from the app without deleting
    # its Company Files source. Stable identities prevent automatic rediscovery
    # from undoing the user's explicit choice.
    reference_source_exclusions: list[str] = field(default_factory=list)
    # Year-folder item IDs let an agency/year rename move the existing subtree
    # rather than creating a second tree. They are populated only after the
    # explicit Company/Shop cutover flags are enabled.
    company_year_folder_id: str = ""
    company_year_folder_path: str = ""
    company_folder_status: str = "not_provisioned"
    company_folder_error: str = ""
    shop_year_folder_id: str = ""
    shop_year_folder_path: str = ""
    shop_folder_status: str = "not_provisioned"
    shop_folder_error: str = ""
