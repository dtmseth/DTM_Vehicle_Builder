"""Phase 3 (schema v2): PartTypeResolver sequence rendering.

Simplified resolver — user picks part_type directly; resolver renders
workbook_label_pattern with per-part-type sequence counter.
"""
from __future__ import annotations

from dtm_buildsheet.planning.part_type_resolver import PartTypeResolver, Placement


_DB = {
    "schema_version": 2,
    "part_types": {
        "forward_warning": {
            "label": "Forward Warning",
            "type_id": "lights",
            "workbook_label_pattern": "Forward Warning {n}",
            "sequence_scope": "global",
        },
        "side_warning": {
            "label": "Side Warning",
            "type_id": "lights",
            "workbook_label_pattern": "Side Warning {n}",
            "sequence_scope": "global",
        },
        "push_bumper": {
            "label": "Push Bumper",
            "type_id": "structural",
            "workbook_label_pattern": "Push Bumper",
            "sequence_scope": "global",
        },
    },
}


class TestSequencing:
    def test_sequenced_label(self):
        r = PartTypeResolver(_DB)
        assert r.next_label(Placement("forward_warning", "p1", "GRILL")) == "Forward Warning 1"
        assert r.next_label(Placement("forward_warning", "p2", "PUSH_BUMPER_TOP")) == "Forward Warning 2"

    def test_separate_counters_per_part_type(self):
        r = PartTypeResolver(_DB)
        assert r.next_label(Placement("forward_warning", "p1", "GRILL")) == "Forward Warning 1"
        assert r.next_label(Placement("side_warning", "p2", "A_PILLAR")) == "Side Warning 1"
        assert r.next_label(Placement("forward_warning", "p3", "GRILL")) == "Forward Warning 2"
        assert r.next_label(Placement("side_warning", "p4", "REAR_DOOR_WINDOW")) == "Side Warning 2"

    def test_pattern_without_n_omits_sequence(self):
        r = PartTypeResolver(_DB)
        # push_bumper pattern is "Push Bumper" with no {n}
        assert r.next_label(Placement("push_bumper", "p1", "PUSH_BUMPER_TOP")) == "Push Bumper"
        # Counter still increments but isn't visible
        assert r.next_label(Placement("push_bumper", "p2", "PUSH_BUMPER_TOP")) == "Push Bumper"

    def test_reset(self):
        r = PartTypeResolver(_DB)
        r.next_label(Placement("forward_warning", "p1", "GRILL"))
        r.reset()
        assert r.next_label(Placement("forward_warning", "p1", "GRILL")) == "Forward Warning 1"

    def test_unknown_part_type_falls_back_to_id(self):
        r = PartTypeResolver(_DB)
        assert r.next_label(Placement("nope", "p1", "GRILL")) == "nope"

    def test_empty_db_safe(self):
        r = PartTypeResolver({})
        assert r.next_label(Placement("forward_warning", "p1", "GRILL")) == "forward_warning"
