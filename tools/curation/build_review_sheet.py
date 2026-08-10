"""Validate the Phase-3 proposal plans and render the review sheet.

- Parses every tools/curation/proposals/*.json in filename order.
- Dry-runs them sequentially through tools/curate.py::apply_plan on a deep copy
  of parts_db (nothing is written) so any bad reference fails HERE, not during
  your apply.
- Checks coverage: every product in tools/triage_products.json (the unhomed
  queue) must be touched by some plan or carry an explicit open question.
- Renders tools/curation/proposals/REVIEW_SHEET.md — grouped by proposed
  part_type, confidence-sorted, one line per product, questions inline.

Usage:  python tools/curation/build_review_sheet.py
"""

from __future__ import annotations

import copy
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CFG = REPO / "src" / "dtm_buildsheet" / "resources" / "config"
PROPOSALS = REPO / "tools" / "curation" / "proposals"
OUT = PROPOSALS / "REVIEW_SHEET.md"

_spec = importlib.util.spec_from_file_location("curate", REPO / "tools" / "curate.py")
curate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(curate)

CONF_ORDER = {"high": 0, "medium": 1, "low": 2}


def main() -> int:
    pdb = json.loads((CFG / "parts_db.json").read_text("utf-8"))
    queue = {r["product_id"]: r for r in
             json.loads((REPO / "tools" / "triage_products.json").read_text("utf-8"))}

    plans = sorted(PROPOSALS.glob("*.json"))
    work = copy.deepcopy(pdb)
    touched: dict[str, str] = {}          # product_id -> plan file
    rows = []                              # review rows
    failures = []

    for pf in plans:
        plan = json.loads(pf.read_text("utf-8"))
        name = pf.name

        # dry-run (mutates the working copy so later plans see earlier results)
        try:
            curate.apply_plan(work, plan)
        except ValueError as exc:
            failures.append(f"{name}: {exc}")
            continue

        for spec in plan.get("create_part_types", []):
            rows.append({
                "plan": name, "kind": "new part_type",
                "pt": spec["part_type_id"], "pid": "(part_type)",
                "conf": spec.get("_confidence", "medium"),
                "why": spec.get("_why", ""), "q": spec.get("_question", ""),
                "label": spec.get("label", ""),
            })
        for m in plan.get("merge", []):
            for s in m["sources"]:
                touched[s] = name
            pts = m.get("fits_part_types") or \
                (pdb["products"].get(m["target_id"], {}).get("fits_part_types") or ["(keep)"])
            rows.append({
                "plan": name, "kind": f"merge {len(m['sources'])}→1",
                "pt": ", ".join(pts), "pid": m["target_id"],
                "conf": m.get("_confidence", "medium"),
                "why": m.get("_why", ""), "q": m.get("_question", ""),
                "label": m.get("model", ""),
            })
        for h in plan.get("set_home", []):
            touched[h["product_id"]] = name
            rows.append({
                "plan": name, "kind": "home",
                "pt": ", ".join(h.get("fits_part_types") or ["(none — question)"]),
                "pid": h["product_id"],
                "conf": h.get("_confidence", "medium"),
                "why": h.get("_why", ""), "q": h.get("_question", ""),
                "label": "",
            })
        for a in plan.get("set_accessory", []):
            touched.setdefault(a["product_id"], name)
            rows.append({
                "plan": name, "kind": f"accessory:{a['accessory_category']}",
                "pt": "(accessory of " + ", ".join(a.get("accessory_of_products") or []) + ")",
                "pid": a["product_id"],
                "conf": a.get("_confidence", "medium"),
                "why": a.get("_why", ""), "q": a.get("_question", ""),
                "label": "",
            })
        for d in plan.get("delete_products", []):
            touched[d] = name
            note = (plan.get("_delete_notes") or {}).get(d) or \
                   (plan.get("_per_item_notes") or {}).get(d, "")
            rows.append({
                "plan": name, "kind": "DELETE", "pt": "(delete)", "pid": d,
                "conf": "low" if note.upper().startswith("LOW") else
                        ("medium" if note.upper().startswith("MEDIUM") else "high"),
                "why": note or plan.get("_meta", {}).get("blanket_rationale", "")[:120],
                "q": "", "label": "",
            })

    uncovered = [pid for pid in queue if pid not in touched]

    print(f"plans: {len(plans)}   rows: {len(rows)}   queue: {len(queue)}   "
          f"covered: {len(queue) - len(uncovered)}   uncovered: {len(uncovered)}")
    if failures:
        print("\nDRY-RUN FAILURES:")
        for f in failures:
            print("  ✗", f)
    if uncovered:
        print("\nUNCOVERED QUEUE PRODUCTS:")
        for pid in uncovered:
            r = queue[pid]
            print(f"  - {pid}  ({r['manufacturer_id']}): {r['desc'][:70]}")

    # ---- render the review sheet ----
    by_pt: dict[str, list] = defaultdict(list)
    for r in rows:
        by_pt[r["pt"]].append(r)

    L = ["# Phase 3 review sheet — classification proposals",
         "",
         f"Generated by `tools/curation/build_review_sheet.py` from {len(plans)} plan files. "
         f"Covers {len(queue) - len(uncovered)}/{len(queue)} queue products"
         + (f" (**{len(uncovered)} uncovered — see end**)" if uncovered else "") + ".",
         "",
         "**How to apply:** review a plan file, delete/edit entries you reject, then "
         "`python tools/curate.py tools/curation/proposals/<file> --write` in filename order "
         "(00 → 01 → 10 → 11 → …). Dry-run first (no `--write`). Close the dev app during "
         "bulk applies (60s sync gotcha) and commit after each plan.",
         "",
         "Confidence: 🟢 high — apply unless it looks wrong · 🟡 medium — worth a glance · "
         "🔴 low — answer the question first, never auto-apply.",
         ""]
    icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}

    def pt_rank(kv):
        pts = kv[0]
        return (pts.startswith("("), pts)

    for pt, items in sorted(by_pt.items(), key=pt_rank):
        items.sort(key=lambda r: (CONF_ORDER.get(r["conf"], 1), r["pid"]))
        n_q = sum(1 for r in items if r["q"])
        L.append(f"\n## → `{pt}`  ({len(items)} proposals{f', {n_q} questions' if n_q else ''})\n")
        for r in items:
            desc = queue.get(r["pid"], {}).get("desc", "")
            line = f"- {icon.get(r['conf'],'🟡')} **{r['pid']}**"
            if r["label"]:
                line += f" → *{r['label']}*"
            line += f" · {r['kind']} · _{r['plan']}_"
            if desc:
                line += f"\n  - QB: {desc[:110]}"
            if r["why"]:
                line += f"\n  - why: {r['why']}"
            if r["q"]:
                line += f"\n  - **❓ {r['q']}**"
            L.append(line)

    if uncovered:
        L.append("\n## ⚠ Uncovered queue products (no proposal — needs a follow-up)\n")
        for pid in uncovered:
            r = queue[pid]
            L.append(f"- **{pid}** ({r['manufacturer_id']}): {r['desc'][:100]}")

    OUT.write_text("\n".join(L) + "\n", "utf-8")
    print(f"\n→ {OUT.relative_to(REPO)}")
    return 1 if (failures or uncovered) else 0


if __name__ == "__main__":
    raise SystemExit(main())
