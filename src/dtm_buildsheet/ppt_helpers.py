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
MANIFEST_HDR_ROW_H   = Inches(0.28)
MANIFEST_DATA_ROW_H  = Inches(0.27)
MANIFEST_SEC_ROW_H   = Inches(0.27)


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


def _color_lens_label(part) -> str:
    color = getattr(part, "color", "").strip()
    lens  = getattr(part, "lens",  "").strip()
    parts = []
    if color:
        parts.append(color)
    if lens:
        parts.append(f"Lens: {lens}")
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
    """Write into TextBox 1, 2, and 5/4 that live on the template view/notes slides."""
    for shape in slide.shapes:
        if shape.name not in ("TextBox 1", "TextBox 2", "TextBox 5", "TextBox 4"):
            continue
        try:
            tf = shape.text_frame
            tf.clear()
        except Exception:
            continue
        p = tf.paragraphs[0]
        r = p.add_run()
        if shape.name == "TextBox 1":
            r.text = title
            r.font.size = Pt(11)
            r.font.bold = True
            r.font.color.rgb = _WHITE
        elif shape.name == "TextBox 2":
            r.text = subtitle
            r.font.size = Pt(8)
            r.font.color.rgb = RGBColor(0xCC, 0xCC, 0xFF)
        else:
            # TextBox 5 / 4 — the sticky footer bar on template slides
            r.text = footer
            r.font.size = Pt(10)
            r.font.bold = True
            r.font.color.rgb = _WHITE


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
              line_h: float = 0.21) -> int:
    y = top
    for key, value in items:
        if not value:
            continue
        box = slide.shapes.add_textbox(left, y, width, Inches(line_h + 0.05))
        tf  = box.text_frame
        tf.word_wrap = True
        p   = tf.paragraphs[0]
        kr  = p.add_run()
        kr.text           = f"{key}:  "
        kr.font.size      = Pt(9)
        kr.font.bold      = True
        kr.font.color.rgb = DTM_NAVY
        vr  = p.add_run()
        vr.text           = value
        vr.font.size      = Pt(9)
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

