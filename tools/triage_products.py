"""Triage no-home products: propose part_type + tags from their QB descriptions.

For every product with no part-type home (the QB-import queue), match its QB
description against an ordered keyword ruleset to propose a fits_part_types home,
a light tag where the description implies a light, and a confidence tier so the
owner can bulk-apply the confident ones and hand-curate the rest.

Confidence:
  high   — a specific, unambiguous keyword hit (CONSOLE, GUN LOCK, FACEPLATE…).
  medium — a category hit that's plausibly right but worth a glance (generic
           bracket/mount/pocket, ambiguous light type).
  low    — weak/none; left for manual (trailers, foam, cables, misc).

Writes tools/triage_products.json (the full proposal) and prints a report.
``--write`` applies ONLY the high-confidence proposals via save_config_file.

Usage:
  python tools/triage_products.py                 # dry run + report
  python tools/triage_products.py --tier medium   # also show medium detail
  python tools/triage_products.py --write         # apply HIGH-confidence only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
OUT = REPO / "tools" / "triage_products.json"

# ── Ruleset ──────────────────────────────────────────────────────────────────
# (regex, part_type_id, confidence, note). First match wins. Ordered most
# specific → most generic. part_type_id must exist in parts_db.
RULES: list[tuple[str, str, str, str]] = [
    # ---- weapons / gun locks (santa_cruz) — brackets before bare locks ----
    (r"GUN ?LOCK BRACKET|OVER ?HEAD.*GUN ?LOCK|GUN ?LOCK.*BRACKET", "gun_lock_bracket", "high", "gun-lock bracket"),
    (r"\b(MUZZLE|BUTT PLATE|INSERT FOR .*GUNLOCK|GUN LOCK SOLENOID|SOLENOID|BARREL KEY|#\w* ?KEY|KEY OVERRIDE|MAGNET RESISTANT|FLAT BAR|RACK UPRIGHT)", "gun_lock_bracket", "medium", "gun-lock part/accessory"),
    (r"\b(GUN ?LOCK|GUNLOCK|SHOTGUN LOCK|WEAPON BARREL|RIFLE LOCK|UNIVERSAL GUN)", "gun_lock", "high", "gun lock"),
    # ---- console-area accessories (specific) BEFORE the bare CONSOLE rule ----
    (r"FACE ?PLATE", "special_face_plate", "high", "faceplate"),
    (r"ARM ?REST|ARMREST", "arm_rest", "high", "armrest"),
    (r"DOCKING STATION|LAPTOP DOCK|COMPUTER CRADLE|\bNOTEPAD\b|LAPTOP MOUNT|SMARTPHONE DOCK|TABLET CRADLE", "docking_station", "high", "docking/cradle"),
    (r"PRINTER.*(MOUNT|BRACKET)|ARM ?REST PRINTER|PRINTER.*ARMREST", "printer_mount", "high", "printer mount"),
    (r"POCKET|FILLER (PANEL|PLATE)|BLANK.*PANEL|KNOCKOUT|BASE PLATE|UPPER POLE|LOWER POLE|SUPPORT BRACE|SKID ?E? ARM|CLEVIS|\bWINGS?\b|FILLER PLATE|MONGOOSE|LEG KIT", "bracket", "medium", "console component/bracket"),
    # ---- console body itself (after its accessories) ----
    (r"ENCLOSED CONSOLE|CONSOLE BOX|CONSOLE BODY|\bCONSOLE\b", "console", "high", "console"),
    # ---- radar / radios / cameras ----
    (r"RADAR (DISPLAY|DISPLAY UNIT|COUNTING)|\bDSR\b", "radar_display_unit", "medium", "radar display"),
    (r"THERMAL", "thermal_imager", "medium", "thermal imager"),
    (r"\b(\d+\") ?SCREEN|MONITOR\b", "thermal_imager_monitor", "low", "monitor (verify)"),
    # ---- preemption ----
    (r"PREEMPTION|OPTICOM|\bGTT\b|MICRO DASH PREEMPT", "preemption", "high", "preemption"),
    # ---- siren / howler / speaker ----
    (r"HOWLER", "howler", "high", "howler"),
    (r"SIREN SPEAKER|SPEAKER.*SIREN|\bSPEAKER\b.*(100W|SA3|SAK)|SIREN/CONTROL|SIREN AMPLIFIER", "siren_speaker", "medium", "siren/speaker"),
    (r"V2V|VEHICLE.?TO.?VEHICLE SYNC", "v2v_sync", "high", "V2V sync"),
    # ---- lights: bars / interior / traffic ----
    (r"UNDERCOVER LIGHTBAR|UNDERCOVER LIGHT BAR|INTERIOR .*LIGHT ?BAR|8 HEAD INTERIOR|INTERIOR TRAFFIC", "front_interior_light_bar", "medium", "interior light bar"),
    (r"\d{2}\".*(LEGACY|LIGHTBAR|LIGHT BAR)|LEGACY (48|54)|FULL SIZE.*BAR|\bLIGHTBAR\b", "roof_light_bar", "medium", "roof light bar / accessory"),
    (r"TRAFFIC CONTROLLER|TRAFFIC ADVISOR|8 HEAD EXTERIOR|ARROW", "rear_warning", "low", "traffic advisor (verify)"),
    (r"ALLEY|TAKE.?DOWN", "bar_takedown", "medium", "take-down/alley"),
    # ---- lights: heads / surface warning ----
    (r"FASCIA LIGHT|GRILLE MOUNT LIGHT|DECK.*MOUNT LIGHT|NFORCE SINGLE|STUD MOUNT.*(RED|BLUE|WHITE|AMBER)|MPOWER.*(FASCIA|STUD)|SURFACE MOUNT.*(RED|BLUE|WHITE|LIGHT)|UTILITY STRIP LIGHT", "front_side_warning", "medium", "surface/fascia warning light"),
    (r"LIGHTHEAD|\bLAMPS?\b|\bLED DUO\b|MIRROR.?BEAM|OUTER EDGE LIGHTHEAD", "lighthead", "medium", "lighthead"),
    (r"FLASHER", "headlight_flasher", "low", "flasher (headlight vs tail — verify)"),
    (r"ENDCAP|LENS KIT|LENSE KIT|SMOKED LENS|MIDNIGHT EDITION|BAIL BRACKET|INSTALLATION KIT|MOUNT KIT|POWER SUPPLY|FIELD SERIES|SYNC MODULE", "bracket", "low", "light bar accessory/kit (verify)"),
    # ---- structural ----
    (r"PARTITION.*(REAR|POLY|STEEL|RECESSED)|REAR PARTITION", "rear_partition", "medium", "rear partition"),
    (r"PARTITION|PRISONER PARTITION|CARGO BARRIER", "front_partition", "medium", "partition"),
    (r"PUSH BUMPER|\bPB\d+\b", "push_bumper", "medium", "push bumper"),
    (r"SEAT COVER", "seat_covers", "high", "seat covers"),
    (r"REPLACEMENT SEAT|REAR SEAT REPLACEMENT|PRISONER SEAT|\bTPO\b SEAT", "replacement_rear_seat", "medium", "replacement seat"),
    (r"WINDOW BAR|WINDOW BARRIER|WINDOW GUARD", "rear_window_bars", "medium", "window bars"),
    (r"FLOOR (PAN|LINER)|\bPAN\b", "floor_pan", "low", "floor pan (verify)"),
    (r"STORAGE (BOX|VAULT|DRAWER)|\bVAULT\b|TUFBOX|CARGO BOX", "storage_box", "medium", "storage box"),
    # ---- extras ----
    (r"FLOOR MAT|CARGO MAT|ALL WEATHER MAT", "floor_mats", "high", "floor mats"),
    (r"\bDECAL|GRAPHIC|REFLECTIVE|CHEVRON", "decals", "medium", "decals"),
    (r"WINDOW TINT|\bTINT\b", "window_tint", "high", "window tint"),
    (r"\bHARNESS\b|WIRE HARNESS|\bWIRING\b", "harness", "medium", "harness"),
    # ---- ballistic / armor ----
    (r"BALLISTIC|LEVEL 3A|LEVEL 3\+|BULLET.?PROOF", "bullet_proof_door_panel", "medium", "ballistic panel (door vs window — verify)"),
    # ---- power / charging ----
    (r"AUTO ?EJECT", "auto_eject", "high", "auto eject"),
    (r"BATTERY (CHARGER|MAINTAINER|TENDER|CONDITIONER)|\bMAINTAINER\b", "battery_tender", "high", "battery charger/tender"),
    # ---- K9 (before siren/thermal) ----
    (r"HEAT ALARM|HOT.?N.?POP|NO K.?9 LEFT|DOOR POPPER", "k9_heat_alarm_popper", "high", "k9 heat alarm"),
    (r"COLLAPSIBLE CRATE|\bCRATE\b|K.?9 (KENNEL|CRATE|TRANSPORT)|KENNEL|DOG (BOX|INSERT)", "k9_kennel", "medium", "k9 crate/kennel"),
    # ---- radio / mic / cable / antenna (cables before antenna) ----
    (r"MIC CLIP|MAGNETIC MIC", "radio_mic_clip", "medium", "mic clip"),
    (r"MIC EXTENSION|COMM(UNICATION)? CABLE|DATA CABLE|MOBILE MIC|DISPLAY CABLE|REMOTE.*CABLE|INTERFACE CABLE|ANTENNA CABLE|RADIO.*CABLE", "radar_interface_cable", "medium", "radio/data/interface cable"),
    (r"ANTENNA", "radio_antenna_top", "medium", "antenna"),
    (r"\bCABLE\b|\bCORD\b|\bHDMI\b|ETHERNET|\bUSB\b|POWER CABLE", "cable", "low", "cable"),
    # ---- storage / drawers ----
    (r"DRAWER|STORAGE (BOX|VAULT|DRAWER|CABINET)|\bVAULT\b|CABINET|DECKED|CARGO BOX|TUFBOX|ACCESSORY BOX", "rear_storage_box", "medium", "storage/drawer"),
    # ---- siren / amp ----
    (r"\bSIREN\b|REMOTE SIREN|SIREN CONTROLLER|\bAMPLIFIER\b|SIREN AMP", "siren_speaker", "medium", "siren/amp (verify)"),
    # ---- thermal / night vision ----
    (r"THERMAL|NIGHT ?VISION|NIGHTRIDE|PRO-SL|INFRARED|FLIR", "thermal_imager", "medium", "thermal/night vision"),
    # ---- vehicle modules ----
    (r"BLACK ?OUT|OBD.*MODULE|DATA MODULE|INTERFACE MODULE|IGNITION.*MODULE", "vehicle_interface", "medium", "vehicle module"),
    # ---- generic mount/holder ----
    (r"RAM MOUNT|BALL BASE|SOCKET ARM|\bVESA\b|CUP HOLDER|MAG CLIP", "bracket", "medium", "generic mount/holder"),
    # ---- generic bracket/mount catch-all (last) ----
    (r"BRACKET|\bMOUNT\b|MOUNTING|\bKIT\b", "bracket", "medium", "generic bracket/mount"),
]

# Light-tag signal (independent of part_type): color combos, LED, light words.
_LIGHT_RE = re.compile(
    r"\b(R/W|B/W|R/B|RED/WHITE|BLUE/WHITE|RED/AMBER|BLUE/AMBER|AMBER/WHITE"
    r"|\bLED\b|LIGHTHEAD|FASCIA|BEACON|WARNING LIGHT|SCENE LIGHT|STROBE|LIGHTBAR"
    r"|\bLAMP|SUPER-?LED|TRACER|FLASHER)\b")


def _light_tag_id(pdb: dict) -> str:
    for tid, t in (pdb.get("tags") or {}).items():
        if tid == "light" or (t.get("label") or "").strip().lower() == "light":
            return tid
    return "light"


def classify(desc: str, model: str) -> dict | None:
    hay = f"{desc} {model}".upper()
    for pat, ptid, conf, note in RULES:
        if re.search(pat, hay):
            is_light = bool(_LIGHT_RE.search(hay))
            return {"part_type_id": ptid, "confidence": conf, "note": note, "light": is_light}
    # No part_type but still clearly a light → medium light-only
    if _LIGHT_RE.search(hay):
        return {"part_type_id": "lighthead", "confidence": "low", "note": "light, type unclear", "light": True}
    return None


def build(pdb: dict) -> list[dict]:
    pts = pdb.get("part_types") or {}
    out = []
    for pid, p in (pdb.get("products") or {}).items():
        if p.get("fits_part_types"):
            continue
        desc = next((pn.get("friendly_name") for pn in p.get("part_numbers", []) if pn.get("friendly_name")), "")
        model = p.get("model", "")
        res = classify(desc, model)
        row = {"product_id": pid, "model": model, "manufacturer_id": p.get("manufacturer_id", ""),
               "desc": desc}
        if res and res["part_type_id"] in pts:
            # Only tag as light when the assigned home is actually a lights-type
            # part_type (avoids tagging e.g. a V2V module that merely says "lightbar").
            res["light"] = bool(res.get("light")) and pts[res["part_type_id"]].get("type_id") == "lights"
            row.update(res)
        else:
            row.update({"part_type_id": None, "confidence": "none", "note": "no rule matched", "light": False})
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="apply HIGH-confidence proposals")
    ap.add_argument("--tier", default="high", choices=["high", "medium", "low", "none", "all"])
    args = ap.parse_args()

    pdb = json.loads(PARTS_DB.read_text("utf-8"))
    rows = build(pdb)
    OUT.write_text(json.dumps(rows, indent=1), "utf-8")

    by_conf = Counter(r["confidence"] for r in rows)
    print(f"no-home products: {len(rows)}  →  "
          + " · ".join(f"{k}: {by_conf.get(k,0)}" for k in ("high", "medium", "low", "none")))
    lights = sum(1 for r in rows if r.get("light"))
    print(f"flagged as light: {lights}")

    # Per-tier part_type distribution
    for tier in (["high", "medium", "low", "none"] if args.tier == "all" else [args.tier]):
        sel = [r for r in rows if r["confidence"] == tier]
        if not sel:
            continue
        print(f"\n===== {tier.upper()} ({len(sel)}) =====")
        byp = defaultdict(list)
        for r in sel:
            byp[r["part_type_id"]].append(r)
        for ptid, items in sorted(byp.items(), key=lambda kv: -len(kv[1])):
            print(f"  → {ptid or '(none)'}  ({len(items)}){'  [light]' if items[0].get('light') else ''}")
            for r in items[:6]:
                print(f"       {r['model'][:38]:38s} | {r['desc'][:52]}")
            if len(items) > 6:
                print(f"       … +{len(items)-6} more")

    if not args.write:
        print(f"\nfull proposal → {OUT.relative_to(REPO)}")
        print("(dry run — re-run with --write to apply HIGH-confidence proposals)")
        return 0

    # Apply high-confidence: set fits_part_types + light tag.
    light_id = _light_tag_id(pdb)
    applied = 0
    for r in rows:
        if r["confidence"] != "high" or not r["part_type_id"]:
            continue
        p = pdb["products"][r["product_id"]]
        p["fits_part_types"] = [r["part_type_id"]]
        if r.get("light"):
            tags = p.setdefault("tag_ids", [])
            if light_id not in tags:
                tags.append(light_id)
        applied += 1

    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.paths import AppPaths
    res = save_config_file("parts_db.json", pdb, AppPaths())
    if not res.get("ok"):
        print(f"Save failed: {res.get('error')}", file=sys.stderr)
        return 3
    print(f"\n✓ applied {applied} high-confidence homes "
          f"({'queued' if res.get('queued') else 'saved'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
