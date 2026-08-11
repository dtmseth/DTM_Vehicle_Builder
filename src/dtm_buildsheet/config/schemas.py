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
    # [shared-settings, Phase 3] — canonical parts database. Direct-mirrored
    # to SharePoint on save (alongside the proposal pipeline). Workbook /
    # parts_library / vehicle_layouts remain as dual-read fallbacks during
    # the transition; see app/services/parts_db_service.py.
    "parts_db.json",
    # [shared-settings, Phase 3] — transition layer mapping legacy workbook
    # part-type strings + model strings to product_ids. Lets manifest_editor
    # and excel_reader find products by their old workbook identifiers
    # without polluting the canonical product records. Throwaway when the
    # workbook input path retires.
    "legacy_workbook_index.json",
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

    definitions = normalized.get("size_rule_definitions", {})
    if not isinstance(definitions, dict):
        raise ValueError("asset_manifest.json size_rule_definitions must be an object")
    for profile_id, profile in definitions.items():
        if not isinstance(profile, dict):
            raise ValueError(f"asset_manifest.json size profile '{profile_id}' must be an object")
        views = profile.get("views", {})
        if not isinstance(views, dict):
            raise ValueError(f"asset_manifest.json size profile '{profile_id}' views must be an object")
        for view, dimensions in views.items():
            if not isinstance(dimensions, dict) or not all(key in dimensions for key in ("w", "h")):
                raise ValueError(
                    f"asset_manifest.json size profile '{profile_id}' view '{view}' must contain w and h"
                )

    size_rules = normalized.get("part_number_size_rules", {})
    if not isinstance(size_rules, dict):
        raise ValueError("asset_manifest.json part_number_size_rules must be an object")
    if not all(isinstance(value, str) for value in size_rules.values()):
        raise ValueError("asset_manifest.json part_number_size_rules values must be profile IDs")


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
    dismissed = normalized.setdefault("dismissed_update_versions", [])
    if not isinstance(dismissed, list) or not all(isinstance(v, str) for v in dismissed):
        raise ValueError(
            "app_settings.json 'dismissed_update_versions' must be a list of strings"
        )


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


_PARTS_DB_REQUIRED_TOP_KEYS = (
    "types",
    "sections",
    "zones",
    "sub_zones",
    "build_attributes",
    "tags",
    "manufacturers",
    "products",
    "part_types",
    "placements",
    "placement_zones",
    "services",
    "system_cable_refreshes",
    "preference_filters",
    "color_palette",
    "naming_rules",
)
_PRODUCT_REQUIRED_KEYS = ("manufacturer_id", "model")
_PART_TYPE_REQUIRED_KEYS = ("label", "type_id")
_FAMILY_REQUIRED_KEYS = ("label", "category", "members")