def fill_overview(slide, project) -> None:
    info    = project.info
    new_v   = info.get("NewVehicle",      {})
    exist_v = info.get("ExistingVehicle", {})
    parts   = project.parts

    agency    = info.get("Agency",         "—")
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
    hdr = slide.shapes.add_textbox(0, 0, SLIDE_W_EMU, Inches(0.95))
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = DTM_NAVY
    tf = hdr.text_frame
    tf.margin_left = Inches(0.3)
    tf.margin_top  = Inches(0.21)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = "FLEET VEHICLE SPECIFICATION PACKAGE"
    r.font.size      = Pt(20)
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
    reused_count = sum(1 for p in parts if _is_reused(p))
    build_type   = "Transfer / Retrofit" if reused_count else "New Installation"
    _textbox(slide, L, col_top, LEFT_W, Inches(0.22),
             "QUOTE & SALES INFORMATION", font_size=7, bold=True, color=DTM_NAVY)
    left_y = col_top + Inches(0.22)
    left_y = _kv_block(slide, [
        ("Sales Rep",    sales_rep),
        ("Quote #",      quote_num),
        ("Build Type",   build_type),
        ("Other Orders", "0"),
    ], L, left_y, LEFT_W)

    # Right: Vehicle specs — NEW primary card (always) + EXISTING secondary card (orange, if data)
    card_h = Inches(1.55)

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
    _textbox(slide, RIGHT_X + Inches(0.10), col_top, CARD_W - Inches(0.2), Inches(0.22),
             "NEW VEHICLE", font_size=7, bold=True, color=TAG_NEW)
    _kv_block(slide, [
        ("Year",    new_year      or "—"),
        ("Make",    new_make      or "—"),
        ("Model",   new_model_str or "—"),
        ("Unit ID", new_unit      or "—"),
        ("VIN",     new_vin       or "—"),
    ], RIGHT_X + Inches(0.10), col_top + Inches(0.22), CARD_W - Inches(0.2))

    # Secondary card: EXISTING VEHICLE (orange theme, only if data present)
    if exist_has_data:
        ex_bg = slide.shapes.add_textbox(EXIST_X, col_top - Inches(0.04), CARD_W, card_h)
        ex_bg.fill.solid()
        ex_bg.fill.fore_color.rgb = DTM_ORANGE_BG
        _add_border(ex_bg, DTM_ORANGE, 1.0)
        _textbox(slide, EXIST_X + Inches(0.10), col_top, CARD_W - Inches(0.2), Inches(0.22),
                 "EXISTING VEHICLE", font_size=7, bold=True, color=DTM_ORANGE)
        _kv_block(slide, [
            ("Year",    ex_year      or "—"),
            ("Make",    ex_make      or "—"),
            ("Model",   ex_model_str or "—"),
            ("Unit ID", ex_unit      or "—"),
            ("VIN",     ex_vin       or "—"),
        ], EXIST_X + Inches(0.10), col_top + Inches(0.22), CARD_W - Inches(0.2))

    # ── Stats row: number tiles ───────────────────────────────────────────────
    stats_top = col_top + card_h + Inches(0.18)

    lights_count = sum(1 for p in parts
                       if getattr(p, "category", "") in MANIFEST_LIGHT_CATS)

    light_brands = sorted({
        getattr(p, "manufacturer", "").strip()
        for p in parts
        if getattr(p, "category", "") in MANIFEST_LIGHT_CATS
        and getattr(p, "manufacturer", "").strip()
    })
    brands_str = ", ".join(light_brands) if light_brands else "—"

    num_stats = [
        (str(lights_count), "Lights + Bars",     brands_str, DTM_NAVY,   _PANEL_BG),
        (str(reused_count), "Reused / Transfer", "",         TAG_REUSED, _REUSED_BG),
    ]
    TILE_W   = Inches(2.36)
    TILE_H   = Inches(0.72)
    TILE_GAP = Inches(0.10)

    for i, (num_str, label, sublabel, num_color, bg_color) in enumerate(num_stats):
        tx = L + i * (TILE_W + TILE_GAP)
        tb = slide.shapes.add_textbox(tx, stats_top, TILE_W, TILE_H)
        tb.fill.solid()
        tb.fill.fore_color.rgb = bg_color
        _add_border(tb, _LIGHT_GRAY, 0.5)
        tf = tb.text_frame
        tf.margin_left   = Inches(0.10)
        tf.margin_top    = Inches(0.06)
        tf.margin_bottom = 0
        p = tf.paragraphs[0]
        nr = p.add_run()
        nr.text           = num_str
        nr.font.size      = Pt(24)
        nr.font.bold      = True
        nr.font.color.rgb = num_color
        p2 = tf.add_paragraph()
        lr = p2.add_run()
        lr.text           = label
        lr.font.size      = Pt(7.5)
        lr.font.color.rgb = DTM_NAVY
        if sublabel:
            p3 = tf.add_paragraph()
            sr = p3.add_run()
            sr.text           = sublabel
            sr.font.size      = Pt(6.5)
            sr.font.italic    = True
            sr.font.color.rgb = DTM_GRAY

    # ── Build scope text tiles ────────────────────────────────────────────────
    text_top = stats_top + TILE_H + Inches(0.10)

    text_cards = [
        ("Cage Type",     "—"),
        ("Bumper",        "—"),
        ("Roof Equipment","—"),
        ("Equipment Tray","—"),
    ]
    TEXT_TILE_W = Inches(2.98)
    TEXT_TILE_H = Inches(0.72)
    TEXT_GAP    = Inches(0.10)

    for i, (card_label, card_value) in enumerate(text_cards):
        tx = L + i * (TEXT_TILE_W + TEXT_GAP)
        tb = slide.shapes.add_textbox(tx, text_top, TEXT_TILE_W, TEXT_TILE_H)
        tb.fill.solid()
        tb.fill.fore_color.rgb = _PANEL_BG
        _add_border(tb, _LIGHT_GRAY, 0.5)
        tf = tb.text_frame
        tf.margin_left = Inches(0.10)
        tf.margin_top  = Inches(0.07)
        p = tf.paragraphs[0]
        lbl_r = p.add_run()
        lbl_r.text           = card_label
        lbl_r.font.size      = Pt(7.5)
        lbl_r.font.bold      = True
        lbl_r.font.color.rgb = DTM_NAVY
        p2 = tf.add_paragraph()
        val_r = p2.add_run()
        val_r.text           = card_value
        val_r.font.size      = Pt(16)
        val_r.font.bold      = True
        val_r.font.color.rgb = DTM_GRAY


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
              font_size=8, bold=True, color=_WHITE, bg=DTM_NAVY,
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
        _fmt_cell(table.cell(row_idx, c), val,
                  font_size=8, bold=is_name, color=cell_clr, bg=cell_bg)
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

    # Strict available height: generous buffer ensures table never touches footer
    avail_h = SLIDE_H_EMU - MANIFEST_TABLE_TOP - FOOTER_H - Inches(0.40)

    slides_added = 0
    i = 0
    page_num = 0

    while i < len(all_rows):
        page_num += 1
        slide_rows: list[tuple] = []
        used_h = MANIFEST_HDR_ROW_H

        while i < len(all_rows):
            rtype = all_rows[i][0]
            row_h = MANIFEST_SEC_ROW_H if rtype == "section" else MANIFEST_DATA_ROW_H
            if used_h + row_h > avail_h and slide_rows:
                break
            slide_rows.append(all_rows[i])
            used_h += row_h
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
                      font_size=8, bold=True, color=_WHITE,
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

