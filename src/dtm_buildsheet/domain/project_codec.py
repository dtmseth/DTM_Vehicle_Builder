"""Serialization/deserialization codec for ProjectRecord and its nested types.

Both project_entry (persistence layer) and project_service (HTTP layer) import
from here so dict↔dataclass parsing lives in exactly one place.
"""
from __future__ import annotations

import uuid
from typing import Any

from .project_models import (
    BuildReferenceAsset,
    BuildReferenceAssignment,
    BuildUnit,
    CustomerInfo,
    EquipmentPreferences,
    IndividualUnit,
    ProjectRecord,
)


_REFERENCE_SCOPES = {"project", "unit_group", "individual"}
_REFERENCE_MEDIA_TYPES = {"photo", "video"}
_REFERENCE_SOURCE_KINDS = {"company_reference", "shop_completed"}


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── from-dict helpers ──────────────────────────────────────────────────────────

def customer_from_dict(d: Any) -> CustomerInfo:
    if not isinstance(d, dict):
        return CustomerInfo()
    from .agency_naming import effective_agency_abbreviation
    agency = str(d.get("agency", ""))
    return CustomerInfo(
        name=str(d.get("name", "")),
        agency=agency,
        agency_id=str(d.get("agency_id", "")),
        agency_abbreviation=effective_agency_abbreviation(
            d.get("agency_abbreviation", ""), agency,
        ),
        quote_number=str(d.get("quote_number", "")),
        build_year=str(d.get("build_year", "")),
        sales_rep=str(d.get("sales_rep", "")),
        sales_rep_id=str(d.get("sales_rep_id", "")),
        contact=str(d.get("contact", "")),
        phone=str(d.get("phone", "")),
        email=str(d.get("email", "")),
    )


def preferences_from_dict(d: Any) -> EquipmentPreferences:
    if not isinstance(d, dict):
        return EquipmentPreferences()
    brands = d.get("lighting_brands", [])
    return EquipmentPreferences(
        lighting_brands=[str(b) for b in brands] if isinstance(brands, list) else [],
        lighting_mode=str(d.get("lighting_mode", "duo")).lower()
        if str(d.get("lighting_mode", "duo")).lower() in {"duo", "trio"} else "duo",
        camera_brand=str(d.get("camera_brand", "")),
        push_bumper_brand=str(d.get("push_bumper_brand", "")),
        cage_brand=str(d.get("cage_brand", "")),
        console_brand=str(d.get("console_brand", "")),
        slick_top=bool(d.get("slick_top", False)),
        mixed_brands=bool(d.get("mixed_brands", False)),
        notes=str(d.get("notes", "")),
        lens=str(d.get("lens", "")),
    )


def reference_assignment_from_dict(d: Any) -> BuildReferenceAssignment:
    if not isinstance(d, dict):
        raise ValueError("BuildReferenceAssignment must be a dict")
    scope = str(d.get("scope", "project") or "project").strip().lower()
    if scope not in _REFERENCE_SCOPES:
        scope = "project"
    target_id = str(d.get("target_id", "") or "").strip()
    if scope == "project":
        target_id = ""
    try:
        sort_order = max(0, int(d.get("sort_order", 0)))
    except (TypeError, ValueError):
        sort_order = 0
    return BuildReferenceAssignment(
        scope=scope,
        target_id=target_id,
        note=str(d.get("note", "") or "").strip(),
        sort_order=sort_order,
    )


def reference_asset_from_dict(d: Any) -> BuildReferenceAsset:
    if not isinstance(d, dict):
        raise ValueError("BuildReferenceAsset must be a dict")
    reference_id = str(d.get("reference_id", "") or "").strip() or str(uuid.uuid4())
    media_type = str(d.get("media_type", "photo") or "photo").strip().lower()
    if media_type not in _REFERENCE_MEDIA_TYPES:
        media_type = "photo"
    source_kind = str(d.get("source_kind", "company_reference") or "company_reference").strip().lower()
    if source_kind not in _REFERENCE_SOURCE_KINDS:
        source_kind = "company_reference"
    try:
        source_size = max(0, int(d.get("source_size", 0)))
    except (TypeError, ValueError):
        source_size = 0
    raw_assignments = d.get("assignments", [])
    assignments = [
        reference_assignment_from_dict(item)
        for item in raw_assignments
        if isinstance(item, dict)
    ] if isinstance(raw_assignments, list) else []
    return BuildReferenceAsset(
        reference_id=reference_id,
        file_name=str(d.get("file_name", "") or "").strip(),
        media_type=media_type,
        source_kind=source_kind,
        source_drive_id=str(d.get("source_drive_id", "") or "").strip(),
        source_item_id=str(d.get("source_item_id", "") or "").strip(),
        source_path=str(d.get("source_path", "") or "").strip(),
        source_web_url=str(d.get("source_web_url", "") or "").strip(),
        source_etag=str(d.get("source_etag", "") or "").strip(),
        source_size=source_size,
        assignments=assignments,
    )


