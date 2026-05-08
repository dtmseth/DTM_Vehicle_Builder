from __future__ import annotations

import traceback

from ...config.loader import load_configs
from ...inputs.project_drafts import draft_to_project_input, load_draft
from ...paths import AppPaths
from ...planning.override_applier import apply_overrides
from ...planning.planner import build_plan
from ...ppt_helpers import icon_size_in_inches

_FALLBACK_VIEW_ORDER = ["front", "rear", "side", "top"]

# Vehicle image slot dimensions in inches, matching place_vehicle_image() in ppt_helpers.py.
# front/rear: VEHICLE_IMAGE_SLOT measured from the PPTX template (9.5" × 5.3").
# side/top: hardcoded in place_vehicle_image() — full width, from 3.5" to bottom of footer.
_SLOT_FRONT_REAR = (9.5,   5.3)
_SLOT_SIDE_TOP   = (13.333, 3.58)   # 7.5 - 3.5 - 0.42 footer


def _view_metadata(vehicle_config: dict) -> tuple[list[str], dict[str, dict]]:
    """Return (ordered view IDs, {view_id: {label, category, ...}}) from vehicle config."""
    view_order = vehicle_config.get("view_order", _FALLBACK_VIEW_ORDER)
    view_map   = vehicle_config.get("views", {})
    meta: dict[str, dict] = {}
    for vid in view_order:
        vcfg = view_map.get(vid, {})
        meta[vid] = {
            "label":    vcfg.get("label", vid.replace(".", " ").title()),
            "category": vcfg.get("category", "external"),
        }
    return view_order, meta


def _rendered_vehicle_size(vehicle_type: str, view: str, paths: AppPaths) -> tuple[float, float]:
    """Return (rendered_width_in, rendered_height_in) of the vehicle PNG fitted into its PPTX slot.

    Mirrors the aspect-ratio-fit logic in place_vehicle_image() so that
    icon_w_pct / icon_h_pct values sent to the canvas match the PPTX layout.
    """
    slot_w, slot_h = _SLOT_SIDE_TOP if view in ("side", "top") else _SLOT_FRONT_REAR

    png = paths.workspace_assets_dir / "vehicles" / f"{vehicle_type}_{view}.png"
    if not png.exists():
        return slot_w, slot_h

    try:
        from PIL import Image as PILImage
        with PILImage.open(png) as img:
            img_w, img_h = img.size
    except Exception:
        return slot_w, slot_h

    img_ratio  = img_w / img_h
    slot_ratio = slot_w / slot_h
    if img_ratio > slot_ratio:
        return slot_w, slot_w / img_ratio
    return slot_h * img_ratio, slot_h