def place_vehicle_image(slide, vehicle_type, view):
    """Return (picture_shape | None, img_box | None).  img_box is (L,T,W,H) in EMU.

    For the side view the vehicle is placed in the bottom ~3" of the slide so
    the legend grid can occupy the top portion.
    """
    slot = find_shape(slide, "VEHICLE_IMAGE_SLOT")
    if not slot:
        return None, None
    slot_left, slot_top, slot_w, slot_h = slot_geometry(slot)

    # Side/top view: move vehicle to bottom so legend grid fits above
    if view in ("side", "top"):
        slot_left = 0
        slot_top  = Inches(4.10)
        slot_w    = SLIDE_W_EMU
        slot_h    = SLIDE_H_EMU - Inches(4.10) - FOOTER_H - Inches(0.05)

    png = ensure_workspace().workspace_assets_dir / "vehicles" / f"{vehicle_type}_{view}.png"
    if not png.exists():
        return None, (slot_left, slot_top, slot_w, slot_h)

    from PIL import Image as PILImage
    with PILImage.open(png) as img:
        img_w, img_h = img.size

    img_ratio  = img_w / img_h
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

    pic = slide.shapes.add_picture(str(png), final_left, final_top,
                                   width=final_w, height=final_h)
    _lock_picture_position(pic)
    return pic, (final_left, final_top, final_w, final_h)


# ─────────────────────────────────────────────────────────────────────────────
# Legend — standard sidebar (front / top / rear views)
# ─────────────────────────────────────────────────────────────────────────────

