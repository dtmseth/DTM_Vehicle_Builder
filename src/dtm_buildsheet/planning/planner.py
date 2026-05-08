from __future__ import annotations

from pathlib import Path

from ..config_loader import ConfigBundle
from ..domain import BuildPlan, PlannedPart, PlannedPlacement, RenderInstance, slot_roles
from ..domain.rules import RuleSeverity
from ..naming import canonical_name
from ..rules.engine import run_rules
from .asset_resolver import resolve_asset_path, size_class_for_part
from .color_resolver import resolve_color_token, resolve_profile
from .fixture_resolver import resolve_fixture_entry
from .location_resolver import apply_co_part_rules, resolve_normal_location
from .quantity_resolver import apply_quantity_rules


_SUPPRESS_QTY_MISMATCH_LOCATIONS: frozenset[str] = frozenset({
    "TOP OF PUSH BUMPER",
    "UNDER PUSH BUMPER",
    "TOP TUBE",
})


def build_plan(project, config: ConfigBundle) -> BuildPlan:
    manifest = config.asset_manifest
    layouts = config.vehicle_layouts.get("vehicles", {})
    vehicle_type = project.info.get("VehicleType", "PIU")
    vehicle = layouts.get(vehicle_type, {})
    view_map = vehicle.get("views", {})
    fixtures_map = vehicle.get("fixtures", {})

    # Pre-pass: collect names of all included parts for co_part_rules
    present_part_names: set[str] = set()
    for part in project.parts:
        if part.include:
            present_part_names.add(part.name.strip())
            present_part_names.add(canonical_name(part.name).strip().upper())
            if part.part_number:
                present_part_names.add(part.part_number.strip())
                present_part_names.add(canonical_name(part.part_number).strip().upper())

    planned_parts: list[PlannedPart] = []
    warnings: list[str] = []

    # Run the rule engine; fold results into the top-level warnings list
    rule_result = run_rules(project, config.build_rules)
    for msg in rule_result.messages:
        prefix = "[ERROR]" if msg.severity == RuleSeverity.ERROR else "[RULE]"
        warnings.append(f"{prefix} {msg.message}")

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

        # Model-based remap: switch spec when the part number matches a model_remaps entry
        if part.part_number and spec.get("model_remaps"):
            model_key = canonical_name(part.part_number).strip().upper()
            remapped_id = spec["model_remaps"].get(model_key)
            if remapped_id and remapped_id in config.parts_by_id:
                spec = config.parts_by_id[remapped_id]

        accessory_parents = spec.get("accessory_of")
        planned = PlannedPart(
            part_id=spec["part_id"],
            part_name=part.name,
            category=spec["category"],
            render_kind=spec["render_kind"],
            on_diagram=False,
            raw=part,
            accessory_of=(
                accessory_parents[0]
                if isinstance(accessory_parents, list) and accessory_parents
                else accessory_parents
                if isinstance(accessory_parents, str)
                else None
            ),
        )

        if spec["render_kind"] == "none":
            planned_parts.append(planned)
            continue

        default_views = spec.get("default_views", [])
        if not default_views:
            planned.warnings.append(f"No default views configured for '{part.name}'")
            planned_parts.append(planned)
            continue

        profile_id, raw_color_token = resolve_profile(part, spec, manifest)
        size_class = size_class_for_part(part.part_number, manifest)
        lib_entry = config.parts_lib_by_model.get(part.part_number.strip().upper(), {})
        lib_size_per_view: dict = lib_entry.get("size_per_view", {})
        lib_images: dict = lib_entry.get("images", {})
        catalog_size_per_view: dict = spec.get("size_per_view", {})
        merged_size_per_view = {**lib_size_per_view, **catalog_size_per_view}

        is_fixture = bool(spec.get("is_fixture"))
        co_overrides = apply_co_part_rules(spec, present_part_names)

        if co_overrides.get("skip"):
            continue

        effective_asset_key = co_overrides.get(
            "asset_key", spec.get("asset_key") or spec.get("part_id", "")
        )

        for view in default_views:
            view_config = view_map.get(view, {})

            if is_fixture:
                location, location_key = resolve_fixture_entry(
                    spec, view, fixtures_map, view_config
                )
                if location is None:
                    planned.warnings.append(
                        f"{view}: no fixture coords for '{part.name}' in vehicle '{vehicle_type}'"
                    )
                    continue
            else:
                location, location_key = resolve_normal_location(
                    part, spec, view, view_config
                )
                if location is None:
                    if location_key:
                        planned.warnings.append(f"{view}: location '{location_key}' not found")
                    else:
                        planned.warnings.append(f"{view}: no location supplied for {part.name}")
                    continue

            quantity_policy = spec.get("render_quantity_policy", "location_slots")
            slot_count = int(location.get("slot_count", 1))

            if quantity_policy == "single_per_line":
                slot_count = 1
            elif quantity_policy == "quantity_as_slots":
                slot_count = max(1, part.quantity or 1)

            qty_overrides = apply_quantity_rules(spec, part.quantity)
            if qty_overrides.get("slot_count"):
                slot_count = int(qty_overrides["slot_count"])
            slot_indices: list[int] | None = qty_overrides.get("slot_indices")

            effective_pattern = co_overrides.get(
                "pattern", qty_overrides.get("pattern", location.get("pattern", "single"))
            )
            forced_side = co_overrides.get("side", "")
            if forced_side:
                slot_count = 1

            loc_asset_rules = spec.get("location_asset_rules", {})
            if not is_fixture and location_key in loc_asset_rules:
                effective_asset_key = loc_asset_rules[location_key]

            roles = slot_roles(
                effective_pattern,
                slot_count,
                view_config,
                forced_side,
                uniform_color=bool(spec.get("group_shapes", False)),
            )

            position_slot_count: int | None = None
            if slot_indices:
                position_slot_count = slot_count
                roles = [roles[i] for i in slot_indices if i < len(roles)]
                slot_count = len(roles)

            original_location_pattern = location.get("pattern", "single")
            anchor_x = (
                0.5
                if effective_pattern == "single"
                and original_location_pattern == "mirror"
                and not forced_side
                else location["x"]
            )

            placement = PlannedPlacement(
                part_id=spec["part_id"],
                part_name=part.name,
                view=view,
                location_key=location_key,
                render_kind=spec["render_kind"],
                asset_key=effective_asset_key,
                size_class=size_class,
                color_profile=profile_id,
                quantity_policy=quantity_policy,
                ordered_quantity=part.quantity,
                location_slot_count=int(location.get("slot_count", 1)),
                anchor={
                    "x": anchor_x,
                    "y": location["y"],
                    "units": location.get("units", view_config.get("coord_space", "relative_image")),
                },
                pattern=effective_pattern,
                h_spacing=location.get("h_spacing") or None,
                v_spacing=location.get("v_spacing") or None,
                h_spacing_units=location.get("h_spacing_units", "relative_image"),
                size_override=merged_size_per_view.get(view) or None,
                rotation=float(location.get("rotation", 0)),
                flip_h=bool(location.get("flip_h", False)),
                flip_v=bool(location.get("flip_v", False)),
                flip_mirrored_h=bool(location.get("flip_mirrored_h", False)),
                behind_vehicle=bool(location.get("behind_vehicle", False)),
                layer=int(location.get("layer", 0)),
                group_shapes=(
                    quantity_policy == "quantity_as_slots"
                    or bool(spec.get("group_shapes", False))
                ),
                is_fixture=is_fixture,
                slot_indices=slot_indices or None,
                position_slot_count=position_slot_count,
            )

            if quantity_policy == "location_slots":
                if part.quantity and part.quantity != placement.location_slot_count:
                    is_side_light = view == "side" and spec["render_kind"] in ("light", "bar")
                    if not is_side_light and location_key not in _SUPPRESS_QTY_MISMATCH_LOCATIONS:
                        placement.warnings.append(
                            f"[{part.name}] @ '{location_key}' ({view}): "
                            f"workbook qty {part.quantity} ≠ location slot count {placement.location_slot_count}"
                        )
            elif quantity_policy == "single_per_line" and part.quantity > 1:
                placement.warnings.append(
                    f"[{part.name}] @ '{location_key}' ({view}): "
                    f"qty {part.quantity} recorded but this part renders once per line item"
                )

            orientation = location.get("orientation", "h")
            for index, slot_role in enumerate(roles, start=1):
                color_token = resolve_color_token(
                    profile_id, raw_color_token, slot_role, part, manifest
                )
                asset_path = resolve_asset_path(
                    render_kind=spec["render_kind"],
                    asset_key=effective_asset_key,
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
                        instance.warnings.append(f"Missing asset ({view}): {asset_path}")
                elif spec["render_kind"] == "equipment":
                    instance.warnings.append(f"No equipment asset configured for '{part.name}' ({view})")
                elif spec["render_kind"] == "bar":
                    instance.warnings.append(f"No bar asset configured for '{part.name}' ({view})")
                elif spec["render_kind"] != "none":
                    instance.warnings.append(f"No asset resolved for '{part.name}' ({view})")
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
