from __future__ import annotations

import copy
import re
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...paths import AppPaths
from ..services.config_service import save_config_file
from ..services.parts_db_service import get_parts_db_service
from .http import send_json


_PREFIX = "/api/parts-db"
_TYPES_PATH = f"{_PREFIX}/types"
_SECTIONS_PATH = f"{_PREFIX}/sections"
_ZONES_PATH = f"{_PREFIX}/zones"
_SUB_ZONES_PATH = f"{_PREFIX}/sub-zones"
_BUILD_ATTRS_PATH = f"{_PREFIX}/build-attributes"
_TAGS_PATH = f"{_PREFIX}/tags"
_SERVICES_PATH = f"{_PREFIX}/services"
_MANUFACTURERS_PATH = f"{_PREFIX}/manufacturers"
_PART_TYPES_PATH = f"{_PREFIX}/part-types"
_PRODUCTS_PATH = f"{_PREFIX}/products"
_VALIDATE_PATH = f"{_PREFIX}/validate-placement"
_MANIFEST_DATA_PATH = f"{_PREFIX}/manifest-data"
_CATEGORY_ZONES_PATH = f"{_PREFIX}/category-zones"
_ZONE_PRODUCTS_PATH = f"{_PREFIX}/zone-products"
_PLACEMENTS_PATH = f"{_PREFIX}/placements"
_CATEGORY_LOCATIONS_PATH = f"{_PREFIX}/category-locations"
_CATEGORY_SKUS_PATH = f"{_PREFIX}/category-skus"
_BROWSE_TREE_PATH = f"{_PREFIX}/browse-tree"
_MANIFEST_GROUPS_PATH = f"{_PREFIX}/manifest-groups"
_MATCH_SKUS_PATH = f"{_PREFIX}/match-skus"
_RESOLVE_PATH = f"{_PREFIX}/resolve-selection"
_ACCESSORIES_PATH = f"{_PREFIX}/accessories"
_TRACER_HEADS_PATH = f"{_PREFIX}/tracer-heads"
_EDIT_PREFIX = f"{_PREFIX}/edit"


# Physical placement_zones relevant to each light category — drives the
# location-last step. Sub-zones (primary_front, front_corner, etc.) are
# collapsed to tree-level views (front/side/rear/roof/interior) because
# category-level placements accept all locations in a view.
_CATEGORY_PLACEMENT_ZONES = {
    "warning":   ["front", "side", "rear"],
    "scene":     ["front", "side", "rear", "roof"],
    "interior":  ["interior"],
    "interior_bar": ["interior", "roof"],
    "roof_bar":  ["roof"],
    "spotlight": ["front", "side"],
}
# placement_zone → broad tree zone.  Used by _resolve_category_locations to
# test whether a placement's sub-zone belongs to a category's view(s).
_PLACEMENT_ZONE_TO_TREE = {
    "primary_front": "front", "front_corner": "front", "front_side": "front",
    "side": "side", "rear_side": "side", "rear_interior": "side",
    "rear": "rear", "rear_corner": "rear",
    "interior": "interior", "roof": "roof",
}
_TREE_PRIMARY_KEYWORD = {"front": "forward", "side": "side", "rear": "rear"}


# Tree-navigation zone → physical placement_zones (lights placement step).
# Judgment mapping; candidate to move into parts_db.json placement_zones as a
# `tree_zone` field so the team can edit it without a release.
_ZONE_TO_PLACEMENT_ZONES = {
    "front": ["primary_front", "front_corner", "front_side"],
    "side": ["side"],
    "rear": ["rear", "rear_corner", "rear_side"],
    "roof": ["roof"],
    "prisoner_area": ["rear_interior"],   # cargo-window warnings; not dash/headliner
    "forward_of_cage": ["interior"],
    "interior": ["interior", "rear_interior"],
}
# Skip-zone light categories derive their placement_zones from the category.
_CATEGORY_TO_PLACEMENT_ZONES = {
    "roof_bar": ["roof"],
    "visor_bar": ["interior"],
    "interior": ["interior", "rear_interior"],
}
# Light category id → keyword matched against part_type labels, so the product
# grid for a category shows only that category's products (e.g. warning vs scene).
_CATEGORY_KEYWORDS = {
    "warning": "warning",
    "scene": "scene",
    "interior": "interior",
    "roof_bar": "roof",
    "visor_bar": "visor",
    "spotlight": "spot",
}
_FIXTURE_PART_ALIASES = {
    # The legacy renderer/catalog name predates the parts_db part_type id.
    "front_interior_light_bar": "interior_light_bar_front",
}


def _pt_matches_category(label: str, category: str) -> bool:
    """Legacy keyword fallback for parts that lack an explicit category."""
    kw = _CATEGORY_KEYWORDS.get(category, category)
    return bool(kw) and kw.lower() in (label or "").lower()


def _pt_in_category(pt, category: str) -> bool:
    """True if a part_type belongs to a category — explicit field first,
    keyword fallback for any part_type not yet tagged."""
    if not category:
        return True
    if pt.category:
        return pt.category == category
    return _pt_matches_category(pt.label, category)


# Per-zone keyword used to pick the "primary" part_type a physical location
# falls back to when no legacy location→part_type mapping exists.
_ZONE_PRIMARY_KEYWORD = {"front": "forward", "side": "side", "rear": "rear"}


def _primary_part_type(candidates: list, zone_id: str):
    """Pick the default part_type for a zone (e.g. front → Forward Warning)."""
    if not candidates:
        return None
    kw = _ZONE_PRIMARY_KEYWORD.get(zone_id, "")
    if kw:
        for pt in candidates:
            if kw in (pt.label or "").lower():
                return pt
    return candidates[0]


# Warning lights have ONE home (warning_light); the zone is chosen at placement
# and only supplies the friendly base name. front→Forward Warning, side→Side
# Warning, rear→Rear Warning (fine-grained legacy zones collapse to these three).
_WARNING_ZONE_NAME = {"front": "Forward Warning", "side": "Side Warning", "rear": "Rear Warning"}


def _warning_home(candidates: list):
    """The single warning-light part_type home (id `warning_light`)."""
    return (next((pt for pt in candidates if pt.part_type_id == "warning_light"), None)
            or next((pt for pt in candidates if (pt.label or "").strip().lower() == "warning light"), None))


def _resolve_category_locations(svc, type_id: str, category: str) -> list[dict]:
    """Locations for the category's location-last step.

    Warning: all placements resolve to the single `warning_light` home; the name
    comes from the placement's tree zone (Forward/Side/Rear Warning) — zones are
    friendly-naming only, not part_types. Other categories map each placement to
    a candidate part_type by tree zone.
    """
    candidates = [pt for pt in svc.list_part_types()
                  if pt.type_id == type_id and _pt_in_category(pt, category)]
    if not candidates:
        return []

    doc = svc.raw_doc()
    placements_doc = doc.get("placements") or {}
    pzones = set(_CATEGORY_PLACEMENT_ZONES.get(category, []))

    # tree_zone → part_type used only for NON-warning categories' naming.
    zone_pt: dict[str, object] = {}
    if category != "warning":
        _zone_keyword = {"front": "forward", "side": "side", "rear": "rear"}
        for tree, kw in _zone_keyword.items():
            for pt in candidates:
                if kw in (pt.label or "").lower() and any(p.zone == tree for p in pt.tree_positions):
                    zone_pt[tree] = pt
                    break

    warn_home = _warning_home(candidates) if category == "warning" else None
    out: list[dict] = []
    for loc, spec in placements_doc.items():
        pz = spec.get("placement_zone", "")
        tree_zone = _PLACEMENT_ZONE_TO_TREE.get(pz, "")
        if tree_zone not in pzones:
            continue
        if category == "warning":
            base = _WARNING_ZONE_NAME.get(tree_zone, "Warning")
            pt_id = warn_home.part_type_id if warn_home else "warning_light"
        else:
            pt = zone_pt.get(tree_zone)
            if pt is None:
                continue
            base = pt.label
            pt_id = pt.part_type_id
        out.append({
            "location": loc,
            "placement_zone": pz,
            "part_type_id": pt_id,
            "name_pattern": f"{base} {{n}}",
            "base_label": base,
            "has_coords": True,
        })
    out.sort(key=lambda x: x["location"])
    return out


