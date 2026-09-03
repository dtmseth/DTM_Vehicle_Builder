"""Read-only audit for adopting the canonical vehicle naming convention."""
from __future__ import annotations

import re

from ...domain.vehicle_naming import (
    qb_project_name,
    project_year_folder_name,
    safe_vehicle_folder_name,
    vehicle_display_name,
    vehicle_export_stem,
    vehicle_folder_name,
    vehicle_identity_ready,
)
from ...inputs.project_entry import list_projects
from ...paths import AppPaths
from .exports_upload_service import portable_export_filename, stable_export_stem


def _safe_segment(value: str, fallback: str) -> str:
    cleaned = safe_vehicle_folder_name(value)
    return cleaned if cleaned != "Unidentified Vehicle" else fallback


def build_vehicle_naming_migration_report(paths: AppPaths) -> dict:
    """Describe every local/shared-record rename without mutating anything."""
    projects = list_projects(paths)
    grouped_projects: dict[tuple[str, str], list] = {}
    for project in projects:
        agency_key = str(project.customer.agency_id or "").strip().casefold()
        if not agency_key:
            agency_key = re.sub(r"[^a-z0-9]+", "", project.customer.agency.casefold())
        year_key = re.sub(r"\D+", "", str(project.customer.build_year or ""))
        if agency_key and year_key:
            grouped_projects.setdefault((agency_key, year_key), []).append(project)
    duplicate_project_groups = [
        {
            "agency": group[0].customer.agency,
            "agency_id": group[0].customer.agency_id,
            "build_year": group[0].customer.build_year,
            "project_ids": [project.project_id for project in group],
            "vehicle_counts": {
                project.project_id: sum(len(unit.individuals) for unit in project.build_units)
                for project in group
            },
            "draft_counts": {
                project.project_id: sum(
                    bool(unit.draft_id) + sum(bool(item.draft_id) for item in unit.individuals)
                    for unit in project.build_units
                )
                for project in group
            },
            "quote_numbers": {
                project.project_id: list(project.quote_numbers)
                for project in group
            },
            "requires_manual_review": True,
        }
        for group in grouped_projects.values() if len(group) > 1
    ]
    rows = []
    manual_qbo = []
    for project in projects:
        for build_unit in project.build_units:
            for ordinal, individual in enumerate(build_unit.individuals, start=1):
                display_name = vehicle_display_name(
                    project, build_unit, individual, ordinal=ordinal,
                )
                desired_qb_name = qb_project_name(
                    project, build_unit, individual, ordinal=ordinal,
                )
                desired_stem = vehicle_export_stem(
                    project, build_unit, individual, ordinal=ordinal,
                ) + "_Updated"
                current_pptx = portable_export_filename(individual.output_path)
                current_pdf = portable_export_filename(individual.pdf_path)
                current_stems = {
                    stable_export_stem(value) for value in (current_pptx, current_pdf) if value
                }
                linked_qb = bool(str(individual.qb_project_id or "").strip())
                qb_rename_required = linked_qb and (
                    str(individual.qb_project_name or "").strip() != desired_qb_name
                )
                folder_rename_required = any(
                    current and current != vehicle_folder_name(
                        project, build_unit, individual, ordinal=ordinal,
                    )
                    for current in (
                        individual.company_vehicle_folder_name,
                        individual.shop_vehicle_folder_name,
                    )
                )
                agency = _safe_segment(project.customer.agency, "Unassigned Agency")
                year = _safe_segment(project_year_folder_name(project), "Unassigned Year")
                folder_name = vehicle_folder_name(
                    project, build_unit, individual, ordinal=ordinal,
                )
                row = {
                    "project_id": project.project_id,
                    "agency": project.customer.agency,
                    "agency_abbreviation": project.customer.agency_abbreviation,
                    "build_year": project.customer.build_year,
                    "unit_id": build_unit.unit_id,
                    "individual_id": individual.individual_id,
                    "canonical_vehicle_name": display_name,
                    "desired_vehicle_folder_name": folder_name,
                    "desired_company_vehicle_folder_path": "/".join((
                        "Vehicle Project Database", agency, year, folder_name,
                    )),
                    "desired_shop_vehicle_folder_path": "/".join((
                        "Shop Project Database", agency, year, folder_name,
                    )),
                    "current_company_vehicle_folder_path": individual.company_vehicle_folder_path,
                    "current_shop_vehicle_folder_path": individual.shop_vehicle_folder_path,
                    "company_folder_status": individual.company_folder_status,
                    "shop_folder_status": individual.shop_folder_status,
                    "current_company_folder_name": individual.company_vehicle_folder_name,
                    "current_shop_folder_name": individual.shop_vehicle_folder_name,
                    "folder_rename_required": folder_rename_required,
                    "folder_provisioning_required": not (
                        individual.company_vehicle_folder_id and individual.shop_vehicle_folder_id
                    ),
                    "current_company_pdf_path": individual.company_pdf_path,
                    "current_shop_pdf_path": individual.shop_pdf_path,
                    "current_pptx_name": current_pptx,
                    "current_pdf_name": current_pdf,
                    "desired_export_stem": desired_stem,
                    "export_rename_required": bool(current_stems and current_stems != {desired_stem}),
                    "qb_project_id": individual.qb_project_id,
                    "current_qb_project_name": individual.qb_project_name,
                    "desired_qb_project_name": desired_qb_name,
                    "manual_qb_rename_required": qb_rename_required,
                    "identifier_missing": not vehicle_identity_ready(individual),
                }
                rows.append(row)
                if qb_rename_required:
                    manual_qbo.append({
                        "agency": project.customer.agency,
                        "project_id": project.project_id,
                        "individual_id": individual.individual_id,
                        "qb_project_id": individual.qb_project_id,
                        "current_name": individual.qb_project_name,
                        "rename_to": desired_qb_name,
                    })
    return {
        "ok": True,
        "dry_run": True,
        "summary": {
            "vehicles": len(rows),
            "missing_identifiers": sum(row["identifier_missing"] for row in rows),
            "folder_renames": sum(row["folder_rename_required"] for row in rows),
            "export_renames": sum(row["export_rename_required"] for row in rows),
            "manual_qb_renames": len(manual_qbo),
            "duplicate_project_groups": len(duplicate_project_groups),
        },
        "vehicles": rows,
        "manual_qb_renames": manual_qbo,
        "duplicate_project_groups": duplicate_project_groups,
        "manual_instructions": (
            "Rename each listed QuickBooks Project in the QBO UI to rename_to, then verify its "
            "Project ID is unchanged. The approved Accounting API cannot rename or list Projects. "
            "Review every duplicate project group before merging; drafts, finalization, references, "
            "outputs, and QuickBooks links are intentionally never combined by this dry run."
        ),
    }
