from __future__ import annotations

from .location_resolver import normalize_location


def resolve_fixture_entry(
    spec: dict, view: str, fixtures_map: dict, view_config: dict
) -> tuple[dict | None, str]:
    """Look up a fixture's location entry for a given view.

    Returns (location_dict, location_key).  location_dict is None when the
    fixture has no coords for this view.
    """
    part_id = spec["part_id"]
    location_key = f"FIXTURE:{part_id.upper()}"
    raw_entry = fixtures_map.get(part_id, {}).get(view)
    if raw_entry is None:
        return None, location_key
    return normalize_location(raw_entry, view_config), location_key
