#!/usr/bin/env python3
"""Apply a reviewed per-manufacturer SKU→product mapping into parts_db.json.

Pass 2 apply step. Reads a mapping file (authored during the human-checked
curation, one per manufacturer) and:
  - creates any new products it declares (fits_part_types copied from a
    template sibling),
  - for each link, writes the QBO SKU as a ``part_numbers[]`` entry on its
    product, carrying the SKU's ``qb_item_id`` + ``qb_unit_price`` (read from
    the synced items cache) and its ``vehicle_tags``,
  - drops the descriptive placeholder part_number (the one equal to the product
    model) once a real SKU lands on that product,
  - parses color, secondary_color, and lens_type from the QB item's
    Sales Description (first) or SKU letter patterns (fallback).

Linkage is per part number (a product can hold many SKUs, each its own price) —
matching the catalog reality. Dry-run by default; ``--write`` saves through
save_config_file so the SharePoint mirror fires.

Usage:
  python tools/qb_apply_links.py tools/qb_links/arcti_start.json
  python tools/qb_apply_links.py tools/qb_links/arcti_start.json --write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARTS_DB = REPO / "src" / "dtm_buildsheet" / "resources" / "config" / "parts_db.json"
CACHE = REPO / "workspace" / "quickbooks_items_cache.json"

_QB_FIELDS = ("qb_item_id", "qb_sku", "qb_unit_price", "qb_inactive", "vehicle_tags")

# Light part_type IDs — color/lens data only populated for products fitting these.
# Dynamically loaded from parts_db types with type_id="lights".
_LIGHT_PART_TYPE_IDS: set[str] = set()


def _load_light_part_types(parts_db: dict) -> set[str]:
    """Return the set of part_type_ids under type_id='lights'."""
    pts = parts_db.get("part_types") or {}
    return {pid for pid, pt in pts.items() if pt.get("type_id") == "lights"}


# ── Color / lens parsing from QB item data ───────────────────────────────

# Spelled-out names + common abbreviations.
_COLOR_WORD: dict[str, str] = {
    "RED": "red",
    "BLUE": "blue", "BLU": "blue",
    "AMBER": "amber", "AMB": "amber",
    "WHITE": "white", "WHT": "white", "WHI": "white",
    "GREEN": "green", "GRN": "green",
    "PURPLE": "purple", "PRP": "purple", "PURP": "purple",
}
# Single-letter initials (Whelen compact codes: R-W, BAW, R/B/W, …).
_COLOR_INITIAL: dict[str, str] = {
    "R": "red", "B": "blue", "A": "amber", "W": "white", "G": "green", "P": "purple",
}

_SMOKE_RE = re.compile(r"\b(SMOKED|SMOKE|SMK)\b", re.IGNORECASE)
_CLEAR_RE = re.compile(r"\b(CLEAR|CLR)\b", re.IGNORECASE)
_LENS_STRIP_RE = re.compile(r"\b(SMOKED|SMOKE|SMK|CLEAR|CLR)\b", re.IGNORECASE)
# Programmable multi-color bars (WeCanX): color is per-config, never one fixed set.
_MULTICOLOR_RE = re.compile(r"WE\s?CAN\s?X|WCX|WECAN", re.IGNORECASE)
# "DUO"/"TRIO"/"SPLIT" signals a color-combo follows — lets us trust a bare
# initial run like "BAW" that has no separators.
_COMBO_CTX_RE = re.compile(r"\b(DUO|TRIO|SPLIT|DUAL)\b", re.IGNORECASE)


def _extract_colors(work: str, allow_bare_codes: bool) -> list[str]:
    """Extract an ordered, de-duplicated color list (max 3) from a description.

    Handles spelled-out names, abbreviations, and single-letter initials with
    ``/``, ``-``, space, or no separator. Bare initial runs (no separator, e.g.
    "BAW") are only trusted when a DUO/TRIO/SPLIT context is present, to avoid
    false positives from model codes like "PB" or "MT".
    """
    colors: list[str] = []
    for raw in re.split(r"[\s,]+", work.upper()):
        tok = raw.strip().strip("-/")
        if not tok:
            continue
        had_sep = ("/" in tok) or ("-" in tok)
        for part in re.split(r"[-/]", tok):
            part = re.sub(r"[^A-Z]", "", part)   # strip parens/punctuation: "(AMBER)" → "AMBER"
            if not part:
                continue
            if part in _COLOR_WORD:
                colors.append(_COLOR_WORD[part])
            elif all(ch in _COLOR_INITIAL for ch in part) and 1 <= len(part) <= 3:
                if len(part) == 1:
                    if had_sep:                      # part of e.g. R/B/W
                        colors.append(_COLOR_INITIAL[part])
                elif had_sep or allow_bare_codes:    # "R-W" or "BAW" w/ TRIO ctx
                    colors.extend(_COLOR_INITIAL[ch] for ch in part)
            # else: model code / noise (BLK, MT, XLP, …) — ignore
    seen: list[str] = []
    for c in colors:
        if c not in seen:
            seen.append(c)
    return seen[:3]


def _parse_color_from_item(description: str, sku: str) -> dict[str, str]:
    """Return {color, secondary_color, tertiary_color, lens_type} from QB data.

    Sales Description is the source of truth. Lens: SMOKE/SMK/SMOKED → smoked,
    CLEAR/CLR → clear, else (with a color) defaults clear. SKU prefix ``X`` is a
    weak smoked fallback only. Programmable multi-color (WeCanX) bars get no
    fixed color.
    """
    result = {"color": "", "secondary_color": "", "tertiary_color": "", "lens_type": ""}
    desc = (description or "").upper().strip()
    sku_upper = (sku or "").upper().strip()

    # ── Lens ──
    if _SMOKE_RE.search(desc):
        result["lens_type"] = "smoked"
    elif _CLEAR_RE.search(desc):
        result["lens_type"] = "clear"

    # ── Color ── (skip programmable multi-color bars entirely)
    if not _MULTICOLOR_RE.search(desc):
        work = _LENS_STRIP_RE.sub(" ", desc)
        colors = _extract_colors(work, allow_bare_codes=bool(_COMBO_CTX_RE.search(desc)))
        if colors:
            result["color"] = colors[0]
            if len(colors) > 1:
                result["secondary_color"] = colors[1]
            if len(colors) > 2:
                result["tertiary_color"] = colors[2]

    # ── Smoked fallback via SKU prefix X (only if desc gave no lens) ──
    if not result["lens_type"] and sku_upper.startswith("X") and len(sku_upper) > 1:
        result["lens_type"] = "smoked"

    # ── Default to clear when a color is present but no lens stated ──
    if not result["lens_type"] and result["color"]:
        result["lens_type"] = "clear"

    return result


def load_cache_index() -> dict:
    """name (part number) → {qb_item_id, unit_price, sku, description} from the synced cache."""
    if not CACHE.exists():
        print(f"items cache not found ({CACHE}). Pull items in the app first.", file=sys.stderr)
        sys.exit(2)
    data = json.loads(CACHE.read_text("utf-8"))
    return {it.get("name", ""): it for it in data.get("items", [])}


def apply_mapping(parts_db: dict, mapping: dict, cache: dict) -> list[str]:
    """Mutate parts_db in place per the mapping. Returns a list of action lines.

    Raises ValueError on any unresolvable reference so nothing is half-applied.
    """
    global _LIGHT_PART_TYPE_IDS
    if not _LIGHT_PART_TYPE_IDS:
        _LIGHT_PART_TYPE_IDS = _load_light_part_types(parts_db)

    products = parts_db.setdefault("products", {})
    actions: list[str] = []

    # 0. Correct fits_part_types on existing products (re-categorization).
    for pid, fits in (mapping.get("set_fits") or {}).items():
        if pid not in products:
            raise ValueError(f"set_fits references unknown product: {pid}")
        if products[pid].get("fits_part_types") != fits:
            products[pid]["fits_part_types"] = list(fits)
            actions.append(f"~ {pid}: fits_part_types → {fits}")

    # 0b. Rename existing products' display model (proper Whelen name vs the
    #     uppercase workbook string). model feeds naming_rules.product_display_name.
    for pid, new_model in (mapping.get("rename") or {}).items():
        if pid not in products:
            raise ValueError(f"rename references unknown product: {pid}")
        old_model = products[pid].get("model", "")
        if old_model != new_model:
            products[pid]["model"] = new_model
            actions.append(f"~ {pid}: model {old_model!r} → {new_model!r}")

    # 0c. Wire product-level accessories (Phase 5). Each entry:
    #     {"category": <accessory_category>, "product_id": <accessory product>,
    #      "required": bool}. Surfaced as per-category dropdowns in the picker.
    for pid, accs in (mapping.get("set_accessories") or {}).items():
        if pid not in products:
            raise ValueError(f"set_accessories references unknown product: {pid}")
        products[pid]["accessories"] = list(accs)
        actions.append(f"~ {pid}: accessories → {[a.get('product_id') for a in accs]}")

    # 0d. New part_types (generic accessory slots, e.g. the bracket_mount home
    #     for product-level lightbar/howler/ION mount kits). Idempotent: skipped
    #     if the id already exists. Each entry carries the fields verbatim
    #     (label, type_id, accessory_category, optional accessory_of/pattern).
    part_types = parts_db.setdefault("part_types", {})
    for npt in mapping.get("new_part_types", []):
        ptid = npt["part_type_id"]
        if ptid in part_types:
            continue
        spec = {
            "label": npt["label"],
            "type_id": npt.get("type_id", "lights"),
            "tree_positions": list(npt.get("tree_positions") or []),
            "tag_ids": list(npt.get("tag_ids") or []),
        }
        for k in ("workbook_label_pattern", "sequence_scope", "accessory_of",
                  "accessory_category", "category"):
            if npt.get(k) is not None:
                spec[k] = npt[k]
        part_types[ptid] = spec
        actions.append(f"+ new part_type {ptid}  (label {npt['label']!r})")

    # 1. New products (copy fits_part_types from the template sibling).
    template_id = mapping.get("template_product")
    template = products.get(template_id, {}) if template_id else {}
    for np in mapping.get("new_products", []):
        pid = np["product_id"]
        if pid in products:
            continue
        products[pid] = {
            "manufacturer_id": mapping["manufacturer_id"],
            "model": np["model"],
            "fits_part_types": list(np.get("fits_part_types")
                                    or template.get("fits_part_types") or []),
            "tag_ids": [],
            "description": np.get("description", ""),
            "images": {},
            "part_numbers": [],
        }
        actions.append(f"+ new product {pid}  (model {np['model']!r})")

    # 2. Links → part_number entries.
    for link in mapping.get("links", []):
        sku = link["sku"]
        pid = link["product"]
        if pid not in products:
            raise ValueError(f"link references unknown product: {pid}")
        item = cache.get(sku)
        if item is None:
            raise ValueError(f"SKU not in items cache (pull items?): {sku!r}")

        spec = products[pid]
        pns = spec.setdefault("part_numbers", [])
        # Drop the descriptive placeholder once a real SKU is attached.
        model = str(spec.get("model", "")).strip().lower()
        pns[:] = [p for p in pns
                  if str(p.get("part_number", "")).strip().lower() != model
                  or str(p.get("qb_item_id", "")).strip()]

        # Parse color / lens from the QB item
        desc = item.get("description") or item.get("sales_description") or ""
        color_info = _parse_color_from_item(desc, sku)

        # Only keep color/lens data for light products (fits at least one light part_type).
        # Non-light items (partitions, seats, cargo decks) often have color-adjacent
        # words in descriptions that produce false positives.
        product_fits = set(spec.get("fits_part_types") or [])
        is_light = bool(product_fits & _LIGHT_PART_TYPE_IDS)
        if not is_light:
            color_info = {"color": "", "secondary_color": "", "tertiary_color": "", "lens_type": ""}

        entry = {
            "part_number": sku,
            "qb_item_id": str(item.get("qb_item_id", "")),
            "qb_sku": str(item.get("sku", "")),
            "qb_unit_price": item.get("unit_price"),
            "qb_inactive": False,
            "vehicle_tags": list(link.get("vehicle_tags") or ["any"]),
            "color": color_info["color"],
            "secondary_color": color_info["secondary_color"],
            "tertiary_color": color_info.get("tertiary_color", ""),
            "lens_type": color_info["lens_type"],
        }
        # Optional curated short description shown in the accessory picker dropdown.
        # Only written when the link supplies it, so re-applying a mapping that
        # omits it never wipes a name set elsewhere (part-manager UI / earlier run).
        if link.get("friendly_name") is not None:
            entry["friendly_name"] = link["friendly_name"]
        existing = next((p for p in pns if p.get("part_number") == sku), None)
        if existing:
            existing.update(entry)
            color_str = f" {entry['color']}"
            if entry["secondary_color"]:
                color_str += f"/{entry['secondary_color']}"
            if entry["lens_type"]:
                color_str += f" ({entry['lens_type']})"
            actions.append(f"~ {pid}: update {sku}  (${entry['qb_unit_price']}{color_str})")
        else:
            pns.append(entry)
            color_label = f" {entry['color']}"
            if entry["secondary_color"]:
                color_label += f"/{entry['secondary_color']}"
            if entry["lens_type"]:
                color_label += f" ({entry['lens_type']})"
            actions.append(f"+ {pid}: link {sku}  (${entry['qb_unit_price']}, "
                           f"veh {entry['vehicle_tags']}{color_label})")

    # 3. Move an already-linked part_number from one product to another (splits).
    #    Relocates the existing entry verbatim (keeps qb data + parsed color/lens).
    for mv in (mapping.get("move") or []):
        sku, src, dst = mv["sku"], mv["from"], mv["to"]
        if src not in products:
            raise ValueError(f"move 'from' references unknown product: {src}")
        if dst not in products:
            raise ValueError(f"move 'to' references unknown product: {dst}")
        src_pns = products[src].setdefault("part_numbers", [])
        entry = next((p for p in src_pns if p.get("part_number") == sku), None)
        if entry is None:
            raise ValueError(f"move: {sku!r} not found on {src}")
        src_pns.remove(entry)
        dst_pns = products[dst].setdefault("part_numbers", [])
        if not any(p.get("part_number") == sku for p in dst_pns):
            dst_pns.append(entry)
        actions.append(f"→ move {sku}: {src} ⇒ {dst}")

    # 4. Delete products (only when emptied of real SKUs — safety guard).
    for pid in (mapping.get("delete_products") or []):
        if pid not in products:
            continue
        leftover = [p for p in (products[pid].get("part_numbers") or [])
                    if str(p.get("qb_item_id", "")).strip()]
        if leftover:
            raise ValueError(f"refusing to delete {pid}: still holds linked SKUs "
                             f"{[p['part_number'] for p in leftover]}")
        del products[pid]
        actions.append(f"- delete product {pid}")
    return actions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mapping", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if not args.mapping.exists():
        print(f"mapping not found: {args.mapping}", file=sys.stderr)
        return 2

    mapping = json.loads(args.mapping.read_text("utf-8"))
    parts_db = json.loads(PARTS_DB.read_text("utf-8"))
    cache = load_cache_index()

    try:
        actions = apply_mapping(parts_db, mapping, cache)
    except ValueError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1

    print(f"manufacturer: {mapping.get('manufacturer_id')}  ({len(actions)} actions)")
    for a in actions:
        print(f"  {a}")

    if not args.write:
        print("\n(dry run — re-run with --write to save through save_config_file)")
        return 0

    sys.path.insert(0, str(REPO / "src"))
    from dtm_buildsheet.app.services.config_service import save_config_file
    from dtm_buildsheet.paths import AppPaths
    result = save_config_file("parts_db.json", parts_db, AppPaths())
    if not result.get("ok"):
        print(f"Cloud push failed: {result.get('error')}", file=sys.stderr)
        return 3
    tag = "queued for retry" if result.get("queued") else "direct-mirrored to SharePoint"
    print(f"\n☁  parts_db.json → {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
