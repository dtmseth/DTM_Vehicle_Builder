from __future__ import annotations

import json
import tempfile
from pathlib import Path

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
            _manifest_cache = json.loads(
                (active_paths.workspace_config_dir / "asset_manifest.json").read_text("utf-8")
            )
        except Exception:
            _manifest_cache = {}
    return _manifest_cache


# ── Brand colors ──────────────────────────────────────────────────────────────
DTM_NAVY      = RGBColor(0x1E, 0x27, 0x61)
DTM_GRAY      = RGBColor(0x55, 0x55, 0x55)
DTM_DARKTEXT  = RGBColor(0x1A, 0x1A, 0x1A)
DTM_ORANGE    = RGBColor(0xC8, 0x60, 0x00)
DTM_ORANGE_BG = RGBColor(0xFF, 0xF0, 0xD4)
DTM_ALT_BG    = RGBColor(0xF2, 0xF2, 0xF5)
DTM_RED       = RGBColor(0xB8, 0x3A, 0x3A)
# Color system: BLUE = NEW, ORANGE = REUSED
TAG_NEW       = RGBColor(0x1A, 0x6F, 0xC8)   # blue  — new / installed
TAG_REUSED    = RGBColor(0xC8, 0x60, 0x00)   # orange — reused / transferred
_WHITE        = RGBColor(0xFF, 0xFF, 0xFF)
_LIGHT_GRAY   = RGBColor(0xCC, 0xCC, 0xCC)
_PANEL_BG     = RGBColor(0xF5, 0xF6, 0xFA)
_REUSED_BG    = RGBColor(0xFF, 0xF3, 0xE8)   # warm tint for reused parts
_NEW_BG       = RGBColor(0xF0, 0xF6, 0xFF)   # cool tint for new parts

# Slide dimensions (from template: 13.333" × 7.5")
SLIDE_W_EMU = 12191695
SLIDE_H_EMU = 6858000
FOOTER_H    = Inches(0.42)   # sticky bottom bar height (consistent on all slides)

VIEWS = ["front", "side", "top", "rear"]

PALETTE_TOKENS: dict[str, list[str]] = {
    "single": ["red", "blue", "white", "amber", "green"],
    "duo": ["red-white", "blue-white", "red-amber", "blue-amber", "red-green",
            "amber-white", "green-white", "green-amber"],
    "trio": ["red-blue-white", "red-blue-amber", "red-amber-white",
             "red-green-white", "blue-amber-white", "blue-green-white"],
}

BAR_SIZES = {"front": (4.110, 0.130), "rear": (4.110, 0.130), "side": (0.708, 0.12)}
BAR_TOP_SIZES = {
    "bar_roof_top":          (0.64, 2.7600),
    "bar_interior-front":    (0.270, 2.53),
    "bar_interior-rear":     (0.250, 2.000),
}
EQUIP_SIZES = {
    "Push Bumper": {"front": (3.128, 2.870), "side": (0.373, 1.353), "top": (0.342, 1.434)},
    "Pit Bar":     {"front": (3.128, 2.870), "side": (3.128, 2.870)},
}

# ── Manifest layout ───────────────────────────────────────────────────────────
MANIFEST_LIGHT_CATS = {"warning_light", "scene_light", "light_bar"}

MANIFEST_COL_HEADERS   = ["PART", "MANUFACTURER", "MODEL / PART #", "QTY",
                           "COLOR / LENS", "LOCATION", "SOURCE", "NOTES"]
MANIFEST_COL_WIDTHS_IN = [2.0, 1.3, 1.6, 0.35, 1.2, 1.45, 1.35, 3.08]

MANIFEST_TABLE_LEFT  = Inches(0.5)
MANIFEST_TABLE_TOP   = Inches(1.10)
MANIFEST_TABLE_W     = sum(Inches(w) for w in MANIFEST_COL_WIDTHS_IN)
MANIFEST_HDR_ROW_H   = Inches(0.34)
MANIFEST_DATA_ROW_H  = Inches(0.34)
MANIFEST_SEC_ROW_H   = Inches(0.34)


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_reused(part) -> bool:
    noru   = getattr(part, "new_or_used", "").strip().lower()
    source = getattr(part, "source",      "").strip()
    return noru not in ("new", "n", "") or bool(source)


def _source_label(part) -> str:
    noru   = getattr(part, "new_or_used", "").strip()
    source = getattr(part, "source",      "").strip()
    if source and noru.lower() not in ("new", "n", ""):
        return f"Reused — {source}"
    if source:
        return f"From: {source}"
    if noru:
        return noru
    return "New"


def _color_label(part) -> str:
    """Return color string only (no lens)."""
    return getattr(part, "color", "").strip()


def _lens_label(part) -> str:
    """Return lens string only (no 'Lens:' prefix — the value already contains 'Lens')."""
    return getattr(part, "lens", "").strip()


def _color_lens_label(part) -> str:
    """Legacy combined helper used by manifest table. Returns 'Color  /  Lens' string."""
    color = _color_label(part)
    lens  = _lens_label(part)
    parts = []
    if color:
        parts.append(color)
    if lens:
        parts.append(lens)
    return "  /  ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Logo
# ─────────────────────────────────────────────────────────────────────────────

_cropped_logo_cache: Path | None = None


