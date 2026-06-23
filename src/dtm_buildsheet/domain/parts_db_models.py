"""Typed return shapes for parts_db_service (schema v2).

Tree-based hierarchy for user navigation:
    Type → Section → Zone → Sub-zone? → Part Type

Plus orthogonal taxonomies:
    Tags                — themes (camera, radar, siren, comms)
    Build Attributes    — pre-selected booleans hiding zones/types
    Preference Filters  — per-category manufacturer restrictions
    Services            — line items the customer wants (not parts)

Compatibility uses a single intersection-based rule applied everywhere:
a (part_type, product, placement) triple is valid iff each entity's
optional whitelist either is empty or contains the other entities.

Each Product is the unit of identity. Models include `fits_part_types`
(forward-indexed for fast lookup from the part_type side too). Variants
live inside the product as a flat `part_numbers[]` list; entries gain
`friendly_name` / `options` tags incrementally as the owner populates
SKU detail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Top-level taxonomies ─────────────────────────────────────────────────────


@dataclass
class Type:
    type_id: str
    label: str
    requires_attribute: str = ""   # build_attribute that must be true for this type to show


@dataclass
class Section:
    section_id: str
    label: str


@dataclass
class Zone:
    """Tree-navigation zone (Front, Rear, Interior > Forward of Cage, etc.)."""
    zone_id: str
    label: str
    section: str
    requires_attribute: str = ""


@dataclass
class SubZone:
    sub_zone_id: str
    label: str
    zone: str
    requires_attribute: str = ""


@dataclass
class BuildAttribute:
    """Pre-selected boolean that filters the visible tree at build time."""
    attribute_id: str
    label: str
    default_by_build_type: dict[str, bool] = field(default_factory=dict)


@dataclass
class Tag:
    tag_id: str
    label: str


# ── Placement-side taxonomies ────────────────────────────────────────────────


@dataclass
class PlacementZone:
    """Light part-type derivation zone (primary_front, front_corner, etc.).

    Distinct from the tree-navigation Zone above. Used by the workbook
    label sequencing and by the workbook input path for legacy compat.
    """
    placement_zone_id: str
    label: str


@dataclass
class Placement:
    """Per-location restriction metadata."""
    location_id: str               # the physical location key from vehicle_layouts.json
    placement_zone: str = ""       # which light placement_zone this location is in
    allowed_products: list[str] = field(default_factory=list)


# ── Products + SKUs ──────────────────────────────────────────────────────────


@dataclass
class Manufacturer:
    manufacturer_id: str
    label: str
    website: str = ""


@dataclass
class PartNumber:
    """One concrete SKU under a product. Sparse during transition.

    QB-linked fields (qb_item_id, qb_sku, qb_unit_price, qb_inactive, vehicle_tags)
    are populated by the QB Pass 2 linking workflow. Color fields are parsed from
    QB Sales Description first, then SKU letter patterns as fallback.
    """
    part_number: str
    friendly_name: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    qty_on_hand: int | None = None
    price_usd: float | None = None
    # ── Color / lens (populated from QB data) ──
    color: str = ""            # primary: "red", "blue", "amber", "white", "green", "purple"
    secondary_color: str = ""  # 2nd color (duo heads): "white", "amber", "blue"
    tertiary_color: str = ""   # 3rd color (trio heads, e.g. R/B/W → red,blue,white)
    lens_type: str = ""        # "clear", "colored", "smoked"
    # ── QB linkage (populated by qb_apply_links.py) ──
    qb_item_id: str = ""
    qb_sku: str = ""
    qb_unit_price: float | None = None
    qb_inactive: bool = False
    # Pre-added before it exists in QuickBooks: usable in builds and billable
    # (via price_usd), but flagged on the estimate as "create item" and
    # auto-reconciled when the SKU later appears in QB. See docs/PENDING_QB_PARTS.md.
    qb_pending: bool = False
    vehicle_tags: list[str] = field(default_factory=list)


@dataclass
class Product:
    product_id: str
    manufacturer_id: str
    model: str                              # freeform — name or number, whatever it's called
    fits_part_types: list[str] = field(default_factory=list)
    tag_ids: list[str] = field(default_factory=list)
    description: str = ""
    images: dict[str, str] = field(default_factory=dict)
    part_numbers: list[PartNumber] = field(default_factory=list)


# ── Part types ───────────────────────────────────────────────────────────────


@dataclass
class TreePosition:
    """One position a part_type occupies in the navigation tree. A part_type
    may have multiple positions (e.g. Side Warning at exterior side AND
    interior prisoner area)."""
    section: str
    zone: str
    sub_zone: str = ""


@dataclass
class PartType:
    part_type_id: str
    label: str
    type_id: str                                            # top-level type (lights, equipment, ...)
    category: str = ""                                      # usage category within the type
                                                            # (lights: warning/scene/interior/
                                                            #  interior_bar/roof_bar/spotlight)
    tree_positions: list[TreePosition] = field(default_factory=list)
    tag_ids: list[str] = field(default_factory=list)
    max_count: int | None = None                            # None = unlimited
    accessory_of: str = ""                                  # parent part_type_id, if accessory
    accessories: list[str] = field(default_factory=list)    # suggested when this part_type is added
    allowed_products: list[str] = field(default_factory=list)
    allowed_placements: list[str] = field(default_factory=list)
    workbook_label_pattern: str = "{label}"                 # legacy workbook export label
    sequence_scope: str = "global"                          # per_part_type counter scope


# ── Color palette ────────────────────────────────────────────────────────────


@dataclass
class Color:
    color_id: str
    label: str
    hex: str = ""
    naming_token: str = ""


# ── Services (non-product line items) ────────────────────────────────────────


@dataclass
class Service:
    service_id: str
    label: str


# ── Preference filters ───────────────────────────────────────────────────────


@dataclass
class PreferenceFilter:
    """Maps a project.preferences.X field to a per-scope manufacturer restriction.

    `filter_scope` accepts exactly one of: type_id, part_type_ids, tag_ids.
    """
    filter_id: str
    preference_field: str                       # "preferences.lighting", etc.
    filter_scope_kind: str                      # "type_id" | "part_type_ids" | "tag_ids"
    filter_scope_values: list[str] = field(default_factory=list)
    filter_action: str = "restrict_to_manufacturer"
