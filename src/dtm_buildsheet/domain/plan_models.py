from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .input_models import PartInput
from .supply import supply_state


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
    mount_visibility: str = ""
    callout_label: str = ""
    callout_dx: float = 0.0
    callout_dy: float = 0.0
    layer: int = 0
    group_shapes: bool = False
    is_fixture: bool = False
    slot_indices: list[int] | None = None
    position_slot_count: int | None = None
    # Some accessories turn several ordinary render instances into one
    # placement unit. A dual T-Series shroud, for example, occupies one cargo-
    # window position while visibly containing two side-by-side lightheads.
    compound_group_size: int = 1
    compound_group_count: int = 0
    compound_group_style: str = ""
    compound_item_spacing: float = 1.0
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
    # Ephemeral render inputs derived from ProjectRecord reference assignments.
    # ``local_path`` is stripped from serialized BuildPlan JSON below so a
    # workstation path never becomes shared project data.
    reference_photos: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("reference_photos"):
            for photo in data["reference_photos"]:
                photo.pop("local_path", None)
        else:
            data.pop("reference_photos", None)
        for part in data.get("planned_parts", []):
            raw = part.get("raw")
            if isinstance(raw, dict):
                # Keep the derived plan-JSON contract stable during the legacy
                # compatibility window. New and customer-used meanings are
                # exactly recoverable from new_or_used/source, so their
                # additive canonical keys stay in memory but need not churn
                # every saved BuildPlan. Customer-supplied New cannot be
                # represented by the old vocabulary and retains the new keys.
                canonical = supply_state(raw)
                legacy = supply_state({
                    "new_or_used": raw.get("new_or_used", ""),
                    "source": raw.get("source", ""),
                })
                if canonical == legacy:
                    raw.pop("supply_type", None)
                    raw.pop("customer_condition", None)
                    raw.pop("customer_source", None)
            if isinstance(raw, dict) and raw.get("components") == []:
                raw.pop("components")
            if isinstance(raw, dict) and raw.get("picker_config") == {}:
                raw.pop("picker_config")
            for placement in part.get("placements", []):
                if placement.get("translate_dx") == 0.0:
                    placement.pop("translate_dx")
                if placement.get("translate_dy") == 0.0:
                    placement.pop("translate_dy")
                if placement.get("callout_dx") == 0.0:
                    placement.pop("callout_dx")
                if placement.get("callout_dy") == 0.0:
                    placement.pop("callout_dy")
                if placement.get("compound_group_size") == 1:
                    placement.pop("compound_group_size")
                if placement.get("compound_group_count") == 0:
                    placement.pop("compound_group_count")
                if placement.get("compound_group_style") == "":
                    placement.pop("compound_group_style")
                if placement.get("compound_item_spacing") == 1.0:
                    placement.pop("compound_item_spacing")
        return data
