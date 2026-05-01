from __future__ import annotations

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


def resolve_normal_location(
    part, spec: dict, view: str, view_config: dict
) -> tuple[dict | None, str]:
    """Look up a part's location in view_config.

    Returns (location_dict, location_key).  location_dict is None when the
    location is missing or not found in the view.
    """
    location_key = canonical_name(
        part.location or spec.get("default_location_key", "")
    ).strip().upper()
    if not location_key:
        return None, location_key
    raw_loc = view_config.get("locations", {}).get(location_key)
    if raw_loc is None:
        return None, location_key
    return normalize_location(raw_loc, view_config), location_key
