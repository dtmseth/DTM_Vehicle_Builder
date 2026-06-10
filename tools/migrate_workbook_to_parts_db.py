#!/usr/bin/env python3
"""Phase 3 migration: workbook_rules + parts_library + vehicle_layouts → parts_db.json.

One-shot script. Reads the three legacy config files (plus part_catalog for
canonical part_ids) and emits two artifacts:

  - parts_db.json              — the new manufacturer-centric canonical DB
  - legacy_workbook_index.json — string-keyed transition map for the
                                  manifest_editor + excel_reader fallback

Plus an orphans.md report listing every datum the script could not place into
the new schema without owner input. The script refuses `--write` when orphans
exist — owner edits the hand-tables in this file (or fixes upstream data),
re-runs `--dry-run`, repeats until clean.

Owner-editable inputs are the four tables at the top:

  LOCATION_TO_ZONE              ~56 entries (vehicle location keys → zones)
  CATEGORY_MAP                  part_catalog.category + display_name → parts_db.category_id
  MODEL_MANUFACTURER            model string → manufacturer slug (mostly ??? on first run)
  WORKBOOK_PART_TYPE_GROUPS     regex match → derivation rule

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


# ─────────────────────────────────────────────────────────────────────────────
# Hand-table 1: LOCATION_TO_ZONE
# Owner reviews each row. Use UNKNOWN ("???") when a location can't be mapped
# without ambiguity — script reports those as orphans.
# Locations not referenced by any product are silently skipped.
# ─────────────────────────────────────────────────────────────────────────────

LOCATION_TO_ZONE: dict[str, str] = {
    # Primary front (push bumper area, grill, headlights)
    "GRILL":               "primary_front",
    "IN GRILL":            "primary_front",
    "LOWER GRILL":         "primary_front",
    "BEHIND GRILL (CENTER)": "primary_front",
    "TOP TUBE":            "primary_front",
    "CENTER PLATE OF PB":  "primary_front",
    "TOP OF PUSH BUMPER":  "primary_front",
    "SIDE OF PUSH BUMPER": "primary_front",
    "UNDER PUSH BUMPER":   "primary_front",
    "PUSH BUMPER":         "primary_front",
    "PUSH BUMPER MOUNT":   "primary_front",
    "BEHIND OEM BUMPER":   "primary_front",
    "HEADLIGHT CUT OUTS":  "primary_front",
    "FOG LIGHT AREA":      "primary_front",
    "PIT BARS":            "primary_front",
    "UPPER WINDSHIELD":    "primary_front",

    # Front corner / front side (fenders, mirrors)
    "FRONT CORNER OF BUMPER": "front_corner",
    "FRONT OF MIRROR":     "front_side",
    "UNDER MIRROR":        "front_side",
    "LEFT FRONT FENDER":   "front_side",
    "RIGHT FRONT FENDER":  "front_side",
    "LEFT AND RIGHT FENDER": "front_side",

    # Side (rocker, running board)
    "ON RUNNING BOARD":    "side",
    "ROCKER PANEL":        "side",

    # Rear
    "ABOVE LICENSE PLATE": "rear",
    "LICENSE PLATE BRACKET": "rear",
    "TAIL LIGHTS":         "rear",
    "REAR BUMPER":         "rear",
    "LOWER LIFTGATE LIP":  "rear",
    "ON TAILGATE/LIFTGATE": "rear",
    "UNDER TAILGATE":      "rear",
    "REAR LEFT ROOF":      "rear",

    # Rear side (rear door window)
    "REAR DOOR WINDOW":    "rear_side",

    # Rear interior (cargo windows, rear glass)
    "LOWER CARGO WINDOW":  "rear_interior",
    "UPPER CARGO WINDOW":  "rear_interior",
    "UPPER REAR WINDOW":   "rear_interior",
    "REAR INTERIOR LIGHT BAR": "rear_interior",

    # Interior (dash, headliner)
    "INTERIOR LIGHT BAR (FRONT)": "interior",
    "CENTER OF DASH":      "interior",
    "ON DASH":             "interior",
    "LEFT ON DASH":        "interior",
    "HEADLINER":           "interior",

    # ─── Ambiguous — owner reviews ────────────────────────────────────────
    # These are referenced by products but the right zone isn't obvious from
    # the location name alone. Mark UNKNOWN and the script reports them as
    # orphans. Owner picks a zone (possibly adding a new zone like `roof`
    # if needed).
    "IN LIGHT BAR":              UNKNOWN,  # interior or roof depending on which light bar
    "LIGHTBAR MOUNT":            UNKNOWN,  # roof — but no `roof` zone exists yet
    "ON ROOF":                   UNKNOWN,
    "ROOF":                      UNKNOWN,
    "ROOF CENTER":               UNKNOWN,
    "ROOF LIGHT BAR":            UNKNOWN,
    "PILLARS":                   UNKNOWN,  # A-pillar (front_corner) or B-pillar (side)?
    "SPOT LIGHT MOUNT":          UNKNOWN,  # mirror area? roof?
    "UPPER DRIVER AND PASSENGER": UNKNOWN,

    # ─── Meta / sentinel locations — not real zones ──────────────────────
    # These don't correspond to a vehicle location at all. Mapped to empty
    # string so the resolver skips zone-based part_type derivation; products
    # placed here fall back to model-name labels.
    "ON SPECIFIC BRACKET":      "",
    "PASSENGER SIDE ONLY":      "",
    "SPECIFY LOCATION":         "",
    "VEHICLE SPECIFIC BRACKET": "",
    "VEHICLE SPECIFIC BRACKET(S)": "",
}


# ─────────────────────────────────────────────────────────────────────────────
# Hand-table 2: CATEGORY_MAP
# Maps part_catalog (category, display_name) → parts_db category_id.
# `_default_per_catalog_category` provides a fallback when no display_name
# override fires. Owner adjusts both.
# ─────────────────────────────────────────────────────────────────────────────

_PARTS_DB_CATEGORIES = {
    "lights":       "Lights",
    "push_bumpers": "Push Bumpers",
    "cages":        "Cages",
    "audio":        "Audio",
    "radar":        "Radar",
    "brackets":     "Brackets",
    "decals":       "Decals",
    "k9":           "K-9 Equipment",
    "accessories":  "Accessories",
    "antennas":     "Antennas",
}

# applies_to_zones — what zones each category is valid in. Owner reviews.
_CATEGORY_ZONES: dict[str, list[str]] = {
    "lights":       ["primary_front", "front_corner", "front_side",
                     "side", "rear_side", "rear_corner", "rear",
                     "rear_interior", "interior"],
    "push_bumpers": ["primary_front"],
    "cages":        ["interior"],
    "audio":        ["primary_front", "interior"],
    "radar":        ["interior"],
    "brackets":     [],  # attach to parts, not locations
    "decals":       [],
    "k9":           ["interior"],
    "accessories":  [],
    "antennas":     ["rear_interior", "interior"],
}

_DEFAULT_PER_CATALOG_CATEGORY: dict[str, str] = {
    "warning_light":   "lights",
    "scene_light":     "lights",
    "light_bar":       "lights",
    "audio":           "audio",
    "equipment_note":  "brackets",     # most equipment_notes are brackets/cables; overrides below catch exceptions
    "appearance_note": "decals",       # wing wraps, wire covers — visible appearance
    "vehicle_system":  "accessories",  # flashers, opticom — bucket category
    "equipment":       UNKNOWN,        # MUST be resolved via per-display_name override
}

# Per-display-name overrides for ambiguous catalog categories (`equipment` is
# the big one — covers push bumpers, cages, speakers, etc.).
_DISPLAY_NAME_TO_CATEGORY: dict[str, str] = {
    "Push Bumper": "push_bumpers",
    "Cage":        "cages",
    "Siren Speaker 1": "audio",
    "Siren Speaker 2": "audio",
    "Siren Speaker Bracket": "brackets",
    "Radar":       "radar",
    "Radar Interface Cable (To Camera)": "accessories",
    "Radio Antenna Cable": "antennas",
    "Cradle Point Antenna": "antennas",
    # Owner adds more here as orphan report surfaces them.
}


def category_for_part(catalog_category: str, display_name: str) -> str:
    """Return the parts_db category_id for a part with the given catalog
    category and display_name. Returns UNKNOWN if it can't be determined."""
    override = _DISPLAY_NAME_TO_CATEGORY.get(display_name)
    if override is not None:
        return override
    return _DEFAULT_PER_CATALOG_CATEGORY.get(catalog_category, UNKNOWN)