def _find_logo(paths: AppPaths | None = None) -> Path | None:
    active = paths or ensure_workspace()
    candidates = [
        active.workspace_assets_dir / "dtm_logo.png",
        active.assets_dir            / "dtm_logo.png",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _get_cropped_logo(logo_path: Path) -> Path:
    global _cropped_logo_cache
    if _cropped_logo_cache and _cropped_logo_cache.exists():
        return _cropped_logo_cache
    try:
        from PIL import Image
        with Image.open(logo_path) as img:
            if img.mode == "RGBA":
                bbox = img.getbbox()
                if bbox and bbox != (0, 0, img.width, img.height):
                    cropped = img.crop(bbox)
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    cropped.save(tmp.name, "PNG")
                    _cropped_logo_cache = Path(tmp.name)
                    return _cropped_logo_cache
    except Exception:
        pass
    return logo_path


def place_logo(slide, paths: AppPaths | None = None, cover: bool = False) -> None:
    """Place the DTM logo in the top-right header band.

    cover=True makes it slightly larger for the cover page.
    """
    logo_path = _find_logo(paths)
    if not logo_path:
        return
    use_path = _get_cropped_logo(logo_path)
    try:
        from PIL import Image
        with Image.open(use_path) as img:
            img_w, img_h = img.size
        ratio    = img_w / img_h
        logo_h   = Inches(0.86) if cover else Inches(0.72)
        logo_w   = int(logo_h * ratio)
        margin   = Inches(0.12)
        logo_top = Inches(0.05)
        logo_left = SLIDE_W_EMU - logo_w - margin
        slide.shapes.add_picture(str(use_path), logo_left, logo_top,
                                 width=logo_w, height=logo_h)
    except Exception:
        pass


def place_logo_bottom(slide, paths: AppPaths | None = None) -> None:
    """Place the DTM logo just above the footer bar (for side/top view slides)."""
    logo_path = _find_logo(paths)
    if not logo_path:
        return
    use_path = _get_cropped_logo(logo_path)
    try:
        from PIL import Image
        with Image.open(use_path) as img:
            img_w, img_h = img.size
        ratio     = img_w / img_h
        logo_h    = Inches(0.30)
        logo_w    = int(logo_h * ratio)
        margin_r  = Inches(0.18)
        margin_b  = Inches(0.06)
        logo_top  = SLIDE_H_EMU - FOOTER_H - logo_h - margin_b
        logo_left = SLIDE_W_EMU - logo_w - margin_r
        slide.shapes.add_picture(str(use_path), logo_left, logo_top,
                                 width=logo_w, height=logo_h)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Header / footer update (for template slides — view + notes slides)
# ─────────────────────────────────────────────────────────────────────────────

def add_slide_footer_bar(slide, footer_text: str) -> None:
    """Remove the template's transparent TextBox 5/4 and replace with a visible navy bar.

    Called for every view slide and the notes slide. Manifest slides build their
    own footer bar directly inside _make_manifest_slide.
    """
    for name in ("TextBox 2", "TextBox 4", "TextBox 5"):
        shape = find_shape(slide, name)
        if shape:
            shape._element.getparent().remove(shape._element)

    ftr_top = SLIDE_H_EMU - FOOTER_H
    ftr = slide.shapes.add_textbox(0, ftr_top, SLIDE_W_EMU, FOOTER_H)
    ftr.fill.solid()
    ftr.fill.fore_color.rgb = DTM_NAVY
    tf = ftr.text_frame
    tf.margin_left = Inches(0.3)
    tf.margin_top  = Inches(0.10)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = footer_text
    r.font.size      = Pt(10)
    r.font.bold      = True
    r.font.color.rgb = _WHITE


def update_slide_header_footer(slide, title: str, subtitle: str = "", footer: str = "") -> None:
    """Replace the template header shapes with a full-width navy header band.

    The template's TextBox 1 has no fill (transparent), so white text would be
    invisible against the white slide background.  We delete TextBox 1/2 and
    create a fresh navy header that matches the cover/manifest slide style.
    TextBox 4/5 (footer) are left for add_slide_footer_bar() to replace.
    """
    for name in ("TextBox 1", "TextBox 2"):
        shape = find_shape(slide, name)
        if shape:
            shape._element.getparent().remove(shape._element)

    HDR_H = Inches(0.62)
    hdr = slide.shapes.add_textbox(0, 0, SLIDE_W_EMU, HDR_H)
    hdr.name = "DTM_SLIDE_HEADER"  # avoid collision with add_slide_footer_bar deletions
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = DTM_NAVY
    tf = hdr.text_frame
    tf.margin_left = Inches(0.3)
    tf.margin_top  = Inches(0.08)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = title
    r.font.size      = Pt(11)
    r.font.bold      = True
    r.font.color.rgb = _WHITE
    if subtitle:
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text           = subtitle
        r2.font.size      = Pt(11)
        r2.font.color.rgb = RGBColor(0xCC, 0xCC, 0xFF)


# ─────────────────────────────────────────────────────────────────────────────
# Layout helpers
# ─────────────────────────────────────────────────────────────────────────────

def _textbox(slide, left, top, width, height, text, font_size=10,
             bold=False, color=DTM_DARKTEXT, italic=False,
             align=PP_ALIGN.LEFT, wrap=True):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf  = box.text_frame
    tf.word_wrap = wrap
    p   = tf.paragraphs[0]
    p.alignment = align
    r   = p.add_run()
    r.text           = text
    r.font.size      = Pt(font_size)
    r.font.bold      = bold
    r.font.italic    = italic
    r.font.color.rgb = color
    return box


def _kv_block(slide, items: list[tuple[str, str]], left, top, width,
              line_h: float = 0.26) -> int:
    y = top
    for key, value in items:
        if not value:
            continue
        box = slide.shapes.add_textbox(left, y, width, Inches(line_h + 0.06))
        tf  = box.text_frame
        tf.word_wrap = True
        p   = tf.paragraphs[0]
        kr  = p.add_run()
        kr.text           = f"{key}:  "
        kr.font.size      = Pt(10)
        kr.font.bold      = True
        kr.font.color.rgb = DTM_NAVY
        vr  = p.add_run()
        vr.text           = value
        vr.font.size      = Pt(12)
        vr.font.color.rgb = DTM_DARKTEXT
        y += Inches(line_h)
    return y


def _divider(slide, y_emu: int, width_in: float = 12.4, margin_left: float = 0.35) -> None:
    bar = slide.shapes.add_textbox(Inches(margin_left), y_emu, Inches(width_in), Inches(0.025))
    bar.fill.solid()
    bar.fill.fore_color.rgb = _LIGHT_GRAY


def _add_border(shape, color: RGBColor = _LIGHT_GRAY, width_pt: float = 0.75) -> None:
    sp_pr = shape._element.find(qn("p:spPr"))
    if sp_pr is None:
        return
    for old in sp_pr.findall(qn("a:ln")):
        sp_pr.remove(old)
    ln  = etree.SubElement(sp_pr, qn("a:ln"))
    ln.set("w", str(int(width_pt * 12700)))
    sf  = etree.SubElement(ln,  qn("a:solidFill"))
    clr = etree.SubElement(sf,  qn("a:srgbClr"))
    clr.set("val", str(color))


def _remove_border(shape) -> None:
    sp_pr = shape._element.find(qn("p:spPr"))
    if sp_pr is None:
        return
    for old in sp_pr.findall(qn("a:ln")):
        sp_pr.remove(old)
    ln = etree.SubElement(sp_pr, qn("a:ln"))
    etree.SubElement(ln, qn("a:noFill"))


def _stripe_box(slide, left, top, width, height, color: RGBColor) -> None:
    box = slide.shapes.add_textbox(left, top, width, height)
    box.fill.solid()
    box.fill.fore_color.rgb = color
    _remove_border(box)


def _card_bg(slide, left, top, width, height, color: RGBColor) -> None:
    box = slide.shapes.add_textbox(left, top, width, height)
    box.fill.solid()
    box.fill.fore_color.rgb = color
    _remove_border(box)


# ─────────────────────────────────────────────────────────────────────────────
# Cover slide
# ─────────────────────────────────────────────────────────────────────────────

def _find_part(parts, *names) -> object | None:
    """Return the first part whose name matches any of the given names (case-insensitive)."""
    targets = {n.lower() for n in names}
    for p in parts:
        if getattr(p, "name", "").lower() in targets:
            return p
    return None


def fill_overview(slide, project) -> None:
    info    = project.info
    new_v   = info.get("NewVehicle",      {})
    exist_v = info.get("ExistingVehicle", {})
    parts   = project.parts

    agency     = info.get("Agency",    "—")
    build_type = info.get("BuildType", "")
    # Fall back to ExistingVehicle when NewVehicle fields are absent
    year      = new_v.get("YEAR",      "") or exist_v.get("YEAR",      "")
    make      = new_v.get("MAKE",      "") or exist_v.get("MAKE",      "")
    model     = (new_v.get("MODEL",     "") or exist_v.get("MODEL",     "")
                 or info.get("VehicleType", ""))
    sub_model = new_v.get("SUB MODEL", "") or exist_v.get("SUB MODEL", "")
    unit_id   = (new_v.get("UNIT ID", new_v.get("UNIT", ""))
                 or exist_v.get("UNIT ID", exist_v.get("UNIT", "")))
    vin       = new_v.get("VIN",       "") or exist_v.get("VIN",       "")
    quote_num = info.get("QuoteNumber",    "")
    sales_rep = info.get("SalesRep",       "")

    # Remove slot shapes and template text boxes (prevents double footer / white-on-white)
    for name in ("PROJECT_INFO_BLOCK", "PARTS_TABLE_SLOT",
                 "TextBox 1", "TextBox 2", "TextBox 4", "TextBox 5"):
        shape = find_shape(slide, name)
        if shape:
            shape._element.getparent().remove(shape._element)

    # ── Navy header bar ───────────────────────────────────────────────────────
    hdr_title = "FLEET VEHICLE SPECIFICATION PACKAGE"
    if build_type:
        hdr_title += f"   •   {build_type.upper()}"
    hdr = slide.shapes.add_textbox(0, 0, SLIDE_W_EMU, Inches(0.95))
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = DTM_NAVY
    tf = hdr.text_frame
    tf.margin_left = Inches(0.3)
    tf.margin_top  = Inches(0.21)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = hdr_title
    r.font.size      = Pt(18)
    r.font.bold      = True
    r.font.color.rgb = _WHITE

    # ── Sticky footer bar — prominent, full vehicle identity ──────────────────
    vehicle_line = " ".join(filter(None, [year, make, model, sub_model]))
    unit_str     = f"Unit #{unit_id}" if unit_id else ""
    footer_parts = list(filter(None, [agency, vehicle_line, unit_str, "DTM Fleet Service"]))
    footer_text  = "   •   ".join(footer_parts)

    ftr_top = SLIDE_H_EMU - FOOTER_H
    ftr = slide.shapes.add_textbox(0, ftr_top, SLIDE_W_EMU, FOOTER_H)
    ftr.fill.solid()
    ftr.fill.fore_color.rgb = DTM_NAVY
    tf2 = ftr.text_frame
    tf2.margin_left = Inches(0.3)
    tf2.margin_top  = Inches(0.10)
    p2 = tf2.paragraphs[0]
    r2 = p2.add_run()
    r2.text           = footer_text
    r2.font.size      = Pt(10)
    r2.font.bold      = True
    r2.font.color.rgb = _WHITE

    # ── H1: Agency name — dominant ────────────────────────────────────────────
    L = Inches(0.45)
    y = Inches(1.05)

    _textbox(slide, L, y, Inches(10.2), Inches(0.82),
             agency, font_size=48, bold=True, color=DTM_NAVY)
    y += Inches(0.82)

    # ── H2: Vehicle identity ──────────────────────────────────────────────────
    veh_display = " ".join(filter(None, [year, make, model, sub_model]))
    if unit_id:
        veh_display += f"   |   Unit #{unit_id}"
    if build_type:
        veh_display += f"   |   {build_type}"
    _textbox(slide, L, y, Inches(12.0), Inches(0.46),
             veh_display, font_size=24, bold=True,
             color=RGBColor(0x2A, 0x35, 0x80))
    y += Inches(0.46)

    _divider(slide, y, width_in=12.3, margin_left=0.45)
    y += Inches(0.18)

    # ── Two-column block ──────────────────────────────────────────────────────
    col_top  = y
    LEFT_W   = Inches(5.6)
    RIGHT_X  = Inches(6.5)
    RIGHT_W  = Inches(5.85)

    # Left: Quote + Sales info
    reused_count  = sum(1 for p in parts if _is_reused(p))
    install_type  = "Transfer / Retrofit" if reused_count else "New Installation"
    _textbox(slide, L, col_top, LEFT_W, Inches(0.25),
             "QUOTE & SALES INFORMATION", font_size=10, bold=True, color=DTM_NAVY)
    left_y = col_top + Inches(0.25)
    left_y = _kv_block(slide, [
        ("Sales Rep",    sales_rep),
        ("Quote #",      quote_num),
        ("Install Type", install_type),
        ("Other Orders", "0"),
    ], L, left_y, LEFT_W)

    # Right: Vehicle specs — NEW primary card (always) + EXISTING secondary card (orange, if data)
    card_h = Inches(1.75)

    new_year      = new_v.get("YEAR",    "")
    new_make      = new_v.get("MAKE",    "")
    new_model_str = " ".join(filter(None, [new_v.get("MODEL",""), new_v.get("SUB MODEL","")]))
    new_unit      = new_v.get("UNIT ID", new_v.get("UNIT", ""))
    new_vin       = new_v.get("VIN",     "")

    ex_year      = exist_v.get("YEAR",    "")
    ex_make      = exist_v.get("MAKE",    "")
    ex_model_str = " ".join(filter(None, [exist_v.get("MODEL",""), exist_v.get("SUB MODEL","")]))
    ex_unit      = exist_v.get("UNIT ID", exist_v.get("UNIT", ""))
    ex_vin       = exist_v.get("VIN",     "")
    exist_has_data = any([ex_year, ex_make, ex_model_str, ex_unit, ex_vin])

    if exist_has_data:
        CARD_W  = int((RIGHT_W - Inches(0.12)) / 2)
        EXIST_X = RIGHT_X + CARD_W + Inches(0.12)
    else:
        CARD_W  = RIGHT_W
        EXIST_X = None

    # Primary card: NEW VEHICLE (blue border)
    veh_bg = slide.shapes.add_textbox(RIGHT_X, col_top - Inches(0.04), CARD_W, card_h)
    veh_bg.fill.solid()
    veh_bg.fill.fore_color.rgb = _PANEL_BG
    _add_border(veh_bg, TAG_NEW, 1.0)
    _textbox(slide, RIGHT_X + Inches(0.10), col_top, CARD_W - Inches(0.2), Inches(0.25),
             "NEW VEHICLE", font_size=10, bold=True, color=TAG_NEW)
    _kv_block(slide, [
        ("Year",    new_year      or "—"),
        ("Make",    new_make      or "—"),
        ("Model",   new_model_str or "—"),
        ("Unit ID", new_unit      or "—"),
        ("VIN",     new_vin       or "—"),
    ], RIGHT_X + Inches(0.10), col_top + Inches(0.25), CARD_W - Inches(0.2))

    # Secondary card: EXISTING VEHICLE (orange theme, only if data present)
    if exist_has_data:
        ex_bg = slide.shapes.add_textbox(EXIST_X, col_top - Inches(0.04), CARD_W, card_h)
        ex_bg.fill.solid()
        ex_bg.fill.fore_color.rgb = DTM_ORANGE_BG
        _add_border(ex_bg, DTM_ORANGE, 1.0)
        _textbox(slide, EXIST_X + Inches(0.10), col_top, CARD_W - Inches(0.2), Inches(0.25),
                 "EXISTING VEHICLE", font_size=10, bold=True, color=DTM_ORANGE)
        _kv_block(slide, [
            ("Year",    ex_year      or "—"),
            ("Make",    ex_make      or "—"),
            ("Model",   ex_model_str or "—"),
            ("Unit ID", ex_unit      or "—"),
            ("VIN",     ex_vin       or "—"),
        ], EXIST_X + Inches(0.10), col_top + Inches(0.25), CARD_W - Inches(0.2))

    # ── Stats / tiles row ─────────────────────────────────────────────────────
    tiles_top = col_top + card_h + Inches(0.18)

    lights_count = sum(
        getattr(p, "quantity", 1) or 1
        for p in parts
        if getattr(p, "category", "") in {"warning_light", "scene_light"}
        and getattr(p, "render_kind", "") not in ("bar",)
        and "tracer" not in getattr(p, "name", "").lower()
    )

    light_brands = sorted({
        getattr(p, "manufacturer", "").strip()
        for p in parts
        if getattr(p, "category", "") in MANIFEST_LIGHT_CATS
        and getattr(p, "manufacturer", "").strip()
    })
    brands_str = ", ".join(light_brands) if light_brands else "—"

    # --- Cage + Tray combined ---
    cage_part  = _find_part(parts, "front partition", "partition")
    cage_value = (getattr(cage_part, "part_number", "") or "—") if cage_part else "—"
    equip_part = _find_part(parts, "equipment tray")
    if equip_part:
        equip_lines = list(filter(None, [
            getattr(equip_part, "manufacturer", ""),
            getattr(equip_part, "part_number",  ""),
            getattr(equip_part, "location",     ""),
        ]))
        equip_value = " · ".join(equip_lines) if equip_lines else "—"
    else:
        equip_value = "—"

    # --- Lighting System + Camera combined ---
    light_ctrl = _find_part(parts, "light controller", "lights controller")
    if light_ctrl:
        lc_lines = list(filter(None, [
            getattr(light_ctrl, "manufacturer", ""),
            getattr(light_ctrl, "part_number",  ""),
        ]))
        lighting_value = " · ".join(lc_lines) if lc_lines else "—"
    else:
        lighting_value = "—"
    camera_part = _find_part(parts, "camera dvr", "dvr", "camera system")
    if camera_part:
        cam_lines = list(filter(None, [
            getattr(camera_part, "manufacturer", ""),
            getattr(camera_part, "part_number",  ""),
        ]))
        camera_value = " · ".join(cam_lines) if cam_lines else "—"
    else:
        camera_value = ""

    # --- Bumper ---
    _BUMPER_KEYWORDS = ["push bumper", "pit bar", "wing wrap", "wire cover"]
    bumper_parts = [p for p in parts
                    if any(kw in getattr(p, "name", "").lower() for kw in _BUMPER_KEYWORDS)]
    bumper_mfg   = next((getattr(p, "manufacturer", "") for p in bumper_parts
                         if getattr(p, "manufacturer", "")), "")

    def _has(keyword: str) -> bool:
        return any(keyword.lower() in getattr(p, "name", "").lower() for p in bumper_parts)

    # Build bumper inline summary line
    if not bumper_parts:
        bumper_summary = "✗  None"
        bumper_summary_color = DTM_RED
    else:
        items_present  = [lbl for lbl, kw in [("Push Bumper","push bumper"),("Pit Bars","pit bar"),
                                               ("Wing Wraps","wing wrap"),("Wire Covers","wire cover")]
                          if _has(kw)]
        items_absent   = [lbl for lbl, kw in [("Push Bumper","push bumper"),("Pit Bars","pit bar"),
                                               ("Wing Wraps","wing wrap"),("Wire Covers","wire cover")]
                          if not _has(kw)]
        bumper_summary       = None
        bumper_summary_color = DTM_DARKTEXT

    # ── 5-tile row: [Lights] [Reused] [Bumper] [Cage+Tray] [Lighting+Camera] ─
    SLIDE_USABLE_W = SLIDE_W_EMU - L - Inches(0.45)
    N_TILES  = 5
    TILE_GAP = Inches(0.10)
    TILE_W   = (SLIDE_USABLE_W - TILE_GAP * (N_TILES - 1)) / N_TILES

    def _tile_bg(tx, ty, th, bg_color, border_color):
        tb = slide.shapes.add_textbox(tx, ty, TILE_W, th)
        tb.fill.solid()
        tb.fill.fore_color.rgb = bg_color
        _add_border(tb, border_color, 0.5)
        return tb

    def _tile_label(tf, label, color=DTM_NAVY):
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text           = label
        r.font.size      = Pt(10)
        r.font.bold      = True
        r.font.color.rgb = color
        return tf

    def _tile_value(tf, value, font_size=12, bold=False, color=None, italic=False):
        p = tf.add_paragraph()
        r = p.add_run()
        r.text           = value
        r.font.size      = Pt(font_size)
        r.font.bold      = bold
        r.font.italic    = italic
        r.font.color.rgb = color or DTM_GRAY

    # Tile 0: Light Heads count
    tx = L
    BASE_TILE_H = Inches(1.10)
    tb = _tile_bg(tx, tiles_top, BASE_TILE_H, _PANEL_BG, _LIGHT_GRAY)
    tf = tb.text_frame
    tf.word_wrap   = True
    tf.margin_left = Inches(0.10)
    tf.margin_top  = Inches(0.06)
    p = tf.paragraphs[0]
    nr = p.add_run()
    nr.text           = str(lights_count)
    nr.font.size      = Pt(28)
    nr.font.bold      = True
    nr.font.color.rgb = DTM_NAVY
    _tile_value(tf, "Light Heads", font_size=12, color=DTM_NAVY)
    if brands_str and brands_str != "—":
        _tile_value(tf, brands_str, font_size=10, italic=True)

    # Tile 1: Reused / Transfer count
    tx = L + (TILE_W + TILE_GAP)
    tb = _tile_bg(tx, tiles_top, BASE_TILE_H, _REUSED_BG, _LIGHT_GRAY)
    tf = tb.text_frame
    tf.word_wrap   = True
    tf.margin_left = Inches(0.10)
    tf.margin_top  = Inches(0.06)
    p = tf.paragraphs[0]
    nr = p.add_run()
    nr.text           = str(reused_count)
    nr.font.size      = Pt(28)
    nr.font.bold      = True
    nr.font.color.rgb = TAG_REUSED
    _tile_value(tf, "Reused / Transfer", font_size=12, color=DTM_NAVY)

    # Tile 2: Bumper (inline checklist)
    tx = L + 2 * (TILE_W + TILE_GAP)
    tb = _tile_bg(tx, tiles_top, BASE_TILE_H, _PANEL_BG, _LIGHT_GRAY)
    tf = tb.text_frame
    tf.word_wrap   = True
    tf.margin_left = Inches(0.10)
    tf.margin_top  = Inches(0.06)
    _tile_label(tf, "Bumper")
    if not bumper_parts:
        _tile_value(tf, "✗  None", font_size=12, bold=True, color=DTM_RED)
    else:
        if bumper_mfg:
            _tile_value(tf, bumper_mfg, font_size=11)
        check_line = "  ".join(
            ("✓" if _has(kw) else "✗") + " " + lbl
            for lbl, kw in [("Bumper","push bumper"),("Pit Bars","pit bar"),
                             ("Wings","wing wrap"),("Wire Cvr","wire cover")]
        )
        p_chk = tf.add_paragraph()
        r_chk = p_chk.add_run()
        r_chk.text           = check_line
        r_chk.font.size      = Pt(10)
        r_chk.font.color.rgb = DTM_GRAY

    # Tile 3: Cage Type + Equipment Tray
    tx = L + 3 * (TILE_W + TILE_GAP)
    tb = _tile_bg(tx, tiles_top, BASE_TILE_H, _PANEL_BG, _LIGHT_GRAY)
    tf = tb.text_frame
    tf.word_wrap   = True
    tf.margin_left = Inches(0.10)
    tf.margin_top  = Inches(0.06)
    _tile_label(tf, "Cage / Tray")
    _tile_value(tf, f"Cage: {cage_value}", font_size=11)
    _tile_value(tf, f"Tray: {equip_value}", font_size=11)

    # Tile 4: Lighting System + Camera DVR
    tx = L + 4 * (TILE_W + TILE_GAP)
    tb = _tile_bg(tx, tiles_top, BASE_TILE_H, _PANEL_BG, _LIGHT_GRAY)
    tf = tb.text_frame
    tf.word_wrap   = True
    tf.margin_left = Inches(0.10)
    tf.margin_top  = Inches(0.06)
    _tile_label(tf, "Lighting / Camera")
    _tile_value(tf, f"Ctrl: {lighting_value}", font_size=11)
    if camera_value:
        _tile_value(tf, f"Cam: {camera_value}", font_size=11)


# ─────────────────────────────────────────────────────────────────────────────
# Parts manifest slides
# ─────────────────────────────────────────────────────────────────────────────

def _set_cell_bg(cell, color: RGBColor) -> None:
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("a:solidFill")):
        tcPr.remove(old)
    sf  = etree.SubElement(tcPr, qn("a:solidFill"))
    clr = etree.SubElement(sf,   qn("a:srgbClr"))
    clr.set("val", str(color))


