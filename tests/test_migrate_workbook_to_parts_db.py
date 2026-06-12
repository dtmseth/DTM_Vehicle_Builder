"""Phase 3 (schema v2): pin the migration script's output.

Small synthetic input (3 manufacturers × 4 products × 2 vehicles) →
known-good parts_db.json + legacy_workbook_index.json under the new
tree-based schema.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import migrate_workbook_to_parts_db as mig  # noqa: E402


# ── Synthetic input fixture ─────────────────────────────────────────────────


def _synthetic_inputs() -> dict:
    return {
        "workbook_rules": {
            "schema_version": 1,
            "template_sections": [],
            "part_rules": {
                "Forward Warning 1": {
                    "manufacturer": ["WHELEN", "SOUNDOFF", "SPECIFY MFG"],
                    "models": ["ION", "MPOWER"],
                    "locations": ["GRILL", "PUSH_BUMPER_TOP"],
                    "colors": ["Red", "Blue", "White", "Red/Blue"],
                    "lens": ["STANDARD LENS", "SMOKED LENS"],
                },
                "Forward Warning 2": {
                    "manufacturer": ["WHELEN"],
                    "models": ["ION"],
                    "locations": ["GRILL"],
                },
                "Push Bumper": {
                    "manufacturer": ["SETINA"],
                    "models": ["PB400"],
                    "locations": ["PUSH_BUMPER_TOP"],
                },
                "Cage": {
                    "manufacturer": ["SETINA", "PRO-GARD"],
                    "models": ["UNKNOWN_TEST_MODEL"],
                    "locations": [],
                },
            },
        },
        "parts_library": {
            "schema_version": 1,
            "parts": [
                {"display_name": "ION", "category": "FRONT WARNING LIGHTS",
                 "manufacturer": "WHELEN", "model_number": "ION",
                 "compatible_types": ["Forward Warning 1", "Forward Warning 2"]},
                {"display_name": "MPOWER", "category": "FRONT WARNING LIGHTS",
                 "manufacturer": "",   # script falls back to MODEL_MANUFACTURER hand-table
                 "model_number": "MPOWER",
                 "compatible_types": ["Forward Warning 1"]},
                {"display_name": "PB400", "category": "PUSH BUMPER",
                 "manufacturer": "SETINA", "model_number": "PB400",
                 "compatible_types": ["Push Bumper"]},
            ],
        },
        "vehicle_layouts": {
            "schema_version": 1,
            "vehicles": {
                "TAHOE": {"views": {"front": {"locations": {
                    "GRILL":           {"x": 0.5, "y": 0.5},
                    "PUSH_BUMPER_TOP": {"x": 0.5, "y": 0.6},
                }}}},
                "PIU":   {"views": {"front": {"locations": {
                    "GRILL": {"x": 0.4, "y": 0.5},
                }}}},
            },
        },
        "part_catalog": {
            "schema_version": 1,
            "parts": [
                {"part_id": "fw1", "display_name": "Forward Warning 1",
                 "category": "warning_light", "render_kind": "light", "default_views": ["front"]},
                {"part_id": "pb",  "display_name": "Push Bumper",
                 "category": "equipment", "render_kind": "equipment", "default_views": ["front"]},
                {"part_id": "cg",  "display_name": "Cage",
                 "category": "equipment", "render_kind": "equipment", "default_views": ["front"]},
            ],
        },
    }


@pytest.fixture
def inputs():
    return _synthetic_inputs()


@pytest.fixture
def built(inputs):
    orphans = mig.Orphans()
    out = mig.build_parts_db(inputs, orphans)
    return out, orphans


# ── parts_db.json shape (schema v2) ─────────────────────────────────────────


class TestPartsDbShape:
    def test_top_level_keys_present(self, built):
        out, _ = built
        db = out["parts_db"]
        assert db["schema_version"] == 2
        for key in ("types", "sections", "zones", "sub_zones", "build_attributes",
                    "tags", "manufacturers", "products", "part_types",
                    "placements", "placement_zones", "services",
                    "preference_filters", "color_palette", "naming_rules"):
            assert key in db, f"missing {key}"

    def test_manufacturers_filter_sentinels(self, built):
        out, _ = built
        mfgs = out["parts_db"]["manufacturers"]
        # WHELEN, SOUNDOFF, SETINA, PRO-GARD — SPECIFY MFG filtered
        assert {"whelen", "soundoff", "setina", "pro_gard"} <= set(mfgs.keys())

    def test_static_taxonomies_emitted(self, built):
        out, _ = built
        db = out["parts_db"]
        assert "lights" in db["types"]
        assert "structural" in db["types"]
        assert "exterior" in db["sections"]
        assert "front" in db["zones"]
        assert "console" in db["sub_zones"]
        assert "has_k9" in db["build_attributes"]
        assert "camera" in db["tags"]
        assert "graphics" in db["services"]
        assert "lighting_brand" in db["preference_filters"]


# ── Products ────────────────────────────────────────────────────────────────


class TestProducts:
    def test_minted_product_ids(self, built):
        out, _ = built
        prods = out["parts_db"]["products"]
        assert "whelen_ion" in prods
        assert "soundoff_mpower" in prods
        assert "setina_pb400" in prods

    def test_product_has_manufacturer_model_fits(self, built):
        out, _ = built
        p = out["parts_db"]["products"]["whelen_ion"]
        assert p["manufacturer_id"] == "whelen"
        assert p["model"] == "ION"
        # Workbook_rules has Forward Warning 1 + Forward Warning 2, both
        # collapse to forward_warning part_type → exactly one entry in fits
        assert p["fits_part_types"] == ["forward_warning"]

    def test_product_part_numbers_seeded_with_model(self, built):
        out, _ = built
        p = out["parts_db"]["products"]["whelen_ion"]
        assert p["part_numbers"] == [{"part_number": "ION"}]


# ── Part types ──────────────────────────────────────────────────────────────


class TestPartTypes:
    def test_forward_warning_collapses(self, built):
        out, _ = built
        # Forward Warning 1 + Forward Warning 2 → one part_type
        pts = out["parts_db"]["part_types"]
        assert "forward_warning" in pts
        forwards = [pid for pid in pts if "forward" in pid]
        assert forwards == ["forward_warning"]

    def test_workbook_label_pattern(self, built):
        out, _ = built
        pt = out["parts_db"]["part_types"]["forward_warning"]
        assert pt["workbook_label_pattern"] == "Forward Warning {n}"

    def test_push_bumper_at_exterior_front(self, built):
        out, _ = built
        pt = out["parts_db"]["part_types"]["push_bumper"]
        assert pt["type_id"] == "structural"
        assert pt["tree_positions"] == [{"section": "exterior", "zone": "front"}]


# ── legacy_workbook_index.json ──────────────────────────────────────────────


class TestLegacyWorkbookIndex:
    def test_part_type_to_products(self, built):
        out, _ = built
        idx = out["legacy_workbook_index"]["part_type_to_products"]
        assert "Forward Warning 1" in idx
        assert set(idx["Forward Warning 1"]) == {"whelen_ion", "soundoff_mpower"}
        assert set(idx["Push Bumper"]) == {"setina_pb400"}

    def test_model_string_to_product(self, built):
        out, _ = built
        idx = out["legacy_workbook_index"]["model_string_to_product"]
        assert idx["ION"] == "whelen_ion"
        assert idx["PB400"] == "setina_pb400"


# ── Orphans ─────────────────────────────────────────────────────────────────


class TestOrphans:
    def test_unknown_model_orphan_collected(self, built):
        _, orphans = built
        models = [m for m, _ in orphans.unknown_model_manufacturers]
        assert "UNKNOWN_TEST_MODEL" in models

    def test_orphans_property(self, built):
        _, orphans = built
        assert orphans.any is True


# ── Helpers ─────────────────────────────────────────────────────────────────


class TestHelpers:
    def test_slugify(self):
        assert mig.slugify("WHELEN") == "whelen"
        assert mig.slugify("Gamber Johnson") == "gamber_johnson"
        assert mig.slugify("Pro-Gard") == "pro_gard"

    def test_lookup_manufacturer_uses_parts_library(self):
        inputs = _synthetic_inputs()
        assert mig.lookup_manufacturer_for_model("ION", inputs["workbook_rules"], inputs["parts_library"]) == "whelen"

    def test_lookup_falls_back_to_hand_table(self):
        inputs = _synthetic_inputs()
        assert mig.lookup_manufacturer_for_model("MPOWER", inputs["workbook_rules"], inputs["parts_library"]) == "soundoff"

    def test_lookup_returns_none_when_unresolvable(self):
        inputs = _synthetic_inputs()
        assert mig.lookup_manufacturer_for_model("UNKNOWN_TEST_MODEL", inputs["workbook_rules"], inputs["parts_library"]) is None
