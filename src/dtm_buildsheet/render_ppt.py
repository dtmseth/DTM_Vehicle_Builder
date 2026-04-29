from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Inches

from .paths import AppPaths, ensure_workspace
from .ppt_helpers import (
    VIEWS,
    _is_reused,
    _source_label,
    add_parts_manifest_slides,
    add_slide_footer_bar,
    fill_notes,
    fill_overview,
    get_icon_size,
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
    left, _, width, _ = img_box
    if slot_count <= 1 or pattern == "single":
        if pattern == "mirror" and slot_roles:
            center_x = left + width // 2
            offset_x = abs(base_cx - center_x)
            role     = slot_roles[0]
            if role in ("passenger", "negative_x"):
                return [(center_x - offset_x, base_cy)]
            if role in ("driver", "positive_x"):
                return [(center_x + offset_x, base_cy)]
        return [(base_cx, base_cy)]
    if pattern == "horizontal":
        total_w = h_spacing * (slot_count - 1)
        start_x = base_cx - total_w // 2
        return [(start_x + int(i * h_spacing), base_cy) for i in range(slot_count)]
    if pattern == "vertical":
        sv      = v_spacing or h_spacing
        total_h = sv * (slot_count - 1)
        start_y = base_cy - total_h // 2
        return [(base_cx, start_y + int(i * sv)) for i in range(slot_count)]
    if pattern == "mirror":
        center_x = left + width // 2
        offset_x = abs(base_cx - center_x)
        if slot_count == 2:
            return [(center_x - offset_x, base_cy), (center_x + offset_x, base_cy)]
        half      = slot_count // 2
        positions = []
        for i in range(half):
            offset = offset_x + int(i * h_spacing)
            positions.append((center_x - offset, base_cy))
            positions.append((center_x + offset, base_cy))
        return positions
    return [(base_cx, base_cy)]


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
    if placement.size_override and "w" in placement.size_override and "h" in placement.size_override:
        w = float(placement.size_override["w"])
        h = float(placement.size_override["h"])
        if instance.orientation == "v":
            w, h = h, w
        return w, h
    return get_icon_size(part_size, placement.render_kind, instance.orientation,
                         view, instance.asset_path, paths=paths)


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


def render_plan_to_ppt(plan, paths: AppPaths | None = None) -> Path:
    active_paths = paths or ensure_workspace()
    template     = active_paths.templates_dir / "build_sheet_template.pptx"
    project_id   = plan.project.get("ProjectID", "UNKNOWN")
    out_path     = active_paths.workspace_output_dir / f"VehicleBuilder_{project_id}_v7.pptx"

    shutil.copyfile(template, out_path)
    prs      = Presentation(out_path)
    overview = prs.slides[0]
    view_slides  = {view: prs.slides[i + 1] for i, view in enumerate(VIEWS)}
    notes_slide  = prs.slides[5]

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

    for view in VIEWS:
        slide = view_slides[view]

        update_slide_header_footer(
            slide,
            title    = f"{view.upper()} VIEW — {agency}",
            subtitle = "  |  ".join(filter(None, [veh_line, unit_str])),
        )
        add_slide_footer_bar(slide, footer)
        if view in ("side", "top"):
            place_logo_bottom(slide, active_paths)
        else:
            place_logo(slide, active_paths)

        vehicle_pic_shape, img_box = place_vehicle_image(
            slide, plan.project.get("VehicleType", "PIU"), view
        )
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

                    is_mirrored = (
                        placement.flip_mirrored_h
                        and placement.pattern == "mirror"
                        and instance.slot_role in ("driver", "positive_x")
                    )
                    inst_flip_h = placement.flip_h ^ is_mirrored
                    is_right    = (
                        placement.pattern == "mirror"
                        and instance.slot_role in ("driver", "positive_x")
                    )
                    inst_rot = (
                        (360 - placement.rotation) % 360
                        if is_right and placement.rotation else placement.rotation
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

        if view in ("side", "top"):
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