def _fmt_cell(cell, text: str, font_size: int = 8, bold: bool = False,
              color: RGBColor = DTM_DARKTEXT, bg: RGBColor | None = None,
              italic: bool = False, align=PP_ALIGN.LEFT) -> None:
    tf = cell.text_frame
    tf.word_wrap    = True
    tf.margin_left  = Inches(0.05)
    tf.margin_right = Inches(0.03)
    tf.margin_top   = Inches(0.025)
    tf.margin_bottom = Inches(0.025)
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.runs[0] if p.runs else p.add_run()
    r.text           = text
    r.font.size      = Pt(font_size)
    r.font.bold      = bold
    r.font.italic    = italic
    r.font.color.rgb = color
    if bg is not None:
        _set_cell_bg(cell, bg)


def _make_manifest_slide(prs, title: str, paths: AppPaths | None = None, footer_text: str = ""):
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    for ph in list(slide.placeholders):
        ph._element.getparent().remove(ph._element)

    hdr = slide.shapes.add_textbox(0, 0, SLIDE_W_EMU, Inches(0.95))
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = DTM_NAVY
    tf = hdr.text_frame
    tf.margin_left = Inches(0.3)
    tf.margin_top  = Inches(0.20)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = title
    r.font.size      = Pt(10)
    r.font.bold      = True
    r.font.color.rgb = _WHITE

    ftr_top = SLIDE_H_EMU - FOOTER_H
    ftr = slide.shapes.add_textbox(0, ftr_top, SLIDE_W_EMU, FOOTER_H)
    ftr.fill.solid()
    ftr.fill.fore_color.rgb = DTM_NAVY
    tf2 = ftr.text_frame
    tf2.margin_left = Inches(0.3)
    tf2.margin_top  = Inches(0.10)
    p2 = tf2.paragraphs[0]
    r2 = p2.add_run()
    r2.text           = footer_text or "DTM Fleet Service  •  Vehicle Build Sheet  •  Parts Manifest"
    r2.font.size      = Pt(10)
    r2.font.bold      = True
    r2.font.color.rgb = _WHITE

    place_logo(slide, paths)
    return slide