def place_legend(slide, placed, unplaced, accessory_map: dict | None = None,
                 view: str = "") -> None:
    slot = find_shape(slide, "LEGEND_SLOT")
    if slot:
        slot._element.getparent().remove(slot._element)

    PANEL_LEFT  = Inches(9.20)
    PANEL_TOP   = Inches(1.02)
    PANEL_W     = Inches(4.00)
    PANEL_H     = SLIDE_H_EMU - PANEL_TOP - FOOTER_H - Inches(0.08)
    STRIPE_W    = Inches(0.07)
    BOTTOM_EDGE = PANEL_TOP + PANEL_H

    y = PANEL_TOP

    # Section header
    count     = len(placed)
    hdr_label = (f"  {count} INSTALLED COMPONENT{'S' if count != 1 else ''}"
                 if placed else "  ON THIS VIEW")
    hdr_h = Inches(0.30)
    hdr   = slide.shapes.add_textbox(PANEL_LEFT, y, PANEL_W, hdr_h)
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = DTM_NAVY
    tf = hdr.text_frame
    tf.margin_left = Inches(0.08)
    tf.margin_top  = Inches(0.07)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = hdr_label
    r.font.size      = Pt(8)
    r.font.bold      = True
    r.font.color.rgb = _WHITE
    y += hdr_h + Inches(0.04)

    # Empty state
    if not placed and not unplaced:
        msg = ("NO ROOF-MOUNTED\nCOMPONENTS SPECIFIED"
               if view.lower() == "top" else "NO COMPONENTS\nON THIS VIEW")
        tb = slide.shapes.add_textbox(PANEL_LEFT + Inches(0.12), y,
                                       PANEL_W - Inches(0.2), Inches(0.70))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_top  = Inches(0.10)
        tf.margin_left = Inches(0.08)
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text           = msg
        r.font.size      = Pt(9)
        r.font.italic    = True
        r.font.color.rgb = DTM_GRAY
        return

    unplaced_reserve = Inches(1.1) if unplaced else Inches(0.05)
    avail_cards      = BOTTOM_EDGE - y - unplaced_reserve
    n_parts          = max(len(placed), 1)
    CARD_GAP         = Inches(0.03)
    card_h           = min(Inches(0.68),
                           max(Inches(0.40),
                               (avail_cards - CARD_GAP * n_parts) / n_parts))

    acc = accessory_map or {}
    for part in placed:
        if y + card_h > BOTTOM_EDGE - unplaced_reserve:
            break

        reused       = getattr(part, "is_reused", False)
        stripe_color = TAG_REUSED if reused else TAG_NEW
        bg_color     = _REUSED_BG if reused else _NEW_BG

        _stripe_box(slide, PANEL_LEFT, y, STRIPE_W, card_h - Inches(0.02), stripe_color)
        _card_bg(slide, PANEL_LEFT + STRIPE_W, y,
                 PANEL_W - STRIPE_W, card_h - Inches(0.02), bg_color)

        inner_x = PANEL_LEFT + STRIPE_W + Inches(0.06)
        inner_w = PANEL_W - STRIPE_W - Inches(0.10)
        tb = slide.shapes.add_textbox(inner_x, y + Inches(0.04),
                                       inner_w, card_h - Inches(0.04))
        tf = tb.text_frame
        tf.word_wrap   = True
        tf.margin_top  = 0
        tf.margin_left = 0

        p  = tf.paragraphs[0]
        nr = p.add_run()
        nr.text           = part.name
        nr.font.size      = Pt(8.5)
        nr.font.bold      = True
        nr.font.color.rgb = DTM_NAVY
        badge = p.add_run()
        badge.text           = "   ↺ REUSED" if reused else "   ■ NEW"
        badge.font.size      = Pt(6.5)
        badge.font.bold      = True
        badge.font.color.rgb = stripe_color

        mfg  = getattr(part, "manufacturer", "") or ""
        pnum = getattr(part, "part_number",   "") or ""
        if mfg or pnum:
            p2 = tf.add_paragraph()
            r2 = p2.add_run()
            r2.text           = "  " + "  ·  ".join(filter(None, [mfg, pnum]))
            r2.font.size      = Pt(7)
            r2.font.color.rgb = DTM_GRAY

        cl = _color_lens_label(part)
        if cl:
            p3 = tf.add_paragraph()
            r3 = p3.add_run()
            r3.text           = f"  {cl}"
            r3.font.size      = Pt(7)
            r3.font.color.rgb = DTM_GRAY

        raw_loc = getattr(part, "location", "") or ""
        if raw_loc and not raw_loc.upper().startswith("FIXTURE:"):
            p4 = tf.add_paragraph()
            r4 = p4.add_run()
            r4.text           = f"  @ {raw_loc}"
            r4.font.size      = Pt(7)
            r4.font.color.rgb = DTM_GRAY

        for acc_name in acc.get(part.name, []):
            pa = tf.add_paragraph()
            ra = pa.add_run()
            ra.text           = f"  + {acc_name}"
            ra.font.size      = Pt(6.5)
            ra.font.italic    = True
            ra.font.color.rgb = DTM_GRAY

        y += card_h + CARD_GAP

    if unplaced:
        y += Inches(0.04)
        box_h    = Inches(0.22) + len(unplaced) * Inches(0.17)
        box_h    = min(box_h, BOTTOM_EDGE - y - Inches(0.05))
        bordered = slide.shapes.add_textbox(PANEL_LEFT, y, PANEL_W, box_h)
        bordered.fill.solid()
        bordered.fill.fore_color.rgb = RGBColor(0xFF, 0xF3, 0xF0)
        _add_border(bordered, DTM_RED, 0.5)
        tf = bordered.text_frame
        tf.word_wrap   = True
        tf.margin_left = Inches(0.08)
        tf.margin_top  = Inches(0.05)
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text           = "ADDITIONAL COMPONENTS NOT SHOWN"
        r.font.size      = Pt(7)
        r.font.bold      = True
        r.font.color.rgb = DTM_RED
        for upart in unplaced:
            loc = getattr(upart, "location", "") or "?"
            p2  = tf.add_paragraph()
            r2  = p2.add_run()
            r2.text           = f"  {upart.name}  @  {loc}"
            r2.font.size      = Pt(7)
            r2.font.color.rgb = DTM_RED