def handle_preview_plan(body: dict, paths: AppPaths) -> dict:
    """Build a plan for the given draft and return a canvas-ready JSON payload.

    Response shape:
        ok          bool
        draft_id    str
        vehicle_type str
        views       {view_name: {label, category, bg_url}}
        planned_parts [
            {part_id, part_name, render_kind,
             placements: [
               {view, override_key, location_key, anchor,
                pattern, h_spacing, h_spacing_units,
                slot_count, position_slot_count, slot_indices,
                rotation, flip_h, flip_v, flip_mirrored_h,
                icon_w_pct, icon_h_pct,
                instances: [{slot_index, slot_role, orientation, color_token, asset_url}],
                override}
             ]}
        ]
        warnings    [str]
    """
    try:
        draft_id = body.get("draft_id", "")
        if not draft_id:
            return {"ok": False, "error": "draft_id required"}

        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        project = draft_to_project_input(draft)
        config = load_configs(paths)
        plan = build_plan(project, config)

        if draft.placement_overrides:
            plan = apply_overrides(plan, draft.placement_overrides)

        vehicle_type = project.info.get("VehicleType", "")
        vehicle_config = config.vehicle_layouts.get("vehicles", {}).get(vehicle_type, {})
        view_order, view_meta = _view_metadata(vehicle_config)

        # Collect views that actually appear in this plan
        used_views: set[str] = set()
        for pp in plan.planned_parts:
            for pl in pp.placements:
                used_views.add(pl.view)

        # Show ALL external views from the vehicle config so tabs appear even
        # when a view has no planned parts (e.g. TRAVERSE top view with no roof items).
        external_view_order = [
            v for v in view_order
            if view_meta.get(v, {}).get("category", "external") == "external"
        ]
        all_preview_views: set[str] = used_views | set(external_view_order)

        # Pre-compute rendered vehicle image dimensions per view (for icon_*_pct)
        rendered_dims: dict[str, tuple[float, float]] = {}
        for view_name in all_preview_views:
            rendered_dims[view_name] = _rendered_vehicle_size(vehicle_type, view_name, paths)

        views: dict = {}
        for view_name in external_view_order:
            m = view_meta[view_name]
            views[view_name] = {
                "label":    m["label"],
                "category": m["category"],
                "bg_url":   f"/assets/vehicles/{vehicle_type}_{view_name}.png",
            }
        for view_name in sorted(all_preview_views - set(external_view_order)):
            views[view_name] = {
                "label":    view_name.replace(".", " ").title(),
                "category": "external",
                "bg_url":   f"/assets/vehicles/{vehicle_type}_{view_name}.png",
            }

        parts_out: list[dict] = []
        for pp in plan.planned_parts:
            if not pp.on_diagram or not pp.placements:
                continue

            placements_out: list[dict] = []
            for pl in pp.placements:
                rw, rh = rendered_dims.get(pl.view, _SLOT_FRONT_REAR)

                # Use the same sizing logic as the PPTX renderer (single source of truth).
                first_inst = pl.instances[0] if pl.instances else None
                if first_inst:
                    w_in, h_in = icon_size_in_inches(
                        render_kind=pl.render_kind,
                        part_name=pl.part_name,
                        size_class=pl.size_class,
                        orientation=first_inst.orientation,
                        asset_path=first_inst.asset_path,
                        view=pl.view,
                        size_override=pl.size_override,
                        paths=paths,
                    )
                    scale = getattr(pl, "size_scale", 1.0)
                    icon_w_pct = (w_in * scale) / rw
                    icon_h_pct = (h_in * scale) / rh
                else:
                    icon_w_pct = 0.04
                    icon_h_pct = 0.02

                slot_count = len(pl.instances) or 1
                override_key = f"{pl.part_id}:{pl.view}"

                instances_out = [
                    {
                        "slot_index": inst.slot_index,
                        "slot_role":  inst.slot_role,
                        "orientation": inst.orientation,
                        "color_token": inst.color_token,
                        "asset_url": (
                            f"/assets/{inst.asset_path}" if inst.asset_path else ""
                        ),
                    }
                    for inst in pl.instances
                ]

                placements_out.append({
                    "view":               pl.view,
                    "override_key":       override_key,
                    "location_key":       pl.location_key,
                    "anchor":             pl.anchor,
                    "pattern":            pl.pattern,
                    "h_spacing":          pl.h_spacing,
                    "h_spacing_units":    pl.h_spacing_units,
                    "slot_count":         slot_count,
                    "position_slot_count": pl.position_slot_count,
                    "slot_indices":       pl.slot_indices,
                    "rotation":           pl.rotation,
                    "flip_h":             pl.flip_h,
                    "flip_v":             pl.flip_v,
                    "flip_mirrored_h":    pl.flip_mirrored_h,
                    "icon_w_pct":         icon_w_pct,
                    "icon_h_pct":         icon_h_pct,
                    "layer":              pl.layer,
                    "size":               pl.size_override,
                    "instances":          instances_out,
                    "override":           draft.placement_overrides.get(override_key, {}),
                })

            if placements_out:
                parts_out.append({
                    "part_id":      pp.part_id,
                    "part_name":    pp.part_name,
                    "render_kind":  pp.render_kind,
                    "manufacturer": getattr(pp.raw, "manufacturer", "") or "",
                    "part_number":  getattr(pp.raw, "part_number", "") or "",
                    "placements":   placements_out,
                })

        return {
            "ok":           True,
            "draft_id":     draft_id,
            "vehicle_type": vehicle_type,
            "views":        views,
            "planned_parts": parts_out,
            "warnings":     plan.warnings,
        }

    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "trace": traceback.format_exc()}
