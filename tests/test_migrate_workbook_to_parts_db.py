"""Phase 3 (revised): pin the migration script's output.

Small synthetic input (3 manufacturers × 4 products × 2 vehicles) →
known-good parts_db.json + legacy_workbook_index.json.

Drives the script's `build_parts_db()` directly so the test doesn't
touch the real resources/config/ files. Acts as both a regression
test and a worked example of the migration mapping rules.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make tools/ importable
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
                    "colors": ["Red", "Blue", "White", "Red/Blue", "Red/White/Blue"],
                    "lens": ["STANDARD LENS", "SMOKED LENS"],
                },
                "Forward Warning 2": {
                    "manufacturer": ["WHELEN"],
                    "models": ["ION"],
                    "locations": ["GRILL"],
                    "colors": ["Red", "Blue"],
                    "lens": [],
                },
                "Push Bumper": {
                    "manufacturer": ["SETINA"],
                    "models": ["PB400"],
                    "locations": ["PUSH_BUMPER_TOP"],
                },
                "Cage": {
                    # Multi-manufacturer + UNKNOWN_TEST_MODEL not in parts_library
                    # and not in MODEL_MANUFACTURER hand-table → orphan
                    "manufacturer": ["SETINA", "PRO-GARD"],
                    "models": ["UNKNOWN_TEST_MODEL"],
                    "locations": [],
                },
            },
        },
        "parts_library": {
            "schema_version": 1,
            "parts": [
                {
                    "part_id": "ion",
                    "display_name": "ION",
                    "category": "FRONT WARNING LIGHTS",
                    "manufacturer": "WHELEN",
                    "model_number": "ION",
                    "compatible_types": ["Forward Warning 1", "Forward Warning 2"],
                },
                {
                    "part_id": "mpower",
                    "display_name": "MPOWER",
                    "category": "FRONT WARNING LIGHTS",
                    "manufacturer": "",  # blank — script falls back to MODEL_MANUFACTURER hand-table
                    "model_number": "MPOWER",
                    "compatible_types": ["Forward Warning 1"],
                },
                {
                    "part_id": "pb400",
                    "display_name": "PB400",
                    "category": "PUSH BUMPER / FRONT STRUCTURE",
                    "manufacturer": "SETINA",
                    "model_number": "PB400",
                    "compatible_types": ["Push Bumper"],
                },
            ],
        },
        "vehicle_layouts": {
            "schema_version": 1,
            "vehicles": {
                "TAHOE": {
                    "views": {
                        "front": {
                            "locations": {
                                "GRILL":           {"x": 0.5, "y": 0.5},
                                "PUSH_BUMPER_TOP": {"x": 0.5, "y": 0.6},
                            },
                        },
                    },
                },
                "PIU": {
                    "views": {
                        "front": {
                            "locations": {
                                "GRILL": {"x": 0.4, "y": 0.5},
                            },
                        },
                    },
                },
            },
        },
        "part_catalog": {
            "schema_version": 1,
            "parts": [
                {"part_id": "fw1", "display_name": "Forward Warning 1",
                 "category": "warning_light", "render_kind": "light", "default_views": ["front"]},
                {"part_id": "fw2", "display_name": "Forward Warning 2",
                 "category": "warning_light", "render_kind": "light", "default_views": ["front"]},
                {"part_id": "pb",  "display_name": "Push Bumper",
                 "category": "equipment",     "render_kind": "equipment", "default_views": ["front"]},
                {"part_id": "cg",  "display_name": "Cage",
                 "category": "equipment",     "render_kind": "equipment", "default_views": ["front"]},
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


# ── parts_db.json shape ─────────────────────────────────────────────────────


class TestPartsDbShape:
    def test_top_level_keys_present(self, built):
        out, _ = built
        db = out["parts_db"]
        for key in ("categories", "manufacturers", "products", "color_palette",
                    "location_zones", "location_zone_map", "part_types", "naming_rules"):
            assert key in db, f"missing {key}"

    def test_manufacturers_filter_sentinels(self, built):
        out, _ = built
        mfgs = out["parts_db"]["manufacturers"]
        # WHELEN, SOUNDOFF, SETINA, PRO-GARD all collected — SPECIFY MFG filtered
        assert set(mfgs.keys()) == {"whelen", "soundoff", "setina", "pro_gard"}
        assert mfgs["whelen"]["label"] == "Whelen"

    def test_categories_have_zones(self, built):
        out, _ = built
        cats = out["parts_db"]["categories"]
        assert "primary_front" in cats["lights"]["applies_to_zones"]
        assert cats["push_bumpers"]["applies_to_zones"] == ["primary_front"]


# ── Products ────────────────────────────────────────────────────────────────


class TestProducts:
    def test_minted_product_ids(self, built):
        out, _ = built
        prods = out["parts_db"]["products"]
        # ION → whelen_ion, MPOWER → soundoff_mpower (resolved via MODEL_MANUFACTURER hand-table),
        # PB400 → setina_pb400, UNKNOWN_TEST_MODEL → orphan
        assert "whelen_ion" in prods
        assert "soundoff_mpower" in prods
        assert "setina_pb400" in prods

    def test_product_has_manufacturer_category_model(self, built):
        out, _ = built
        p = out["parts_db"]["products"]["whelen_ion"]
        assert p["manufacturer_id"] == "whelen"
        assert p["category_id"] == "lights"
        assert p["model"] == "ION"

    def test_lights_get_option_axes_from_workbook(self, built):
        out, _ = built
        p = out["parts_db"]["products"]["whelen_ion"]
        # Red, Blue, White from workbook colors (and Red/Blue, Red/White/Blue split)
        assert "colors" in p["option_axes"]
        assert set(p["option_axes"]["colors"]["allowed"]) == {"red", "blue", "white"}
        # STANDARD LENS / SMOKED LENS → standard, smoked
        assert "lens" in p["option_axes"]
        assert set(p["option_axes"]["lens"]["allowed"]) == {"standard", "smoked"}

    def test_non_lights_no_option_axes(self, built):
        out, _ = built
        pb = out["parts_db"]["products"]["setina_pb400"]
        assert pb["option_axes"] == {}

    def test_part_numbers_seeded_with_model_string(self, built):
        out, _ = built
        p = out["parts_db"]["products"]["whelen_ion"]
        assert p["part_numbers"] == [{"part_number": "ION"}]


# ── Categories per-display-name overrides ───────────────────────────────────


class TestCategoryMapping:
    def test_push_bumper_resolves_to_push_bumpers(self, built):
        out, _ = built
        assert out["parts_db"]["products"]["setina_pb400"]["category_id"] == "push_bumpers"

    def test_cage_resolves_to_cages(self, inputs):
        # UNKNOWN_TEST_MODEL under Cage has no resolvable manufacturer, so the
        # product won't be minted — but the category mapping itself should
        # still work. Verify by adding a resolvable model to both
        # workbook_rules (so the model gets iterated) and parts_library
        # (so the manufacturer resolves cleanly).
        inputs["workbook_rules"]["part_rules"]["Cage"]["models"].append("FAKE_CAGE_MODEL")
        inputs["parts_library"]["parts"].append({
            "display_name": "FAKE_CAGE_MODEL", "category": "X",
            "manufacturer": "SETINA", "model_number": "FAKE_CAGE_MODEL",
            "compatible_types": ["Cage"],
        })
        orphans = mig.Orphans()
        out = mig.build_parts_db(inputs, orphans)
        assert "setina_fake_cage_model" in out["parts_db"]["products"]
        assert out["parts_db"]["products"]["setina_fake_cage_model"]["category_id"] == "cages"


# ── Part types ──────────────────────────────────────────────────────────────


class TestPartTypes:
    def test_fw1_and_fw2_collapse_to_one_part_type(self, built):
        out, _ = built
        pts = out["parts_db"]["part_types"]
        # WORKBOOK_PART_TYPE_GROUPS regex `^Forward Warning \d+$` catches both
        assert "forward_warning" in pts
        # Only one entry minted even though two workbook labels matched
        forward_pts = [k for k in pts if "forward" in k]
        assert forward_pts == ["forward_warning"]

    def test_workbook_label_pattern_preserved(self, built):
        out, _ = built
        assert out["parts_db"]["part_types"]["forward_warning"]["workbook_label_pattern"] == "Forward Warning {n}"

    def test_push_bumper_part_type(self, built):
        out, _ = built
        pt = out["parts_db"]["part_types"]["push_bumper"]
        assert pt["category_id"] == "push_bumpers"
        assert pt["sequence_scope"] == "global"


# ── legacy_workbook_index.json ──────────────────────────────────────────────


class TestLegacyWorkbookIndex:
    def test_part_type_to_products(self, built):
        out, _ = built
        idx = out["legacy_workbook_index"]["part_type_to_products"]
        # "Forward Warning 1" mints from WHELEN+SOUNDOFF × ION+MPOWER → whelen_ion + soundoff_mpower
        # (SPECIFY MFG filtered; cross-product is mfg-per-model not full cartesian)
        assert "Forward Warning 1" in idx
        # Specifically: each model resolves to its single manufacturer,
        # so we get whelen_ion + soundoff_mpower (not whelen_mpower or soundoff_ion).
        assert set(idx["Forward Warning 1"]) == {"whelen_ion", "soundoff_mpower"}
        assert set(idx["Forward Warning 2"]) == {"whelen_ion"}
        assert set(idx["Push Bumper"]) == {"setina_pb400"}

    def test_model_string_to_product(self, built):
        out, _ = built
        idx = out["legacy_workbook_index"]["model_string_to_product"]
        assert idx["ION"] == "whelen_ion"
        assert idx["MPOWER"] == "soundoff_mpower"
        assert idx["PB400"] == "setina_pb400"


# ── Orphans ─────────────────────────────────────────────────────────────────


class TestOrphans:
    def test_unknown_model_orphan_collected(self, built):
        _, orphans = built
        # UNKNOWN_TEST_MODEL has no resolvable manufacturer → orphan
        models = [m for m, _ in orphans.unknown_model_manufacturers]
        assert "UNKNOWN_TEST_MODEL" in models

    def test_orphans_property(self, built):
        _, orphans = built
        assert orphans.any is True

    def test_orphans_markdown(self, built):
        _, orphans = built
        md = orphans.to_markdown()
        assert "Migration orphans report" in md
        assert "UNKNOWN_TEST_MODEL" in md


# ── Helpers ─────────────────────────────────────────────────────────────────


class TestHelpers:
    def test_slugify_basic(self):
        assert mig.slugify("WHELEN") == "whelen"
        assert mig.slugify("Gamber Johnson") == "gamber_johnson"
        assert mig.slugify("Pro-Gard") == "pro_gard"

    def test_extract_palette_colors_splits_slash(self):
        out = mig._extract_palette_colors(["Red", "Red/Blue", "Red/White/Blue", "Pink"])
        assert out == ["red", "blue", "white"]

    def test_lookup_manufacturer_for_model_uses_parts_library(self):
        inputs = _synthetic_inputs()
        slug = mig.lookup_manufacturer_for_model("ION", inputs["workbook_rules"], inputs["parts_library"])
        assert slug == "whelen"

    def test_lookup_manufacturer_falls_back_to_hand_table(self):
        inputs = _synthetic_inputs()
        # MPOWER's manufacturer is "" in parts_library + listed alongside multiple
        # mfgs in workbook_rules → resolved only by MODEL_MANUFACTURER hand-table
        slug = mig.lookup_manufacturer_for_model("MPOWER", inputs["workbook_rules"], inputs["parts_library"])
        assert slug == "soundoff"

    def test_lookup_returns_none_when_unresolvable(self):
        inputs = _synthetic_inputs()
        assert mig.lookup_manufacturer_for_model("UNKNOWN_TEST_MODEL", inputs["workbook_rules"], inputs["parts_library"]) is None
