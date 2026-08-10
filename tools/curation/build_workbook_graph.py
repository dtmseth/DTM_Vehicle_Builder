"""Mine workbook_rules.json into an explicit relationship graph + reconcile vs parts_db.

Phase 2 of the curation-intelligence session (2026-07-07). Read-only over
config; writes only tools/curation/workbook_graph.json and
tools/curation/WORKBOOK_GRAPH.md.

Sources:
  - workbook_rules.json      part_rules (label -> manufacturers/models/locations),
                             template_sections (section -> ordered part slots)
  - legacy_workbook_index.json  label -> product_ids, model string -> product_id
  - parts_db.json            the live catalog to reconcile against

The graph groups numbered slots ("Forward Warning 1/2") into one base slot,
maps each base to its live part_type (via workbook_label_pattern, plurals
handled, plus a superseded-map for the collapsed warning-light homes), and
reports per-slot reconciliation: location confirmations/conflicts, which
workbook manufacturers actually have homed products on that part_type, and
whether each workbook model string still resolves to a live product.

Usage:  python tools/curation/build_workbook_graph.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CFG = REPO / "src" / "dtm_buildsheet" / "resources" / "config"
OUT_JSON = REPO / "tools" / "curation" / "workbook_graph.json"
OUT_MD = REPO / "tools" / "curation" / "WORKBOOK_GRAPH.md"

# Workbook base labels whose part_type was collapsed into the single
# warning-light home (locked 2026-07-01). legacy_zone preserves what the
# zone-named slot used to say about *where* — placement decides that now.
SUPERSEDED_TO_WARNING = {
    "Forward Warning {n}": "front (primary)",
    "Front Side Warning": "front side",
    "Pit Bar Warning": "pit bar",
    "Side Warning {n}": "side",
    "Rear Warning {n}": "rear",
    "Lower Lift Gate Warning": "lower liftgate",
    "Mirror Warning {n}": "under mirror",
    "2-Lamp Tracer": "front (tracer)",
    "5-Lamp Tracer": "side running board (tracer)",
    "6-Lamp Tracer": "side running board (tracer)",
}

# Manual label -> part_type fixes where pattern matching can't reach.
MANUAL_MAP = {
    "Mirror Warning Brackets {n}": "mirror_warning_bracket",   # plural in workbook
    "Front Side Brackets": "front_side_bracket",
    "Radar Interface Cable (To Camera)": "radar_cable",        # renamed 2026-07-06 (cables plan)
}

def _is_placeholder(s: str) -> bool:
    """'SPECIFY LOCATION', 'SPECIFY LOACTION' (sic), 'SPECIFY DOOR(S)', … — the
    workbook's free-entry escape rows, not real vocabulary."""
    u = s.upper().strip()
    return u.startswith("SPECIFY") or u.startswith("SPECIFIY")


def base_label(label: str) -> str:
    """'Forward Warning 1' -> 'Forward Warning {n}'; 'FW 2 Bracket' -> 'FW {n} Bracket'.

    Only space-delimited digits are instance numbers — 'K-9 Kennel', '2-Lamp
    Tracer', and '12v Aux Ports' keep their digits.
    """
    return re.sub(r"(?<= )\d+(?= |$)", "{n}", label).strip()


def norm(s: str) -> str:
    """Loose key for pattern matching: casefold, drop non-alnum (keep {n})."""
    s = s.replace("{n}", "\x00")
    s = re.sub(r"[^a-z0-9\x00]", "", s.lower())
    return s.replace("\x00", "{n}")


