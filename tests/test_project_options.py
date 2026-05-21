"""Tests for the config-driven project options endpoint.

`project_options.json` is served through the generic config loader after Phase 0
(see app/routes/config.py GET_ROUTES and config/schemas.REQUIRED_CONFIG_FILES).
The dedicated project_options_service is gone; behavior is exercised through
config.store.load_config and the validator in config/schemas.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.config.store import load_config, save_config
from dtm_buildsheet.config.schemas import REQUIRED_CONFIG_FILES
from dtm_buildsheet.paths import AppPaths, DEFAULT_CONFIG_DIR


def _seeded_paths(tmp_path: Path) -> AppPaths:
    """Workspace pointed at *tmp_path*, seeded with the bundled project_options.json."""
    src = DEFAULT_CONFIG_DIR / "project_options.json"
    (tmp_path / "project_options.json").write_bytes(src.read_bytes())
    return AppPaths(workspace_config_dir=tmp_path)


class TestProjectOptionsConfigRegistration:
    def test_in_required_config_files(self):
        assert "project_options.json" in REQUIRED_CONFIG_FILES

    def test_bundled_file_exists(self):
        assert (DEFAULT_CONFIG_DIR / "project_options.json").exists()


class TestLoadProjectOptions:
    def test_loads_through_generic_config(self, tmp_path):
        paths = _seeded_paths(tmp_path)
        options = load_config("project_options.json", paths)
        assert "build_types" in options
        assert isinstance(options["build_types"], list)

    def test_canonical_build_types_present(self, tmp_path):
        paths = _seeded_paths(tmp_path)
        options = load_config("project_options.json", paths)
        for expected in ("Patrol", "Admin", "Unmarked", "K-9", "Fire"):
            assert expected in options["build_types"]


class TestValidator:
    def test_rejects_non_list_field(self, tmp_path):
        bad = {
            "schema_version": 1,
            "build_types": "Patrol",  # must be a list
            "camera_brands": [],
            "lighting_brands": [],
            "bumper_brands": [],
            "cage_brands": [],
        }
        (tmp_path / "project_options.json").write_text(json.dumps(bad), "utf-8")
        paths = AppPaths(workspace_config_dir=tmp_path)
        with pytest.raises(ValueError, match="build_types"):
            load_config("project_options.json", paths)

    def test_fills_missing_lists_with_defaults(self, tmp_path):
        sparse = {"schema_version": 1, "build_types": ["Custom"]}
        paths = AppPaths(workspace_config_dir=tmp_path)
        normalized = save_config("project_options.json", sparse, paths)
        for key in ("camera_brands", "lighting_brands", "bumper_brands", "cage_brands"):
            assert normalized[key] == []
        assert normalized["build_types"] == ["Custom"]


class TestSaveRoundtrip:
    def test_workspace_override_round_trips(self, tmp_path):
        override = {
            "schema_version": 1,
            "build_types": ["Custom"],
            "camera_brands": [],
            "lighting_brands": [],
            "bumper_brands": [],
            "cage_brands": [],
        }
        paths = AppPaths(workspace_config_dir=tmp_path)
        save_config("project_options.json", override, paths)
        loaded = load_config("project_options.json", paths)
        assert loaded["build_types"] == ["Custom"]
