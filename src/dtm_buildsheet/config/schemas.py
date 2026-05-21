from __future__ import annotations

"""Per-file schema validation and normalization.

Each validator returns a normalized copy of the data or raises ValueError.
Cross-file validation lives in loader.py (needs all configs at once).
"""

from copy import deepcopy

from ..naming import canonical_name

REQUIRED_CONFIG_FILES = {
    # [shared-settings] — reviewed via PR through the GitHub settings repo in
    # Phase 2. Edits propose a change; the merged result syncs back to every
    # user's app via SharePoint /Settings/.
    "part_catalog.json",
    "vehicle_layouts.json",
    "asset_manifest.json",
    "parts_library.json",
    "workbook_rules.json",
    "build_rules.json",
    "project_options.json",
    # [local-only] — per-machine. Never synced. Holds the user's
    # project_output_root, template_save_dir, etc.
    "app_settings.json",
}

# Phase 2 will partition this set across two roots. Settings flow through
# /Settings/ on SharePoint with PR review; app_settings.json stays on the
# user's disk and is never proposed or synced.
_LOCAL_ONLY_CONFIG_FILES = {"app_settings.json"}

_VALID_RENDER_KINDS = {"light", "bar", "equipment", "none"}
_VALID_CATEGORIES = {
    "warning_light",
    "scene_light",
    "light_bar",
    "audio",
    "equipment",
    "equipment_note",
    "appearance_note",
    "vehicle_system",
}


# ── per-file validators ────────────────────────────────────────────────────────


def _validate_part_catalog(normalized: dict) -> None:
    parts = normalized.get("parts")
    if not isinstance(parts, list):
        raise ValueError("part_catalog.json must contain a 'parts' array")

    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    for spec in parts:
        if not isinstance(spec, dict):
            raise ValueError("part_catalog.json entries must be objects")
        for key in ("part_id", "display_name", "category", "render_kind", "default_views"):
            if key not in spec:
                raise ValueError(f"Catalog entry missing '{key}': {spec.get('part_id', '?')}")

        part_id = spec["part_id"]
        if part_id in seen_ids:
            raise ValueError(f"part_catalog.json duplicate part_id: '{part_id}'")
        seen_ids.add(part_id)

        rk = spec["render_kind"]
        if rk not in _VALID_RENDER_KINDS:
            raise ValueError(
                f"part_catalog.json unknown render_kind '{rk}' on part '{part_id}'. "
                f"Valid: {sorted(_VALID_RENDER_KINDS)}"
            )

        cat = spec["category"]
        if cat not in _VALID_CATEGORIES:
            raise ValueError(
                f"part_catalog.json unknown category '{cat}' on part '{part_id}'. "
                f"Valid: {sorted(_VALID_CATEGORIES)}"
            )

        if not isinstance(spec["default_views"], list):
            raise ValueError(f"part_catalog.json 'default_views' must be a list on '{part_id}'")

        # Normalize display_name and aliases
        spec["display_name"] = canonical_name(str(spec["display_name"]))
        canonical_display = spec["display_name"].strip().upper()
        if canonical_display in seen_names:
            raise ValueError(
                f"part_catalog.json duplicate display_name (after normalization): '{spec['display_name']}'"
            )
        seen_names.add(canonical_display)

        aliases = [canonical_name(str(a)) for a in spec.get("aliases", [])]
        if spec["display_name"] not in aliases:
            spec["aliases"] = sorted(set(aliases + [str(spec["display_name"])]))
        else:
            spec["aliases"] = sorted(set(aliases))


_VALID_VIEW_CATEGORIES   = {"external", "internal"}
_VALID_LEGEND_LAYOUTS    = {"standard", "grid"}
_VALID_LOGO_POSITIONS    = {"top-right", "bottom"}


def _validate_vehicle_layouts(normalized: dict) -> None:
    vehicles = normalized.get("vehicles")
    if not isinstance(vehicles, dict):
        raise ValueError("vehicle_layouts.json must contain a 'vehicles' object")

    for vehicle_type, vehicle in vehicles.items():
        if not isinstance(vehicle, dict):
            raise ValueError(f"vehicle_layouts.json vehicle '{vehicle_type}' must be an object")

        # view_order must be a list of strings when present
        view_order = vehicle.get("view_order")
        if view_order is not None:
            if not isinstance(view_order, list) or not all(isinstance(v, str) for v in view_order):
                raise ValueError(
                    f"vehicle_layouts.json vehicle '{vehicle_type}' view_order must be a list of strings"
                )
            # All view_order entries should reference existing views
            known_views = set(vehicle.get("views", {}).keys())
            for vid in view_order:
                if vid not in known_views:
                    raise ValueError(
                        f"vehicle_layouts.json '{vehicle_type}' view_order references unknown view '{vid}'"
                    )

        for view_name, view in vehicle.get("views", {}).items():
            if not isinstance(view, dict):
                raise ValueError(
                    f"vehicle_layouts.json view '{view_name}' on '{vehicle_type}' must be an object"
                )

            # Validate optional metadata fields
            cat = view.get("category")
            if cat is not None and cat not in _VALID_VIEW_CATEGORIES:
                raise ValueError(
                    f"vehicle_layouts.json '{vehicle_type}/{view_name}' has invalid category '{cat}'. "
                    f"Valid: {sorted(_VALID_VIEW_CATEGORIES)}"
                )
            ll = view.get("legend_layout")
            if ll is not None and ll not in _VALID_LEGEND_LAYOUTS:
                raise ValueError(
                    f"vehicle_layouts.json '{vehicle_type}/{view_name}' has invalid legend_layout '{ll}'. "
                    f"Valid: {sorted(_VALID_LEGEND_LAYOUTS)}"
                )
            lp = view.get("logo_position")
            if lp is not None and lp not in _VALID_LOGO_POSITIONS:
                raise ValueError(
                    f"vehicle_layouts.json '{vehicle_type}/{view_name}' has invalid logo_position '{lp}'. "
                    f"Valid: {sorted(_VALID_LOGO_POSITIONS)}"
                )

            locations = view.get("locations", {})
            fixed_locations: dict = {}
            for name, loc in locations.items():
                key = canonical_name(str(name)).upper()
                if not isinstance(loc, dict):
                    raise ValueError(
                        f"vehicle_layouts.json location '{name}' on {vehicle_type}/{view_name} must be an object"
                    )
                for coord in ("x", "y"):
                    if coord not in loc:
                        raise ValueError(
                            f"vehicle_layouts.json location '{name}' on {vehicle_type}/{view_name} missing '{coord}'"
                        )
                fixed_locations[key] = loc
            view["locations"] = fixed_locations


