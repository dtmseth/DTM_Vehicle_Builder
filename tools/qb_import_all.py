"""Bulk-import every QB Online item that isn't yet in parts_db.

Goal: make the FULL QuickBooks inventory visible in the Part Manager so the owner
can curate it through the SKU grid — assign part-types, merge SKUs into shared
products, tag lights, set accessories, etc. This is the "fill the shelves" step.

What it does, per QB item not already represented in parts_db (matched by
qb_item_id OR part_number):
  * infers the manufacturer from the QB description (prefix, then substring match
    against known manufacturer labels); unmatched items land under a single
    holding manufacturer (`qb_unassigned`) so they're easy to find and reassign.
  * creates ONE product with ONE SKU (one-product-per-SKU, conservative — the
    owner merges variants later via the grid's "move SKU" tool).
  * the SKU carries the real QB linkage (qb_item_id / qb_sku / qb_unit_price) and
    the QB description as its friendly_name (sales description). These items ARE
    in QB, so they are QB-linked, not pending-QB.
  * products are left with NO part-type home (fits_part_types=[]) and reviewed=
    false → they show as "Needs: home" in the grid, which is the work queue.

Dry-run by default; ``--write`` saves through save_config_file so the SharePoint
mirror fires (run while signed in to propagate to the team; otherwise it writes
locally and the next signed-in save mirrors it).

Usage:
  python tools/qb_import_all.py                # dry run — summary only
  python tools/qb_import_all.py --write        # apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
CACHE = REPO / "workspace" / "quickbooks_items_cache.json"
CATMAP = REPO / "tools" / "qb_category_to_manufacturer.json"

HOLDING_MID = "qb_unassigned"
HOLDING_LABEL = "Unassigned (QB Import)"


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").strip().lower())
    return s.strip("_") or "x"


def _present_keys(parts_db: dict) -> tuple[set[str], set[str]]:
    """qb_item_ids and uppercased part_numbers already in parts_db."""
    qids: set[str] = set()
    pns: set[str] = set()
    for p in parts_db.get("products", {}).values():
        for pn in p.get("part_numbers", []) or []:
            if pn.get("qb_item_id"):
                qids.add(str(pn["qb_item_id"]))
            if pn.get("part_number"):
                pns.add(str(pn["part_number"]).strip().upper())
    return qids, pns


def _build_label_map(parts_db: dict, catmap: dict) -> tuple[dict[str, str], dict[str, str]]:
    """UPPER manufacturer label → manufacturer_id, plus id → display label."""
    label_to_id: dict[str, str] = {}
    id_to_label: dict[str, str] = {}
    for mid, m in parts_db.get("manufacturers", {}).items():
        lab = (m.get("label") or mid).strip()
        label_to_id[lab.upper()] = mid
        id_to_label[mid] = lab
    for label, mid in catmap.items():
        label_to_id.setdefault(label.strip().upper(), mid)
        id_to_label.setdefault(mid, label.strip().title())
    return label_to_id, id_to_label


def _infer_mid(desc: str, labels_sorted: list[str], label_to_id: dict[str, str]) -> tuple[str | None, str | None]:
    """Return (manufacturer_id, matched_label) or (None, None)."""
    d = (desc or "").strip().upper()
    for lab in labels_sorted:                       # prefix match (most specific)
        if d.startswith(lab):
            return label_to_id[lab], lab
    for lab in labels_sorted:                       # substring anywhere
        if len(lab) >= 4 and lab in d:
            return label_to_id[lab], lab
    return None, None


def _clean_model(desc: str, name: str, matched_label: str | None) -> str:
    """Display model: description minus a leading manufacturer label, else the name."""
    d = (desc or "").strip()
    if not d:
        return name.strip()
    if matched_label and d.upper().startswith(matched_label):
        d = d[len(matched_label):].lstrip(" ,-:").strip()
    return d or name.strip()


def build_plan(parts_db: dict, items: list[dict], catmap: dict) -> dict:
    present_qid, present_pn = _present_keys(parts_db)
    label_to_id, id_to_label = _build_label_map(parts_db, catmap)
    labels_sorted = sorted(label_to_id.keys(), key=len, reverse=True)
    now = datetime.now(timezone.utc).isoformat()

    products = parts_db.setdefault("products", {})
    manufacturers = parts_db.setdefault("manufacturers", {})
    used_ids = set(products.keys())

    new_products: dict[str, dict] = {}
    new_mfrs: dict[str, str] = {}
    per_mfr: dict[str, int] = {}
    skipped = 0

    for it in items:
        qid = str(it.get("qb_item_id", ""))
        name = (it.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        if qid in present_qid or name.upper() in present_pn:
            continue

        desc = it.get("description") or ""
        mid, matched = _infer_mid(desc, labels_sorted, label_to_id)
        if not mid:
            mid, matched = HOLDING_MID, None

        # Ensure the manufacturer exists (create inferred-but-missing + holding).
        if mid not in manufacturers and mid not in new_mfrs:
            new_mfrs[mid] = HOLDING_LABEL if mid == HOLDING_MID else (
                id_to_label.get(mid) or matched.title() if matched else mid)

        pid = f"{mid}_{_slug(name)}"
        n = 2
        while pid in used_ids or pid in new_products:
            pid = f"{mid}_{_slug(name)}_{n}"
            n += 1
        used_ids.add(pid)

        price = it.get("unit_price")
        sku = {
            "part_number": name,
            "friendly_name": desc,
            "qb_item_id": qid,
            "qb_sku": it.get("sku") or "",
            "qb_unit_price": price,
            "qb_inactive": False,
            "qb_last_synced": now,
            "price_usd": price,
            "vehicle_tags": ["any"],
            "options": {},
        }
        new_products[pid] = {
            "manufacturer_id": mid,
            "model": _clean_model(desc, name, matched),
            "fits_part_types": [],
            "tag_ids": [],
            "description": "",
            "images": {},
            "part_numbers": [sku],
            "reviewed": False,
        }
        per_mfr[mid] = per_mfr.get(mid, 0) + 1

    return {"new_products": new_products, "new_mfrs": new_mfrs,
            "per_mfr": per_mfr, "skipped": skipped}


def apply_plan(parts_db: dict, plan: dict) -> None:
    for mid, label in plan["new_mfrs"].items():
        parts_db.setdefault("manufacturers", {})[mid] = {"label": label, "website": ""}
    parts_db.setdefault("products", {}).update(plan["new_products"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if not CACHE.exists():
        print(f"items cache not found ({CACHE}). Pull items in the app first.", file=sys.stderr)
        return 2

    parts_db = json.loads(PARTS_DB.read_text("utf-8"))
    items = json.loads(CACHE.read_text("utf-8")).get("items", [])
    catmap = json.loads(CATMAP.read_text("utf-8")) if CATMAP.exists() else {}

    plan = build_plan(parts_db, items, catmap)
    total = len(plan["new_products"])
    print(f"QB items: {len(items)} | new products to create: {total} | "
          f"new manufacturers: {len(plan['new_mfrs'])} | skipped (no name): {plan['skipped']}")
    print("\nNew products by manufacturer:")
    for mid, c in sorted(plan["per_mfr"].items(), key=lambda kv: -kv[1]):
        flag = "  ← holding bucket (reassign in grid)" if mid == HOLDING_MID else ""
        print(f"  {c:4d}  {mid}{flag}")
    if plan["new_mfrs"]:
        print("\nManufacturers created:", ", ".join(sorted(plan["new_mfrs"])))

    if not args.write:
        print("\n(dry run — re-run with --write to save through save_config_file)")
        return 0

    apply_plan(parts_db, plan)
    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.paths import AppPaths
    result = save_config_file("parts_db.json", parts_db, AppPaths())
    if not result.get("ok"):
        print(f"Save failed: {result.get('error')}", file=sys.stderr)
        return 3
    tag = "queued for retry" if result.get("queued") else "saved (mirror fired if signed in)"
    print(f"\n✓ wrote {total} products — {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
