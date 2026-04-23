from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from pptx import Presentation
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


def _legend_item(part_name: str, location: str = "", notes: str = "") -> SimpleNamespace:
    return SimpleNamespace(name=part_name, location=location, notes=notes)


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


def _slot_positions(pattern: str, slot_count: int, base_cx, base_cy, img_box, spacing):
    left, _, width, _ = img_box
    if slot_count <= 1 or pattern == "single":
        return [(base_cx, base_cy)]
    if pattern == "horizontal":
        total_w = spacing * (slot_count - 1)
        start_x = base_cx - total_w // 2
        return [(start_x + int(index * spacing), base_cy) for index in range(slot_count)]
    if pattern == "mirror":
        center_x = left + width // 2
        offset_x = abs(base_cx - center_x)
        if slot_count == 2:
            return [(center_x - offset_x, base_cy), (center_x + offset_x, base_cy)]
        half = slot_count // 2
        positions = []
        for index in range(half):
            offset = offset_x + int(index * spacing)
            positions.append((center_x - offset, base_cy))
            positions.append((center_x + offset, base_cy))
        return positions
    return [(base_cx, base_cy)]


def _instance_icon_size(placement, part_size, instance, view: str, paths: AppPaths) -> tuple[float, float]:
    if placement.size_override and "w" in placement.size_override and "h" in placement.size_override:
        size_w = float(placement.size_override["w"])
        size_h = float(placement.size_override["h"])
        if instance.orientation == "v":
            size_w, size_h = size_h, size_w
        return size_w, size_h
    return get_icon_size(part_size, placement.render_kind, instance.orientation, view, instance.asset_path, paths=paths)


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

    for view in VIEWS:
        slide = view_slides[view]
        img_box = place_vehicle_image(slide, plan.project.get("VehicleType", "PIU"), view)
        if img_box is None:
            place_legend(slide, [], [])
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
                spacing = int(img_box[2] * placement.spacing) if placement.spacing is not None and placement.spacing > 0 else Inches(size_w + 0.03)
                positions = _slot_positions(placement.pattern, len(placement.instances), base_cx, base_cy, img_box, spacing)

                for instance, (px, py) in zip(placement.instances, positions):
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
                    nudge = Inches(0.30)
                    for other_x, other_y in used_centers:
                        if abs(adjusted_x - other_x) < collision and abs(adjusted_y - other_y) < collision:
                            adjusted_x += nudge
                            nudge += Inches(0.30)
                    used_centers.append((adjusted_x, adjusted_y))

                    slide.shapes.add_picture(str(icon_path), adjusted_x - icon_w // 2, adjusted_y - icon_h // 2, width=icon_w, height=icon_h)
                    rendered_part_names.add(planned_part.part_name)

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
                placed_legend.append(_legend_item(pp.part_name, pl.location_key, pp.raw.notes))

        unplaced_legend = _unplaced_for_view(plan, view)
        palette_offset = 0
        for category in specify_palettes:
            consumed = place_specify_palette(slide, category, img_box, y_offset_emu=palette_offset)
            if consumed:
                palette_offset += consumed

        place_legend(slide, placed_legend, unplaced_legend)

    fill_notes(notes_slide, plan.notes)
    prs.save(out_path)
    return out_path