def _section_row(table, row_idx: int, label: str) -> None:
    n = len(MANIFEST_COL_HEADERS)
    table.cell(row_idx, 0).merge(table.cell(row_idx, n - 1))
    display = f"  ━━━  {label.upper()}  ━━━"
    _fmt_cell(table.cell(row_idx, 0),
              display,
              font_size=10, bold=True, color=_WHITE, bg=DTM_NAVY,
              align=PP_ALIGN.CENTER)
    table.rows[row_idx].height = MANIFEST_SEC_ROW_H


def _part_row(table, row_idx: int, part, location: str, alt_bg: bool) -> None:
    reused = _is_reused(part)
    row_bg = RGBColor(0xFF, 0xF3, 0xE8) if reused else (DTM_ALT_BG if alt_bg else None)

    raw_source  = getattr(part, "source", "").strip()
    source_text  = f"↺  {raw_source}" if raw_source else ("↺  REUSED" if reused else "■  NEW")
    source_color = TAG_REUSED if reused else TAG_NEW
    source_bg    = RGBColor(0xFF, 0xE8, 0xD0) if reused else RGBColor(0xD8, 0xEC, 0xFF)

    values = [
        getattr(part, "name",         "") or "",
        getattr(part, "manufacturer", "") or "",
        getattr(part, "part_number",  "") or "",
        str(getattr(part, "quantity", "") or ""),
        _color_lens_label(part),
        location,
        source_text,
        getattr(part, "notes",        "") or "",
    ]
    for c, val in enumerate(values):
        is_name   = c == 0
        is_source = c == 6
        cell_clr  = (DTM_NAVY      if is_name   else
                     source_color  if is_source else
                     DTM_DARKTEXT)
        cell_bg   = source_bg if is_source else row_bg
        fs        = 10 if is_name else 12
        _fmt_cell(table.cell(row_idx, c), val,
                  font_size=fs, bold=is_name, color=cell_clr, bg=cell_bg)
    table.rows[row_idx].height = MANIFEST_DATA_ROW_H


def _clean_location(pp) -> str:
    raw_loc = (pp.raw.location or "").strip()
    if raw_loc:
        return raw_loc
    if pp.placements:
        key = pp.placements[0].location_key or ""
        if key.upper().startswith("FIXTURE:"):
            return key[8:].replace("_", " ").title()
        return key
    return "—"


def _manifest_rows(planned_parts) -> list[tuple]:
    lights, structural, electronics = [], [], []
    for pp in planned_parts:
        if not pp.raw.include:
            continue
        cat = pp.category or ""
        rk  = pp.render_kind or ""
        loc   = _clean_location(pp)
        entry = (pp.raw, loc)
        if cat in MANIFEST_LIGHT_CATS:
            lights.append(entry)
        elif rk == "equipment":
            structural.append(entry)
        else:
            electronics.append(entry)

    rows = []
    for label, group in [
        ("Lighting",                lights),
        ("Structural Equipment",    structural),
        ("Equipment & Electronics", electronics),
    ]:
        if not group:
            continue
        rows.append(("section", label, None, ""))
        for raw, loc in group:
            rows.append(("part", "", raw, loc))
    return rows