def _build_browse_tree(svc) -> list[dict]:
    """`category (type) -> family -> part_type` tree for the picker sidebar
    accordion (PICKER_REDESIGN.md Step 1). Server-derived so the client
    renders only — it does not reconstruct the hierarchy.

    A part_type is a tree node (bare, under its own type_id, or nested inside
    a family) unless it's an explicit accessory (`accessory_of` set) — those
    are surfaced through the accessories panel, not the browse tree. A
    family's members are listed under the family regardless of each member's
    own `type_id` (families are a cross-cutting browse concept, e.g. an
    Equipment part_type can belong to a Structural family — see
    docs/PARTS_DB_AND_PICKER.md).

    Ordering + selectability (owner rulings 2026-07-10, flaws #7+#8): within
    each category, families sort first (by `order`, then label), standalones
    after (by label). A family carries `selectable` (its header alone can be
    clicked to filter by `picker_flow` — same handoff as a leaf) and
    `browse_collapsed` (render as a single selectable row with no members,
    e.g. Scene/Spotlight). A member's own `picker_flow` is its part_type's
    `category` field (falling back to the family's), so a mixed-flow family
    like Light Bars can carry members with different flows.
    """
    doc = svc.raw_doc()
    part_types_doc: dict = doc.get("part_types") or {}
    families_doc: dict = doc.get("families") or {}

    def label_of(pt_id: str) -> str:
        return (part_types_doc.get(pt_id) or {}).get("label", pt_id)

    in_family: set[str] = set()
    families_by_type: dict[str, list[dict]] = {}
    for family_id, spec in families_doc.items():
        members = [m for m in (spec.get("members") or []) if m in part_types_doc]
        in_family.update(members)
        type_id = spec.get("category", "")
        family_flow = spec.get("picker_flow")
        families_by_type.setdefault(type_id, []).append({
            "kind": "family",
            "family_id": family_id,
            "label": spec.get("label", family_id),
            "picker_flow": family_flow,
            "order": spec.get("order", 999),
            "selectable": bool(spec.get("selectable", False)),
            "browse_collapsed": bool(spec.get("browse_collapsed", False)),
            # Each member carries its OWN flow (its part_type's `category`
            # field) rather than always inheriting the family's — needed for
            # mixed-flow families like Light Bars (interior_bar + roof_bar
            # members under one family with no single picker_flow). A member
            # can also be `browse_hidden` (e.g. `warning_light`, whose home is
            # covered entirely by the Warning header's own selectable click,
            # per owner ruling 2026-07-10 — "eliminates the redundant
            # sub-leaf") — it STAYS in `members` (so edit-mode pre-fill/
            # type-lock can still resolve it to this family) but the client
            # must not render it as a clickable leaf.
            "members": [
                {
                    "part_type_id": m,
                    "label": label_of(m),
                    "picker_flow": (part_types_doc.get(m) or {}).get("category") or family_flow,
                    "browse_hidden": bool((part_types_doc.get(m) or {}).get("browse_hidden", False)),
                }
                for m in members
            ],
        })

    bare_by_type: dict[str, list[dict]] = {}
    for pt_id, spec in part_types_doc.items():
        if spec.get("accessory_of"):
            continue
        if spec.get("accessory_category"):
            continue
        if spec.get("browse_hidden"):
            continue
        if pt_id in in_family:
            continue
        type_id = spec.get("type_id", "")
        bare_by_type.setdefault(type_id, []).append({
            "kind": "part_type",
            "part_type_id": pt_id,
            "label": spec.get("label", pt_id),
        })

    types_doc: dict = doc.get("types") or {}
    out: list[dict] = []
    for type_id, tspec in types_doc.items():
        # Families first (by `order`, then label), then bare part_types (by
        # label) — owner ruling 2026-07-10 (flaws #7+#8): every category is
        # dropdowns/families first, standalones below.
        families = sorted(families_by_type.get(type_id, []), key=lambda c: (c.get("order", 999), c["label"]))
        standalones = sorted(bare_by_type.get(type_id, []), key=lambda c: c["label"])
        children = families + standalones
        out.append({"type_id": type_id, "label": tspec.get("label", type_id), "children": children})
    return out


def _build_manifest_groups(svc) -> dict:
    """Sales/build-manifest grouping model.

    The picker browse tree is a navigation taxonomy; the manifest needs a
    scan/order taxonomy that matches how a salesperson thinks through a car.
    `manifest_groups` provides that layer and resolves every part_type to a
    main group + subgroup with specificity: explicit part_type, family, type,
    then zone fallback.
    """
    doc = svc.raw_doc()
    part_types: dict = doc.get("part_types") or {}
    families: dict = doc.get("families") or {}
    groups: list[dict] = list((doc.get("manifest_groups") or {}).get("groups") or [])

    family_for_pt: dict[str, str] = {}
    for fid, family in families.items():
        for pt_id in family.get("members") or []:
            family_for_pt.setdefault(pt_id, fid)

    def _ids(spec: dict, key: str) -> set[str]:
        return {str(x) for x in (spec.get(key) or []) if str(x)}

    def _pt_zones(pt: dict) -> set[str]:
        return {str(pos.get("zone", "")) for pos in (pt.get("tree_positions") or []) if pos.get("zone")}

    def _matches(spec: dict, pt_id: str, pt: dict, family_id: str, specificity: str) -> bool:
        if specificity == "part_type":
            return pt_id in _ids(spec, "part_types")
        if specificity == "family":
            return bool(family_id and family_id in _ids(spec, "families"))
        if specificity == "type":
            return pt.get("type_id", "") in _ids(spec, "type_ids")
        if specificity == "zone":
            return bool(_pt_zones(pt) & _ids(spec, "zones"))
        return False

    def _pick(pt_id: str, pt: dict) -> tuple[dict | None, dict | None]:
        family_id = family_for_pt.get(pt_id, "")
        for specificity in ("part_type", "family", "type", "zone"):
            for group in groups:
                for subgroup in group.get("subgroups") or []:
                    if _matches(subgroup, pt_id, pt, family_id, specificity):
                        return group, subgroup
                if _matches(group, pt_id, pt, family_id, specificity):
                    fallback = {
                        "subgroup_id": group.get("group_id", "group"),
                        "label": group.get("label", "Other"),
                        "order": 999,
                    }
                    return group, fallback
        return None, None

    part_type_map: dict[str, dict] = {}
    legacy_label_map: dict[str, str] = {}
    ordered_groups: dict[str, dict] = {}

    def _ensure_group(group: dict) -> dict:
        gid = group.get("group_id", "_other")
        if gid not in ordered_groups:
            ordered_groups[gid] = {
                "group_id": gid,
                "label": group.get("label", "Other"),
                "order": int(group.get("order", 999)),
                "subgroups": [],
            }
        return ordered_groups[gid]

    def _add_subgroup(out_group: dict, subgroup: dict) -> dict:
        sid = subgroup.get("subgroup_id", out_group["group_id"])
        section_key = f"{out_group['group_id']}:{sid}"
        found = next((s for s in out_group["subgroups"] if s["section_key"] == section_key), None)
        if found is None:
            found = {
                "section_key": section_key,
                "subgroup_id": sid,
                "label": subgroup.get("label", out_group["label"]),
                "order": int(subgroup.get("order", 999)),
                "part_types": [],
            }
            out_group["subgroups"].append(found)
        return found

    for pt_id, pt in part_types.items():
        if pt.get("accessory_of") or pt.get("accessory_category"):
            continue
        group, subgroup = _pick(pt_id, pt)
        if group is None or subgroup is None:
            group = {"group_id": "_other", "label": "Other", "order": 999}
            subgroup = {"subgroup_id": "_other", "label": "Other", "order": 999}
        out_group = _ensure_group(group)
        out_subgroup = _add_subgroup(out_group, subgroup)
        out_subgroup["part_types"].append(pt_id)
        part_type_map[pt_id] = {
            "group_id": out_group["group_id"],
            "group_label": out_group["label"],
            "group_order": out_group["order"],
            "section_key": out_subgroup["section_key"],
            "section_label": out_subgroup["label"],
            "section_order": out_subgroup["order"],
        }
        label = (pt.get("label") or "").strip().lower()
        if label:
            legacy_label_map[label] = out_subgroup["section_key"]

    for group in ordered_groups.values():
        group["subgroups"].sort(key=lambda s: (s["order"], s["label"]))
        for subgroup in group["subgroups"]:
            subgroup["part_types"].sort()

    ordered = sorted(ordered_groups.values(), key=lambda g: (g["order"], g["label"]))
    return {
        "groups": ordered,
        "part_type_map": part_type_map,
        "legacy_label_map": legacy_label_map,
    }


