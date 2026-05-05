from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Inches

from .domain.geometry import slot_relative_positions
from .paths import AppPaths, ensure_workspace
from .ppt_helpers import (
    VIEWS as _LEGACY_VIEWS,
    _is_reused,
    _source_label,
    add_parts_manifest_slides,
    add_slide_footer_bar,
    fill_notes,
    fill_overview,
    icon_size_in_inches,
    place_legend,
    place_legend_grid,
    place_logo,
    place_logo_bottom,
    place_specify_palette,
    place_vehicle_image,
    update_slide_header_footer,
)


def _project_shim(plan) -> SimpleNamespace:
    parts = []
    for pp in plan.planned_parts:
        if not pp.raw.include:
            continue
        raw = pp.raw
        parts.append(SimpleNamespace(
            name         = pp.part_name,
            manufacturer = raw.manufacturer,
            part_number  = raw.part_number,
            color        = raw.raw_color,
            quantity     = raw.quantity,
            lens         = raw.lens,
            new_or_used  = raw.new_or_used,
            source       = raw.source,
            category     = pp.category or "",
            render_kind  = pp.render_kind or "",
        ))
    return SimpleNamespace(info=plan.project, parts=parts, notes=plan.notes)


def _legend_item(part_name: str, location: str = "", notes: str = "",
                 accessories: list[str] | None = None,
                 manufacturer: str = "", part_number: str = "",
                 color: str = "", lens: str = "",
                 new_or_used: str = "", source: str = "",
                 is_reused: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        name         = part_name,
        location     = location,
        notes        = notes,
        accessories  = accessories or [],
        manufacturer = manufacturer,
        part_number  = part_number,
        color        = color,
        lens         = lens,
        new_or_used  = new_or_used,
        source       = source,
        is_reused    = is_reused,
    )


def _unplaced_for_view(plan, view: str):
    unplaced = []
    seen     = set()
    prefix   = f"{view}:"
    for pp in plan.planned_parts:
        matching = [w for w in pp.warnings if w.startswith(prefix)]
        if not matching:
            continue
        key = (pp.part_name, pp.raw.location)
        if key in seen:
            continue
        seen.add(key)
        unplaced.append(_legend_item(
            pp.part_name, pp.raw.location or "?",
            "; ".join(matching),
        ))
    return unplaced


def _position_from_anchor(anchor: dict, img_box):
    left, top, width, height = img_box
    units = anchor.get("units", "relative_image")
    if units == "relative_image":
        return left + int(anchor["x"] * width), top + int(anchor["y"] * height)
    if units == "image_inches":
        return left + Inches(anchor["x"]), top + Inches(anchor["y"])
    return left + int(anchor["x"] * width), top + int(anchor["y"] * height)


def _slot_positions(pattern: str, slot_count: int, base_cx, base_cy,
                    img_box, h_spacing, v_spacing=None, slot_roles=None):
    """EMU-space adapter over domain geometry slot_relative_positions."""
    left, top, width, height = img_box
    anchor_x = (base_cx - left) / width
    anchor_y = (base_cy - top) / height
    h_rel = h_spacing / width
    v_rel = (v_spacing / height) if v_spacing is not None else None
    norm = slot_relative_positions(
        pattern, slot_count, anchor_x, anchor_y, h_rel, v_rel, slot_roles
    )
    return [(left + int(nx * width), top + int(ny * height)) for nx, ny in norm]


def _apply_shape_transforms(shape, rotation: float, flip_h: bool, flip_v: bool) -> None:
    if not rotation and not flip_h and not flip_v:
        return
    sp_pr = shape._element.find(qn("p:spPr"))
    if sp_pr is None:
        return
    xfrm = sp_pr.find(qn("a:xfrm"))
    if xfrm is None:
        xfrm = etree.SubElement(sp_pr, qn("a:xfrm"))
    if rotation:
        xfrm.set("rot", str(int(rotation * 60000)))
    if flip_h:
        xfrm.set("flipH", "1")
    if flip_v:
        xfrm.set("flipV", "1")


def _move_shape_behind(slide, shape, vehicle_pic_element) -> None:
    sp_tree   = slide.shapes._spTree
    shape_elem = shape._element
    sp_tree.remove(shape_elem)
    children = list(sp_tree)
    try:
        vehicle_idx = children.index(vehicle_pic_element)
    except ValueError:
        vehicle_idx = 2
    sp_tree.insert(vehicle_idx, shape_elem)


