"""Typed return values from parts_db_service.

These are read-only views over `parts_db.json` content. They are NOT persisted
records — parts_db is a single document, not a per-record collection. The
dataclasses exist so callers get type help and so the service can return the
same shape whether the data came from parts_db.json or the legacy fallback
(workbook_rules.json / parts_library.json / vehicle_layouts.json).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Color:
    color_id: str
    label: str
    hex: str = ""
    naming_token: str = ""


@dataclass
class Manufacturer:
    manufacturer_id: str
    label: str
    website: str = ""


@dataclass
class Model:
    model_id: str
    model_number: str = ""
    submodel: str = ""
    color_count: int = 1
    power_outputs: int = 0
    supported_colors: list[str] = field(default_factory=list)
    price_usd: float | None = None
    qty_on_hand: int | None = None


@dataclass
class Zone:
    zone_id: str
    label: str


@dataclass
class BuildSection:
    section_id: str
    label: str
    order: int = 0


@dataclass
class Location:
    location_id: str
    label: str
    zone: str = ""


@dataclass
class BracketRequirement:
    required: bool
    compatible_bracket_part_ids: list[str] = field(default_factory=list)


@dataclass
class Part:
    part_id: str
    friendly_name: str
    category: str
    manufacturer_id: str = ""
    build_section: str = ""
    template_section: str = ""
    legacy_workbook_name: str = ""
    aliases: list[str] = field(default_factory=list)
    models: list[Model] = field(default_factory=list)
    compatible_vehicles: list[str] = field(default_factory=list)
    compatible_locations_by_vehicle: dict[str, list[str]] = field(default_factory=dict)
    color_asset_map: dict[str, str] = field(default_factory=dict)
    bracket_required: bool = False
    compatible_bracket_part_ids: list[str] = field(default_factory=list)
    # bracket-specific reverse fields (when this part IS a bracket)
    compatible_part_ids: list[str] = field(default_factory=list)
    compatible_locations: list[str] = field(default_factory=list)
    serialized: bool = False
