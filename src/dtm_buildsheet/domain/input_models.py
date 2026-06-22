from __future__ import annotations

from dataclasses import dataclass
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
    line_id: str = ""


@dataclass
class ProjectInput:
    info: dict[str, Any]
    parts: list[PartInput]
    notes: dict[str, list[str]]