def _validate_asset_manifest(normalized: dict) -> None:
    if "equipment_assets" not in normalized:
        raise ValueError("asset_manifest.json must contain 'equipment_assets'")
    normalized.setdefault("placeholder_assets", {})

    color_profiles = normalized.get("color_profiles", {})
    for profile_id, profile in color_profiles.items():
        if not isinstance(profile, dict):
            raise ValueError(f"asset_manifest.json color_profile '{profile_id}' must be an object")
        slot_tokens = profile.get("slot_tokens", {})
        if not isinstance(slot_tokens, dict):
            raise ValueError(
                f"asset_manifest.json color_profile '{profile_id}' slot_tokens must be an object"
            )

    light_rule = normalized.get("light_icon_rule", {})
    if light_rule:
        for key in ("subfolder", "filename_pattern"):
            if key not in light_rule:
                raise ValueError(f"asset_manifest.json light_icon_rule missing '{key}'")


def _validate_parts_library(normalized: dict) -> None:
    parts = normalized.get("parts")
    if not isinstance(parts, list):
        raise ValueError("parts_library.json must contain a 'parts' array")
    for entry in parts:
        if not isinstance(entry, dict):
            raise ValueError("parts_library.json entries must be objects")
        compat = entry.get("compatible_types", [])
        entry["compatible_types"] = [canonical_name(str(item)) for item in compat]


def _validate_workbook_rules(normalized: dict) -> None:
    if "template_sections" not in normalized:
        raise ValueError("workbook_rules.json must contain 'template_sections'")
    if not isinstance(normalized["template_sections"], list):
        raise ValueError("workbook_rules.json 'template_sections' must be an array")


def _validate_app_settings(normalized: dict) -> None:
    normalized.setdefault("template_save_dir", "")
    normalized.setdefault("output_save_dir", "")
    normalized.setdefault("project_output_root", "")


_VALID_RULE_SEVERITIES = {"warning", "error"}
_KNOWN_RULE_TYPES = {
    "incompatible_parts",
    "required_dependencies",
    "vehicle_compatibility",
    "location_compatibility",
    "part_groups",
    "presets",
}


def _validate_project_options(normalized: dict) -> None:
    for key in ("build_types", "camera_brands", "lighting_brands", "bumper_brands", "cage_brands"):
        val = normalized.setdefault(key, [])
        if not isinstance(val, list):
            raise ValueError(f"project_options.json '{key}' must be an array")


def _validate_build_rules(normalized: dict) -> None:
    rules = normalized.setdefault("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("build_rules.json 'rules' must be an object")

    for rule_type in rules:
        if rule_type not in _KNOWN_RULE_TYPES:
            raise ValueError(
                f"build_rules.json unknown rule type '{rule_type}'. "
                f"Valid: {sorted(_KNOWN_RULE_TYPES)}"
            )
        entries = rules[rule_type]
        if not isinstance(entries, list):
            raise ValueError(f"build_rules.json rules.{rule_type} must be an array")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"build_rules.json rules.{rule_type} entries must be objects")
            if "rule_id" not in entry and rule_type != "presets":
                raise ValueError(
                    f"build_rules.json rules.{rule_type} entry missing 'rule_id': {entry}"
                )
            sev = entry.get("severity", "warning")
            if sev not in _VALID_RULE_SEVERITIES:
                raise ValueError(
                    f"build_rules.json rule '{entry.get('rule_id', '?')}' has invalid severity "
                    f"'{sev}'. Valid: {sorted(_VALID_RULE_SEVERITIES)}"
                )

    # Ensure all rule-type lists exist (default to empty)
    for rule_type in _KNOWN_RULE_TYPES:
        rules.setdefault(rule_type, [])


_VALIDATORS = {
    "part_catalog.json": _validate_part_catalog,
    "vehicle_layouts.json": _validate_vehicle_layouts,
    "asset_manifest.json": _validate_asset_manifest,
    "parts_library.json": _validate_parts_library,
    "workbook_rules.json": _validate_workbook_rules,
    "app_settings.json": _validate_app_settings,
    "build_rules.json": _validate_build_rules,
    "project_options.json": _validate_project_options,
}


# ── public entry point ─────────────────────────────────────────────────────────


def validate_config_payload(filename: str, data: object) -> dict:
    """Validate and normalize a loaded config dict. Raises ValueError on failure."""
    if not isinstance(data, dict):
        raise ValueError(f"{filename} must contain a JSON object at the top level")

    normalized = deepcopy(data)
    version = normalized.setdefault("schema_version", 1)
    if not isinstance(version, int):
        raise ValueError(f"{filename} schema_version must be an integer")

    validator = _VALIDATORS.get(filename)
    if validator:
        validator(normalized)

    return normalized
