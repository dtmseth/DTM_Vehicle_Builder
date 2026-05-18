"""Tests for project records (Phase 3)."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from dtm_buildsheet.domain.project_models import (
    BuildUnit,
    CustomerInfo,
    EquipmentPreferences,
    ProjectRecord,
)
from dtm_buildsheet.inputs.project_entry import (
    delete_project,
    list_projects,
    load_project,
    new_project,
    save_project,
)
from dtm_buildsheet.paths import AppPaths


# ── helpers ────────────────────────────────────────────────────────────────────

def _paths(tmp_path: Path) -> AppPaths:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return AppPaths(workspace_projects_dir=projects_dir)


def _unit(**kwargs) -> BuildUnit:
    defaults = dict(unit_id="unit-1", vehicle_model="Tahoe PPV", build_type="Patrol", preset_id="patrol_starter", quantity=1)
    defaults.update(kwargs)
    return BuildUnit(**defaults)


def _project(**kwargs) -> ProjectRecord:
    defaults = dict(
        customer=CustomerInfo(name="Test", agency="Test PD", quote_number="Q-001"),
        preferences=EquipmentPreferences(lighting_brands=["Whelen"], slick_top=True),
        build_units=[_unit()],
    )
    defaults.update(kwargs)
    return new_project(**defaults)


# ── new_project ────────────────────────────────────────────────────────────────

class TestNewProject:
    def test_generates_project_id(self):
        p = new_project()
        assert p.project_id
        assert len(p.project_id) > 0

    def test_explicit_project_id_preserved(self):
        p = new_project(project_id="my-proj")
        assert p.project_id == "my-proj"

    def test_timestamps_set(self):
        p = new_project()
        assert p.created_at
        assert p.updated_at

    def test_defaults_are_empty_models(self):
        p = new_project()
        assert isinstance(p.customer, CustomerInfo)
        assert isinstance(p.preferences, EquipmentPreferences)
        assert p.build_units == []

    def test_unsafe_id_rejected(self):
        with pytest.raises(ValueError):
            new_project(project_id="../escape")

    def test_slash_id_rejected(self):
        with pytest.raises(ValueError):
            new_project(project_id="foo/bar")

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError):
            new_project(project_id="")


# ── save / load round-trip ────────────────────────────────────────────────────

class TestSaveLoad:
    def test_save_creates_file(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        path = save_project(p, paths)
        assert path.exists()
        assert path.name == "project.json"

    def test_save_creates_project_subdir(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        save_project(p, paths)
        assert (paths.workspace_projects_dir / p.project_id).is_dir()

    def test_save_updates_updated_at(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        old_ts = p.updated_at
        time.sleep(0.01)
        save_project(p, paths)
        assert p.updated_at >= old_ts

    def test_load_roundtrip_basic_fields(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        save_project(p, paths)
        loaded = load_project(p.project_id, paths)
        assert loaded.project_id == p.project_id
        assert loaded.customer.agency == "Test PD"
        assert loaded.customer.quote_number == "Q-001"

    def test_load_roundtrip_preferences(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        save_project(p, paths)
        loaded = load_project(p.project_id, paths)
        assert loaded.preferences.lighting_brands == ["Whelen"]
        assert loaded.preferences.slick_top is True

    def test_load_roundtrip_build_units(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        save_project(p, paths)
        loaded = load_project(p.project_id, paths)
        assert len(loaded.build_units) == 1
        u = loaded.build_units[0]
        assert isinstance(u, BuildUnit)
        assert u.unit_id == "unit-1"
        assert u.vehicle_model == "Tahoe PPV"
        assert u.preset_id == "patrol_starter"
        assert u.quantity == 1

    def test_load_roundtrip_draft_id(self, tmp_path):
        paths = _paths(tmp_path)
        unit = _unit(draft_id="some-draft-id")
        p = new_project(build_units=[unit])
        save_project(p, paths)
        loaded = load_project(p.project_id, paths)
        assert loaded.build_units[0].draft_id == "some-draft-id"

    def test_load_roundtrip_null_draft_id(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        save_project(p, paths)
        loaded = load_project(p.project_id, paths)
        assert loaded.build_units[0].draft_id is None

    def test_file_is_valid_json(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        path = save_project(p, paths)
        data = json.loads(path.read_text("utf-8"))
        assert data["project_id"] == p.project_id
        assert "customer" in data
        assert "preferences" in data
        assert "build_units" in data

    def test_load_not_found_raises(self, tmp_path):
        paths = _paths(tmp_path)
        with pytest.raises(FileNotFoundError, match="not found"):
            load_project("nonexistent-project", paths)

    def test_unsafe_load_id_rejected(self, tmp_path):
        paths = _paths(tmp_path)
        with pytest.raises(ValueError):
            load_project("../etc/passwd", paths)


# ── optional fields / backward compat ─────────────────────────────────────────

class TestMissingOptionalFields:
    def test_missing_customer_loads_with_defaults(self, tmp_path):
        paths = _paths(tmp_path)
        p = new_project(project_id="minimal-proj")
        proj_dir = paths.workspace_projects_dir / "minimal-proj"
        proj_dir.mkdir()
        data = {"project_id": "minimal-proj", "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"}
        (proj_dir / "project.json").write_text(json.dumps(data), "utf-8")
        loaded = load_project("minimal-proj", paths)
        assert loaded.customer.agency == ""
        assert loaded.preferences.lighting_brands == []
        assert loaded.build_units == []

    def test_missing_contact_fields_load_with_defaults(self, tmp_path):
        paths = _paths(tmp_path)
        proj_dir = paths.workspace_projects_dir / "old-format"
        proj_dir.mkdir()
        data = {
            "project_id": "old-format",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "customer": {"name": "Alice", "agency": "City PD"},
        }
        (proj_dir / "project.json").write_text(json.dumps(data), "utf-8")
        loaded = load_project("old-format", paths)
        assert loaded.customer.name == "Alice"
        assert loaded.customer.phone == ""
        assert loaded.customer.email == ""
        assert loaded.customer.contact == ""

    def test_quantity_normalized_to_minimum_one(self, tmp_path):
        paths = _paths(tmp_path)
        proj_dir = paths.workspace_projects_dir / "qty-proj"
        proj_dir.mkdir()
        data = {
            "project_id": "qty-proj",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "build_units": [{"unit_id": "u1", "quantity": 0}],
        }
        (proj_dir / "project.json").write_text(json.dumps(data), "utf-8")
        loaded = load_project("qty-proj", paths)
        assert loaded.build_units[0].quantity == 1

    def test_negative_quantity_normalized(self, tmp_path):
        paths = _paths(tmp_path)
        proj_dir = paths.workspace_projects_dir / "neg-qty"
        proj_dir.mkdir()
        data = {
            "project_id": "neg-qty",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "build_units": [{"unit_id": "u1", "quantity": -5}],
        }
        (proj_dir / "project.json").write_text(json.dumps(data), "utf-8")
        loaded = load_project("neg-qty", paths)
        assert loaded.build_units[0].quantity == 1

    def test_missing_unit_id_auto_generated(self, tmp_path):
        paths = _paths(tmp_path)
        proj_dir = paths.workspace_projects_dir / "no-uid"
        proj_dir.mkdir()
        data = {
            "project_id": "no-uid",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "build_units": [{"vehicle_model": "Tahoe"}],
        }
        (proj_dir / "project.json").write_text(json.dumps(data), "utf-8")
        loaded = load_project("no-uid", paths)
        assert loaded.build_units[0].unit_id  # auto-generated UUID


# ── list_projects ──────────────────────────────────────────────────────────────

class TestListProjects:
    def test_empty_dir_returns_empty_list(self, tmp_path):
        paths = _paths(tmp_path)
        assert list_projects(paths) == []

    def test_missing_projects_dir_returns_empty_list(self, tmp_path):
        paths = AppPaths(workspace_projects_dir=tmp_path / "nonexistent")
        assert list_projects(paths) == []

    def test_returns_all_projects(self, tmp_path):
        paths = _paths(tmp_path)
        p1 = _project()
        p2 = _project()
        save_project(p1, paths)
        save_project(p2, paths)
        result = list_projects(paths)
        assert len(result) == 2
        ids = {p.project_id for p in result}
        assert p1.project_id in ids
        assert p2.project_id in ids

    def test_sorted_newest_first(self, tmp_path):
        paths = _paths(tmp_path)
        p1 = _project()
        save_project(p1, paths)
        time.sleep(0.02)
        p2 = _project()
        save_project(p2, paths)
        result = list_projects(paths)
        # p2 was saved last → updated_at is later → should appear first
        assert result[0].project_id == p2.project_id
        assert result[1].project_id == p1.project_id

    def test_skips_corrupt_files(self, tmp_path):
        paths = _paths(tmp_path)
        bad_dir = paths.workspace_projects_dir / "corrupt-proj"
        bad_dir.mkdir()
        (bad_dir / "project.json").write_text("not json{{{", "utf-8")
        good = _project()
        save_project(good, paths)
        result = list_projects(paths)
        assert len(result) == 1
        assert result[0].project_id == good.project_id

    def test_skips_dirs_without_project_json(self, tmp_path):
        paths = _paths(tmp_path)
        stray = paths.workspace_projects_dir / "stray-dir"
        stray.mkdir()
        good = _project()
        save_project(good, paths)
        result = list_projects(paths)
        assert len(result) == 1

    def test_all_results_are_project_records(self, tmp_path):
        paths = _paths(tmp_path)
        save_project(_project(), paths)
        save_project(_project(), paths)
        for p in list_projects(paths):
            assert isinstance(p, ProjectRecord)


# ── delete_project ─────────────────────────────────────────────────────────────

class TestDeleteProject:
    def test_delete_removes_directory(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        save_project(p, paths)
        delete_project(p.project_id, paths)
        assert not (paths.workspace_projects_dir / p.project_id).exists()

    def test_delete_removes_only_target(self, tmp_path):
        paths = _paths(tmp_path)
        p1 = _project()
        p2 = _project()
        save_project(p1, paths)
        save_project(p2, paths)
        delete_project(p1.project_id, paths)
        remaining = list_projects(paths)
        assert len(remaining) == 1
        assert remaining[0].project_id == p2.project_id

    def test_delete_not_found_raises(self, tmp_path):
        paths = _paths(tmp_path)
        with pytest.raises(FileNotFoundError):
            delete_project("nonexistent-project", paths)

    def test_delete_unsafe_id_rejected(self, tmp_path):
        paths = _paths(tmp_path)
        with pytest.raises(ValueError):
            delete_project("../escape", paths)

    def test_deleted_project_not_loadable(self, tmp_path):
        paths = _paths(tmp_path)
        p = _project()
        save_project(p, paths)
        delete_project(p.project_id, paths)
        with pytest.raises(FileNotFoundError):
            load_project(p.project_id, paths)


# ── CustomerInfo / EquipmentPreferences fields ─────────────────────────────────

class TestModels:
    def test_customer_all_fields(self):
        c = CustomerInfo(
            name="John",
            agency="City PD",
            quote_number="Q-123",
            sales_rep="Bob",
            contact="Jane",
            phone="555-0001",
            email="jane@pd.gov",
        )
        assert c.email == "jane@pd.gov"
        assert c.contact == "Jane"

    def test_preferences_lighting_brands_list(self):
        p = EquipmentPreferences(lighting_brands=["Whelen", "Code 3"])
        assert len(p.lighting_brands) == 2

    def test_build_unit_quantity_default(self):
        u = BuildUnit(unit_id="u1")
        assert u.quantity == 1

    def test_build_unit_draft_id_default_none(self):
        u = BuildUnit(unit_id="u1")
        assert u.draft_id is None

    def test_project_record_asdict_is_json_serialisable(self):
        p = new_project(
            customer=CustomerInfo(agency="PD"),
            preferences=EquipmentPreferences(lighting_brands=["Whelen"]),
            build_units=[BuildUnit(unit_id="u1", quantity=2)],
        )
        d = asdict(p)
        encoded = json.dumps(d)
        assert "PD" in encoded
        assert "Whelen" in encoded
