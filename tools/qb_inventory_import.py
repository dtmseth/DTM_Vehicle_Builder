#!/usr/bin/env python3
"""Incrementally fold the QuickBooks inventory export into parts_db.json.

This is a reviewed, multi-pass importer (run it dry, eyeball the report, then
``--write``). It is deliberately conservative: every guess is encoded in an
editable table at the top of the file so a human can correct it before anything
is written.

The QB export (`ProductsServicesList_*.csv`) is non-standard:
  - ``Product/Service Name`` holds the **part number** (the SKU column is empty).
  - ``Category`` holds the **manufacturer**.
  - There is no price/description column — price comes from the API sync later.

Pass 1 (this file, today): MANUFACTURERS.
  Reconcile the export's ``Category`` values against parts_db manufacturers,
  add the confirmed-new ones, and emit a category→manufacturer_id map that the
  later product/link passes will consume.

Usage:
  python tools/qb_inventory_import.py PATH/TO/export.csv            # dry run
  python tools/qb_inventory_import.py PATH/TO/export.csv --write    # apply
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
CATEGORY_MAP_OUT = REPO / "tools" / "qb_category_to_manufacturer.json"

# ── Confirmed manufacturer reconciliation (Seth, 2026-06-16) ──────────────────
#
# QB Category (verbatim, upper-cased on read) → existing app manufacturer LABEL.
# Exact-name matches (WHELEN→Whelen, …) are resolved automatically and don't
# need an entry here. Only spelling aliases + the DTM decision live here.
ALIAS_TO_EXISTING: dict[str, str] = {
    "SOUNDOFF SIGNAL": "Soundoff",
    "NIGHTRIDE": "Night Ride",
    "ACE K9": "Ace K-9",
    "ARCTICSTART": "Arcti Start",
    "WEATHERTECH": "Weather Tech",
    "MAG MIC": "Magnetic Mic",
    "ROCKLAND": "Rockland Cabinets",
    "DTM": "5-0 Fab (Dtm)",        # confirmed: DTM in-house == 5-0 Fab
}

# QB Category → desired NEW manufacturer label (nice casing). These don't exist
# in parts_db yet and will be created on --write.
NEW_LABELS: dict[str, str] = {
    "JB LUND DOCK": "JB Lund Dock",
    "PAC TOOL": "Pac Tool",
    "UNITY": "Unity",
    "FEDERAL SIGNAL": "Federal Signal",
    "RAM": "RAM",
    "GO RHINO": "Go Rhino",
    "INTERMOTIVE": "InterMotive",
    "FIRENINJA SAFETY EQUIPMENT": "FireNinja Safety Equipment",
    "AIR ONE EQUIPMENT": "Air One Equipment",
    "SNOWEX": "SnowEx",
    "NOPTIC": "Noptic",
    "LIND": "Lind",
    "LAIRD": "Laird",
}

# Categories with no usable manufacturer — left unassigned for now (Seth).
SKIP = {"", "MISC"}


def slug(label: str) -> str:
    """Manufacturer id convention: lower, non-alnum runs → single underscore."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def read_categories(csv_path: Path) -> Counter:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return Counter((r.get("Category") or "").strip().upper() for r in rows)


def reconcile(categories: Counter, parts_db: dict):
    """Bucket each QB category. Returns (matched, to_create, skipped, unresolved).

    matched/to_create/unresolved are lists of (category, count, target_label).
    """
    by_label_upper = {
        spec.get("label", "").upper(): mid
        for mid, spec in parts_db.get("manufacturers", {}).items()
    }

    matched, to_create, skipped, unresolved = [], [], [], []
    for cat, n in categories.most_common():
        if cat in SKIP:
            skipped.append((cat, n, ""))
        elif cat in ALIAS_TO_EXISTING:
            label = ALIAS_TO_EXISTING[cat]
            mid = by_label_upper.get(label.upper())
            (matched if mid else unresolved).append((cat, n, label))
        elif cat in by_label_upper:
            matched.append((cat, n, parts_db["manufacturers"][by_label_upper[cat]]["label"]))
        elif cat in NEW_LABELS:
            to_create.append((cat, n, NEW_LABELS[cat]))
        else:
            unresolved.append((cat, n, ""))
    return matched, to_create, skipped, unresolved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path, help="QuickBooks ProductsServicesList CSV")
    ap.add_argument("--write", action="store_true", help="apply changes to parts_db.json")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 2

    parts_db = json.loads(PARTS_DB.read_text("utf-8"))
    categories = read_categories(args.csv)
    matched, to_create, skipped, unresolved = reconcile(categories, parts_db)

    items = lambda bucket: sum(n for _, n, _ in bucket)  # noqa: E731

    print(f"QB categories: {len(categories)} distinct\n")
    print(f"✅ matched existing ({len(matched)} cats, {items(matched)} items)")
    for cat, n, label in matched:
        arrow = "" if cat == label.upper() else f"  →  {label}"
        print(f"     {n:4d}  {cat}{arrow}")
    print(f"\n🆕 new to create ({len(to_create)} cats, {items(to_create)} items)")
    for cat, n, label in to_create:
        print(f"     {n:4d}  {cat}  →  {label}  (id: {slug(label)})")
    print(f"\n⏭  skipped / unassigned ({len(skipped)} cats, {items(skipped)} items)")
    for cat, n, _ in skipped:
        print(f"     {n:4d}  {cat or '(blank)'}")
    if unresolved:
        print(f"\n⚠  UNRESOLVED — fix the tables above ({len(unresolved)} cats)")
        for cat, n, _ in unresolved:
            print(f"     {n:4d}  {cat}")
        return 1

    # Build the category → manufacturer_id map (matched + new; skips excluded).
    by_label_upper = {
        spec.get("label", "").upper(): mid
        for mid, spec in parts_db.get("manufacturers", {}).items()
    }
    cat_to_mid: dict[str, str] = {}
    for cat, _, label in matched:
        cat_to_mid[cat] = by_label_upper[label.upper()]
    for cat, _, label in to_create:
        cat_to_mid[cat] = slug(label)

    if not args.write:
        print("\n(dry run — re-run with --write to add the new manufacturers "
              "and write the category map)")
        return 0

    # Apply: add new manufacturers, write category map.
    for _, _, label in to_create:
        mid = slug(label)
        parts_db["manufacturers"][mid] = {"label": label}
    PARTS_DB.write_text(json.dumps(parts_db, indent=2) + "\n", "utf-8")
    CATEGORY_MAP_OUT.write_text(
        json.dumps(dict(sorted(cat_to_mid.items())), indent=2) + "\n", "utf-8"
    )
    print(f"\n✍  wrote {len(to_create)} new manufacturers to {PARTS_DB.relative_to(REPO)}")
    print(f"✍  wrote category→manufacturer map ({len(cat_to_mid)} entries) "
          f"to {CATEGORY_MAP_OUT.relative_to(REPO)}")
    print("\nNote (dev): this is a direct file write. For the bundled/cloud app the "
          "same change must go through save_config_file to mirror to SharePoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
