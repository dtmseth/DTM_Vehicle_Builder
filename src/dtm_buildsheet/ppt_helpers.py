from __future__ import annotations

import json

from lxml import etree
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from .paths import AppPaths, ensure_workspace


_manifest_cache: dict | None = None


def _load_manifest(paths: AppPaths | None = None) -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        active_paths = paths or ensure_workspace()
        try:
            _manifest_cache = json.loads((active_paths.workspace_config_dir / "asset_manifest.json").read_text("utf-8"))
        except Exception:
            _manifest_cache = {}
    return _manifest_cache


DTM_NAVY = RGBColor(0x1E, 0x27, 0x61)
DTM_GRAY = RGBColor(0x55, 0x55, 0x55)
DTM_DARKTEXT = RGBColor(0x1A, 0x1A, 0x1A)

VIEWS = ["front", "side", "top", "rear"]

PALETTE_TOKENS: dict[str, list[str]] = {
    "single": ["red", "blue", "white", "amber", "green"],
    "duo": ["red-white", "blue-white", "red-amber", "blue-amber", "red-green", "amber-white", "green-white", "green-amber"],
    "trio": ["red-blue-white", "red-blue-amber", "red-amber-white", "red-green-white", "blue-amber-white", "blue-green-white"],
}

BAR_SIZES = {"front": (4.110, 0.130), "rear": (4.110, 0.130), "side": (0.708, 0.12)}
BAR_TOP_SIZES = {
    "bar_roof_top": (0.64, 2.7600),
    "bar_interior-front": (0.270, 2.53),
    "bar_interior-rear": (0.250, 2.000),
}
EQUIP_SIZES = {
    "Push Bumper": {"front": (3.128, 2.870), "side": (0.373, 1.353), "top": (0.342, 1.434)},
    "Pit Bar": {"front": (3.128, 2.870), "side": (3.128, 2.870)},
}


def get_icon_size(part, icon_type, orient, view, icon_path_str="", paths: AppPaths | None = None):
    if icon_type == "equipment":
        equip = EQUIP_SIZES.get(part.name, {})
        if view in equip:
            return equip[view]
        if not icon_path_str:
            return (1.0, 1.0)
        from PIL import Image as PILImage

        with PILImage.open((paths or ensure_workspace()).workspace_assets_dir / icon_path_str) as img:
            image_w, image_h = img.size
        ratio = image_w / image_h
        max_dim = 1.0
        return (max_dim, max_dim / ratio) if ratio > 1 else (max_dim * ratio, max_dim)

    if icon_type == "bar":
        if view == "top":
            for key, size in BAR_TOP_SIZES.items():
                if key.replace("_", "-") in icon_path_str.replace("_", "-"):
                    return size
            return (0.40, 2.20)
        if view in BAR_SIZES:
            return BAR_SIZES[view]
        return (2.80, 0.25)

    size_class = getattr(part, "size_class", "sm")
    defs = _load_manifest(paths).get("size_rule_definitions", {})
    class_def = defs.get(size_class) or defs.get("sm", {})
    views_data = class_def.get("views", {})
    view_data = views_data.get(view) or views_data.get("front")
    if view_data:
        w, h = float(view_data["w"]), float(view_data["h"])
        return (h, w) if orient == "v" else (w, h)
    return (0.244, 0.085) if orient == "h" else (0.085, 0.244)


def _lock_picture_position(picture) -> None:
    c_nv_pic_pr = picture._element.find(".//" + qn("p:cNvPicPr"))
    if c_nv_pic_pr is None:
        return
    locks = c_nv_pic_pr.find(qn("a:picLocks"))
    if locks is None:
        locks = etree.SubElement(c_nv_pic_pr, qn("a:picLocks"))
    locks.set("noMove", "1")
    locks.set("noResize", "1")


def find_shape(slide, name):
    for shape in slide.shapes:
        if shape.name == name:
            return shape
    return None


def slot_geometry(shape):
    left, top, width, height = shape.left, shape.top, shape.width, shape.height
    element = shape._element
    element.getparent().remove(element)
    return left, top, width, height


def fill_overview(slide, project):
    info_shape = find_shape(slide, "PROJECT_INFO_BLOCK")
    if info_shape:
        info_shape.text_frame.clear()
        text_frame = info_shape.text_frame
        text_frame.word_wrap = True
        paragraph = text_frame.paragraphs[0]
        paragraph.alignment = PP_ALIGN.LEFT
        run = paragraph.add_run()
        run.text = project.info.get("Agency", "—")
        run.font.size = Pt(20)
        run.font.bold = True
        run.font.color.rgb = DTM_NAVY

        sub = text_frame.add_paragraph()
        sub_run = sub.add_run()
        sub_run.text = f"Quote {project.info.get('QuoteNumber', '')}  •  {project.info.get('ProjectID', '')}"
        sub_run.font.size = Pt(11)
        sub_run.font.color.rgb = DTM_GRAY


def place_vehicle_image(slide, vehicle_type, view):
    """Return (picture_shape | None, img_box | None). Box is (left, top, w, h) in EMU."""
    slot = find_shape(slide, "VEHICLE_IMAGE_SLOT")
    if not slot:
        return None, None
    slot_left, slot_top, slot_w, slot_h = slot_geometry(slot)
    png = ensure_workspace().workspace_assets_dir / "vehicles" / f"{vehicle_type}_{view}.png"
    if not png.exists():
        return None, (slot_left, slot_top, slot_w, slot_h)

    from PIL import Image as PILImage

    with PILImage.open(png) as img:
        img_w, img_h = img.size

    img_ratio = img_w / img_h
    slot_ratio = slot_w / slot_h
    if img_ratio > slot_ratio:
        final_w = slot_w
        final_h = int(slot_w / img_ratio)
        final_left = slot_left
        final_top = slot_top + (slot_h - final_h) // 2
    else:
        final_h = slot_h
        final_w = int(slot_h * img_ratio)
        final_left = slot_left + (slot_w - final_w) // 2
        final_top = slot_top

    pic = slide.shapes.add_picture(str(png), final_left, final_top, width=final_w, height=final_h)
    _lock_picture_position(pic)
    return pic, (final_left, final_top, final_w, final_h)


