from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dtm_buildsheet.app.services.draft_service import handle_save_override
from dtm_buildsheet.app.services.finalization_service import (
    handle_finalization_check,
    handle_finalize_build,
    handle_reopen_build,
)
from dtm_buildsheet.domain.project_models import BuildUnit, IndividualUnit
from dtm_buildsheet.inputs.project_drafts import DraftPart, new_draft, save_draft
from dtm_buildsheet.inputs.project_entry import load_project, new_project, save_project
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path):
    for name in ("projects", "drafts", "config", "output"):
        (tmp_path / name).mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=tmp_path / "projects",
        workspace_drafts_dir=tmp_path / "drafts",
        workspace_config_dir=tmp_path / "config",
        workspace_output_dir=tmp_path / "output",
    )


def _complete_final_check_parts(*, parent_line_id=""):
    return [
        DraftPart(name="Roof Light Bar", part_type="roof_light_bar", parent_line_id=parent_line_id),
        DraftPart(name="Siren Speaker", part_type="siren_speaker", parent_line_id=parent_line_id),
        DraftPart(name="Light Controller", part_type="light_controller", parent_line_id=parent_line_id),
        DraftPart(name="Control Head", part_type="control_head", parent_line_id=parent_line_id),
        DraftPart(name="Radio System", part_type="radio_system", parent_line_id=parent_line_id),
        DraftPart(name="Camera DVR", part_type="camera_dvr", parent_line_id=parent_line_id),
        DraftPart(name="Expansion Module", part_type="expansion_module", parent_line_id=parent_line_id),
    ]


