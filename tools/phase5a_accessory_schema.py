#!/usr/bin/env python3
"""Phase 5a: accessory schema scaffolding for parts_db.json.

Idempotent. Adds the accessory_categories vocabulary, tags every accessory
part_type with its accessory_category, and creates generic accessory part_types
for the categories that have no part_type home yet (lighthead/cable/flange/
shroud/flasher_power). Pure schema — links no SKUs and creates no products
(that's 5b). Writes through save_config_file so the change validates + mirrors.

Usage:
  python tools/phase5a_accessory_schema.py            # dry-run
  python tools/phase5a_accessory_schema.py --write
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"

# ── The 7 accessory categories (each becomes one dropdown in the picker) ──
ACCESSORY_CATEGORIES = {
    "lighthead":     {"label": "Lighthead"},
    "bracket_mount": {"label": "Bracket / Mount"},
    "cable":         {"label": "Cable"},
    "flange":        {"label": "Flange"},
    "shroud":        {"label": "Shroud"},
    "flasher_power": {"label": "Flasher / Power"},
    "other":         {"label": "Other"},
}

# ── accessory_category for each existing accessory part_type ──
EXISTING_TYPE_CATEGORY = {
    "wire_covers":                    "other",
    "fw_bracket":                     "bracket_mount",
    "front_side_bracket":             "bracket_mount",
    "siren_speaker_bracket":          "bracket_mount",
    "pa_mic_clip":                    "bracket_mount",
    "mirror_warning_bracket":         "bracket_mount",
    "side_warning_bracket":           "bracket_mount",
    "rear_warning_bracket":           "bracket_mount",
    "lower_liftgate_warning_bracket": "bracket_mount",
    "front_radar_antenna_mount":      "bracket_mount",
    "rear_radar_antenna_mount":       "bracket_mount",
    "printer_mount":                  "bracket_mount",
    "printer_power":                  "flasher_power",
    "printer_usb":                    "cable",
    "front_partition_transfer_kit":   "other",
    "gun_lock_bracket":               "bracket_mount",
    "arges_mount":                    "bracket_mount",
}

# ── Generic accessory part_types for categories with no part_type yet ──
# These hold product-level accessory products (e.g. the shared Inner Edge
# lighthead). type_id "lights" since the first wave of accessories are light
# parts; accessory_of is intentionally absent (parent is a product, not a type).
NEW_ACCESSORY_TYPES = {
    "lighthead":     {"label": "Lighthead",     "type_id": "lights", "accessory_category": "lighthead"},
    "cable":         {"label": "Cable",         "type_id": "lights", "accessory_category": "cable"},
    "flange":        {"label": "Flange",        "type_id": "lights", "accessory_category": "flange"},
    "shroud":        {"label": "Shroud",        "type_id": "lights", "accessory_category": "shroud"},
    "flasher_power": {"label": "Flasher / Power","type_id": "lights", "accessory_category": "flasher_power"},
}


def apply(db: dict) -> list[str]:
    actions: list[str] = []

    # 1. accessory_categories vocabulary
    if db.get("accessory_categories") != ACCESSORY_CATEGORIES:
        db["accessory_categories"] = ACCESSORY_CATEGORIES
        actions.append(f"+ accessory_categories ({len(ACCESSORY_CATEGORIES)} categories)")

    part_types = db.setdefault("part_types", {})

    # 2. tag existing accessory part_types
    for pt_id, cat in EXISTING_TYPE_CATEGORY.items():
        pt = part_types.get(pt_id)
        if pt is None:
            actions.append(f"! missing part_type {pt_id} (skipped)")
            continue
        if pt.get("accessory_category") != cat:
            pt["accessory_category"] = cat
            actions.append(f"~ {pt_id}: accessory_category → {cat}")

    # 3. create generic accessory part_types
    for pt_id, spec in NEW_ACCESSORY_TYPES.items():
        if pt_id in part_types:
            # already present — ensure the category tag is set
            if part_types[pt_id].get("accessory_category") != spec["accessory_category"]:
                part_types[pt_id]["accessory_category"] = spec["accessory_category"]
                actions.append(f"~ {pt_id}: accessory_category → {spec['accessory_category']}")
            continue
        part_types[pt_id] = {
            "label": spec["label"],
            "type_id": spec["type_id"],
            "tree_positions": [],
            "tag_ids": [],
            "accessory_category": spec["accessory_category"],
        }
        actions.append(f"+ new accessory part_type {pt_id}")

    return actions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    db = json.loads(PARTS_DB.read_text("utf-8"))
    actions = apply(db)

    print(f"phase 5a: {len(actions)} actions")
    for a in actions:
        print(f"  {a}")
    if not actions:
        print("  (nothing to do — already applied)")

    if not args.write:
        print("\n(dry run — re-run with --write to save through save_config_file)")
        return 0

    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.paths import AppPaths
    result = save_config_file("parts_db.json", db, AppPaths())
    if not result.get("ok"):
        print(f"save failed: {result.get('error')}", file=sys.stderr)
        return 1
    print("\n☁  parts_db.json saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
