from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Inches

from .paths import AppPaths, ensure_workspace
from .ppt_helpers import VIEWS, fill_notes, fill_overview, get_icon_size, place_legend, place_specify_palette, place_vehicle_image


def _project_shim(plan) -> SimpleNamespace:
    parts = []
    for planned_part in plan.planned_parts:
        raw = planned_part.raw
        parts.append(
            SimpleNamespace(
                name=planned_part.part_name,
                manufacturer=raw.manufacturer,
                part_number=raw.part_number,
                color=raw.raw_color,
                quantity=raw.quantity,
            )
        )
    return SimpleNamespace(info=plan.project, parts=parts, notes=plan.notes)


def _legend_item(part_name: str, location: str = "", notes: str = "", accessories: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=part_name, location=location, notes=notes, accessories=accessories or [])


def _unplaced_for_view(plan, view: str):
    unplaced = []
    seen = set()
    prefix = f"{view}:"
    for planned_part in plan.planned_parts:
        matching = [warning for warning in planned_part.warnings if warning.startswith(prefix)]
        if not matching:
            continue
        key = (planned_part.part_name, planned_part.raw.location)
        if key in seen:
            continue
        seen.add(key)
        unplaced.append(_legend_item(planned_part.part_name, planned_part.raw.location or "?", "; ".join(matching)))
    return unplaced


def _position_from_anchor(anchor: dict, img_box):
    left, top, width, height = img_box
    units = anchor.get("units", "relative_image")
    if units == "relative_image":
        return left + int(anchor["x"] * width), top + int(anchor["y"] * height)
    if units == "image_inches":
        return left + Inches(anchor["x"]), top + Inches(anchor["y"])
    return left + int(anchor["x"] * width), top + int(anchor["y"] * height)


def _slot_positions(pattern: str, slot_count: int, base_cx, base_cy, img_box, h_spacing, v_spacing=None, slot_roles=None):
    left, _, width, _ = img_box
    if slot_count <= 1 or pattern == "single":
        if pattern == "mirror" and slot_roles:
            center_x = left + width // 2
            offset_x = abs(base_cx - center_x)
            role = slot_roles[0]
            # negative_x / passenger = left side; positive_x / driver = right side
            if role in ("passenger", "negative_x"):
                return [(center_x - offset_x, base_cy)]
            if role in ("driver", "positive_x"):
                return [(center_x + offset_x, base_cy)]
        return [(base_cx, base_cy)]
    if pattern == "horizontal":
        total_w = h_spacing * (slot_count - 1)
        start_x = base_cx - total_w // 2
        return [(start_x + int(index * h_spacing), base_cy) for index in range(slot_count)]
    if pattern == "vertical":
        spacing_v = v_spacing or h_spacing  # fall back to h_spacing if v_spacing absent
        total_h = spacing_v * (slot_count - 1)
        start_y = base_cy - total_h // 2
        return [(base_cx, start_y + int(index * spacing_v)) for index in range(slot_count)]
    if pattern == "mirror":
        center_x = left + width // 2
        offset_x = abs(base_cx - center_x)
        if slot_count == 2:
            return [(center_x - offset_x, base_cy), (center_x + offset_x, base_cy)]
        half = slot_count // 2
        positions = []
        for index in range(half):
            offset = offset_x + int(index * h_spacing)
            positions.append((center_x - offset, base_cy))
            positions.append((center_x + offset, base_cy))
        return positions
    return [(base_cx, base_cy)]


def _apply_shape_transforms(shape, rotation: float, flip_h: bool, flip_v: bool) -> None:
    """Apply rotation and flip to a picture shape via its XML xfrm element."""
    if not rotation and not flip_h and not flip_v:
        return
    # For p:pic elements the spPr lives at p:pic/p:spPr/a:xfrm
    sp_pr = shape._element.find(qn("p:spPr"))
    if sp_pr is None:
        return
    xfrm = sp_pr.find(qn("a:xfrm"))
    if xfrm is None:
        xfrm = etree.SubElement(sp_pr, qn("a:xfrm"))
    if rotation:
        # pptx rotation is in 1/60000 of a degree, clockwise
        xfrm.set("rot", str(int(rotation * 60000)))
    if flip_h:
        xfrm.set("flipH", "1")
    if flip_v:
        xfrm.set("flipV", "1")


def _move_shape_behind(slide, shape, vehicle_pic_element) -> None:
    """Reorder shape XML so it renders behind the vehicle image."""
    sp_tree = slide.shapes._spTree
    shape_elem = shape._element
    sp_tree.remove(shape_elem)
    children = list(sp_tree)
    try:
        vehicle_idx = children.index(vehicle_pic_element)
    except ValueError:
        vehicle_idx = 2  # after nvGrpSpPr and grpSpPr
    sp_tree.insert(vehicle_idx, shape_elem)


