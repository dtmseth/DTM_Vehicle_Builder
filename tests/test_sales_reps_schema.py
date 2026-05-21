"""Tests for sales rep schema + Phase 1 per-record storage layout.

Canonical key is `sales_reps`, never `reps` (legacy field name).

Storage:  workspace/sales_reps/{rep_id}.json (one file per rep)
Legacy:   workspace/sales_reps.json (monolithic) — read-only fallback that
          triggers a one-shot migration into the per-record dir.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.services import sales_rep_service
from dtm_buildsheet.app.services.sales_rep_service import (
    handle_delete_rep,
    handle_list_reps,
    handle_save_rep,
    handle_search_reps,
    load_reps,
)
from dtm_buildsheet.paths import AppPaths


@pytest.fixture(autouse=True)
def _clear_cache():
    sales_rep_service._cache.clear()
    yield
    sales_rep_service._cache.clear()


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(workspace_dir=tmp_path)


def _reps_dir(tmp_path: Path) -> Path:
    return tmp_path / "sales_reps"


# ── Per-record storage ─────────────────────────────────────────────────────────


class TestPerRecordStorage:
    def test_save_writes_one_file_per_rep(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_rep({"name": "Alice", "phone": "111", "email": "a@x.com"}, paths)
        handle_save_rep({"name": "Bob", "phone": "222", "email": "b@x.com"}, paths)
        files = list(_reps_dir(tmp_path).glob("*.json"))
        assert len(files) == 2
        # No monolithic file is written
        assert not (tmp_path / "sales_reps.json").exists()

    def test_save_then_load_roundtrip(self, tmp_path):
        paths = _paths(tmp_path)
        res = handle_save_rep({"name": "Carol", "phone": "333", "email": "c@x.com"}, paths)
        rep_id = res["rep"]["rep_id"]
        sales_rep_service._cache.clear()
        reps = load_reps(paths)
        assert len(reps) == 1
        assert reps[0].rep_id == rep_id
        assert reps[0].name == "Carol"

    def test_delete_removes_file(self, tmp_path):
        paths = _paths(tmp_path)
        res = handle_save_rep({"name": "Dave", "phone": "444", "email": "d@x.com"}, paths)
        rep_id = res["rep"]["rep_id"]
        del_res = handle_delete_rep(rep_id, paths)
        assert del_res["ok"] is True
        assert not (_reps_dir(tmp_path) / f"{rep_id}.json").exists()
        assert load_reps(paths) == []


# ── Validation ─────────────────────────────────────────────────────────────────


class TestValidation:
    def test_missing_name_rejected(self, tmp_path):
        res = handle_save_rep({"phone": "1", "email": "e@x.com"}, _paths(tmp_path))
        assert res["ok"] is False and "name" in res["error"].lower()

    def test_missing_phone_rejected(self, tmp_path):
        res = handle_save_rep({"name": "X", "email": "e@x.com"}, _paths(tmp_path))
        assert res["ok"] is False and "phone" in res["error"].lower()

    def test_missing_email_rejected(self, tmp_path):
        res = handle_save_rep({"name": "X", "phone": "1"}, _paths(tmp_path))
        assert res["ok"] is False and "email" in res["error"].lower()


# ── Legacy fallback + migration ────────────────────────────────────────────────


class TestLegacyFallback:
    def _seed_legacy(self, tmp_path: Path, names: list[str]) -> None:
        data = {
            "schema_version": 1,
            "sales_reps": [
                {
                    "rep_id": f"r{i}",
                    "name": n,
                    "phone": "555",
                    "email": f"{n.lower()}@x.com",
                    "created_at": "t",
                    "updated_at": "t",
                }
                for i, n in enumerate(names)
            ],
        }
        (tmp_path / "sales_reps.json").write_text(json.dumps(data), "utf-8")

    def test_reads_sales_reps_key(self, tmp_path):
        self._seed_legacy(tmp_path, ["Alice"])
        reps = load_reps(_paths(tmp_path))
        assert len(reps) == 1
        assert reps[0].name == "Alice"

    def test_does_not_read_legacy_reps_key(self, tmp_path):
        # The legacy 'reps' key (renamed to 'sales_reps' earlier) is not supported.
        data = {"schema_version": 1, "reps": [{"rep_id": "r1", "name": "Bob"}]}
        (tmp_path / "sales_reps.json").write_text(json.dumps(data), "utf-8")
        assert load_reps(_paths(tmp_path)) == []

    def test_legacy_read_triggers_migration(self, tmp_path):
        self._seed_legacy(tmp_path, ["Alice", "Bob"])
        load_reps(_paths(tmp_path))
        per_record = list(_reps_dir(tmp_path).glob("*.json"))
        assert len(per_record) == 2
        assert (tmp_path / "sales_reps.json").exists()  # left as backup

    def test_per_record_dir_wins_over_legacy(self, tmp_path):
        self._seed_legacy(tmp_path, ["Legacy"])
        _reps_dir(tmp_path).mkdir()
        (_reps_dir(tmp_path) / "rmodern.json").write_text(json.dumps({
            "rep_id": "rmodern",
            "name": "Modern",
            "phone": "1",
            "email": "m@x.com",
            "created_at": "t",
            "updated_at": "t",
        }), "utf-8")
        names = [r.name for r in load_reps(_paths(tmp_path))]
        assert names == ["Modern"]

    def test_save_after_legacy_load_preserves_siblings(self, tmp_path):
        self._seed_legacy(tmp_path, ["Alice", "Bob"])
        paths = _paths(tmp_path)
        handle_save_rep({"name": "Carol", "phone": "1", "email": "c@x.com"}, paths)
        sales_rep_service._cache.clear()
        names = sorted(r.name for r in load_reps(paths))
        assert names == ["Alice", "Bob", "Carol"]


# ── Cache ──────────────────────────────────────────────────────────────────────


class TestCache:
    def test_cache_is_lazy(self, tmp_path):
        assert str(_reps_dir(tmp_path)) not in sales_rep_service._cache
        load_reps(_paths(tmp_path))
        assert str(_reps_dir(tmp_path)) in sales_rep_service._cache

    def test_save_updates_cache_in_place(self, tmp_path):
        paths = _paths(tmp_path)
        res = handle_save_rep({"name": "Eve", "phone": "5", "email": "e@x.com"}, paths)
        rep_id = res["rep"]["rep_id"]
        handle_save_rep(
            {"rep_id": rep_id, "name": "Eve", "phone": "9", "email": "e@x.com"},
            paths,
        )
        reps = load_reps(paths)
        assert reps[0].phone == "9"


# ── Response shape ─────────────────────────────────────────────────────────────


class TestHandleListReps:
    def test_response_uses_sales_reps_key(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_rep({"name": "Eve", "phone": "555", "email": "e@x.com"}, paths)
        result = handle_list_reps(paths)
        assert result["ok"] is True
        assert "sales_reps" in result
        assert "reps" not in result
        assert result["sales_reps"][0]["name"] == "Eve"


# ── Search ─────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_substring(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_rep({"name": "Alice Anderson", "phone": "1", "email": "a@x.com"}, paths)
        handle_save_rep({"name": "Bob Brown", "phone": "2", "email": "b@x.com"}, paths)
        res = handle_search_reps("alice", paths)
        names = [m["name"] for m in res["matches"]]
        assert "Alice Anderson" in names
        assert "Bob Brown" not in names
