"""Apply a reviewed curation plan to parts_db.json.

The QB import created one product per SKU; real products bundle variant SKUs
(lengths, colors). This helper applies a JSON plan of curation ops so a walk-
through section becomes one reviewed, idempotent write instead of manual grid
clicks.

Plan schema (all keys optional):
{
  "create_part_types": [
    {"part_type_id","label","type_id", ...optional: "category","accessory_category",
     "accessory_of","tag_ids","tree_positions","workbook_label_pattern",
     "sequence_scope","location_mode","location_options"}
  ],
  "delete_part_types": ["id", ...],          # refuses if any product still fits it
  "merge": [
    {"target_id","model","manufacturer_id","fits_part_types":[...],
     "sources":[product_id,...],             # SKUs pulled into target, in order
     ...optional: "tag_ids","accessory_category","accessory_of_products","reviewed"}
  ],
  "set_home":     [{"product_id","fits_part_types":[...], "add_tags":[...]}],
  "set_accessory":[{"product_id","accessory_category","accessory_of_products":[...]}]
}

Merge: target_id may be one of `sources` (reused, others deleted) or a new id.
All source part_numbers are concatenated onto the target; sources other than the
target are removed.

Dry-run by default; ``--write`` saves through save_config_file.

Usage:
  python tools/curate.py tools/plans/cables.json
  python tools/curate.py tools/plans/cables.json --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"

_PT_FIELDS = ("category", "accessory_category", "accessory_of", "location_mode",
              "location_options", "workbook_label_pattern", "sequence_scope")


def apply_plan(pdb: dict, plan: dict) -> list[str]:
    products = pdb.setdefault("products", {})
    part_types = pdb.setdefault("part_types", {})
    acts: list[str] = []

    # 1. Create part_types (idempotent).
    for spec in plan.get("create_part_types", []):
        ptid = spec["part_type_id"]
        if ptid in part_types:
            acts.append(f"= part_type {ptid} exists, skip")
            continue
        pt = {"label": spec["label"], "type_id": spec["type_id"],
              "tree_positions": list(spec.get("tree_positions") or []),
              "tag_ids": list(spec.get("tag_ids") or [])}
        for k in _PT_FIELDS:
            if spec.get(k) is not None:
                pt[k] = spec[k]
        part_types[ptid] = pt
        acts.append(f"+ part_type {ptid} ({spec['label']!r})")

    # 2. Merge products (do before delete_part_types so homes resolve).
    for m in plan.get("merge", []):
        srcs = list(m["sources"])
        missing = [s for s in srcs if s not in products]
        if missing:
            raise ValueError(f"merge sources not found: {missing}")
        skus: list[dict] = []
        for s in srcs:
            skus.extend(products[s].get("part_numbers") or [])
        tid = m["target_id"]
        base = products.get(tid, {}) if tid in products else {}
        target = {
            "manufacturer_id": m.get("manufacturer_id") or base.get("manufacturer_id", ""),
            "model": m.get("model") or base.get("model", ""),
            "fits_part_types": list(m.get("fits_part_types") or base.get("fits_part_types") or []),
            "tag_ids": list(m.get("tag_ids") if m.get("tag_ids") is not None else base.get("tag_ids") or []),
            "description": base.get("description", ""),
            "images": base.get("images", {}),
            "part_numbers": skus,
            "reviewed": m.get("reviewed", base.get("reviewed", False)),
        }
        if m.get("accessory_category"):
            target["accessory_category"] = m["accessory_category"]
        if m.get("accessory_of_products"):
            target["accessory_of_products"] = list(m["accessory_of_products"])
        for s in srcs:
            if s != tid:
                del products[s]
        products[tid] = target
        acts.append(f"⇒ merged {len(srcs)} products → {tid} ({len(skus)} SKUs, home={target['fits_part_types']})")

    # 3. Set home on existing products.
    for h in plan.get("set_home", []):
        pid = h["product_id"]
        if pid not in products:
            raise ValueError(f"set_home unknown product: {pid}")
        products[pid]["fits_part_types"] = list(h.get("fits_part_types") or [])
        for t in (h.get("add_tags") or []):
            tags = products[pid].setdefault("tag_ids", [])
            if t not in tags:
                tags.append(t)
        acts.append(f"~ {pid} home → {products[pid]['fits_part_types']}")

    # 4. Set accessory role.
    for a in plan.get("set_accessory", []):
        pid = a["product_id"]
        if pid not in products:
            raise ValueError(f"set_accessory unknown product: {pid}")
        products[pid]["accessory_category"] = a["accessory_category"]
        products[pid]["accessory_of_products"] = list(a.get("accessory_of_products") or [])
        acts.append(f"~ {pid} accessory of {len(products[pid]['accessory_of_products'])} products")

    # 5. Delete part_types (only if unused).
    for ptid in plan.get("delete_part_types", []):
        users = [pid for pid, p in products.items() if ptid in (p.get("fits_part_types") or [])]
        if users:
            raise ValueError(f"refuse to delete part_type {ptid}: still used by {users}")
        if ptid in part_types:
            del part_types[ptid]
            acts.append(f"- part_type {ptid}")

    return acts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    pdb = json.loads(PARTS_DB.read_text("utf-8"))
    plan = json.loads(args.plan.read_text("utf-8"))
    try:
        acts = apply_plan(pdb, plan)
    except ValueError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1

    for a in acts:
        print(f"  {a}")
    if not args.write:
        print("\n(dry run — re-run with --write to save through save_config_file)")
        return 0

    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.paths import AppPaths
    res = save_config_file("parts_db.json", pdb, AppPaths())
    if not res.get("ok"):
        print(f"Save failed: {res.get('error')}", file=sys.stderr)
        return 3
    print(f"\n✓ applied ({'queued' if res.get('queued') else 'saved'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