def _group_shapes(slide, shapes: list) -> None:
    """Wrap a list of picture shapes into a PPTX group shape."""
    if len(shapes) < 2:
        return
    sp_tree = slide.shapes._spTree

    lefts  = [s.left for s in shapes]
    tops   = [s.top  for s in shapes]
    rights = [s.left + s.width  for s in shapes]
    bots   = [s.top  + s.height for s in shapes]
    gx, gy = min(lefts), min(tops)
    gcx = max(rights) - gx
    gcy = max(bots) - gy

    existing_ids = {int(el.get("id", 0)) for el in sp_tree.iter() if el.get("id") is not None}
    grp_id = max(existing_ids, default=0) + 1

    grp_sp = etree.SubElement(sp_tree, qn("p:grpSp"))

    nv_grp_sp_pr = etree.SubElement(grp_sp, qn("p:nvGrpSpPr"))
    cnv_pr = etree.SubElement(nv_grp_sp_pr, qn("p:cNvPr"))
    cnv_pr.set("id", str(grp_id)); cnv_pr.set("name", f"Group {grp_id}")
    etree.SubElement(nv_grp_sp_pr, qn("p:cNvGrpSpPr"))
    etree.SubElement(nv_grp_sp_pr, qn("p:nvPr"))

    grp_sp_pr = etree.SubElement(grp_sp, qn("p:grpSpPr"))
    xfrm = etree.SubElement(grp_sp_pr, qn("a:xfrm"))
    off   = etree.SubElement(xfrm, qn("a:off"));  off.set("x", str(gx)); off.set("y", str(gy))
    ext   = etree.SubElement(xfrm, qn("a:ext")); ext.set("cx", str(gcx)); ext.set("cy", str(gcy))
    chOff = etree.SubElement(xfrm, qn("a:chOff")); chOff.set("x", str(gx)); chOff.set("y", str(gy))
    chExt = etree.SubElement(xfrm, qn("a:chExt")); chExt.set("cx", str(gcx)); chExt.set("cy", str(gcy))

    for shape in shapes:
        elem = shape._element
        sp_tree.remove(elem)
        grp_sp.append(elem)


def _instance_icon_size(placement, part_size, instance, view: str, paths: AppPaths) -> tuple[float, float]:
    if placement.size_override and "w" in placement.size_override and "h" in placement.size_override:
        size_w = float(placement.size_override["w"])
        size_h = float(placement.size_override["h"])
        if instance.orientation == "v":
            size_w, size_h = size_h, size_w
        return size_w, size_h
    return get_icon_size(part_size, placement.render_kind, instance.orientation, view, instance.asset_path, paths=paths)


def _build_accessory_map(plan) -> dict[str, list[str]]:
    """Map parent part name → list of accessory part names present in the build."""
    accessory_map: dict[str, list[str]] = {}
    for pp in plan.planned_parts:
        if pp.accessory_of:
            accessory_map.setdefault(pp.accessory_of, []).append(pp.part_name)
    return accessory_map


