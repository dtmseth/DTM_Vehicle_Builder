#!/usr/bin/env python3
"""Apply a reviewed per-manufacturer SKU→product mapping into parts_db.json.

Pass 2 apply step. Reads a mapping file (authored during the human-checked
curation, one per manufacturer) and:
  - creates any new products it declares (fits_part_types copied from a
    template sibling),
  - for each link, writes the QBO SKU as a ``part_numbers[]`` entry on its
    product, carrying the SKU's ``qb_item_id`` + ``qb_unit_price`` (read from
    the synced items cache) and its ``vehicle_tags``,
  - drops the descriptive placeholder part_number (the one equal to the product
    model) once a real SKU lands on that product.

Linkage is per part number (a product can hold many SKUs, each its own price) —
matching the catalog reality. Dry-run by default; ``--write`` saves through
save_config_file so the SharePoint mirror fires.

Usage:
  python tools/qb_apply_links.py tools/qb_links/arcti_start.json
  python tools/qb_apply_links.py tools/qb_links/arcti_start.json --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
CACHE = REPO / "workspace" / "quickbooks_items_cache.json"

_QB_FIELDS = ("qb_item_id", "qb_sku", "qb_unit_price", "qb_inactive", "vehicle_tags")


def load_cache_index() -> dict:
    """name (part number) → {qb_item_id, unit_price, sku} from the synced cache."""
    if not CACHE.exists():
        print(f"items cache not found ({CACHE}). Pull items in the app first.", file=sys.stderr)
        sys.exit(2)
    data = json.loads(CACHE.read_text("utf-8"))
    return {it.get("name", ""): it for it in data.get("items", [])}


def apply_mapping(parts_db: dict, mapping: dict, cache: dict) -> list[str]:
    """Mutate parts_db in place per the mapping. Returns a list of action lines.

    Raises ValueError on any unresolvable reference so nothing is half-applied.
    """
    products = parts_db.setdefault("products", {})
    actions: list[str] = []

    # 1. New products (copy fits_part_types from the template sibling).
    template_id = mapping.get("template_product")
    template = products.get(template_id, {}) if template_id else {}
    for np in mapping.get("new_products", []):
        pid = np["product_id"]
        if pid in products:
            continue
        products[pid] = {
            "manufacturer_id": mapping["manufacturer_id"],
            "model": np["model"],
            "fits_part_types": list(np.get("fits_part_types")
                                    or template.get("fits_part_types") or []),
            "tag_ids": [],
            "description": np.get("description", ""),
            "images": {},
            "part_numbers": [],
        }
        actions.append(f"+ new product {pid}  (model {np['model']!r})")

    # 2. Links → part_number entries.
    for link in mapping.get("links", []):
        sku = link["sku"]
        pid = link["product"]
        if pid not in products:
            raise ValueError(f"link references unknown product: {pid}")
        item = cache.get(sku)
        if item is None:
            raise ValueError(f"SKU not in items cache (pull items?): {sku!r}")

        spec = products[pid]
        pns = spec.setdefault("part_numbers", [])
        # Drop the descriptive placeholder once a real SKU is attached.
        model = str(spec.get("model", "")).strip().lower()
        pns[:] = [p for p in pns
                  if str(p.get("part_number", "")).strip().lower() != model
                  or str(p.get("qb_item_id", "")).strip()]

        entry = {
            "part_number": sku,
            "qb_item_id": str(item.get("qb_item_id", "")),
            "qb_sku": str(item.get("sku", "")),
            "qb_unit_price": item.get("unit_price"),
            "qb_inactive": False,
            "vehicle_tags": list(link.get("vehicle_tags") or ["any"]),
        }
        existing = next((p for p in pns if p.get("part_number") == sku), None)
        if existing:
            existing.update(entry)
            actions.append(f"~ {pid}: update {sku}  (${entry['qb_unit_price']})")
        else:
            pns.append(entry)
            actions.append(f"+ {pid}: link {sku}  (${entry['qb_unit_price']}, "
                           f"veh {entry['vehicle_tags']})")
    return actions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mapping", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if not args.mapping.exists():
        print(f"mapping not found: {args.mapping}", file=sys.stderr)
        return 2

    mapping = json.loads(args.mapping.read_text("utf-8"))
    parts_db = json.loads(PARTS_DB.read_text("utf-8"))
    cache = load_cache_index()

    try:
        actions = apply_mapping(parts_db, mapping, cache)
    except ValueError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1

    print(f"manufacturer: {mapping.get('manufacturer_id')}  ({len(actions)} actions)")
    for a in actions:
        print(f"  {a}")

    if not args.write:
        print("\n(dry run — re-run with --write to save through save_config_file)")
        return 0

    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.paths import AppPaths
    result = save_config_file("parts_db.json", parts_db, AppPaths())
    if not result.get("ok"):
        print(f"Cloud push failed: {result.get('error')}", file=sys.stderr)
        return 3
    tag = "queued for retry" if result.get("queued") else "direct-mirrored to SharePoint"
    print(f"\n☁  parts_db.json → {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
