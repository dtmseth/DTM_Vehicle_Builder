from __future__ import annotations

from pathlib import Path

from .config_loader import ConfigBundle
from .models import BuildPlan, PlannedPart, PlannedPlacement, RenderInstance
from .naming import canonical_name


def _normalize_token(value: str) -> str:
    if not value:
        return ""
    token = value.strip().lower()
    for separator in ["/", " and ", "&", ",", " "]:
        token = token.replace(separator, "-")
    while "--" in token:
        token = token.replace("--", "-")
    return token.strip("-")


_COLOR_PRESETS: dict[str, tuple[str, str] | None] = {
    "blue": ("legacy_uniform", "blue"),
    "white": ("legacy_uniform", "white"),
    "amber": ("legacy_uniform", "amber"),
    "red/blue": ("legacy_uniform", "red-blue"),
    "red and blue": ("duo_r_b", ""),
    "red/white blue/white": ("std_duo_rb_w", ""),
    "red/amber blue/amber": ("duo_ra_ba", ""),
    "single color (specify)": None,
    "dual color (specify)": None,
    "tri color (specify)": None,
}


def _size_class_for_part(part_number: str, asset_manifest: dict) -> str:
    rules = asset_manifest.get("part_number_size_rules", {})
    part_number_upper = part_number.strip().upper()
    if not part_number_upper:
        return "sm"
    if part_number_upper in rules:
        return rules[part_number_upper]
    for key, size_class in rules.items():
        if key.upper() in part_number_upper:
            return size_class
    return "sm"


def _resolve_profile(part, spec: dict, asset_manifest: dict) -> tuple[str, str]:
    color_profiles = asset_manifest.get("color_profiles", {})

    explicit = _normalize_token(part.explicit_color_profile)
    if explicit and explicit in color_profiles:
        return explicit, ""

    if part.raw_color:
        preset_key = part.raw_color.strip().lower()
        if preset_key in _COLOR_PRESETS:
            preset_result = _COLOR_PRESETS[preset_key]
            if preset_result is not None:
                return preset_result
            category = {"single": "single", "dual": "duo", "tri": "trio"}.get(
                preset_key.split()[0],
                "single",
            )
            if part.notes:
                notes_token = _normalize_token(part.notes)
                notes_preset_result = _COLOR_PRESETS.get(part.notes.strip().lower())
                if notes_preset_result is not None:
                    return notes_preset_result
                notes_alias = asset_manifest.get("legacy_color_aliases", {}).get(notes_token, {})
                if "profile" in notes_alias and notes_alias["profile"] in color_profiles:
                    return notes_alias["profile"], notes_token
                if "color_token" in notes_alias:
                    return "legacy_uniform", notes_alias["color_token"]
                if notes_token in asset_manifest.get("light_color_tokens", []):
                    return "legacy_uniform", notes_token
            return "specify_palette", category

    if part.driver_color or part.passenger_color or part.center_color:
        return "custom", ""

    raw_token = _normalize_token(part.raw_color)
    alias = asset_manifest.get("legacy_color_aliases", {}).get(raw_token, {})
    if "profile" in alias and alias["profile"] in color_profiles:
        return alias["profile"], raw_token
    if "color_token" in alias:
        return "legacy_uniform", alias["color_token"]

    if raw_token in asset_manifest.get("light_color_tokens", []):
        return "legacy_uniform", raw_token

    default_profile = spec.get("default_color_profile", "")
    if default_profile and default_profile in color_profiles:
        return default_profile, raw_token

    return "none", raw_token


def _view_side_role(view_config: dict, direction: str) -> str:
    return view_config.get("side_roles", {}).get(direction, "center")


def _build_slot_roles(pattern: str, slot_count: int, view_config: dict) -> list[str]:
    if slot_count <= 1 or pattern == "single":
        return [view_config.get("default_slot_role", "center")]
    if pattern == "mirror":
        if slot_count == 2:
            return [
                _view_side_role(view_config, "negative_x"),
                _view_side_role(view_config, "positive_x"),
            ]
        roles: list[str] = []
        half = slot_count // 2
        roles.extend([_view_side_role(view_config, "negative_x")] * half)
        roles.extend([_view_side_role(view_config, "positive_x")] * half)
        return roles
    if pattern == "horizontal":
        roles: list[str] = []
        middle_left = (slot_count - 1) / 2
        for index in range(slot_count):
            if index < middle_left:
                roles.append(_view_side_role(view_config, "negative_x"))
            elif index > middle_left:
                roles.append(_view_side_role(view_config, "positive_x"))
            else:
                roles.append("center")
        return roles
    return [f"slot_{index + 1}" for index in range(slot_count)]


def _resolve_color_token(profile_id: str, raw_color_token: str, slot_role: str, part, asset_manifest: dict) -> str:
    if profile_id == "none":
        return ""
    if profile_id == "custom":
        role_map = {
            "driver": _normalize_token(part.driver_color),
            "passenger": _normalize_token(part.passenger_color),
            "center": _normalize_token(part.center_color),
        }
        return role_map.get(slot_role) or role_map.get("center") or raw_color_token
    if profile_id == "legacy_uniform":
        return raw_color_token

    profile = asset_manifest.get("color_profiles", {}).get(profile_id, {})
    slot_tokens = profile.get("slot_tokens", {})
    return slot_tokens.get(slot_role) or slot_tokens.get("default") or raw_color_token


