"""Tests for the per-record agency storage layout introduced in Phase 1.

Storage:  workspace/agencies/{agency_id}.json (one file per agency)
Legacy:   workspace/agencies.json (monolithic) — read-only fallback that triggers
          a one-shot migration into the per-record dir.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.services import agency_service
from dtm_buildsheet.app.services.agency_service import (
    handle_delete_agency,
    handle_list_agency_choices,
    handle_list_agencies,
    handle_save_agency,
    handle_save_agency_default_preferences,
    handle_search_agencies,
    load_agency_choices,
    load_agencies,
)
from dtm_buildsheet.paths import AppPaths


@pytest.fixture(autouse=True)
def _clear_cache():
    """Every test gets a fresh cache."""
    agency_service._cache.clear()
    yield
    agency_service._cache.clear()


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(workspace_dir=tmp_path)


def _agencies_dir(tmp_path: Path) -> Path:
    return tmp_path / "agencies"


# ── Per-record storage ─────────────────────────────────────────────────────────


class TestPerRecordStorage:
    def test_save_writes_one_file_per_agency(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_agency({"name": "Alpha PD"}, paths)
        handle_save_agency({"name": "Beta SO"}, paths)
        files = list(_agencies_dir(tmp_path).glob("*.json"))
        assert len(files) == 2
        # No monolithic file is written
        assert not (tmp_path / "agencies.json").exists()

    def test_save_then_load_roundtrip(self, tmp_path):
        paths = _paths(tmp_path)
        res = handle_save_agency(
            {"name": "Alpha PD", "contact_email": "chief@alpha.gov"}, paths
        )
        agency_id = res["agency"]["agency_id"]
        # Force a fresh cache load
        agency_service._cache.clear()
        records = load_agencies(paths)
        assert len(records) == 1
        assert records[0].agency_id == agency_id
        assert records[0].contact_email == "chief@alpha.gov"

    def test_default_preferences_round_trip(self, tmp_path):
        paths = _paths(tmp_path)
        saved = handle_save_agency({
            "name": "Alpha PD",
            "default_preferences": {
                "lighting_brands": ["Whelen"],
                "lighting_mode": "trio",
                "camera_brand": "Axon",
                "push_bumper_brand": "Setina",
            },
        }, paths)
        agency_service._cache.clear()
        agency = load_agencies(paths)[0]
        assert agency.agency_id == saved["agency"]["agency_id"]
        assert agency.default_preferences.lighting_brands == ["Whelen"]
        assert agency.default_preferences.lighting_mode == "trio"
        assert agency.default_preferences.camera_brand == "Axon"
        assert agency.default_preferences.push_bumper_brand == "Setina"

    def test_customer_pricing_overrides_round_trip(self, tmp_path):
        paths = _paths(tmp_path)
        saved = handle_save_agency({
            "name": "Alpha PD",
            "pricing_overrides": {"whelen": 35, "havis": 12.5},
        }, paths)
        assert saved["ok"] is True
        agency_service._cache.clear()
        agency = load_agencies(paths)[0]
        assert agency.pricing_overrides == {"whelen": 35.0, "havis": 12.5}

    def test_customer_pricing_override_rejects_out_of_range_discount(self, tmp_path):
        result = handle_save_agency({
            "name": "Alpha PD",
            "pricing_overrides": {"whelen": 101},
        }, _paths(tmp_path))
        assert result["ok"] is False
        assert "0 through 100" in result["error"]

    def test_project_choices_can_update_only_agency_default_preferences(self, tmp_path, monkeypatch):
        paths = _paths(tmp_path)
        saved = handle_save_agency({
            "name": "Alpha PD",
            "contact_email": "chief@alpha.gov",
            "default_preferences": {"lighting_brands": ["Whelen"]},
        }, paths)

        monkeypatch.setattr(
            agency_service,
            "save_via_proposal",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("proposal path must not run")),
        )
        result = handle_save_agency_default_preferences({
            "agency_id": saved["agency"]["agency_id"],
            "default_preferences": {
                "lighting_brands": ["Code 3"],
                "lighting_mode": "trio",
                "camera_brand": "Axon",
                "console_brand": "Havis",
            },
        }, paths)

        assert result["ok"] is True
        agency = load_agencies(paths)[0]
        assert agency.contact_email == "chief@alpha.gov"
        assert agency.default_preferences.lighting_brands == ["Code 3"]
        assert agency.default_preferences.lighting_mode == "trio"
        assert agency.default_preferences.camera_brand == "Axon"
        assert agency.default_preferences.console_brand == "Havis"

    def test_delete_removes_file_and_cache_entry(self, tmp_path):
        paths = _paths(tmp_path)
        res = handle_save_agency({"name": "Alpha PD"}, paths)
        agency_id = res["agency"]["agency_id"]
        assert (tmp_path / "agencies" / f"{agency_id}.json").exists()
        del_res = handle_delete_agency(agency_id, paths)
        assert del_res["ok"] is True
        assert not (tmp_path / "agencies" / f"{agency_id}.json").exists()
        assert load_agencies(paths) == []

    def test_delete_unknown_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        res = handle_delete_agency("does-not-exist", paths)
        assert res["ok"] is False

    def test_unsafe_agency_id_rejected_on_save(self, tmp_path):
        paths = _paths(tmp_path)
        res = handle_save_agency({"agency_id": "../etc/passwd", "name": "Evil"}, paths)
        assert res["ok"] is False
        assert "agency_id" in res["error"].lower() or "separator" in res["error"].lower()


# ── Legacy fallback + one-shot migration ───────────────────────────────────────


class TestLegacyFallback:
    def _seed_legacy(self, tmp_path: Path, names: list[str]) -> None:
        data = {
            "schema_version": 1,
            "agencies": [
                {
                    "agency_id": f"id-{i}",
                    "name": n,
                    "contact_name": "",
                    "contact_phone": "",
                    "contact_email": "",
                    "customer_since": "",
                    "created_at": "t",
                    "updated_at": "t",
                }
                for i, n in enumerate(names)
            ],
        }
        (tmp_path / "agencies.json").write_text(json.dumps(data), "utf-8")

    def test_legacy_file_loads_when_per_record_dir_missing(self, tmp_path):
        self._seed_legacy(tmp_path, ["Alpha PD", "Beta SO"])
        names = sorted(r.name for r in load_agencies(_paths(tmp_path)))
        assert names == ["Alpha PD", "Beta SO"]

    def test_legacy_read_triggers_one_shot_migration(self, tmp_path):
        self._seed_legacy(tmp_path, ["Alpha PD", "Beta SO"])
        load_agencies(_paths(tmp_path))
        per_record = list(_agencies_dir(tmp_path).glob("*.json"))
        assert len(per_record) == 2
        # Legacy file is left as backup, not deleted
        assert (tmp_path / "agencies.json").exists()

    def test_per_record_dir_wins_over_legacy(self, tmp_path):
        # Seed legacy with one set; per-record with a different set.
        self._seed_legacy(tmp_path, ["Legacy Only"])
        (tmp_path / "agencies").mkdir()
        (tmp_path / "agencies" / "id-modern.json").write_text(json.dumps({
            "agency_id": "id-modern",
            "name": "Modern Only",
            "created_at": "t",
            "updated_at": "t",
        }), "utf-8")
        records = load_agencies(_paths(tmp_path))
        assert [r.name for r in records] == ["Modern Only"]

    def test_save_after_legacy_load_preserves_other_records(self, tmp_path):
        """Regression: pre-Phase-1 a save in legacy mode would overwrite the
        monolithic file; in the new layout we must not lose siblings."""
        self._seed_legacy(tmp_path, ["Alpha PD", "Beta SO"])
        paths = _paths(tmp_path)
        # Save a new one. Migration runs first, so all three end up on disk.
        handle_save_agency({"name": "Gamma PD"}, paths)
        agency_service._cache.clear()
        names = sorted(r.name for r in load_agencies(paths))
        assert names == ["Alpha PD", "Beta SO", "Gamma PD"]


# ── Cache behavior ─────────────────────────────────────────────────────────────


class TestCache:
    def test_cache_is_lazy(self, tmp_path):
        # Cache shouldn't be populated until first read
        assert str(_agencies_dir(tmp_path)) not in agency_service._cache
        load_agencies(_paths(tmp_path))
        assert str(_agencies_dir(tmp_path)) in agency_service._cache

    def test_save_updates_cache_in_place(self, tmp_path):
        paths = _paths(tmp_path)
        res = handle_save_agency({"name": "Alpha PD"}, paths)
        agency_id = res["agency"]["agency_id"]
        # Modify via save again; do NOT clear cache. The cached list should reflect it.
        handle_save_agency(
            {"agency_id": agency_id, "name": "Alpha PD", "contact_phone": "555-0100"},
            paths,
        )
        # No re-read from disk
        records = load_agencies(paths)
        assert records[0].contact_phone == "555-0100"


# ── Search ─────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_substring_match(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_agency({"name": "St. Cloud Police Department"}, paths)
        handle_save_agency({"name": "Stearns County Sheriff"}, paths)
        res = handle_search_agencies("cloud", paths)
        names = [m["name"] for m in res["matches"]]
        assert "St. Cloud Police Department" in names
        assert "Stearns County Sheriff" not in names

    def test_abbreviation_normalization(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_agency({"name": "St. Cloud PD"}, paths)
        res = handle_search_agencies("saint cloud police department", paths)
        assert res["matches"]
        assert res["matches"][0]["name"] == "St. Cloud PD"

    def test_empty_query_returns_no_matches(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_agency({"name": "Alpha PD"}, paths)
        res = handle_search_agencies("", paths)
        assert res["matches"] == []


# ── Response shape ─────────────────────────────────────────────────────────────


class TestHandleListAgencies:
    def test_response_shape(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_agency({"name": "Alpha PD"}, paths)
        res = handle_list_agencies(paths)
        assert res["ok"] is True
        assert "agencies" in res
        assert res["agencies"][0]["name"] == "Alpha PD"


class TestAgencyChoices:
    def test_includes_project_identity_missing_from_agency_records(self, tmp_path):
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "project-1"
        project_dir.mkdir(parents=True)
        (project_dir / "project.json").write_text(json.dumps({
            "project_id": "project-1",
            "customer": {
                "agency_id": "project-agency-id",
                "agency": "Project-Only Agency",
            },
        }), "utf-8")
        paths = AppPaths(workspace_dir=tmp_path, workspace_projects_dir=projects_dir)
        handle_save_agency({"agency_id": "saved-id", "name": "Saved Agency"}, paths)

        choices = load_agency_choices(paths)
        assert [(choice["agency_id"], choice["name"], choice["choice_source"]) for choice in choices] == [
            ("project-agency-id", "Project-Only Agency", "project"),
            ("saved-id", "Saved Agency", "agency"),
        ]
        response = handle_list_agency_choices(paths)
        assert response["ok"] is True
        assert response["total"] == 2

    def test_persisted_agency_wins_over_project_copy(self, tmp_path):
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "project-1"
        project_dir.mkdir(parents=True)
        (project_dir / "project.json").write_text(json.dumps({
            "customer": {"agency_id": "same-id", "agency": "Old Project Name"},
        }), "utf-8")
        paths = AppPaths(workspace_dir=tmp_path, workspace_projects_dir=projects_dir)
        handle_save_agency({"agency_id": "same-id", "name": "Current Agency Name"}, paths)

        choices = load_agency_choices(paths)
        assert choices == [{
            "agency_id": "same-id",
            "name": "Current Agency Name",
            "choice_source": "agency",
        }]
