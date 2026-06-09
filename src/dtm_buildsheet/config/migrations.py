from __future__ import annotations

"""Config migrations — applied before validation, each migration is idempotent."""


def _migrate_vehicle_layouts_spacing(data: dict) -> dict:
    """Rename legacy 'spacing' key to 'h_spacing' in all location/fixture entries."""
    for vehicle in data.get("vehicles", {}).values():
        for view in vehicle.get("views", {}).values():
            for loc in view.get("locations", {}).values():
                if isinstance(loc, dict):
                    if "spacing" in loc and "h_spacing" not in loc:
                        loc["h_spacing"] = loc.pop("spacing")
                    elif "spacing" in loc:
                        loc.pop("spacing")
        for fix_views in vehicle.get("fixtures", {}).values():
            for fix_entry in fix_views.values():
                if isinstance(fix_entry, dict):
                    if "spacing" in fix_entry and "h_spacing" not in fix_entry:
                        fix_entry["h_spacing"] = fix_entry.pop("spacing")
                    elif "spacing" in fix_entry:
                        fix_entry.pop("spacing")
    return data


_MIGRATIONS: dict[str, list] = {
    "vehicle_layouts.json": [_migrate_vehicle_layouts_spacing],
    # parts_db.json starts at schema_version 1; no migrations registered yet.
    # Hook point for future field changes (Phase 5 light naming, etc.).
    "parts_db.json": [],
}


def migrate(filename: str, data: dict) -> dict:
    """Apply all registered migrations for filename, in order. Returns modified data."""
    for fn in _MIGRATIONS.get(filename, []):
        data = fn(data)
    return data
