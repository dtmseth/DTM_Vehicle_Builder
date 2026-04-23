from __future__ import annotations

from dataclasses import dataclass

from .config_store import load_config
from .paths import AppPaths, ensure_workspace


@dataclass
class ConfigBundle:
    paths: AppPaths
    part_catalog: dict
    vehicle_layouts: dict
    asset_manifest: dict
    parts_by_name: dict[str, dict]
    parts_by_id: dict[str, dict]
    parts_lib_by_model: dict[str, dict]


def load_configs(paths: AppPaths | None = None) -> ConfigBundle:
    active_paths = paths or ensure_workspace()
    part_catalog = load_config("part_catalog.json", active_paths)
    vehicle_layouts = load_config("vehicle_layouts.json", active_paths)
    asset_manifest = load_config("asset_manifest.json", active_paths)
    parts_library = load_config("parts_library.json", active_paths)

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

    return ConfigBundle(
        paths=active_paths,
        part_catalog=part_catalog,
        vehicle_layouts=vehicle_layouts,
        asset_manifest=asset_manifest,
        parts_by_name=parts_by_name,
        parts_by_id=parts_by_id,
        parts_lib_by_model=parts_lib_by_model,
    )
