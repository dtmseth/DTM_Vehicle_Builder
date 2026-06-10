"""Typed return shapes for parts_db_service.

Manufacturer-centric hierarchy:
    Category → Manufacturer → Product → PartNumber

A Product is the unit of identity in the parts database — exactly one
manufacturer and one category per product. Variants live inside the
product as a flat `part_numbers` list (gain `friendly_name` / `options`
tags over time) plus a declarative `option_axes` block describing the
combinatorial dimensions (used by light products to generate variants
from color × lens; used by other products to filter the part_numbers UI).

PartType is NOT a record — it's a derivation rule. See planning/part_type_resolver
for how a placement's workbook label gets computed at render time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Category:
    category_id: str
    label: str
    applies_to_zones: list[str] = field(default_factory=list)


@dataclass
class Manufacturer:
    manufacturer_id: str
    label: str
    website: str = ""


@dataclass
class OptionAxis:
    """Declarative description of one variant dimension on a product.

    `type` selects the picker shape — multi_select_from_palette (colors),
    single_select (lens, vehicle_fitment), free_text. `axis_id` optionally
    points at a shared definition in `option_axes_catalog`; if absent,
    the axis is product-local.
    """
    name: str                           # the key under product.option_axes
    type: str
    axis_id: str = ""
    allowed: list[str] = field(default_factory=list)
    min: int | None = None
    max: int | None = None


@dataclass
class PartNumber:
    """One concrete SKU under a product.

    During transition many entries will be raw strings — `part_number`
    set, everything else empty. Owner fills `friendly_name` and
    `options` over time. Untyped SKUs are valid and just display the
    raw string in the UI.
    """
    part_number: str
    friendly_name: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    qty_on_hand: int | None = None
    price_usd: float | None = None


@dataclass
class Product:
    product_id: str
    manufacturer_id: str
    category_id: str
    model: str                          # freeform — name or number, whatever it's called
    description: str = ""
    images: dict[str, str] = field(default_factory=dict)
    option_axes: dict[str, OptionAxis] = field(default_factory=dict)
    part_numbers: list[PartNumber] = field(default_factory=list)
    # For bracket products only — points at the products this bracket attaches to.
    compatible_with_products: list[str] = field(default_factory=list)


@dataclass
class Color:
    color_id: str
    label: str
    hex: str = ""
    naming_token: str = ""


@dataclass
class Zone:
    zone_id: str
    label: str


@dataclass
class PartType:
    """Derivation rule, not a record.

    `predicate` is a declarative match — never a string expression.
    `sequence_scope` selects how the sequence counter rolls over:
      "per_zone_per_role" — counter per (zone, role)
      "global"            — one counter for everything in this part_type
    `workbook_label_pattern` is the legacy compatibility hook — produces
    the string ("Forward Warning 1") that build_rules.json keys on.
    """
    part_type_id: str
    label: str
    category_id: str
    predicate: dict[str, Any] = field(default_factory=dict)
    sequence_scope: str = "global"
    workbook_label_pattern: str = "{label}"
