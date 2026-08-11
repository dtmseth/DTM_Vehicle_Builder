"""Tests for project service and draft-creation orchestration (Phase 4)."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from dtm_buildsheet.app.services.project_service import (
    handle_create_draft,
    handle_create_individual_draft,
    handle_delete_project,
    handle_get_project,
    handle_list_projects,
    handle_save_project,
)
from dtm_buildsheet.app.services.agency_service import handle_save_agency
from dtm_buildsheet.domain.project_models import BuildUnit, CustomerInfo, EquipmentPreferences
from dtm_buildsheet.inputs.project_drafts import draft_to_project_input, load_draft
from dtm_buildsheet.inputs.project_entry import load_project, new_project, save_project
from dtm_buildsheet.paths import AppPaths, BUNDLED_PRESETS_DIR


# ── helpers ────────────────────────────────────────────────────────────────────

def _paths(tmp_path: Path) -> AppPaths:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=projects_dir,
        workspace_drafts_dir=drafts_dir,
        bundled_presets_dir=BUNDLED_PRESETS_DIR,
        workspace_presets_dir=tmp_path / "presets",
    )


def _project_body(**overrides) -> dict:
    body = {
        "customer": {
            "name": "Test Customer",
            "agency": "Test PD",
            "quote_number": "Q-001",
            "sales_rep": "Alice",
        },
        "preferences": {
            "lighting_brands": ["Whelen", "Code 3"],
            "camera_brand": "Axon",
            "slick_top": True,
        },
        "build_units": [
            {
                "unit_id": "unit-1",
                "vehicle_model": "Tahoe PPV",
                "build_type": "Patrol",
                "preset_id": "patrol_piu_standard",
                "quantity": 2,
            }
        ],
    }
    body.update(overrides)
    return body


# ── handle_save_project ────────────────────────────────────────────────────────

class TestHandleSaveProject:
    def test_creates_new_project(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        assert result["ok"] is True
        assert result["project_id"]

    def test_persists_to_disk(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        project = load_project(result["project_id"], paths)
        assert project.customer.agency == "Test PD"
        assert project.customer.quote_number == "Q-001"

    def test_preserves_build_units(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        project = load_project(result["project_id"], paths)
        assert len(project.build_units) == 1
        unit = project.build_units[0]
        assert unit.unit_id == "unit-1"
        assert unit.vehicle_model == "Tahoe PPV"
        assert unit.quantity == 2

    def test_custom_build_type_is_saved_only_on_its_project_unit(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body(build_units=[{
            "unit_id": "unit-drone",
            "vehicle_model": "Tahoe PPV",
            "build_type": "Drone Squad",
            "quantity": 1,
        }])
        result = handle_save_project(body, paths)

        project = load_project(result["project_id"], paths)
        assert project.build_units[0].build_type == "Drone Squad"

    def test_preserves_preferences(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        project = load_project(result["project_id"], paths)
        assert project.preferences.lighting_brands == ["Whelen", "Code 3"]
        assert project.preferences.slick_top is True
        assert project.preferences.camera_brand == "Axon"

    def test_shared_project_note_is_copied_to_new_draft(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(
            project_notes="Keep the completed unit indoors until pickup.",
        ), paths)

        result = handle_create_draft(create["project_id"], "unit-1", paths)

        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert draft.project_notes == "Keep the completed unit indoors until pickup."

    def test_new_project_copies_agency_defaults_when_preferences_omitted(self, tmp_path):
        paths = _paths(tmp_path)
        agency = handle_save_agency({
            "name": "Alpha PD",
            "default_preferences": {
                "lighting_brands": ["Whelen"],
                "camera_brand": "Axon",
                "console_brand": "Havis",
            },
        }, paths)["agency"]

        result = handle_save_project({
            "customer": {"agency": "Alpha PD", "agency_id": agency["agency_id"]},
            "build_units": [],
        }, paths)

        project = load_project(result["project_id"], paths)
        assert project.preferences.lighting_brands == ["Whelen"]
        assert project.preferences.camera_brand == "Axon"
        assert project.preferences.console_brand == "Havis"

    def test_explicit_project_preferences_override_agency_defaults(self, tmp_path):
        paths = _paths(tmp_path)
        agency = handle_save_agency({
            "name": "Alpha PD",
            "default_preferences": {"lighting_brands": ["Whelen"]},
        }, paths)["agency"]

        result = handle_save_project({
            "customer": {"agency": "Alpha PD", "agency_id": agency["agency_id"]},
            "preferences": {"lighting_brands": ["Code 3"]},
            "build_units": [],
        }, paths)

        project = load_project(result["project_id"], paths)
        assert project.preferences.lighting_brands == ["Code 3"]

    def test_explicit_project_id_honored(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project({**_project_body(), "project_id": "my-proj"}, paths)
        assert result["ok"] is True
        assert result["project_id"] == "my-proj"

    def test_update_existing_project(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        update_body = {"project_id": pid, "customer": {"agency": "Updated PD"}}
        handle_save_project(update_body, paths)
        project = load_project(pid, paths)
        assert project.customer.agency == "Updated PD"

    def test_unsafe_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project({"project_id": "../escape"}, paths)
        assert result["ok"] is False
        assert "error" in result

    def test_returns_path(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        assert "path" in result
        assert result["path"].endswith("project.json")


# ── handle_get_project ─────────────────────────────────────────────────────────

class TestHandleGetProject:
    def test_returns_project_dict(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_get_project(pid, paths)
        assert result["ok"] is True
        assert result["project"]["project_id"] == pid
        assert result["project"]["customer"]["agency"] == "Test PD"

    def test_missing_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_get_project("nonexistent", paths)
        assert result["ok"] is False
        assert "error" in result

    def test_unsafe_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_get_project("../escape", paths)
        assert result["ok"] is False


# ── handle_list_projects ───────────────────────────────────────────────────────

class TestHandleListProjects:
    def test_empty_returns_empty_list(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_list_projects(paths)
        assert result["ok"] is True
        assert result["projects"] == []

    def test_lists_saved_projects(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_project(_project_body(), paths)
        handle_save_project(_project_body(), paths)
        result = handle_list_projects(paths)
        assert result["ok"] is True
        assert len(result["projects"]) == 2

    def test_each_item_has_required_keys(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_project(_project_body(), paths)
        result = handle_list_projects(paths)
        p = result["projects"][0]
        for key in ("project_id", "customer", "preferences", "build_units"):
            assert key in p


# ── handle_delete_project ──────────────────────────────────────────────────────

class TestHandleDeleteProject:
    def test_deletes_project(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_delete_project(pid, paths)
        assert result["ok"] is True
        assert handle_get_project(pid, paths)["ok"] is False

    def test_missing_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_delete_project("nonexistent", paths)
        assert result["ok"] is False
        assert "error" in result

    def test_unsafe_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_delete_project("../escape", paths)
        assert result["ok"] is False


# ── handle_create_draft ────────────────────────────────────────────────────────

class TestHandleCreateDraft:
    def test_returns_ok_with_ids(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        assert result["ok"] is True
        assert result["draft_id"]
        assert result["project_id"] == pid
        assert result["unit_id"] == "unit-1"

    def test_draft_saved_to_disk(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft_id = result["draft_id"]
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        assert draft.draft_id == draft_id

    def test_draft_id_written_back_to_unit(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        project = load_project(pid, paths)
        assert project.build_units[0].draft_id == result["draft_id"]

    def test_vehicle_info_populated(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        info = draft.vehicle_info
        assert info["VehicleType"] == "Tahoe PPV"
        assert info["Agency"] == "Test PD"
        assert "QuoteNumber" not in info
        assert info["SalesRep"] == "Alice"
        assert info["BuildType"] == "Patrol"
        assert info["ProjectID"]

    def test_new_vehicle_block_set(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        nv = draft.vehicle_info.get("NewVehicle", {})
        assert nv.get("MODEL") == "Tahoe PPV"
        assert nv.get("UNIT ID") == "Group Build"
        assert draft.vehicle_info.get("ExistingVehicle") == {}

    def test_preset_parts_transferred(self, tmp_path):
        paths = _paths(tmp_path)
        # Seed a workspace preset (the cloud-synced cache stand-in) since
        # bundled presets no longer exist.
        paths.workspace_presets_dir.mkdir(parents=True, exist_ok=True)
        (paths.workspace_presets_dir / "patrol_piu_standard.json").write_text(
            json.dumps({
                "schema_version": 2,
                "preset_id": "patrol_piu_standard",
                "label": "Patrol PIU Standard",
                "vehicle_types": [],
                "agency_ids": [],
                "build_types": [],
                "tag": "",
                "parts": [{"name": "Headlight", "include": True}],
            })
        )
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert len(draft.parts) > 0

    def test_preset_retains_picker_skus_and_render_identity(self, tmp_path):
        paths = _paths(tmp_path)
        paths.workspace_presets_dir.mkdir(parents=True, exist_ok=True)
        (paths.workspace_presets_dir / "patrol_piu_standard.json").write_text(
            json.dumps({
                "schema_version": 3,
                "preset_id": "patrol_piu_standard",
                "label": "Patrol PIU Standard",
                "vehicle_types": [],
                "agency_ids": [],
                "build_types": [],
                "tag": "",
                "placement_overrides": {"front_interior_light_bar:front": {"dx": 0.1}},
                "parts": [{
                    "name": "Front Interior Light Bar",
                    "include": True,
                    "part_number": "Inner Edge FST",
                    "part_type": "front_interior_light_bar",
                    "components": [{"part_number": "BSFW50ZT", "quantity": 1}],
                    "picker_config": {"coverage": "full"},
                    "new_or_used": "Reused",
                }],
            })
        )
        create = handle_save_project(_project_body(), paths)
        result = handle_create_draft(create["project_id"], "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)

        assert draft.placement_overrides == {
            "front_interior_light_bar:front": {"dx": 0.1}
        }
        assert len(draft.parts) == 1
        part = draft.parts[0]
        assert part.part_type == "front_interior_light_bar"
        assert part.components == [{"part_number": "BSFW50ZT", "quantity": 1}]
        assert part.picker_config == {"coverage": "full"}
        assert part.new_or_used == "Reused"

    def test_individual_vehicle_retains_rich_preset_fields(self, tmp_path):
        paths = _paths(tmp_path)
        paths.workspace_presets_dir.mkdir(parents=True, exist_ok=True)
        (paths.workspace_presets_dir / "patrol_piu_standard.json").write_text(
            json.dumps({
                "schema_version": 3,
                "preset_id": "patrol_piu_standard",
                "label": "Patrol PIU Standard",
                "vehicle_types": [],
                "agency_ids": [],
                "build_types": [],
                "parts": [{
                    "name": "Rear Interior Light Bar",
                    "part_number": "Inner Edge RST",
                    "part_type": "rear_interior_light_bar",
                    "components": [{"part_number": "BS50ZT", "quantity": 1}],
                    "picker_config": {"coverage": "full"},
                }],
            })
        )
        body = _project_body()
        body["build_units"][0]["individuals"] = [{
            "individual_id": "vehicle-1",
            "unit_number": "101",
            "year": "2026",
        }]
        create = handle_save_project(body, paths)
        result = handle_create_individual_draft(
            create["project_id"], "unit-1", "vehicle-1", paths
        )
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)

        assert draft.parts[0].part_type == "rear_interior_light_bar"
        assert draft.parts[0].components == [
            {"part_number": "BS50ZT", "quantity": 1}
        ]
        assert draft.parts[0].picker_config == {"coverage": "full"}

    def test_blank_custom_used_when_no_preset(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["build_units"][0]["preset_id"] = ""
        create = handle_save_project(body, paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        assert result["ok"] is True
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert draft.parts == []  # blank_custom has no parts

    def test_missing_preset_falls_back_to_blank(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["build_units"][0]["preset_id"] = "nonexistent-preset-xyz"
        create = handle_save_project(body, paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        assert result["ok"] is True

    def test_equipment_preferences_in_notes(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        pref_notes = draft.notes.get("EQUIPMENT PREFERENCES", [])
        combined = " ".join(pref_notes)
        assert "Whelen" in combined
        assert "Code 3" in combined
        assert "Axon" in combined
        assert "Slick top: Yes" in combined

    def test_draft_converts_to_project_input(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        project_input = draft_to_project_input(draft)
        assert project_input.info["VehicleType"] == "Tahoe PPV"
        assert project_input.info["Agency"] == "Test PD"
        assert project_input.info["ProjectID"]
        assert isinstance(project_input.parts, list)

    def test_missing_project_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_create_draft("nonexistent-project", "unit-1", paths)
        assert result["ok"] is False
        assert "error" in result

    def test_missing_unit_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "no-such-unit", paths)
        assert result["ok"] is False
        assert "error" in result

    def test_project_id_uses_persistent_project_id(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["customer"]["quote_number"] = "Q-999"
        create = handle_save_project(body, paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert draft.vehicle_info["ProjectID"] == pid

    def test_second_create_draft_updates_draft_id(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result1 = handle_create_draft(pid, "unit-1", paths)
        result2 = handle_create_draft(pid, "unit-1", paths)
        project = load_project(pid, paths)
        # The unit's draft_id should reflect the most recent creation
        assert project.build_units[0].draft_id == result2["draft_id"]