def main() -> int:
    wb = json.loads((CFG / "workbook_rules.json").read_text("utf-8"))
    db = json.loads((CFG / "parts_db.json").read_text("utf-8"))
    legacy = json.loads((CFG / "legacy_workbook_index.json").read_text("utf-8"))

    products = db["products"]
    part_types = db["part_types"]
    placements = db["placements"]

    # -- workbook label pattern -> part_type_id (exact norm, then s-stripped) --
    pat_index: dict[str, str] = {}
    for ptid, pt in part_types.items():
        pat = pt.get("workbook_label_pattern")
        if pat:
            pat_index[norm(pat)] = ptid

    def map_part_type(base: str) -> tuple[str | None, str]:
        """Return (part_type_id, how)."""
        if base in MANUAL_MAP:
            return MANUAL_MAP[base], "manual"
        if base in SUPERSEDED_TO_WARNING:
            return "warning_light", "superseded"
        n = norm(base)
        if n in pat_index:
            return pat_index[n], "pattern"
        if n.endswith("s") and n[:-1] in pat_index:          # Panel(s) / plural
            return pat_index[n[:-1]], "pattern~plural"
        return None, "unmapped"

    # -- manufacturer label normalization: workbook name -> manufacturer_id --
    mfr_by_norm = {norm(m.get("label", "")): mid for mid, m in db["manufacturers"].items()}
    mfr_by_norm.setdefault(norm("Arctic Start"), "arcti_start")

    def map_mfr(wb_name: str) -> str | None:
        if _is_placeholder(wb_name):
            return None
        return mfr_by_norm.get(norm(wb_name))

    # -- sections: part name -> (section label, sub flag, order) --
    slot_section: dict[str, dict] = {}
    for sec in wb["template_sections"]:
        for i, part in enumerate(sec["parts"]):
            slot_section[part["name"]] = {"section": sec["label"], "sub": bool(part.get("sub")), "order": i}

    # -- group part_rules by base label --
    slots: dict[str, dict] = {}
    for label, rule in wb["part_rules"].items():
        base = base_label(label)
        s = slots.setdefault(base, {
            "instances": [], "rows": [], "manufacturers_raw": [], "models": [],
            "locations": [], "section": None, "sub": False,
        })
        s["instances"].append(label)
        if rule.get("_row") is not None:
            s["rows"].append(rule["_row"])
        for key, dst in (("manufacturer", "manufacturers_raw"), ("models", "models"),
                         ("locations", "locations")):
            for v in rule.get(key) or []:
                if v not in s[dst]:
                    s[dst].append(v)
        meta = slot_section.get(label)
        if meta:
            s["section"] = s["section"] or meta["section"]
            s["sub"] = s["sub"] or meta["sub"]

    # -- enrich + reconcile each slot --
    homed_by_pt: dict[str, list[str]] = defaultdict(list)
    for pid, p in products.items():
        for f in p.get("fits_part_types") or []:
            homed_by_pt[f].append(pid)

    legacy_l2p = legacy.get("part_type_to_products", {})
    legacy_m2p = legacy.get("model_string_to_product", {})

    confirmations, conflicts, gaps = [], [], []

    for base, s in slots.items():
        ptid, how = map_part_type(base)
        s["part_type_id"] = ptid
        s["mapping"] = how
        if how == "superseded":
            s["legacy_zone"] = SUPERSEDED_TO_WARNING[base]
        s["max_instances_in_template"] = len(s["instances"])

        # manufacturers -> ids + presence check
        mfr_ids, mfr_unknown = [], []
        for name in s["manufacturers_raw"]:
            mid = map_mfr(name)
            if mid:
                mfr_ids.append(mid)
            elif not _is_placeholder(name):
                mfr_unknown.append(name)
        s["manufacturer_ids"] = mfr_ids
        if mfr_unknown:
            s["manufacturers_unmatched"] = mfr_unknown

        if ptid and ptid in part_types:
            pt = part_types[ptid]
            homed = homed_by_pt.get(ptid, [])

            # location reconciliation
            wb_locs = [l for l in s["locations"] if not _is_placeholder(l)]
            if pt.get("location_mode") == "text":
                live = pt.get("location_options") or []
                s["loc_check"] = {
                    "mode": "text",
                    "confirmed": [l for l in wb_locs if l in live],
                    "workbook_only": [l for l in wb_locs if l not in live],
                    "parts_db_only": [l for l in live if l not in wb_locs],
                }
            else:
                s["loc_check"] = {
                    "mode": "placement",
                    "confirmed": [l for l in wb_locs if l in placements],
                    "workbook_only": [l for l in wb_locs if l not in placements],
                }

            # manufacturer reconciliation: who has a homed product on this pt
            present = {products[pid].get("manufacturer_id") for pid in homed}
            s["mfr_check"] = {
                "confirmed": [m for m in mfr_ids if m in present],
                "workbook_only": [m for m in mfr_ids if m not in present],
            }

            # model reconciliation via the legacy index
            mods_ok, mods_moved, mods_broken = [], [], []
            for m in s["models"]:
                if _is_placeholder(m):
                    continue
                pid = legacy_m2p.get(m)
                if pid and pid in products:
                    fits = products[pid].get("fits_part_types") or []
                    (mods_ok if ptid in fits else mods_moved).append(
                        m if ptid in fits else {"model": m, "product": pid, "now_fits": fits})
                else:
                    mods_broken.append({"model": m, "legacy_product": pid})
            s["model_check"] = {"confirmed": mods_ok, "re_homed": mods_moved, "unresolved": mods_broken}

            # roll-up: true conflicts (parts_db actively disagrees) vs gaps
            # (workbook knowledge not yet represented — curation will close most)
            s["flags"] = []
            if mods_moved:
                s["flags"].append("conflict:model-re-homed")
            if s["loc_check"].get("workbook_only"):
                s["flags"].append("gap:location-options")
            if s["mfr_check"]["workbook_only"]:
                s["flags"].append("gap:manufacturer-coverage")
            if mods_broken:
                s["flags"].append("gap:model-unresolved")
            if any(f.startswith("conflict") for f in s["flags"]):
                conflicts.append(base)
            elif s["flags"]:
                gaps.append(base)
            else:
                confirmations.append(base)
        else:
            s["flags"] = ["unmapped"]
            conflicts.append(base)          # no live home at all → needs a ruling

        s["legacy_products"] = legacy_l2p.get(s["instances"][0], [])

    graph = {
        "generated": "2026-07-07",
        "source": "workbook_rules.json v1.0 + legacy_workbook_index.json + parts_db.json",
        "counts": {
            "workbook_labels": len(wb["part_rules"]),
            "base_slots": len(slots),
            "mapped": sum(1 for s in slots.values() if s["part_type_id"]),
            "confirmed_clean": len(confirmations),
            "conflicts_need_ruling": len(conflicts),
            "gaps": len(gaps),
        },
        "sections": [{"label": sec["label"],
                      "parts": [p["name"] for p in sec["parts"]]}
                     for sec in wb["template_sections"]],
        "slots": slots,
        "manufacturer_models": _mfr_models(slots),
        "reconciliation": {"clean": sorted(confirmations),
                           "conflicts": sorted(conflicts),
                           "gaps": sorted(gaps)},
    }
    OUT_JSON.write_text(json.dumps(graph, indent=1), "utf-8")
    OUT_MD.write_text(render_md(graph), "utf-8")
    print(f"slots: {len(slots)}  mapped: {graph['counts']['mapped']}  "
          f"clean: {len(confirmations)}  conflicts: {len(conflicts)}  gaps: {len(gaps)}")
    print(f"→ {OUT_JSON.relative_to(REPO)}\n→ {OUT_MD.relative_to(REPO)}")
    return 0


