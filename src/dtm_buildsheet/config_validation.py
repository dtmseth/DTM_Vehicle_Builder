from __future__ import annotations

from copy import deepcopy

from .naming import canonical_name


REQUIRED_CONFIG_FILES = {
    "part_catalog.json",
    "vehicle_layouts.json",
    "asset_manifest.json",
    "parts_library.json",
    "workbook_rules.json",
    "app_settings.json",
}


def validate_config_payload(filename: str, data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"{filename} must contain a JSON object at the top level")

    normalized = deepcopy(data)
    version = normalized.setdefault("schema_version", 1)
    if not isinstance(version, int):
        raise ValueError(f"{filename} schema_version must be an integer")

    if filename == "part_catalog.json":
        parts = normalized.get("parts")
        if not isinstance(parts, list):
            raise ValueError("part_catalog.json must contain a 'parts' array")
        for spec in parts:
            if not isinstance(spec, dict):
                raise ValueError("part_catalog.json entries must be objects")
            for key in ("part_id", "display_name", "category", "render_kind", "default_views"):
                if key not in spec:
                    raise ValueError(f"Catalog entry missing '{key}'")
            spec["display_name"] = canonical_name(str(spec["display_name"]))
            aliases = [canonical_name(str(alias)) for alias in spec.get("aliases", [])]
            if spec["display_name"] not in aliases:
                spec["aliases"] = sorted(set(aliases + [str(spec["display_name"])]))
            else:
                spec["aliases"] = sorted(set(aliases))
    elif filename == "vehicle_layouts.json":
        vehicles = normalized.get("vehicles")
        if not isinstance(vehicles, dict):
            raise ValueError("vehicle_layouts.json must contain a 'vehicles' object")
        for vehicle in vehicles.values():
            for view in vehicle.get("views", {}).values():
                locations = view.get("locations", {})
                fixed_locations = {}
                for name, config in locations.items():
                    fixed_locations[canonical_name(str(name)).upper()] = config
                view["locations"] = fixed_locations
    elif filename == "asset_manifest.json":
        if "equipment_assets" not in normalized:
            raise ValueError("asset_manifest.json must contain 'equipment_assets'")
        normalized.setdefault("placeholder_assets", {})
    elif filename == "parts_library.json":
        parts = normalized.get("parts")
        if not isinstance(parts, list):
            raise ValueError("parts_library.json must contain a 'parts' array")
        for entry in parts:
            compat = entry.get("compatible_types", [])
            entry["compatible_types"] = [canonical_name(str(item)) for item in compat]
    elif filename == "workbook_rules.json":
        if "template_sections" not in normalized:
            raise ValueError("workbook_rules.json must contain 'template_sections'")
    elif filename == "app_settings.json":
        normalized.setdefault("template_save_dir", "")

    return normalized
