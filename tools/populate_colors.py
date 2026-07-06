"""Populate color / secondary_color on light-tagged SKUs that lack them.

Warning/scene lights need per-SKU colors for the picker's color configurator and
the grid's readiness check. Freshly-imported light products have empty colors;
this fills them from two signals, in order:

  1. explicit colors in the QB description ("RED/WHITE", "BLUE/AMBER", "BLUE"…);
  2. the SoundOff MPOWER/NForce SKU suffix code (D=R/W, E=B/W, K=R/A, M=B/A,
     R=red, B=blue, A=amber, W=white).

Confident hits are applied; anything unresolved (e.g. an unknown suffix) is left
blank and reported for manual entry. Scoped to products carrying the `light`
tag whose SKUs have no color yet. Dry-run by default; ``--write`` saves.

Usage:
  python tools/populate_colors.py
  python tools/populate_colors.py --write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"

# Description combos (checked first), then singles.
_COMBOS = [
    (r"RED\s*/\s*WHITE", ("red", "white")),
    (r"BLUE\s*/\s*WHITE", ("blue", "white")),
    (r"RED\s*/\s*AMBER", ("red", "amber")),
    (r"BLUE\s*/\s*AMBER", ("blue", "amber")),
    (r"RED\s*/\s*BLUE", ("red", "blue")),
    (r"AMBER\s*/\s*WHITE", ("amber", "white")),
]
_SINGLES = [("\\bRED\\b", ("red",)), ("\\bBLUE\\b", ("blue",)),
            ("\\bAMBER\\b", ("amber",)), ("\\bWHITE\\b", ("white",))]

# SoundOff MPOWER/NForce SKU trailing color code (last char after the size digit).
_SKU_CODE = {"D": ("red", "white"), "E": ("blue", "white"),
             "K": ("red", "amber"), "M": ("blue", "amber"),
             "R": ("red",), "B": ("blue",), "A": ("amber",), "W": ("white",)}


def infer(desc: str, sku: str) -> tuple[tuple[str, ...] | None, str]:
    """Return (colors, source) or (None, reason)."""
    d = (desc or "").upper()
    for pat, cols in _COMBOS:
        if re.search(pat, d):
            return cols, "desc-combo"
    for pat, cols in _SINGLES:
        if re.search(pat, d):
            return cols, "desc-single"
    # SoundOff suffix: a size digit followed by a single color letter at the end.
    m = re.search(r"\d([A-Z])$", (sku or "").upper())
    if m and m.group(1) in _SKU_CODE:
        return _SKU_CODE[m.group(1)], "sku-code"
    return None, "unresolved"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    pdb = json.loads(PARTS_DB.read_text("utf-8"))
    # light tag id
    light_id = next((tid for tid, t in (pdb.get("tags") or {}).items()
                     if tid == "light" or (t.get("label") or "").strip().lower() == "light"), "light")

    applied = 0
    unresolved: list[str] = []
    report: list[str] = []
    for pid, p in pdb["products"].items():
        if light_id not in (p.get("tag_ids") or []):
            continue
        for pn in p.get("part_numbers", []):
            if pn.get("color"):
                continue   # already has a color
            cols, src = infer(pn.get("friendly_name", ""), pn.get("part_number", ""))
            if not cols:
                unresolved.append(f"{pid} / {pn.get('part_number','')} — {pn.get('friendly_name','')[:44]}")
                continue
            pn["color"] = cols[0]
            pn["secondary_color"] = cols[1] if len(cols) > 1 else ""
            applied += 1
            report.append(f"  {pn.get('part_number',''):14s} → {'/'.join(cols):12s} ({src})")

    print(f"colored {applied} SKUs; {len(unresolved)} unresolved\n")
    for line in report:
        print(line)
    if unresolved:
        print(f"\nUNRESOLVED ({len(unresolved)}) — fill manually in the grid:")
        for u in unresolved:
            print(f"  {u}")

    if not args.write:
        print("\n(dry run — re-run with --write to save)")
        return 0

    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.paths import AppPaths
    res = save_config_file("parts_db.json", pdb, AppPaths())
    if not res.get("ok"):
        print(f"Save failed: {res.get('error')}", file=sys.stderr)
        return 3
    print(f"\n✓ colored {applied} SKUs ({'queued' if res.get('queued') else 'saved'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
