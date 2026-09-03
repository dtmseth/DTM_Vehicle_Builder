from __future__ import annotations

"""Config migrations — applied before validation, each migration is idempotent."""


_HISTORICAL_VEHICLE_PLACEHOLDERS = {
    "BLAZER EV": ("Chevrolet", "Blazer EV", ["Blazer EV"], "PIU"),
    "EXPEDITION": ("Ford", "Expedition", ["Expedition"], "PIU"),
    "F-150 LIGHTNING": ("Ford", "F-150 Lightning", ["F-150 Lightning", "Lightning"], "F-150"),
    "F-550": ("Ford", "F-550", ["F550"], "F-150"),
    "HARLEY": ("Harley-Davidson", "Motorcycle", ["Harley", "Harley-Davidson"], "PIU"),
    "JEEP": ("Jeep", "Model pending", ["Jeep"], "PIU"),
    "MACH-E": ("Ford", "Mustang Mach-E", ["Mach-E", "Mustang Mach-E"], "PIU"),
    "RAM 1500": ("Ram", "1500", ["Ram 1500"], "F-150"),
    "SILVERADO": ("Chevrolet", "Silverado", ["Silverado"], "F-150"),
    "SILVERADO 3500": ("Chevrolet", "Silverado 3500", ["3500", "Chevy 3500", "Silverado 3500"], "F-150"),
    "VAN": ("", "Van", ["Van"], "PIU"),
}


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


def _migrate_historical_vehicle_placeholders(data: dict) -> dict:
    """Forward-merge assignable historical models into older shared configs.

    SharePoint may still hold the pre-feature layout file when a newly built
    app first starts.  Adding only absent keys prevents that cloud mirror from
    temporarily hiding these models, while preserving every later user-edited
    definition under the same canonical ID.
    """
    vehicles = data.setdefault("vehicles", {})
    if not {"PIU", "F-150"}.issubset(vehicles):
        return data
    for vehicle_id, (make, model, aliases, layout_source) in _HISTORICAL_VEHICLE_PLACEHOLDERS.items():
        vehicles.setdefault(vehicle_id, {
            "make": make,
            "model": model,
            "aliases": list(aliases),
            "layout_source": layout_source,
            "placeholder": True,
        })
    return data


_MIGRATIONS: dict[str, list] = {
    "vehicle_layouts.json": [
        _migrate_vehicle_layouts_spacing,
        _migrate_historical_vehicle_placeholders,
    ],
    # parts_db.json starts at schema_version 1; no migrations registered yet.
    # Hook point for future field changes (Phase 5 light naming, etc.).
    "parts_db.json": [],
    "legacy_workbook_index.json": [],
    "estimate_charges.json": [],
}


def migrate(filename: str, data: dict) -> dict:
    """Apply all registered migrations for filename, in order. Returns modified data."""
    for fn in _MIGRATIONS.get(filename, []):
        data = fn(data)
    return data
