from __future__ import annotations

from dataclasses import dataclass, field

from ..paths import AppPaths, ensure_workspace
from .store import load_config


@dataclass
class ConfigBundle:
    paths: AppPaths
    part_catalog: dict
    vehicle_layouts: dict
    asset_manifest: dict
    build_rules: dict
    parts_by_name: dict[str, dict]
    parts_by_id: dict[str, dict]
    parts_lib_by_model: dict[str, dict]
    config_warnings: list[str] = field(default_factory=list)


def _cross_reference_warnings(
    part_catalog: dict,
    vehicle_layouts: dict,
    asset_manifest: dict,
    paths: AppPaths,
) -> list[str]:
    """Return a list of cross-file consistency warnings (non-fatal)."""
    warnings: list[str] = []

    known_views: set[str] = set()
    for vehicle in vehicle_layouts.get("vehicles", {}).values():
        known_views.update(vehicle.get("views", {}).keys())

    fixture_ids_by_vehicle: dict[str, set[str]] = {}
    for vtype, vehicle in vehicle_layouts.get("vehicles", {}).items():
        fixture_ids_by_vehicle[vtype] = set(vehicle.get("fixtures", {}).keys())
    all_fixture_ids = {fid for ids in fixture_ids_by_vehicle.values() for fid in ids}

    known_profile_ids = set(asset_manifest.get("color_profiles", {}).keys())

    catalog_part_ids: set[str] = set()
    for spec in part_catalog.get("parts", []):
        part_id = spec["part_id"]
        catalog_part_ids.add(part_id)

        # default_views should exist in at least one vehicle's view set
        for view in spec.get("default_views", []):
            if view not in known_views:
                warnings.append(
                    f"part_catalog '{part_id}': default_view '{view}' not found in any vehicle layout"
                )

        # fixture IDs in vehicle_layouts should exist in catalog
        # (checked from the other direction below)

        # color profile reference
        profile = spec.get("default_color_profile", "")
        if profile and profile not in known_profile_ids:
            warnings.append(
                f"part_catalog '{part_id}': default_color_profile '{profile}' not found in asset_manifest"
            )

    # Fixture IDs in vehicle_layouts should have a matching part in catalog
    for fid in all_fixture_ids:
        if fid not in catalog_part_ids:
            warnings.append(
                f"vehicle_layouts fixture '{fid}' has no matching part_id in part_catalog"
            )

    # Asset files referenced in equipment_assets and bar_assets should exist on disk
    assets_dir = paths.workspace_assets_dir
    for asset_key, views in asset_manifest.get("equipment_assets", {}).items():
        for view, rel_path in views.items():
            if rel_path and not (assets_dir / rel_path).exists():
                warnings.append(
                    f"asset_manifest equipment_assets['{asset_key}']['{view}']: "
                    f"file not found: {rel_path}"
                )
    for asset_key, views in asset_manifest.get("bar_assets", {}).items():
        for view, rel_path in views.items():
            if rel_path and not (assets_dir / rel_path).exists():
                warnings.append(
                    f"asset_manifest bar_assets['{asset_key}']['{view}']: "
                    f"file not found: {rel_path}"
                )

    return warnings


def _load_build_rules(paths: AppPaths) -> dict:
    """Load build_rules.json; fall back to empty rules if the file is missing."""
    try:
        return load_config("build_rules.json", paths)
    except FileNotFoundError:
        return {"schema_version": 1, "rules": {}}


def load_configs(paths: AppPaths | None = None) -> ConfigBundle:
    active_paths = paths or ensure_workspace()
    part_catalog = load_config("part_catalog.json", active_paths)
    vehicle_layouts = load_config("vehicle_layouts.json", active_paths)
    asset_manifest = load_config("asset_manifest.json", active_paths)
    parts_library = load_config("parts_library.json", active_paths)
    build_rules = _load_build_rules(active_paths)

    parts_by_name: dict[str, dict] = {}
    parts_by_id: dict[str, dict] = {}
    for spec in part_catalog.get("parts", []):
        parts_by_id[spec["part_id"]] = spec
        parts_by_name[spec["display_name"].strip().upper()] = spec
        for alias in spec.get("aliases", []):
            parts_by_name[alias.strip().upper()] = spec

    parts_lib_by_model: dict[str, dict] = {}
    for entry in parts_library.get("parts", []):
        model = (entry.get("model_number") or "").strip().upper()
        if model:
            parts_lib_by_model[model] = entry

    config_warnings = _cross_reference_warnings(
        part_catalog, vehicle_layouts, asset_manifest, active_paths
    )

    return ConfigBundle(
        paths=active_paths,
        part_catalog=part_catalog,
        vehicle_layouts=vehicle_layouts,
        asset_manifest=asset_manifest,
        build_rules=build_rules,
        parts_by_name=parts_by_name,
        parts_by_id=parts_by_id,
        parts_lib_by_model=parts_lib_by_model,
        config_warnings=config_warnings,
    )
