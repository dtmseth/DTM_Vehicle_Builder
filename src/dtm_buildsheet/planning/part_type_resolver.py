"""Derive a placement's workbook part-type label from the parts_db taxonomy.

Phase 3 hook that keeps build_rules.json unchanged. The rule engine matches
on part name strings ("Forward Warning 1", "Push Bumper", etc); the new
parts_db doesn't store those strings — they get *computed* at planning time
from each placement's (product.category, location.zone, options.colors) +
a per-scope sequence counter.

Usage:

    resolver = PartTypeResolver(parts_db_doc)
    for placement in draft.placements:
        label = resolver.next_label(placement)   # "Forward Warning 1", etc.

`next_label` is stateful — call once per placement in the order they should
appear in the build sheet. Sequence counters roll forward within their
scope ("per_zone_per_role" → separate counters for Forward Warning vs
Side Warning; "global" → one counter for the whole draft).

If no part_type matches, returns the product's friendly name (or the
product_id as a last resort). Never raises on bad input — a draft with
data quality issues should still render, with the planner warning the
user separately.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class Placement:
    """Minimal shape consumed by the resolver. Real placements (in domain/
    plan_models.py) carry more — this is just what the derivation needs."""
    product_id: str
    location_id: str
    options: dict[str, Any] = None  # type: ignore[assignment]


class PartTypeResolver:
    def __init__(self, parts_db_doc: dict):
        self._doc = parts_db_doc or {}
        self._products = self._doc.get("products") or {}
        self._part_types = self._doc.get("part_types") or {}
        self._location_zone_map = self._doc.get("location_zone_map") or {}
        # Sequence counters keyed by (scope_key, bucket_key).
        # scope_key = "per_zone_per_role" or "global"; bucket_key is the
        # specific sub-bucket we're counting in (e.g. ("primary_front",
        # "forward_warning") under per_zone_per_role).
        self._counters: dict[tuple, int] = defaultdict(int)

    def reset(self) -> None:
        self._counters.clear()

    def next_label(self, placement: Placement) -> str:
        """Return the workbook label for *placement*, incrementing the sequence
        counter for its scope. See module docstring for usage notes."""
        product = self._products.get(placement.product_id)
        if not product:
            return placement.product_id  # safety: render *something*
        zone = self._location_zone_map.get(placement.location_id, "")
        opts = placement.options or {}

        match = self._first_matching_part_type(product, zone, opts)
        if match is None:
            return product.get("model") or placement.product_id

        part_type_id, part_type = match
        bucket = self._sequence_bucket(part_type_id, part_type, zone)
        self._counters[bucket] += 1
        n = self._counters[bucket]
        pattern = part_type.get("workbook_label_pattern") or "{label}"
        return pattern.format(n=n, label=part_type.get("label", ""))

    # ── Internals ──────────────────────────────────────────────────────────

    def _first_matching_part_type(
        self, product: dict, zone: str, options: dict
    ) -> tuple[str, dict] | None:
        product_category = product.get("category_id", "")
        for part_type_id, part_type in self._part_types.items():
            if part_type.get("category_id") != product_category:
                continue
            if self._predicate_matches(part_type.get("predicate") or {}, zone, options):
                return part_type_id, part_type
        return None

    @staticmethod
    def _predicate_matches(predicate: dict, zone: str, options: dict) -> bool:
        # category_only: matches every placement in the category (no further constraints)
        if predicate.get("category_only"):
            return True

        # zone: exact match against the placement's resolved zone
        wanted_zone = predicate.get("zone")
        if wanted_zone is not None and wanted_zone != zone:
            return False

        # colors: declarative predicate against options.colors
        color_pred = predicate.get("colors")
        if color_pred is not None:
            colors = options.get("colors") or []
            if color_pred == "all_white":
                if not colors or any(c != "white" for c in colors):
                    return False
            elif color_pred == "any_non_white":
                if not any(c != "white" for c in colors):
                    return False
            elif color_pred == "any":
                pass  # always match
            else:
                # unknown color predicate — be strict so misconfiguration surfaces
                return False
        return True

    @staticmethod
    def _sequence_bucket(part_type_id: str, part_type: dict, zone: str) -> tuple:
        scope = part_type.get("sequence_scope") or "global"
        if scope == "per_zone_per_role":
            return (scope, zone, part_type_id)
        return (scope, part_type_id)
