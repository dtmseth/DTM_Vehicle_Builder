"""Tests for QB Sales-Description color/lens parsing (qb_apply_links).

Covers the description variation Whelen uses: spelled-out names, abbreviations,
single-letter initials, and "/ - space none" separators, plus trios, smoked
lens detection, and false-positive guards.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from qb_apply_links import _parse_color_from_item, apply_mapping  # noqa: E402


def c(desc, sku=""):
    return _parse_color_from_item(desc, sku)


# ── spelled-out + abbreviations ──────────────────────────────────────────────

def test_spelled_slash_duo():
    r = c("WHELEN ION LIGHT RED/WHITE")
    assert (r["color"], r["secondary_color"], r["tertiary_color"]) == ("red", "white", "")


def test_abbrev_slash():
    r = c("WHELEN SURFACE MT ION LT BLU/WHT")
    assert (r["color"], r["secondary_color"]) == ("blue", "white")


def test_single_color():
    r = c("WHELEN ION LIGHT AMBER")
    assert r["color"] == "amber" and r["secondary_color"] == ""


# ── separator variations ─────────────────────────────────────────────────────

def test_dash_separator():
    r = c("WHELEN VXE DUO DIRECTIONAL LT R-W/SMK", "VX2DX")
    assert (r["color"], r["secondary_color"], r["lens_type"]) == ("red", "white", "smoked")


def test_slash_initials_trio():
    r = c("WHELEN VXE TRIO DIRECTIONAL LT R/B/W", "VX3RBC")
    assert (r["color"], r["secondary_color"], r["tertiary_color"]) == ("red", "blue", "white")


def test_no_separator_trio_with_context():
    r = c("WHELEN VXE TRIO DIRECTIONAL BAW/SMK", "VX3BACX")
    assert (r["color"], r["secondary_color"], r["tertiary_color"]) == ("blue", "amber", "white")
    assert r["lens_type"] == "smoked"


def test_mixed_initials_and_word():
    r = c("WHELEN TRIO ION R/B WHT OVERRIDE SMK", "XI3JC")
    assert (r["color"], r["secondary_color"], r["tertiary_color"]) == ("red", "blue", "white")


def test_dash_trio():
    r = c("WHELEN U-SERIES TRIO R-A-W/SMOKE", "U180KCX")
    assert (r["color"], r["secondary_color"], r["tertiary_color"]) == ("red", "amber", "white")


def test_parenthesized_color():
    r = c("WHELEN MINI CENTURY LIGHTBAR 23\" WITH PERM KIT (AMBER)", "MC23PA")
    assert r["color"] == "amber"


# ── lens detection ───────────────────────────────────────────────────────────

def test_smoke_word():
    assert c("WHELEN ION LIGHT BLUE W/ SMOKE LENS", "XONB")["lens_type"] == "smoked"


def test_clear_default_when_color_present():
    assert c("WHELEN ION LIGHT RED")["lens_type"] == "clear"


def test_x_prefix_smoked_fallback():
    # No lens word in desc, but X-prefix SKU → smoked fallback.
    assert c("WHELEN ION LIGHT BLUE", "XONB")["lens_type"] == "smoked"


def test_no_lens_without_color():
    assert c("WHELEN SIREN SPEAKER")["lens_type"] == ""


# ── false-positive guards ────────────────────────────────────────────────────

def test_bare_code_without_combo_context_ignored():
    # "PB" (push bumper) must NOT become purple/blue without DUO/TRIO context.
    r = c("WHELEN LIGHT CENTER PLATE OF PB")
    assert r["color"] == ""


def test_tracer_config_code_not_color():
    # "WXC" is a config code, not a color.
    r = c("WHELEN TWO LAMP TRACER WXC", "TCRWX2")
    assert r["color"] == "" and r["secondary_color"] == ""


def test_blk_not_a_color():
    r = c("WHELEN DUO LINEAR ION RED/WHITE BLK", "I2D")
    assert (r["color"], r["secondary_color"], r["tertiary_color"]) == ("red", "white", "")


def test_wecanx_programmable_no_color():
    r = c("WHELEN I-E RST WCX 10-LT TRIO DURANGO", "BS44ZT")
    assert r["color"] == "" and r["secondary_color"] == ""


def test_apply_mapping_preserves_explicit_universal_vehicle_tags_and_qb_description():
    parts_db = {
        "part_types": {"howler": {"type_id": "equipment"}},
        "products": {
            "whelen_wcx_howler": {
                "manufacturer_id": "whelen",
                "model": "Howler WCX",
                "fits_part_types": ["howler"],
                "part_numbers": [],
            }
        },
    }
    mapping = {
        "links": [{
            "sku": "CHWLUNI",
            "product": "whelen_wcx_howler",
            "vehicle_tags": [],
        }]
    }
    cache = {
        "CHWLUNI": {
            "qb_item_id": "1290",
            "sku": "",
            "description": "WHELEN WCX LOW FREQ SIREN AMP UNIV MT",
            "unit_price": 756.0,
        }
    }

    apply_mapping(parts_db, mapping, cache)

    entry = parts_db["products"]["whelen_wcx_howler"]["part_numbers"][0]
    assert entry["vehicle_tags"] == []
    assert entry["qb_sales_description"] == cache["CHWLUNI"]["description"]
