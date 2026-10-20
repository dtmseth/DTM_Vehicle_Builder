#!/usr/bin/env python3
"""Plan and safely apply the researched SoundOff catalog curation.

The normal mode is a read-only full-catalog audit.  ``--pilot SKU --write``
applies exactly one open QuickBooks item after creating a timestamped snapshot.
No fuzzy parent matching is allowed: a parent either maps through an explicit
catalog-family rule, matches a primary family exactly, or receives its own
exactly named non-orderable family anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src/dtm_buildsheet/resources/config/parts_db.json"
CACHE = REPO / "workspace/quickbooks_items_cache.json"
CURATION = REPO / "outputs/2026-10-12-soundoff-builder-curation/soundoff_builder_curation.json"
OUTPUT_DIR = REPO / "outputs/2026-10-12-soundoff-builder-curation"
AUDIT_PATH = OUTPUT_DIR / "soundoff_parent_resolution_audit.json"
FULL_APPLY_CONFIRMATION = "APPLY ALL RESEARCHED SOUNDOFF ITEMS"

MANUFACTURER_ID = "soundoff"

# These are exact catalog aliases, not similarity guesses.  Each left-hand
# label comes from the official price guide's Used With column.  The right-hand
# labels are the reviewed primary product-family names in the curation file.
PARENT_TO_PRIMARY_FAMILIES: dict[str, tuple[str, ...]] = {
    '100J Series Speaker': ('100J Speaker', '100J Speaker with Polished Stainless Cover'),
    '100U Series Speaker': ('100U Speaker',),
    '200 Series Compact Siren': ('200 Series Siren',),
    'bluePRINT® 200 Series Compact Siren': ('200 Series Siren',),
    '4200 Series LED Beacon': (
        '4200 Series 4" Beacon - Flat/Pipe Mount',
        '4200 Series 4" Beacon - Magnetic Mount',
        '4200 Series 6" Beacon - Flat/Pipe Mount',
        '4200 Series 6" Beacon - Magnetic Mount',
    ),
    '4500 Series LED Beacon': (
        '4500 Series 4" Beacon - Flat/Pipe Mount',
        '4500 Series 4" Beacon - Magnetic Mount',
        '4500 Series 6" Beacon - Flat/Pipe Mount',
        '4500 Series 6" Beacon - Magnetic Mount',
    ),
    '600 Series 6 Function Switch': ('600 Series Switch',),
    '900 Series 9 Function Switch': ('900 Series Switch',),
    'bluePRINT® Control Panel': (
        'bluePRINT® Handheld Controller',
        'bluePRINT® Push Button Control Panel',
        'bluePRINT® Rotary Control Panel',
        'bluePRINT® 19-Button Control Panel\u200b',
    ),
    'bluePRINT® 400 Series Siren/Switch Module': (
        'bluePRINT® 400 Series Remote Siren Knob Control, 100 Watt',
        'bluePRINT® 400 Series Remote Siren, Knob, 200 Watt',
        'bluePRINT® 400 Series Console Siren, Button, 100 Watt',
        'bluePRINT® 400 Series Console Siren, Button, 200 Watt',
        'bluePRINT® 400 Series Console Siren, Knob, 100 Watt',
    ),
    'bluePRINT® 500 Series Control System (with Link)': (
        'bluePRINT 500 Series Remote Amp with Link',
        'bluePRINT 500 Series Console 100W Button Control System',
        'bluePRINT 500 Series Console 100W Knob Control System',
        'bluePRINT 500 Series Console 200W Button Control System',
        'bluePRINT 500 Series Console 200W Knob Control System',
    ),
    'bluePRINT® Remote Node': ('Remote Node',),
    'Ford Dual Beacon 360-Degree Lighting Kit': (
        'Ford Dual 360 Degree Light Kit - Ford F-150 High Dome',
        'Ford Dual 360 Degree Light Kit - Ford F-150 Low Dome',
        'Ford Dual 360 Degree Light Kit - Ford Super Duty High Dome',
        'Ford Dual 360 Degree Light Kit - Ford Super Duty Low Dome',
    ),
    'LED3 Plus Surface Mount': ('LED3 Plus',),
    'LF Aftershock Siren System': ('Aftershock',),
    'Headlight & Taillight Flashers': (
        'Headlight Flasher Kit',
        'Select-A-Pattern Headlight Flashers',
        'Headlight Flasher',
        'Flashback Alternating Taillight Flasher',
        'Taillight Flasher Kit',
    ),
    'mpower® Brow Light': (
        'mpower® 15” Brow Light',
        'mpower® 27.5” Brow Light',
        'mpower® 34” Brow Light',
        'mpower® 40” Brow Light',
        'mpower® 53” Brow Light',
        'mpower® 55” Brow Light',
        'mpower® 65.5” Brow Light',
    ),
    'mpower® Grid Light': ('Grid Light',),
    'nERGY 400 Series Console Siren': (
        'nERGY 400 Series Console Siren - Button, 1 speaker',
        'nERGY 400 Series Console Siren - Knob, 1 speaker',
        'nERGY 400 Series Console Siren - Button, 2 speaker',
    ),
    'nERGY 400 Series Handheld Siren': (
        'nERGY 400 Series Handheld Siren - 1 speaker',
        'nERGY 400 Series Handheld Siren - 2 speaker',
    ),
    'nERGY 400 Series Remote Siren': (
        'nERGY 400 Series Remote Siren - Button, 1 speaker',
        'nERGY 400 Series Remote Siren - Knob, 1 speaker',
        'nERGY 400 Series Remote Siren - Button, 2 speaker',
        'nERGY 400 Series Remote Siren - Knob, 2 speaker',
    ),
    'nFORCE® nxt Beacon': ('nFORCE nxt Red/White Beacon', 'nFORCE nxt Blue/White Beacon'),
    'nFUSE® XL Lightbar': (
        'nFUSE® XL 84" Single Color Lightbar',
        'nFUSE® XL 84" Dual Color Lightbar',
        'nFUSE® XL 90" Single Color Lightbar',
        'nFUSE® XL 90" Dual Color Lightbar',
    ),
    'Pinnacle Mini LED Lightbar': ('Pinnacle 7000 Mini Lightbar', 'Pinnacle Mini 7300 Lightbar'),
    'Smart Arrow Board': ('78" Smart Arrow Board',),
    'UltraLITE Plus Exterior LED Warning Bar': ('UltraLITE Plus',),
    'UltraLITE Plus Interior LED Warning Bar': ('UltraLITE Plus',),
    'mpower® Fascia 3"': ('mpower 3" Fascia Light',),
    'mpower® Fascia 4"': ('mpower 4" Fascia Light',),
    'mpower® Fascia 4x2': ('mpower 4x2 Fascia Light',),
    'mpower® 6x4 Scene Light': ('mpower 6x4 Light',),
    'mpower® 6x4 Light': ('mpower 6x4 Light',),
    'mpower® 7x3 Scene Light': ('mpower 7x3 Light',),
    'mpower® 7x3 Light': ('mpower 7x3 Light',),
    'mpower® 9x7 Scene Light': ('mpower 9x7 Light',),
    'mpower® 9x7 Light': ('mpower 9x7 Light',),
    'nFUSE® 6x4 P Scene Light': ('nFUSE 6x4 P Light',),
    'nFUSE® 6x4 P Light': ('nFUSE 6x4 P Light',),
    'nFUSE® 7x3 P Scene Light': ('nFUSE 7x3 P Light',),
    'nFUSE® 7x3 P Light': ('nFUSE 7x3 P Light',),
    'nFUSE® 9x7 P Scene Light': ('nFUSE 9x7 P Light',),
    'nFUSE® 9x7 P Warning': ('nFUSE 9x7 P Light',),
    'Intersector Surface Mount': ('Intersector Light',),
    'Intersector LED Under Mirror Light': ('Intersector Light',),
    'nFORCE® Deck/Grille': ('nFORCE Single Light', 'nFORCE Dual Light'),
    'nFORCE® LED Windshield Lights': ('nFORCE Single Light', 'nFORCE Dual Light'),
    'nFORCE® Surface Mount': ('nFORCE Single Light',),
    'nFORCE® LED Recess Mount Light': ('nFORCE Single Light',),
    'mpower® HD Light': ('mpower HD Light',),
    'mpower® HP 2x1': ('mpower HP 2x1',),
    'mpower® HP 6x1': ('mpower® HP 6x1',),
    'Golight® SL': ('Golight SL',),
    'bluePRINT® Central Controller': ('bluePRINT Central Controller',),
    'mpower® Arrow System': ('mpower Arrow System',),
    'mpower® Arrow Kit (EMPAK)': ('mpower Arrow System',),
}

# Reviewed reuse decisions for existing SoundOff products.  Reusing these IDs
# prevents duplicate families and preserves their already-linked QBO SKUs.
PRIMARY_FAMILY_EXISTING_TARGETS: dict[str, str] = {
    'mpower 3" Fascia Light': "soundoff_mpower_3_fascia",
    'mpower 4" Fascia Light': "soundoff_mpower_4_fascia",
    "nFORCE Single Light": "soundoff_nforce_deck_grille",
    "Intersector Light": "soundoff_intersector",
    "Universal UnderCover LED Insert": "soundoff_eluc_undercover_insert",
}

# Exact family labels that already have concrete configured products in the
# current Builder.  These supplement (rather than replace) primary-family
# targets produced by the import plan.
EXISTING_PARENT_TARGETS: dict[str, tuple[str, ...]] = {
    'mpower® Exterior Full Size Lightbar': ("soundoff_mpower_per_config",),
    'nROADS® Mini and MidSize Lightbar': ("soundoff_enrmb",),
    'nFORCE® Interior LED Lightbar': (
        "soundoff_enfwb0005k", "soundoff_enfwb003mp", "soundoff_enfwbfs",
    ),
    'nFORCE® Interior LED Traffic Controller': ("soundoff_enftc001bw",),
    'nFORCE® Exterior LED Traffic Controller': ("soundoff_enftcdxs1208",),
    'Headlight & Taillight Flashers': ("soundoff_ethfss_sp_iso", "soundoff_etfbssn_p"),
}

_PROTECTED_COMMA_FAMILIES = {
    'obSERVE+ Dome Light, 3"': 'obSERVE+ Dome Light§ 3"',
    'obSERVE Dome Light, 6"': 'obSERVE Dome Light§ 6"',
}

_SUPER_DUTY_TEXT = re.compile(r"\bSUPER[ -]?DUTY\b", re.IGNORECASE)
_SUPER_DUTY_VEHICLE_TAGS = ("FORD F-250", "FORD F-350", "FORD F-450", "FORD F-550")


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").upper()
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _norm(value).lower()).strip("_")
    return slug or "item"


def _stable_product_id(prefix: str, label: str, occupied: set[str]) -> str:
    base = f"soundoff_{prefix}{_slug(label)}"
    if len(base) > 88:
        digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:10]
        base = f"{base[:77].rstrip('_')}_{digest}"
    candidate = base
    if candidate not in occupied:
        occupied.add(candidate)
        return candidate
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:10]
    candidate = f"{base[:77].rstrip('_')}_{digest}"
    if candidate in occupied:
        raise ValueError(f"deterministic product-id collision for {label!r}")
    occupied.add(candidate)
    return candidate


def split_parent_families(value: str) -> tuple[str, ...]:
    work = str(value or "").strip()
    for original, protected in _PROTECTED_COMMA_FAMILIES.items():
        work = work.replace(original, protected)
    atoms = [part.strip().replace("§", ",") for part in work.split(", ") if part.strip()]
    if not atoms:
        return ()
    # Used With order varies in the source catalog.  Relationship identity does not.
    unique = {atom: None for atom in atoms}
    return tuple(sorted(unique, key=lambda atom: _norm(atom)))


def _group_key(record: dict) -> tuple:
    if record.get("accessory_category"):
        return (
            "accessory",
            record.get("catalog_group") or "Catalog component",
            record["accessory_category"],
            split_parent_families(record.get("associated_parent_family") or ""),
        )
    return ("primary", record["product_family"])


def _group_label(key: tuple) -> str:
    if key[0] == "primary":
        return key[1]
    _, catalog_group, accessory_category, parents = key
    parent_text = ", ".join(parents)
    suffix = catalog_group
    if accessory_category == "other":
        suffix = f"{suffix} (service component)"
    return f"{parent_text} — {suffix}"


def _load_inputs() -> tuple[dict, dict, list[dict]]:
    db = json.loads(PARTS_DB.read_text("utf-8"))
    cache_doc = json.loads(CACHE.read_text("utf-8"))
    curation_doc = json.loads(CURATION.read_text("utf-8"))
    cache = {str(item.get("qb_item_id") or ""): item for item in cache_doc.get("items") or []}
    records = list(curation_doc.get("records") or [])
    if len(records) != 3843:
        raise ValueError(f"expected 3,843 researched records, found {len(records):,}")
    return db, cache, records


def build_plan(db: dict, cache: dict, records: list[dict]) -> dict:
    products = db.get("products") or {}
    occupied = set(products)
    curation_open_records = [record for record in records if record.get("builder_status") == "Inbox open"]
    if len(curation_open_records) != 3813:
        raise ValueError(f"expected 3,813 curated open records, found {len(curation_open_records):,}")

    linked_ids = {
        str(part.get("qb_item_id") or "")
        for product in products.values()
        for part in (product.get("part_numbers") or [])
        if str(part.get("qb_item_id") or "")
    }
    curated_qb_ids = [str(record.get("qb_item_id") or "") for record in curation_open_records]
    if len(set(curated_qb_ids)) != len(curated_qb_ids):
        raise ValueError("curation contains duplicate open QuickBooks item IDs")
    applied_records = [
        record for record in curation_open_records
        if str(record.get("qb_item_id") or "") in linked_ids
    ]
    open_records = [
        record for record in curation_open_records
        if str(record.get("qb_item_id") or "") not in linked_ids
    ]
    missing_cache = [qb_id for qb_id in curated_qb_ids if qb_id not in cache]
    if missing_cache:
        raise ValueError(f"open items missing from current QBO cache: {missing_cache[:10]}")
    identity_mismatches = []
    inactive_items = []
    for record in curation_open_records:
        qb_id = str(record.get("qb_item_id") or "")
        item = cache[qb_id]
        actual_sku = str(item.get("sku") or item.get("name") or "").strip()
        expected_sku = str(record.get("sku") or "").strip()
        if actual_sku.casefold() != expected_sku.casefold():
            identity_mismatches.append((qb_id, expected_sku, actual_sku))
        if item.get("active") is False:
            inactive_items.append((qb_id, expected_sku))
    if identity_mismatches:
        raise ValueError(f"QBO cache identity mismatch: {identity_mismatches[:10]}")
    if inactive_items:
        raise ValueError(f"curation contains inactive QBO items: {inactive_items[:10]}")

    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for record in open_records:
        grouped[_group_key(record)].append(record)

    primary_target_by_norm: dict[str, str] = {}
    product_id_by_group: dict[tuple, str] = {}
    reused_products: set[str] = set()
    for key in sorted(grouped, key=lambda item: repr(item)):
        label = _group_label(key)
        target = ""
        if key[0] == "primary":
            target = PRIMARY_FAMILY_EXISTING_TARGETS.get(key[1], "")
            if target:
                if target not in products:
                    raise ValueError(f"reviewed existing target is missing: {target}")
                if products[target].get("manufacturer_id") != MANUFACTURER_ID:
                    raise ValueError(f"reviewed existing target is not SoundOff: {target}")
                reused_products.add(target)
        if not target:
            target = _stable_product_id("", label, occupied)
        product_id_by_group[key] = target
        if key[0] == "primary":
            family_norm = _norm(key[1])
            if family_norm in primary_target_by_norm and primary_target_by_norm[family_norm] != target:
                raise ValueError(f"primary family mapped twice: {key[1]}")
            primary_target_by_norm[family_norm] = target

    parent_atoms = sorted({
        atom
        for key in grouped
        if key[0] == "accessory"
        for atom in key[3]
    }, key=_norm)
    parent_usage: dict[str, list[str]] = defaultdict(list)
    for record in open_records:
        if not record.get("accessory_category"):
            continue
        for atom in split_parent_families(record.get("associated_parent_family") or ""):
            parent_usage[_norm(atom)].append(record["sku"])
    parent_targets: dict[str, list[str]] = {}
    parent_resolution: dict[str, dict] = {}
    virtual_parents: dict[str, dict] = {}

    alias_by_norm = {_norm(key): value for key, value in PARENT_TO_PRIMARY_FAMILIES.items()}
    existing_by_norm = {_norm(key): value for key, value in EXISTING_PARENT_TARGETS.items()}
    for atom in parent_atoms:
        targets: list[str] = []
        evidence: list[str] = []
        atom_norm = _norm(atom)

        if atom_norm in primary_target_by_norm:
            targets.append(primary_target_by_norm[atom_norm])
            evidence.append("exact reviewed primary-family match")

        for primary_family in alias_by_norm.get(atom_norm, ()):
            target = primary_target_by_norm.get(_norm(primary_family))
            if not target:
                raise ValueError(
                    f"explicit alias {atom!r} references absent primary family {primary_family!r}"
                )
            targets.append(target)
            evidence.append(f"explicit catalog alias → {primary_family}")

        for target in existing_by_norm.get(atom_norm, ()):
            if target not in products:
                raise ValueError(f"existing parent target for {atom!r} is missing: {target}")
            targets.append(target)
            evidence.append(f"reviewed existing Builder product → {target}")

        targets = list(dict.fromkeys(targets))
        if not targets:
            # The official Used With label is authoritative, but the 2026 price
            # guide has no orderable complete-product row for many configured
            # families.  Preserve an exact, SKU-less anchor instead of guessing.
            target = _stable_product_id("family_", atom, occupied)
            targets = [target]
            virtual_parents[target] = {
                "manufacturer_id": MANUFACTURER_ID,
                "model": atom,
                "description": (
                    "SoundOff catalog family anchor created from the official 2026 Used With column; "
                    "not an orderable SKU."
                ),
                "fits_part_types": [],
                "tag_ids": [],
                "part_numbers": [],
                "reviewed": True,
            }
            evidence.append("exact official Used With family anchor; no orderable parent SKU in import")

        parent_targets[atom_norm] = targets
        referencing_skus = sorted(set(parent_usage[atom_norm]))
        parent_resolution[atom] = {
            "product_ids": targets,
            "evidence": evidence,
            "referencing_sku_count": len(referencing_skus),
            "referencing_skus": referencing_skus,
        }

    planned_products = []
    for key, rows in sorted(grouped.items(), key=lambda item: repr(item[0])):
        product_id = product_id_by_group[key]
        accessory_categories = {row.get("accessory_category") or "" for row in rows}
        roles = {row.get("role") or "" for row in rows}
        if len(accessory_categories) != 1 or len(roles) != 1:
            raise ValueError(f"mixed product group {key!r}: {accessory_categories=}, {roles=}")
        parent_ids: list[str] = []
        if key[0] == "accessory":
            for atom in key[3]:
                atom_targets = parent_targets.get(_norm(atom))
                if not atom_targets:
                    raise ValueError(f"unresolved parent atom: {atom}")
                parent_ids.extend(atom_targets)
        parent_ids = list(dict.fromkeys(parent_ids))
        fits = sorted({row.get("part_type_id") or "" for row in rows} - {""})
        tags = sorted({row.get("tag_id") or "" for row in rows} - {""})
        planned_products.append({
            "product_id": product_id,
            "group_key": list(key),
            "model": _group_label(key),
            "reuses_existing_product": product_id in products,
            "fits_part_types": fits,
            "tag_ids": tags,
            "accessory_category": next(iter(accessory_categories)),
            "accessory_of_products": parent_ids,
            "role": next(iter(roles)),
            "skus": [row["sku"] for row in sorted(rows, key=lambda row: row["sku"])],
            "qb_item_ids": [str(row["qb_item_id"]) for row in sorted(rows, key=lambda row: row["sku"])],
        })

    all_future_products = set(products) | {p["product_id"] for p in planned_products} | set(virtual_parents)
    dangling = sorted({
        parent_id
        for planned in planned_products
        for parent_id in planned["accessory_of_products"]
        if parent_id not in all_future_products
    })
    if dangling:
        raise ValueError(f"dangling resolved parent IDs: {dangling[:10]}")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_edit_revision": (db.get("metadata") or {}).get("edit_revision", ""),
        "summary": {
            "catalog_records": len(records),
            "curated_open_records": len(curation_open_records),
            "already_applied_records": len(applied_records),
            "remaining_open_records": len(open_records),
            "planned_product_groups": len(planned_products),
            "reused_existing_products": len(reused_products),
            "official_parent_families": len(parent_atoms),
            "exact_family_anchors_required": len(virtual_parents),
            "unresolved_parent_families": 0,
            "dangling_parent_ids": 0,
        },
        "parent_resolution": parent_resolution,
        "virtual_parent_products": virtual_parents,
        "planned_products": planned_products,
    }


def _part_number_from_record(record: dict, item: dict, now_iso: str) -> dict:
    part_number = str(item.get("sku") or item.get("name") or record.get("sku") or "").strip()
    if not part_number:
        raise ValueError(f"QBO item {record['qb_item_id']} has no usable SKU/name")
    vehicle_tags = [
        tag for tag in str(record.get("vehicle_tags") or "").split(", ") if tag
    ]
    description_text = " ".join((
        str(record.get("description") or ""),
        str(item.get("description") or ""),
    ))
    if _SUPER_DUTY_TEXT.search(description_text):
        vehicle_tags.extend(_SUPER_DUTY_VEHICLE_TAGS)
    vehicle_tags = list(dict.fromkeys(vehicle_tags))
    pn = {
        "part_number": part_number,
        "friendly_name": str(item.get("description") or record.get("description") or "").strip(),
        "qb_item_id": str(item.get("qb_item_id") or "").strip(),
        "qb_sku": str(item.get("sku") or "").strip(),
        "qb_sales_description": str(item.get("description") or "").strip(),
        "qb_unit_price": item.get("unit_price"),
        "qb_last_synced": now_iso,
        "vehicle_tags": vehicle_tags,
        "options": {},
    }
    for source, target in (
        ("color_1", "color"),
        ("color_2", "secondary_color"),
        ("color_3", "tertiary_color"),
        ("lens_type", "lens_type"),
    ):
        if record.get(source):
            pn[target] = record[source]
    return pn


def apply_pilot(db: dict, cache: dict, records: list[dict], plan: dict, sku: str) -> tuple[dict, dict]:
    matches = [
        record for record in records
        if record.get("builder_status") == "Inbox open" and record.get("sku", "").casefold() == sku.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"pilot SKU must match exactly one open item; found {len(matches)}")
    record = matches[0]
    planned = next((p for p in plan["planned_products"] if record["sku"] in p["skus"]), None)
    if planned is None:
        raise ValueError(f"pilot SKU is already applied or absent from the current dry-run plan: {record['sku']}")
    product_id = planned["product_id"]
    qb_item_id = str(record["qb_item_id"])
    item = cache[qb_item_id]

    work = deepcopy(db)
    products = work.setdefault("products", {})
    if product_id not in products:
        products[product_id] = {
            "manufacturer_id": MANUFACTURER_ID,
            "model": planned["model"],
            "description": "",
            "fits_part_types": list(planned["fits_part_types"]),
            "tag_ids": list(planned["tag_ids"]),
            "part_numbers": [],
            "reviewed": True,
        }
        if planned["accessory_category"]:
            products[product_id]["accessory_category"] = planned["accessory_category"]
            products[product_id]["accessory_of_products"] = list(planned["accessory_of_products"])

    product = products[product_id]
    if product.get("manufacturer_id") != MANUFACTURER_ID:
        raise ValueError(f"pilot target is not a SoundOff product: {product_id}")
    existing_qb_ids = {
        str(part.get("qb_item_id") or "")
        for existing in products.values()
        for part in (existing.get("part_numbers") or [])
    }
    if qb_item_id in existing_qb_ids:
        raise ValueError(f"pilot QBO item is already linked: {qb_item_id}")
    existing_skus = {
        str(part.get("part_number") or "").strip().casefold()
        for existing in products.values()
        for part in (existing.get("part_numbers") or [])
    }
    if record["sku"].casefold() in existing_skus:
        raise ValueError(f"pilot SKU already exists in parts_db: {record['sku']}")

    now_iso = datetime.now(timezone.utc).isoformat()
    product.setdefault("part_numbers", []).append(_part_number_from_record(record, item, now_iso))
    receipt = {
        "sku": record["sku"],
        "qb_item_id": qb_item_id,
        "product_id": product_id,
        "model": product["model"],
        "part_type_ids": product.get("fits_part_types") or [],
        "accessory_category": product.get("accessory_category") or "",
        "accessory_of_products": product.get("accessory_of_products") or [],
        "source_edit_revision": plan["source_edit_revision"],
    }
    return work, receipt


def apply_all(db: dict, cache: dict, records: list[dict], plan: dict) -> tuple[dict, dict]:
    """Apply the complete current dry-run plan to a copy of ``parts_db``.

    This is deliberately additive.  It creates exact family anchors and
    researched products, appends each still-open QBO item exactly once, and
    only extends the five explicitly reviewed existing SoundOff products.
    """
    expected_remaining = plan["summary"]["remaining_open_records"]
    if expected_remaining <= 0:
        raise ValueError("no researched SoundOff items remain to apply")

    work = deepcopy(db)
    products = work.setdefault("products", {})
    before_product_ids = set(products)
    touched_existing: set[str] = set()
    created_products: set[str] = set()

    for product_id, spec in plan["virtual_parent_products"].items():
        if product_id in products:
            raise ValueError(f"family anchor unexpectedly already exists: {product_id}")
        products[product_id] = deepcopy(spec)
        created_products.add(product_id)

    records_by_qb_id = {
        str(record.get("qb_item_id") or ""): record
        for record in records
        if record.get("builder_status") == "Inbox open"
    }
    existing_qb_ids = {
        str(part.get("qb_item_id") or "")
        for product in products.values()
        for part in (product.get("part_numbers") or [])
        if str(part.get("qb_item_id") or "")
    }
    existing_skus = {
        str(part.get("part_number") or "").strip().casefold()
        for product in products.values()
        for part in (product.get("part_numbers") or [])
        if str(part.get("part_number") or "").strip()
    }

    now_iso = datetime.now(timezone.utc).isoformat()
    added_qb_ids: list[str] = []
    added_skus: list[str] = []
    for planned in plan["planned_products"]:
        product_id = planned["product_id"]
        product = products.get(product_id)
        if product is None:
            product = {
                "manufacturer_id": MANUFACTURER_ID,
                "model": planned["model"],
                "description": "",
                "fits_part_types": list(planned["fits_part_types"]),
                "tag_ids": list(planned["tag_ids"]),
                "part_numbers": [],
                "reviewed": True,
            }
            products[product_id] = product
            created_products.add(product_id)
        else:
            if not planned["reuses_existing_product"]:
                raise ValueError(f"unreviewed product-id collision: {product_id}")
            if product.get("manufacturer_id") != MANUFACTURER_ID:
                raise ValueError(f"reviewed reuse target is not SoundOff: {product_id}")
            touched_existing.add(product_id)
            product["fits_part_types"] = list(dict.fromkeys([
                *(product.get("fits_part_types") or []),
                *planned["fits_part_types"],
            ]))
            product["tag_ids"] = list(dict.fromkeys([
                *(product.get("tag_ids") or []),
                *planned["tag_ids"],
            ]))
            product["reviewed"] = True

        if planned["accessory_category"]:
            product["accessory_category"] = planned["accessory_category"]
            product["accessory_of_products"] = list(planned["accessory_of_products"])
        elif planned["accessory_of_products"]:
            raise ValueError(f"parents supplied for a non-accessory product: {product_id}")

        for qb_item_id in planned["qb_item_ids"]:
            record = records_by_qb_id.get(qb_item_id)
            item = cache.get(qb_item_id)
            if record is None or item is None:
                raise ValueError(f"missing researched/cache record for QBO item {qb_item_id}")
            if qb_item_id in existing_qb_ids:
                raise ValueError(f"QBO item became linked during apply planning: {qb_item_id}")
            part = _part_number_from_record(record, item, now_iso)
            sku_key = str(part["part_number"]).strip().casefold()
            if sku_key in existing_skus:
                raise ValueError(f"SKU became duplicated during apply planning: {part['part_number']}")
            product.setdefault("part_numbers", []).append(part)
            existing_qb_ids.add(qb_item_id)
            existing_skus.add(sku_key)
            added_qb_ids.append(qb_item_id)
            added_skus.append(record["sku"])

    if len(added_qb_ids) != expected_remaining:
        raise ValueError(
            f"planned {expected_remaining:,} remaining items but constructed {len(added_qb_ids):,}"
        )
    if len(set(added_qb_ids)) != len(added_qb_ids):
        raise ValueError("full apply constructed duplicate QBO item IDs")
    if len(set(sku.casefold() for sku in added_skus)) != len(added_skus):
        raise ValueError("full apply constructed duplicate SKUs")

    for product_id in created_products | touched_existing:
        product = products[product_id]
        for parent_id in product.get("accessory_of_products") or []:
            if parent_id not in products:
                raise ValueError(f"{product_id} has dangling parent {parent_id}")

    receipt = {
        "source_edit_revision": plan["source_edit_revision"],
        "added_qbo_items": len(added_qb_ids),
        "created_products": len(created_products),
        "created_family_anchors": len(plan["virtual_parent_products"]),
        "touched_existing_products": sorted(touched_existing),
        "before_product_count": len(before_product_ids),
        "expected_after_product_count": len(products),
        "added_qb_item_ids_sha256": hashlib.sha256(
            "\n".join(sorted(added_qb_ids)).encode("utf-8")
        ).hexdigest(),
        "added_skus_sha256": hashlib.sha256(
            "\n".join(sorted(added_skus, key=str.casefold)).encode("utf-8")
        ).hexdigest(),
    }
    return work, receipt


def verify_full_apply(before: dict, saved: dict, records: list[dict], plan: dict, receipt: dict) -> None:
    before_products = before.get("products") or {}
    saved_products = saved.get("products") or {}
    if not set(before_products).issubset(saved_products):
        raise ValueError("post-save verification failed: a pre-existing product was deleted")
    if len(saved_products) != receipt["expected_after_product_count"]:
        raise ValueError("post-save verification failed: product count differs from the plan")

    allowed_existing_changes = set(receipt["touched_existing_products"])
    for product_id, product in before_products.items():
        if product_id not in allowed_existing_changes and saved_products[product_id] != product:
            raise ValueError(
                f"post-save verification failed: unrelated product changed: {product_id}"
            )

    curated_qb_ids = {
        str(record.get("qb_item_id") or "")
        for record in records
        if record.get("builder_status") == "Inbox open"
    }
    occurrences: dict[str, list[str]] = defaultdict(list)
    for product_id, product in saved_products.items():
        for part in product.get("part_numbers") or []:
            qb_item_id = str(part.get("qb_item_id") or "")
            if qb_item_id in curated_qb_ids:
                occurrences[qb_item_id].append(product_id)
    missing = sorted(curated_qb_ids - set(occurrences))
    duplicated = sorted(qb_id for qb_id, product_ids in occurrences.items() if len(product_ids) != 1)
    if missing or duplicated:
        raise ValueError(
            f"post-save verification failed: {len(missing)} missing and {len(duplicated)} duplicated QBO links"
        )

    for planned in plan["planned_products"]:
        product = saved_products.get(planned["product_id"])
        if product is None:
            raise ValueError(f"post-save verification failed: missing product {planned['product_id']}")
        if planned["accessory_category"]:
            if product.get("accessory_category") != planned["accessory_category"]:
                raise ValueError(f"post-save verification failed: category mismatch on {planned['product_id']}")
            if list(product.get("accessory_of_products") or []) != planned["accessory_of_products"]:
                raise ValueError(f"post-save verification failed: parent mismatch on {planned['product_id']}")

    for product_id, product in saved_products.items():
        for parent_id in product.get("accessory_of_products") or []:
            if parent_id not in saved_products:
                raise ValueError(f"post-save verification failed: {product_id} has dangling parent {parent_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", help="apply or preview exactly one open SKU")
    parser.add_argument("--apply-all", action="store_true", help="apply every item in the audited plan")
    parser.add_argument("--confirm", default="", help="exact safety confirmation for --apply-all")
    parser.add_argument("--write", action="store_true", help="persist the requested pilot/full apply")
    args = parser.parse_args()
    if args.pilot and args.apply_all:
        parser.error("choose --pilot or --apply-all, not both")
    if args.write and not (args.pilot or args.apply_all):
        parser.error("--write requires --pilot or --apply-all")
    if args.apply_all and args.confirm != FULL_APPLY_CONFIRMATION:
        parser.error(f"--apply-all requires --confirm {FULL_APPLY_CONFIRMATION!r}")

    db, cache, records = _load_inputs()
    plan = build_plan(db, cache, records)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps(plan["summary"], indent=2))
    print(f"audit: {AUDIT_PATH}")
    if not args.pilot and not args.apply_all:
        print("dry run only; no Builder/QBO data changed")
        return 0

    if args.apply_all:
        work, receipt = apply_all(db, cache, records, plan)
    else:
        work, receipt = apply_pilot(db, cache, records, plan, args.pilot)
    if not args.write:
        print(json.dumps(receipt, indent=2))
        print("apply preview only; re-run with --write to persist")
        return 0

    current = json.loads(PARTS_DB.read_text("utf-8"))
    current_revision = (current.get("metadata") or {}).get("edit_revision", "")
    if current_revision != plan["source_edit_revision"]:
        raise ValueError("parts_db changed after planning; refusing stale write")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = f"pilot-{receipt['sku']}" if args.pilot else "full-apply"
    backup = OUTPUT_DIR / f"parts_db.before-soundoff-{label}-{stamp}.json"
    shutil.copy2(PARTS_DB, backup)

    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.config.schemas import validate_config_payload
    from dtm_buildsheet.paths import AppPaths

    validate_config_payload("parts_db.json", work)
    result = save_config_file("parts_db.json", work, AppPaths())
    if not result.get("ok"):
        raise ValueError(result.get("error") or "save failed")
    saved = json.loads(PARTS_DB.read_text("utf-8"))
    if args.apply_all:
        verify_full_apply(db, saved, records, plan, receipt)
    else:
        product = (saved.get("products") or {}).get(receipt["product_id"])
        if not product:
            raise ValueError("post-save verification failed: pilot product missing")
        linked = [
            part for part in product.get("part_numbers") or []
            if str(part.get("qb_item_id") or "") == receipt["qb_item_id"]
        ]
        if len(linked) != 1:
            raise ValueError("post-save verification failed: pilot QBO link count is not one")
        if list(product.get("accessory_of_products") or []) != receipt["accessory_of_products"]:
            raise ValueError("post-save verification failed: accessory parents changed")

    receipt.update({
        "saved_edit_revision": (saved.get("metadata") or {}).get("edit_revision", ""),
        "backup_path": str(backup),
        "save_result": result,
        "verified": True,
    })
    receipt_name = f"soundoff_pilot_{receipt['sku']}_receipt.json" if args.pilot else "soundoff_full_apply_receipt.json"
    receipt_path = OUTPUT_DIR / receipt_name
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps(receipt, indent=2))
    print(f"receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
