from __future__ import annotations

import importlib.util
from pathlib import Path


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "apply_soundoff_builder_catalog.py"
SPEC = importlib.util.spec_from_file_location("apply_soundoff_builder_catalog", TOOL_PATH)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def test_parent_split_is_order_independent_and_preserves_dimension_commas():
    left = tool.split_parent_families(
        'mpower® Fascia 4", Intersector Surface Mount, mpower® Fascia 3"'
    )
    right = tool.split_parent_families(
        'mpower® Fascia 3", mpower® Fascia 4", Intersector Surface Mount'
    )
    assert left == right
    assert tool.split_parent_families('obSERVE+ Dome Light, 3"') == (
        'obSERVE+ Dome Light, 3"',
    )


def test_pilot_adds_exactly_one_accessory_with_reviewed_parent():
    db = {
        "products": {
            "soundoff_mpower_3_fascia": {
                "manufacturer_id": "soundoff",
                "model": 'MPOWER 3" Fascia Light',
                "part_numbers": [],
            }
        }
    }
    records = [{
        "sku": "PMP1BK005",
        "qb_item_id": "4432",
        "builder_status": "Inbox open",
        "vehicle_tags": "any",
        "description": "Stud Mount Conversion Bracket Kit",
    }]
    cache = {"4432": {
        "qb_item_id": "4432",
        "name": "PMP1BK005",
        "sku": "",
        "description": "STUD MOUNT CONVERSION BRACKET KIT",
        "unit_price": 12.0,
    }}
    plan = {
        "source_edit_revision": "rev-1",
        "planned_products": [{
            "product_id": "soundoff_mpower_fascia_3_bracket_conversion",
            "model": 'mpower® Fascia 3" — Bracket - Conversion',
            "fits_part_types": ["bracket"],
            "tag_ids": [],
            "accessory_category": "bracket_mount",
            "accessory_of_products": ["soundoff_mpower_3_fascia"],
            "skus": ["PMP1BK005"],
        }],
    }

    result, receipt = tool.apply_pilot(db, cache, records, plan, "PMP1BK005")
    assert db.keys() == {"products"}  # input is not mutated
    product = result["products"][receipt["product_id"]]
    assert product["accessory_of_products"] == ["soundoff_mpower_3_fascia"]
    assert product["accessory_category"] == "bracket_mount"
    assert product["part_numbers"] == [{
        "part_number": "PMP1BK005",
        "friendly_name": "STUD MOUNT CONVERSION BRACKET KIT",
        "qb_item_id": "4432",
        "qb_sku": "",
        "qb_sales_description": "STUD MOUNT CONVERSION BRACKET KIT",
        "qb_unit_price": 12.0,
        "qb_last_synced": product["part_numbers"][0]["qb_last_synced"],
        "vehicle_tags": ["any"],
        "options": {},
    }]


def test_full_apply_is_additive_and_verifies_exact_parent_links():
    db = {
        "metadata": {"edit_revision": "rev-1"},
        "products": {
            "soundoff_parent": {
                "manufacturer_id": "soundoff",
                "model": "Parent",
                "fits_part_types": ["warning_light"],
                "tag_ids": ["light"],
                "part_numbers": [{"part_number": "OLD", "qb_item_id": "old-id"}],
            },
            "unrelated": {
                "manufacturer_id": "other",
                "model": "Untouched",
                "part_numbers": [],
            },
        },
    }
    records = [{
        "sku": "ACC1",
        "qb_item_id": "new-id",
        "builder_status": "Inbox open",
        "vehicle_tags": "any",
        "description": "Exact accessory",
    }]
    cache = {"new-id": {
        "qb_item_id": "new-id",
        "name": "ACC1",
        "sku": "",
        "description": "EXACT ACCESSORY",
        "unit_price": 10.0,
    }}
    plan = {
        "source_edit_revision": "rev-1",
        "summary": {"remaining_open_records": 1},
        "virtual_parent_products": {},
        "planned_products": [{
            "product_id": "soundoff_accessory",
            "model": "Accessory",
            "reuses_existing_product": False,
            "fits_part_types": ["bracket"],
            "tag_ids": [],
            "accessory_category": "bracket_mount",
            "accessory_of_products": ["soundoff_parent"],
            "skus": ["ACC1"],
            "qb_item_ids": ["new-id"],
        }],
    }

    result, receipt = tool.apply_all(db, cache, records, plan)
    assert result["products"]["unrelated"] == db["products"]["unrelated"]
    assert result["products"]["soundoff_accessory"]["accessory_of_products"] == ["soundoff_parent"]
    assert receipt["added_qbo_items"] == 1
    tool.verify_full_apply(db, result, records, plan, receipt)


def test_part_number_expands_super_duty_compatibility():
    part_number = tool._part_number_from_record(
        {
            "qb_item_id": "new-id",
            "description": "Fits Ford F-150 and Super Duty",
            "vehicle_tags": "FORD F-150",
        },
        {
            "qb_item_id": "new-id",
            "name": "BRACKET",
            "description": "Ford bracket",
            "unit_price": 10.0,
        },
        "2026-10-20T00:00:00Z",
    )

    assert part_number["vehicle_tags"] == [
        "FORD F-150",
        "FORD F-250",
        "FORD F-350",
        "FORD F-450",
        "FORD F-550",
    ]