def _mfr_models(slots: dict) -> dict:
    """Invert: manufacturer -> the slots (part types) the workbook offered them for."""
    inv: dict[str, list[str]] = defaultdict(list)
    for base, s in slots.items():
        for mid in s.get("manufacturer_ids") or []:
            if base not in inv[mid]:
                inv[mid].append(base)
    return dict(sorted(inv.items()))


def render_md(g: dict) -> str:
    L: list[str] = []
    A = L.append
    c = g["counts"]
    A("# Workbook Relationship Graph — human summary\n")
    A(f"Generated {g['generated']} by `tools/curation/build_workbook_graph.py` "
      f"(re-runnable). Machine form: `workbook_graph.json`.\n")
    A(f"**{c['workbook_labels']} workbook labels → {c['base_slots']} base slots** · "
      f"{c['mapped']} mapped to live part_types · {c['confirmed_clean']} fully clean · "
      f"{c['conflicts_need_ruling']} conflicts (need your ruling) · {c['gaps']} with gaps "
      f"(workbook knowledge not yet in parts_db — Phase 3 curation closes most).\n")

    def emit_slot(b: str) -> None:
        s = g["slots"][b]
        A(f"\n### {b} → `{s['part_type_id']}` ({s['mapping']})")
        if s.get("legacy_zone"):
            A(f"- legacy zone: {s['legacy_zone']} (now decided by placement)")
        lc = s.get("loc_check") or {}
        if lc.get("workbook_only"):
            A(f"- locations in workbook, absent in parts_db ({lc['mode']} mode): "
              f"{lc['workbook_only']}")
        mc = s.get("mfr_check") or {}
        if mc.get("workbook_only"):
            A(f"- workbook manufacturers with **no homed product** on this part_type: "
              f"{mc['workbook_only']}")
        mo = s.get("model_check") or {}
        if mo.get("re_homed"):
            A(f"- **models whose product moved to another home**: {mo['re_homed']}")
        if mo.get("unresolved"):
            A(f"- model strings that no longer resolve: "
              f"{[m['model'] for m in mo['unresolved']]}")

    A("\n## Conflicts — workbook says X, parts_db says Y (rulings needed)\n")
    for b in g["reconciliation"]["conflicts"]:
        emit_slot(b)

    A("\n## Gaps — workbook knowledge not yet represented (expected to close via curation)\n")
    for b in g["reconciliation"]["gaps"]:
        emit_slot(b)

    A("\n## Clean confirmations\n")
    A(", ".join(f"`{b}`" for b in g["reconciliation"]["clean"]) or "(none)")

    A("\n\n## Manufacturer ↔ slot matrix (what the workbook sold from whom)\n")
    for mid, bases in g["manufacturer_models"].items():
        A(f"- **{mid}**: {', '.join(bases)}")

    A("\n\n## Sections (build-sheet order, template rev at freeze)\n")
    for sec in g["sections"]:
        A(f"- **{sec['label']}**: {', '.join(sec['parts'])}")
    A("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
