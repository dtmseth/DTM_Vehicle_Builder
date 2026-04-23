from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PartInput:
    name: str
    include: bool = True
    new_or_used: str = ""
    source: str = ""
    manufacturer: str = ""
    part_number: str = ""
    location: str = ""
    raw_color: str = ""
    quantity: int = 0
    lens: str = ""
    notes: str = ""
    explicit_color_profile: str = ""
    driver_color: str = ""
    passenger_color: str = ""
    center_color: str = ""


@dataclass
class ProjectInput:
    info: dict[str, Any]
    parts: list[PartInput]
    notes: list[str]


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
    spacing: float | None = None  # relative to image width (0.0–1.0); None = auto
    size_override: dict[str, float] | None = None  # {"w": inches, "h": inches} per-view override
    instances: list[RenderInstance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PlannedPart:
    part_id: str
    part_name: str
    category: str
    render_kind: str
    on_diagram: bool
    raw: PartInput
    placements: list[PlannedPlacement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BuildPlan:
    version: str
    project: dict[str, Any]
    planned_parts: list[PlannedPart]
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

