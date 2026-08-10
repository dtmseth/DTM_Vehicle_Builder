"""Seed per-part-type location model onto parts_db.json.

Locations live at the part_type level (see docs/PARTS_DB_AND_PICKER.md). Each
part_type gets:
  * location_mode: 'placement' (external/visual — the location tells the build
    preview WHERE to draw the part: lights, bumpers, arges, sirens) or 'text'
    (interior/equipment — the location is a curated pick-list printed on the
    sheet so the builder knows where it goes; no visual placement).
  * location_options: for text-mode part_types, the curated list — seeded from
    the old workbook per-part locations (minus 'specify' placeholders).

Mode is inferred: a part_type whose catalog parts render a diagram icon =
placement; everything else = text. Idempotent + non-destructive: part_types that
already carry a location_mode are left untouched (protects hand edits).

Dry-run by default; ``--write`` saves through save_config_file.

Usage:
  python tools/seed_part_type_locations.py            # dry run
  python tools/seed_part_type_locations.py --write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
PART_CATALOG = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "part_catalog.json"


def _base(label: str) -> str:
    return re.sub(r"\s+\d+$", "", (label or "").strip()).strip().lower()


def _renders_map(catalog: dict) -> dict[str, bool]:
    """base display_name (lower) → does any matching catalog part render a dot?"""
    out: dict[str, bool] = {}
    for p in catalog.get("parts", []):
        b = _base(p.get("display_name") or "")
        renders = (p.get("render_kind") or "none") != "none" and bool(p.get("default_views"))
        out[b] = out.get(b, False) or renders
    return out


def build_plan(parts_db: dict) -> list[dict]:
    # Legacy workbook locations, read through the service's fallback reader so we
    # match the same label→locations mapping the picker uses.
    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.parts_db_service import PartsDbService
    from dtm_buildsheet.paths import AppPaths
    svc = PartsDbService(AppPaths())

    catalog = json.loads(PART_CATALOG.read_text("utf-8"))
    renders = _renders_map(catalog)

    plan: list[dict] = []
    for ptid, pt in (parts_db.get("part_types") or {}).items():
        if pt.get("location_mode"):
            continue   # already seeded / hand-edited → leave alone
        label = pt.get("label") or ptid
        mode = "placement" if renders.get(_base(label)) else "text"
        options: list[str] = []
        if mode == "text":
            seen: set[str] = set()
            for loc in svc.locations_by_legacy_name(label):
                s = str(loc).strip()
                if not s or "SPECIFY" in s.upper() or s.upper() in seen:
                    continue
                seen.add(s.upper())
                options.append(s)
        plan.append({"ptid": ptid, "label": label, "mode": mode, "options": options})
    return plan


def apply_plan(parts_db: dict, plan: list[dict]) -> None:
    pts = parts_db.get("part_types") or {}
    for row in plan:
        pt = pts.get(row["ptid"])
        if pt is None:
            continue
        pt["location_mode"] = row["mode"]
        if row["mode"] == "text":
            pt["location_options"] = row["options"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    parts_db = json.loads(PARTS_DB.read_text("utf-8"))
    plan = build_plan(parts_db)

    placement = [r for r in plan if r["mode"] == "placement"]
    text = [r for r in plan if r["mode"] == "text"]
    text_seeded = [r for r in text if r["options"]]
    print(f"part_types to seed: {len(plan)}  "
          f"(placement {len(placement)} · text {len(text)}; "
          f"{len(text_seeded)} text part_types get options from the workbook)")
    print("\nText part_types WITH seeded options:")
    for r in sorted(text_seeded, key=lambda r: r["label"]):
        print(f"  {r['label']:<32s} {r['options']}")
    empty = [r["label"] for r in text if not r["options"]]
    print(f"\nText part_types with NO workbook options (editable to add later, {len(empty)}):")
    print("  " + ", ".join(sorted(empty)))

    if not args.write:
        print("\n(dry run — re-run with --write to save through save_config_file)")
        return 0

    apply_plan(parts_db, plan)
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.paths import AppPaths
    result = save_config_file("parts_db.json", parts_db, AppPaths())
    if not result.get("ok"):
        print(f"Save failed: {result.get('error')}", file=sys.stderr)
        return 3
    print(f"\n✓ seeded {len(plan)} part_types "
          f"({'queued' if result.get('queued') else 'saved'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
