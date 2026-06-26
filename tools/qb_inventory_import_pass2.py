#!/usr/bin/env python3
"""Pass 2 of the QuickBooks inventory import: items → products + part numbers.

Pass 1 (`qb_inventory_import.py`) reconciled the export's manufacturers and
emitted `qb_category_to_manufacturer.json`. This pass takes the remaining
**items** and proposes how each enters `parts_db.json`.

It is a **proposer, not a writer**: it never touches parts_db. It emits one
reviewable `qb_apply_links.py` mapping file per manufacturer (into
`tools/qb_links/qb_inv_<mid>.json`) plus a printed report. You eyeball/edit the
mapping, then apply it with the existing, tested tool:

    python tools/qb_apply_links.py tools/qb_links/qb_inv_<mid>.json          # dry
    python tools/qb_apply_links.py tools/qb_links/qb_inv_<mid>.json --write  # apply

Policy (locked with Seth, 2026-06-26):
  - **Mechanism = pending-QB** (`pending_parts`): each item is added as a real,
    orderable `part_number` carrying the CSV **Price** and `qb_pending=true`
    (the CSV has no QBO Item Id — only an API sync provides that). It reconciles
    to the Item Id automatically once items are synced. See docs/PENDING_QB_PARTS.md.
  - **Granularity = one product per SKU**, conservative attach: an item only
    attaches to an existing product when that product's model is a confident
    match; otherwise it gets its own new product (model from the cleaned Sales
    Description, `fits_part_types: []` so it's catalog-only until you assign a
    part type in the Part Manager).
  - **Skips**: items whose part# is already in parts_db (already imported), and
    junk rows (blank/placeholder part#, blank description, missing price). Junk
    is listed under REVIEW so nothing is silently dropped or silently created.

The CSV (`ProductsServicesList_*.csv`) layout: `Product/Service Name` = part
number (SKU column is empty), `Category` = manufacturer, `Sales Description` =
human name, `Price` = list price.

Usage:
  python tools/qb_inventory_import_pass2.py PATH/TO/export.csv                      # all mfrs
  python tools/qb_inventory_import_pass2.py PATH/TO/export.csv --manufacturers whelen,setina
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
CATEGORY_MAP = REPO / "tools" / "qb_category_to_manufacturer.json"
OUT_DIR = REPO / "tools" / "qb_links"

# A plausible SKU: starts alnum, no internal spaces, len >= 3, only SKU chars.
_SKU_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-./#]{2,}$")
# Placeholder/junk part numbers that aren't real SKUs.
_JUNK_PN_RE = re.compile(r"\b(PART|SHIPPING|QUOTE|MISC|TBD)\b", re.IGNORECASE)


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def strip_mfr(sales_desc: str, mfr_label: str) -> str:
    """Sales Description with a leading manufacturer name dropped + whitespace
    collapsed. Kept faithful (no re-casing) — the owner renames in the Part
    Manager."""
    s = re.sub(r"\s+", " ", (sales_desc or "").strip())
    pref = mfr_label.strip()
    if pref and s.upper().startswith(pref.upper()):
        s = s[len(pref):].strip(" -,")
    return s or re.sub(r"\s+", " ", (sales_desc or "").strip())


def clean_model(sales_desc: str, mfr_label: str) -> str:
    """Product model = manufacturer-stripped description, truncated."""
    return strip_mfr(sales_desc, mfr_label)[:60].strip() or sales_desc[:60].strip()


def load_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def parse_price(raw: str):
    try:
        v = float(str(raw).replace(",", "").strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--manufacturers", default="",
                    help="comma-separated manufacturer_ids to process (default: all mapped)")
    args = ap.parse_args()
    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 2

    parts_db = json.loads(PARTS_DB.read_text("utf-8"))
    catmap = json.loads(CATEGORY_MAP.read_text("utf-8"))
    rows = load_rows(args.csv)
    only = {m.strip() for m in args.manufacturers.split(",") if m.strip()}

    mfr_label = {mid: spec.get("label", mid)
                 for mid, spec in parts_db.get("manufacturers", {}).items()}
    # Existing part numbers (any product) and existing products per manufacturer.
    existing_pns = set()
    prods_by_mfr: dict[str, list[tuple[str, str]]] = {}
    for pid, p in parts_db.get("products", {}).items():
        prods_by_mfr.setdefault(p.get("manufacturer_id"), []).append((pid, p.get("model", "")))
        for pn in (p.get("part_numbers") or []):
            existing_pns.add(str(pn.get("part_number", "")).strip().upper())

    # Bucket rows per manufacturer.
    per_mfr: dict[str, dict] = {}
    for r in rows:
        cat = (r.get("Category") or "").strip().upper()
        mid = catmap.get(cat)
        if not mid or (only and mid not in only):
            continue
        b = per_mfr.setdefault(mid, {"attach": [], "create": [], "already": 0, "review": []})
        pn = (r.get("Product/Service Name") or "").strip()
        sd = re.sub(r"\s+", " ", (r.get("Sales Description") or "").strip())
        price = parse_price(r.get("Price"))

        if not pn or pn.upper() in existing_pns:
            if pn:
                b["already"] += 1
            continue
        # Junk / un-importable guards.
        reason = None
        if not _SKU_RE.match(pn) or _JUNK_PN_RE.search(pn):
            reason = "implausible part#"
        elif not sd:
            reason = "blank description"
        elif price is None:
            reason = "missing/zero price"
        if reason:
            b["review"].append((pn, sd or "(blank)", reason))
            continue

        # Conservative attach: exactly one existing product whose (>=3-char)
        # model appears as a whole phrase in the normalized description.
        nd = _norm(sd)
        hits = [(pid, model) for pid, model in prods_by_mfr.get(mid, [])
                if len(_norm(model)) >= 3 and _norm(model) in nd]
        if len(hits) == 1:
            b["attach"].append((hits[0][0], pn, price, sd))
        else:
            b["create"].append((pn, price, sd))

    if not per_mfr:
        print("No matching rows (check --manufacturers and the category map).")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    grand = {"attach": 0, "create": 0, "already": 0, "review": 0}
    for mid, b in sorted(per_mfr.items()):
        label = mfr_label.get(mid, mid)
        new_products, pending, seen_ids = [], [], set()

        for pid, pn, price, sd in b["attach"]:
            pending.append({"product": pid, "part_number": pn, "price": price,
                            "friendly_name": strip_mfr(sd, label), "vehicle_tags": ["any"]})
        for pn, price, sd in b["create"]:
            model = clean_model(sd, label)
            base = f"{mid}_{slug(model)[:48]}".strip("_")
            pidnew, n = base, 2
            while pidnew in seen_ids or pidnew in parts_db.get("products", {}):
                pidnew = f"{base}_{n}"; n += 1
            seen_ids.add(pidnew)
            new_products.append({"product_id": pidnew, "model": model, "fits_part_types": []})
            pending.append({"product": pidnew, "part_number": pn, "price": price,
                            "friendly_name": strip_mfr(sd, label), "vehicle_tags": ["any"]})

        mapping = {
            "manufacturer_id": mid,
            "_note": (f"QB inventory import Pass 2 (proposed) for {label}. "
                      f"{len(new_products)} new products (one per SKU, fits_part_types empty "
                      f"= catalog-only until a part type is assigned in the Part Manager), "
                      f"{len(pending)} pending-QB part_numbers (CSV price; reconcile to Item Id "
                      f"on sync). REVIEW before --write; edit/merge products + assign fits as needed."),
            "new_products": new_products,
            "pending_parts": pending,
        }
        out = OUT_DIR / f"qb_inv_{mid}.json"
        out.write_text(json.dumps(mapping, indent=2) + "\n", "utf-8")

        for k in grand:
            grand[k] += b[k] if isinstance(b[k], int) else len(b[k])
        print(f"\n=== {label}  ({mid}) ===")
        print(f"  attach to existing: {len(b['attach'])}   create new: {len(b['create'])}"
              f"   already in db: {b['already']}   review/skip: {len(b['review'])}")
        print(f"  → wrote {out.relative_to(REPO)}")
        for pn, sd, why in b["review"]:
            print(f"     ⚠ REVIEW [{why}]  {pn!r}: {sd[:60]}")

    print(f"\nTOTAL  attach={grand['attach']}  create={grand['create']}  "
          f"already={grand['already']}  review={grand['review']}")
    print("\nProposer only — parts_db unchanged. Review each qb_inv_<mid>.json, then apply with "
          "qb_apply_links.py (dry-run → --write).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
