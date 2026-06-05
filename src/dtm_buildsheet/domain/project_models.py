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
    camera_brand: str = ""
    push_bumper_brand: str = ""
    cage_brand: str = ""
    slick_top: bool = False
    mixed_brands: bool = False
    notes: str = ""


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
    # ISO timestamp of the last successful PPTX render. Compared against
    # max(project.updated_at, draft.updated_at) to detect a stale output,
    # and against the PPTX file's mtime to detect a manual PowerPoint edit.
    last_rendered_at: str = ""
    last_rendered_by: str = ""  # display name of the signed-in M365 user
    pdf_path: str = ""
    last_exported_at: str = ""
    last_exported_by: str = ""


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


@dataclass
class ProjectRecord:
    project_id: str
    created_at: str
    updated_at: str
    customer: CustomerInfo = field(default_factory=CustomerInfo)
    preferences: EquipmentPreferences = field(default_factory=EquipmentPreferences)
    build_units: list[BuildUnit] = field(default_factory=list)
