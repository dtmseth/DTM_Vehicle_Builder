"""Phase 3 (schema v2): three-tier dual-read fallback for legacy lookups.

Tier 1: parts_db.json (via legacy_workbook_index for name→product mapping)
Tier 2: legacy_workbook_index.json (transition map)
Tier 3: workbook_rules.json (last resort)
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


def _seed_workbook_only(tmp_path: Path) -> AppPaths:
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


def _seed_all_three_tiers(tmp_path: Path) -> AppPaths:
    _write(tmp_path / "workbook_rules.json", {
        "schema_version": 1,
        "template_sections": [],
        "part_rules": {
            "Forward Warning 1": {
                "manufacturer": ["STALE"],
                "models": ["STALE"],
                "locations": ["STALE"],
            },
        },
    })
    _write(tmp_path / "legacy_workbook_index.json", {
        "schema_version": 1,
        "part_type_to_products": {"Forward Warning 1": ["whelen_ion"]},
        "model_string_to_product": {"ION": "whelen_ion"},
    })
    _write(tmp_path / "parts_db.json", {
        "schema_version": 2,
        "manufacturers": {"whelen": {"label": "Whelen"}},
        "products": {
            "whelen_ion": {
                "manufacturer_id": "whelen",
                "model": "ION T",
                "fits_part_types": ["forward_warning"],
            },
        },
    })
    return AppPaths(workspace_config_dir=tmp_path)


# ── Tier-3 fallback only ─────────────────────────────────────────────────────


class TestTier3:
    def test_manufacturers_from_workbook(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.manufacturers_by_legacy_name("Forward Warning 1") == [
            "Whelen", "Federal Signal"
        ]

    def test_models_from_workbook(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.models_by_legacy_name("Forward Warning 1") == ["ION", "T-ION", "2 LAMP TRACER"]

    def test_locations_from_workbook(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.locations_by_legacy_name("Forward Warning 1") == ["GRILL", "PUSH_BUMPER_TOP"]

    def test_no_legacy_index_no_resolution(self, tmp_path):
        svc = PartsDbService(_seed_workbook_only(tmp_path))
        assert svc.product_for_legacy_model_string("ION") is None
        assert svc.products_for_legacy_part_type_label("Forward Warning 1") == []


# ── Tier-1 wins ──────────────────────────────────────────────────────────────


class TestTier1Wins:
    def test_manufacturers_from_parts_db(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        assert svc.manufacturers_by_legacy_name("Forward Warning 1") == ["Whelen"]

    def test_models_from_parts_db(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        assert svc.models_by_legacy_name("Forward Warning 1") == ["ION T"]

    def test_product_lookup_via_index(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        p = svc.product_for_legacy_model_string("ION")
        assert p is not None and p.product_id == "whelen_ion"

    def test_products_for_legacy_part_type_label(self, tmp_path):
        svc = PartsDbService(_seed_all_three_tiers(tmp_path))
        products = svc.products_for_legacy_part_type_label("Forward Warning 1")
        assert [p.product_id for p in products] == ["whelen_ion"]
