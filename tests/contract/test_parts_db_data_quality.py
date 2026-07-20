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


def test_console_setup_catalogs_keep_only_matching_equipment(tmp_path):
    """Guard the curated console setup lists against obvious inventory mis-homes."""
    paths = hermetic_paths(tmp_path)
    doc = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))
    products = doc.get("products") or {}

    # The legacy workbook records Mongoose and XE under Gamber Johnson.
    assert products["havis_9_mongoose"]["manufacturer_id"] == "gamber_johnson"
    assert products["havis_9_mongoose"]["fits_part_types"] == []
    assert products["havis_9_xe"]["manufacturer_id"] == "gamber_johnson"
    assert products["gamber_johnson_7160_0220"]["fits_part_types"] == ["motion_attachment"]

    # These are complete console kits, not loose armrests.
    for product_id in (
        "gamber_johnson_7170_0734_02",
        "gamber_johnson_7170_0734_04",
        "gamber_johnson_7170_0734_09",
        "gamber_johnson_7170_0882_02",
        "gamber_johnson_7170_0882_03",
        "havis_pkg_vsx_1800_tah_pm_5",
    ):
        assert products[product_id]["fits_part_types"] == ["console"]

    # Kit contents are structured so the picker can select the closest QB
    # package and avoid billing components already included in its price.
    assert products["gamber_johnson_7170_0734_09"]["console_kit"] == {
        "style": "low_profile",
        "included": {
            "cup_holder": True,
            "oem_relocation_plate": True,
            "armrest": "printer",
            "motion_attachment": "mongoose",
        },
    }
    assert products["havis_pkg_vsx_1800_tah_pm_5"]["console_kit"] == {
        "style": "wide_body",
        "included": {"cup_holder": True, "oem_relocation_plate": True},
    }

    # These accessories support a dock; they are not themselves a dock choice.
    expected_types = {
        "gamber_johnson_18540": "bracket",
        "gamber_johnson_7110_1213": "bracket",
        "gamber_johnson_7110_1385": "bracket",
        "gamber_johnson_7300_0468": "cable",
        "lind_cblop_f90610": "cable",
        "lind_de2045_1342": "cable",
        "havis_lps_211": "bracket",
        "lind_dell_power_adapter_2542": "cable",
    }
    for product_id, part_type in expected_types.items():
        assert products[product_id]["fits_part_types"] == [part_type]


def test_printer_accessory_roles_have_distinct_shop_labels(tmp_path):
    paths = hermetic_paths(tmp_path)
    doc = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))

    categories = doc["accessory_categories"]
    assert categories["printer_mount"]["label"] == "Bracket / Mount"
    assert categories["printer_power_cable"]["label"] == "Power Cable"
    assert categories["printer_usb_cable"]["label"] == "USB Cable"

    part_types = doc["part_types"]
    assert part_types["printer_mount"]["accessory_category"] == "printer_mount"
    assert part_types["printer_power"]["accessory_category"] == "printer_power_cable"
    assert part_types["printer_usb"]["accessory_category"] == "printer_usb_cable"

    products = doc["products"]
    assert products["brother_pocketjet_power_cable"]["accessory_category"] == "printer_power_cable"
    assert products["brother_pocketjet_usb_cable"]["accessory_category"] == "printer_usb_cable"


def test_mega_t_series_exposes_its_90_degree_mount_kit(tmp_path):
    paths = hermetic_paths(tmp_path)
    doc = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))

    products = doc["products"]
    assert products["whelen_mega_t_series"]["accessories"] == [{
        "category": "bracket_mount",
        "product_id": "whelen_strip_lite_mount",
        "required": False,
        "include_generic": True,
    }]
    sku = products["whelen_strip_lite_mount"]["part_numbers"][0]
    assert sku["part_number"] == "PSBKT90"
    assert sku["friendly_name"] == "90° mount kit"


def test_warning_bracket_scope_metadata_keeps_family_specific_mounts_out_of_generic_lists(tmp_path):
    paths = hermetic_paths(tmp_path)
    doc = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))
    products = doc["products"]

    assert any(
        accessory["product_id"] == "whelen_u_mirror_mount"
        for accessory in products["whelen_u_series"]["accessories"]
    )
    assert any(
        accessory["product_id"] == "whelen_fender_mount"
        for accessory in products["whelen_pro_focus"]["accessories"]
    )
    for product_id in ("whelen_vxe", "whelen_vertex"):
        assert any(
            accessory["product_id"] == "dtm_twist_lock_adaptor"
            for accessory in products[product_id]["accessories"]
        )
    for product_id in (
        "westin_westin_2_light_tube",
        "westin_westin_4_light_tube",
        "whelen_tracer_l_brackets_x2_per",
    ):
        assert products[product_id]["include_in_generic_accessory_options"] is False


def test_tiger_tough_seat_covers_are_vehicle_scoped_and_offer_custom_patch_embroidery(tmp_path):
    paths = hermetic_paths(tmp_path)
    doc = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))
    products = doc["products"]

    assert "tiger_tough_standard" not in products
    assert doc["accessory_categories"]["custom_patch"]["label"] == "Custom Patch"
    assert products["tiger_tough_w0523028_iw_blk"]["fits_part_types"] == ["seat_covers"]
    expected_tags = {
        "tiger_tough_t0512017_iw_blk": ["PIU"],
        "tiger_tough_w0521045_iw_blk": ["F-150", "F-150-LIGHTNING", "SUPER-DUTY"],
        "tiger_tough_w0523028_iw_blk": ["F-150", "SUPER-DUTY"],
        "tiger_tough_w0555062_iw_blk": ["F-150", "F-150-LIGHTNING", "SUPER-DUTY"],
        "tiger_tough_w0721000_iw_blk": ["RAM-1500", "RAM-HD"],
    }
    for product_id, tags in expected_tags.items():
        assert products[product_id]["part_numbers"][0]["vehicle_tags"] == tags

    embroidery = products["tiger_tough_embroidery"]
    assert embroidery["accessory_category"] == "custom_patch"
    assert embroidery["part_numbers"][0]["qb_item_id"] == "1209"
    assert "unbilled" not in embroidery["tag_ids"]
    assert set(embroidery["accessory_of_products"]) == {
        product_id for product_id, product in products.items()
        if product.get("manufacturer_id") == "tiger_tough"
        and "seat_covers" in product.get("fits_part_types", [])
    }
    assert not any("digit" in product_id for product_id in products)
