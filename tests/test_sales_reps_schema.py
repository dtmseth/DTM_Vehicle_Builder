"""Tests for sales rep schema (canonical key is 'sales_reps', never 'reps')."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.services.sales_rep_service import (
    handle_list_reps,
    handle_save_rep,
    load_reps,
)
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(workspace_dir=tmp_path)


class TestLoadReps:
    def test_reads_sales_reps_key(self, tmp_path):
        data = {
            "schema_version": 1,
            "sales_reps": [
                {"rep_id": "r1", "name": "Alice", "phone": "111", "email": "a@x.com"},
            ],
        }
        (tmp_path / "sales_reps.json").write_text(json.dumps(data), "utf-8")
        reps = load_reps(_paths(tmp_path))
        assert len(reps) == 1
        assert reps[0].name == "Alice"

    def test_missing_file_returns_empty_list(self, tmp_path):
        assert load_reps(_paths(tmp_path)) == []

    def test_does_not_read_legacy_reps_key(self, tmp_path):
        data = {
            "schema_version": 1,
            "reps": [
                {"rep_id": "r1", "name": "Bob", "phone": "222", "email": "b@x.com"},
            ],
        }
        (tmp_path / "sales_reps.json").write_text(json.dumps(data), "utf-8")
        reps = load_reps(_paths(tmp_path))
        # Old 'reps' key is not supported — should return empty
        assert reps == []


class TestSaveRep:
    def test_saves_with_sales_reps_key(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_rep({"name": "Carol", "phone": "333", "email": "c@x.com"}, paths)
        raw = json.loads((tmp_path / "sales_reps.json").read_text("utf-8"))
        assert "sales_reps" in raw
        assert "reps" not in raw
        assert raw["sales_reps"][0]["name"] == "Carol"

    def test_roundtrip_load_after_save(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_rep({"name": "Dave", "phone": "444", "email": "d@x.com"}, paths)
        reps = load_reps(paths)
        assert len(reps) == 1
        assert reps[0].name == "Dave"


class TestHandleListReps:
    def test_response_uses_sales_reps_key(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_rep({"name": "Eve", "phone": "555", "email": "e@x.com"}, paths)
        result = handle_list_reps(paths)
        assert result["ok"] is True
        assert "sales_reps" in result
        assert "reps" not in result
        assert result["sales_reps"][0]["name"] == "Eve"