def _resolve_asset_path(
    render_kind: str,
    asset_key: str,
    view: str,
    orientation: str,
    color_token: str,
    asset_manifest: dict,
    fallback_images: dict | None = None,
) -> str:
    if render_kind == "equipment":
        if not asset_key:
            return ""
        return asset_manifest.get("equipment_assets", {}).get(asset_key, {}).get(view, "") or (fallback_images or {}).get(view, "")

    if render_kind == "bar":
        if not asset_key:
            return ""
        return asset_manifest.get("bar_assets", {}).get(asset_key, {}).get(view, "") or (fallback_images or {}).get(view, "")

    if render_kind == "light" and color_token:
        if color_token in ("single", "duo", "trio"):
            return ""
        filename = asset_manifest["light_icon_rule"]["filename_pattern"].format(
            color_token=color_token,
            orientation=orientation,
        )
        return f"{asset_manifest['light_icon_rule']['subfolder']}/{filename}"

    return ""


def build_plan(project, config: ConfigBundle) -> BuildPlan:
    manifest = config.asset_manifest
    layouts = config.vehicle_layouts.get("vehicles", {})
    vehicle_type = project.info.get("VehicleType", "PIU")
    vehicle = layouts.get(vehicle_type, {})
    view_map = vehicle.get("views", {})

    planned_parts: list[PlannedPart] = []
    warnings: list[str] = []

    for part in project.parts:
        if not part.include:
            continue

        spec = config.parts_by_name.get(part.name.upper())
        if spec is None:
            planned_parts.append(
                PlannedPart(
                    part_id="unmapped",
                    part_name=part.name,
                    category="unknown",
                    render_kind="none",
                    on_diagram=False,
                    raw=part,
                    warnings=[f"No part catalog entry for '{part.name}'"],
                )
            )
            warnings.append(f"Unmapped part: {part.name}")
            continue

        planned = PlannedPart(
            part_id=spec["part_id"],
            part_name=part.name,
            category=spec["category"],
            render_kind=spec["render_kind"],
            on_diagram=False,
            raw=part,
        )

        if spec["render_kind"] == "none":
            planned_parts.append(planned)
            continue

        default_views = spec.get("default_views", [])
        if not default_views:
            planned.warnings.append(f"No default views configured for '{part.name}'")
            planned_parts.append(planned)
            continue

        profile_id, raw_color_token = _resolve_profile(part, spec, manifest)
        size_class = _size_class_for_part(part.part_number, manifest)
        lib_entry = config.parts_lib_by_model.get(part.part_number.strip().upper(), {})
        lib_size_per_view: dict = lib_entry.get("size_per_view", {})
        lib_images: dict = lib_entry.get("images", {})
        catalog_size_per_view: dict = spec.get("size_per_view", {})
        merged_size_per_view = {**lib_size_per_view, **catalog_size_per_view}

        for view in default_views:
            view_config = view_map.get(view, {})
            location_key = canonical_name(part.location or spec.get("default_location_key", "")).strip().upper()
            if not location_key:
                planned.warnings.append(f"{view}: no location supplied for {part.name}")
                continue

            location = view_config.get("locations", {}).get(location_key)
            if location is None:
                planned.warnings.append(f"{view}: location '{location_key}' not found")
                continue

            quantity_policy = spec.get("render_quantity_policy", "location_slots")
            slot_count = int(location.get("slot_count", 1))
            if quantity_policy == "single_per_line":
                slot_count = 1

            slot_roles = _build_slot_roles(location.get("pattern", "single"), slot_count, view_config)
            placement = PlannedPlacement(
                part_id=spec["part_id"],
                part_name=part.name,
                view=view,
                location_key=location_key,
                render_kind=spec["render_kind"],
                asset_key=spec.get("asset_key", ""),
                size_class=size_class,
                color_profile=profile_id,
                quantity_policy=quantity_policy,
                ordered_quantity=part.quantity,
                location_slot_count=int(location.get("slot_count", 1)),
                anchor={
                    "x": location["x"],
                    "y": location["y"],
                    "units": location.get("units", view_config.get("coord_space", "relative_image")),
                },
                pattern=location.get("pattern", "single"),
                spacing=location.get("spacing") or None,
                size_override=merged_size_per_view.get(view) or None,
            )

            if quantity_policy == "location_slots":
                if part.quantity and part.quantity != placement.location_slot_count:
                    placement.warnings.append(f"Qty {part.quantity} differs from location slot count {placement.location_slot_count}")
            elif quantity_policy == "single_per_line" and part.quantity > 1:
                placement.warnings.append(f"Qty {part.quantity} is recorded but this part currently renders once per line item")

            orientation = location.get("orientation", "h")
            for index, slot_role in enumerate(slot_roles, start=1):
                color_token = _resolve_color_token(profile_id, raw_color_token, slot_role, part, manifest)
                asset_path = _resolve_asset_path(
                    render_kind=spec["render_kind"],
                    asset_key=spec.get("asset_key", ""),
                    view=view,
                    orientation=orientation,
                    color_token=color_token,
                    asset_manifest=manifest,
                    fallback_images=lib_images,
                )
                instance = RenderInstance(
                    slot_index=index,
                    slot_role=slot_role,
                    orientation=orientation,
                    color_token=color_token,
                    asset_path=asset_path,
                )
                if asset_path:
                    asset_file = config.paths.workspace_assets_dir / Path(asset_path)
                    if not asset_file.exists():
                        instance.warnings.append(f"Missing asset: {asset_path}")
                elif spec["render_kind"] == "equipment":
                    instance.warnings.append(f"No equipment asset configured for '{part.name}'")
                elif spec["render_kind"] == "bar":
                    instance.warnings.append(f"No bar asset configured for '{part.name}'")
                elif spec["render_kind"] != "none":
                    instance.warnings.append("No asset resolved")
                placement.instances.append(instance)

            planned.placements.append(placement)

        planned.on_diagram = bool(planned.placements)
        planned_parts.append(planned)

    return BuildPlan(
        version="7.0",
        project=project.info,
        planned_parts=planned_parts,
        warnings=warnings,
        notes=project.notes,
    )