def individual_unit_from_dict(d: Any) -> IndividualUnit:
    if not isinstance(d, dict):
        raise ValueError("IndividualUnit must be a dict")
    ind_id = str(d.get("individual_id", "")).strip()
    if not ind_id:
        ind_id = str(uuid.uuid4())
    draft_id = d.get("draft_id")
    return IndividualUnit(
        individual_id=ind_id,
        unit_number=str(d.get("unit_number", "")),
        year=str(d.get("year", "")),
        make=str(d.get("make", "")),
        model=str(d.get("model", "")),
        color=str(d.get("color", "")),
        vin=str(d.get("vin", "")),
        existing_year=str(d.get("existing_year", "")),
        existing_make=str(d.get("existing_make", "")),
        existing_model=str(d.get("existing_model", "")),
        existing_build_type=str(d.get("existing_build_type", "")),
        existing_unit_number=str(d.get("existing_unit_number", "")),
        existing_vin=str(d.get("existing_vin", "")),
        notes=str(d.get("notes", "")),
        draft_id=str(draft_id) if draft_id is not None else None,
        output_path=str(d.get("output_path", "")),
        confirmed=bool(d.get("confirmed", False)),
        confirmed_at=str(d.get("confirmed_at", "")),
        status=str(d.get("status", "draft")) if str(d.get("status", "draft")) in {"draft", "finalized", "reopened"} else "draft",
        finalized_at=str(d.get("finalized_at", "")),
        finalized_by=str(d.get("finalized_by", "")),
        finalized_draft_fingerprint=str(d.get("finalized_draft_fingerprint", "")),
        final_check_version=str(d.get("final_check_version", "")),
        finalization_acknowledgements=list(d.get("finalization_acknowledgements") or []),
        reopened_at=str(d.get("reopened_at", "")),
        reopened_by=str(d.get("reopened_by", "")),
        reopen_reason=str(d.get("reopen_reason", "")),
        last_rendered_at=str(d.get("last_rendered_at", "")),
        last_rendered_by=str(d.get("last_rendered_by", "")),
        pdf_path=str(d.get("pdf_path", "")),
        last_exported_at=str(d.get("last_exported_at", "")),
        last_exported_by=str(d.get("last_exported_by", "")),
        qb_job_id=str(d.get("qb_job_id", "")),
        qb_project_id=str(d.get("qb_project_id", "")),
        qb_project_name=str(d.get("qb_project_name", "")),
        qb_estimate_id=str(d.get("qb_estimate_id", "")),
        qb_estimate_snapshot=dict(d.get("qb_estimate_snapshot") or {})
        if isinstance(d.get("qb_estimate_snapshot"), dict) else {},
        qb_estimate_snapshot_at=str(d.get("qb_estimate_snapshot_at", "")),
        qb_invoice_id=str(d.get("qb_invoice_id", "")),
        company_vehicle_folder_id=str(d.get("company_vehicle_folder_id", "")),
        company_vehicle_folder_name=str(d.get("company_vehicle_folder_name", "")),
        company_vehicle_folder_path=str(d.get("company_vehicle_folder_path", "")),
        company_folder_status=str(d.get("company_folder_status", "not_provisioned")),
        company_folder_error=str(d.get("company_folder_error", "")),
        company_pdf_item_id=str(d.get("company_pdf_item_id", "")),
        company_pdf_path=str(d.get("company_pdf_path", "")),
        company_publication_fingerprint=str(d.get("company_publication_fingerprint", "")),
        company_publication_status=str(d.get("company_publication_status", "not_published")),
        company_publication_error=str(d.get("company_publication_error", "")),
        shop_vehicle_folder_id=str(d.get("shop_vehicle_folder_id", "")),
        shop_vehicle_folder_name=str(d.get("shop_vehicle_folder_name", "")),
        shop_vehicle_folder_path=str(d.get("shop_vehicle_folder_path", "")),
        shop_folder_status=str(d.get("shop_folder_status", "not_provisioned")),
        shop_folder_error=str(d.get("shop_folder_error", "")),
        shop_pdf_item_id=str(d.get("shop_pdf_item_id", "")),
        shop_pdf_path=str(d.get("shop_pdf_path", "")),
        shop_publication_fingerprint=str(d.get("shop_publication_fingerprint", "")),
        shop_published_at=str(d.get("shop_published_at", "")),
        shop_publication_status=str(d.get("shop_publication_status", "not_published")),
        shop_publication_error=str(d.get("shop_publication_error", "")),
        shop_reference_items=list(d.get("shop_reference_items") or [])
        if isinstance(d.get("shop_reference_items"), list) else [],
    )


