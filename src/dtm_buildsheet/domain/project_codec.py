"""Serialization/deserialization codec for ProjectRecord and its nested types.

Both project_entry (persistence layer) and project_service (HTTP layer) import
from here so dict↔dataclass parsing lives in exactly one place.
"""
from __future__ import annotations

import uuid
from typing import Any

from .project_models import (
    BuildUnit,
    CustomerInfo,
    EquipmentPreferences,
    IndividualUnit,
    ProjectRecord,
)


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── from-dict helpers ──────────────────────────────────────────────────────────

def customer_from_dict(d: Any) -> CustomerInfo:
    if not isinstance(d, dict):
        return CustomerInfo()
    return CustomerInfo(
        name=str(d.get("name", "")),
        agency=str(d.get("agency", "")),
        agency_id=str(d.get("agency_id", "")),
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
    )


def project_from_dict(d: dict) -> ProjectRecord:
    return ProjectRecord(
        project_id=str(d["project_id"]),
        created_at=str(d.get("created_at", _utcnow())),
        updated_at=str(d.get("updated_at", _utcnow())),
        customer=customer_from_dict(d.get("customer", {})),
        preferences=preferences_from_dict(d.get("preferences", {})),
        build_units=[build_unit_from_dict(u) for u in d.get("build_units", [])],
        project_notes=str(d.get("project_notes", "") or "").strip(),
    )