def render_plan_to_ppt(plan, paths: AppPaths | None = None) -> Path:
    active_paths = paths or ensure_workspace()
    template = active_paths.templates_dir / "build_sheet_template.pptx"
    project_id = plan.project.get("ProjectID", "UNKNOWN")
    out_path = active_paths.workspace_output_dir / f"VehicleBuilder_{project_id}_v7.pptx"

    shutil.copyfile(template, out_path)
    prs = Presentation(out_path)
    overview = prs.slides[0]
    view_slides = {view: prs.slides[index + 1] for index, view in enumerate(VIEWS)}
    notes_slide = prs.slides[5]

    fill_overview(overview, _project_shim(plan))
    accessory_map = _build_accessory_map(plan)

    for view in VIEWS:
        slide = view_slides[view]
        vehicle_pic_shape, img_box = place_vehicle_image(slide, plan.project.get("VehicleType", "PIU"), view)
        vehicle_pic_element = vehicle_pic_shape._element if vehicle_pic_shape else None
        if img_box is None:
            place_legend(slide, [], [], accessory_map)
            continue

        used_centers = []
        collision = Inches(0.18)
        specify_palettes: list[str] = []
        rendered_part_names: set[str] = set()

        for planned_part in plan.planned_parts:
            for placement in planned_part.placements:
                if placement.view != view or not placement.instances:
                    continue

                if placement.color_profile == "specify_palette":
                    category = placement.instances[0].color_token
                    if category not in specify_palettes:
                        specify_palettes.append(category)
                    continue

                base_cx, base_cy = _position_from_anchor(placement.anchor, img_box)
                part_size = SimpleNamespace(name=placement.part_name, size_class=placement.size_class)
                first_instance = placement.instances[0]
                if placement.render_kind in ("equipment", "bar") and not first_instance.asset_path:
                    continue

                size_w, _ = _instance_icon_size(placement, part_size, first_instance, view, active_paths)

                # h_spacing / v_spacing: use saved value or auto-compute from icon width
                # h_spacing_units controls what the value is relative to:
                #   "relative_image"  → fraction of the vehicle image dimension (legacy default)
                #   "icon_width"      → fraction of the rendered icon size (use 1.0 for edge-to-edge)
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
                        _, size_h = _instance_icon_size(placement, part_size, first_instance, view, active_paths)
                        v_spacing_emu = int(Inches(size_h) * placement.v_spacing)
                    else:
                        v_spacing_emu = int(img_box[3] * placement.v_spacing)
                else:
                    v_spacing_emu = h_spacing_emu  # symmetric fallback

                positions = _slot_positions(
                    placement.pattern, len(placement.instances),
                    base_cx, base_cy, img_box,
                    h_spacing_emu, v_spacing_emu,
                    slot_roles=[inst.slot_role for inst in placement.instances],
                )

                placement_shapes: list = []

                for slot_idx, (instance, (px, py)) in enumerate(zip(placement.instances, positions)):
                    if not instance.asset_path:
                        continue
                    icon_path = active_paths.workspace_assets_dir / instance.asset_path
                    if not icon_path.exists():
                        continue

                    instance_w, instance_h = _instance_icon_size(placement, part_size, instance, view, active_paths)
                    icon_w = Inches(instance_w)
                    icon_h = Inches(instance_h)

                    adjusted_x = px
                    adjusted_y = py
                    # Skip collision nudging for group_shapes placements — lamps are
                    # intentionally packed edge-to-edge and should never be nudged apart.
                    if not placement.group_shapes:
                        nudge = Inches(0.30)
                        for other_x, other_y in used_centers:
                            if abs(adjusted_x - other_x) < collision and abs(adjusted_y - other_y) < collision:
                                adjusted_x += nudge
                                nudge += Inches(0.30)
                    used_centers.append((adjusted_x, adjusted_y))

                    pic = slide.shapes.add_picture(
                        str(icon_path),
                        adjusted_x - icon_w // 2,
                        adjusted_y - icon_h // 2,
                        width=icon_w,
                        height=icon_h,
                    )

                    # Determine per-instance flip_h: base flip XOR mirrored-side flip
                    # positive_x / driver = right side of image in front view
                    is_mirrored_side = (
                        placement.flip_mirrored_h
                        and placement.pattern == "mirror"
                        and instance.slot_role in ("driver", "positive_x")
                    )
                    instance_flip_h = placement.flip_h ^ is_mirrored_side
                    # Mirror rotation for right-side (driver/positive_x) instances
                    is_right_side = (
                        placement.pattern == "mirror"
                        and instance.slot_role in ("driver", "positive_x")
                    )
                    instance_rotation = (360 - placement.rotation) % 360 if is_right_side and placement.rotation else placement.rotation
                    _apply_shape_transforms(pic, instance_rotation, instance_flip_h, placement.flip_v)

                    if placement.behind_vehicle and vehicle_pic_element is not None:
                        _move_shape_behind(slide, pic, vehicle_pic_element)

                    placement_shapes.append(pic)
                    rendered_part_names.add(planned_part.part_name)

                if placement.group_shapes and len(placement_shapes) >= 2:
                    _group_shapes(slide, placement_shapes)

        placed_legend = []
        seen_placed: set[tuple] = set()
        for pp in plan.planned_parts:
            for pl in pp.placements:
                if pl.view != view:
                    continue
                if pp.part_name not in rendered_part_names and pl.color_profile != "specify_palette":
                    continue
                key = (pp.part_name, pl.location_key)
                if key in seen_placed:
                    continue
                seen_placed.add(key)
                accessories = accessory_map.get(pp.part_name, [])
                placed_legend.append(_legend_item(pp.part_name, pl.location_key, pp.raw.notes, accessories))

        unplaced_legend = _unplaced_for_view(plan, view)
        palette_offset = 0
        for category in specify_palettes:
            consumed = place_specify_palette(slide, category, img_box, y_offset_emu=palette_offset)
            if consumed:
                palette_offset += consumed

        place_legend(slide, placed_legend, unplaced_legend, accessory_map)

    fill_notes(notes_slide, plan.notes)
    prs.save(out_path)
    return out_path
