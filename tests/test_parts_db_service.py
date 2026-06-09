"""Phase 3: PartsDbService typed-query coverage.

Drives every public method off a small synthetic parts_db.json so the
assertions stay grounded. The legacy fallback path is exercised separately
in test_parts_db_dual_read.py.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from dtm_buildsheet.app.services import parts_db_service
from dtm_buildsheet.app.services.parts_db_service import (
    PartsDbService,
    get_parts_db_service,
)
from dtm_buildsheet.paths import AppPaths


@pytest.fixture(autouse=True)
def _reset_singleton():
    parts_db_service.reset_for_testing()
    yield
    parts_db_service.reset_for_testing()


_SYNTHETIC_DB = {
    "schema_version": 1,
    "metadata": {"last_updated": "2026-06-09T00:00:00Z", "updated_by": "test"},
    "part_categories": {
        "lights":   {"label": "Lights"},
        "brackets": {"label": "Brackets"},
        "radar":    {"label": "Radar"},
    },
    "location_zones": {
        "primary_front": {"label": "Primary Front"},
        "interior":      {"label": "Interior"},
    },
    "locations": {
        "GRILL":           {"label": "Grill",            "zone": "primary_front"},
        "PUSH_BUMPER_TOP": {"label": "Push Bumper Top",  "zone": "primary_front"},
        "DASH":            {"label": "Dash",             "zone": "interior"},
    },
    "build_sections": {
        "front":          {"label": "Front",          "order": 1},
        "equipment_tray": {"label": "Equipment Tray", "order": 6},
    },
    "manufacturers": {
        "whelen":  {"label": "Whelen"},
        "stalker": {"label": "Stalker Radar"},
    },
    "color_palette": {
        "red":   {"label": "Red",   "hex": "#E10600", "naming_token": "R"},
        "blue":  {"label": "Blue",  "hex": "#003DA5", "naming_token": "B"},
        "white": {"label": "White", "hex": "#FFFFFF", "naming_token": "W"},
        "amber": {"label": "Amber", "hex": "#FFA500", "naming_token": "A"},
    },
    "parts": {
        "whelen_ion_t": {
            "friendly_name": "Whelen ION T-Series",
            "legacy_workbook_name": "ION T",
            "aliases": ["ION", "Whelen ION T"],
            "category": "lights",
            "build_section": "front",
            "manufacturer_id": "whelen",
            "models": [
                {
                    "model_id": "wh_ion_t_single",
                    "model_number": "ION-T-1",
                    "supported_colors": ["red", "blue", "white", "amber"],
                },
                {
                    "model_id": "wh_ion_t_tri",
                    "model_number": "ION-T-T-T",
                    "supported_colors": ["red", "blue", "white"],
                },
            ],
            "compatible_vehicles": ["TAHOE", "PIU"],
            "compatible_locations_by_vehicle": {
                "TAHOE": ["GRILL", "PUSH_BUMPER_TOP"],
                "PIU":   ["GRILL"],
            },
            "bracket_required": True,
            "compatible_bracket_part_ids": ["whelen_bracket_universal"],
        },
        "whelen_bracket_universal": {
            "friendly_name": "Whelen Universal Bracket",
            "category": "brackets",
            "manufacturer_id": "whelen",
            "models": [{"model_id": "brk_univ", "model_number": "BRK-UNIV"}],
            "compatible_locations": ["GRILL", "PUSH_BUMPER_TOP"],
        },
        "stalker_dsr_radar": {
            "friendly_name": "Stalker DSR 2X",
            "category": "radar",
            "manufacturer_id": "stalker",
            "models": [{"model_id": "dsr_2x", "model_number": "DSR-2X"}],
            "compatible_vehicles": ["TAHOE"],
            "compatible_locations_by_vehicle": {"TAHOE": ["DASH"]},
            "serialized": True,
        },
    },
    "naming_rules": {},
}


def _paths_with_db(tmp_path: Path, db: dict | None = _SYNTHETIC_DB) -> AppPaths:
    if db is not None:
        (tmp_path / "parts_db.json").write_text(json.dumps(db), "utf-8")
    return AppPaths(workspace_config_dir=tmp_path)


# ── Primary typed queries ────────────────────────────────────────────────────


class TestListByCategory:
    def test_returns_parts_in_category(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        lights = svc.list_parts_by_category("lights")
        assert len(lights) == 1
        assert lights[0].part_id == "whelen_ion_t"

    def test_unknown_category_returns_empty(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.list_parts_by_category("nonexistent") == []


class TestManufacturersForPart:
    def test_returns_part_manufacturer(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        mfgs = svc.list_manufacturers_for_part("whelen_ion_t")
        assert len(mfgs) == 1
        assert mfgs[0].manufacturer_id == "whelen"
        assert mfgs[0].label == "Whelen"

    def test_unknown_part_returns_empty(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.list_manufacturers_for_part("nope") == []


class TestModelsForPart:
    def test_returns_all_models(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        models = svc.list_models_for_part("whelen_ion_t")
        assert [m.model_id for m in models] == ["wh_ion_t_single", "wh_ion_t_tri"]

    def test_unknown_part_returns_empty(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.list_models_for_part("nope") == []


class TestCompatibleLocations:
    def test_filters_by_vehicle(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        locs = svc.list_compatible_locations("whelen_ion_t", "PIU")
        assert [loc.location_id for loc in locs] == ["GRILL"]
        assert locs[0].zone == "primary_front"

    def test_unknown_vehicle_returns_empty(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.list_compatible_locations("whelen_ion_t", "F150") == []


class TestCompatibleColors:
    def test_returns_union_across_models(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        colors = svc.list_compatible_colors("whelen_ion_t")
        color_ids = {c.color_id for c in colors}
        assert color_ids == {"red", "blue", "white", "amber"}

    def test_part_without_models_returns_empty(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        # bracket has models but no supported_colors → empty
        assert svc.list_compatible_colors("whelen_bracket_universal") == []


class TestBracketRequirement:
    def test_returns_requirement_when_required(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        req = svc.bracket_requirement("whelen_ion_t")
        assert req is not None
        assert req.required is True
        assert req.compatible_bracket_part_ids == ["whelen_bracket_universal"]

    def test_returns_none_when_not_required(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.bracket_requirement("stalker_dsr_radar") is None

    def test_unknown_part_returns_none(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.bracket_requirement("nope") is None


class TestCompatibleBrackets:
    def test_returns_listed_brackets(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        brackets = svc.list_compatible_brackets("whelen_ion_t")
        assert [b.part_id for b in brackets] == ["whelen_bracket_universal"]

    def test_filters_by_location_when_provided(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        # bracket allows GRILL + PUSH_BUMPER_TOP; DASH should filter it out
        assert svc.list_compatible_brackets("whelen_ion_t", location="DASH") == []
        assert len(svc.list_compatible_brackets("whelen_ion_t", location="GRILL")) == 1


# ── Compat-shim queries (name-keyed; tested without legacy data here) ────────


class TestLookupByName:
    def test_matches_friendly_name(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.lookup_part_by_name("Whelen ION T-Series").part_id == "whelen_ion_t"

    def test_matches_legacy_workbook_name(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.lookup_part_by_name("ION T").part_id == "whelen_ion_t"

    def test_matches_alias_case_insensitively(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.lookup_part_by_name("ion").part_id == "whelen_ion_t"

    def test_unknown_returns_none(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.lookup_part_by_name("Nothing") is None
        assert svc.lookup_part_by_name("") is None


class TestLegacyNameShims:
    def test_manufacturers_resolves_through_db(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        # Match by legacy_workbook_name
        assert svc.manufacturers_by_legacy_name("ION T") == ["Whelen"]

    def test_models_resolves_through_db(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.models_by_legacy_name("ION T") == ["ION-T-1", "ION-T-T-T"]

    def test_locations_resolves_through_db(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        locs = svc.locations_by_legacy_name("ION T")
        # Union across TAHOE + PIU, deduped, order-preserving
        assert locs == ["GRILL", "PUSH_BUMPER_TOP"]


# ── Lifecycle ────────────────────────────────────────────────────────────────


class TestCaching:
    def test_singleton_per_paths(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        assert get_parts_db_service(paths) is get_parts_db_service(paths)

    def test_invalidate_drops_cache(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        svc.raw_doc()  # warm
        assert svc._cache is not None
        svc.invalidate()
        assert svc._cache is None


class TestMissingFile:
    def test_empty_doc_when_parts_db_missing(self, tmp_path):
        # No parts_db.json written
        svc = PartsDbService(AppPaths(workspace_config_dir=tmp_path))
        doc = svc.raw_doc()
        assert doc["parts"] == {}
        # Typed queries also return empty
        assert svc.list_parts_by_category("lights") == []
        assert svc.lookup_part_by_name("ION T") is None


# ── Performance guardrail (§5.4 of the plan) ─────────────────────────────────


class TestLookupPerf:
    def test_thousand_lookups_under_100ms(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        svc.raw_doc()  # warm cache
        start = time.perf_counter()
        for _ in range(1000):
            svc.lookup_part_by_name("ION T")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 100, f"1000 lookups took {elapsed_ms:.0f}ms"
