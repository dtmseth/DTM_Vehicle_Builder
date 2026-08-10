"""Translate a picker color selection into concrete SKUs and build rows.

Pure functions — no I/O, no service access. Callers pass in the product's
PartNumber list (already loaded from parts_db) plus the chosen per-head colors.

The picker produces a list of "heads", each a list of color tokens
(e.g. [["red","white"], ["red","white"], ["blue","white"], ["blue","white"]]
for a 4-head standard-split duo). This module:

  1. match_heads()  — groups identical color sets, finds the matching SKUs for
     each (a combo can match several output/lens variants), reports any combo
     with no matching SKU.
  2. build_rows()   — given the user's chosen SKU + quantity per combo, emits
     PartInput-shaped row dicts (one per combo) plus a consolidated build-sheet
     description.

SKU color matching is set-equality on the SKU's colors, after first rejecting
any repeated-color request (for example, Red/Red). A 3-color "trio" head can
match only an actual three-color SKU; otherwise it is reported as unmatched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Canonical display order for joining colors into names/descriptions. Mirrors
# naming_rules.light_part_name.color_canonical_order in parts_db.json.
_COLOR_ORDER = ["red", "blue", "white", "amber", "green", "purple"]


def _ion_rank(part_number: str) -> int:
    """Sort key: I2_ preferred (0), IOND/IONE deprecated (2), others normal (1)."""
    if part_number.startswith("I2"):
        return 0
    if part_number.startswith(("IOND", "IONE")):
        return 2
    return 1


def _color_key(colors: list[str]) -> tuple[str, ...]:
    """Order-insensitive key for a requested head, retaining multiplicity.

    A repeated color is not a valid two-/three-color lighthead. Keeping it in
    the key lets ``match_heads`` reject it instead of resolving a single-color
    or lower-color-count SKU.
    """
    return tuple(sorted(c.lower() for c in colors if c))


def _color_label(colors: list[str]) -> str:
    """Canonical-ordered, slash-joined display string: 'Red/White'."""
    uniq = {c.lower() for c in colors if c}
    ordered = [c for c in _COLOR_ORDER if c in uniq]
    ordered += [c for c in sorted(uniq) if c not in _COLOR_ORDER]
    return "/".join(c.capitalize() for c in ordered)


@dataclass
class SkuOption:
    part_number: str
    price: float | None
    lens_type: str
    qb: bool


@dataclass
class Combo:
    colors: list[str]          # canonical-ordered color tokens
    label: str                 # "Red/White"
    count: int                 # how many heads use this color set
    skus: list[SkuOption]      # matching SKUs, cheapest first
    default_sku: str           # part_number of the cheapest match ("" if none)
    matched: bool


def match_heads(part_numbers: list[Any], heads: list[list[str]],
                lens: str = "") -> dict:
    """Group heads by color set and resolve matching SKUs for each.

    `part_numbers` are PartNumber dataclasses (need .color, .secondary_color,
    .lens_type, .part_number, .qb_unit_price, .price_usd, .qb_item_id).
    `lens` optionally filters SKUs to a lens type (clear/colored/smoked).
    """
    # Bucket heads by color set, preserving first-seen order.
    order: list[tuple[str, ...]] = []
    buckets: dict[tuple[str, ...], list[str]] = {}
    for head in heads:
        key = _color_key(head)
        if key not in buckets:
            buckets[key] = list(dict.fromkeys(c.lower() for c in head if c))
            order.append(key)

    counts: dict[tuple[str, ...], int] = {}
    for head in heads:
        key = _color_key(head)
        counts[key] = counts.get(key, 0) + 1

    combos: list[Combo] = []
    for key in order:
        want = set(key)
        matches: list[SkuOption] = []
        # The picker has no valid meaning for Red/Red or Red/Blue/Blue. Reject
        # impossible requests even if a client accidentally sends one.
        if len(key) == len(want):
            for pn in part_numbers:
                have = {c for c in (getattr(pn, "color", ""),
                                    getattr(pn, "secondary_color", ""),
                                    getattr(pn, "tertiary_color", "")) if c}
                # An empty `want` is the picker's "no color filter" choice: every SKU
                # matches (scene/interior lights are white and need no filter). Only a
                # non-empty want requires exact color-set equality. Without this guard,
                # an empty want matched ONLY colorless SKUs — the inverted-filter bug.
                if want and {c.lower() for c in have} != want:
                    continue
                lt = getattr(pn, "lens_type", "") or ""
                if lens and lt and lt != lens:
                    continue
                price = getattr(pn, "qb_unit_price", None) or getattr(pn, "price_usd", None)
                matches.append(SkuOption(
                    part_number=getattr(pn, "part_number", ""),
                    price=price,
                    lens_type=lt,
                    qb=bool(getattr(pn, "qb_item_id", "")),
                ))
        matches.sort(key=lambda s: (_ion_rank(s.part_number), s.price if s.price is not None else 9e9, s.part_number))
        combos.append(Combo(
            colors=buckets[key],
            label=_color_label(buckets[key]),
            count=counts[key],
            skus=matches,
            default_sku=matches[0].part_number if matches else "",
            matched=bool(matches),
        ))

    return {
        "combos": [_combo_to_dict(c) for c in combos],
        "all_matched": all(c.matched for c in combos),
        "head_count": len(heads),
    }


def _combo_to_dict(c: Combo) -> dict:
    return {
        "colors": c.colors,
        "label": c.label,
        "count": c.count,
        "matched": c.matched,
        "default_sku": c.default_sku,
        "skus": [
            {"part_number": s.part_number, "price": s.price,
             "lens_type": s.lens_type, "qb": s.qb}
            for s in c.skus
        ],
    }


def build_rows(product_model: str, manufacturer_label: str, location: str,
               base_name: str, lens: str, combo_choices: list[dict],
               color_fields: dict | None = None, total_heads: int = 0) -> dict:
    """Turn the user's per-combo SKU + quantity choices into ONE parent row.

    combo_choices: [{colors:[...], part_number:"IOND", quantity:2, price:178}]

    Returns {rows: [<one parent dict>], description, total}. The parent is the
    simple, build-sheet-facing line (name / manufacturer / model / color profile
    / total quantity). The concrete SKUs become `components` on the parent —
    shown as expandable children in the manifest UI, never sent to the planner.

    `color_fields` (from the picker, which knows the color mode) optionally
    supplies raw_color + driver/passenger/center for correct rendering; missing
    pieces fall back to a combined color string.
    """
    components: list[dict] = []
    desc_parts: list[str] = []
    total = 0.0
    for ch in combo_choices:
        colors = ch.get("colors") or []
        qty = int(ch.get("quantity") or 0)
        pn = (ch.get("part_number") or "").strip()
        if qty <= 0 or not pn:
            continue
        color_label = _color_label(colors)
        price = ch.get("price")
        if isinstance(price, (int, float)):
            total += price * qty
        components.append({
            "part_number": pn,
            "color": color_label,
            "quantity": qty,
            "price": price,
        })
        desc_parts.append(f"({qty}) {product_model} {color_label}")

    if not components:
        return {"rows": [], "description": "", "total": 0.0}

    cf = color_fields or {}
    qty_total = total_heads or sum(c["quantity"] for c in components)
    raw_color = cf.get("raw_color") or ", ".join(
        dict.fromkeys(c["color"] for c in components))

    parent = {
        "name": base_name,
        "include": True,
        "manufacturer": manufacturer_label,
        "part_number": product_model,
        "location": location,
        "raw_color": raw_color,
        "quantity": qty_total,
        "lens": lens or "",
        "notes": "",
        "explicit_color_profile": cf.get("explicit_color_profile", ""),
        "driver_color": cf.get("driver_color", ""),
        "passenger_color": cf.get("passenger_color", ""),
        "center_color": cf.get("center_color", ""),
        "components": components,
    }

    description = ", ".join(desc_parts)
    if location:
        description = f"{description} — {location}" if description else location
    return {"rows": [parent], "description": description, "total": round(total, 2)}
