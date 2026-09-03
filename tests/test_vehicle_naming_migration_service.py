from __future__ import annotations

from pathlib import Path

from dtm_buildsheet.app.services.vehicle_naming_migration_service import (
    build_vehicle_naming_migration_report,
)
from dtm_buildsheet.domain.project_models import BuildUnit, CustomerInfo, IndividualUnit
from dtm_buildsheet.inputs.project_entry import new_project, save_project
from dtm_buildsheet.paths import AppPaths


def test_migration_report_lists_exact_manual_qbo_rename_without_writes(tmp_path: Path):
    paths = AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=tmp_path / "projects",
        workspace_output_dir=tmp_path / "output",
    )
    individual = IndividualUnit(
        individual_id="vehicle-1",
        unit_number="12",
        vin="ABC123456",
        model="Tahoe",
        output_path="output/Legacy_12_Updated_Aug1_2026_1-00PM.pptx",
        pdf_path="output/Legacy_12_Updated_Aug1_2026_1-00PM.pdf",
        qb_project_id="123",
        qb_project_name="Unit 12 | Build 2026",
    )
    project = new_project(
        project_id="project-1",
        customer=CustomerInfo(agency="Test PD", build_year="2027"),
        build_units=[BuildUnit(
            unit_id="group-1",
            vehicle_model="Tahoe",
            build_type="Patrol",
            individuals=[individual],
        )],
    )
    save_project(project, paths)
    before = (paths.workspace_projects_dir / "project-1" / "project.json").read_text(encoding="utf-8")

    report = build_vehicle_naming_migration_report(paths)

    assert report["dry_run"] is True
    assert report["summary"] == {
        "vehicles": 1,
        "missing_identifiers": 0,
        "folder_renames": 0,
        "export_renames": 1,
        "manual_qb_renames": 1,
        "duplicate_project_groups": 0,
    }
    row = report["vehicles"][0]
    assert row["canonical_vehicle_name"] == "2027 TP Tahoe - Patrol - Unit 12 - VIN 123456"
    assert row["desired_company_vehicle_folder_path"] == (
        "Vehicle Project Database/Test PD/TP - 2027/"
        "2027 TP Tahoe - Patrol - Unit 12 - VIN 123456"
    )
    assert row["desired_shop_vehicle_folder_path"] == (
        "Shop Project Database/Test PD/TP - 2027/"
        "2027 TP Tahoe - Patrol - Unit 12 - VIN 123456"
    )
    assert row["desired_export_stem"] == "2027_TP_Tahoe_Patrol_Unit_12_VIN_123456_Updated"
    assert report["manual_qb_renames"][0]["rename_to"] == (
        "2027 TP Tahoe | Patrol | Unit 12 | VIN 123456"
    )
    assert (paths.workspace_projects_dir / "project-1" / "project.json").read_text(encoding="utf-8") == before


def test_migration_report_flags_existing_same_agency_year_projects(tmp_path: Path):
    paths = AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=tmp_path / "projects",
        workspace_output_dir=tmp_path / "output",
    )
    for project_id, agency in (("project-a", "Lake County"), ("project-b", "Lake County!")):
        project = new_project(
            project_id=project_id,
            customer=CustomerInfo(agency=agency, build_year="2027"),
            build_units=[BuildUnit(unit_id="group-" + project_id)],
        )
        save_project(project, paths)

    report = build_vehicle_naming_migration_report(paths)

    assert report["summary"]["duplicate_project_groups"] == 1
    duplicate = report["duplicate_project_groups"][0]
    assert set(duplicate["project_ids"]) == {"project-a", "project-b"}
    assert duplicate["requires_manual_review"] is True
