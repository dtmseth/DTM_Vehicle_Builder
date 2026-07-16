"""Data-quality guards for picker-facing parts_db product labels."""
from __future__ import annotations

import json
import re

from tests.contract.harness import hermetic_paths


GENERIC_SELECTABLE_MODELS = {
    "ADJUSTABLE MAG CLIP",
    "ALL IN ONE UNIT",
    "ANTENNA",
    "ANGLE BRACKET",
    "CARGO BRACKET KIT",
    "CCTL5",
    "CCTL6",
    "CCTL7",
    "CCTL8",
    "CCTL9",
    "CEM8",
    "CEM16",
    "CEM24",
    "CLIP",
    "DSR",
    "ETHERNET CABLE",
    "FIRST NET ROOF MOUNT",
    "FIRST NET WINDOW MOUNT",
    "FIRE EXTINGUISHER BRACKETS",
    "FRONT OVERHEAD BRACKETS",
    "FRONT RIGHT OF DASH",
    "GROMMET MOUNT",
    "HDX",
    "ION",
    "L BRACKET",
    "L-BRACKET",
    "L31",
    "L32",
    "LICENSE PLATE BRACKET",
    "M500",
    "MOUNTING BRACKET",
    "MOUNTING HINGE",
    "NON-WATER PROOF",
    "PB5",
    "PB6",
    "PB8",
    "PB9",
    "PB10",
    "POLY",
    "REAR OVERHEAD BRACKETS",
    "RECESS MOUNTING BRACKET",
    "ROLL BAR MOUNT",
    "ROOF MOUNT",
    "ROOF MOUNTED",
    "SAK1",
    "SAK9",
    "SIDE MOUNT ARMREST",
    "SPLIT UNIT",
    "T-RAIL MOUNT KIT",
    "TAHOE DISPLAY MOUNT",
    "UNIVERSAL GRILL BRACKET",
    "VEHICLE SPECIFIC",
    "VEHICLE SPECIFIC BRACKET",
    "VERIZON ROOF MOUNT",
    "VERIZON WINDOW MOUNT",
    "VSS INSTALLATION KIT",
    "VXE",
    "W/BRACKET",
    "WATER PROOF",
    "WINDOW MOUNT",
}

MANUFACTURER_PREFIX_ALIASES = {
    "5_0_fab_dtm": ["5-0 Fab", "5.0 Fab"],
    "cradle_point": ["CradlePoint", "Cradle Point"],
    "go_rhino": ["Go Rhino"],
    "gamber_johnson": ["Gamber Johnson", "Gamber-Johnson"],
    "magnetic_mic": ["Magnetic Mic"],
    "pro_gard": ["Pro-Gard", "Pro Gard"],
    "soundoff": ["SoundOff", "Soundoff", "Sound Off"],
    "watchguard": ["WatchGuard", "Watchguard"],
}

VEHICLE_TEXT_PATTERNS = [
    ("PIU", re.compile(r"POLICE INTERCEPTOR UTILITY|\bFORD UTILITY\b|\bFORD PIU\b|\bFORD EXPLORER\b", re.I)),
    ("TAHOE", re.compile(r"\bTAHOE\b", re.I)),
    ("DURANGO", re.compile(r"\bDURANGO\b", re.I)),
    ("F-150", re.compile(r"\bF[- ]?150\b|\bF150\b", re.I)),
    ("SUPER-DUTY", re.compile(r"\bF[- ]?(250|350|450|550)\b|SUPER[ -]?DUTY", re.I)),
    ("EXPEDITION", re.compile(r"\bEXPEDITION\b", re.I)),
    ("RAM-1500", re.compile(r"\bRAM 1500\b", re.I)),
    ("CHEVY-1500", re.compile(r"\bSILVERADO 1500\b|\bCHEV(Y|ROLET)? TRUCK 1500\b", re.I)),
    (
        "SILVERADO-HD",
        re.compile(r"\bSILVERADO (2500|3500)\b|\bCHEV(Y|ROLET)? TRUCK (2500|3500)\b", re.I),
    ),
    ("SUBURBAN", re.compile(r"\bSUBURBAN\b", re.I)),
    ("YUKON", re.compile(r"\bYUKON\b", re.I)),
    ("MACH-E", re.compile(r"\bMACH[- ]?E\b", re.I)),
    ("MUSTANG", re.compile(r"\bMUSTANG\b", re.I)),
    ("RAM-HD", re.compile(r"\bRAM (2500|3500)\b", re.I)),
    ("TRAVERSE", re.compile(r"\bTRAVERSE\b", re.I)),
]


def _normalized_prefix_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _selectable_product_has_visible_leaf(product: dict, part_types: dict) -> bool:
    fits = [pt_id for pt_id in product.get("fits_part_types") or [] if pt_id in part_types]
    if not fits:
        return False
    return not all((part_types.get(pt_id) or {}).get("browse_hidden") for pt_id in fits)


def test_no_exact_generic_models_remain_selectable(tmp_path):
    paths = hermetic_paths(tmp_path)
    doc = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))
    products = doc.get("products") or {}
    part_types = doc.get("part_types") or {}

    offenders: list[str] = []
    for product_id, product in products.items():
        if product.get("browse_hidden"):
            continue
        model = str(product.get("model") or "").strip().upper()
        if model not in GENERIC_SELECTABLE_MODELS:
            continue
        if not _selectable_product_has_visible_leaf(product, part_types):
            continue
        offenders.append(f"{product_id}: {product.get('model')}")

    assert offenders == []


def test_selectable_models_do_not_start_with_own_manufacturer(tmp_path):
    paths = hermetic_paths(tmp_path)
    doc = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))
    manufacturers = doc.get("manufacturers") or {}
    part_types = doc.get("part_types") or {}

    offenders: list[str] = []
    for product_id, product in (doc.get("products") or {}).items():
        if product.get("browse_hidden"):
            continue
        if not _selectable_product_has_visible_leaf(product, part_types):
            continue
        model = str(product.get("model") or "").strip()
        if not model:
            continue
        manufacturer_id = str(product.get("manufacturer_id") or "")
        manufacturer = manufacturers.get(manufacturer_id) or {}
        prefixes = [
            str(manufacturer.get("label") or ""),
            *MANUFACTURER_PREFIX_ALIASES.get(manufacturer_id, []),
        ]
        normalized_model = _normalized_prefix_text(model)
        for prefix in prefixes:
            normalized_prefix = _normalized_prefix_text(prefix)
            if normalized_prefix and normalized_model.startswith(normalized_prefix):
                offenders.append(f"{product_id}: {model}")
                break

    assert offenders == []


def test_clear_vehicle_fit_text_has_vehicle_tags(tmp_path):
    paths = hermetic_paths(tmp_path)
    doc = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))

    offenders: list[str] = []
    for product_id, product in (doc.get("products") or {}).items():
        for sku in product.get("part_numbers") or []:
            text = " ".join(
                str(value)
                for value in (
                    product.get("model", ""),
                    sku.get("friendly_name", ""),
                    sku.get("part_number", ""),
                )
                if value
            )
            expected = [tag for tag, pattern in VEHICLE_TEXT_PATTERNS if pattern.search(text)]
            if "MACH-E" in expected and "MUSTANG" in expected:
                expected.remove("MUSTANG")
            if not expected:
                continue
            vehicle_tags = set(sku.get("vehicle_tags") or [])
            missing = [tag for tag in expected if tag not in vehicle_tags]
            if missing or vehicle_tags == {"any"}:
                offenders.append(f"{product_id}/{sku.get('part_number')}: missing {missing or expected}")

    assert offenders == []
