"""Collapse legacy zone-warning part_types into the single `warning_light` home.

Per the locked warning-light model (docs/PARTS_DB_AND_PICKER.md): a warning light
has ONE home; the zone is decided at placement (friendly naming only). This
migrates every product off the legacy zone-named warning part_types onto
`warning_light`, repoints their accessory brackets, and deletes the legacy
part_types. The picker's naming already resolves warning names from the placement
zone, so no product loses its Forward/Side/Rear name.

Flashers and tracers stay separate (not zone-warnings).

Dry-run by default; ``--write`` saves through save_config_file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"

LEGACY = ["forward_warning", "front_side_warning", "pit_bar_warning", "mirror_warning",
          "side_warning", "rear_warning", "lower_liftgate_warning"]
HOME = "warning_light"


def migrate(pdb: dict) -> list[str]:
    pts = pdb.get("part_types") or {}
    prods = pdb.get("products") or {}
    if HOME not in pts:
        raise ValueError(f"target home {HOME} missing — create it first")
    acts: list[str] = []
    legacy = set(LEGACY)

    # 1. Repoint products: any legacy warning id → warning_light (dedupe, keep others).
    moved = 0
    for pid, p in prods.items():
        fits = p.get("fits_part_types") or []
        if not (set(fits) & legacy):
            continue
        new = []
        for f in fits:
            f2 = HOME if f in legacy else f
            if f2 not in new:
                new.append(f2)
        p["fits_part_types"] = new
        moved += 1
    acts.append(f"repointed {moved} products → {HOME}")

    # 2. Repoint accessory brackets whose accessory_of is a legacy warning.
    reb = 0
    for ptid, pt in pts.items():
        if pt.get("accessory_of") in legacy:
            pt["accessory_of"] = HOME
            reb += 1
            acts.append(f"  accessory {ptid}: accessory_of → {HOME}")
    acts.append(f"repointed {reb} accessory part_types")

    # 3. Delete legacy part_types (only if no product still fits them).
    for ptid in LEGACY:
        users = [pid for pid, p in prods.items() if ptid in (p.get("fits_part_types") or [])]
        if users:
            raise ValueError(f"{ptid} still used by {users}")
        if ptid in pts:
            del pts[ptid]
            acts.append(f"- deleted part_type {ptid}")
    return acts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    pdb = json.loads(PARTS_DB.read_text("utf-8"))
    try:
        acts = migrate(pdb)
    except ValueError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1
    for a in acts:
        print(f"  {a}")
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
    print(f"\n✓ migrated ({'queued' if res.get('queued') else 'saved'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
