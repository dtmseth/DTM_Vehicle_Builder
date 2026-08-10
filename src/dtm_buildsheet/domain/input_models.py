from __future__ import annotations

from dataclasses import dataclass, field
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
    # A user-authored, manifest-facing comment.  This stays separate from
    # ``notes``, which often contains picker/system configuration.
    comment: str = ""
    explicit_color_profile: str = ""
    driver_color: str = ""
    passenger_color: str = ""
    center_color: str = ""
    line_id: str = ""
    # Picker-created parts carry their canonical parts_db type. The planner
    # uses it when a manifest-friendly line name cannot be inferred from the
    # old workbook naming convention.
    part_type: str = ""
    # Picker accessories are saved as distinct purchase lines. Keep their
    # parent relationship in the planning input so customer-facing exports can
    # present the accessory directly beneath the product it belongs to.
    parent_line_id: str = ""
    linked_parent_line_id: str = ""
    accessory_category: str = ""
    accessory_parent_product: str = ""
    components: list[dict[str, Any]] = field(default_factory=list)
    # Picker configuration normally supports edit round-tripping only. A small
    # number of configured physical products also need it to faithfully render
    # their selected SKU layout (for example an Inner Edge FST's coverage).
    picker_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectInput:
    info: dict[str, Any]
    parts: list[PartInput]
    notes: dict[str, list[str]]
