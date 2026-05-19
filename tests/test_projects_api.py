"""Tests for project service and draft-creation orchestration (Phase 4)."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from dtm_buildsheet.app.services.project_service import (
    handle_create_draft,
    handle_delete_project,
    handle_get_project,
    handle_list_projects,
    handle_save_project,
)
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

    def test_preserves_preferences(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        project = load_project(result["project_id"], paths)
        assert project.preferences.lighting_brands == ["Whelen", "Code 3"]
        assert project.preferences.slick_top is True
        assert project.preferences.camera_brand == "Axon"

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
        assert info["QuoteNumber"] == "Q-001"
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
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        # patrol_starter has parts
        assert len(draft.parts) > 0

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

    def test_project_id_derived_from_quote_number(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["customer"]["quote_number"] = "Q-999"
        create = handle_save_project(body, paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert "Q-999" in draft.vehicle_info["ProjectID"] or draft.vehicle_info["ProjectID"] == "Q-999"

    def test_second_create_draft_updates_draft_id(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result1 = handle_create_draft(pid, "unit-1", paths)
        result2 = handle_create_draft(pid, "unit-1", paths)
        project = load_project(pid, paths)
        # The unit's draft_id should reflect the most recent creation
        assert project.build_units[0].draft_id == result2["draft_id"]
