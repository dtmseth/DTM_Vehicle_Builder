"""Render workbook-style part-type labels for placements (schema v2).

In the new schema the user picks the part_type directly from the tree, so
the resolver no longer needs to derive part_type from (category, zone, colors).
It just renders the workbook_label_pattern with a per-part-type sequence
counter — enough to keep build_rules.json compatible with the existing
string-keyed rule entries (Forward Warning 1, Forward Warning 2, etc.).

Usage:

    resolver = PartTypeResolver(parts_db_doc)
    for placement in draft.placements_in_render_order:
        label = resolver.next_label(placement)

`next_label` is stateful — call once per placement in the order they should
appear in the build sheet.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Placement:
    """Minimal shape consumed by the resolver. Real placements (in domain/
    plan_models.py) carry more; this is just what derivation needs."""
    part_type_id: str
    product_id: str = ""
    location_id: str = ""


class PartTypeResolver:
    def __init__(self, parts_db_doc: dict):
        self._part_types: dict = (parts_db_doc or {}).get("part_types") or {}
        self._counters: dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        self._counters.clear()

    def next_label(self, placement: Placement) -> str:
        pt = self._part_types.get(placement.part_type_id)
        if not pt:
            return placement.part_type_id or "?"
        self._counters[placement.part_type_id] += 1
        n = self._counters[placement.part_type_id]
        pattern = pt.get("workbook_label_pattern") or pt.get("label", placement.part_type_id)
        return pattern.format(n=n)
