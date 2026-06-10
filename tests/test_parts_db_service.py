"""Phase 3 (revised): PartsDbService typed-query coverage.

The schema redesign on 2026-06-10 moved to a manufacturer-centric hierarchy
(Category → Manufacturer → Product → PartNumber). These tests drive every
public query off a small synthetic parts_db.json that exercises the
relationships described in the quiet-vaulting-quail plan §1.
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
    "categories": {
        "lights":       {"label": "Lights",       "applies_to_zones": ["primary_front", "side", "rear"]},
        "push_bumpers": {"label": "Push Bumpers", "applies_to_zones": ["primary_front"]},
        "brackets":     {"label": "Brackets"},
    },
    "manufacturers": {
        "whelen":   {"label": "Whelen", "website": "https://whelen.com"},
        "setina":   {"label": "Setina"},
        "soundoff": {"label": "SoundOff Signal"},
    },
    "products": {
        "whelen_ion_t": {
            "manufacturer_id": "whelen",
            "category_id": "lights",
            "model": "ION T-Series",
            "option_axes": {
                "colors": {
                    "type": "multi_select_from_palette",
                    "min": 1, "max": 3,
                    "allowed": ["red", "blue", "white", "amber"],
                },
                "lens": {
                    "type": "single_select",
                    "axis_id": "lens",
                    "allowed": ["standard", "smoked"],
                },
            },
            "part_numbers": [
                {"part_number": "ION-T-RW-STD", "friendly_name": "Red/White Standard",
                 "options": {"colors": ["red", "white"], "lens": "standard"}},
                {"part_number": "ION-T-RB-STD"},  # untyped during transition
            ],
        },
        "soundoff_mpower": {
            "manufacturer_id": "soundoff",
            "category_id": "lights",
            "model": "mPOWER",
        },
        "setina_pb400": {
            "manufacturer_id": "setina",
            "category_id": "push_bumpers",
            "model": "PB400",
            "option_axes": {
                "vehicle_fitment": {
                    "type": "single_select",
                    "axis_id": "vehicle_fitment",
                    "allowed": ["TAHOE", "DURANGO", "PIU"],
                },
            },
            "part_numbers": [
                {"part_number": "PB400-TAHOE-2020", "options": {"vehicle_fitment": "TAHOE"}},
                {"part_number": "PB400-DURANGO",     "options": {"vehicle_fitment": "DURANGO"}},
            ],
        },
        "whelen_tion_bracket": {
            "manufacturer_id": "whelen",
            "category_id": "brackets",
            "model": "T-ION Bracket",
            "compatible_with_products": ["whelen_ion_t"],
            "part_numbers": [{"part_number": "BRK-TION-1"}],
        },
    },
    "color_palette": {
        "red":   {"label": "Red",   "hex": "#E10600", "naming_token": "R"},
        "blue":  {"label": "Blue",  "hex": "#003DA5", "naming_token": "B"},
        "white": {"label": "White", "hex": "#FFFFFF", "naming_token": "W"},
        "amber": {"label": "Amber", "hex": "#FFA500", "naming_token": "A"},
    },
    "location_zones": {
        "primary_front": {"label": "Primary Front"},
        "side":          {"label": "Side"},
        "rear":          {"label": "Rear"},
    },
    "location_zone_map": {
        "GRILL":           "primary_front",
        "PUSH_BUMPER_TOP": "primary_front",
        "A_PILLAR_DRIVER": "side",
    },
    "part_types": {},
    "naming_rules": {},
}


def _paths_with_db(tmp_path: Path, db: dict | None = _SYNTHETIC_DB) -> AppPaths:
    if db is not None:
        (tmp_path / "parts_db.json").write_text(json.dumps(db), "utf-8")
    return AppPaths(workspace_config_dir=tmp_path)


# ── Primary typed queries ────────────────────────────────────────────────────


class TestListCategories:
    def test_returns_all(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        cats = svc.list_categories()
        assert {c.category_id for c in cats} == {"lights", "push_bumpers", "brackets"}

    def test_applies_to_zones_carried_through(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        lights = next(c for c in svc.list_categories() if c.category_id == "lights")
        assert "primary_front" in lights.applies_to_zones


class TestManufacturersInCategory:
    def test_returns_only_mfgs_with_products_in_category(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        mfgs = svc.list_manufacturers_in_category("lights")
        assert {m.manufacturer_id for m in mfgs} == {"whelen", "soundoff"}

    def test_unknown_category_returns_empty(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.list_manufacturers_in_category("nope") == []


class TestProducts:
    def test_list_all(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {p.product_id for p in svc.list_products()}
        assert ids == {"whelen_ion_t", "soundoff_mpower", "setina_pb400", "whelen_tion_bracket"}

    def test_filter_by_category(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        light_ids = {p.product_id for p in svc.list_products_by_category("lights")}
        assert light_ids == {"whelen_ion_t", "soundoff_mpower"}

    def test_filter_by_manufacturer(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        whelen_ids = {p.product_id for p in svc.list_products_by_manufacturer("whelen")}
        assert whelen_ids == {"whelen_ion_t", "whelen_tion_bracket"}

    def test_get_single(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        p = svc.get_product("whelen_ion_t")
        assert p is not None
        assert p.model == "ION T-Series"
        assert p.manufacturer_id == "whelen"
        assert len(p.part_numbers) == 2

    def test_get_unknown_returns_none(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.get_product("nope") is None


class TestPartNumbersAndOptionAxes:
    def test_list_part_numbers(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        pns = svc.list_part_numbers("whelen_ion_t")
        assert [pn.part_number for pn in pns] == ["ION-T-RW-STD", "ION-T-RB-STD"]
        # First one is fully typed; second is untyped (raw transition entry)
        assert pns[0].friendly_name == "Red/White Standard"
        assert pns[0].options == {"colors": ["red", "white"], "lens": "standard"}
        assert pns[1].friendly_name == ""
        assert pns[1].options == {}

    def test_list_option_axes(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        axes = svc.list_option_axes("whelen_ion_t")
        assert set(axes.keys()) == {"colors", "lens"}
        assert axes["colors"].type == "multi_select_from_palette"
        assert axes["colors"].max == 3
        assert "smoked" in axes["lens"].allowed


# ── Compatibility queries ────────────────────────────────────────────────────


class TestZoneCompatibility:
    def test_zones_for_category(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        zones = svc.zones_for_category("lights")
        assert zones == ["primary_front", "side", "rear"]

    def test_products_compatible_with_zone(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        front_products = {p.product_id for p in svc.products_compatible_with_zone("primary_front")}
        # Lights AND push_bumpers both apply to primary_front
        assert front_products == {"whelen_ion_t", "soundoff_mpower", "setina_pb400"}

    def test_zone_with_only_lights(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        side_products = {p.product_id for p in svc.products_compatible_with_zone("side")}
        # Push bumpers don't apply to side; brackets have no zones at all
        assert side_products == {"whelen_ion_t", "soundoff_mpower"}


class TestBrackets:
    def test_brackets_for_product(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        brackets = svc.brackets_for_product("whelen_ion_t")
        assert [b.product_id for b in brackets] == ["whelen_tion_bracket"]

    def test_no_brackets_for_unrelated_product(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.brackets_for_product("setina_pb400") == []


class TestColors:
    def test_list_colors(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        colors = svc.list_colors()
        assert {c.color_id for c in colors} == {"red", "blue", "white", "amber"}


# ── Compat shims (three-tier fallback) ───────────────────────────────────────


class TestLegacyCompatShims:
    """parts_db only — no legacy_workbook_index file, no workbook_rules.

    Asserts shims return empty when there's nothing to fall through to.
    The dual-read fallthrough is tested in test_parts_db_dual_read.py.
    """
    def test_empty_when_no_legacy_data(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert svc.products_for_legacy_part_type("Forward Warning 1") == []
        assert svc.product_for_legacy_model_string("ION") is None


# ── Lifecycle ────────────────────────────────────────────────────────────────


class TestCachingAndLifecycle:
    def test_singleton_per_paths(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        assert get_parts_db_service(paths) is get_parts_db_service(paths)

    def test_invalidate_drops_cache(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        svc.raw_doc()
        assert svc._cache is not None
        svc.invalidate()
        assert svc._cache is None


class TestMissingFile:
    def test_empty_doc_when_parts_db_missing(self, tmp_path):
        svc = PartsDbService(AppPaths(workspace_config_dir=tmp_path))
        assert svc.raw_doc()["products"] == {}
        assert svc.list_products() == []
        assert svc.list_categories() == []
        assert svc.get_product("anything") is None


# ── Performance guardrail ────────────────────────────────────────────────────


class TestLookupPerf:
    def test_thousand_product_lookups_under_100ms(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        svc.raw_doc()  # warm
        start = time.perf_counter()
        for _ in range(1000):
            svc.get_product("whelen_ion_t")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 100, f"1000 lookups took {elapsed_ms:.0f}ms"