def _group_shapes(slide, shapes: list) -> None:
    if len(shapes) < 2:
        return
    sp_tree = slide.shapes._spTree

    lefts  = [s.left              for s in shapes]
    tops   = [s.top               for s in shapes]
    rights = [s.left + s.width    for s in shapes]
    bots   = [s.top  + s.height   for s in shapes]
    gx, gy = min(lefts), min(tops)
    gcx    = max(rights) - gx
    gcy    = max(bots)   - gy

    existing_ids = {int(el.get("id", 0)) for el in sp_tree.iter() if el.get("id") is not None}
    grp_id = max(existing_ids, default=0) + 1

    grp_sp = etree.SubElement(sp_tree, qn("p:grpSp"))

    nv = etree.SubElement(grp_sp, qn("p:nvGrpSpPr"))
    cp = etree.SubElement(nv, qn("p:cNvPr"))
    cp.set("id", str(grp_id)); cp.set("name", f"Group {grp_id}")
    etree.SubElement(nv, qn("p:cNvGrpSpPr"))
    etree.SubElement(nv, qn("p:nvPr"))

    gpr  = etree.SubElement(grp_sp, qn("p:grpSpPr"))
    xfrm = etree.SubElement(gpr,    qn("a:xfrm"))
    off  = etree.SubElement(xfrm,   qn("a:off"));  off.set("x",  str(gx)); off.set("y", str(gy))
    ext  = etree.SubElement(xfrm,   qn("a:ext")); ext.set("cx", str(gcx)); ext.set("cy", str(gcy))
    cho  = etree.SubElement(xfrm,   qn("a:chOff")); cho.set("x", str(gx)); cho.set("y", str(gy))
    che  = etree.SubElement(xfrm,   qn("a:chExt")); che.set("cx", str(gcx)); che.set("cy", str(gcy))

    for shape in shapes:
        elem = shape._element
        sp_tree.remove(elem)
        grp_sp.append(elem)


def _instance_icon_size(placement, part_size, instance, view: str,
                        paths: AppPaths) -> tuple[float, float]:
    w, h = icon_size_in_inches(
        render_kind=placement.render_kind,
        part_name=part_size.name,
        size_class=part_size.size_class,
        orientation=instance.orientation,
        asset_path=instance.asset_path,
        view=view,
        size_override=placement.size_override,
        paths=paths,
    )
    scale = getattr(placement, "size_scale", 1.0)
    return w * scale, h * scale


def _build_accessory_map(plan) -> dict[str, list[str]]:
    acc_map: dict[str, list[str]] = {}
    for pp in plan.planned_parts:
        if pp.accessory_of:
            acc_map.setdefault(pp.accessory_of, []).append(pp.part_name)
    return acc_map


def _move_slides_to_position(prs, start_position: int, count: int) -> None:
    """Move the last `count` slides in prs to start at index `start_position`."""
    if count <= 0:
        return
    sldIdLst = prs.slides._sldIdLst
    total    = len(sldIdLst)
    to_move  = list(sldIdLst)[total - count:]
    for elem in to_move:
        sldIdLst.remove(elem)
    for idx, elem in enumerate(to_move):
        sldIdLst.insert(start_position + idx, elem)


def _load_vehicle_view_config(vehicle_type: str, paths) -> tuple[list[str], dict]:
    """Return (external_view_order, {view_name: view_config}) from vehicle_layouts config.

    Falls back to the legacy hardcoded order if the config is unavailable.
    """
    import json
    try:
        layouts_path = paths.workspace_config_dir / "vehicle_layouts.json"
        layouts = json.loads(layouts_path.read_text("utf-8"))
        vehicle = layouts.get("vehicles", {}).get(vehicle_type, {})
    except Exception:
        vehicle = {}

    view_map   = vehicle.get("views", {})
    view_order = vehicle.get("view_order", list(_LEGACY_VIEWS))
    external   = [v for v in view_order
                  if view_map.get(v, {}).get("category", "external") == "external"]
    return (external or list(_LEGACY_VIEWS)), view_map


# The PPTX template has exactly this many view slides (indices 1..N, then notes at N+1)
_TEMPLATE_VIEW_SLOTS = 4