def test_finalization_requires_current_pdf_locks_edits_and_records_reopen(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    import dtm_buildsheet.app.services.shared_work_service as shared
    monkeypatch.setattr(shared, "mirror_project_to_cloud_in_background", lambda *args, **kwargs: None)
    monkeypatch.setattr(shared, "mirror_draft_to_cloud_in_background", lambda *args, **kwargs: None)

    draft = new_draft(parts=_complete_final_check_parts())
    save_draft(draft, paths.workspace_drafts_dir)

    project = new_project()
    individual = IndividualUnit(
        individual_id="vehicle-1",
        unit_number="101",
        draft_id=draft.draft_id,
        pdf_path="output/final.pdf",
        last_exported_at="2999-01-01T00:00:00+00:00",
    )
    project.build_units = [BuildUnit(unit_id="unit-1", individuals=[individual])]
    save_project(project, paths)

    check = handle_finalization_check(project.project_id, "unit-1", "vehicle-1", paths)
    assert check["ok"]
    assert check["blocking"] == []
    assert check["warnings"] == []
    assert [item["id"] for item in check["checks"]] == [
        "current_pdf", "front_warning_coverage", "side_warning_coverage", "rear_warning_coverage",
        "no_siren_speaker", "lights_without_controller", "controller_without_control_head",
        "core_vehicle_interface", "photo_eye_without_roof_bar", "no_primary_light_bar",
        "docking_without_motion", "no_radio", "patrol_without_radar", "no_camera",
        "patrol_front_partition", "patrol_rear_partition", "no_expansion_module",
    ]
    assert all(item["status"] == "passed" for item in check["checks"])

    finalized = handle_finalize_build(project.project_id, "unit-1", "vehicle-1", {
        "fingerprint": check["fingerprint"], "acknowledgements": [],
    }, paths)
    assert finalized["ok"]
    stored = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert stored.status == "finalized"
    assert stored.finalized_at
    assert stored.finalized_by

    blocked = handle_save_override(draft.draft_id, {
        "key": "warning:front", "override": {"rotation": 10},
    }, paths)
    assert blocked["error"] == "build_finalized"

    reopened = handle_reopen_build(project.project_id, "unit-1", "vehicle-1", {
        "reason": "Move the grille lights",
    }, paths)
    assert reopened["ok"]
    stored = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert stored.status == "reopened"
    assert stored.reopen_reason == "Move the grille lights"
    assert handle_save_override(draft.draft_id, {
        "key": "warning:front", "override": {"rotation": 10},
    }, paths)["ok"]


def test_finalization_counts_guided_child_parts_and_compares_iso_timestamps(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    import dtm_buildsheet.app.services.shared_work_service as shared
    monkeypatch.setattr(shared, "mirror_project_to_cloud_in_background", lambda *args, **kwargs: None)
    monkeypatch.setattr(shared, "mirror_draft_to_cloud_in_background", lambda *args, **kwargs: None)

    draft = new_draft(parts=_complete_final_check_parts(parent_line_id="system"))
    save_draft(draft, paths.workspace_drafts_dir)
    exported_at = (
        datetime.fromisoformat(draft.updated_at).astimezone(timezone(timedelta(hours=-5)))
        + timedelta(seconds=1)
    ).isoformat()

    project = new_project()
    project.build_units = [BuildUnit(
        unit_id="unit-1", draft_id=draft.draft_id, pdf_path="output/final.pdf",
        last_exported_at=exported_at,
    )]
    save_project(project, paths)

    check = handle_finalization_check(project.project_id, "unit-1", "", paths)
    assert check["ok"]
    assert check["blocking"] == []
    assert check["warnings"] == []
    assert len(check["checks"]) == 17
    assert all(item["status"] == "passed" for item in check["checks"])


def test_finalization_returns_visible_warning_check_results(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    import dtm_buildsheet.app.services.shared_work_service as shared
    monkeypatch.setattr(shared, "mirror_project_to_cloud_in_background", lambda *args, **kwargs: None)

    draft = new_draft(parts=[DraftPart(name="Front Warning Light", part_type="front_warning")])
    save_draft(draft, paths.workspace_drafts_dir)
    project = new_project()
    project.build_units = [BuildUnit(
        unit_id="unit-1", draft_id=draft.draft_id, pdf_path="output/final.pdf",
        last_exported_at="2999-01-01T00:00:00+00:00",
    )]
    save_project(project, paths)

    check = handle_finalization_check(project.project_id, "unit-1", "", paths)
    statuses = {item["id"]: item["status"] for item in check["checks"]}
    assert statuses["current_pdf"] == "passed"
    assert statuses["front_warning_coverage"] == "passed"
    assert statuses["side_warning_coverage"] == "warning"
    assert statuses["rear_warning_coverage"] == "warning"
    assert statuses["no_siren_speaker"] == "warning"
    assert statuses["lights_without_controller"] == "warning"
    warning_ids = {warning["id"] for warning in check["warnings"]}
    assert {
        "side_warning_coverage", "rear_warning_coverage", "no_siren_speaker",
        "lights_without_controller", "photo_eye_without_roof_bar", "no_primary_light_bar",
        "no_radio", "no_camera", "no_expansion_module",
    } <= warning_ids


def test_finalization_patrol_and_dependency_checks_are_visible(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    import dtm_buildsheet.app.services.shared_work_service as shared
    monkeypatch.setattr(shared, "mirror_project_to_cloud_in_background", lambda *args, **kwargs: None)

    draft = new_draft(parts=[
        DraftPart(
            name="CenCom Core", part_type="light_controller", part_number="C399",
            picker_config={"product_id": "whelen_core"},
        ),
        DraftPart(name="Docking Station", part_type="docking_station"),
        DraftPart(name="Front Interior Light Bar", part_type="front_interior_light_bar"),
    ])
    save_draft(draft, paths.workspace_drafts_dir)
    project = new_project()
    project.build_units = [BuildUnit(
        unit_id="unit-1", build_type="Patrol", draft_id=draft.draft_id,
        pdf_path="output/final.pdf", last_exported_at="2999-01-01T00:00:00+00:00",
    )]
    save_project(project, paths)

    check = handle_finalization_check(project.project_id, "unit-1", "", paths)
    statuses = {item["id"]: item["status"] for item in check["checks"]}
    assert statuses["core_vehicle_interface"] == "warning"
    assert statuses["photo_eye_without_roof_bar"] == "warning"
    assert statuses["no_primary_light_bar"] == "passed"
    assert statuses["docking_without_motion"] == "warning"
    assert statuses["patrol_without_radar"] == "warning"
    assert statuses["patrol_front_partition"] == "warning"
    assert statuses["patrol_rear_partition"] == "warning"


def test_finalization_accepts_core_canport_photo_eye_motion_and_patrol_equipment(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    import dtm_buildsheet.app.services.shared_work_service as shared
    monkeypatch.setattr(shared, "mirror_project_to_cloud_in_background", lambda *args, **kwargs: None)

    draft = new_draft(parts=[
        DraftPart(name="Front Interior Light Bar", part_type="front_interior_light_bar"),
        DraftPart(name="Rear Interior Light Bar", part_type="rear_interior_light_bar"),
        DraftPart(name="Mirror Warning", part_type="mirror_warning"),
        DraftPart(name="Siren Speaker", part_type="siren_speaker"),
        DraftPart(name="CenCom Core", part_type="light_controller", part_number="C399"),
        DraftPart(name="Control Head", part_type="control_head"),
        DraftPart(name="CANPORT Interface", part_type="cable", part_number="C399K3"),
        DraftPart(name="Photo Eye", part_type="photo_eye"),
        DraftPart(name="Docking Station", part_type="docking_station"),
        DraftPart(name="Motion Attachment", part_type="motion_attachment"),
        DraftPart(name="Radio System", part_type="radio_system"),
        DraftPart(name="Radar System", part_type="radar_system"),
        DraftPart(name="Camera DVR", part_type="camera_dvr"),
        DraftPart(name="Front Partition", part_type="front_partition"),
        DraftPart(name="Rear Partition", part_type="rear_partition"),
        DraftPart(name="Expansion Module", part_type="expansion_module"),
    ])
    save_draft(draft, paths.workspace_drafts_dir)
    project = new_project()
    project.build_units = [BuildUnit(
        unit_id="unit-1", build_type="Patrol", draft_id=draft.draft_id,
        pdf_path="output/final.pdf", last_exported_at="2999-01-01T00:00:00+00:00",
    )]
    save_project(project, paths)

    check = handle_finalization_check(project.project_id, "unit-1", "", paths)
    assert check["warnings"] == []
    assert all(item["status"] == "passed" for item in check["checks"])