def _validate_parts_db(normalized: dict) -> None:
    """Phase 3 validator (schema v2): tree-based + intersection rule format.

    Top-level shape + per-product / per-part-type required keys. Deep
    validation (every type_id resolves, every tree_positions.zone exists,
    every part_number is unique) deferred to Phase 4 when users edit
    parts_db through the UI.
    """
    normalized.setdefault("schema_version", 2)
    for key in _PARTS_DB_REQUIRED_TOP_KEYS:
        normalized.setdefault(key, {})

    products = normalized.get("products")
    if not isinstance(products, dict):
        raise ValueError("parts_db.json 'products' must be an object keyed by product_id")

    customer_pricing = normalized.get("customer_pricing")
    if customer_pricing is not None:
        if not isinstance(customer_pricing, dict):
            raise ValueError("parts_db.json customer_pricing must be an object")
        default_rule = customer_pricing.get("default_rule")
        if not isinstance(default_rule, dict):
            raise ValueError("parts_db.json customer_pricing.default_rule must be an object")
        if not isinstance(default_rule.get("name"), str) or not default_rule["name"].strip():
            raise ValueError("parts_db.json customer_pricing.default_rule requires a name")
        discounts = default_rule.get("manufacturer_discounts")
        if not isinstance(discounts, dict) or not discounts:
            raise ValueError("parts_db.json customer_pricing.default_rule requires manufacturer_discounts")
        manufacturers = normalized.get("manufacturers") or {}
        for manufacturer_id, discount in discounts.items():
            if manufacturer_id not in manufacturers:
                raise ValueError(
                    f"parts_db.json customer pricing references unknown manufacturer '{manufacturer_id}'"
                )
            if isinstance(discount, bool) or not isinstance(discount, (int, float)) or not 0 <= discount <= 100:
                raise ValueError(
                    f"parts_db.json customer pricing discount for '{manufacturer_id}' must be 0 through 100"
                )

    for product_id, spec in products.items():
        if not isinstance(spec, dict):
            raise ValueError(f"parts_db.json product '{product_id}' must be an object")
        for key in _PRODUCT_REQUIRED_KEYS:
            if key not in spec:
                raise ValueError(
                    f"parts_db.json product '{product_id}' missing '{key}'"
                )
        part_numbers = spec.get("part_numbers", [])
        if not isinstance(part_numbers, list):
            raise ValueError(
                f"parts_db.json product '{product_id}' 'part_numbers' must be a list"
            )
        for idx, pn in enumerate(part_numbers):
            if not isinstance(pn, dict):
                raise ValueError(
                    f"parts_db.json product '{product_id}' part_numbers[{idx}] must be an object"
                )
            if "part_number" not in pn:
                raise ValueError(
                    f"parts_db.json product '{product_id}' part_numbers[{idx}] missing 'part_number'"
                )
            if "size_rule_id" in pn and not isinstance(pn["size_rule_id"], str):
                raise ValueError(
                    f"parts_db.json product '{product_id}' part_numbers[{idx}] size_rule_id must be a string"
                )
        render = spec.get("render")
        if render is not None:
            if not isinstance(render, dict):
                raise ValueError(f"parts_db.json product '{product_id}' render must be an object")
            if "size_rule_id" in render and not isinstance(render["size_rule_id"], str):
                raise ValueError(f"parts_db.json product '{product_id}' render.size_rule_id must be a string")
            if (
                "center_single_at_mirror_location" in render
                and not isinstance(render["center_single_at_mirror_location"], bool)
            ):
                raise ValueError(
                    f"parts_db.json product '{product_id}' render.center_single_at_mirror_location must be a boolean"
                )
        aliases = spec.get("model_aliases")
        if aliases is not None and not (
            isinstance(aliases, list) and all(isinstance(alias, str) and alias.strip() for alias in aliases)
        ):
            raise ValueError(
                f"parts_db.json product '{product_id}' model_aliases must be a list of non-empty strings"
            )
        fits = spec.get("fits_part_types", [])
        if not isinstance(fits, list):
            raise ValueError(
                f"parts_db.json product '{product_id}' 'fits_part_types' must be a list"
            )
        for field in ("picker_primary_part_type", "global_search_part_type"):
            picker_primary_part_type = spec.get(field)
            if picker_primary_part_type is not None and (
                not isinstance(picker_primary_part_type, str)
                or picker_primary_part_type not in fits
            ):
                raise ValueError(
                    f"parts_db.json product '{product_id}' '{field}' "
                    "must be a part type listed in 'fits_part_types'"
                )
        location_options = spec.get("location_options")
        if location_options is not None and not (
            isinstance(location_options, list) and all(isinstance(x, str) for x in location_options)
        ):
            raise ValueError(
                f"parts_db.json product '{product_id}' 'location_options' must be a list of strings"
            )
        fixed_location = spec.get("fixed_location")
        if fixed_location is not None and not isinstance(fixed_location, str):
            raise ValueError(
                f"parts_db.json product '{product_id}' 'fixed_location' must be a string"
            )
        for field in ("allow_custom_location", "pa_mic_required"):
            value = spec.get(field)
            if value is not None and not isinstance(value, bool):
                raise ValueError(
                    f"parts_db.json product '{product_id}' '{field}' must be a boolean"
                )
        default_colors = spec.get("default_colors")
        if default_colors is not None and not (
            isinstance(default_colors, list) and all(isinstance(x, str) for x in default_colors)
        ):
            raise ValueError(
                f"parts_db.json product '{product_id}' 'default_colors' must be a list of strings"
            )
        accessories_disabled = spec.get("accessories_disabled")
        if accessories_disabled is not None and not isinstance(accessories_disabled, bool):
            raise ValueError(
                f"parts_db.json product '{product_id}' 'accessories_disabled' must be a boolean"
            )
        console_kit = spec.get("console_kit")
        if console_kit is not None:
            if not isinstance(console_kit, dict):
                raise ValueError(
                    f"parts_db.json product '{product_id}' 'console_kit' must be an object"
                )
            if not isinstance(console_kit.get("style", ""), str) or not console_kit.get("style", "").strip():
                raise ValueError(
                    f"parts_db.json product '{product_id}' console_kit requires a non-empty 'style'"
                )
            if not isinstance(console_kit.get("included", {}), dict):
                raise ValueError(
                    f"parts_db.json product '{product_id}' console_kit 'included' must be an object"
                )

    # Guided radio/radar/camera cable-refresh choices are intentionally
    # authored separately from the product browse tree.  Each choice must
    # resolve to a live QB-linked SKU so selecting a refresh creates a billable
    # estimate line rather than a descriptive, unpriced manifest note.
    cable_refreshes = normalized.get("system_cable_refreshes")
    if not isinstance(cable_refreshes, dict):
        raise ValueError("parts_db.json 'system_cable_refreshes' must be an object")
    for system_id, entries in cable_refreshes.items():
        if system_id not in {"radio", "radar", "camera"}:
            raise ValueError(
                f"parts_db.json system_cable_refreshes has unknown system '{system_id}'"
            )
        if not isinstance(entries, list):
            raise ValueError(
                f"parts_db.json system_cable_refreshes '{system_id}' must be a list"
            )
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] must be an object"
                )
            for key in ("id", "label", "part_type", "billing_options"):
                if key not in entry:
                    raise ValueError(
                        f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] missing '{key}'"
                    )
            if not isinstance(entry["id"], str) or not entry["id"].strip():
                raise ValueError(
                    f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] requires a non-empty id"
                )
            if not isinstance(entry["label"], str) or not entry["label"].strip():
                raise ValueError(
                    f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] requires a non-empty label"
                )
            if not isinstance(entry["part_type"], str) or not entry["part_type"].strip():
                raise ValueError(
                    f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] requires a part_type"
                )
            if "billing_once" in entry and not isinstance(entry["billing_once"], bool):
                raise ValueError(
                    f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] billing_once must be a boolean"
                )
            options = entry["billing_options"]
            if not isinstance(options, list) or not options:
                raise ValueError(
                    f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] requires billing_options"
                )
            for opt_idx, option in enumerate(options):
                if not isinstance(option, dict):
                    raise ValueError(
                        f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] billing_options[{opt_idx}] must be an object"
                    )
                product_id = option.get("product_id")
                part_number = option.get("part_number")
                if not isinstance(product_id, str) or not product_id or not isinstance(part_number, str) or not part_number:
                    raise ValueError(
                        f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] billing_options[{opt_idx}] requires product_id and part_number"
                    )
                product = products.get(product_id)
                if not product:
                    raise ValueError(
                        f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] references unknown product '{product_id}'"
                    )
                sku = next((pn for pn in (product.get("part_numbers") or [])
                            if pn.get("part_number") == part_number), None)
                if not sku:
                    raise ValueError(
                        f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] references unknown SKU '{part_number}'"
                    )
                if not sku.get("qb_item_id") or sku.get("qb_inactive"):
                    raise ValueError(
                        f"parts_db.json system_cable_refreshes '{system_id}'[{idx}] SKU '{part_number}' must be live and QB-linked"
                    )

    # Optional families collection (browse-time grouping, orthogonal to type_id/
    # zone/section — see docs/audit/PART_TYPE_TAXONOMY_PROPOSAL.md). Additive: absent
    # entirely on older parts_db.json, so this block is skipped when the key is missing.
    families = normalized.get("families")
    if families is not None:
        if not isinstance(families, dict):
            raise ValueError("parts_db.json 'families' must be an object keyed by family_id")
        for family_id, spec in families.items():
            if not isinstance(spec, dict):
                raise ValueError(f"parts_db.json family '{family_id}' must be an object")
            for key in _FAMILY_REQUIRED_KEYS:
                if key not in spec:
                    raise ValueError(f"parts_db.json family '{family_id}' missing '{key}'")
            members = spec.get("members")
            if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
                raise ValueError(
                    f"parts_db.json family '{family_id}' 'members' must be a list of part_type_id strings"
                )
            picker_part_label = spec.get("picker_part_label")
            if picker_part_label is not None and not isinstance(picker_part_label, str):
                raise ValueError(
                    f"parts_db.json family '{family_id}' 'picker_part_label' must be a string"
                )
            fixed_location = spec.get("fixed_location")
            if fixed_location is not None and not isinstance(fixed_location, str):
                raise ValueError(
                    f"parts_db.json family '{family_id}' 'fixed_location' must be a string"
                )

    manifest_groups = normalized.get("manifest_groups")
    if manifest_groups is not None:
        if not isinstance(manifest_groups, dict):
            raise ValueError("parts_db.json 'manifest_groups' must be an object")
        groups = manifest_groups.get("groups", [])
        if not isinstance(groups, list):
            raise ValueError("parts_db.json manifest_groups.groups must be a list")
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("parts_db.json manifest_groups.groups entries must be objects")
            for key in ("group_id", "label"):
                if not isinstance(group.get(key), str) or not group.get(key):
                    raise ValueError(f"parts_db.json manifest group missing string '{key}'")
            subgroups = group.get("subgroups", [])
            if subgroups is not None and not isinstance(subgroups, list):
                raise ValueError("parts_db.json manifest group subgroups must be a list")
            for subgroup in subgroups or []:
                if not isinstance(subgroup, dict):
                    raise ValueError("parts_db.json manifest subgroup entries must be objects")
                for key in ("subgroup_id", "label"):
                    if not isinstance(subgroup.get(key), str) or not subgroup.get(key):
                        raise ValueError(f"parts_db.json manifest subgroup missing string '{key}'")

    part_types = normalized.get("part_types")
    if not isinstance(part_types, dict):
        raise ValueError("parts_db.json 'part_types' must be an object keyed by part_type_id")

    for pt_id, spec in part_types.items():
        if not isinstance(spec, dict):
            raise ValueError(f"parts_db.json part_type '{pt_id}' must be an object")
        for key in _PART_TYPE_REQUIRED_KEYS:
            if key not in spec:
                raise ValueError(f"parts_db.json part_type '{pt_id}' missing '{key}'")
        positions = spec.get("tree_positions", [])
        if not isinstance(positions, list):
            raise ValueError(
                f"parts_db.json part_type '{pt_id}' 'tree_positions' must be a list"
            )
        for idx, pos in enumerate(positions):
            if not isinstance(pos, dict):
                raise ValueError(
                    f"parts_db.json part_type '{pt_id}' tree_positions[{idx}] must be an object"
                )
            for k in ("section", "zone"):
                if k not in pos:
                    raise ValueError(
                        f"parts_db.json part_type '{pt_id}' tree_positions[{idx}] missing '{k}'"
                    )
        # Optional location model (per-part-type, see docs/PARTS_DB_AND_PICKER.md):
        # location_mode is 'placement' (visual, coordinate-driven — lights/bumpers)
        # or 'text' (a curated pick-list of mount locations — interior/equipment).
        lmode = spec.get("location_mode")
        if lmode is not None and lmode not in ("placement", "text"):
            raise ValueError(
                f"parts_db.json part_type '{pt_id}' location_mode must be "
                f"'placement' or 'text' (got {lmode!r})"
            )
        lopts = spec.get("location_options")
        if lopts is not None and not (
            isinstance(lopts, list) and all(isinstance(x, str) for x in lopts)
        ):
            raise ValueError(
                f"parts_db.json part_type '{pt_id}' location_options must be a list of strings"
            )
        recommendations = spec.get("recommended_accessories")
        if recommendations is not None:
            if not isinstance(recommendations, list):
                raise ValueError(
                    f"parts_db.json part_type '{pt_id}' recommended_accessories must be a list"
                )
            for idx, recommendation in enumerate(recommendations):
                if not isinstance(recommendation, dict):
                    raise ValueError(
                        f"parts_db.json part_type '{pt_id}' recommended_accessories[{idx}] must be an object"
                    )
                for key in ("category", "product_id", "when_existing_part_type", "message"):
                    value = recommendation.get(key)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(
                            f"parts_db.json part_type '{pt_id}' recommended_accessories[{idx}] "
                            f"requires a non-empty '{key}'"
                        )
                minimum = recommendation.get("minimum_existing_count")
                if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
                    raise ValueError(
                        f"parts_db.json part_type '{pt_id}' recommended_accessories[{idx}] "
                        "minimum_existing_count must be an integer of at least 1"
                    )
        # Optional family membership (additive; see 'families' above). Kept alongside
        # .category, not in place of it — the picker still reads .category until it
        # migrates to family_id + families[...].picker_flow.
        family_id = spec.get("family_id")
        if family_id is not None and not isinstance(family_id, str):
            raise ValueError(f"parts_db.json part_type '{pt_id}' family_id must be a string")
        render = spec.get("render")
        if render is not None:
            if not isinstance(render, dict):
                raise ValueError(f"parts_db.json part_type '{pt_id}' render must be an object")
            if "size_rule_id" in render and not isinstance(render["size_rule_id"], str):
                raise ValueError(f"parts_db.json part_type '{pt_id}' render.size_rule_id must be a string")
            images = render.get("images")
            if images is not None and not (
                isinstance(images, dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in images.items())
            ):
                raise ValueError(
                    f"parts_db.json part_type '{pt_id}' render.images must be an object of view → asset path"
                )
            sizes = render.get("size_per_view")
            if sizes is not None:
                if not isinstance(sizes, dict):
                    raise ValueError(
                        f"parts_db.json part_type '{pt_id}' render.size_per_view must be an object"
                    )
                for view, size in sizes.items():
                    if not isinstance(view, str) or not isinstance(size, dict):
                        raise ValueError(
                            f"parts_db.json part_type '{pt_id}' render.size_per_view entries must be objects"
                        )
                    if "w" not in size or "h" not in size:
                        raise ValueError(
                            f"parts_db.json part_type '{pt_id}' render.size_per_view['{view}'] missing w/h"
                        )
            qrules = render.get("quantity_rules")
            if qrules is not None and not isinstance(qrules, list):
                raise ValueError(
                    f"parts_db.json part_type '{pt_id}' render.quantity_rules must be a list"
                )
            default_views = render.get("default_views")
            if default_views is not None and not (
                isinstance(default_views, list) and all(isinstance(view, str) for view in default_views)
            ):
                raise ValueError(
                    f"parts_db.json part_type '{pt_id}' render.default_views must be a list of strings"
                )
            is_fixture = render.get("is_fixture")
            if is_fixture is not None and not isinstance(is_fixture, bool):
                raise ValueError(
                    f"parts_db.json part_type '{pt_id}' render.is_fixture must be a boolean"
                )
            quantity_policy = render.get("render_quantity_policy")
            if quantity_policy is not None and quantity_policy not in {
                "location_slots", "single_per_line", "quantity_as_slots",
            }:
                raise ValueError(
                    f"parts_db.json part_type '{pt_id}' has invalid render.render_quantity_policy "
                    f"{quantity_policy!r}"
                )
            co_part_rules = render.get("co_part_rules")
            if co_part_rules is not None and not isinstance(co_part_rules, list):
                raise ValueError(
                    f"parts_db.json part_type '{pt_id}' render.co_part_rules must be a list"
                )


def _validate_legacy_workbook_index(normalized: dict) -> None:
    """Top-level shape for legacy_workbook_index.json.

    Two maps that must be dicts; values can be anything reasonable
    (lists of strings, individual strings). Deep validation deferred —
    the file is produced by the migration script which does its own
    cross-referencing.
    """
    for key in ("part_type_to_products", "model_string_to_product"):
        normalized.setdefault(key, {})
        if not isinstance(normalized[key], dict):
            raise ValueError(f"legacy_workbook_index.json '{key}' must be an object")


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
    "parts_db.json": _validate_parts_db,
    "legacy_workbook_index.json": _validate_legacy_workbook_index,
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