def place_legend(slide, placed, unplaced, accessory_map: dict | None = None):
    slot = find_shape(slide, "LEGEND_SLOT")
    if not slot:
        return
    left, top, width, height = slot_geometry(slot)
    text_box = slide.shapes.add_textbox(left, top, width, height)
    tf = text_box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.12)
    tf.margin_right = Inches(0.12)
    tf.margin_top = Inches(0.08)

    header = tf.paragraphs[0]
    header.alignment = PP_ALIGN.LEFT
    hr = header.add_run()
    hr.text = "On this view"
    hr.font.size = Pt(13)
    hr.font.bold = True
    hr.font.color.rgb = DTM_NAVY

    if not placed and not unplaced:
        p = tf.add_paragraph()
        r = p.add_run()
        r.text = "(no parts for this view)"
        r.font.size = Pt(10)
        r.font.italic = True
        r.font.color.rgb = DTM_GRAY
        return

    acc = accessory_map or {}
    # Track which accessories have been nested so they don't appear standalone
    nested_accessories: set[str] = set()

    for part in placed:
        p = tf.add_paragraph()
        run = p.add_run()
        run.text = f"{part.name}"
        run.font.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = DTM_NAVY
        if getattr(part, "location", ""):
            loc = p.add_run()
            loc.text = f"\n   @ {part.location}"
            loc.font.size = Pt(8)
            loc.font.color.rgb = DTM_GRAY
        if getattr(part, "notes", ""):
            note_run = p.add_run()
            note_run.text = f"\n   {part.notes}"
            note_run.font.size = Pt(8)
            note_run.font.italic = True
            note_run.font.color.rgb = DTM_GRAY
        # Inline accessories for this part
        for acc_name in acc.get(part.name, []):
            nested_accessories.add(acc_name)
            acc_p = tf.add_paragraph()
            acc_r = acc_p.add_run()
            acc_r.text = f"  + {acc_name}"
            acc_r.font.size = Pt(8)
            acc_r.font.italic = True
            acc_r.font.color.rgb = DTM_GRAY

    if unplaced:
        p = tf.add_paragraph()
        r = p.add_run()
        r.text = "\nNot shown on diagram"
        r.font.size = Pt(10)
        r.font.italic = True
        r.font.color.rgb = RGBColor(0xB8, 0x3A, 0x3A)
        for part in unplaced:
            up = tf.add_paragraph()
            run = up.add_run()
            run.text = f"{part.name} @ {getattr(part, 'location', '?') or '?'}"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0xB8, 0x3A, 0x3A)


def place_specify_palette(slide, category: str, img_box, y_offset_emu: int = 0):
    tokens = PALETTE_TOKENS.get(category, [])
    if not tokens:
        return 0

    left_px, top_px, width_px, height_px = img_box
    icon_w = Inches(0.45)
    icon_h = Inches(0.114)
    label_h = Inches(0.13)
    col_w = Inches(0.54)
    max_cols = 10
    row_h = icon_h + label_h + Inches(0.04)
    palette_top = top_px + height_px + Inches(0.18) + y_offset_emu
    palette_left = left_px

    header = slide.shapes.add_textbox(palette_left, palette_top - Inches(0.17), Inches(4), Inches(0.15))
    tf = header.text_frame
    r = tf.paragraphs[0].add_run()
    r.text = f"Specify {category} — keep one, delete the rest"
    r.font.size = Pt(7)
    r.font.italic = True
    r.font.color.rgb = RGBColor(0xB8, 0x3A, 0x3A)

    rendered = 0
    for token in tokens:
        png_path = ensure_workspace().workspace_assets_dir / "lights" / f"sm_{token}_h.png"
        if not png_path.exists():
            continue
        col = rendered % max_cols
        row = rendered // max_cols
        x = palette_left + col * col_w
        y = palette_top + row * row_h
        slide.shapes.add_picture(str(png_path), x, y, width=icon_w, height=icon_h)
        lbl = slide.shapes.add_textbox(x, y + icon_h + Inches(0.01), col_w, label_h)
        tf = lbl.text_frame
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r2 = p.add_run()
        r2.text = token
        r2.font.size = Pt(6)
        r2.font.color.rgb = DTM_GRAY
        rendered += 1

    rows_used = (rendered + max_cols - 1) // max_cols if rendered else 0
    return rows_used * row_h + Inches(0.18)


def fill_notes(slide, notes):
    slot = find_shape(slide, "NOTES_SLOT")
    if not slot:
        return
    left, top, width, height = slot_geometry(slot)
    text_box = slide.shapes.add_textbox(left, top, width, height)
    tf = text_box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.15)
    tf.margin_right = Inches(0.15)
    tf.margin_top = Inches(0.1)
    if not notes:
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = "(no notes)"
        r.font.size = Pt(12)
        r.font.italic = True
        r.font.color.rgb = DTM_GRAY
        return

    for index, note in enumerate(notes):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        num = p.add_run()
        num.text = f"{index + 1}.  "
        num.font.bold = True
        num.font.size = Pt(12)
        num.font.color.rgb = DTM_NAVY
        body = p.add_run()
        body.text = note
        body.font.size = Pt(12)
        body.font.color.rgb = DTM_DARKTEXT