def add_parts_manifest_slides(prs, plan, paths: AppPaths | None = None) -> int:
    all_rows = _manifest_rows(plan.planned_parts)
    if not all_rows:
        return 0

    proj    = plan.project
    new_v   = proj.get("NewVehicle",      {})
    exist_v = proj.get("ExistingVehicle", {})
    agency  = proj.get("Agency", "")
    year    = new_v.get("YEAR","") or exist_v.get("YEAR","")
    make    = new_v.get("MAKE","") or exist_v.get("MAKE","")
    model   = (new_v.get("MODEL","") or exist_v.get("MODEL","")
               or proj.get("VehicleType",""))
    veh_line = " ".join(filter(None, [year, make, model]))
    unit_id  = (new_v.get("UNIT ID", new_v.get("UNIT",""))
                or exist_v.get("UNIT ID", exist_v.get("UNIT","")))
    unit_part = f"Unit #{unit_id}" if unit_id else ""
    hdr_parts = list(filter(None, ["PARTS MANIFEST", agency, veh_line, unit_part]))
    hdr_base  = "   •   ".join(hdr_parts)
    footer_text = "   •   ".join(filter(None, [agency, veh_line, unit_part, "DTM Fleet Service"]))

    n_cols     = len(MANIFEST_COL_HEADERS)
    col_widths = [Inches(w) for w in MANIFEST_COL_WIDTHS_IN]

    avail_h = SLIDE_H_EMU - MANIFEST_TABLE_TOP - FOOTER_H - Inches(0.40)
    MAX_DATA_ROWS_PER_PAGE = 10

    slides_added = 0
    i = 0
    page_num = 0

    while i < len(all_rows):
        page_num += 1
        slide_rows: list[tuple] = []
        used_h = MANIFEST_HDR_ROW_H
        data_rows_on_page = 0

        while i < len(all_rows):
            rtype = all_rows[i][0]
            row_h = MANIFEST_SEC_ROW_H if rtype == "section" else MANIFEST_DATA_ROW_H
            if data_rows_on_page >= MAX_DATA_ROWS_PER_PAGE:
                break
            if used_h + row_h > avail_h and slide_rows:
                break
            slide_rows.append(all_rows[i])
            used_h += row_h
            data_rows_on_page += 1
            i += 1

        if not slide_rows:
            break

        slide_title = f"{hdr_base}   •   Page {page_num}"
        slide = _make_manifest_slide(prs, slide_title, paths, footer_text=footer_text)
        slides_added += 1

        total_rows = 1 + len(slide_rows)
        table_h    = used_h
        tbl_shape  = slide.shapes.add_table(
            total_rows, n_cols,
            MANIFEST_TABLE_LEFT, MANIFEST_TABLE_TOP,
            MANIFEST_TABLE_W, table_h,
        )
        table = tbl_shape.table
        for c, w in enumerate(col_widths):
            table.columns[c].width = w

        table.rows[0].height = MANIFEST_HDR_ROW_H
        for c, hdr in enumerate(MANIFEST_COL_HEADERS):
            _fmt_cell(table.cell(0, c), hdr,
                      font_size=10, bold=True, color=_WHITE,
                      bg=DTM_NAVY, align=PP_ALIGN.CENTER)

        part_counter = 0
        for r_idx, (rtype, section_label, raw, loc) in enumerate(slide_rows):
            tbl_r = r_idx + 1
            if rtype == "section":
                _section_row(table, tbl_r, section_label)
                part_counter = 0
            else:
                _part_row(table, tbl_r, raw, loc, alt_bg=(part_counter % 2 == 1))
                part_counter += 1

    return slides_added


# ─────────────────────────────────────────────────────────────────────────────
# Icon sizing
# ─────────────────────────────────────────────────────────────────────────────

def get_icon_size(part, icon_type, orient, view, icon_path_str="", paths: AppPaths | None = None):
    if icon_type == "equipment":
        equip = EQUIP_SIZES.get(part.name, {})
        if view in equip:
            return equip[view]
        if not icon_path_str:
            return (1.0, 1.0)
        from PIL import Image as PILImage
        with PILImage.open(
            (paths or ensure_workspace()).workspace_assets_dir / icon_path_str
        ) as img:
            image_w, image_h = img.size
        ratio   = image_w / image_h
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
    defs       = _load_manifest(paths).get("size_rule_definitions", {})
    class_def  = defs.get(size_class) or defs.get("sm", {})
    views_data = class_def.get("views", {})
    view_data  = views_data.get(view) or views_data.get("front")
    if view_data:
        w, h = float(view_data["w"]), float(view_data["h"])
        return (h, w) if orient == "v" else (w, h)
    return (0.244, 0.085) if orient == "h" else (0.085, 0.244)


def icon_size_in_inches(
    render_kind: str,
    part_name: str,
    size_class: str,
    orientation: str,
    asset_path: str,
    view: str,
    size_override: "dict | None" = None,
    paths: "AppPaths | None" = None,
) -> "tuple[float, float]":
    """Single source of truth for icon sizing — used by both PPTX renderer and preview service.

    Returns (width_inches, height_inches).  size_override, if present, takes
    precedence over all catalog/manifest lookup.
    """
    if size_override and "w" in size_override and "h" in size_override:
        w, h = float(size_override["w"]), float(size_override["h"])
        return (h, w) if orientation == "v" else (w, h)
    from types import SimpleNamespace
    part = SimpleNamespace(name=part_name, size_class=size_class)
    return get_icon_size(part, render_kind, orientation, view, asset_path, paths=paths)


# ─────────────────────────────────────────────────────────────────────────────
# Generic shape helpers
# ─────────────────────────────────────────────────────────────────────────────

def _lock_picture_position(picture) -> None:
    c_nv_pic_pr = picture._element.find(".//" + qn("p:cNvPicPr"))
    if c_nv_pic_pr is None:
        return
    locks = c_nv_pic_pr.find(qn("a:picLocks"))
    if locks is None:
        locks = etree.SubElement(c_nv_pic_pr, qn("a:picLocks"))
    locks.set("noMove",   "1")
    locks.set("noResize", "1")


def find_shape(slide, name):
    for shape in slide.shapes:
        if shape.name == name:
            return shape
    return None


def slot_geometry(shape):
    left, top, width, height = shape.left, shape.top, shape.width, shape.height
    shape._element.getparent().remove(shape._element)
    return left, top, width, height


# ─────────────────────────────────────────────────────────────────────────────
# Vehicle image
# ─────────────────────────────────────────────────────────────────────────────

def place_vehicle_image(slide, vehicle_type, view, max_right_emu=None):
    """Return (picture_shape | None, img_box | None, equip_scale).

    img_box is (L,T,W,H) in EMU.  equip_scale is (scale_w, scale_h) — the ratio
    of the constrained vehicle image size to the unconstrained size.  Equipment
    icons (Push Bumper, Wing Wraps, etc.) whose sizes were calibrated for the
    unconstrained image should multiply their dimensions by equip_scale so they
    remain proportionally correct when the vehicle image is made smaller to
    accommodate a legend panel.

    For the side view the vehicle is placed in the bottom ~3" of the slide so
    the legend grid can occupy the top portion.
    max_right_emu: if set, constrains the vehicle image's right edge.
    """
    slot = find_shape(slide, "VEHICLE_IMAGE_SLOT")
    if not slot:
        return None, None, (1.0, 1.0)
    slot_left, slot_top, slot_w, slot_h = slot_geometry(slot)

    # Side/top view: move vehicle to bottom so legend grid fits above.
    # Slot top matches GRID_BOTTOM in place_legend_grid (3.50").
    if view in ("side", "top"):
        slot_left = 0
        slot_top  = Inches(3.50)
        slot_w    = SLIDE_W_EMU
        slot_h    = SLIDE_H_EMU - Inches(3.50) - FOOTER_H

    # Remember unconstrained slot width for equipment scale factor
    unconstrained_slot_w = slot_w

    # Honour caller-supplied right edge limit (e.g. to leave room for a legend panel)
    if max_right_emu is not None:
        available_w = max_right_emu - slot_left
        if available_w > 0:
            slot_w = min(slot_w, available_w)

    png = ensure_workspace().workspace_assets_dir / "vehicles" / f"{vehicle_type}_{view}.png"
    if not png.exists():
        return None, (slot_left, slot_top, slot_w, slot_h), (1.0, 1.0)

    from PIL import Image as PILImage
    with PILImage.open(png) as img:
        img_w, img_h = img.size

    img_ratio = img_w / img_h

    # Compute unconstrained final size (reference that size_per_view was calibrated for)
    uncons_slot_ratio = unconstrained_slot_w / slot_h
    if img_ratio > uncons_slot_ratio:
        ref_final_w = float(unconstrained_slot_w)
        ref_final_h = unconstrained_slot_w / img_ratio
    else:
        ref_final_h = float(slot_h)
        ref_final_w = slot_h * img_ratio

    # Compute constrained final size
    slot_ratio = slot_w / slot_h
    if img_ratio > slot_ratio:
        final_w    = slot_w
        final_h    = int(slot_w / img_ratio)
        final_left = slot_left
        final_top  = slot_top + (slot_h - final_h) // 2
    else:
        final_h    = slot_h
        final_w    = int(slot_h * img_ratio)
        final_left = slot_left + (slot_w - final_w) // 2
        final_top  = slot_top

    # Scale factor so equipment icons stay proportional to the vehicle image
    equip_scale = (final_w / ref_final_w, final_h / ref_final_h)

    pic = slide.shapes.add_picture(str(png), final_left, final_top,
                                   width=final_w, height=final_h)
    _lock_picture_position(pic)
    return pic, (final_left, final_top, final_w, final_h), equip_scale


