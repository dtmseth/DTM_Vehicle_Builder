"""Phase 3 (schema v2): the standardized intersection-based compatibility rule.

Validates that (part_type, product, placement) triples pass iff every
participating entity's optional whitelist either is empty or contains
the others. Covers all five rejection paths:

  1. part_type.allowed_products excludes the product
  2. part_type.allowed_placements excludes the location
  3. product.fits_part_types excludes the part_type
  4. placement.allowed_products excludes the product
  5. unknown part_type / product (graceful failure)
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


_DB = {
    "schema_version": 2,
    "products": {
        "whelen_vxe":           {"manufacturer_id": "whelen", "model": "VXE",
                                  "fits_part_types": ["forward_warning"]},
        "whelen_vertex":        {"manufacturer_id": "whelen", "model": "Vertex",
                                  "fits_part_types": ["forward_warning"]},
        "factory_spotlight":    {"manufacturer_id": "factory_brand", "model": "Factory",
                                  "fits_part_types": ["spotlight"]},
        "arges_spotlight":      {"manufacturer_id": "arges", "model": "Arges",
                                  "fits_part_types": ["spotlight"]},
        "setina_pb400":         {"manufacturer_id": "setina", "model": "PB400",
                                  "fits_part_types": ["push_bumper"]},
        "off_brand_universal":  {"manufacturer_id": "off_brand", "model": "Universal",
                                  "fits_part_types": []},  # empty fits = no restriction
    },
    "part_types": {
        "forward_warning": {
            "label": "Forward Warning", "type_id": "lights",
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "workbook_label_pattern": "Forward Warning {n}",
        },
        "spotlight": {
            "label": "Spotlight", "type_id": "lights",
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "allowed_products": ["factory_spotlight", "arges_spotlight"],
            "allowed_placements": ["A_PILLAR_DRIVER", "LIGHTBAR_MOUNT"],
            "workbook_label_pattern": "Spotlight",
        },
        "push_bumper": {
            "label": "Push Bumper", "type_id": "structural",
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "workbook_label_pattern": "Push Bumper",
        },
    },
    "placements": {
        "GRILL":                {"placement_zone": "primary_front"},
        "A_PILLAR_DRIVER":      {"placement_zone": "front_corner"},
        "LIGHTBAR_MOUNT":       {"placement_zone": "roof",
                                  "allowed_products": ["arges_spotlight"]},
        "HEADLIGHT_TWIST_LOCK": {"placement_zone": "primary_front",
                                  "allowed_products": ["whelen_vxe", "whelen_vertex"]},
        "FRONT_FENDER":         {"placement_zone": "front_side"},
    },
}


def _paths(tmp_path: Path) -> AppPaths:
    (tmp_path / "parts_db.json").write_text(json.dumps(_DB), "utf-8")
    return AppPaths(workspace_config_dir=tmp_path)


# ── The happy path ──────────────────────────────────────────────────────────


class TestValidTriples:
    def test_unrestricted_path(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # forward_warning has no allowed_products / allowed_placements;
        # whelen_vxe.fits includes forward_warning; placement has no restriction.
        r = svc.validate_placement("forward_warning", "whelen_vxe", "GRILL")
        assert r["valid"] is True

    def test_part_type_allowed_product_passes(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # spotlight allows factory_spotlight and arges_spotlight; A_PILLAR_DRIVER OK
        r = svc.validate_placement("spotlight", "factory_spotlight", "A_PILLAR_DRIVER")
        assert r["valid"] is True

    def test_arges_at_lightbar_mount(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # LIGHTBAR_MOUNT restricts to arges_spotlight; arges_spotlight ∈ list
        r = svc.validate_placement("spotlight", "arges_spotlight", "LIGHTBAR_MOUNT")
        assert r["valid"] is True

    def test_unrestricted_product_passes(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # off_brand_universal.fits_part_types is empty → no restriction from product side
        r = svc.validate_placement("forward_warning", "off_brand_universal", "GRILL")
        assert r["valid"] is True


# ── The five rejection paths ────────────────────────────────────────────────


class TestRejections:
    def test_part_type_allowed_products_excludes(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # spotlight.allowed_products = [factory, arges]; whelen_vxe not in list
        r = svc.validate_placement("spotlight", "whelen_vxe", "A_PILLAR_DRIVER")
        assert r["valid"] is False
        assert "allowed_products" in r["reason"]

    def test_part_type_allowed_placements_excludes(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # spotlight allowed_placements = [A_PILLAR_DRIVER, LIGHTBAR_MOUNT]; GRILL excluded
        r = svc.validate_placement("spotlight", "factory_spotlight", "GRILL")
        assert r["valid"] is False
        assert "allowed_placements" in r["reason"]

    def test_product_fits_part_types_excludes(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # setina_pb400 only fits push_bumper
        r = svc.validate_placement("forward_warning", "setina_pb400", "GRILL")
        assert r["valid"] is False
        assert "fits_part_types" in r["reason"]

    def test_placement_allowed_products_excludes(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # LIGHTBAR_MOUNT only accepts arges_spotlight
        r = svc.validate_placement("spotlight", "factory_spotlight", "LIGHTBAR_MOUNT")
        assert r["valid"] is False
        assert "not allowed at placement" in r["reason"]

    def test_unknown_part_type(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        r = svc.validate_placement("nope", "whelen_vxe", "GRILL")
        assert r["valid"] is False
        assert "Unknown part_type" in r["reason"]

    def test_unknown_product(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        r = svc.validate_placement("forward_warning", "nope", "GRILL")
        assert r["valid"] is False
        assert "Unknown product" in r["reason"]


# ── Twist-lock case (placement-side whitelist) ──────────────────────────────


class TestTwistLockCase:
    """HEADLIGHT_TWIST_LOCK only accepts whelen_vxe / whelen_vertex.

    Tests both directions: those two pass; everything else fails at this
    specific placement.
    """

    def test_vxe_at_twist_lock(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        r = svc.validate_placement("forward_warning", "whelen_vxe", "HEADLIGHT_TWIST_LOCK")
        assert r["valid"] is True

    def test_vertex_at_twist_lock(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        r = svc.validate_placement("forward_warning", "whelen_vertex", "HEADLIGHT_TWIST_LOCK")
        assert r["valid"] is True

    def test_off_brand_excluded_at_twist_lock(self, tmp_path):
        svc = PartsDbService(_paths(tmp_path))
        # off_brand_universal has no fits restrictions, but placement restricts it out
        r = svc.validate_placement("forward_warning", "off_brand_universal", "HEADLIGHT_TWIST_LOCK")
        assert r["valid"] is False
        assert "not allowed at placement" in r["reason"]
