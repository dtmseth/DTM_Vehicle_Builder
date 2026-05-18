"""Tests for project export directory computation."""
from __future__ import annotations

import pytest

from dtm_buildsheet.inputs.project_dirs import (
    ensure_project_output_dir,
    project_subdir_name,
    resolve_project_output_dir,
)


class TestProjectSubdirName:
    def test_agency_and_year(self):
        assert project_subdir_name("City PD", "2026") == "City PD - 2026"

    def test_agency_no_year(self):
        assert project_subdir_name("City PD", "") == "City PD"

    def test_empty_agency_uses_fallback(self):
        name = project_subdir_name("", "2026")
        assert "Unknown Agency" in name

    def test_unsafe_chars_stripped(self):
        name = project_subdir_name('PD/Name<bad>', "2026")
        assert "/" not in name
        assert "<" not in name

    def test_long_agency_truncated(self):
        long = "A" * 200
        name = project_subdir_name(long, "2026")
        assert len(name) <= 90  # slug capped at 80 + " - 2026"


class TestResolveProjectOutputDir:
    def test_none_when_root_empty(self):
        assert resolve_project_output_dir("", "City PD", "2026") is None
        assert resolve_project_output_dir("  ", "City PD", "2026") is None

    def test_returns_path_when_root_set(self, tmp_path):
        result = resolve_project_output_dir(str(tmp_path), "City PD", "2026")
        assert result is not None
        assert result == tmp_path / "City PD - 2026"

    def test_no_year_omits_suffix(self, tmp_path):
        result = resolve_project_output_dir(str(tmp_path), "City PD", "")
        assert result == tmp_path / "City PD"


class TestEnsureProjectOutputDir:
    def test_none_when_root_empty(self):
        assert ensure_project_output_dir("", "City PD", "2026") is None

    def test_creates_directory(self, tmp_path):
        result = ensure_project_output_dir(str(tmp_path), "City PD", "2026")
        assert result is not None
        assert result.is_dir()

    def test_idempotent_if_dir_already_exists(self, tmp_path):
        result1 = ensure_project_output_dir(str(tmp_path), "City PD", "2026")
        result2 = ensure_project_output_dir(str(tmp_path), "City PD", "2026")
        assert result1 == result2
        assert result2.is_dir()

    def test_creates_nested_parents(self, tmp_path):
        root = str(tmp_path / "deep" / "root")
        result = ensure_project_output_dir(root, "City PD", "2026")
        assert result is not None
        assert result.is_dir()
