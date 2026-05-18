"""Tests for the config-driven project options endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.app.services.project_options_service import (
    handle_get_project_options,
    load_project_options,
)
from dtm_buildsheet.paths import AppPaths, DEFAULT_CONFIG_DIR


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(workspace_config_dir=tmp_path)


class TestLoadProjectOptions:
    def test_loads_bundled_defaults(self, tmp_path):
        paths = _paths(tmp_path)
        options = load_project_options(paths)
        assert "build_types" in options
        assert isinstance(options["build_types"], list)

    def test_canonical_build_types_present(self, tmp_path):
        paths = _paths(tmp_path)
        options = load_project_options(paths)
        build_types = options["build_types"]
        for expected in ("Patrol", "Admin", "Unmarked", "K-9", "Fire"):
            assert expected in build_types

    def test_no_extra_build_types(self, tmp_path):
        paths = _paths(tmp_path)
        options = load_project_options(paths)
        assert set(options["build_types"]) == {"Patrol", "Admin", "Unmarked", "K-9", "Fire"}

    def test_workspace_override_takes_precedence(self, tmp_path):
        import json
        override = {
            "schema_version": 1,
            "build_types": ["Custom"],
            "camera_brands": [],
            "lighting_brands": [],
            "bumper_brands": [],
            "cage_brands": [],
        }
        (tmp_path / "project_options.json").write_text(json.dumps(override), "utf-8")
        paths = _paths(tmp_path)
        options = load_project_options(paths)
        assert options["build_types"] == ["Custom"]

    def test_malformed_workspace_override_falls_back_to_bundled(self, tmp_path):
        (tmp_path / "project_options.json").write_text("not json{{{", "utf-8")
        paths = _paths(tmp_path)
        options = load_project_options(paths)
        assert "build_types" in options
        assert "Patrol" in options["build_types"]


class TestHandleGetProjectOptions:
    def test_returns_ok(self, tmp_path):
        result = handle_get_project_options(_paths(tmp_path))
        assert result["ok"] is True
        assert "options" in result

    def test_options_has_build_types(self, tmp_path):
        result = handle_get_project_options(_paths(tmp_path))
        assert "build_types" in result["options"]
