"""Apply docs/audit/part_type_taxonomy_plan.json to parts_db.json.

One-shot, idempotent applier for the part-type taxonomy finalized in
PART_TYPE_TAXONOMY_PROPOSAL.md (owner answers 2026-07-07). Applies:

  1. task1_type_id_corrections — flips part_type.type_id (console, preemption).
  2. task2_families — writes the top-level `families` collection and stamps
     `family_id` onto each member part_type.

Additive/non-destructive: no part_type deleted, no fits_part_types/home
changed, no product touched. part_type.category is left untouched (the
picker still reads it; family_id is layered alongside, not in place of it).

Dry-run by default; ``--write`` saves through save_config_file.

Usage:
  python tools/apply_family_taxonomy.py
  python tools/apply_family_taxonomy.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
PLAN = REPO / "docs" / "audit" / "part_type_taxonomy_plan.json"


def apply_plan(pdb: dict, plan: dict) -> list[str]:
    part_types = pdb.setdefault("part_types", {})
    acts: list[str] = []

    # 1. type_id corrections.
    for corr in plan.get("task1_type_id_corrections", []):
        ptid = corr["part_type"]
        if ptid not in part_types:
            raise ValueError(f"type_id correction: unknown part_type {ptid!r}")
        current = part_types[ptid].get("type_id")
        if current != corr["from"]:
            acts.append(
                f"= {ptid} type_id already {current!r} (expected from={corr['from']!r}), skip"
            )
            continue
        part_types[ptid]["type_id"] = corr["to"]
        acts.append(f"~ {ptid} type_id: {corr['from']} -> {corr['to']}")

    # 2. families collection + family_id back-references.
    families = pdb.setdefault("families", {})
    for family_id, spec in plan.get("task2_families", {}).items():
        members = list(spec["members"])
        missing = [m for m in members if m not in part_types]
        if missing:
            raise ValueError(f"family {family_id!r}: unknown member part_types {missing}")
        family_doc = {
            "label": spec["label"],
            "category": spec["category"],
            "members": members,
        }
        if "kind" in spec:
            family_doc["kind"] = spec["kind"]
        if "picker_flow" in spec:
            family_doc["picker_flow"] = spec["picker_flow"]
        families[family_id] = family_doc
        acts.append(f"+ family {family_id} ({len(members)} members)")

        for ptid in members:
            existing = part_types[ptid].get("family_id")
            if existing not in (None, family_id):
                raise ValueError(
                    f"part_type {ptid!r} already has family_id={existing!r}, "
                    f"cannot also assign {family_id!r} (membership must be single)"
                )
            part_types[ptid]["family_id"] = family_id

    return acts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, default=PLAN)
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
