"""Phase 3 (revised): three-tier dual-read fallback.

Tier 1: parts_db.json (via legacy_workbook_index for name-keyed queries)
Tier 2: legacy_workbook_index.json (transition map)
Tier 3: workbook_rules.json (last resort)

Tests pin the cascade: each query returns from the highest tier that has
data; missing tiers fall through to the next.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.services import parts_db_service
from dtm_buildsheet.app.services.parts_db_service import PartsDbService
from dtm_buildsheet.paths import AppPaths


@pytest.fixture(autouse=True)
def _reset_singleton():
    parts_db_service.reset_for_testing()
    yield
    parts_db_service.reset_for_testing()


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), "utf-8")


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _seed_workbook_only(tmp_path: Path) -> AppPaths:
    """workbook_rules.json only — both parts_db.json and legacy_workbook_index
    missing. Tier-3 fallback should engage."""
    _write(tmp_path / "workbook_rules.json", {
        "schema_version": 1,
        "template_sections": [],
        "part_rules": {
            "Forward Warning 1": {
                "manufacturer": ["Whelen", "Federal Signal"],
                "models": ["ION", "T-ION", "2 LAMP TRACER"],
                "locations": ["GRILL", "PUSH_BUMPER_TOP"],
            },
        },
    })
    return AppPaths(workspace_config_dir=tmp_path)


def _seed_workbook_plus_legacy_index(tmp_path: Path) -> AppPaths:
    """Both workbook_rules and legacy_workbook_index present, but parts_db
    has no matching products. The legacy_index points at products that
    aren't there, so the shim should fall through to workbook_rules."""
    _write(tmp_path / "workbook_rules.json", {
        "schema_version": 1,
        "template_sections": [],
        "part_rules": {
            "Forward Warning 1": {
                "manufacturer": ["Whelen"],
                "models": ["ION"],
                "locations": ["GRILL"],
            },
        },
    })
    _write(tmp_path / "legacy_workbook_index.json", {
        "schema_version": 1,
        "part_type_to_products": {
            "Forward Warning 1": ["whelen_ion_t"],
        },
        "model_string_to_product": {
            "ION": "whelen_ion_t",
        },
    })
    # parts_db.json missing → tier-1 misses, tier-2 returns product_ids that
    # don't resolve, shim falls through to tier-3.
    return AppPaths(workspace_config_dir=tmp_path)


def _seed_all_three_tiers(tmp_path: Path) -> AppPaths:
    """Full dataset: parts_db has the product, legacy_index points at it,
    workbook_rules has stale fallback data. Tier-1 wins."""
    _write(tmp_path / "workbook_rules.json", {
        "schema_version": 1,
        "template_sections": [],
        "part_rules": {
            "Forward Warning 1": {
                "manufacturer": ["STALE_MFG"],
                "models": ["STALE_MODEL"],
                "locations": ["STALE_LOC"],
            },
        },
    })
    _write(tmp_path / "legacy_workbook_index.json", {
        "schema_version": 1,
        "part_type_to_products": {
            "Forward Warning 1": ["whelen_ion_t"],
        },
        "model_string_to_product": {
            "ION": "whelen_ion_t",
        },
    })
    _write(tmp_path / "parts_db.json", {
        "schema_version": 1,
        "categories": {"lights": {"label": "Lights", "applies_to_zones": ["primary_front"]}},
        "manufacturers": {"whelen": {"label": "Whelen"}},
        "products": {
            "whelen_ion_t": {
                "manufacturer_id": "whelen",
                "category_id": "lights",
                "model": "ION T-Series",
            },
        },
        "location_zone_map": {"GRILL": "primary_front", "PUSH_BUMPER_TOP": "primary_front"},
    })
    return AppPaths(workspace_config_dir=tmp_path)


# ── Tier 3: workbook_rules only ───────────────────────────────────────────────


class TestTier3FallbackOnly:
    def test_manufacturers_from_workbook(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.manufacturers_by_legacy_name("Forward Warning 1") == ["Whelen", "Federal Signal"]

    def test_models_from_workbook(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.models_by_legacy_name("Forward Warning 1") == ["ION", "T-ION", "2 LAMP TRACER"]

    def test_locations_from_workbook(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.locations_by_legacy_name("Forward Warning 1") == ["GRILL", "PUSH_BUMPER_TOP"]

    def test_unknown_label_returns_empty(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.manufacturers_by_legacy_name("Phantom Light") == []


# ── Tier 2 misses → Tier 3 takes over ────────────────────────────────────────


class TestTier2MissResolvesToTier3:
    def test_index_points_at_missing_product_falls_through(self, tmp_path):
        svc = PartsDbService(_seed_workbook_plus_legacy_index(tmp_path))
        # legacy_workbook_index says "Forward Warning 1" → whelen_ion_t,
        # but no parts_db.json exists. Shim returns nothing from tier-1+2
        # and falls back to workbook_rules.
        assert svc.manufacturers_by_legacy_name("Forward Warning 1") == ["Whelen"]


# ── Tier 1 wins ──────────────────────────────────────────────────────────────


class TestTier1Wins:
    def test_manufacturers_from_parts_db(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        # parts_db has whelen → "Whelen" label. workbook_rules stale string ignored.
        assert svc.manufacturers_by_legacy_name("Forward Warning 1") == ["Whelen"]

    def test_models_from_parts_db(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        assert svc.models_by_legacy_name("Forward Warning 1") == ["ION T-Series"]

    def test_locations_via_category_applies_to_zones(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        # parts_db has lights → applies_to_zones=[primary_front]; location_zone_map
        # GRILL/PUSH_BUMPER_TOP → primary_front. Both should come through.
        locs = svc.locations_by_legacy_name("Forward Warning 1")
        assert set(locs) == {"GRILL", "PUSH_BUMPER_TOP"}


# ── Product-string lookups ───────────────────────────────────────────────────


class TestProductLookups:
    def test_product_for_legacy_model_string(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        p = svc.product_for_legacy_model_string("ION")
        assert p is not None and p.product_id == "whelen_ion_t"

    def test_products_for_legacy_part_type(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        products = svc.products_for_legacy_part_type("Forward Warning 1")
        assert [p.product_id for p in products] == ["whelen_ion_t"]

    def test_no_legacy_index_no_resolution(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.product_for_legacy_model_string("ION") is None
        assert svc.products_for_legacy_part_type("Forward Warning 1") == []
