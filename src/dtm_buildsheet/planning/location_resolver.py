from __future__ import annotations

import math

from ..naming import canonical_name


def normalize_location(loc_dict: dict, view_config: dict) -> dict:
    """Normalise a location/fixture entry, migrating legacy 'spacing' → 'h_spacing'."""
    loc = dict(loc_dict)
    if "h_spacing" not in loc and "spacing" in loc:
        loc["h_spacing"] = loc.pop("spacing")
    elif "spacing" in loc:
        loc.pop("spacing")
    if "units" not in loc:
        loc["units"] = view_config.get("coord_space", "relative_image")
    return loc


def apply_co_part_rules(spec: dict, present_part_names: set[str]) -> dict:
    """Merge co_part_rules overrides (pattern, side, asset_key, skip, …)."""
    overrides: dict = {}
    for rule in spec.get("co_part_rules", []):
        co = rule.get("co_part", "")
        present = co in present_part_names
        branch = rule.get("if_present" if present else "if_absent", {})
        overrides.update(branch)
    return overrides


def resolved_location_key(part, spec: dict) -> str:
    """Return the renderable location key for a part.

    A picker custom location keeps the shop-facing name on ``part.location``
    while optionally recording a chosen vehicle dot separately. This preserves
    the custom manifest wording without asking the renderer to invent a
    coordinate when no render placement was selected.
    """
    picker_config = getattr(part, "picker_config", {}) or {}
    custom = picker_config.get("custom_location") if isinstance(picker_config, dict) else None
    render_location = custom.get("render_location", "") if isinstance(custom, dict) else ""
    # A named custom location is valid without a diagram anchor.  In that
    # case, do not mistake the shop-facing text for a layout location and
    # invent a render placement from it.
    if isinstance(custom, dict):
        return canonical_name(render_location).strip().upper()
    return canonical_name(
        part.location or spec.get("default_location_key", "")
    ).strip().upper()


def custom_location_points(part) -> dict[str, list[dict]]:
    """Return validated free-placement points saved by the picker, by view."""
    picker_config = getattr(part, "picker_config", {}) or {}
    custom = picker_config.get("custom_location") if isinstance(picker_config, dict) else None
    raw = custom.get("placements") if isinstance(custom, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[dict[str, float]]] = {}
    for view, points in raw.items():
        if not isinstance(view, str) or not isinstance(points, list):
            continue
        cleaned: list[dict] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            try:
                x, y = float(point.get("x")), float(point.get("y"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1:
                clean: dict = {"x": x, "y": y}
                head_index = point.get("head_index")
                if isinstance(head_index, int) and not isinstance(head_index, bool) and head_index >= 0:
                    clean["head_index"] = head_index
                group_id = point.get("group_id")
                if isinstance(group_id, str) and group_id.strip():
                    clean["group_id"] = group_id.strip()[:40]
                cleaned.append(clean)
        if cleaned:
            out[view.lower()] = cleaned
    return out


def custom_location_has_no_render_placement(part) -> bool:
    """Whether a named custom location is intentionally manifest-only.

    The picker may save a shop-specific location without selecting a saved
    vehicle dot or free point. That is a valid part line, not an unplaceable
    render request.
    """
    picker_config = getattr(part, "picker_config", {}) or {}
    custom = picker_config.get("custom_location") if isinstance(picker_config, dict) else None
    if not isinstance(custom, dict):
        return False
    return (
        bool(str(custom.get("label") or getattr(part, "location", "")).strip())
        and not str(custom.get("render_location") or "").strip()
        and not custom_location_points(part)
    )


def resolve_normal_location(
    part, spec: dict, view: str, view_config: dict
) -> tuple[dict | None, str]:
    """Look up a part's location in view_config.

    Returns (location_dict, location_key).  location_dict is None when the
    location is missing or not found in the view.
    """
    location_key = resolved_location_key(part, spec)
    if not location_key:
        return None, location_key
    raw_loc = view_config.get("locations", {}).get(location_key)
    if raw_loc is None:
        return None, location_key
    return normalize_location(raw_loc, view_config), location_key