# ─────────────────────────────────────────────────────────────────────────────
# Legend — grid layout for side view (vehicle at bottom, cards at top)
# ─────────────────────────────────────────────────────────────────────────────

def place_legend_grid(slide, placed, unplaced, accessory_map: dict | None = None) -> None:
    """Render part cards in a 4-column grid occupying the top portion of the slide.

    Used for the side view where the vehicle image is moved to the bottom half.
    """
    slot = find_shape(slide, "LEGEND_SLOT")
    if slot:
        slot._element.getparent().remove(slot._element)

    GRID_LEFT    = Inches(0.3)
    GRID_TOP     = Inches(0.95)   # flush with header band bottom
    GRID_BOTTOM  = Inches(3.95)   # vehicle image starts at 4.10", leave small gap
    GRID_COLS    = 4
    COL_GAP      = Inches(0.10)
    COL_W        = (SLIDE_W_EMU - GRID_LEFT * 2 - COL_GAP * (GRID_COLS - 1)) / GRID_COLS
    STRIPE_W     = Inches(0.06)
    CARD_GAP_V   = Inches(0.07)

    # Section header spanning full width
    count     = len(placed)
    hdr_label = (f"  {count} INSTALLED COMPONENT{'S' if count != 1 else ''}"
                 if placed else "  SIDE VIEW COMPONENTS")
    hdr_h = Inches(0.28)
    hdr   = slide.shapes.add_textbox(GRID_LEFT, GRID_TOP,
                                      SLIDE_W_EMU - GRID_LEFT * 2, hdr_h)
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = DTM_NAVY
    tf = hdr.text_frame
    tf.margin_left = Inches(0.10)
    tf.margin_top  = Inches(0.06)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text           = hdr_label
    r.font.size      = Pt(8)
    r.font.bold      = True
    r.font.color.rgb = _WHITE

    card_area_top  = GRID_TOP + hdr_h + Inches(0.06)
    avail_h        = GRID_BOTTOM - card_area_top
    n_parts        = max(len(placed), 1)
    n_rows         = max(1, -(-n_parts // GRID_COLS))   # ceiling division
    card_h         = min(Inches(0.85),
                         max(Inches(0.45),
                             (avail_h - CARD_GAP_V * (n_rows - 1)) / n_rows))

    acc = accessory_map or {}
    last_card_bottom = card_area_top  # updated after each rendered card row

    if not placed and not unplaced:
        tb = slide.shapes.add_textbox(GRID_LEFT + Inches(0.12), card_area_top,
                                       Inches(8), Inches(0.60))
        tf = tb.text_frame
        p  = tf.paragraphs[0]
        r  = p.add_run()
        r.text           = "NO SIDE-VIEW COMPONENTS SPECIFIED"
        r.font.size      = Pt(9)
        r.font.italic    = True
        r.font.color.rgb = DTM_GRAY
    else:
        for i, part in enumerate(placed):
            col_i = i % GRID_COLS
            row_i = i // GRID_COLS
            cx    = GRID_LEFT + col_i * (COL_W + COL_GAP)
            cy    = card_area_top + row_i * (card_h + CARD_GAP_V)
            if cy + card_h > GRID_BOTTOM:
                break
            last_card_bottom = cy + card_h

            reused       = getattr(part, "is_reused", False)
            stripe_color = TAG_REUSED if reused else TAG_NEW
            bg_color     = _REUSED_BG if reused else _NEW_BG

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

            p  = tf.paragraphs[0]
            nr = p.add_run()
            nr.text           = part.name
            nr.font.size      = Pt(8)
            nr.font.bold      = True
            nr.font.color.rgb = DTM_NAVY
            badge = p.add_run()
            badge.text           = "  ↺" if reused else "  ■"
            badge.font.size      = Pt(7)
            badge.font.bold      = True
            badge.font.color.rgb = stripe_color

            mfg  = getattr(part, "manufacturer", "") or ""
            pnum = getattr(part, "part_number",   "") or ""
            if mfg or pnum:
                p2 = tf.add_paragraph()
                r2 = p2.add_run()
                r2.text           = "  " + "  ·  ".join(filter(None, [mfg, pnum]))
                r2.font.size      = Pt(6.5)
                r2.font.color.rgb = DTM_GRAY

            cl = _color_lens_label(part)
            if cl:
                p3 = tf.add_paragraph()
                r3 = p3.add_run()
                r3.text           = f"  {cl}"
                r3.font.size      = Pt(6.5)
                r3.font.color.rgb = DTM_GRAY

            for acc_name in acc.get(part.name, []):
                pa = tf.add_paragraph()
                ra = pa.add_run()
                ra.text           = f"  +{acc_name}"
                ra.font.size      = Pt(6)
                ra.font.italic    = True
                ra.font.color.rgb = DTM_GRAY

    if unplaced:
        # Place "not shown" note just below the lowest rendered card row
        y_note = last_card_bottom + Inches(0.08)
        box_h  = Inches(0.20) + len(unplaced) * Inches(0.16)
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
        r.font.size      = Pt(7)
        r.font.bold      = True
        r.font.color.rgb = DTM_RED
        for upart in unplaced:
            loc = getattr(upart, "location", "") or "?"
            p2  = tf.add_paragraph()
            r2  = p2.add_run()
            r2.text           = f"  {upart.name}  @  {loc}"
            r2.font.size      = Pt(6.5)
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
    r.font.size      = Pt(7)
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

_NOTES_SECTIONS = [
    "INSTALLATION NOTES",
    "CUSTOMER REQUESTS",
    "SPECIAL FABRICATION NOTES",
    "DELIVERY REQUIREMENTS",
    "FINAL APPROVALS",
]


def fill_notes(slide, notes) -> None:
    slot = find_shape(slide, "NOTES_SLOT")
    if not slot:
        return
    left, top, width, height = slot_geometry(slot)

    y       = top
    sec_gap = Inches(0.14)
    label_h = Inches(0.26)
    line_h  = Inches(0.22)
    placeholder_color = RGBColor(0xAA, 0xAA, 0xAA)

    for sec_idx, section in enumerate(_NOTES_SECTIONS):
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
        r.font.size      = Pt(9)
        r.font.bold      = True
        r.font.color.rgb = DTM_NAVY
        y += label_h + Inches(0.06)

        if sec_idx == 0 and notes:
            for idx, note in enumerate(notes):
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
            placeholder_text = {
                "CUSTOMER REQUESTS":         "No customer requests specified.",
                "SPECIAL FABRICATION NOTES": "No special fabrication notes specified.",
                "DELIVERY REQUIREMENTS":     "No delivery requirements specified.",
                "FINAL APPROVALS":           "Pending final inspection sign-off.",
            }.get(section, "No notes specified.")
            tb  = slide.shapes.add_textbox(left + Inches(0.2), y,
                                            width - Inches(0.2), line_h)
            tf2 = tb.text_frame
            p2  = tf2.paragraphs[0]
            r2  = p2.add_run()
            r2.text           = placeholder_text
            r2.font.size      = Pt(10)
            r2.font.italic    = True
            r2.font.color.rgb = placeholder_color
            y += line_h

        y += sec_gap