# ─────────────────────────────────────────────────────────────────────────────
# Legend shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _est_wrapped_lines(text: str, inner_w_in: float, pt_size: int = 10) -> int:
    """Conservative estimate of how many display lines `text` needs.

    Uses an empirical average character width for Calibri mixed-case text, then
    applies a 0.85 safety factor to account for wide characters and word-wrap
    boundaries that push partial words to the next line.
    """
    if not text:
        return 0
    avg_char_w = pt_size * 0.0060          # inches per character at this pt size
    chars_per_line = max(1, int(inner_w_in / avg_char_w * 0.85))
    return max(1, -(-len(text) // chars_per_line))  # ceiling division


def _badge_label(part) -> tuple[str, object]:
    """Return (display_text, color) for the status badge on a legend card."""
    noru   = getattr(part, "new_or_used", "").strip().upper()
    src    = getattr(part, "source",      "").strip()
    reused = getattr(part, "is_reused",   False)
    if noru in ("REUSED", "R"):
        return "↺ REUSED", TAG_REUSED
    if noru in ("USED", "U"):
        return "↺ USED", TAG_REUSED
    if src or reused:
        return "↺ REUSED", TAG_REUSED
    return "■ NEW", TAG_NEW


def _legend_headline(part) -> str:
    """Return the bold headline text for a legend card.

    For most parts the headline is the location (what the user typed in the workbook).
    Exceptions that keep the part *name* as headline:
      - Fixture parts (location is empty or starts with "FIXTURE:")
      - Parts whose name contains "tracer" or "light bar"
    """
    name       = getattr(part, "name",     "") or ""
    name_lower = name.lower()
    loc        = getattr(part, "location", "") or ""
    if "tracer" in name_lower or "light bar" in name_lower:
        return name
    if not loc or loc.upper().startswith("FIXTURE:"):
        return name
    return loc


def _card_content_height(part, inner_w_in: float,
                          acc: dict,
                          pad_top=None, pad_bot=None,
                          lh_name=None, lh_spec=None, lh_acc=None,
                          min_card=None) -> int:
    """Compute card EMU height for a single part, accounting for text wrapping.

    All Inches() arguments use module defaults when None.
    """
    pad_top  = pad_top  if pad_top  is not None else Inches(0.06)
    pad_bot  = pad_bot  if pad_bot  is not None else Inches(0.04)
    lh_name  = lh_name  if lh_name  is not None else Inches(0.175)
    lh_spec  = lh_spec  if lh_spec  is not None else Inches(0.175)
    lh_acc   = lh_acc   if lh_acc   is not None else Inches(0.165)
    min_card = min_card if min_card is not None else Inches(0.34)

    badge_text, _ = _badge_label(part)
    headline = _legend_headline(part) + f"  {badge_text}"
    h = pad_top + _est_wrapped_lines(headline, inner_w_in, 10) * lh_name

    mfg   = getattr(part, "manufacturer", "") or ""
    pnum  = getattr(part, "part_number",   "") or ""
    color = _color_label(part)
    specs = "  ·  ".join(filter(None, [mfg, pnum, color]))
    if specs:
        h += _est_wrapped_lines(specs, inner_w_in, 11) * lh_spec
    lens = _lens_label(part)
    if lens:
        h += _est_wrapped_lines(lens, inner_w_in, 11) * lh_spec

    for acc_entry in (acc.get(part.name) or []):
        acc_name = acc_entry[0] if isinstance(acc_entry, tuple) else acc_entry
        acc_pnum = acc_entry[1] if isinstance(acc_entry, tuple) else ""
        acc_text = "+ " + acc_name + (f"  ·  {acc_pnum}" if acc_pnum else "")
        h += _est_wrapped_lines(acc_text, inner_w_in, 10) * lh_acc

    return max(min_card, h + pad_bot)


# ─────────────────────────────────────────────────────────────────────────────
# Legend — standard sidebar (front / top / rear views)
# ─────────────────────────────────────────────────────────────────────────────

def place_legend(slide, placed, unplaced, accessory_map: dict | None = None,
                 view: str = "", panel_left_emu=None) -> None:
    """Two-column legend panel for front/rear views.

    panel_left_emu: left edge of the legend area in EMU (caller sets this to match
    whatever right edge was passed to place_vehicle_image).  Defaults to 7.80".
    """
    slot = find_shape(slide, "LEGEND_SLOT")
    if slot:
        slot._element.getparent().remove(slot._element)

    PANEL_LEFT  = panel_left_emu if panel_left_emu is not None else Inches(7.80)
    PANEL_TOP   = Inches(0.66)   # just below the 0.62" header band
    PANEL_W     = SLIDE_W_EMU - PANEL_LEFT - Inches(0.10)
    PANEL_H     = SLIDE_H_EMU - PANEL_TOP - FOOTER_H - Inches(0.06)
    BOTTOM_EDGE = PANEL_TOP + PANEL_H

    N_COLS   = 2
    COL_GAP  = Inches(0.08)
    COL_W    = (PANEL_W - COL_GAP * (N_COLS - 1)) / N_COLS
    STRIPE_W = Inches(0.05)

    # ── Panel section header ──────────────────────────────────────────────────
    count     = len(placed)
    hdr_label = (f"  {count} INSTALLED COMPONENT{'S' if count != 1 else ''}"
                 if placed else "  COMPONENTS")
    hdr_h = Inches(0.28)
    hdr   = slide.shapes.add_textbox(PANEL_LEFT, PANEL_TOP, PANEL_W, hdr_h)
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = DTM_NAVY
    tf = hdr.text_frame
    tf.margin_left = Inches(0.08)
    tf.margin_top  = Inches(0.05)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = hdr_label
    r.font.size      = Pt(10)
    r.font.bold      = True
    r.font.color.rgb = _WHITE

    cards_top = PANEL_TOP + hdr_h + Inches(0.04)

    # ── Empty state ───────────────────────────────────────────────────────────
    if not placed and not unplaced:
        msg = "NO ROOF-MOUNTED COMPONENTS" if view.lower() == "top" else "NO COMPONENTS ON THIS VIEW"
        tb = slide.shapes.add_textbox(PANEL_LEFT + Inches(0.10), cards_top,
                                       PANEL_W - Inches(0.20), Inches(0.60))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = msg; r.font.size = Pt(12); r.font.italic = True
        r.font.color.rgb = DTM_GRAY
        return

    # ── Card geometry ─────────────────────────────────────────────────────────
    CARD_GAP = Inches(0.05)
    PAD_TOP  = Inches(0.06)
    MIN_CARD = Inches(0.34)

    acc = accessory_map or {}

    # Inner column width (in inches) needed by _card_content_height
    _inner_w_in = float(COL_W - Inches(0.05) - Inches(0.08)) / 914400  # EMU → inches

    card_heights = [
        _card_content_height(p, _inner_w_in, acc, min_card=MIN_CARD)
        for p in placed
    ]

    # Available height per column
    avail_h = BOTTOM_EDGE - cards_top - (Inches(0.8) if unplaced else Inches(0.06))

    # Distribute cards into 2 columns greedily
    col_fills  = [0, 0]
    col_assign = []
    for h in card_heights:
        # pick the column with less fill, prefer left on tie
        c = 0 if col_fills[0] <= col_fills[1] else 1
        col_assign.append(c)
        col_fills[c] += h + CARD_GAP

    # If tallest column overflows, scale all heights down uniformly
    max_fill = max(col_fills) if col_fills else 0
    if max_fill > avail_h and card_heights:
        scale        = avail_h / max_fill
        card_heights = [max(MIN_CARD, h * scale) for h in card_heights]
        # Recompute fills
        col_fills = [0, 0]
        for h, c in zip(card_heights, col_assign):
            col_fills[c] += h + CARD_GAP

    # Track current y per column
    col_y = [cards_top, cards_top]

    for part, card_h, col_i in zip(placed, card_heights, col_assign):
        y   = col_y[col_i]
        cx  = PANEL_LEFT + col_i * (COL_W + COL_GAP)
        if y + card_h > BOTTOM_EDGE - (Inches(0.8) if unplaced else Inches(0.06)):
            break

        reused       = getattr(part, "is_reused", False)
        stripe_color = TAG_REUSED if reused else TAG_NEW
        bg_color     = _REUSED_BG if reused else _NEW_BG

        _stripe_box(slide, cx, y, STRIPE_W, card_h - Inches(0.02), stripe_color)
        _card_bg(slide, cx + STRIPE_W, y, COL_W - STRIPE_W, card_h - Inches(0.02), bg_color)

        inner_x = cx + STRIPE_W + Inches(0.05)
        inner_w = COL_W - STRIPE_W - Inches(0.08)
        tb = slide.shapes.add_textbox(inner_x, y + PAD_TOP,
                                       inner_w, card_h - PAD_TOP)
        tf = tb.text_frame
        tf.word_wrap   = True
        tf.margin_top  = 0
        tf.margin_left = 0

        # Line 1: Location (or part name for fixtures/bars/tracers)  ■ NEW / ↺ REUSED
        badge_text, badge_color = _badge_label(part)
        p  = tf.paragraphs[0]
        nr = p.add_run()
        nr.text           = _legend_headline(part)
        nr.font.size      = Pt(10)
        nr.font.bold      = True
        nr.font.color.rgb = DTM_NAVY
        badge = p.add_run()
        badge.text           = f"  {badge_text}"
        badge.font.size      = Pt(10)
        badge.font.bold      = True
        badge.font.color.rgb = badge_color

        # Line 2: mfg · part# · color (no lens here)
        mfg   = getattr(part, "manufacturer", "") or ""
        pnum  = getattr(part, "part_number",   "") or ""
        color = _color_label(part)
        specs = "  ·  ".join(filter(None, [mfg, pnum, color]))
        if specs:
            p2 = tf.add_paragraph()
            r2 = p2.add_run()
            r2.text           = specs
            r2.font.size      = Pt(11)
            r2.font.color.rgb = DTM_GRAY

        # Line 3: lens on its own line (value already contains "Lens")
        lens = _lens_label(part)
        if lens:
            p3 = tf.add_paragraph()
            r3 = p3.add_run()
            r3.text           = lens
            r3.font.size      = Pt(11)
            r3.font.color.rgb = DTM_GRAY

        # Line 4+: accessories with part numbers
        for acc_entry in acc.get(part.name, []):
            acc_name = acc_entry[0] if isinstance(acc_entry, tuple) else acc_entry
            acc_pnum = acc_entry[1] if isinstance(acc_entry, tuple) else ""
            pa = tf.add_paragraph()
            ra = pa.add_run()
            ra.text           = "+ " + acc_name + (f"  ·  {acc_pnum}" if acc_pnum else "")
            ra.font.size      = Pt(10)
            ra.font.italic    = True
            ra.font.color.rgb = DTM_GRAY

        col_y[col_i] += card_h + CARD_GAP

    # ── "Not shown" box spans full panel width ────────────────────────────────
    if unplaced:
        y_note  = max(col_y) + Inches(0.06)
        box_h   = Inches(0.26) + len(unplaced) * Inches(0.20)
        box_h   = min(box_h, BOTTOM_EDGE - y_note - Inches(0.04))
        bordered = slide.shapes.add_textbox(PANEL_LEFT, y_note, PANEL_W, box_h)
        bordered.fill.solid()
        bordered.fill.fore_color.rgb = RGBColor(0xFF, 0xF3, 0xF0)
        _add_border(bordered, DTM_RED, 0.5)
        tf = bordered.text_frame
        tf.word_wrap   = True
        tf.margin_left = Inches(0.08)
        tf.margin_top  = Inches(0.04)
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text           = "ADDITIONAL COMPONENTS NOT SHOWN"
        r.font.size      = Pt(10)
        r.font.bold      = True
        r.font.color.rgb = DTM_RED
        for upart in unplaced:
            loc = getattr(upart, "location", "") or "?"
            p2  = tf.add_paragraph()
            r2  = p2.add_run()
            r2.text           = f"  {upart.name}  @  {loc}"
            r2.font.size      = Pt(11)
            r2.font.color.rgb = DTM_RED


# ─────────────────────────────────────────────────────────────────────────────
# Legend — grid layout for side view (vehicle at bottom, cards at top)
# ─────────────────────────────────────────────────────────────────────────────

def place_legend_grid(slide, placed, unplaced, accessory_map: dict | None = None,
                      view: str = "side") -> None:
    """Render part cards in a 4-column grid occupying the top portion of the slide.

    Used for side and top view slides where the vehicle image is at the bottom.
    """
    slot = find_shape(slide, "LEGEND_SLOT")
    if slot:
        slot._element.getparent().remove(slot._element)

    GRID_LEFT    = Inches(0.3)
    GRID_TOP     = Inches(0.66)   # flush with 0.62" header band bottom
    GRID_BOTTOM  = Inches(3.50)   # vehicle image starts at 3.50"
    GRID_COLS    = 4
    COL_GAP      = Inches(0.10)
    COL_W        = (SLIDE_W_EMU - GRID_LEFT * 2 - COL_GAP * (GRID_COLS - 1)) / GRID_COLS
    STRIPE_W     = Inches(0.06)
    CARD_GAP_V   = Inches(0.07)

    view_label = view.upper() if view else "SIDE"
    # Section header spanning full width
    count     = len(placed)
    hdr_label = (f"  {count} INSTALLED COMPONENT{'S' if count != 1 else ''}"
                 if placed else f"  {view_label} VIEW COMPONENTS")
    hdr_h = Inches(0.34)
    hdr   = slide.shapes.add_textbox(GRID_LEFT, GRID_TOP,
                                      SLIDE_W_EMU - GRID_LEFT * 2, hdr_h)
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = DTM_NAVY
    tf = hdr.text_frame
    tf.margin_left = Inches(0.10)
    tf.margin_top  = Inches(0.07)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = hdr_label
    r.font.size      = Pt(10)
    r.font.bold      = True
    r.font.color.rgb = _WHITE

    card_area_top  = GRID_TOP + hdr_h + Inches(0.06)
    avail_h        = GRID_BOTTOM - card_area_top
    acc = accessory_map or {}
    last_card_bottom = card_area_top

    if not placed and not unplaced:
        tb = slide.shapes.add_textbox(GRID_LEFT + Inches(0.12), card_area_top,
                                       Inches(8), Inches(0.70))
        tf = tb.text_frame
        p  = tf.paragraphs[0]
        r  = p.add_run()
        r.text = f"NO {view_label}-VIEW COMPONENTS SPECIFIED"
        r.font.size = Pt(12); r.font.italic = True; r.font.color.rgb = DTM_GRAY
    else:
        # ── Dynamic per-row card heights ──────────────────────────────────────
        MIN_CARD  = Inches(0.32)
        inner_w_in = float(COL_W - STRIPE_W - Inches(0.08)) / 914400  # EMU → inches

        per_card_h = [
            _card_content_height(p, inner_w_in, acc, min_card=MIN_CARD)
            for p in placed
        ]

        # Group into rows; row height = max card height in that row
        n_rows    = max(1, -(-len(placed) // GRID_COLS))
        row_heights = []
        for r_i in range(n_rows):
            start = r_i * GRID_COLS
            end   = min(start + GRID_COLS, len(per_card_h))
            row_heights.append(max(per_card_h[start:end]) if per_card_h[start:end] else MIN_CARD)

        total_h = sum(row_heights) + CARD_GAP_V * (n_rows - 1)
        if total_h > avail_h and row_heights:
            scale       = avail_h / total_h
            row_heights = [max(MIN_CARD, h * scale) for h in row_heights]

        # Row y-offsets
        row_tops = [card_area_top]
        for rh in row_heights[:-1]:
            row_tops.append(row_tops[-1] + rh + CARD_GAP_V)

        for i, part in enumerate(placed):
            col_i  = i % GRID_COLS
            row_i  = i // GRID_COLS
            if row_i >= len(row_heights):
                break
            cx     = GRID_LEFT + col_i * (COL_W + COL_GAP)
            cy     = row_tops[row_i]
            card_h = row_heights[row_i]

            if cy + card_h > GRID_BOTTOM:
                break
            last_card_bottom = cy + card_h

            badge_text, badge_color = _badge_label(part)
            stripe_color = badge_color
            bg_color     = _REUSED_BG if stripe_color == TAG_REUSED else _NEW_BG

            _stripe_box(slide, cx, cy, STRIPE_W, card_h - Inches(0.02), stripe_color)
            _card_bg(slide, cx + STRIPE_W, cy,
                     COL_W - STRIPE_W, card_h - Inches(0.02), bg_color)

            inner_x = cx + STRIPE_W + Inches(0.05)
            inner_w = COL_W - STRIPE_W - Inches(0.08)
            tb = slide.shapes.add_textbox(inner_x, cy + Inches(0.04),
                                           inner_w, card_h - Inches(0.05))
            tf = tb.text_frame
            tf.word_wrap   = True
            tf.margin_top  = 0
            tf.margin_left = 0

            # Line 1: Location (or part name for fixtures/bars/tracers)  ■ NEW / ↺ REUSED
            p  = tf.paragraphs[0]
            nr = p.add_run()
            nr.text = _legend_headline(part); nr.font.size = Pt(10); nr.font.bold = True
            nr.font.color.rgb = DTM_NAVY
            bdg = p.add_run()
            bdg.text = f"  {badge_text}"; bdg.font.size = Pt(10); bdg.font.bold = True
            bdg.font.color.rgb = badge_color

            # Line 2: mfg · part# · color (no lens)
            mfg   = getattr(part, "manufacturer", "") or ""
            pnum  = getattr(part, "part_number",   "") or ""
            color = _color_label(part)
            specs = "  ·  ".join(filter(None, [mfg, pnum, color]))
            if specs:
                p2 = tf.add_paragraph()
                r2 = p2.add_run()
                r2.text = specs; r2.font.size = Pt(11); r2.font.color.rgb = DTM_GRAY

            # Line 3: lens on its own line (value already contains "Lens")
            lens = _lens_label(part)
            if lens:
                p3 = tf.add_paragraph()
                r3 = p3.add_run()
                r3.text = lens; r3.font.size = Pt(11); r3.font.color.rgb = DTM_GRAY

            # Lines 4+: accessories
            for acc_entry in acc.get(part.name, []):
                acc_name = acc_entry[0] if isinstance(acc_entry, tuple) else acc_entry
                acc_pnum = acc_entry[1] if isinstance(acc_entry, tuple) else ""
                pa = tf.add_paragraph()
                ra = pa.add_run()
                ra.text = "+ " + acc_name + (f"  ·  {acc_pnum}" if acc_pnum else "")
                ra.font.size = Pt(10); ra.font.italic = True; ra.font.color.rgb = DTM_GRAY

    if unplaced:
        # Place "not shown" note just below the lowest rendered card row
        y_note = last_card_bottom + Inches(0.08)
        box_h  = Inches(0.26) + len(unplaced) * Inches(0.20)
        box_h  = min(box_h, GRID_BOTTOM - y_note - Inches(0.04))
        bordered = slide.shapes.add_textbox(GRID_LEFT, y_note,
                                             SLIDE_W_EMU - GRID_LEFT * 2, box_h)
        bordered.fill.solid()
        bordered.fill.fore_color.rgb = RGBColor(0xFF, 0xF3, 0xF0)
        _add_border(bordered, DTM_RED, 0.5)
        tf = bordered.text_frame
        tf.word_wrap   = True
        tf.margin_left = Inches(0.10)
        tf.margin_top  = Inches(0.04)
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text           = "ADDITIONAL COMPONENTS NOT SHOWN ON DIAGRAM"
        r.font.size      = Pt(10)
        r.font.bold      = True
        r.font.color.rgb = DTM_RED
        for upart in unplaced:
            loc = getattr(upart, "location", "") or "?"
            p2  = tf.add_paragraph()
            r2  = p2.add_run()
            r2.text           = f"  {upart.name}  @  {loc}"
            r2.font.size      = Pt(11)
            r2.font.color.rgb = DTM_RED


# ─────────────────────────────────────────────────────────────────────────────
# Specify-palette swatches
# ─────────────────────────────────────────────────────────────────────────────

def place_specify_palette(slide, category: str, img_box, y_offset_emu: int = 0):
    tokens = PALETTE_TOKENS.get(category, [])
    if not tokens:
        return 0

    left_px, top_px, width_px, height_px = img_box
    icon_w   = Inches(0.45)
    icon_h   = Inches(0.114)
    label_h  = Inches(0.13)
    col_w    = Inches(0.54)
    max_cols = 10
    row_h    = icon_h + label_h + Inches(0.04)
    pal_top  = top_px + height_px + Inches(0.18) + y_offset_emu
    pal_left = left_px

    hdr = slide.shapes.add_textbox(pal_left, pal_top - Inches(0.17), Inches(4), Inches(0.15))
    tf  = hdr.text_frame
    r   = tf.paragraphs[0].add_run()
    r.text           = f"Specify {category} — keep one, delete the rest"
    r.font.size      = Pt(12)
    r.font.italic    = True
    r.font.color.rgb = DTM_RED

    rendered = 0
    for token in tokens:
        png_path = ensure_workspace().workspace_assets_dir / "lights" / f"sm_{token}_h.png"
        if not png_path.exists():
            continue
        col = rendered % max_cols
        row = rendered // max_cols
        x   = pal_left + col * col_w
        y   = pal_top  + row * row_h
        slide.shapes.add_picture(str(png_path), x, y, width=icon_w, height=icon_h)
        lbl = slide.shapes.add_textbox(x, y + icon_h + Inches(0.01), col_w, label_h)
        tf  = lbl.text_frame
        p   = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r2  = p.add_run()
        r2.text           = token
        r2.font.size      = Pt(6)
        r2.font.color.rgb = DTM_GRAY
        rendered += 1

    rows_used = (rendered + max_cols - 1) // max_cols if rendered else 0
    return rows_used * row_h + Inches(0.18)


# ─────────────────────────────────────────────────────────────────────────────
# Notes slide — structured sections
# ─────────────────────────────────────────────────────────────────────────────

NOTES_CATEGORIES = [
    "INSTALLATION NOTES",
    "CUSTOMER REQUESTS",
    "SPECIAL FABRICATION NOTES",
    "DELIVERY REQUIREMENTS",
    "FINAL APPROVALS",
]


def fill_notes(slide, notes: dict[str, list[str]]) -> None:
    slot = find_shape(slide, "NOTES_SLOT")
    if not slot:
        return
    left, top, width, height = slot_geometry(slot)

    y       = top
    sec_gap = Inches(0.14)
    label_h = Inches(0.26)
    line_h  = Inches(0.22)
    placeholder_color = RGBColor(0xAA, 0xAA, 0xAA)

    _placeholders = {
        "INSTALLATION NOTES":      "No installation notes specified.",
        "CUSTOMER REQUESTS":       "No customer requests specified.",
        "SPECIAL FABRICATION NOTES": "No special fabrication notes specified.",
        "DELIVERY REQUIREMENTS":   "No delivery requirements specified.",
        "FINAL APPROVALS":         "Pending final inspection sign-off.",
    }

    for section in NOTES_CATEGORIES:
        if y + label_h > top + height - Inches(0.1):
            break

        lbl = slide.shapes.add_textbox(left, y, width, label_h)
        lbl.fill.solid()
        lbl.fill.fore_color.rgb = RGBColor(0xEC, 0xEE, 0xF6)
        tf  = lbl.text_frame
        tf.margin_left = Inches(0.12)
        tf.margin_top  = Inches(0.05)
        p   = tf.paragraphs[0]
        r   = p.add_run()
        r.text           = section
        r.font.size      = Pt(10)
        r.font.bold      = True
        r.font.color.rgb = DTM_NAVY
        y += label_h + Inches(0.06)

        section_notes = notes.get(section, []) if isinstance(notes, dict) else []
        if section_notes:
            for idx, note in enumerate(section_notes):
                if y + line_h > top + height - Inches(0.1):
                    break
                tb  = slide.shapes.add_textbox(left + Inches(0.2), y,
                                                width - Inches(0.2), line_h)
                tf2 = tb.text_frame
                tf2.word_wrap = True
                p2  = tf2.paragraphs[0]
                nr  = p2.add_run()
                nr.text           = f"{idx + 1}.  "
                nr.font.size      = Pt(11)
                nr.font.bold      = True
                nr.font.color.rgb = DTM_NAVY
                br  = p2.add_run()
                br.text           = note
                br.font.size      = Pt(11)
                br.font.color.rgb = DTM_DARKTEXT
                y += line_h
        else:
            tb  = slide.shapes.add_textbox(left + Inches(0.2), y,
                                            width - Inches(0.2), line_h)
            tf2 = tb.text_frame
            p2  = tf2.paragraphs[0]
            r2  = p2.add_run()
            r2.text           = _placeholders.get(section, "No notes specified.")
            r2.font.size      = Pt(10)
            r2.font.italic    = True
            r2.font.color.rgb = placeholder_color
            y += line_h

        y += sec_gap
