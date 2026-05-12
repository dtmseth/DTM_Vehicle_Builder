"""Convert a GUI form submission dict into a ProjectInput.

The form payload mirrors the field names in ProjectInput / PartInput so the
planner does not need to know whether the data came from Excel or the GUI.

Expected top-level keys
-----------------------
vehicle_type      str   e.g. "TAHOE", "PIU"
agency            str
quote_number      str
sales_rep         str
primary_contact   str
phone             str
email             str
additional_info   str
new_vehicle       dict  keys matching vehicle field names (UNIT ID, VIN, …)
existing_vehicle  dict  same
parts             list  of part-entry dicts (see PartInput fields)
notes             dict  category → list of str  (keys match NOTES_CATEGORIES in ppt_helpers)
"""
from __future__ import annotations

from typing import Any

from ..domain.input_models import PartInput, ProjectInput
from ..naming import canonical_name, safe_project_id


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    text = _s(v).lower()
    return text not in {"n", "no", "false", "0", "off", ""}


def project_input_from_form(data: dict[str, Any]) -> ProjectInput:
    """Build a ProjectInput from a GUI form submission dict."""
    new_vehicle: dict[str, str] = {k: _s(v) for k, v in data.get("new_vehicle", {}).items()}
    existing_vehicle: dict[str, str] = {k: _s(v) for k, v in data.get("existing_vehicle", {}).items()}

    vehicle_type = _s(data.get("vehicle_type", "")).upper()
    if not vehicle_type:
        model = new_vehicle.get("MODEL", existing_vehicle.get("MODEL", "")).upper()
        if "PIU" in model or "UTILITY" in model:
            vehicle_type = "PIU"
        elif "TAHOE" in model:
            vehicle_type = "TAHOE"
        elif "DURANGO" in model:
            vehicle_type = "DURANGO"
        elif "CHARGER" in model:
            vehicle_type = "CHARGER"
        else:
            vehicle_type = model.replace(" ", "_")[:24] or "UNKNOWN"

    raw_id = _s(data.get("quote_number", "")) or _s(data.get("agency", "Project"))
    info: dict[str, Any] = {
        "Agency": _s(data.get("agency", "")),
        "PrimaryContact": _s(data.get("primary_contact", "")),
        "Phone": _s(data.get("phone", "")),
        "Email": _s(data.get("email", "")),
        "SalesRep": _s(data.get("sales_rep", "")),
        "QuoteNumber": _s(data.get("quote_number", "")),
        "AdditionalInfo": _s(data.get("additional_info", "")),
        "NewVehicle": new_vehicle,
        "ExistingVehicle": existing_vehicle,
        "VehicleType": vehicle_type,
        "ProjectID": safe_project_id(raw_id, fallback="PROJECT"),
    }

    parts: list[PartInput] = []
    for entry in data.get("parts", []):
        name = canonical_name(_s(entry.get("name", "")))
        if not name:
            continue
        parts.append(
            PartInput(
                name=name,
                include=_bool(entry.get("include", True)),
                new_or_used=_s(entry.get("new_or_used", "")),
                source=_s(entry.get("source", "")),
                manufacturer=_s(entry.get("manufacturer", "")),
                part_number=_s(entry.get("part_number", "")),
                location=canonical_name(_s(entry.get("location", ""))),
                raw_color=_s(entry.get("raw_color", "") or entry.get("color", "")),
                quantity=_int(entry.get("quantity", 0) or entry.get("qty", 0)),
                lens=_s(entry.get("lens", "")),
                notes=_s(entry.get("notes", "")),
                explicit_color_profile=_s(entry.get("explicit_color_profile", "")),
                driver_color=_s(entry.get("driver_color", "")),
                passenger_color=_s(entry.get("passenger_color", "")),
                center_color=_s(entry.get("center_color", "")),
            )
        )

    raw_notes = data.get("notes", {})
    if isinstance(raw_notes, dict):
        notes: dict[str, list[str]] = {
            k: [_s(n) for n in v if _s(n)]
            for k, v in raw_notes.items()
            if isinstance(v, list)
        }
    else:
        notes = {}
    return ProjectInput(info=info, parts=parts, notes=notes)
