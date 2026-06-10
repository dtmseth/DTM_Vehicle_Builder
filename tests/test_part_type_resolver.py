"""Phase 3 (revised): PartTypeResolver derivation rules.

The resolver computes workbook-style labels ("Forward Warning 1", "Push Bumper")
from a placement's (product.category, location.zone, options.colors) plus
a per-scope sequence counter. This is the Phase 3 hook that keeps
build_rules.json keying on string names without modification.
"""
from __future__ import annotations

import pytest

from dtm_buildsheet.planning.part_type_resolver import PartTypeResolver, Placement


_DB = {
    "schema_version": 1,
    "categories": {
        "lights":       {"label": "Lights",       "applies_to_zones": ["primary_front", "side", "rear"]},
        "push_bumpers": {"label": "Push Bumpers", "applies_to_zones": ["primary_front"]},
    },
    "products": {
        "whelen_ion_t":  {"manufacturer_id": "whelen", "category_id": "lights",       "model": "ION T"},
        "setina_pb400":  {"manufacturer_id": "setina", "category_id": "push_bumpers", "model": "PB400"},
        "feniex_quad":   {"manufacturer_id": "feniex", "category_id": "lights",       "model": "Quad"},
    },
    "location_zone_map": {
        "GRILL":           "primary_front",
        "PUSH_BUMPER_TOP": "primary_front",
        "A_PILLAR_DRIVER": "side",
        "REAR_DECK":       "rear",
    },
    "part_types": {
        "forward_warning": {
            "label": "Forward Warning",
            "category_id": "lights",
            "predicate": {"zone": "primary_front", "colors": "any_non_white"},
            "sequence_scope": "per_zone_per_role",
            "workbook_label_pattern": "Forward Warning {n}",
        },
        "forward_scene": {
            "label": "Forward Scene",
            "category_id": "lights",
            "predicate": {"zone": "primary_front", "colors": "all_white"},
            "sequence_scope": "per_zone_per_role",
            "workbook_label_pattern": "Forward Scene {n}",
        },
        "side_warning": {
            "label": "Side Warning",
            "category_id": "lights",
            "predicate": {"zone": "side", "colors": "any_non_white"},
            "sequence_scope": "per_zone_per_role",
            "workbook_label_pattern": "Side Warning {n}",
        },
        "push_bumper": {
            "label": "Push Bumper",
            "category_id": "push_bumpers",
            "predicate": {"category_only": True},
            "sequence_scope": "global",
            "workbook_label_pattern": "Push Bumper",
        },
    },
}


# ── Per-zone-per-role sequencing ─────────────────────────────────────────────


class TestSequencing:
    def test_two_forward_warnings_increment(self):
        r = PartTypeResolver(_DB)
        l1 = r.next_label(Placement("whelen_ion_t", "GRILL",           {"colors": ["red"]}))
        l2 = r.next_label(Placement("whelen_ion_t", "PUSH_BUMPER_TOP", {"colors": ["blue"]}))
        assert l1 == "Forward Warning 1"
        assert l2 == "Forward Warning 2"

    def test_separate_counters_per_zone_per_role(self):
        r = PartTypeResolver(_DB)
        # forward warning + forward scene + side warning — each in its own bucket
        l1 = r.next_label(Placement("whelen_ion_t", "GRILL",           {"colors": ["red"]}))
        l2 = r.next_label(Placement("whelen_ion_t", "PUSH_BUMPER_TOP", {"colors": ["white"]}))
        l3 = r.next_label(Placement("whelen_ion_t", "A_PILLAR_DRIVER", {"colors": ["red"]}))
        l4 = r.next_label(Placement("whelen_ion_t", "GRILL",           {"colors": ["blue"]}))
        assert l1 == "Forward Warning 1"
        assert l2 == "Forward Scene 1"
        assert l3 == "Side Warning 1"
        assert l4 == "Forward Warning 2"

    def test_global_scope_one_counter(self):
        r = PartTypeResolver(_DB)
        l1 = r.next_label(Placement("setina_pb400", "PUSH_BUMPER_TOP"))
        # The push_bumper rule has workbook_label_pattern "Push Bumper" (no {n}) and
        # sequence_scope "global" — counter increments but pattern doesn't show it.
        assert l1 == "Push Bumper"


# ── Predicate matching ──────────────────────────────────────────────────────


class TestPredicateMatching:
    def test_all_white_is_scene(self):
        r = PartTypeResolver(_DB)
        assert r.next_label(Placement("whelen_ion_t", "GRILL", {"colors": ["white"]})) == "Forward Scene 1"

    def test_red_white_is_warning(self):
        r = PartTypeResolver(_DB)
        # any_non_white predicate matches even when white is mixed in
        assert r.next_label(Placement("whelen_ion_t", "GRILL", {"colors": ["red", "white"]})) == "Forward Warning 1"

    def test_no_colors_no_match_for_color_predicates(self):
        # Light with no colors → none of the light part_types match
        # (push_bumper is category_only but wrong category) →
        # resolver falls back to product model name
        r = PartTypeResolver(_DB)
        assert r.next_label(Placement("whelen_ion_t", "GRILL", {})) == "ION T"

    def test_category_only_matches_any_options(self):
        r = PartTypeResolver(_DB)
        assert r.next_label(Placement("setina_pb400", "PUSH_BUMPER_TOP", {})) == "Push Bumper"


# ── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_unknown_product_returns_product_id(self):
        r = PartTypeResolver(_DB)
        assert r.next_label(Placement("nope", "GRILL", {"colors": ["red"]})) == "nope"

    def test_unknown_location_no_zone_no_zone_predicate_match(self):
        # Location not in location_zone_map → zone="" → no light part_type matches
        # (all have zone predicates) → falls back to model name
        r = PartTypeResolver(_DB)
        label = r.next_label(Placement("whelen_ion_t", "UNKNOWN_LOC", {"colors": ["red"]}))
        assert label == "ION T"

    def test_reset_clears_counters(self):
        r = PartTypeResolver(_DB)
        r.next_label(Placement("whelen_ion_t", "GRILL", {"colors": ["red"]}))
        r.next_label(Placement("whelen_ion_t", "PUSH_BUMPER_TOP", {"colors": ["red"]}))
        r.reset()
        assert r.next_label(Placement("whelen_ion_t", "GRILL", {"colors": ["red"]})) == "Forward Warning 1"

    def test_empty_db_falls_back_gracefully(self):
        r = PartTypeResolver({})
        assert r.next_label(Placement("whelen_ion_t", "GRILL", {"colors": ["red"]})) == "whelen_ion_t"
