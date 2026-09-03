from __future__ import annotations

from pathlib import Path

from dtm_buildsheet.app.services.draft_service import handle_generate_from_draft
from dtm_buildsheet.app.services.generation_service import finalize_output
from dtm_buildsheet.domain.plan_models import BuildPlan
from dtm_buildsheet.domain.project_models import BuildUnit, CustomerInfo, IndividualUnit
from dtm_buildsheet.inputs.project_drafts import DraftPart, new_draft, save_draft
from dtm_buildsheet.inputs.project_entry import new_project, save_project
from dtm_buildsheet.paths import AppPaths, BUNDLED_PRESETS_DIR


def _paths(tmp_path: Path) -> AppPaths:
    for name in ("drafts", "projects", "output", "presets"):
        (tmp_path / name).mkdir()
    return AppPaths(
        workspace_drafts_dir=tmp_path / "drafts",
        workspace_projects_dir=tmp_path / "projects",
        workspace_output_dir=tmp_path / "output",
        bundled_presets_dir=BUNDLED_PRESETS_DIR,
        workspace_presets_dir=tmp_path / "presets",
    )


def test_finalize_output_never_uploads_local_powerpoint(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    pptx = paths.workspace_output_dir / "conversion-only.pptx"
    pptx.write_bytes(b"PPTX")
    calls = []
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.exports_upload_service.upload_export_in_background",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = finalize_output(pptx, paths, agency="Test", year="2026")

    assert result["output_path"] == str(pptx)
    assert calls == []


def test_generate_from_project_draft_without_project_output_root(tmp_path, monkeypatch):
    """Regression: SharePoint agency/year metadata must not depend on custom folders."""
    paths = _paths(tmp_path)
    draft = new_draft(
        vehicle_info={
            "VehicleType": "PIU",
            "Agency": "Original PD",
            "BuildYear": "",
            "ProjectID": "Q-100",
            "NewVehicle": {"UNIT ID": "Old", "YEAR": "", "VIN": "STALEVIN"},
            "ExistingVehicle": {"UNIT ID": "OLD-03", "VIN": "OLDVIN654321"},
        },
        parts=[DraftPart(name="Unknown Test Part", include=False)],
    )
    save_draft(draft, paths.workspace_drafts_dir)

    project = new_project("proj-1")
    project.customer = CustomerInfo(
        agency="Cloud Agency",
        quote_number="Q-100",
        build_year="2026",
    )
    project.build_units = [
        BuildUnit(
            unit_id="unit-1",
            vehicle_model="PIU",
            build_type="Patrol",
            individuals=[
                IndividualUnit(
                    individual_id="ind-1",
                    unit_number="A-12",
                    year="2025",
                    vin="ACTUAL123456",
                    existing_year="2018",
                    existing_make="Ford",
                    existing_model="Police Interceptor Utility",
                    existing_build_type="Patrol",
                    existing_unit_number="OLD-03",
                    existing_vin="OLDVIN654321",
                    notes="Install the customer radio in the upper console position.",
                    draft_id=draft.draft_id,
                )
            ],
        )
    ]
    save_project(project, paths)

    def fake_render_plan_to_ppt(plan, active_paths):
        pptx = active_paths.workspace_output_dir / "Cloud_Agency_A-12_2026_Updated_Jun5_2026_9-00AM.pptx"
        pptx.write_bytes(b"pptx")
        return pptx

    monkeypatch.setattr(
        "dtm_buildsheet.config.loader.load_configs",
        lambda active_paths: object(),
    )
    captured = {}
    def fake_build_plan(project_input, config):
        captured["info"] = project_input.info
        return BuildPlan(version="test", project={}, planned_parts=[])

    monkeypatch.setattr(
        "dtm_buildsheet.planning.planner.build_plan",
        fake_build_plan,
    )
    monkeypatch.setattr(
        "dtm_buildsheet.render_ppt.render_plan_to_ppt",
        fake_render_plan_to_ppt,
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.exports_upload_service.upload_export_in_background",
        lambda *args, **kwargs: None,
    )

    result = handle_generate_from_draft(
        {"draft_id": draft.draft_id, "project_id": project.project_id},
        paths,
    )

    assert result["ok"] is True, result.get("error")
    assert result["output_path"].endswith(".pptx")
    assert Path(result["output_path"]).parent == paths.workspace_output_dir
    assert captured["info"]["NewVehicle"]["UNIT ID"] == "A-12"
    assert captured["info"]["NewVehicle"]["VIN"] == "ACTUAL123456"
    assert captured["info"]["UnitNotes"] == (
        "Install the customer radio in the upper console position."
    )
    assert captured["info"]["ExistingVehicle"] == {
        "YEAR": "2018",
        "MAKE": "Ford",
        "MODEL": "Police Interceptor Utility",
        "BUILD TYPE": "Patrol",
        "UNIT ID": "OLD-03",
        "VIN": "OLDVIN654321",
    }