def _catalog_parts_for_label(catalog_parts: list, label: str) -> list:
    """Catalog parts whose display_name matches a part_type label (ignoring a
    trailing sequence number). These are the names the planner actually renders."""
    import re as _re
    ll = (label or "").strip().lower()
    out = []
    for p in catalog_parts:
        dn = (p.get("display_name") or "").strip()
        base = _re.sub(r"\s+\d+$", "", dn).strip().lower()
        if base == ll or dn.lower() == ll:
            out.append(p)
    return out


def _catalog_parts_for_part_type(catalog_parts: list, pt) -> list:
    labels = [pt.label]
    wb = (pt.workbook_label_pattern or "").strip()
    if wb and "{" not in wb:
        labels.append(wb)
    out: list[dict] = []
    seen: set[str] = set()
    for label in labels:
        for p in _catalog_parts_for_label(catalog_parts, label):
            key = p.get("part_id") or p.get("display_name") or id(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def _default_views_for_label(catalog_parts: list, label: str) -> set[str]:
    views: set[str] = set()
    for p in _catalog_parts_for_label(catalog_parts, label):
        views |= set(p.get("default_views") or [])
    return views


def _fixture_catalog_id(part_type_id: str) -> str:
    return _FIXTURE_PART_ALIASES.get(part_type_id, part_type_id)


def _catalog_part_by_id(catalog_parts: list, part_id: str) -> dict:
    for p in catalog_parts:
        if p.get("part_id") == part_id:
            return p
    return {}


def _resolve_product_locations(svc, paths, type_id: str, category: str,
                               product_id: str, vehicle: str) -> list[dict]:
    """Locations a specific PRODUCT can go, guaranteed to render.

    Driven by the schema's `fits_part_types` (intersected with the category) AND
    each part_type's catalog `default_views`: a location is only offered if it
    exists in the vehicle layout in one of the part's render views — exactly the
    test the planner applies — so every offered placement loads in the preview.
    Curated workbook-rule locations are preferred where present.
    """
    from ..services.config_service import load_config_file
    product = svc.get_product(product_id)
    if not product:
        return _resolve_category_locations(svc, type_id, category)

    catalog_parts = (load_config_file("part_catalog.json", paths).get("parts") or [])
    layouts = load_config_file("vehicle_layouts.json", paths)
    views_doc = (layouts.get("vehicles", {}).get(vehicle, {}).get("views") or {})
    # name (upper) → set of views it has coords in, for this vehicle
    loc_views: dict[str, set] = {}
    for vk, vd in views_doc.items():
        for name in (vd.get("locations") or {}):
            loc_views.setdefault(name.upper(), set()).add(vk)

    cat_pts = [pt for pt in svc.list_part_types()
               if pt.type_id == type_id and _pt_in_category(pt, category)]
    fit = [pt for pt in cat_pts if pt.part_type_id in (product.fits_part_types or [])]
    if not fit:
        fit = cat_pts
    fit.sort(key=lambda pt: 0 if svc.locations_by_legacy_name(pt.label) else 1)

    doc = svc.raw_doc()
    placements_doc = doc.get("placements") or {}
    pzones_doc = doc.get("placement_zones") or {}
    out: list[dict] = []
    seen: set[str] = set()
    for pt in fit:
        cparts = _catalog_parts_for_part_type(catalog_parts, pt)
        dviews: set[str] = set()
        for p in cparts:
            dviews |= set(p.get("default_views") or [])
        # Does this part_type render a diagram icon anywhere? Lights/structural do;
        # most equipment + interior parts (radios, consoles, gun racks) do not —
        # they're line items with a mount location but no dot on the vehicle view.
        renders = bool(dviews) and any(
            (p.get("render_kind") or "none") != "none" for p in cparts)
        # The exact names the planner renders (catalog display_names), sorted so
        # the picker assigns the lowest unused one (e.g. Forward Warning 1, 2).
        catalog_names = sorted(
            (p.get("display_name") or "").strip() for p in cparts if (p.get("display_name") or "").strip())
        # Curated locations, in precedence: the part_type's rendered placement
        # allow-list → editable
        # location_options (Part Manager) → the legacy workbook list (minus
        # "specify" placeholders). Renderable options become diagram dots; the
        # rest stay in the picker's location dropdown.
        raw_pt = (doc.get("part_types") or {}).get(pt.part_type_id) or {}
        allowed = [str(l).strip().upper() for l in (raw_pt.get("allowed_placements") or [])
                   if str(l).strip()]
        edited = [str(l).strip().upper() for l in (raw_pt.get("location_options") or [])
                  if str(l).strip()]
        ruled = edited or [l.upper() for l in svc.locations_by_legacy_name(pt.label)
                           if "SPECIFY" not in l.upper()]
        if allowed:
            cand = allowed
        elif ruled:
            cand = ruled
        elif renders:
            # Diagram part with no curated list: any location that has coordinates
            # in one of the part's render views (so the dot loads in the preview).
            cand = [k for k, vs in loc_views.items() if vs & dviews]
        else:
            cand = []   # no curated list and nothing renders → needs no location
        for key in cand:
            if key in seen:
                continue
            seen.add(key)
            pz = (placements_doc.get(key) or {}).get("placement_zone", "")
            # A location shows as a diagram dot only if it has coords in one of the
            # part's render views; otherwise the picker offers it in the dropdown.
            has_coords = renders and bool(loc_views.get(key, set()) & dviews)
            out.append({
                "location": key,
                "placement_zone": pz,
                "placement_zone_label": (pzones_doc.get(pz) or {}).get("label", pz),
                "part_type_id": pt.part_type_id,
                "name_pattern": pt.workbook_label_pattern or pt.label,
                "base_label": pt.label,
                "catalog_names": catalog_names,
                "has_coords": has_coords,
            })
    out.sort(key=lambda x: x["location"])
    return out


def _resolve_accessories(svc, product_id: str) -> list[dict]:
    """Resolve a product's accessories, grouped by accessory_category.

    Two sources, unioned: product-level ``accessories`` (explicit, may be
    ``required``) and part_type-level (any product fitting an accessory part_type
    whose ``accessory_of`` matches one of this product's ``fits_part_types``).
    Returns ``[{category, label, required, options:[{product_id, model, skus}]}]``
    ordered by the accessory_categories vocabulary.
    """
    doc = svc.raw_doc()
    products = doc.get("products") or {}
    part_types = doc.get("part_types") or {}
    acc_cats = doc.get("accessory_categories") or {}
    mfrs = doc.get("manufacturers") or {}
    prod = products.get(product_id)
    if not prod:
        return []

    groups: dict[str, dict] = {}

    def add(category: str, acc_pid: str, required: bool) -> None:
        if not category or not acc_pid or acc_pid == product_id or acc_pid not in products:
            return
        g = groups.setdefault(category, {"required": False, "option_ids": []})
        if required:
            g["required"] = True
        if acc_pid not in g["option_ids"]:
            g["option_ids"].append(acc_pid)

    # Product-specific relationships are more precise than part_type-level
    # fallbacks. Keep an inverse lookup as well: an accessory which belongs to
    # a named product must not leak into every other product that happens to
    # share its accessory part_type. For example, an U-Series mirror mount is
    # a warning-light bracket in the catalog, but it is not a Mega T bracket.
    specific_parents_by_accessory: dict[str, set[str]] = {}
    for parent_id, parent in products.items():
        for relationship in parent.get("accessories") or []:
            accessory_id = relationship.get("product_id")
            if accessory_id in products:
                specific_parents_by_accessory.setdefault(accessory_id, set()).add(parent_id)
    for accessory_id, accessory in products.items():
        for parent_id in accessory.get("accessory_of_products") or []:
            if parent_id in products:
                specific_parents_by_accessory.setdefault(accessory_id, set()).add(parent_id)

    # If a product curates a category explicitly, do not union in every
    # generic accessory part_type for that same category — unless that
    # relationship deliberately opts back in via ``include_generic``. This is
    # for products such as Mega T-Series, which have a product-specific mount
    # in addition to their normal compatible bracket choices.
    specific_categories: set[str] = set()
    for a in prod.get("accessories") or []:
        category = a.get("category")
        if category and not a.get("include_generic"):
            specific_categories.add(category)
    for ap in products.values():
        if product_id in (ap.get("accessory_of_products") or []):
            specific_categories.add(ap.get("accessory_category") or "other")

    # 1. Product-level accessories.
    for a in prod.get("accessories") or []:
        add(a.get("category"), a.get("product_id"), bool(a.get("required")))

    # 2. Part_type-level: accessory part_types whose parent is one of our fits.
    fits = set(prod.get("fits_part_types") or [])
    if fits:
        acc_pt_cat = {pt_id: (pt.get("accessory_category") or "other")
                      for pt_id, pt in part_types.items()
                      if pt.get("accessory_of") in fits}
        if acc_pt_cat:
            for apid, ap in products.items():
                ap_fits = set(ap.get("fits_part_types") or [])
                for pt_id, cat in acc_pt_cat.items():
                    if cat in specific_categories:
                        continue
                    specific_parents = specific_parents_by_accessory.get(apid)
                    if specific_parents and product_id not in specific_parents:
                        continue
                    # A product can be filed under an accessory part type for
                    # catalog purposes while waiting for its actual parent
                    # picker (for example, a Westin light channel). It must
                    # not appear as a universal bracket in the meantime.
                    if ap.get("include_in_generic_accessory_options") is False:
                        continue
                    if pt_id in ap_fits:
                        add(cat, apid, False)

    # 3. Child-side: products that declare THIS product as a parent via the
    #    product-level Accessory Role (accessory_of_products on the child).
    for apid, ap in products.items():
        if product_id in (ap.get("accessory_of_products") or []):
            add(ap.get("accessory_category") or "other", apid, bool(ap.get("accessory_required")))

    out: list[dict] = []
    for cat_id in acc_cats:                      # vocabulary order
        g = groups.get(cat_id)
        if not g:
            continue
        options = []
        for apid in g["option_ids"]:
            ap = products.get(apid) or {}
            mfr = mfrs.get(ap.get("manufacturer_id"), {})
            skus = [{
                "part_number": pn.get("part_number"),
                "friendly_name": pn.get("friendly_name", ""),
                "price": pn.get("qb_unit_price") if pn.get("qb_unit_price") is not None else pn.get("price_usd"),
                "color": pn.get("color", ""), "secondary_color": pn.get("secondary_color", ""),
                "tertiary_color": pn.get("tertiary_color", ""),
                "lens_type": pn.get("lens_type", ""),
                "vehicle_tags": list(pn.get("vehicle_tags") or []),
                "qb_pending": bool(pn.get("qb_pending")),
            } for pn in (ap.get("part_numbers") or [])]
            options.append({
                "product_id": apid, "model": ap.get("model", apid),
                "manufacturer_label": mfr.get("label", ap.get("manufacturer_id", "")),
                "skus": skus,
            })
        out.append({
            "category": cat_id, "label": acc_cats[cat_id].get("label", cat_id),
            "required": g["required"], "options": options,
        })
    return out


# ── Granular edit endpoints (Part Manager SKU grid + hierarchy) ──────────────
# The client sends a small patch; the server applies it to the full doc and
# persists via save_config_file (keeping _validate_parts_db + the SharePoint
# mirror). Tiny network payload, no fragile whole-document round-trips.

_PRODUCT_EDIT_FIELDS = {"model", "manufacturer_id", "description", "fits_part_types", "tag_ids",
                        "reviewed", "accessory_category", "accessory_of_products", "accessory_required"}
_SKU_EDIT_FIELDS = {
    "part_number", "friendly_name", "color", "secondary_color", "tertiary_color",
    "lens_type", "price_usd", "qb_pending", "vehicle_tags",
}
_PART_TYPE_EDIT_FIELDS = {
    "label", "type_id", "category", "tree_positions", "tag_ids", "max_count",
    "accessory_of", "accessories", "allowed_products", "allowed_placements",
    "workbook_label_pattern", "sequence_scope",
    "location_mode", "location_options",
}


def _slugify(s: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "_", (s or "").strip().lower()).strip("_")
    return out or "item"


def _unique_key(base: str, existing) -> str:
    if base not in existing:
        return base
    i = 2
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


def _clean_tree_positions(positions) -> list[dict]:
    """Drop blank rows; guarantee the section+zone keys the validator requires."""
    out: list[dict] = []
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        section, zone, sub_zone = pos.get("section") or "", pos.get("zone") or "", pos.get("sub_zone") or ""
        if not section and not zone and not sub_zone:
            continue
        entry = {"section": section, "zone": zone}
        if sub_zone:
            entry["sub_zone"] = sub_zone
        out.append(entry)
    return out


def _sku_at(product: dict, index: int, expect: str = ""):
    """Resolve a SKU index, tolerating a shifted index when `expect`
    (the part_number) is supplied. Returns (part_numbers_list, resolved_index)."""
    pns = product.setdefault("part_numbers", [])
    if 0 <= index < len(pns) and (not expect or pns[index].get("part_number") == expect):
        return pns, index
    if expect:
        for i, pn in enumerate(pns):
            if pn.get("part_number") == expect:
                return pns, i
    raise ValueError(f"part number index {index} not found")


def _apply_sku_fields(pn: dict, fields: dict) -> None:
    linked = bool(pn.get("qb_item_id"))
    for k, v in fields.items():
        if k not in _SKU_EDIT_FIELDS:
            continue
        if k == "price_usd":
            if linked:
                continue   # QB owns the price on linked SKUs (qb_unit_price)
            pn[k] = None if (v is None or v == "") else float(v)
        elif k == "qb_pending":
            if v:
                pn[k] = True
            else:
                pn.pop("qb_pending", None)
        else:
            pn[k] = v


def _mutate_parts_db(svc, paths, mutate):
    """Deep-copy the doc, run mutate(doc) -> payload, then persist + invalidate.
    `mutate` may raise ValueError(message) to signal a 400."""
    doc = copy.deepcopy(svc.raw_doc())
    payload = mutate(doc) or {}
    meta = doc.setdefault("metadata", {})
    meta["last_updated"] = datetime.now(timezone.utc).isoformat()
    meta["updated_by"] = "part-manager-ui"
    result = save_config_file("parts_db.json", doc, paths)
    if not result.get("ok"):
        raise ValueError(result.get("error") or "save failed")
    svc.invalidate()
    payload["ok"] = True
    return payload


def _handle_edit(svc, paths, sub: str, body: dict) -> dict:
    def products_of(doc):
        return doc.setdefault("products", {})

    if sub == "product-update":
        pid, fields = body.get("product_id", ""), (body.get("fields") or {})

        def m(doc):
            p = products_of(doc).get(pid)
            if p is None:
                raise ValueError(f"unknown product_id: {pid}")
            for k, v in fields.items():
                if k in _PRODUCT_EDIT_FIELDS:
                    p[k] = v
            return {"product_id": pid}
        return _mutate_parts_db(svc, paths, m)

    if sub == "product-create":
        model = (body.get("model") or "").strip()
        if not model:
            raise ValueError("model is required")
        mid = body.get("manufacturer_id") or ""

        def m(doc):
            products = products_of(doc)
            base = (_slugify(mid) + "_" + _slugify(model)) if mid else _slugify(model)
            pid = _unique_key(base, products)
            products[pid] = {
                "manufacturer_id": mid,
                "model": model,
                "description": body.get("description") or "",
                "fits_part_types": list(body.get("fits_part_types") or []),
                "tag_ids": list(body.get("tag_ids") or []),
                "part_numbers": list(body.get("part_numbers") or []),
            }
            return {"product_id": pid}
        return _mutate_parts_db(svc, paths, m)

    if sub == "product-delete":
        pid = body.get("product_id", "")

        def m(doc):
            if pid not in products_of(doc):
                raise ValueError(f"unknown product_id: {pid}")
            del doc["products"][pid]
            return {"product_id": pid}
        return _mutate_parts_db(svc, paths, m)

    if sub == "sku-update":
        pid = body.get("product_id", "")
        index = int(body.get("index", -1))
        expect = body.get("expect_part_number", "") or ""
        fields = body.get("fields") or {}

        def m(doc):
            p = products_of(doc).get(pid)
            if p is None:
                raise ValueError(f"unknown product_id: {pid}")
            pns, i = _sku_at(p, index, expect)
            _apply_sku_fields(pns[i], fields)
            return {"product_id": pid, "index": i}
        return _mutate_parts_db(svc, paths, m)

    if sub == "sku-add":
        pid = body.get("product_id", "")
        sku = body.get("sku") or {}

        def m(doc):
            p = products_of(doc).get(pid)
            if p is None:
                raise ValueError(f"unknown product_id: {pid}")
            new = {"part_number": (sku.get("part_number") or "").strip() or "NEW-SKU"}
            _apply_sku_fields(new, sku)
            p.setdefault("part_numbers", []).append(new)
            return {"product_id": pid, "index": len(p["part_numbers"]) - 1}
        return _mutate_parts_db(svc, paths, m)

    if sub == "sku-delete":
        pid = body.get("product_id", "")
        index = int(body.get("index", -1))
        expect = body.get("expect_part_number", "") or ""

        def m(doc):
            p = products_of(doc).get(pid)
            if p is None:
                raise ValueError(f"unknown product_id: {pid}")
            pns, i = _sku_at(p, index, expect)
            pns.pop(i)
            return {"product_id": pid}
        return _mutate_parts_db(svc, paths, m)

    if sub == "sku-move":
        src = body.get("from_product_id", "")
        dst = body.get("to_product_id", "")
        index = int(body.get("index", -1))
        expect = body.get("expect_part_number", "") or ""

        def m(doc):
            products = products_of(doc)
            ps, pd = products.get(src), products.get(dst)
            if ps is None or pd is None:
                raise ValueError("unknown source or destination product")
            pns, i = _sku_at(ps, index, expect)
            pd.setdefault("part_numbers", []).append(pns.pop(i))
            return {"from_product_id": src, "to_product_id": dst}
        return _mutate_parts_db(svc, paths, m)

    if sub == "sku-bulk":
        targets = body.get("targets") or []
        op = body.get("op") or "set"
        fields = body.get("fields") or {}

        def m(doc):
            products = products_of(doc)
            by_pid: dict[str, list[int]] = {}
            for t in targets:
                by_pid.setdefault(t.get("product_id", ""), []).append(int(t.get("index", -1)))
            count = 0
            for pid, idxs in by_pid.items():
                p = products.get(pid)
                if p is None:
                    continue
                pns = p.setdefault("part_numbers", [])
                if op == "delete":
                    for i in sorted(set(idxs), reverse=True):
                        if 0 <= i < len(pns):
                            pns.pop(i)
                            count += 1
                else:
                    for i in set(idxs):
                        if 0 <= i < len(pns):
                            _apply_sku_fields(pns[i], fields)
                            count += 1
            return {"count": count}
        return _mutate_parts_db(svc, paths, m)

    if sub == "manufacturer-create":
        label = (body.get("label") or "").strip()
        if not label:
            raise ValueError("label is required")

        def m(doc):
            mfrs = doc.setdefault("manufacturers", {})
            mid = _unique_key(_slugify(label), mfrs)
            entry = {"label": label}
            if body.get("website"):
                entry["website"] = body["website"]
            mfrs[mid] = entry
            return {"manufacturer_id": mid, "label": label}
        return _mutate_parts_db(svc, paths, m)

    if sub == "tag-create":
        label = (body.get("label") or "").strip()
        if not label:
            raise ValueError("label is required")

        def m(doc):
            tags = doc.setdefault("tags", {})
            tid = _unique_key(_slugify(label), tags)
            tags[tid] = {"label": label}
            return {"tag_id": tid, "label": label}
        return _mutate_parts_db(svc, paths, m)

    if sub == "part-type-create":
        label = (body.get("label") or "").strip()
        type_id = (body.get("type_id") or "").strip()
        if not label or not type_id:
            raise ValueError("label and type_id are required")

        def m(doc):
            pts = doc.setdefault("part_types", {})
            ptid = _unique_key(_slugify(label), pts)
            pts[ptid] = {
                "label": label,
                "type_id": type_id,
                "category": body.get("category") or "",
                "tree_positions": _clean_tree_positions(body.get("tree_positions")),
                "tag_ids": list(body.get("tag_ids") or []),
                "workbook_label_pattern": body.get("workbook_label_pattern") or "{label}",
                "sequence_scope": body.get("sequence_scope") or "global",
            }
            return {"part_type_id": ptid, "label": label}
        return _mutate_parts_db(svc, paths, m)

    if sub == "part-type-update":
        ptid, fields = body.get("part_type_id", ""), (body.get("fields") or {})

        def m(doc):
            pt = doc.setdefault("part_types", {}).get(ptid)
            if pt is None:
                raise ValueError(f"unknown part_type_id: {ptid}")
            for k, v in fields.items():
                if k not in _PART_TYPE_EDIT_FIELDS:
                    continue
                if k == "tree_positions":
                    pt[k] = _clean_tree_positions(v)
                elif k == "max_count":
                    pt[k] = None if (v is None or v == "") else int(v)
                elif k == "location_options":
                    # De-dupe, trim, drop blanks; preserve order.
                    seen: set[str] = set()
                    opts: list[str] = []
                    for x in (v or []):
                        s = str(x).strip()
                        if s and s.upper() not in seen:
                            seen.add(s.upper())
                            opts.append(s)
                    pt[k] = opts
                else:
                    pt[k] = v
            return {"part_type_id": ptid}
        return _mutate_parts_db(svc, paths, m)

    if sub == "seed-light-tags":
        # Tag products as "light" where the data already implies it (a SKU has a
        # color, or it fits a light-category part_type). Creates the tag if
        # missing. Idempotent; the owner corrects individual products afterward.
        light_cats = {"warning", "scene", "interior", "interior_bar", "roof_bar", "spotlight"}

        def m(doc):
            tags = doc.setdefault("tags", {})
            lid = next((tid for tid, t in tags.items()
                        if tid == "light" or (t.get("label") or "").strip().lower() == "light"), None)
            if lid is None:
                lid = "light"
                tags[lid] = {"label": "Light"}
            part_types = doc.get("part_types") or {}
            n = 0
            for p in (doc.get("products") or {}).values():
                if lid in (p.get("tag_ids") or []):
                    continue
                has_color = any((pn.get("color") or "").strip() for pn in (p.get("part_numbers") or []))
                fits_light = any((part_types.get(ptid, {}).get("category") in light_cats)
                                 for ptid in (p.get("fits_part_types") or []))
                if has_color or fits_light:
                    p.setdefault("tag_ids", []).append(lid)
                    n += 1
            return {"count": n, "light_tag_id": lid}
        return _mutate_parts_db(svc, paths, m)

    if sub == "backfill-descriptions":
        # Fill empty SKU sales descriptions (friendly_name) from the QB items
        # cache for every QB-linked SKU. Never overwrites a hand-curated name.
        from ..services.qb_sync_service import get_cached_items
        items = (get_cached_items(paths).get("items") or [])
        desc_by_id = {str(it.get("qb_item_id")): (it.get("description") or "").strip()
                      for it in items if it.get("description")}

        def m(doc):
            n = 0
            for p in (doc.get("products") or {}).values():
                for pn in (p.get("part_numbers") or []):
                    qid = str(pn.get("qb_item_id") or "")
                    if qid and not (pn.get("friendly_name") or "").strip() and desc_by_id.get(qid):
                        pn["friendly_name"] = desc_by_id[qid]
                        n += 1
            return {"count": n}
        return _mutate_parts_db(svc, paths, m)

    raise ValueError(f"unknown edit action: {sub}")


def _part_type_response(part_type) -> dict:
    data = asdict(part_type)
    data.pop("render", None)
    return data


def _product_response(product) -> dict:
    """Keep optional structured product metadata out of ordinary product payloads."""
    data = asdict(product)
    if not data.get("console_kit"):
        data.pop("console_kit", None)
    return data


def route_parts_db(
    handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths
) -> bool:
    qs = parse_qs(urlparse(handler.path).query)
    svc = get_parts_db_service(paths)

    # GET endpoints ───────────────────────────────────────────────────────

    if method == "GET" and path == _PREFIX:
        send_json(handler, svc.raw_doc())
        return True

    if method == "GET" and path == _TYPES_PATH:
        send_json(handler, {"types": [asdict(t) for t in svc.list_types()]})
        return True

    if method == "GET" and path == _BROWSE_TREE_PATH:
        send_json(handler, {"categories": _build_browse_tree(svc)})
        return True

    if method == "GET" and path == _MANIFEST_GROUPS_PATH:
        send_json(handler, _build_manifest_groups(svc))
        return True

    if method == "GET" and path == _SECTIONS_PATH:
        send_json(handler, {"sections": [asdict(s) for s in svc.list_sections()]})
        return True

    if method == "GET" and path == _ZONES_PATH:
        section = qs.get("section", [""])[0] or None
        send_json(handler, {"zones": [asdict(z) for z in svc.list_zones(section)]})
        return True

    if method == "GET" and path == _SUB_ZONES_PATH:
        zone = qs.get("zone", [""])[0] or None
        send_json(handler, {"sub_zones": [asdict(s) for s in svc.list_sub_zones(zone)]})
        return True

    if method == "GET" and path == _BUILD_ATTRS_PATH:
        send_json(handler, {"build_attributes": [asdict(a) for a in svc.list_build_attributes()]})
        return True

    if method == "GET" and path == _TAGS_PATH:
        send_json(handler, {"tags": [asdict(t) for t in svc.list_tags()]})
        return True

    if method == "GET" and path == _SERVICES_PATH:
        send_json(handler, {"services": [asdict(s) for s in svc.list_services()]})
        return True

    if method == "GET" and path == _MANUFACTURERS_PATH:
        send_json(handler, {"manufacturers": [asdict(m) for m in svc.list_manufacturers()]})
        return True

    if method == "GET" and path == _PART_TYPES_PATH:
        type_id = qs.get("type", [""])[0] or None
        section = qs.get("section", [""])[0] or None
        zone = qs.get("zone", [""])[0] or None
        sub_zone = qs.get("sub_zone", [""])[0] or None
        tag = qs.get("tag", [""])[0] or None
        if tag:
            results = svc.list_part_types_with_tag(tag)
        elif type_id or section or zone or sub_zone is not None:
            results = svc.list_part_types_at(type_id, section, zone, sub_zone)
        else:
            results = svc.list_part_types()
        send_json(handler, {"part_types": [_part_type_response(pt) for pt in results]})
        return True

    if method == "GET" and path.startswith(_PART_TYPES_PATH + "/"):
        tail = path[len(_PART_TYPES_PATH) + 1 :]
        if not tail:
            return False
        if tail.endswith("/products"):
            pt_id = tail[: -len("/products")]
            if not pt_id or "/" in pt_id:
                return False
            if svc.get_part_type(pt_id) is None:
                send_json(handler, {"error": f"unknown part_type_id: {pt_id}"}, status=404)
                return True
            send_json(handler, {"products": [_product_response(p) for p in svc.list_products_for_part_type(pt_id)]})
            return True
        if "/" in tail:
            return False
        pt = svc.get_part_type(tail)
        if pt is None:
            send_json(handler, {"error": f"unknown part_type_id: {tail}"}, status=404)
            return True
        send_json(handler, _part_type_response(pt))
        return True

    if method == "GET" and path == _PRODUCTS_PATH:
        tag = qs.get("tag", [""])[0] or None
        if tag:
            results = svc.list_products_with_tag(tag)
        else:
            results = svc.list_products()
        send_json(handler, {"products": [_product_response(p) for p in results]})
        return True

    if method == "GET" and path.startswith(_PRODUCTS_PATH + "/"):
        tail = path[len(_PRODUCTS_PATH) + 1 :]
        if not tail:
            return False
        if tail.endswith("/part-numbers"):
            product_id = tail[: -len("/part-numbers")]
            if not product_id or "/" in product_id:
                return False
            if svc.get_product(product_id) is None:
                send_json(handler, {"error": f"unknown product_id: {product_id}"}, status=404)
                return True
            send_json(handler, {"part_numbers": [asdict(pn) for pn in svc.list_part_numbers(product_id)]})
            return True
        if "/" in tail:
            return False
        product = svc.get_product(tail)
        if product is None:
            send_json(handler, {"error": f"unknown product_id: {tail}"}, status=404)
            return True
        send_json(handler, _product_response(product))
        return True

    if method == "GET" and path == _MANIFEST_DATA_PATH:
        label = qs.get("part_type", [""])[0]
        if not label:
            send_json(handler, {"error": "missing part_type query param"}, status=400)
            return True
        # Direct lookup: find part_type by label, then its products
        part_type_id = ""
        all_pts = svc.list_part_types()
        for pt in all_pts:
            if (pt.label or "").strip().lower() == label.strip().lower():
                part_type_id = pt.part_type_id
                break
        products = svc.list_products_for_part_type(part_type_id) if part_type_id else []
        # Fall back to legacy index + workbook_rules
        if not products:
            products = svc.products_for_legacy_part_type_label(label)
        # Build manufacturers list with IDs
        mfrs_doc = (svc.raw_doc().get("manufacturers") or {})
        seen_ids: set[str] = set()
        manufacturers: list[dict] = []
        part_numbers: list[dict] = []
        for product in products:
            mid = product.manufacturer_id
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                mfr = mfrs_doc.get(mid, {})
                manufacturers.append({
                    "manufacturer_id": mid,
                    "label": mfr.get("label", mid),
                })
            for pn in product.part_numbers:
                entry = asdict(pn)
                entry["manufacturer_id"] = mid
                entry["product_id"] = product.product_id
                entry["product_model"] = product.model
                part_numbers.append(entry)
        if not manufacturers:
            labels_list = svc.manufacturers_by_legacy_name(label)
            manufacturers = [{"manufacturer_id": l, "label": l} for l in labels_list]
        if not part_numbers:
            models = svc.models_by_legacy_name(label)
            part_numbers = [{"part_number": m} for m in models]
        locations = svc.locations_by_legacy_name(label)
        send_json(handler, {
            "manufacturers": manufacturers,
            "part_numbers": part_numbers,
            "locations": locations,
        })
        return True

    if method == "GET" and path == _CATEGORY_ZONES_PATH:
        type_id = qs.get("type", [""])[0]
        category = qs.get("category", [""])[0]
        if not type_id or not category:
            send_json(handler, {"error": "missing type or category"}, status=400)
            return True
        all_pts = svc.list_part_types()
        matching = [pt for pt in all_pts
                    if pt.type_id == type_id
                    and category.lower() in (pt.label or "").lower()]
        zones_doc = svc.raw_doc().get("zones") or {}
        seen: set[str] = set()
        zones: list[dict] = []
        for pt in matching:
            for pos in pt.tree_positions:
                zid = pos.zone
                if zid and zid not in seen:
                    seen.add(zid)
                    z = zones_doc.get(zid, {})
                    zones.append({"zone_id": zid, "label": z.get("label", zid)})
        send_json(handler, {"zones": zones, "part_type_count": len(matching)})
        return True

    if method == "GET" and path == _PLACEMENTS_PATH:
        # Placement step (after zone, before product).
        #   lights      → physical locations for the zone (from `placements`)
        #   non-lights  → part_types of the type act as placements (hybrid)
        type_id = qs.get("type", [""])[0]
        category = qs.get("category", [""])[0]
        zone_id = qs.get("zone", [""])[0]
        if not type_id:
            send_json(handler, {"error": "missing type"}, status=400)
            return True
        doc = svc.raw_doc()
        if type_id == "lights":
            placements_doc = doc.get("placements") or {}
            pzones_doc = doc.get("placement_zones") or {}
            if zone_id:
                pzs = set(_ZONE_TO_PLACEMENT_ZONES.get(zone_id, []))
            else:
                pzs = set(_CATEGORY_TO_PLACEMENT_ZONES.get(category, []))
            # Resolve which part_type backs each location so the picker can name
            # parts per the part_type's workbook_label_pattern (required for the
            # planner/preview to render them). Map by the part_type's legacy
            # locations where known, else fall back to the zone's primary.
            candidates = [pt for pt in svc.list_part_types()
                          if pt.type_id == "lights"
                          and (not category or _pt_matches_category(pt.label, category))
                          and (not zone_id or any(p.zone == zone_id for p in pt.tree_positions))]
            primary = _primary_part_type(candidates, zone_id)
            loc_to_pt: dict[str, object] = {}
            for pt in candidates:
                for legloc in svc.locations_by_legacy_name(pt.label):
                    loc_to_pt.setdefault(legloc.upper(), pt)
            locs = []
            for loc, spec in placements_doc.items():
                pz = spec.get("placement_zone", "")
                if not pzs or pz in pzs:
                    pt = loc_to_pt.get(loc.upper(), primary)
                    locs.append({
                        "location": loc,
                        "placement_zone": pz,
                        "placement_zone_label": (pzones_doc.get(pz) or {}).get("label", pz),
                        "part_type_id": pt.part_type_id if pt else "",
                        "name_pattern": (pt.workbook_label_pattern if pt else "") or (pt.label if pt else ""),
                        "base_label": pt.label if pt else "",
                    })
            locs.sort(key=lambda x: x["location"])
            send_json(handler, {"mode": "location", "placements": locs})
            return True
        # Non-lights: part_types as placement options.
        out = []
        for pt in svc.list_part_types():
            if pt.type_id != type_id:
                continue
            if category and category.lower() not in (pt.label or "").lower():
                continue
            if zone_id and not any(pos.zone == zone_id for pos in pt.tree_positions):
                continue
            out.append({
                "part_type_id": pt.part_type_id,
                "label": pt.label,
                "name_pattern": pt.workbook_label_pattern or pt.label,
                "base_label": pt.label,
                "product_count": len(svc.list_products_for_part_type(pt.part_type_id)),
            })
        out.sort(key=lambda x: x["label"])
        send_json(handler, {"mode": "part_type", "placements": out})
        return True

    if method == "GET" and path == _ACCESSORIES_PATH:
        # A product's accessories, grouped by category — drives the picker's
        # per-type accessory dropdowns.
        product_id = qs.get("product_id", [""])[0]
        if not product_id:
            send_json(handler, {"error": "missing product_id"}, status=400)
            return True
        send_json(handler, {"accessories": _resolve_accessories(svc, product_id)})
        return True

    if method == "GET" and path == _TRACER_HEADS_PATH:
        # Resolve a tracer housing + Duo/Trio + White/Amber into concrete
        # housings + head SKUs (qty rolled up). Drives the tracer picker's
        # Standard Duo / Standard Trio pills. See docs/PARTS_DB_AND_PICKER.md.
        from ..services.lighthead_resolver import resolve_tracer
        product_id = qs.get("product_id", [""])[0]
        if not product_id:
            send_json(handler, {"error": "missing product_id"}, status=400)
            return True
        result = resolve_tracer(
            svc.raw_doc(), product_id,
            mode=qs.get("mode", ["duo"])[0],
            secondary_color=qs.get("secondary", ["white"])[0],
            lens=qs.get("lens", ["clear"])[0],
        )
        send_json(handler, result)
        return True

    if method == "GET" and path == _CATEGORY_SKUS_PATH:
        # Products + their SKUs for one category (drives the two-pane live list).
        type_id = qs.get("type", [""])[0]
        category = qs.get("category", [""])[0]
        all_products = qs.get("all", [""])[0].lower() in {"1", "true", "yes"}
        # Optional exact family / part_type filters (picker sidebar accordion):
        # narrow the list to a family or one specific part_type instead of the
        # whole category/type. Additive — omitting them keeps every prior
        # caller's behavior (whole-category or whole-type list) unchanged.
        family_filter = qs.get("family", [""])[0]
        part_type_filter = qs.get("part_type", [""])[0]
        if not type_id and not all_products:
            send_json(handler, {"error": "missing type"}, status=400)
            return True
        from ..services.config_service import load_config_file
        catalog_parts = (load_config_file("part_catalog.json", paths).get("parts") or [])
        catalog_fixture_ids = {p["part_id"] for p in catalog_parts if p.get("is_fixture")}
        catalog_default_locs = {
            p["part_id"]: p["default_location_key"]
            for p in catalog_parts if p.get("default_location_key")
        }
        fixture_part_type_ids = {
            pt.part_type_id for pt in svc.list_part_types()
            if _fixture_catalog_id(pt.part_type_id) in catalog_fixture_ids
        }
        doc = svc.raw_doc()
        mfrs_doc = doc.get("manufacturers") or {}
        part_types_doc = doc.get("part_types") or {}
        types_doc = doc.get("types") or {}
        families_doc = doc.get("families") or {}
        family_by_pt: dict[str, tuple[str, dict]] = {}
        for family_id, family in families_doc.items():
            for member_id in family.get("members") or []:
                family_by_pt.setdefault(member_id, (family_id, family))

        if all_products:
            pt_ids = [
                pt_id for pt_id, pt in part_types_doc.items()
                if pt.get("type_id")
                and not pt.get("accessory_of")
                and not pt.get("accessory_category")
                and (not pt.get("browse_hidden") or pt.get("category"))
            ]
        elif part_type_filter:
            # Exact part_type filter (picker sidebar leaf): trust it directly.
            # A family can surface a part_type under a different top-level type
            # than the part_type's own `type_id` (e.g. the Structural "Console
            # System" family lists the equipment-typed `motion_attachment`), so
            # the leaf's display type must NOT gate the lookup — otherwise the
            # product grid comes back empty for cross-type family members.
            pt_ids = [part_type_filter] if svc.get_part_type(part_type_filter) else []
        elif family_filter:
            family = (svc.raw_doc().get("families") or {}).get(family_filter) or {}
            pt_ids = [pt_id for pt_id in (family.get("members") or []) if svc.get_part_type(pt_id)]
        else:
            pt_ids = [pt.part_type_id for pt in svc.list_part_types()
                      if pt.type_id == type_id and _pt_in_category(pt, category)]
        out: list[dict] = []
        seen: set[str] = set()
        for pid in pt_ids:
            pt = svc.get_part_type(pid)
            for p in svc.list_products_for_part_type(pid):
                if p.product_id in seen:
                    continue
                seen.add(p.product_id)
                mfr = mfrs_doc.get(p.manufacturer_id, {})
                skus = []
                for pn in p.part_numbers:
                    skus.append({
                        "part_number": pn.part_number,
                        "friendly_name": pn.friendly_name,
                        "color": pn.color, "secondary_color": pn.secondary_color,
                        "tertiary_color": pn.tertiary_color, "lens_type": pn.lens_type,
                        "price": pn.qb_unit_price or pn.price_usd,
                        "qb": bool(pn.qb_item_id),
                        "qb_pending": bool(pn.qb_pending),
                        "vehicle_tags": list(pn.vehicle_tags or []),
                    })
                fits = p.fits_part_types or []
                primary_pt_raw = part_types_doc.get(pid) or {}
                primary_type_id = primary_pt_raw.get("type_id", "")
                primary_family_id, primary_family = family_by_pt.get(
                    pid, (primary_pt_raw.get("family_id", ""), {})
                )
                related_pt_ids = [pt_id for pt_id in fits if pt_id in part_types_doc]
                related_pt_labels = [
                    (part_types_doc.get(pt_id) or {}).get("label", pt_id)
                    for pt_id in related_pt_ids
                ]
                related_type_labels = [
                    (types_doc.get((part_types_doc.get(pt_id) or {}).get("type_id", "")) or {}).get(
                        "label",
                        (part_types_doc.get(pt_id) or {}).get("type_id", ""),
                    )
                    for pt_id in related_pt_ids
                ]
                related_family_labels = [
                    family.get("label", family_id)
                    for pt_id in related_pt_ids
                    for family_id, family in [family_by_pt.get(pt_id, ("", {}))]
                    if family_id
                ]
                vehicle_tags = [
                    tag for pn in p.part_numbers for tag in (pn.vehicle_tags or [])
                ]
                fixture_part_type_id = (
                    pid if pid in fixture_part_type_ids
                    else next((pt_id for pt_id in fits if pt_id in fixture_part_type_ids), "")
                )
                fixture_catalog_id = _fixture_catalog_id(fixture_part_type_id)
                fixture_catalog_part = _catalog_part_by_id(catalog_parts, fixture_catalog_id)
                is_fixture = bool(fixture_part_type_id)
                default_loc = (
                    catalog_default_locs.get(fixture_catalog_id)
                    or (fixture_catalog_part.get("display_name") or "")
                )
                fixture_label = (fixture_catalog_part.get("display_name") or (pt.label if pt else "")).strip()
                fixture_name_pattern = (pt.workbook_label_pattern if pt else "") or fixture_label
                fixture_base_label = (pt.label if pt else "") or fixture_label
                entry = {
                    "product_id": p.product_id, "model": p.model,
                    "description": p.description,
                    "manufacturer_id": p.manufacturer_id,
                    "manufacturer_label": mfr.get("label", p.manufacturer_id),
                    "skus": skus,
                    "fits_part_types": fits,
                    "primary_part_type_id": pid,
                    "primary_part_type_label": primary_pt_raw.get("label", pid),
                    "primary_type_id": primary_type_id,
                    "primary_type_label": (types_doc.get(primary_type_id) or {}).get("label", primary_type_id),
                    "primary_category_id": primary_pt_raw.get("category", ""),
                    "primary_family_id": primary_family_id,
                    "primary_family_label": primary_family.get("label", primary_family_id) if primary_family_id else "",
                    "search_text": " ".join(str(x) for x in [
                        p.model,
                        p.description,
                        p.manufacturer_id,
                        mfr.get("label", p.manufacturer_id),
                        primary_pt_raw.get("label", pid),
                        (types_doc.get(primary_type_id) or {}).get("label", primary_type_id),
                        primary_family.get("label", primary_family_id) if primary_family_id else "",
                        *related_pt_ids,
                        *related_pt_labels,
                        *related_type_labels,
                        *related_family_labels,
                        *vehicle_tags,
                        *[pn.part_number for pn in p.part_numbers],
                        *[pn.friendly_name for pn in p.part_numbers],
                    ] if x),
                    "is_fixture": is_fixture,
                    "default_location": default_loc,
                }
                if p.console_kit:
                    entry["console_kit"] = dict(p.console_kit)
                if is_fixture:
                    entry.update({
                        "fixture_part_type_id": fixture_part_type_id,
                        "fixture_catalog_id": fixture_catalog_id,
                        "fixture_label": fixture_label,
                        "fixture_name_pattern": fixture_name_pattern,
                        "fixture_base_label": fixture_base_label,
                    })
                out.append(entry)
        out.sort(key=lambda x: x["model"])
        send_json(handler, {"products": out})
        return True

    if method == "GET" and path == _CATEGORY_LOCATIONS_PATH:
        # Location step.
        #   lights      → category-wide placement pool (coords drive diagram dots).
        #   non-lights  → the selected product's own curated location list; coords
        #                 decide whether each option is a diagram dot or dropdown row.
        type_id = qs.get("type", [""])[0]
        category = qs.get("category", [""])[0]
        product_id = qs.get("product", [""])[0]
        vehicle = qs.get("vehicle", [""])[0]
        if not type_id:
            send_json(handler, {"error": "missing type"}, status=400)
            return True
        if type_id == "lights":
            locs = _resolve_category_locations(svc, type_id, category)
        else:
            locs = _resolve_product_locations(svc, paths, type_id, category, product_id, vehicle)
        send_json(handler, {"locations": locs})
        return True

    if method == "GET" and path == _ZONE_PRODUCTS_PATH:
        type_id = qs.get("type", [""])[0]
        zone_id = qs.get("zone", [""])[0]
        part_type_id = qs.get("part_type", [""])[0]
        category = qs.get("category", [""])[0]
        group_mode = qs.get("group", [""])[0]
        if not type_id:
            send_json(handler, {"error": "missing type"}, status=400)
            return True

        all_pts = svc.list_part_types()
        doc = svc.raw_doc()
        mfrs_doc = doc.get("manufacturers") or {}
        zones_doc = doc.get("zones") or {}

        if group_mode == "zone":
            # Group products by zone
            zone_map: dict[str, dict] = {}
            for pt in all_pts:
                if pt.type_id != type_id:
                    continue
                for pos in pt.tree_positions:
                    zid = pos.zone
                    if not zid:
                        continue
                    # Get products for this part type
                    for p in svc.list_products_for_part_type(pt.part_type_id):
                        if zid not in zone_map:
                            z = zones_doc.get(zid, {})
                            zone_map[zid] = {"zone_id": zid, "label": z.get("label", zid), "product_count": 0}
                            zone_map[zid]["_ids"] = set()
                        if p.product_id not in zone_map[zid]["_ids"]:
                            zone_map[zid]["_ids"].add(p.product_id)
                            zone_map[zid]["product_count"] += 1
            # Sort and return
            groups = []
            for zid, g in zone_map.items():
                del g["_ids"]
                groups.append(g)
            groups.sort(key=lambda g: g["label"])
            send_json(handler, {"groups": groups})
            return True

        # Product query mode
        if part_type_id:
            # Scoped to a single part_type (non-lights placement = part_type)
            matching_pt_ids = [part_type_id]
        elif category:
            # Category-scoped across all zones (new lights flow: pick the part
            # before worrying about where it goes).
            matching_pt_ids = [pt.part_type_id for pt in all_pts
                               if pt.type_id == type_id and _pt_in_category(pt, category)]
        elif not zone_id:
            # No zone filter — return all products for this type
            matching_pt_ids = [pt.part_type_id for pt in all_pts if pt.type_id == type_id]
        else:
            matching_pt_ids = []
            for pt in all_pts:
                if pt.type_id != type_id:
                    continue
                if any(pos.zone == zone_id for pos in pt.tree_positions):
                    matching_pt_ids.append(pt.part_type_id)
        products = []
        for pt_id in matching_pt_ids:
            for p in svc.list_products_for_part_type(pt_id):
                if not any(x.product_id == p.product_id for x in products):
                    products.append(p)
        result = []
        for p in products:
            mfr = mfrs_doc.get(p.manufacturer_id, {})
            price_min = None
            for pn in p.part_numbers:
                pp = pn.qb_unit_price or pn.price_usd
                if price_min is None or (pp is not None and pp < price_min):
                    price_min = pp
            qb_count = sum(1 for pn in p.part_numbers if pn.qb_item_id)
            result.append({
                "product_id": p.product_id,
                "model": p.model,
                "manufacturer_id": p.manufacturer_id,
                "manufacturer_label": mfr.get("label", p.manufacturer_id),
                "sku_count": len(p.part_numbers),
                "price_min": price_min,
                "qb_count": qb_count,
            })
        send_json(handler, {"products": result, "part_type_count": len(matching_pt_ids)})
        return True

    # POST endpoints ──────────────────────────────────────────────────────

    if method == "POST" and path == _PREFIX:
        result = save_config_file("parts_db.json", body, paths)
        svc.invalidate()
        send_json(handler, result)
        return True

    if method == "POST" and path == _MATCH_SKUS_PATH:
        from ...planning import sku_resolver
        product_id = body.get("product_id", "")
        heads = body.get("heads") or []
        lens = body.get("lens", "")
        pns = svc.list_part_numbers(product_id) if product_id else []
        result = sku_resolver.match_heads(pns, heads, lens)
        send_json(handler, result)
        return True

    if method == "POST" and path == _RESOLVE_PATH:
        from ...planning import sku_resolver
        result = sku_resolver.build_rows(
            product_model=body.get("product_model", ""),
            manufacturer_label=body.get("manufacturer_label", ""),
            location=body.get("location", ""),
            base_name=body.get("base_name", ""),
            lens=body.get("lens", ""),
            combo_choices=body.get("combos") or [],
            color_fields=body.get("color_fields") if isinstance(body.get("color_fields"), dict) else None,
            total_heads=int(body.get("total_heads") or 0),
        )
        send_json(handler, result)
        return True

    if method == "POST" and path == _VALIDATE_PATH:
        part_type_id = body.get("part_type_id", "")
        product_id = body.get("product_id", "")
        location_id = body.get("location_id", "")
        send_json(handler, svc.validate_placement(part_type_id, product_id, location_id))
        return True

    if method == "POST" and path.startswith(_EDIT_PREFIX + "/"):
        sub = path[len(_EDIT_PREFIX) + 1:]
        try:
            send_json(handler, _handle_edit(svc, paths, sub, body))
        except ValueError as exc:
            send_json(handler, {"ok": False, "error": str(exc)}, status=400)
        return True

    return False
