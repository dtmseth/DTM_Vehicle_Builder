#!/usr/bin/env python3
"""Phase 3 migration: workbook_rules + parts_library + vehicle_layouts → parts_db.json (v2).

One-shot script. Reads the four legacy config files and emits two artifacts:

  - parts_db.json              — the new tree+rules-based canonical DB (schema_version 2)
  - legacy_workbook_index.json — string-keyed transition map for the
                                  manifest_editor + excel_reader fallback

Plus an orphans.md report listing every datum the script could not place into
the new schema without owner input. The script refuses --write while orphans
exist — owner edits the hand-tables in this file (or fixes upstream data),
re-runs --dry-run, repeats until clean.

Owner-editable inputs (hand-tables at the top of this file):

  PLACEMENT_LOCATION_TO_ZONE     ~56 entries — physical location → light placement_zone
  MODEL_MANUFACTURER             ~165 entries — model string → manufacturer slug
  WORKBOOK_PART_TYPE_GROUPS      ~90 entries — regex match → part_type with tree position

Plus the static taxonomies (Types, Sections, Zones, Sub-zones, Build Attributes,
Tags, Services, Preference Filters) defined directly below the imports.

Usage:
  tools/migrate_workbook_to_parts_db.py --dry-run
  tools/migrate_workbook_to_parts_db.py --write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "src" / "dtm_buildsheet" / "resources" / "config"

INPUT_WORKBOOK_RULES = CONFIG_DIR / "workbook_rules.json"
INPUT_PARTS_LIBRARY = CONFIG_DIR / "parts_library.json"
INPUT_VEHICLE_LAYOUTS = CONFIG_DIR / "vehicle_layouts.json"
INPUT_PART_CATALOG = CONFIG_DIR / "part_catalog.json"

OUTPUT_PARTS_DB = CONFIG_DIR / "parts_db.json"
OUTPUT_LEGACY_INDEX = CONFIG_DIR / "legacy_workbook_index.json"

UNKNOWN = "???"


# ═════════════════════════════════════════════════════════════════════════════
# STATIC TAXONOMIES — the structure that doesn't come from workbook data
# ═════════════════════════════════════════════════════════════════════════════


# ── Top-level Types (5) ──────────────────────────────────────────────────────
TYPES: dict[str, dict] = {
    "extras":     {"label": "Extras"},
    "structural": {"label": "Structural"},
    "equipment":  {"label": "Equipment"},
    "lights":     {"label": "Lights"},
    "k9":         {"label": "K-9", "requires_attribute": "has_k9"},
}

# ── Sections (2) ─────────────────────────────────────────────────────────────
SECTIONS: dict[str, dict] = {
    "exterior": {"label": "Exterior"},
    "interior": {"label": "Interior"},
}

# ── Zones (8) ────────────────────────────────────────────────────────────────
ZONES: dict[str, dict] = {
    # Exterior
    "front":             {"label": "Front",            "section": "exterior"},
    "rear":              {"label": "Rear",             "section": "exterior"},
    "side":              {"label": "Side",             "section": "exterior"},
    "roof":              {"label": "Roof",             "section": "exterior"},
    # Interior
    "forward_of_cage":   {"label": "Forward of Cage",  "section": "interior"},
    "prisoner_area":     {"label": "Prisoner Area",    "section": "interior",
                          "requires_attribute": "has_prisoner_compartment"},
    "side_storage":      {"label": "Side Storage",     "section": "interior",
                          "requires_attribute": "has_side_storage"},
    "rear_storage_area": {"label": "Rear Storage Area", "section": "interior"},
}

# ── Sub-zones (2) — physical containers that hold other parts ───────────────
SUB_ZONES: dict[str, dict] = {
    "console":        {"label": "Console", "zone": "forward_of_cage",
                       "requires_attribute": "has_console"},
    "equipment_tray": {"label": "Equipment Tray", "zone": "rear_storage_area",
                       "requires_attribute": "has_equipment_tray"},
}

# ── Build Attributes ─────────────────────────────────────────────────────────
BUILD_ATTRIBUTES: dict[str, dict] = {
    "has_k9": {
        "label": "K-9 Vehicle",
        "default_by_build_type": {"K-9": True},
    },
    "has_prisoner_compartment": {
        "label": "Has Prisoner Compartment",
        "default_by_build_type": {"Patrol": True, "K-9": False, "Admin": False, "Unmarked": True},
    },
    "has_side_storage": {
        "label": "Has Side Storage",
        "default_by_build_type": {},
    },
    "has_console": {
        "label": "Has Console",
        "default_by_build_type": {"Patrol": True, "K-9": True, "Admin": True, "Unmarked": True},
    },
    "has_equipment_tray": {
        "label": "Has Equipment Tray",
        "default_by_build_type": {"Patrol": True, "K-9": True, "Admin": False, "Unmarked": True},
    },
}

# ── Tags (4 themes) ──────────────────────────────────────────────────────────
TAGS: dict[str, dict] = {
    "camera": {"label": "Camera"},
    "radar":  {"label": "Radar"},
    "siren":  {"label": "Siren"},
    "comms":  {"label": "Communications"},
}

# ── Services (not parts — line items the customer wants) ─────────────────────
SERVICES: dict[str, dict] = {
    "graphics":            {"label": "Graphics / Decals"},
    "pickup_delivery":     {"label": "Pickup / Delivery"},
    "shipping":            {"label": "Shipping Services"},
    "vehicle_acquisition": {"label": "Vehicle Acquisition"},
    "vehicle_trade_in":    {"label": "Vehicle Trade-In"},
}

# ── Preference filters ───────────────────────────────────────────────────────
PREFERENCE_FILTERS: dict[str, dict] = {
    "lighting_brand": {
        "preference_field":   "preferences.lighting",
        "filter_scope_kind":  "type_id",
        "filter_scope_values": ["lights"],
        "filter_action":      "restrict_to_manufacturer",
    },
    "bumper_brand": {
        "preference_field":   "preferences.bumper",
        "filter_scope_kind":  "part_type_ids",
        "filter_scope_values": ["push_bumper", "pit_bar", "wing_wraps"],
        "filter_action":      "restrict_to_manufacturer",
    },
    "cage_brand": {
        "preference_field":   "preferences.cage",
        "filter_scope_kind":  "part_type_ids",
        "filter_scope_values": ["cage", "front_partition", "rear_partition",
                                "rear_seat_divider", "floor_pan",
                                "replacement_rear_seat", "k9_kennel"],
        "filter_action":      "restrict_to_manufacturer",
    },
    "camera_brand": {
        "preference_field":   "preferences.camera",
        "filter_scope_kind":  "tag_ids",
        "filter_scope_values": ["camera"],
        "filter_action":      "restrict_to_manufacturer",
    },
}

# ── Light placement zones (kept distinct from tree zones above) ─────────────
# Used by workbook label sequencing + light part-type derivation for the
# legacy workbook import path. Note: `roof` is shared with tree zones.
PLACEMENT_ZONES: dict[str, dict] = {
    "primary_front": {"label": "Primary Front"},
    "front_corner":  {"label": "Front Corner"},
    "front_side":    {"label": "Front Side"},
    "side":          {"label": "Side"},
    "rear_side":     {"label": "Rear Side"},
    "rear_corner":   {"label": "Rear Corner"},
    "rear":          {"label": "Rear"},
    "rear_interior": {"label": "Rear Interior"},
    "interior":      {"label": "Interior"},
    "roof":          {"label": "Roof"},
}

# ── Per-placement allowed_products restrictions ──────────────────────────────
# Each entry adds a `allowed_products` whitelist to the placement metadata.
# Locations not listed here have no product restriction.
PLACEMENT_RESTRICTIONS: dict[str, list[str]] = {
    # Twist-locks only fit VXE / Vertex
    "HEADLIGHT_TWIST_LOCK": ["whelen_vxe", "whelen_vertex"],
    "TAILLIGHT_TWIST_LOCK": ["whelen_vxe", "whelen_vertex"],
    # Roof light-bar mount only accepts Arges spotlights
    "LIGHTBAR_MOUNT":       ["arges_arges_control_head"],   # owner: refine product slug
}


# ═════════════════════════════════════════════════════════════════════════════
# Hand-table 1: PLACEMENT_LOCATION_TO_ZONE
# Maps physical vehicle locations to light placement_zone (NOT tree zone).
# Drives workbook label sequencing for warning/scene lights.
# ═════════════════════════════════════════════════════════════════════════════

PLACEMENT_LOCATION_TO_ZONE: dict[str, str] = {
    # Primary front
    "GRILL":                 "primary_front",
    "IN GRILL":              "primary_front",
    "LOWER GRILL":           "primary_front",
    "BEHIND GRILL (CENTER)": "primary_front",
    "TOP TUBE":              "primary_front",
    "CENTER PLATE OF PB":    "primary_front",
    "TOP OF PUSH BUMPER":    "primary_front",
    "SIDE OF PUSH BUMPER":   "primary_front",
    "UNDER PUSH BUMPER":     "primary_front",
    "PUSH BUMPER":           "primary_front",
    "PUSH BUMPER MOUNT":     "primary_front",
    "BEHIND OEM BUMPER":     "primary_front",
    "HEADLIGHT TWIST-LOCK":  "primary_front",   # new clean name
    "HEADLIGHT CUT OUTS":    "primary_front",   # legacy name in vehicle_layouts.json — rename upstream in Phase 4
    "FOG LIGHT AREA":        "primary_front",
    "PIT BARS":              "primary_front",
    "UPPER WINDSHIELD":      "primary_front",

    # Front corner / front side
    "FRONT CORNER OF BUMPER":  "front_corner",
    "FRONT OF MIRROR":         "front_side",
    "UNDER MIRROR":            "front_side",
    "LEFT FRONT FENDER":       "front_side",
    "RIGHT FRONT FENDER":      "front_side",
    "LEFT AND RIGHT FENDER":   "front_side",
    "PILLARS":                 "front_corner",
    "UPPER DRIVER AND PASSENGER": "primary_front",

    # Side
    "ON RUNNING BOARD":   "side",
    "ROCKER PANEL":       "side",

    # Rear
    "ABOVE LICENSE PLATE":   "rear",
    "LICENSE PLATE BRACKET": "rear",
    "TAIL LIGHTS":           "rear",
    "TAILLIGHT TWIST-LOCK":  "rear",            # new
    "REAR BUMPER":           "rear",
    "LOWER LIFTGATE LIP":    "rear",
    "ON TAILGATE/LIFTGATE":  "rear",
    "UNDER TAILGATE":        "rear",
    "REAR LEFT ROOF":        "rear",

    # Rear side / rear interior
    "REAR DOOR WINDOW":         "rear_side",
    "LOWER CARGO WINDOW":       "rear_interior",
    "UPPER CARGO WINDOW":       "rear_interior",
    "UPPER REAR WINDOW":        "rear_interior",
    "REAR INTERIOR LIGHT BAR":  "rear_interior",

    # Interior
    "INTERIOR LIGHT BAR (FRONT)": "interior",
    "CENTER OF DASH":             "interior",
    "ON DASH":                    "interior",
    "LEFT ON DASH":               "interior",
    "HEADLINER":                  "interior",

    # Roof
    "IN LIGHT BAR":               "roof",
    "LIGHTBAR MOUNT":             "roof",
    "ON ROOF":                    "roof",
    "ROOF":                       "roof",
    "ROOF CENTER":                "roof",
    "ROOF LIGHT BAR":             "roof",

    # Meta / sentinel — no placement zone
    "SPOT LIGHT MOUNT":            "",
    "ON SPECIFIC BRACKET":         "",
    "PASSENGER SIDE ONLY":         "",
    "SPECIFY LOCATION":            "",
    "VEHICLE SPECIFIC BRACKET":    "",
    "VEHICLE SPECIFIC BRACKET(S)": "",
}


# ═════════════════════════════════════════════════════════════════════════════
# Hand-table 2: MODEL_MANUFACTURER
# When neither workbook_rules nor parts_library reveals a model's
# manufacturer, owner fills in the slug here. Every entry below was
# owner-reviewed (or marked # ? for owner to confirm during PR review).
# ═════════════════════════════════════════════════════════════════════════════

MODEL_MANUFACTURER: dict[str, str] = {
    # Pre-seed known mappings
    "ION":           "whelen",
    "T-ION":         "whelen",
    "MEGA ION":      "whelen",
    "LPRL":          "whelen",
    "VERTEX":        "whelen",
    "MPOWER":        "soundoff",
    "MPOWER 6 FACE": "soundoff",
    "MPOWER FASCIA": "soundoff",
    "MPOWER 12 FACE": "soundoff",
    "PB400":         "setina",
    "PB450L":        "setina",
    "PB450L2":       "setina",
    "HDX":           "pro_gard",
    "PIT ULTRA":     "westin",

    # Whelen lighting
    "2 LAMP TRACER":       "whelen",
    "TRACER 5 LAMP":       "whelen",
    "TRACER 6 LAMP":       "whelen",
    "TRACER L BRACKETS X2 PER": "whelen",
    "T-SERIES":            "whelen",
    "T-SERIES ION":        "whelen",
    "MEGA T-SERIES":       "whelen",
    "MINI T-SERIES":       "whelen",
    "T-IONS W/SHORUD":     "whelen",
    "STANDARD MOUNT ION":  "whelen",
    "SURFACE MOUNT ION":   "whelen",
    "INNER EDGE":          "whelen",
    "MICRO PULSE":         "whelen",
    "MIRROR BEAMS":        "whelen",
    "U-SERIES":            "whelen",
    "INTERSECTORS":        "whelen",
    "VXE":                 "whelen",
    "9X EDGE":             "whelen",
    "PIONEER":             "whelen",
    "FIELD SERIES":        "whelen",
    "FREEDOM":             "whelen",
    "LEGACY":              "whelen",
    "LIBERTY":             "whelen",
    "JUSTICE":             "whelen",
    "CENATOR":             "whelen",
    "CCTL5":               "whelen",
    "CCTL6":               "whelen",
    "CCTL7":               "whelen",
    "CCTL8":               "whelen",
    "CCTL9":               "whelen",
    "CEM8":                "whelen",
    "CEM16":               "whelen",
    "CEM24":               "whelen",
    "CORE":                "whelen",
    "CORE CONTROL HEAD":   "whelen",
    "BLUEPRINT":           "whelen",
    "FLASHED WITH CORE":   "whelen",
    "AM-900":              "whelen",
    "LC HOWLER":           "whelen",
    "WC HOWLER":           "whelen",
    "WCX HOWLER":          "whelen",
    "SA315P":              "whelen",
    "SA315U":              "whelen",
    "SAK1":                "whelen",
    "SAK9":                "whelen",
    "RST":                 "whelen",
    "FST":                 "whelen",
    "XLP":                 "whelen",

    # SoundOff
    "M-POWER":             "soundoff",
    "NFORCE":              "soundoff",
    "N-FORCE":             "soundoff",
    "M4":                  "soundoff",

    # Federal Signal
    "AVENGER X1":          "federal_signal",
    "AVENGER X2":          "federal_signal",

    # Setina
    "TPO":                 "setina",
    "CARGO MAXX":          "setina",
    "BOARD":               "setina",
    "EQUIPMENT TRAY":      "setina",
    "EQUIPMENT DRAWER":    "setina",
    "EQUIMPENT BOX":       "setina",
    "REPLACEMENT FLOOR":   "setina",
    "FULL PARTITION":      "setina",
    "FULL XL PARTITION":   "setina",
    "PASSENGER SIDE XL PARTITION": "setina",
    "SINGLE PRISIONER":    "setina",
    "POLY DIVIDER":        "setina",
    "POLY WINDOW":         "setina",
    "STEEL WINDOW":        "setina",

    # Pro-Gard
    "POLY FLOOR PAN":            "pro_gard",
    "POLY FLOOR PAN W/ DRAINS":  "pro_gard",
    "POLY SEAT COVER":           "pro_gard",
    "FULL REPLACMENT SEAT W/ CENTER PULL SEAT BELTS": "pro_gard",
    "HEAT ALARM AND DOOR POPPER": "pro_gard",
    "HEAT ALARM ONLY":           "pro_gard",

    # Ace K-9
    "ACE K-9":             "ace_k_9",
    "ULTIMATE":            "ace_k_9",
    "ULTIMATE II":         "ace_k_9",
    "FULL PLATFORM":       "ace_k_9",
    "2/3 1/2 PASS EXIT":   "ace_k_9",
    "2/3 1/3 DRIVER EXIT": "ace_k_9",

    # Pro-Gard gun racks
    "DUAL HANDCUFF":         "pro_gard",
    "DUAL SHOT GUN":         "pro_gard",
    "HANDCUFF AND SHOT GUN": "pro_gard",
    "SINGLE HANDCUFF":       "pro_gard",
    "SINGLE SHOT GUN":       "pro_gard",

    # Santa Cruz
    "DUAL T-RAIL":             "santa_cruz",
    "SINGLE T-RAIL":           "santa_cruz",
    "FRONT OVERHEAD BRACKETS": "santa_cruz",
    "REAR OVERHEAD BRACKETS":  "santa_cruz",

    # Havis
    "UNIVERSAL":           "havis",
    "VEHICLE SPECIFIC":    "havis",
    "7\"\" SCREEN":        "havis",
    "8\"\" SCREEN":        "havis",
    "9\"\" SCREEN":        "havis",
    "9\"\" MONGOOSE":      "havis",
    "9\"\" XE":            "havis",
    "PRINTER ARM REST":    "havis",
    "SIDE ARM REST":       "havis",
    "STANDARD ARM REST":   "havis",
    "3.5\"\" POCKET":      "havis",
    "6\"\" POCKET":        "havis",

    # Watchguard / Axon
    "WATCHGUARD DVR":      "watchguard",
    "4RE":                 "watchguard",
    "M500":                "watchguard",
    "FLEET 2":             "axon",
    "FLEET 3":             "axon",

    # Angel Armor
    "LEVEL 3+(RIFLE)":     "angel_armor",
    "LEVEL 3A (HANDGUN)":  "angel_armor",

    # Cradlepoint
    "FIRST NET ROOF MOUNT":   "cradle_point",
    "FIRST NET WINDOW MOUNT": "cradle_point",
    "VERIZON ROOF MOUNT":     "cradle_point",
    "VERIZON WINDOW MOUNT":   "cradle_point",
    "ROOF MOUNT":             "cradle_point",
    "WINDOW MOUNT":           "cradle_point",

    # Motorola
    "MOTORAOLA XTL":   "motorola",
    "ALL IN ONE UNIT": "motorola",
    "SPLIT UNIT":      "motorola",

    # Arges
    "ARGES CONTROL HEAD": "arges",

    # Westin push bumper accessories
    "PIT BARS":            "westin",
    "WING WRAPS":          "westin",
    "WESTIN 2 LIGHT TUBE": "westin",
    "WESTIN 4 LIGHT TUBE": "westin",

    # DTM custom
    "DTM EXTENDED CARGO WINDOW BRACKET": "dtm",
    "UNIVERSAL GRILL BRACKET":           "dtm",

    # Generic / material descriptors
    "POLY":                "setina",
    "POLY TINTED":         "setina",
    "STEEL":               "setina",
    "STEEL HORIZONTAL":    "setina",
    "STEEL VERTICAL":      "setina",
    "ANGLE BRACKET":       "dtm",
    "L BRACKET":           "dtm",
    "GROMMET MOUNT":       "dtm",
    "LICENSE PLATE BRACKET": "dtm",
    "TWIST LOCK ADAPTOR":  "dtm",
    "CYLINDER STYLE":      "specify",
    "WHIP STYLE":          "specify",
    "3\"\" ROUND":         "specify",
    "3\"\" ROUND(S)":      "specify",
    "6\"\" ROUND":         "specify",

    # Center console face plate inserts
    "CUP HOLDERS":                       "havis",
    "FACTORY COMPONENT RELOCATION PLATE": "havis",
}


# ═════════════════════════════════════════════════════════════════════════════
# Sentinel manufacturer + model values — silently dropped
# ═════════════════════════════════════════════════════════════════════════════

_SENTINEL_MFGS = {
    "", "SPECIFY", "SPECIFY MFG", "SPECIFY MANUFACTURER", "OEM", "MFG CLIP",
}

_SENTINEL_MODELS = {
    "SPECIFY BAR", "SPECIFY BRACKET", "SPECIFY CRADLE", "SPECIFY DOCK",
    "SPECITY MODEL", "SWITCH PLATE (SPECIFY)",
    "PREWIRE", "DIRECT TO COMPUTER",
}


# ═════════════════════════════════════════════════════════════════════════════
# Hand-table 3: WORKBOOK_PART_TYPE_GROUPS
# Maps each workbook part-type label to a part_type definition in the new
# schema. Matching is regex; first match wins.
#
# Required fields per entry:
#   match_re            — regex matched against workbook part-type label
#   part_type_id        — stable slug (the part_type's key in parts_db)
#   label               — display name
#   type_id             — top-level type (extras/structural/equipment/lights/k9)
#   tree_positions[]    — list of {section, zone, sub_zone?} where this part_type
#                          appears in the navigation tree
#   workbook_label_pattern — string for legacy workbook export (supports {n})
#   sequence_scope      — "global" (per-part-type counter)
#
# Optional fields:
#   tag_ids             — themes (camera/radar/siren/comms)
#   max_count           — cap on instances per build
#   accessory_of        — parent part_type_id if this is an accessory (bracket etc.)
#   allowed_products    — whitelist of product_ids that can fill this part_type
#   allowed_placements  — whitelist of location_ids
# ═════════════════════════════════════════════════════════════════════════════

WORKBOOK_PART_TYPE_GROUPS: list[dict[str, Any]] = [
    # ── Lights / Exterior / Front ───────────────────────────────────────
    {"match_re": r"^Forward Warning \d+$", "part_type_id": "forward_warning",
     "label": "Forward Warning", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Forward Warning {n}", "sequence_scope": "global"},
    {"match_re": r"^Front Scene$", "part_type_id": "front_scene",
     "label": "Front Scene", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Front Scene", "sequence_scope": "global"},
    {"match_re": r"^Mirror Warning \d+$", "part_type_id": "mirror_warning",
     "label": "Mirror Warning", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Mirror Warning {n}", "sequence_scope": "global"},
    {"match_re": r"^Front Side Warning$", "part_type_id": "front_side_warning",
     "label": "Front Side Warning", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Front Side Warning {n}", "sequence_scope": "global"},
    {"match_re": r"^Headlight Flasher$", "part_type_id": "headlight_flasher",
     "label": "Headlight Flasher", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Headlight Flasher", "sequence_scope": "global"},
    {"match_re": r"^Pit Bar Warning$", "part_type_id": "pit_bar_warning",
     "label": "Pit Bar Warning", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Pit Bar Warning", "sequence_scope": "global"},

    # ── Lights / Exterior / Rear ────────────────────────────────────────
    {"match_re": r"^Rear Warning \d+$", "part_type_id": "rear_warning",
     "label": "Rear Warning", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "rear"}],
     "workbook_label_pattern": "Rear Warning {n}", "sequence_scope": "global"},
    {"match_re": r"^Rear Scene$", "part_type_id": "rear_scene",
     "label": "Rear Scene", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "rear"}],
     "workbook_label_pattern": "Rear Scene", "sequence_scope": "global"},
    {"match_re": r"^Lower Lift Gate Warning$", "part_type_id": "lower_liftgate_warning",
     "label": "Lower Lift Gate Warning", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "rear"}],
     "workbook_label_pattern": "Lower Lift Gate Warning", "sequence_scope": "global"},
    {"match_re": r"^Tail Light Flasher$", "part_type_id": "tail_light_flasher",
     "label": "Tail Light Flasher", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "rear"}],
     "workbook_label_pattern": "Tail Light Flasher", "sequence_scope": "global"},

    # ── Lights / Exterior / Side — also present interior at prisoner_area ──
    {"match_re": r"^Side Warning \d+$", "part_type_id": "side_warning",
     "label": "Side Warning", "type_id": "lights",
     "tree_positions": [
         {"section": "exterior", "zone": "side"},
         {"section": "interior", "zone": "prisoner_area"},
     ],
     "workbook_label_pattern": "Side Warning {n}", "sequence_scope": "global"},
    {"match_re": r"^Side Scene$", "part_type_id": "side_scene",
     "label": "Side Scene", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "side"}],
     "workbook_label_pattern": "Side Scene", "sequence_scope": "global"},

    # ── Lights / Exterior / Roof ────────────────────────────────────────
    {"match_re": r"^Roof Light Bar$", "part_type_id": "roof_light_bar",
     "label": "Light Bar", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "roof"}],
     "workbook_label_pattern": "Roof Light Bar", "sequence_scope": "global"},

    # ── Lights / Interior / Forward of Cage ─────────────────────────────
    {"match_re": r"^Front Interior Light Bar$", "part_type_id": "front_interior_light_bar",
     "label": "Interior Light Bar", "type_id": "lights",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Front Interior Light Bar", "sequence_scope": "global"},
    {"match_re": r"^Front Dome Light$", "part_type_id": "front_dome_light",
     "label": "Dome Light", "type_id": "lights",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Front Dome Light", "sequence_scope": "global"},

    # ── Lights / Interior / Prisoner Area ───────────────────────────────
    # (Side Warning also appears here via its multi-position tree_positions above)

    # ── Lights / Interior / Rear Storage Area ───────────────────────────
    {"match_re": r"^Rear Interior Light Bar$", "part_type_id": "rear_interior_light_bar",
     "label": "Interior Light Bar", "type_id": "lights",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area"}],
     "workbook_label_pattern": "Rear Interior Light Bar", "sequence_scope": "global"},
    {"match_re": r"^Cargo Lighting$", "part_type_id": "cargo_lighting",
     "label": "Cargo Lighting", "type_id": "lights",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area"}],
     "workbook_label_pattern": "Cargo Lighting", "sequence_scope": "global"},
    {"match_re": r"^Rear Seat Lights \d+$", "part_type_id": "rear_seat_lights",
     "label": "Rear Seat Lights", "type_id": "lights",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Rear Seat Lights {n}", "sequence_scope": "global"},
    {"match_re": r"^Rear Seat Cargo Lights$", "part_type_id": "rear_seat_cargo_lights",
     "label": "Rear Seat Cargo Lights", "type_id": "lights",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area"}],
     "workbook_label_pattern": "Rear Seat Cargo Lights", "sequence_scope": "global"},

    # ── Lights — workbook-only labels treated as their own part_types ───
    {"match_re": r"^2-Lamp Tracer$", "part_type_id": "tracer_2_lamp",
     "label": "2-Lamp Tracer", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "2-Lamp Tracer", "sequence_scope": "global"},
    {"match_re": r"^5-Lamp Tracer$", "part_type_id": "tracer_5_lamp",
     "label": "5-Lamp Tracer", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "5-Lamp Tracer", "sequence_scope": "global"},
    {"match_re": r"^6-Lamp Tracer$", "part_type_id": "tracer_6_lamp",
     "label": "6-Lamp Tracer", "type_id": "lights",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "6-Lamp Tracer", "sequence_scope": "global"},

    # ── Structural / Exterior / Front ───────────────────────────────────
    {"match_re": r"^Push Bumper$", "part_type_id": "push_bumper",
     "label": "Push Bumper", "type_id": "structural",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "accessories": ["wire_covers"],
     "workbook_label_pattern": "Push Bumper", "sequence_scope": "global"},
    {"match_re": r"^Pit Bar$", "part_type_id": "pit_bar",
     "label": "Pit Bar", "type_id": "structural",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Pit Bar", "sequence_scope": "global"},
    {"match_re": r"^Wing Wraps$", "part_type_id": "wing_wraps",
     "label": "Wing Wraps", "type_id": "structural",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Wing Wraps", "sequence_scope": "global"},
    {"match_re": r"^Wire Covers$", "part_type_id": "wire_covers",
     "label": "Wire Covers", "type_id": "structural",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "accessory_of": "push_bumper",
     "workbook_label_pattern": "Wire Covers", "sequence_scope": "global"},

    # ── Structural / Interior ──────────────────────────────────────────
    {"match_re": r"^Cage$", "part_type_id": "cage",
     "label": "Cage", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Cage", "sequence_scope": "global"},
    {"match_re": r"^Front Partition$", "part_type_id": "front_partition",
     "label": "Front Partition", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Front Partition", "sequence_scope": "global"},
    {"match_re": r"^Front Partition Transfer Kit$", "part_type_id": "front_partition_transfer_kit",
     "label": "Front Partition Transfer Kit", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "accessory_of": "front_partition",
     "workbook_label_pattern": "Front Partition Transfer Kit", "sequence_scope": "global"},
    {"match_re": r"^Rear Partition$", "part_type_id": "rear_partition",
     "label": "Rear Partition", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Rear Partition", "sequence_scope": "global"},
    {"match_re": r"^Chicago Barrier$", "part_type_id": "chicago_barrier",
     "label": "Chicago Barrier", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Chicago Barrier", "sequence_scope": "global"},
    {"match_re": r"^Rear Window Bars$", "part_type_id": "rear_window_bars",
     "label": "Rear Window Bars", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Rear Window Bars", "sequence_scope": "global"},
    {"match_re": r"^Rear Seat Divider$", "part_type_id": "rear_seat_divider",
     "label": "Rear Seat Divider", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Rear Seat Divider", "sequence_scope": "global"},
    {"match_re": r"^Replacement Rear Seat$", "part_type_id": "replacement_rear_seat",
     "label": "Replacement Seat", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Replacement Rear Seat", "sequence_scope": "global"},
    {"match_re": r"^Floor Pan$", "part_type_id": "floor_pan",
     "label": "Floor Pan", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Floor Pan", "sequence_scope": "global"},
    {"match_re": r"^Storage Compartment$", "part_type_id": "rear_storage_box",
     "label": "Storage Box", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area"}],
     "workbook_label_pattern": "Storage Compartment", "sequence_scope": "global"},

    # ── Extras (no further sub-location) ────────────────────────────────
    {"match_re": r"^Bullet Proof Door Panel\(s\)$", "part_type_id": "bullet_proof_door_panel",
     "label": "Bullet Proof Door Panel", "type_id": "extras",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Bullet Proof Door Panel", "sequence_scope": "global"},
    {"match_re": r"^Bullet Proof Door Window\(s\)$", "part_type_id": "bullet_proof_door_window",
     "label": "Bullet Proof Door Window", "type_id": "extras",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "Bullet Proof Door Window", "sequence_scope": "global"},
    {"match_re": r"^Floor Mats$", "part_type_id": "floor_mats",
     "label": "Floor Mats", "type_id": "extras",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Floor Mats", "sequence_scope": "global"},
    {"match_re": r"^Seat Covers$", "part_type_id": "seat_covers",
     "label": "Seat Covers", "type_id": "extras",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Seat Covers", "sequence_scope": "global"},
    {"match_re": r"^Window Tint$", "part_type_id": "window_tint",
     "label": "Window Tint", "type_id": "extras",
     "tree_positions": [{"section": "exterior", "zone": "side"}],
     "workbook_label_pattern": "Window Tint", "sequence_scope": "global"},
    {"match_re": r"^Harness$", "part_type_id": "harness",
     "label": "Harness", "type_id": "extras",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Harness", "sequence_scope": "global"},
    {"match_re": r"^Decals$", "part_type_id": "decals",
     "label": "Decals", "type_id": "extras",
     "tree_positions": [{"section": "exterior", "zone": "side"}],
     "workbook_label_pattern": "Decals", "sequence_scope": "global"},

    # ── Equipment / Exterior ────────────────────────────────────────────
    {"match_re": r"^Siren Speaker \d+$", "part_type_id": "siren_speaker",
     "label": "Siren Speaker", "type_id": "equipment",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "tag_ids": ["siren"],
     "workbook_label_pattern": "Siren Speaker {n}", "sequence_scope": "global"},
    {"match_re": r"^Howler$", "part_type_id": "howler",
     "label": "Howler", "type_id": "equipment",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "tag_ids": ["siren"],
     "workbook_label_pattern": "Howler", "sequence_scope": "global"},

    # ── Equipment / Interior / Forward of Cage ──────────────────────────
    {"match_re": r"^Front Camera$", "part_type_id": "front_camera",
     "label": "Front Camera", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "tag_ids": ["camera"],
     "workbook_label_pattern": "Front Camera", "sequence_scope": "global"},
    {"match_re": r"^Body Camera Dock$", "part_type_id": "body_camera_dock",
     "label": "Body Camera Dock", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "tag_ids": ["camera"],
     "workbook_label_pattern": "Body Camera Dock", "sequence_scope": "global"},
    {"match_re": r"^Camera DVR$", "part_type_id": "camera_dvr",
     "label": "Camera DVR", "type_id": "equipment",
     "tree_positions": [
         {"section": "interior", "zone": "forward_of_cage"},
         {"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"},
     ],
     "tag_ids": ["camera"],
     "workbook_label_pattern": "Camera DVR", "sequence_scope": "global"},
    {"match_re": r"^Wireless Mic Charger$", "part_type_id": "wireless_mic_charger",
     "label": "Wireless Mic Charger", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Wireless Mic Charger", "sequence_scope": "global"},
    {"match_re": r"^Radar$", "part_type_id": "radar_display_unit",
     "label": "Radar Display Unit", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "tag_ids": ["radar"],
     "workbook_label_pattern": "Radar", "sequence_scope": "global"},
    {"match_re": r"^Thermal Imager Monitor$", "part_type_id": "thermal_imager_monitor",
     "label": "Thermal Imager Monitor", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Thermal Imager Monitor", "sequence_scope": "global"},
    {"match_re": r"^Thermal Imager$", "part_type_id": "thermal_imager",
     "label": "Thermal Imager", "type_id": "equipment",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Thermal Imager", "sequence_scope": "global"},
    {"match_re": r"^Light Controller$", "part_type_id": "light_controller",
     "label": "Light Controller", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"}],
     "workbook_label_pattern": "Light Controller", "sequence_scope": "global"},
    {"match_re": r"^Control Head$", "part_type_id": "control_head",
     "label": "Light Control Head", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage", "sub_zone": "console"}],
     "workbook_label_pattern": "Control Head", "sequence_scope": "global"},
    {"match_re": r"^Vehicle interface$", "part_type_id": "vehicle_interface",
     "label": "Vehicle Interface", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"}],
     "workbook_label_pattern": "Vehicle interface", "sequence_scope": "global"},
    {"match_re": r"^Expansion Module$", "part_type_id": "expansion_module",
     "label": "Expansion Module", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"}],
     "workbook_label_pattern": "Expansion Module", "sequence_scope": "global"},
    {"match_re": r"^Radio \d+$", "part_type_id": "radio_head",
     "label": "Radio Head", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage", "sub_zone": "console"}],
     "tag_ids": ["comms"],
     "workbook_label_pattern": "Radio {n}", "sequence_scope": "global"},
    {"match_re": r"^Radio Mic Clip \d+$", "part_type_id": "radio_mic_clip",
     "label": "Radio Mic Clip", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "tag_ids": ["comms"],
     "workbook_label_pattern": "Radio Mic Clip {n}", "sequence_scope": "global"},
    {"match_re": r"^Center Console$", "part_type_id": "console",
     "label": "Console", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "max_count": 1,
     "workbook_label_pattern": "Center Console", "sequence_scope": "global"},
    {"match_re": r"^Special Face Plate \d+$", "part_type_id": "special_face_plate",
     "label": "Special Face Plate", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage", "sub_zone": "console"}],
     "workbook_label_pattern": "Special Face Plate {n}", "sequence_scope": "global"},
    {"match_re": r"^Arm Rest$", "part_type_id": "arm_rest",
     "label": "Armrest", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage", "sub_zone": "console"}],
     "workbook_label_pattern": "Arm Rest", "sequence_scope": "global"},
    {"match_re": r"^Motion Attachment$", "part_type_id": "motion_attachment",
     "label": "Motion Attachment", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage", "sub_zone": "console"}],
     "workbook_label_pattern": "Motion Attachment", "sequence_scope": "global"},
    {"match_re": r"^Docking Station$", "part_type_id": "docking_station",
     "label": "Docking Station", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage", "sub_zone": "console"}],
     "workbook_label_pattern": "Docking Station", "sequence_scope": "global"},
    {"match_re": r"^Printer$", "part_type_id": "printer",
     "label": "Printer", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage", "sub_zone": "console"}],
     "workbook_label_pattern": "Printer", "sequence_scope": "global"},
    {"match_re": r"^Printer Power$", "part_type_id": "printer_power",
     "label": "Printer Power", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "accessory_of": "printer",
     "workbook_label_pattern": "Printer Power", "sequence_scope": "global"},
    {"match_re": r"^Printer USB$", "part_type_id": "printer_usb",
     "label": "Printer USB", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "accessory_of": "printer",
     "workbook_label_pattern": "Printer USB", "sequence_scope": "global"},
    {"match_re": r"^12v Aux Ports$", "part_type_id": "aux_12v_ports",
     "label": "12v Aux Ports", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "12v Aux Ports", "sequence_scope": "global"},
    {"match_re": r"^Opticom$", "part_type_id": "preemption",
     "label": "Preemption", "type_id": "lights",
     "tree_positions": [
         {"section": "exterior", "zone": "roof"},
         {"section": "interior", "zone": "forward_of_cage"},
     ],
     "max_count": 1,
     "allowed_placements": ["IN_LIGHT_BAR", "UPPER_WINDSHIELD", "CENTER_OF_DASH"],
     "workbook_label_pattern": "Opticom", "sequence_scope": "global"},
    {"match_re": r"^Photo Eye$", "part_type_id": "photo_eye",
     "label": "Photo Eye", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Photo Eye", "sequence_scope": "global"},
    {"match_re": r"^GPD W/ Extension$", "part_type_id": "gpd",
     "label": "GPS", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "GPD W/ Extension", "sequence_scope": "global"},
    {"match_re": r"^Cradle Point$", "part_type_id": "cradle_point",
     "label": "Cloud System", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"}],
     "workbook_label_pattern": "Cradle Point", "sequence_scope": "global"},
    {"match_re": r"^Cradle Point Antenna$", "part_type_id": "cloud_antenna",
     "label": "Cloud Antenna", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area"}],
     "workbook_label_pattern": "Cradle Point Antenna", "sequence_scope": "global"},
    {"match_re": r"^Cloud System$", "part_type_id": "cloud_system_tray",
     "label": "Cloud System", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"}],
     "workbook_label_pattern": "Cloud System", "sequence_scope": "global"},
    {"match_re": r"^Vehicle to Vehicle Sync$", "part_type_id": "v2v_sync",
     "label": "Vehicle to Vehicle Sync", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"}],
     "workbook_label_pattern": "Vehicle to Vehicle Sync", "sequence_scope": "global"},
    {"match_re": r"^Remote Start$", "part_type_id": "remote_start",
     "label": "Remote Start", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Remote Start", "sequence_scope": "global"},
    {"match_re": r"^Arges$", "part_type_id": "arges_face",
     "label": "Arges", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage", "sub_zone": "console"}],
     "workbook_label_pattern": "Arges", "sequence_scope": "global"},
    {"match_re": r"^Arges Controller$", "part_type_id": "arges_controller",
     "label": "Arges Controller", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Arges Controller", "sequence_scope": "global"},
    {"match_re": r"^External Amp$", "part_type_id": "external_amp",
     "label": "External Amp", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"}],
     "tag_ids": ["siren"],
     "workbook_label_pattern": "External Amp", "sequence_scope": "global"},
    {"match_re": r"^Pa Mic$", "part_type_id": "pa_mic",
     "label": "PA Mic", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "Pa Mic", "sequence_scope": "global"},
    {"match_re": r"^Auto Eject$", "part_type_id": "auto_eject",
     "label": "Auto Eject", "type_id": "equipment",
     "tree_positions": [{"section": "exterior", "zone": "side"}],
     "workbook_label_pattern": "Auto Eject", "sequence_scope": "global"},
    {"match_re": r"^Battery Tender$", "part_type_id": "battery_tender",
     "label": "Battery Tender", "type_id": "equipment",
     "tree_positions": [{"section": "exterior", "zone": "front"}],
     "workbook_label_pattern": "Battery Tender", "sequence_scope": "global"},

    # ── Equipment / Interior / Storage Compartment (side storage) ──────
    # Note: workbook has no parts at side_storage today; gun_lock multi-position
    # entry below covers any future placement.

    # ── Equipment / Interior / Rear Storage Area ────────────────────────
    {"match_re": r"^Equipment Tray$", "part_type_id": "equipment_tray",
     "label": "Equipment Tray", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area"}],
     "max_count": 1,
     "workbook_label_pattern": "Equipment Tray", "sequence_scope": "global"},
    {"match_re": r"^Storage Compartment$", "part_type_id": "rear_storage_box_zone",
     "label": "Cargo Light Switch", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area"}],
     "workbook_label_pattern": "Storage Compartment", "sequence_scope": "global"},

    # ── Gun Locks — multi-position, same part_type ─────────────────────
    {"match_re": r"^Gunlock \d+$", "part_type_id": "gun_lock",
     "label": "Gun Lock", "type_id": "equipment",
     "tree_positions": [
         {"section": "interior", "zone": "side_storage"},
         {"section": "interior", "zone": "forward_of_cage"},
         {"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"},
     ],
     "workbook_label_pattern": "Gunlock {n}", "sequence_scope": "global"},

    # ── Camera-related (Equipment > Interior > Prisoner Area / Rear) ──
    {"match_re": r"^Rear Seat Camera$", "part_type_id": "rear_seat_camera",
     "label": "Rear Seat Camera", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "tag_ids": ["camera"],
     "workbook_label_pattern": "Rear Seat Camera", "sequence_scope": "global"},
    {"match_re": r"^Rear Camera$", "part_type_id": "rear_camera",
     "label": "Rear Camera", "type_id": "equipment",
     "tree_positions": [{"section": "exterior", "zone": "rear"}],
     "tag_ids": ["camera"],
     "workbook_label_pattern": "Rear Camera", "sequence_scope": "global"},

    # ── Door / Storage ──────────────────────────────────────────────────
    {"match_re": r"^Storage Compartment$", "part_type_id": "side_storage_compartment",
     "label": "Side Storage Compartment", "type_id": "structural",
     "tree_positions": [{"section": "interior", "zone": "side_storage"}],
     "workbook_label_pattern": "Storage Compartment", "sequence_scope": "global"},
    {"match_re": r"^Door Lock Button$", "part_type_id": "door_lock_button",
     "label": "Door Lock Button", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "rear_storage_area", "sub_zone": "equipment_tray"}],
     "workbook_label_pattern": "Door Lock Button", "sequence_scope": "global"},

    # ── K-9 ─────────────────────────────────────────────────────────────
    {"match_re": r"^K-9 Kennel$", "part_type_id": "k9_kennel",
     "label": "K-9 Kennel", "type_id": "k9",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "K-9 Kennel", "sequence_scope": "global"},
    {"match_re": r"^K-9 Heat Alarm/Popper$", "part_type_id": "k9_heat_alarm_popper",
     "label": "K-9 Heat Alarm / Door Popper", "type_id": "k9",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "K-9 Heat Alarm/Popper", "sequence_scope": "global"},
    {"match_re": r"^K-9 Control Head$", "part_type_id": "k9_control_head",
     "label": "K-9 Control Head", "type_id": "k9",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "workbook_label_pattern": "K-9 Control Head", "sequence_scope": "global"},
    {"match_re": r"^K-9 Add-Ons$", "part_type_id": "k9_add_ons",
     "label": "K-9 Add-Ons", "type_id": "k9",
     "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
     "workbook_label_pattern": "K-9 Add-Ons", "sequence_scope": "global"},

    # ── Brackets (all accessories) ──────────────────────────────────────
    {"match_re": r"^FW \d+ Bracket$", "part_type_id": "fw_bracket",
     "label": "FW Bracket", "type_id": "lights",
     "tree_positions": [],
     "accessory_of": "forward_warning",
     "workbook_label_pattern": "FW {n} Bracket", "sequence_scope": "global"},
    {"match_re": r"^Mirror Warning Brackets? \d+$", "part_type_id": "mirror_warning_bracket",
     "label": "Mirror Warning Bracket", "type_id": "lights",
     "tree_positions": [],
     "accessory_of": "mirror_warning",
     "workbook_label_pattern": "Mirror Warning Bracket {n}", "sequence_scope": "global"},
    {"match_re": r"^Front Side Brackets$", "part_type_id": "front_side_bracket",
     "label": "Front Side Bracket", "type_id": "lights",
     "tree_positions": [],
     "accessory_of": "front_side_warning",
     "workbook_label_pattern": "Front Side Brackets", "sequence_scope": "global"},
    {"match_re": r"^Side Warning Bracket \d+$", "part_type_id": "side_warning_bracket",
     "label": "Side Warning Bracket", "type_id": "lights",
     "tree_positions": [],
     "accessory_of": "side_warning",
     "workbook_label_pattern": "Side Warning Bracket {n}", "sequence_scope": "global"},
    {"match_re": r"^Rear Warning Bracket \d+$", "part_type_id": "rear_warning_bracket",
     "label": "Rear Warning Bracket", "type_id": "lights",
     "tree_positions": [],
     "accessory_of": "rear_warning",
     "workbook_label_pattern": "Rear Warning Bracket {n}", "sequence_scope": "global"},
    {"match_re": r"^Lower Lift Gate Warning Bracket$", "part_type_id": "lower_liftgate_warning_bracket",
     "label": "Lower Lift Gate Warning Bracket", "type_id": "lights",
     "tree_positions": [],
     "accessory_of": "lower_liftgate_warning",
     "workbook_label_pattern": "Lower Lift Gate Warning Bracket", "sequence_scope": "global"},
    {"match_re": r"^Siren Speaker Bracket$", "part_type_id": "siren_speaker_bracket",
     "label": "Siren Speaker Bracket", "type_id": "equipment",
     "tree_positions": [],
     "accessory_of": "siren_speaker",
     "workbook_label_pattern": "Siren Speaker Bracket", "sequence_scope": "global"},
    {"match_re": r"^Front Radar Antenna Mount$", "part_type_id": "front_radar_antenna_mount",
     "label": "Front Radar Antenna Mount", "type_id": "equipment",
     "tree_positions": [],
     "accessory_of": "radar_display_unit",
     "tag_ids": ["radar"],
     "workbook_label_pattern": "Front Radar Antenna Mount", "sequence_scope": "global"},
    {"match_re": r"^Rear Radar Antenna Mount$", "part_type_id": "rear_radar_antenna_mount",
     "label": "Rear Radar Antenna Mount", "type_id": "equipment",
     "tree_positions": [],
     "accessory_of": "radar_display_unit",
     "tag_ids": ["radar"],
     "workbook_label_pattern": "Rear Radar Antenna Mount", "sequence_scope": "global"},
    {"match_re": r"^Radar Interface Cable \(To Camera\)$", "part_type_id": "radar_interface_cable",
     "label": "Radar Interface Cable", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "tag_ids": ["radar", "camera"],
     "workbook_label_pattern": "Radar Interface Cable (To Camera)", "sequence_scope": "global"},
    {"match_re": r"^Printer Mount$", "part_type_id": "printer_mount",
     "label": "Printer Mount", "type_id": "equipment",
     "tree_positions": [],
     "accessory_of": "printer",
     "workbook_label_pattern": "Printer Mount", "sequence_scope": "global"},
    {"match_re": r"^Pa Mic Clip$", "part_type_id": "pa_mic_clip",
     "label": "PA Mic Clip", "type_id": "equipment",
     "tree_positions": [],
     "accessory_of": "pa_mic",
     "workbook_label_pattern": "Pa Mic Clip", "sequence_scope": "global"},
    {"match_re": r"^Gunlock Bracket \d+$", "part_type_id": "gun_lock_bracket",
     "label": "Gun Lock Bracket", "type_id": "equipment",
     "tree_positions": [],
     "accessory_of": "gun_lock",
     "workbook_label_pattern": "Gunlock Bracket {n}", "sequence_scope": "global"},
    {"match_re": r"^Arges Mount$", "part_type_id": "arges_mount",
     "label": "Arges Mount", "type_id": "equipment",
     "tree_positions": [],
     "accessory_of": "arges_controller",
     "workbook_label_pattern": "Arges Mount", "sequence_scope": "global"},
    {"match_re": r"^Radio Antenna Cable$", "part_type_id": "radio_antenna_cable",
     "label": "Radio Communication Cable", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "tag_ids": ["comms"],
     "workbook_label_pattern": "Radio Antenna Cable", "sequence_scope": "global"},
    {"match_re": r"^Radio Antenna Top$", "part_type_id": "radio_antenna_top",
     "label": "Radio Antenna Top", "type_id": "equipment",
     "tree_positions": [{"section": "exterior", "zone": "roof"}],
     "tag_ids": ["comms"],
     "workbook_label_pattern": "Radio Antenna Top", "sequence_scope": "global"},
    {"match_re": r"^Radio Speaker$", "part_type_id": "radio_speaker",
     "label": "Radio Speaker", "type_id": "equipment",
     "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
     "tag_ids": ["comms"],
     "workbook_label_pattern": "Radio Speaker", "sequence_scope": "global"},
]

_BRACKET_PT_IDS_FOR_DEFAULT_TAG: set[str] = set()  # populated at build time


def find_part_type_group(workbook_label: str) -> dict | None:
    for group in WORKBOOK_PART_TYPE_GROUPS:
        if re.match(group["match_re"], workbook_label):
            return group
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    s = (s or "").lower()
    s = _SLUG_RE.sub("_", s).strip("_")
    return s


def detect_typos(strings: list[str], threshold: float = 0.85) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(strings):
        for b in strings[i + 1 :]:
            key = (min(a, b), max(a, b))
            if key in seen:
                continue
            ratio = SequenceMatcher(None, a, b).ratio()
            if threshold <= ratio < 1.0:
                pairs.append((a, b))
                seen.add(key)
    return pairs


# ═════════════════════════════════════════════════════════════════════════════
# Orphans
# ═════════════════════════════════════════════════════════════════════════════


class Orphans:
    def __init__(self) -> None:
        self.unmapped_placement_locations: list[str] = []
        self.unknown_model_manufacturers: list[tuple[str, list[str]]] = []
        self.unmatched_workbook_part_types: list[str] = []
        self.manufacturer_typos: list[tuple[str, str]] = []

    @property
    def any(self) -> bool:
        return bool(
            self.unmapped_placement_locations
            or self.unknown_model_manufacturers
            or self.unmatched_workbook_part_types
            or self.manufacturer_typos
        )

    def to_markdown(self) -> str:
        lines: list[str] = ["# Migration orphans report\n"]
        lines.append("Edit the hand-tables in `tools/migrate_workbook_to_parts_db.py`")
        lines.append("(or fix upstream config files for typos) until this report is empty.\n")

        def section(title: str, items: list[str]) -> None:
            if not items:
                lines.append(f"## {title}\n\n_None._\n")
                return
            lines.append(f"## {title} ({len(items)})\n")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")

        section(
            "Unmapped placement locations (PLACEMENT_LOCATION_TO_ZONE)",
            [f"`{loc}` — set a placement_zone or leave as `\"\"` for meta locations"
             for loc in self.unmapped_placement_locations],
        )
        section(
            "Unknown model → manufacturer (MODEL_MANUFACTURER)",
            [
                f"`{model}` (referenced by {', '.join(refs)}) — add to MODEL_MANUFACTURER"
                for model, refs in self.unknown_model_manufacturers
            ],
        )
        section(
            "Unmatched workbook part-types (WORKBOOK_PART_TYPE_GROUPS)",
            [f"`{label}` — add a regex row to WORKBOOK_PART_TYPE_GROUPS"
             for label in self.unmatched_workbook_part_types],
        )
        section(
            "Manufacturer typo candidates (upstream fix)",
            [f"`{a}` vs `{b}` — fix one or both in source config files"
             for a, b in self.manufacturer_typos],
        )

        return "\n".join(lines) + "\n"


# ═════════════════════════════════════════════════════════════════════════════
# Loaders / collectors
# ═════════════════════════════════════════════════════════════════════════════


def load_inputs() -> dict[str, dict]:
    return {
        "workbook_rules":  json.loads(INPUT_WORKBOOK_RULES.read_text("utf-8")),
        "parts_library":   json.loads(INPUT_PARTS_LIBRARY.read_text("utf-8")),
        "vehicle_layouts": json.loads(INPUT_VEHICLE_LAYOUTS.read_text("utf-8")),
        "part_catalog":    json.loads(INPUT_PART_CATALOG.read_text("utf-8")),
    }


def collect_all_locations(vehicle_layouts: dict) -> set[str]:
    out: set[str] = set()
    for vehicle in (vehicle_layouts.get("vehicles") or {}).values():
        for view in (vehicle.get("views") or {}).values():
            for loc_key in (view.get("locations") or {}).keys():
                out.add(loc_key)
    return out


def build_manufacturers(workbook_rules: dict, parts_library: dict) -> tuple[dict, list[tuple[str, str]]]:
    raw: set[str] = set()
    for rule in (workbook_rules.get("part_rules") or {}).values():
        for m in rule.get("manufacturer") or []:
            raw.add(m)
    for entry in parts_library.get("parts") or []:
        if entry.get("manufacturer"):
            raw.add(entry["manufacturer"])

    real = sorted(
        {m for m in raw if m.strip().upper() not in {s.upper() for s in _SENTINEL_MFGS}}
    )

    by_slug: dict[str, list[str]] = defaultdict(list)
    for m in real:
        by_slug[slugify(m)].append(m)

    manufacturers: dict[str, dict] = {}
    for slug, variants in sorted(by_slug.items()):
        label = max(variants, key=lambda v: sum(1 for c in v if c.isupper())).title()
        manufacturers[slug] = {"label": label}

    return manufacturers, detect_typos(real)


def lookup_manufacturer_for_model(
    model: str, workbook_rules: dict, parts_library: dict
) -> str | None:
    # 1. parts_library entry with manufacturer
    for entry in parts_library.get("parts") or []:
        if entry.get("model_number") == model and entry.get("manufacturer"):
            mfg = entry["manufacturer"]
            if mfg.strip().upper() not in {s.upper() for s in _SENTINEL_MFGS}:
                return slugify(mfg)

    # 2. workbook_rules single-real-mfg rule containing this model
    for rule in (workbook_rules.get("part_rules") or {}).values():
        if model not in (rule.get("models") or []):
            continue
        real_mfgs = [
            m for m in (rule.get("manufacturer") or [])
            if m.strip().upper() not in {s.upper() for s in _SENTINEL_MFGS}
        ]
        if len(real_mfgs) == 1:
            return slugify(real_mfgs[0])

    # 3. Hand-table
    hand = MODEL_MANUFACTURER.get(model)
    if hand and hand != UNKNOWN:
        return hand
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Builders for parts_db.json (schema v2)
# ═════════════════════════════════════════════════════════════════════════════


def build_part_types(workbook_rules: dict, orphans: Orphans) -> dict:
    """Walk every workbook part-type label, group via WORKBOOK_PART_TYPE_GROUPS,
    emit ONE part_type entry per group's part_type_id (collapsing
    similarly-labeled workbook entries like Forward Warning 1/2 into one
    part_type)."""
    part_types: dict[str, dict] = {}
    for label in (workbook_rules.get("part_rules") or {}).keys():
        group = find_part_type_group(label)
        if group is None:
            orphans.unmatched_workbook_part_types.append(label)
            continue
        pid = group["part_type_id"]
        if pid in part_types:
            continue
        spec: dict[str, Any] = {
            "label": group["label"],
            "type_id": group["type_id"],
            "tree_positions": [dict(p) for p in group.get("tree_positions", [])],
            "tag_ids": list(group.get("tag_ids", [])),
            "workbook_label_pattern": group["workbook_label_pattern"],
            "sequence_scope": group.get("sequence_scope", "global"),
        }
        if group.get("max_count") is not None:
            spec["max_count"] = group["max_count"]
        if group.get("accessory_of"):
            spec["accessory_of"] = group["accessory_of"]
        if group.get("accessories"):
            spec["accessories"] = list(group["accessories"])
        if group.get("allowed_products"):
            spec["allowed_products"] = list(group["allowed_products"])
        if group.get("allowed_placements"):
            spec["allowed_placements"] = list(group["allowed_placements"])
        part_types[pid] = spec
    return part_types


def build_products_and_legacy_index(
    workbook_rules: dict,
    parts_library: dict,
    part_types: dict,
    orphans: Orphans,
) -> tuple[dict, dict, dict]:
    """Mint products from the (manufacturer × model) cross-product of workbook
    rules. For each model resolved, attach the matched part_type_id to the
    product's fits_part_types list (forward index).
    """
    # workbook label → part_type_id (matched via regex from WORKBOOK_PART_TYPE_GROUPS)
    label_to_part_type: dict[str, str] = {}
    for label in (workbook_rules.get("part_rules") or {}).keys():
        group = find_part_type_group(label)
        if group is not None:
            label_to_part_type[label] = group["part_type_id"]

    products: dict[str, dict] = {}
    part_type_to_products: dict[str, list[str]] = defaultdict(list)
    model_string_to_product: dict[str, str] = {}
    unknown_models: dict[str, list[str]] = defaultdict(list)

    for part_type_label, rule in (workbook_rules.get("part_rules") or {}).items():
        pt_id = label_to_part_type.get(part_type_label)
        if pt_id is None:
            continue  # already recorded as orphan in build_part_types

        models = rule.get("models") or []
        for model in models:
            if model in _SENTINEL_MODELS:
                continue
            mfg_slug = lookup_manufacturer_for_model(model, workbook_rules, parts_library)
            if not mfg_slug:
                unknown_models[model].append(part_type_label)
                continue

            product_id = f"{mfg_slug}_{slugify(model)}"
            if product_id not in products:
                # Tag inheritance: products pick up the part_type's tags by default
                pt = part_types.get(pt_id) or {}
                inherited_tags = list(pt.get("tag_ids", []))
                products[product_id] = {
                    "manufacturer_id": mfg_slug,
                    "model": model,
                    "fits_part_types": [],
                    "tag_ids": inherited_tags,
                    "description": "",
                    "images": {},
                    "part_numbers": [{"part_number": model}],
                }
            if pt_id not in products[product_id]["fits_part_types"]:
                products[product_id]["fits_part_types"].append(pt_id)

            if product_id not in part_type_to_products[part_type_label]:
                part_type_to_products[part_type_label].append(product_id)
            model_string_to_product.setdefault(model, product_id)

    for model, refs in sorted(unknown_models.items()):
        orphans.unknown_model_manufacturers.append((model, sorted(set(refs))))

    return products, dict(part_type_to_products), model_string_to_product


def build_placements(all_locations: set[str], orphans: Orphans) -> dict:
    """One entry per known physical location. Carries placement_zone (for
    workbook label derivation) + optional allowed_products restriction."""
    out: dict[str, dict] = {}
    for loc in sorted(all_locations):
        zone = PLACEMENT_LOCATION_TO_ZONE.get(loc)
        if zone is None:
            orphans.unmapped_placement_locations.append(loc)
            continue
        entry: dict[str, Any] = {}
        if zone:
            entry["placement_zone"] = zone
        restrictions = PLACEMENT_RESTRICTIONS.get(loc)
        if restrictions:
            entry["allowed_products"] = list(restrictions)
        out[loc] = entry
    # Also register any locations referenced in PLACEMENT_RESTRICTIONS but
    # not yet in vehicle_layouts (e.g. the new TWIST_LOCK locations)
    for loc, restrictions in PLACEMENT_RESTRICTIONS.items():
        if loc not in out:
            entry = {"allowed_products": list(restrictions)}
            zone = PLACEMENT_LOCATION_TO_ZONE.get(loc)
            if zone:
                entry["placement_zone"] = zone
            out[loc] = entry
    return out


def build_color_palette() -> dict:
    return {
        "red":    {"label": "Red",    "hex": "#E10600", "naming_token": "R"},
        "blue":   {"label": "Blue",   "hex": "#003DA5", "naming_token": "B"},
        "white":  {"label": "White",  "hex": "#FFFFFF", "naming_token": "W"},
        "amber":  {"label": "Amber",  "hex": "#FFA500", "naming_token": "A"},
        "green":  {"label": "Green",  "hex": "#00853E", "naming_token": "G"},
        "purple": {"label": "Purple", "hex": "#8B5CF6", "naming_token": "P"},
    }


def build_parts_db(inputs: dict, orphans: Orphans) -> dict:
    workbook_rules = inputs["workbook_rules"]
    parts_library = inputs["parts_library"]
    vehicle_layouts = inputs["vehicle_layouts"]

    manufacturers, typo_pairs = build_manufacturers(workbook_rules, parts_library)
    orphans.manufacturer_typos.extend(typo_pairs)

    part_types = build_part_types(workbook_rules, orphans)
    products, part_type_to_products, model_string_to_product = (
        build_products_and_legacy_index(workbook_rules, parts_library, part_types, orphans)
    )
    placements = build_placements(collect_all_locations(vehicle_layouts), orphans)

    return {
        "parts_db": {
            "schema_version": 2,
            "metadata": {
                "last_updated": "2026-06-11T00:00:00Z",
                "updated_by": "migrate_workbook_to_parts_db.py",
            },
            "types":             {k: dict(v) for k, v in TYPES.items()},
            "sections":          {k: dict(v) for k, v in SECTIONS.items()},
            "zones":             {k: dict(v) for k, v in ZONES.items()},
            "sub_zones":         {k: dict(v) for k, v in SUB_ZONES.items()},
            "build_attributes":  {k: dict(v) for k, v in BUILD_ATTRIBUTES.items()},
            "tags":              {k: dict(v) for k, v in TAGS.items()},
            "manufacturers":     manufacturers,
            "products":          products,
            "part_types":        part_types,
            "placements":        placements,
            "placement_zones":   {k: dict(v) for k, v in PLACEMENT_ZONES.items()},
            "services":          {k: dict(v) for k, v in SERVICES.items()},
            "preference_filters": {k: dict(v) for k, v in PREFERENCE_FILTERS.items()},
            "color_palette":     build_color_palette(),
            "naming_rules": {
                "product_display_name": {
                    "template": "{manufacturer_label} {model}",
                },
                "light_part_name": {
                    "template": "{manufacturer_label} {model} {colors_joined}",
                    "color_joiner": "/",
                    "color_canonical_order": ["red", "blue", "white", "amber", "green", "purple"],
                    "color_display_form": "label",
                },
            },
        },
        "legacy_workbook_index": {
            "schema_version": 1,
            "purpose": "Maps legacy workbook part-type labels + model strings to product_ids and part_type_ids. Used by manifest_editor and excel_reader during the parts_db transition. Generated by tools/migrate_workbook_to_parts_db.py.",
            "part_type_to_products": part_type_to_products,
            "model_string_to_product": model_string_to_product,
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print summary; do not write files")
    parser.add_argument("--write", action="store_true",
                        help="Write parts_db.json + legacy_workbook_index.json")
    parser.add_argument("--push-to-cloud", action="store_true",
                        help="After --write, route both files through save_config_file "
                             "so the SharePoint direct-mirror fires. Prevents the next "
                             "60s shared-settings sync from clobbering the migration with "
                             "whatever (older) copy SharePoint has.")
    parser.add_argument("--orphans-out", default="orphans.md",
                        help="Path for the orphans report")
    args = parser.parse_args()

    if not args.dry_run and not args.write:
        parser.error("Pick one: --dry-run or --write")

    inputs = load_inputs()
    orphans = Orphans()
    out = build_parts_db(inputs, orphans)

    parts_db = out["parts_db"]
    legacy_index = out["legacy_workbook_index"]

    print(f"Types:           {len(parts_db['types'])}")
    print(f"Sections:        {len(parts_db['sections'])}")
    print(f"Zones:           {len(parts_db['zones'])}")
    print(f"Sub-zones:       {len(parts_db['sub_zones'])}")
    print(f"Build attrs:     {len(parts_db['build_attributes'])}")
    print(f"Tags:            {len(parts_db['tags'])}")
    print(f"Manufacturers:   {len(parts_db['manufacturers'])}")
    print(f"Products:        {len(parts_db['products'])}")
    print(f"Part types:      {len(parts_db['part_types'])}")
    print(f"Placements:      {len(parts_db['placements'])}")
    print(f"Services:        {len(parts_db['services'])}")
    print(f"Preference filt: {len(parts_db['preference_filters'])}")
    print(f"legacy_index pt→prod:   {len(legacy_index['part_type_to_products'])}")
    print(f"legacy_index model→prod: {len(legacy_index['model_string_to_product'])}")
    print()

    orphans_path = Path(args.orphans_out)
    orphans_path.write_text(orphans.to_markdown(), "utf-8")
    print(f"Orphans report → {orphans_path}")
    print(f"  Unmapped placement locations:  {len(orphans.unmapped_placement_locations)}")
    print(f"  Unknown model→mfg:             {len(orphans.unknown_model_manufacturers)}")
    print(f"  Unmatched workbook part-types: {len(orphans.unmatched_workbook_part_types)}")
    print(f"  Manufacturer typos:            {len(orphans.manufacturer_typos)}")

    if args.dry_run:
        return 0

    if orphans.any:
        print()
        print("REFUSING TO WRITE: orphans remain.", file=sys.stderr)
        return 2

    OUTPUT_PARTS_DB.write_text(json.dumps(parts_db, indent=2) + "\n", "utf-8")
    OUTPUT_LEGACY_INDEX.write_text(json.dumps(legacy_index, indent=2) + "\n", "utf-8")
    print(f"Wrote {OUTPUT_PARTS_DB}")
    print(f"Wrote {OUTPUT_LEGACY_INDEX}")

    if args.push_to_cloud:
        # Re-save through save_config_file so direct-mirror to SharePoint
        # fires for both files. Without this step the next shared-settings
        # sync will overwrite the migrated data with whatever (older) copy
        # SharePoint has, because the writes above bypass the save pipeline.
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from dtm_buildsheet.paths import AppPaths
        from dtm_buildsheet.app.services.config_service import save_config_file
        paths = AppPaths()
        for filename, payload in (
            ("parts_db.json", parts_db),
            ("legacy_workbook_index.json", legacy_index),
        ):
            result = save_config_file(filename, payload, paths)
            if not result.get("ok"):
                print(f"Cloud push failed for {filename}: {result.get('error')}", file=sys.stderr)
                return 3
            tag = "queued for retry" if result.get("queued") else "direct-mirrored"
            print(f"  {filename} → {tag} (proposal {result.get('proposal_id','—')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