def build_unit_from_dict(d: Any) -> BuildUnit:
    if not isinstance(d, dict):
        raise ValueError("BuildUnit must be a dict")
    unit_id = str(d.get("unit_id", "")).strip()
    if not unit_id:
        unit_id = str(uuid.uuid4())
    quantity = max(1, int(d.get("quantity", 1)))
    draft_id = d.get("draft_id")
    individuals_raw = d.get("individuals", [])
    individuals = [individual_unit_from_dict(i) for i in individuals_raw if isinstance(i, dict)]
    return BuildUnit(
        unit_id=unit_id,
        vehicle_model=str(d.get("vehicle_model", "")),
        build_type=str(d.get("build_type", "")),
        preset_id=str(d.get("preset_id", "")),
        quantity=quantity,
        draft_id=str(draft_id) if draft_id is not None else None,
        output_path=str(d.get("output_path", "")),
        individuals=individuals,
        last_rendered_at=str(d.get("last_rendered_at", "")),
        last_rendered_by=str(d.get("last_rendered_by", "")),
        pdf_path=str(d.get("pdf_path", "")),
        last_exported_at=str(d.get("last_exported_at", "")),
        last_exported_by=str(d.get("last_exported_by", "")),
        status=str(d.get("status", "draft")) if str(d.get("status", "draft")) in {"draft", "finalized", "reopened"} else "draft",
        finalized_at=str(d.get("finalized_at", "")),
        finalized_by=str(d.get("finalized_by", "")),
        finalized_draft_fingerprint=str(d.get("finalized_draft_fingerprint", "")),
        final_check_version=str(d.get("final_check_version", "")),
        finalization_acknowledgements=list(d.get("finalization_acknowledgements") or []),
        reopened_at=str(d.get("reopened_at", "")),
        reopened_by=str(d.get("reopened_by", "")),
        reopen_reason=str(d.get("reopen_reason", "")),
        company_group_folder_id=str(d.get("company_group_folder_id", "")),
        company_group_folder_path=str(d.get("company_group_folder_path", "")),
        shop_group_folder_id=str(d.get("shop_group_folder_id", "")),
        shop_group_folder_path=str(d.get("shop_group_folder_path", "")),
    )


def project_from_dict(d: dict) -> ProjectRecord:
    customer = customer_from_dict(d.get("customer", {}))
    quote_numbers_raw = d.get("quote_numbers", [])
    quote_numbers = [
        str(value).strip() for value in quote_numbers_raw
        if str(value).strip()
    ] if isinstance(quote_numbers_raw, list) else []
    if customer.quote_number and customer.quote_number not in quote_numbers:
        quote_numbers.insert(0, customer.quote_number)
    references_raw = d.get("reference_assets", [])
    return ProjectRecord(
        project_id=str(d["project_id"]),
        created_at=str(d.get("created_at", _utcnow())),
        updated_at=str(d.get("updated_at", _utcnow())),
        customer=customer,
        preferences=preferences_from_dict(d.get("preferences", {})),
        build_units=[build_unit_from_dict(u) for u in d.get("build_units", [])],
        project_status=(
            str(d.get("project_status", "active"))
            if str(d.get("project_status", "active")) in {"active", "completed"}
            else "active"
        ),
        completed_at=str(d.get("completed_at", "")),
        completed_by=str(d.get("completed_by", "")),
        reactivated_at=str(d.get("reactivated_at", "")),
        reactivated_by=str(d.get("reactivated_by", "")),
        project_notes=str(d.get("project_notes", "") or "").strip(),
        quote_numbers=quote_numbers,
        reference_assets=[
            reference_asset_from_dict(item)
            for item in references_raw
            if isinstance(item, dict)
        ] if isinstance(references_raw, list) else [],
        reference_source_exclusions=[
            str(value).strip()
            for value in d.get("reference_source_exclusions", [])
            if value is not None and str(value).strip()
        ] if isinstance(d.get("reference_source_exclusions", []), list) else [],
        company_year_folder_id=str(d.get("company_year_folder_id", "")),
        company_year_folder_path=str(d.get("company_year_folder_path", "")),
        company_folder_status=str(d.get("company_folder_status", "not_provisioned")),
        company_folder_error=str(d.get("company_folder_error", "")),
        shop_year_folder_id=str(d.get("shop_year_folder_id", "")),
        shop_year_folder_path=str(d.get("shop_year_folder_path", "")),
        shop_folder_status=str(d.get("shop_folder_status", "not_provisioned")),
        shop_folder_error=str(d.get("shop_folder_error", "")),
    )
