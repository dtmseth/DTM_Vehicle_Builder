from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .input_models import PartInput


@dataclass
class RenderInstance:
    slot_index: int
    slot_role: str
    orientation: str
    color_token: str = ""
    asset_path: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class PlannedPlacement:
    part_id: str
    part_name: str
    view: str
    location_key: str
    render_kind: str
    asset_key: str
    size_class: str
    color_profile: str
    quantity_policy: str
    ordered_quantity: int
    location_slot_count: int
    anchor: dict[str, Any]
    pattern: str
    h_spacing: float | None = None
    v_spacing: float | None = None
    h_spacing_units: str = "relative_image"
    size_override: dict[str, float] | None = None
    size_scale: float = 1.0
    rotation: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    flip_mirrored_h: bool = False
    translate_dx: float = 0.0
    translate_dy: float = 0.0
    behind_vehicle: bool = False
    layer: int = 0
    group_shapes: bool = False
    is_fixture: bool = False
    slot_indices: list[int] | None = None
    position_slot_count: int | None = None
    instances: list[RenderInstance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    line_id: str = ""


@dataclass
class PlannedPart:
    part_id: str
    part_name: str
    category: str
    render_kind: str
    on_diagram: bool
    raw: PartInput
    accessory_of: str | None = None
    placements: list[PlannedPlacement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BuildPlan:
    version: str
    project: dict[str, Any]
    planned_parts: list[PlannedPart]
    warnings: list[str] = field(default_factory=list)
    notes: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for part in data.get("planned_parts", []):
            raw = part.get("raw")
            if isinstance(raw, dict) and raw.get("components") == []:
                raw.pop("components")
            for placement in part.get("placements", []):
                if placement.get("translate_dx") == 0.0:
                    placement.pop("translate_dx")
                if placement.get("translate_dy") == 0.0:
                    placement.pop("translate_dy")
        return data
