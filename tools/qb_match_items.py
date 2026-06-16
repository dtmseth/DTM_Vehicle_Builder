#!/usr/bin/env python3
"""Pass 2: propose matches between catalog products and QBO inventory items.

Reads the real-company CSV export (authoritative for manufacturer + Sales
Description + part number) and the catalog (`parts_db.json`), and proposes
which CSV items each catalog product corresponds to — so a human can confirm
before any link is written. **This tool only proposes; it writes nothing to
parts_db.** Applying confirmed links (and pulling in the QBO Item Id) is a
later, separate step.

Matching is conservative on purpose (these become invoice line items):
  - EXACT  — a catalog part_number equals a CSV part number.
  - STRONG — the catalog model's tokens appear as whole words in the CSV Sales
             Description (≥70% token coverage, at least one token ≥3 chars).
             Whole-token, never substring, so "ION" doesn't match "extensION".
A product can have several STRONG candidates — that's the expected
one-product-to-many-part-numbers case.

Output: a grouped review file (`tools/qb_match_proposals.md`) + a summary.

Usage:
  python tools/qb_match_items.py PATH/TO/export.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
CATEGORY_MAP = REPO / "tools" / "qb_category_to_manufacturer.json"
PROPOSALS_OUT = REPO / "tools" / "qb_match_proposals.md"

_STRONG_COVERAGE = 0.70


def toks(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) >= 2]


def score(model_tokens: list[str], desc_tokens: set[str]) -> tuple[float, bool]:
    """Return (coverage, has_strong_token) for a model against a description."""
    if not model_tokens:
        return 0.0, False
    present = [t for t in model_tokens if t in desc_tokens]
    if not present:
        return 0.0, False
    return len(present) / len(model_tokens), any(len(t) >= 3 for t in present)


def load_csv_items(csv_path: Path, cat_to_mid: dict) -> list[dict]:
    items = []
    for r in csv.DictReader(open(csv_path, newline="", encoding="utf-8-sig")):
        pn = (r.get("Product/Service Name") or "").strip()
        if not pn:
            continue
        cat = (r.get("Category") or "").strip().upper()
        desc = " ".join((r.get("Sales Description") or "").split())
        items.append({
            "pn": pn,
            "mid": cat_to_mid.get(cat, ""),
            "desc": desc,
            "desc_tokens": set(toks(desc)),
        })
    return items


def propose(products: dict, csv_items: list[dict]):
    """Return per-product proposals + summary buckets."""
    by_mid = defaultdict(list)
    for it in csv_items:
        if it["mid"]:
            by_mid[it["mid"]].append(it)
    csv_pn = {it["pn"].lower(): it for it in csv_items}

    proposals = {}  # product_id -> {"exact": [...], "strong": [(item, cov)...]}
    for pid, spec in products.items():
        mid = spec.get("manufacturer_id", "")
        model_tokens = toks(spec.get("model", ""))
        exact, strong = [], []

        for pn in spec.get("part_numbers") or []:
            num = str(pn.get("part_number", "")).strip().lower()
            if num and num in csv_pn:
                exact.append(csv_pn[num])

        for it in by_mid.get(mid, []):
            cov, has_strong = score(model_tokens, it["desc_tokens"])
            if cov >= _STRONG_COVERAGE and has_strong:
                strong.append((it, cov))
        strong.sort(key=lambda x: -x[1])
        if exact or strong:
            proposals[pid] = {"exact": exact, "strong": strong}
    return proposals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    args = ap.parse_args()
    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 2

    db = json.loads(PARTS_DB.read_text("utf-8"))
    products = db.get("products", {})
    mfrs = db.get("manufacturers", {})
    cat_to_mid = json.loads(CATEGORY_MAP.read_text("utf-8"))
    csv_items = load_csv_items(args.csv, cat_to_mid)

    proposals = propose(products, csv_items)

    n_exact = sum(1 for p in proposals.values() if p["exact"])
    n_strong = sum(1 for p in proposals.values() if p["strong"] and not p["exact"])
    n_strong_pairs = sum(len(p["strong"]) for p in proposals.values())
    matched_pids = set(proposals)
    no_match = [pid for pid in products if pid not in matched_pids]

    print(f"catalog products: {len(products)}")
    print(f"  EXACT part-number match : {n_exact}")
    print(f"  STRONG description match : {n_strong} products "
          f"({n_strong_pairs} candidate part numbers)")
    print(f"  no match (manual later)  : {len(no_match)}")

    # Write a grouped, reviewable proposal file.
    lines = ["# QB item match proposals (Pass 2 — review before linking)\n",
             "Confirm/strike rows, then I apply the confirmed links. Nothing is "
             "written to parts_db until you approve.\n"]
    by_mfr = defaultdict(list)
    for pid, prop in proposals.items():
        by_mfr[products[pid].get("manufacturer_id", "")].append((pid, prop))
    for mid in sorted(by_mfr):
        label = mfrs.get(mid, {}).get("label", mid or "(no manufacturer)")
        lines.append(f"\n## {label}\n")
        for pid, prop in sorted(by_mfr[mid]):
            model = products[pid].get("model", "")
            lines.append(f"- **{model}**  `{pid}`")
            for it in prop["exact"]:
                lines.append(f"    - ✅ EXACT  `{it['pn']}`  —  {it['desc']}")
            for it, cov in prop["strong"]:
                lines.append(f"    - ◇ {cov:.0%}  `{it['pn']}`  —  {it['desc']}")
    PROPOSALS_OUT.write_text("\n".join(lines) + "\n", "utf-8")
    print(f"\nwrote review file → {PROPOSALS_OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