def render_plan_to_ppt(plan, paths: AppPaths | None = None) -> Path:
    active_paths = paths or ensure_workspace()
    template     = active_paths.templates_dir / "build_sheet_template.pptx"
    project_id   = plan.project.get("ProjectID", "UNKNOWN")
    out_path     = active_paths.workspace_output_dir / f"VehicleBuilder_{project_id}_v7.pptx"

    vehicle_type = plan.project.get("VehicleType", "PIU")
    external_views, view_map = _load_vehicle_view_config(vehicle_type, active_paths)

    shutil.copyfile(template, out_path)
    prs      = Presentation(out_path)
    overview = prs.slides[0]
    # Map the first N external views to the template's view slide slots
    view_slides = {
        v: prs.slides[i + 1]
        for i, v in enumerate(external_views[:_TEMPLATE_VIEW_SLOTS])
    }
    notes_slide = prs.slides[_TEMPLATE_VIEW_SLOTS + 1]

    # ── Shared project metadata ───────────────────────────────────────────────
    project_shim = _project_shim(plan)
    new_v    = plan.project.get("NewVehicle",      {})
    exist_v  = plan.project.get("ExistingVehicle", {})
    agency   = plan.project.get("Agency", "")
    year     = new_v.get("YEAR",  "") or exist_v.get("YEAR",  "")
    make     = new_v.get("MAKE",  "") or exist_v.get("MAKE",  "")
    model    = (new_v.get("MODEL","") or exist_v.get("MODEL","")
                or plan.project.get("VehicleType",""))
    veh_line = " ".join(filter(None, [year, make, model]))
    unit_id  = (new_v.get("UNIT ID", new_v.get("UNIT",""))
                or exist_v.get("UNIT ID", exist_v.get("UNIT","")))
    unit_str = f"Unit#{unit_id}" if unit_id else ""
    footer   = "   •   ".join(filter(None, [agency, veh_line, unit_str, "DTM Fleet Service"]))

    # ── Cover slide ───────────────────────────────────────────────────────────
    fill_overview(overview, project_shim)
    place_logo(overview, active_paths, cover=True)

    # ── View slides ───────────────────────────────────────────────────────────
    accessory_map = _build_accessory_map(plan)

    for view in external_views:
        slide = view_slides.get(view)
        if slide is None:
            continue  # more external views than template slots; skip extras

        view_cfg      = view_map.get(view, {})
        legend_layout = view_cfg.get("legend_layout", "standard")
        logo_position = view_cfg.get("logo_position", "top-right")
        view_label    = view_cfg.get("label", view.upper())

        update_slide_header_footer(
            slide,
            title    = f"{view_label.upper()} VIEW — {agency}",
            subtitle = "  |  ".join(filter(None, [veh_line, unit_str])),
        )
        add_slide_footer_bar(slide, footer)
        if logo_position == "bottom":
            place_logo_bottom(slide, active_paths)
        else:
            place_logo(slide, active_paths)

        vehicle_pic_shape, img_box = place_vehicle_image(slide, vehicle_type, view)
        vehicle_pic_element = vehicle_pic_shape._element if vehicle_pic_shape else None
        if img_box is None:
            place_legend(slide, [], [], accessory_map)
            continue

        used_centers: list   = []
        collision            = Inches(0.18)
        specify_palettes: list[str] = []
        rendered_part_names: set[str] = set()

        for pp in plan.planned_parts:
            for placement in pp.placements:
                if placement.view != view or not placement.instances:
                    continue

                if placement.color_profile == "specify_palette":
                    cat = placement.instances[0].color_token
                    if cat not in specify_palettes:
                        specify_palettes.append(cat)
                    continue

                base_cx, base_cy = _position_from_anchor(placement.anchor, img_box)
                part_size        = SimpleNamespace(name=placement.part_name,
                                                   size_class=placement.size_class)
                first_inst       = placement.instances[0]
                if placement.render_kind in ("equipment", "bar") and not first_inst.asset_path:
                    continue

                size_w, _ = _instance_icon_size(placement, part_size, first_inst, view, active_paths)
                icon_w_emu = Inches(size_w)

                if placement.h_spacing is not None and placement.h_spacing > 0:
                    if placement.h_spacing_units == "icon_width":
                        h_spacing_emu = int(icon_w_emu * placement.h_spacing)
                    else:
                        h_spacing_emu = int(img_box[2] * placement.h_spacing)
                else:
                    h_spacing_emu = int(icon_w_emu + Inches(0.03))

                if placement.v_spacing is not None and placement.v_spacing > 0:
                    if placement.h_spacing_units == "icon_width":
                        _, size_h = _instance_icon_size(placement, part_size, first_inst,
                                                        view, active_paths)
                        v_spacing_emu = int(Inches(size_h) * placement.v_spacing)
                    else:
                        v_spacing_emu = int(img_box[3] * placement.v_spacing)
                else:
                    v_spacing_emu = h_spacing_emu

                if placement.slot_indices and placement.position_slot_count:
                    all_positions = _slot_positions(
                        placement.pattern, placement.position_slot_count,
                        base_cx, base_cy, img_box,
                        h_spacing_emu, v_spacing_emu,
                    )
                    positions = [all_positions[i] for i in placement.slot_indices if i < len(all_positions)]
                else:
                    positions = _slot_positions(
                        placement.pattern, len(placement.instances),
                        base_cx, base_cy, img_box,
                        h_spacing_emu, v_spacing_emu,
                        slot_roles=[inst.slot_role for inst in placement.instances],
                    )

                placement_shapes: list = []

                for instance, (px, py) in zip(placement.instances, positions):
                    if not instance.asset_path:
                        continue
                    icon_path = active_paths.workspace_assets_dir / instance.asset_path
                    if not icon_path.exists():
                        continue

                    inst_w, inst_h = _instance_icon_size(placement, part_size, instance,
                                                         view, active_paths)
                    iw = Inches(inst_w)
                    ih = Inches(inst_h)

                    ax, ay = px, py
                    if not placement.group_shapes:
                        nudge = Inches(0.30)
                        for ox, oy in used_centers:
                            if abs(ax - ox) < collision and abs(ay - oy) < collision:
                                ax    += nudge
                                nudge += Inches(0.30)
                    used_centers.append((ax, ay))

                    pic = slide.shapes.add_picture(
                        str(icon_path), ax - iw // 2, ay - ih // 2,
                        width=iw, height=ih,
                    )

                    is_right_slot = instance.slot_role in ("driver", "positive_x")
                    is_sym_pattern = placement.pattern in ("mirror", "horizontal")
                    is_mirrored = (
                        placement.flip_mirrored_h
                        and is_sym_pattern
                        and is_right_slot
                    )
                    inst_flip_h = placement.flip_h ^ is_mirrored
                    is_right    = is_sym_pattern and is_right_slot
                    inst_rot = (
                        (360 - placement.rotation) % 360
                        if is_right and placement.rotation != 0 else placement.rotation
                    )
                    _apply_shape_transforms(pic, inst_rot, inst_flip_h, placement.flip_v)

                    if placement.behind_vehicle and vehicle_pic_element is not None:
                        _move_shape_behind(slide, pic, vehicle_pic_element)

                    placement_shapes.append(pic)
                    rendered_part_names.add(pp.part_name)

                if placement.group_shapes and len(placement_shapes) >= 2:
                    _group_shapes(slide, placement_shapes)

        # ── Build legend items ────────────────────────────────────────────────
        placed_legend: list = []
        seen_placed: set[tuple] = set()

        for pp in plan.planned_parts:
            for pl in pp.placements:
                if pl.view != view:
                    continue
                # Skip pure fixture placements — not customer-ordered parts
                if pl.is_fixture:
                    continue
                if (pp.part_name not in rendered_part_names
                        and pl.color_profile != "specify_palette"):
                    continue
                key = (pp.part_name, pl.location_key)
                if key in seen_placed:
                    continue
                seen_placed.add(key)

                raw       = pp.raw
                reused    = _is_reused(raw)
                source    = raw.source or ""
                accessories = accessory_map.get(pp.part_name, [])
                placed_legend.append(_legend_item(
                    pp.part_name, pl.location_key, raw.notes, accessories,
                    manufacturer = raw.manufacturer,
                    part_number  = raw.part_number,
                    color        = raw.raw_color,
                    lens         = raw.lens,
                    new_or_used  = raw.new_or_used,
                    source       = source,
                    is_reused    = reused,
                ))

        unplaced_legend = _unplaced_for_view(plan, view)
        palette_offset  = 0
        for cat in specify_palettes:
            consumed = place_specify_palette(slide, cat, img_box,
                                             y_offset_emu=palette_offset)
            if consumed:
                palette_offset += consumed

        if legend_layout == "grid":
            place_legend_grid(slide, placed_legend, unplaced_legend, accessory_map, view=view)
        else:
            place_legend(slide, placed_legend, unplaced_legend, accessory_map, view=view)

    # ── Notes slide ───────────────────────────────────────────────────────────
    update_slide_header_footer(
        notes_slide,
        title    = f"BUILD NOTES — {agency}",
        subtitle = "  |  ".join(filter(None, [veh_line, unit_str])),
    )
    add_slide_footer_bar(notes_slide, footer)
    place_logo(notes_slide, active_paths)
    fill_notes(notes_slide, plan.notes)

    # ── Parts manifest slides (appended, then moved to position 1) ────────────
    n_manifest = add_parts_manifest_slides(prs, plan, active_paths)
    if n_manifest:
        _move_slides_to_position(prs, start_position=1, count=n_manifest)

    prs.save(out_path)
    return out_path