# ─────────────────────────────────────────────────────────────────────────────
# Hand-table 3: MODEL_MANUFACTURER
# When neither workbook_rules nor parts_library reveals a model's
# manufacturer, owner fills in the slug here. Script pre-populates every
# unknown with UNKNOWN; dry-run lists them with the part-types each model
# is referenced from.
# ─────────────────────────────────────────────────────────────────────────────

MODEL_MANUFACTURER: dict[str, str] = {
    # Pre-seed obvious ones discovered during data inspection.
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
    # Everything else is filled in by the dry-run report. Owner edits this
    # dict in place and re-runs.
}


# ─────────────────────────────────────────────────────────────────────────────
# Hand-table 4: WORKBOOK_PART_TYPE_GROUPS
# Maps each workbook part-type label (the keys of workbook_rules.part_rules)
# to a derivation rule. Multiple labels collapse into one part_type entry
# (e.g. "Forward Warning 1" and "Forward Warning 2" share the same rule).
# Order matters — first matching pattern wins. Owner adjusts.
# ─────────────────────────────────────────────────────────────────────────────

WORKBOOK_PART_TYPE_GROUPS: list[dict[str, Any]] = [
    # ── Front warning lights ────────────────────────────────────────────
    {
        "match_re": r"^Forward Warning \d+$",
        "part_type_id": "forward_warning",
        "label": "Forward Warning",
        "category_id": "lights",
        "predicate": {"zone": "primary_front", "colors": "any_non_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Forward Warning {n}",
    },
    {
        "match_re": r"^Front Scene$",
        "part_type_id": "front_scene",
        "label": "Front Scene",
        "category_id": "lights",
        "predicate": {"zone": "primary_front", "colors": "all_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Front Scene {n}",
    },
    # ── Mirror / front corner ───────────────────────────────────────────
    {
        "match_re": r"^Mirror Warning \d+$",
        "part_type_id": "mirror_warning",
        "label": "Mirror Warning",
        "category_id": "lights",
        "predicate": {"zone": "front_corner", "colors": "any_non_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Mirror Warning {n}",
    },
    {
        "match_re": r"^Mirror Warning Brackets? \d+$",
        "part_type_id": "mirror_warning_bracket",
        "label": "Mirror Warning Bracket",
        "category_id": "brackets",
        "predicate": {"category_only": True},
        "sequence_scope": "global",
        "workbook_label_pattern": "Mirror Warning Bracket",
    },
    # ── Side ────────────────────────────────────────────────────────────
    {
        "match_re": r"^Side Warning \d+$",
        "part_type_id": "side_warning",
        "label": "Side Warning",
        "category_id": "lights",
        "predicate": {"zone": "side", "colors": "any_non_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Side Warning {n}",
    },
    {
        "match_re": r"^Front Side Warning$",
        "part_type_id": "front_side_warning",
        "label": "Front Side Warning",
        "category_id": "lights",
        "predicate": {"zone": "front_side", "colors": "any_non_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Front Side Warning {n}",
    },
    {
        "match_re": r"^Front Side Brackets$",
        "part_type_id": "front_side_bracket",
        "label": "Front Side Bracket",
        "category_id": "brackets",
        "predicate": {"category_only": True},
        "sequence_scope": "global",
        "workbook_label_pattern": "Front Side Brackets",
    },
    {
        "match_re": r"^Side Scene$",
        "part_type_id": "side_scene",
        "label": "Side Scene",
        "category_id": "lights",
        "predicate": {"zone": "side", "colors": "all_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Side Scene {n}",
    },
    # ── Rear ────────────────────────────────────────────────────────────
    {
        "match_re": r"^Rear Warning \d+$",
        "part_type_id": "rear_warning",
        "label": "Rear Warning",
        "category_id": "lights",
        "predicate": {"zone": "rear", "colors": "any_non_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Rear Warning {n}",
    },
    {
        "match_re": r"^Rear Scene$",
        "part_type_id": "rear_scene",
        "label": "Rear Scene",
        "category_id": "lights",
        "predicate": {"zone": "rear", "colors": "all_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Rear Scene {n}",
    },
    {
        "match_re": r"^Lower Lift Gate Warning$",
        "part_type_id": "lower_liftgate_warning",
        "label": "Lower Lift Gate Warning",
        "category_id": "lights",
        "predicate": {"zone": "rear", "colors": "any_non_white"},
        "sequence_scope": "per_zone_per_role",
        "workbook_label_pattern": "Lower Lift Gate Warning",
    },
    # ── Equipment (one-offs) ────────────────────────────────────────────
    {
        "match_re": r"^Push Bumper$",
        "part_type_id": "push_bumper",
        "label": "Push Bumper",
        "category_id": "push_bumpers",
        "predicate": {"category_only": True},
        "sequence_scope": "global",
        "workbook_label_pattern": "Push Bumper",
    },
    {
        "match_re": r"^Cage$",
        "part_type_id": "cage",
        "label": "Cage",
        "category_id": "cages",
        "predicate": {"category_only": True},
        "sequence_scope": "global",
        "workbook_label_pattern": "Cage",
    },
    # Catch-all: any workbook label not matched by the patterns above is an
    # orphan. Owner adds a row above to match it, then re-runs.
]


def find_part_type_group(workbook_label: str) -> dict | None:
    for group in WORKBOOK_PART_TYPE_GROUPS:
        if re.match(group["match_re"], workbook_label):
            return group
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Sentinel manufacturer strings — treated as "unspecified" and never minted
# as a manufacturer entry. Owner adjusts list as new sentinels surface.
# ─────────────────────────────────────────────────────────────────────────────

_SENTINEL_MFGS = {
    "",
    "SPECIFY",
    "SPECIFY MFG",
    "SPECIFY MANUFACTURER",
    "OEM",
    "MFG CLIP",
}


# ─────────────────────────────────────────────────────────────────────────────
# Slug helpers
# ─────────────────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    s = (s or "").lower()
    s = _SLUG_RE.sub("_", s).strip("_")
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Typo detection
# ─────────────────────────────────────────────────────────────────────────────


def detect_typos(strings: list[str], threshold: float = 0.85) -> list[tuple[str, str]]:
    """Return pairs (a, b) of similar-but-not-identical strings.

    Conservative threshold so we surface true typos (MOTOTOLA / MOTOROLA)
    without flagging legitimate variants. Owner reviews the report and
    fixes upstream.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────────────────


class Orphans:
    """Collects every datum the script couldn't place into the new schema."""

    def __init__(self) -> None:
        self.unmapped_locations: list[str] = []
        self.unmapped_categories: list[tuple[str, str]] = []  # (catalog_category, display_name)
        self.unknown_model_manufacturers: list[tuple[str, list[str]]] = []  # (model, referenced_by)
        self.unmatched_workbook_part_types: list[str] = []
        self.manufacturer_typos: list[tuple[str, str]] = []

    @property
    def any(self) -> bool:
        return bool(
            self.unmapped_locations
            or self.unmapped_categories
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
            "Unmapped locations (LOCATION_TO_ZONE)",
            [f"`{loc}` — set a zone or leave as `\"\"` for meta/sentinel locations"
             for loc in self.unmapped_locations],
        )
        section(
            "Unmapped categories (CATEGORY_MAP)",
            [f"`{cat}` / `{name}` — add to `_DISPLAY_NAME_TO_CATEGORY`"
             for cat, name in self.unmapped_categories],
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
            [f"`{a}` vs `{b}` — fix one or both in part_catalog.json / parts_library.json / workbook_rules.json"
             for a, b in self.manufacturer_typos],
        )

        return "\n".join(lines) + "\n"


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
    """Collect manufacturers, slugify, detect typos.

    Returns (manufacturers_dict_for_parts_db, typo_pairs).
    """
    raw: set[str] = set()
    for rule in (workbook_rules.get("part_rules") or {}).values():
        for m in rule.get("manufacturer") or []:
            raw.add(m)
    for entry in parts_library.get("parts") or []:
        if entry.get("manufacturer"):
            raw.add(entry["manufacturer"])

    # Filter sentinels (compare case-insensitively)
    real = sorted(
        {m for m in raw if m.strip().upper() not in {s.upper() for s in _SENTINEL_MFGS}}
    )

    # Group by slug — different casings collapse
    by_slug: dict[str, list[str]] = defaultdict(list)
    for m in real:
        by_slug[slugify(m)].append(m)

    manufacturers: dict[str, dict] = {}
    for slug, variants in sorted(by_slug.items()):
        # Prefer Title Case representation, falling back to first variant
        label = max(variants, key=lambda v: sum(1 for c in v if c.isupper())).title()
        manufacturers[slug] = {"label": label}

    typo_pairs = detect_typos(real)
    return manufacturers, typo_pairs


def build_categories() -> dict:
    out: dict[str, dict] = {}
    for cid, label in _PARTS_DB_CATEGORIES.items():
        entry: dict[str, Any] = {"label": label}
        zones = _CATEGORY_ZONES.get(cid)
        if zones:
            entry["applies_to_zones"] = list(zones)
        out[cid] = entry
    return out


def build_color_palette() -> dict:
    """Phase 5 enumerates these for real; Phase 3 seeds the §7 palette."""
    return {
        "red":    {"label": "Red",    "hex": "#E10600", "naming_token": "R"},
        "blue":   {"label": "Blue",   "hex": "#003DA5", "naming_token": "B"},
        "white":  {"label": "White",  "hex": "#FFFFFF", "naming_token": "W"},
        "amber":  {"label": "Amber",  "hex": "#FFA500", "naming_token": "A"},
        "green":  {"label": "Green",  "hex": "#00853E", "naming_token": "G"},
        "purple": {"label": "Purple", "hex": "#8B5CF6", "naming_token": "P"},
    }


def build_location_zones() -> dict:
    return {
        "primary_front": {"label": "Primary Front"},
        "front_corner":  {"label": "Front Corner"},
        "front_side":    {"label": "Front Side"},
        "side":          {"label": "Side"},
        "rear_side":     {"label": "Rear Side"},
        "rear_corner":   {"label": "Rear Corner"},
        "rear":          {"label": "Rear"},
        "rear_interior": {"label": "Rear Interior"},
        "interior":      {"label": "Interior"},
    }


def build_location_zone_map(all_locations: set[str], orphans: Orphans) -> dict:
    out: dict[str, str] = {}
    for loc in sorted(all_locations):
        zone = LOCATION_TO_ZONE.get(loc)
        if zone is None:
            orphans.unmapped_locations.append(loc)
            continue
        if zone == UNKNOWN:
            orphans.unmapped_locations.append(loc)
            continue
        if zone == "":
            # Meta/sentinel — explicitly skip mapping (resolver falls back)
            continue
        out[loc] = zone
    return out


def lookup_manufacturer_for_model(
    model: str, workbook_rules: dict, parts_library: dict
) -> str | None:
    """Try to resolve a model string to a manufacturer slug.

    Resolution order:
      1. parts_library entry with this model_number that has a manufacturer
      2. workbook_rules part_rules whose manufacturer list has exactly one
         real entry (sentinels filtered) AND models list contains this model
      3. MODEL_MANUFACTURER hand-table

    Returns the slug or None if unresolved.
    """
    # 1. parts_library
    for entry in parts_library.get("parts") or []:
        if entry.get("model_number") == model and entry.get("manufacturer"):
            mfg = entry["manufacturer"]
            if mfg.strip().upper() not in {s.upper() for s in _SENTINEL_MFGS}:
                return slugify(mfg)

    # 2. workbook_rules single-manufacturer match
    for rule in (workbook_rules.get("part_rules") or {}).values():
        models = rule.get("models") or []
        if model not in models:
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


def build_products(
    workbook_rules: dict,
    parts_library: dict,
    part_catalog: dict,
    orphans: Orphans,
) -> tuple[dict, dict, dict]:
    """Mint product entries from the (manufacturer × model) cross-product.

    Returns:
      - products dict for parts_db.products
      - part_type_to_products map for legacy_workbook_index
      - model_string_to_product map for legacy_workbook_index
    """
    # Catalog name → catalog_category lookup (for category resolution)
    catalog_category_by_name: dict[str, str] = {}
    for spec in part_catalog.get("parts") or []:
        catalog_category_by_name[spec["display_name"]] = spec["category"]

    products: dict[str, dict] = {}
    # legacy_workbook_index
    part_type_to_products: dict[str, list[str]] = defaultdict(list)
    model_string_to_product: dict[str, str] = {}
    # Track unknown manufacturer models with their referencing part-types
    unknown_models: dict[str, list[str]] = defaultdict(list)

    for part_type_label, rule in (workbook_rules.get("part_rules") or {}).items():
        # Determine the parts_db category for this part-type
        catalog_cat = catalog_category_by_name.get(part_type_label, "")
        category_id = category_for_part(catalog_cat, part_type_label)
        if category_id == UNKNOWN:
            orphans.unmapped_categories.append((catalog_cat, part_type_label))
            continue

        # Light option_axes from the workbook_rule (colors + lens)
        light_option_axes: dict[str, dict] = {}
        if category_id == "lights":
            # Map raw color strings → palette ids
            colors_raw = rule.get("colors") or []
            palette_colors = _extract_palette_colors(colors_raw)
            if palette_colors:
                light_option_axes["colors"] = {
                    "type": "multi_select_from_palette",
                    "min": 1,
                    "max": 3,
                    "allowed": palette_colors,
                }
            lens_raw = rule.get("lens") or []
            if lens_raw:
                # Map to tokens — keep simple: "STANDARD LENS" → standard, "SMOKED LENS" → smoked
                lens_tokens = []
                for lens in lens_raw:
                    if "STANDARD" in lens.upper():
                        lens_tokens.append("standard")
                    elif "SMOKED" in lens.upper():
                        lens_tokens.append("smoked")
                if lens_tokens:
                    light_option_axes["lens"] = {
                        "type": "single_select",
                        "axis_id": "lens",
                        "allowed": sorted(set(lens_tokens)),
                    }

        # Cross-product manufacturer × models. For each model, resolve its
        # manufacturer specifically (using parts_library or hand-table when
        # the workbook_rule lists multiple mfgs).
        models = rule.get("models") or []
        for model in models:
            mfg_slug = lookup_manufacturer_for_model(model, workbook_rules, parts_library)
            if not mfg_slug:
                unknown_models[model].append(part_type_label)
                continue

            product_id = f"{mfg_slug}_{slugify(model)}"
            if product_id not in products:
                products[product_id] = {
                    "manufacturer_id": mfg_slug,
                    "category_id": category_id,
                    "model": model,
                    "description": "",
                    "images": {},
                    "option_axes": dict(light_option_axes),
                    "part_numbers": [{"part_number": model}],
                }
            # Track legacy mappings
            if product_id not in part_type_to_products[part_type_label]:
                part_type_to_products[part_type_label].append(product_id)
            model_string_to_product.setdefault(model, product_id)

    # Record unknown-manufacturer models
    for model, refs in sorted(unknown_models.items()):
        orphans.unknown_model_manufacturers.append((model, sorted(set(refs))))

    return products, dict(part_type_to_products), model_string_to_product


def _extract_palette_colors(colors_raw: list[str]) -> list[str]:
    """Map workbook color strings → palette tokens.

    Workbook colors come as 'Red', 'Red/Blue', 'Red/Blue/Amber', etc.
    Split on '/', lowercase, keep only known palette ids.
    """
    palette = {"red", "blue", "white", "amber", "green", "purple"}
    seen: list[str] = []
    for c in colors_raw:
        for tok in c.split("/"):
            t = tok.strip().lower()
            if t in palette and t not in seen:
                seen.append(t)
    return seen


def build_part_types(workbook_rules: dict, orphans: Orphans) -> dict:
    """Walk every workbook part-type label, group via WORKBOOK_PART_TYPE_GROUPS,
    emit ONE part_type entry per group."""
    part_types: dict[str, dict] = {}
    for label in (workbook_rules.get("part_rules") or {}).keys():
        group = find_part_type_group(label)
        if group is None:
            orphans.unmatched_workbook_part_types.append(label)
            continue
        pid = group["part_type_id"]
        if pid in part_types:
            continue
        part_types[pid] = {
            "label": group["label"],
            "category_id": group["category_id"],
            "predicate": group["predicate"],
            "sequence_scope": group["sequence_scope"],
            "workbook_label_pattern": group["workbook_label_pattern"],
        }
    return part_types


def build_parts_db(inputs: dict, orphans: Orphans) -> dict:
    workbook_rules = inputs["workbook_rules"]
    parts_library = inputs["parts_library"]
    vehicle_layouts = inputs["vehicle_layouts"]
    part_catalog = inputs["part_catalog"]

    manufacturers, typo_pairs = build_manufacturers(workbook_rules, parts_library)
    orphans.manufacturer_typos.extend(typo_pairs)

    categories = build_categories()
    color_palette = build_color_palette()
    location_zones = build_location_zones()
    location_zone_map = build_location_zone_map(collect_all_locations(vehicle_layouts), orphans)
    products, part_type_to_products, model_string_to_product = build_products(
        workbook_rules, parts_library, part_catalog, orphans
    )
    part_types = build_part_types(workbook_rules, orphans)

    return {
        "parts_db": {
            "schema_version": 1,
            "metadata": {
                "last_updated": "2026-06-10T00:00:00Z",
                "updated_by": "migrate_workbook_to_parts_db.py",
            },
            "categories": categories,
            "manufacturers": manufacturers,
            "products": products,
            "option_axes_catalog": {
                "lens": {
                    "label": "Lens Type",
                    "values": {
                        "standard": {"label": "Standard (Clear)"},
                        "smoked":   {"label": "Smoked"},
                    },
                },
            },
            "color_palette": color_palette,
            "location_zones": location_zones,
            "location_zone_map": location_zone_map,
            "part_types": part_types,
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
            "purpose": "Maps legacy workbook part-type strings and model strings to product_ids. Used by manifest_editor and excel_reader during the parts_db transition. Generated by tools/migrate_workbook_to_parts_db.py.",
            "part_type_to_products": part_type_to_products,
            "model_string_to_product": model_string_to_product,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print summary; do not write files")
    parser.add_argument("--write", action="store_true",
                        help="Write parts_db.json + legacy_workbook_index.json")
    parser.add_argument("--orphans-out", default="orphans.md",
                        help="Path for the orphans report (default: orphans.md in CWD)")
    args = parser.parse_args()

    if not args.dry_run and not args.write:
        parser.error("Pick one: --dry-run or --write")

    inputs = load_inputs()
    orphans = Orphans()
    out = build_parts_db(inputs, orphans)

    parts_db = out["parts_db"]
    legacy_index = out["legacy_workbook_index"]

    # Summary to stdout
    print(f"Manufacturers: {len(parts_db['manufacturers'])}")
    print(f"Categories: {len(parts_db['categories'])}")
    print(f"Products: {len(parts_db['products'])}")
    print(f"Part types: {len(parts_db['part_types'])}")
    print(f"Location zone mappings: {len(parts_db['location_zone_map'])}")
    print(f"legacy_workbook_index.part_type_to_products: {len(legacy_index['part_type_to_products'])}")
    print(f"legacy_workbook_index.model_string_to_product: {len(legacy_index['model_string_to_product'])}")
    print()

    orphans_path = Path(args.orphans_out)
    orphans_path.write_text(orphans.to_markdown(), "utf-8")
    print(f"Orphans report → {orphans_path}")
    print(f"  Unmapped locations: {len(orphans.unmapped_locations)}")
    print(f"  Unmapped categories: {len(orphans.unmapped_categories)}")
    print(f"  Unknown model→manufacturer: {len(orphans.unknown_model_manufacturers)}")
    print(f"  Unmatched workbook part-types: {len(orphans.unmatched_workbook_part_types)}")
    print(f"  Manufacturer typo candidates: {len(orphans.manufacturer_typos)}")

    if args.dry_run:
        return 0

    # --write
    if orphans.any:
        print()
        print("REFUSING TO WRITE: orphans remain. Edit the hand-tables in this file "
              "(or fix upstream data) until the orphans report is empty.", file=sys.stderr)
        return 2

    OUTPUT_PARTS_DB.write_text(json.dumps(parts_db, indent=2) + "\n", "utf-8")
    OUTPUT_LEGACY_INDEX.write_text(json.dumps(legacy_index, indent=2) + "\n", "utf-8")
    print(f"Wrote {OUTPUT_PARTS_DB}")
    print(f"Wrote {OUTPUT_LEGACY_INDEX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
