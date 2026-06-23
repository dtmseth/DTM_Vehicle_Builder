from __future__ import annotations

from dataclasses import asdict
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
_MATCH_SKUS_PATH = f"{_PREFIX}/match-skus"
_RESOLVE_PATH = f"{_PREFIX}/resolve-selection"
_ACCESSORIES_PATH = f"{_PREFIX}/accessories"
_TRACER_HEADS_PATH = f"{_PREFIX}/tracer-heads"


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


def _resolve_category_locations(svc, type_id: str, category: str) -> list[dict]:
    """Locations for the category's location-last step.

    Each location resolves to a canonical part_type based solely on its
    tree zone: front→Forward Warning, side→Side Warning, rear→Rear Warning.
    Legacy fine-grained part_types (Front Side Warning, Pit Bar Warning,
    Lower Lift Gate Warning, etc.) are intentionally collapsed per owner
    direction — all warning-category locations use the same 3 names.
    """
    candidates = [pt for pt in svc.list_part_types()
                  if pt.type_id == type_id and _pt_in_category(pt, category)]
    if not candidates:
        return []

    # Build fast lookup: tree_zone → canonical part_type for naming.
    # Prefer an exact label match (case-insensitive) to the zone's keyword.
    _zone_keyword = {"front": "forward warning", "side": "side warning", "rear": "rear warning"}
    zone_pt: dict[str, object] = {}
    for tree, kw in _zone_keyword.items():
        for pt in candidates:
            if (pt.label or "").strip().lower() == kw:
                if any(p.zone == tree for p in pt.tree_positions):
                    zone_pt[tree] = pt
                    break
        # Fallback: any candidate in the tree zone whose label contains the keyword
        if tree not in zone_pt and kw:
            for pt in candidates:
                if kw in (pt.label or "").lower():
                    if any(p.zone == tree for p in pt.tree_positions):
                        zone_pt[tree] = pt
                        break

    doc = svc.raw_doc()
    placements_doc = doc.get("placements") or {}
    pzones = set(_CATEGORY_PLACEMENT_ZONES.get(category, []))
    out: list[dict] = []
    for loc, spec in placements_doc.items():
        pz = spec.get("placement_zone", "")
        tree_zone = _PLACEMENT_ZONE_TO_TREE.get(pz, "")
        if tree_zone not in pzones:
            continue
        pt = zone_pt.get(tree_zone)
        if pt is None:
            continue
        out.append({
            "location": loc,
            "placement_zone": pz,
            "part_type_id": pt.part_type_id,
            "name_pattern": (pt.workbook_label_pattern or pt.label),
            "base_label": pt.label,
        })
    out.sort(key=lambda x: x["location"])
    return out


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


def _default_views_for_label(catalog_parts: list, label: str) -> set[str]:
    views: set[str] = set()
    for p in _catalog_parts_for_label(catalog_parts, label):
        views |= set(p.get("default_views") or [])
    return views


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
        cparts = _catalog_parts_for_label(catalog_parts, pt.label)
        # Skip non-rendering part_types (e.g. Tail/Headlight Flasher — line items
        # that flash existing vehicle lights, no diagram icon): they have no
        # placement and would never load in the preview.
        if not any((p.get("render_kind") or "none") != "none" for p in cparts):
            continue
        dviews: set[str] = set()
        for p in cparts:
            dviews |= set(p.get("default_views") or [])
        if not dviews:
            continue   # part doesn't render anywhere → nothing to offer
        # The exact names the planner renders (catalog display_names), sorted so
        # the picker assigns the lowest unused one (e.g. Forward Warning 1, 2).
        catalog_names = sorted(
            (p.get("display_name") or "").strip() for p in cparts if (p.get("display_name") or "").strip())
        # Candidate locations: curated rule first, else everything in the part's views.
        ruled = [l.upper() for l in svc.locations_by_legacy_name(pt.label)]
        if ruled:
            cand = [k for k in ruled if loc_views.get(k, set()) & dviews]
        else:
            cand = [k for k, vs in loc_views.items() if vs & dviews]
        for key in cand:
            if key in seen:
                continue
            seen.add(key)
            pz = (placements_doc.get(key) or {}).get("placement_zone", "")
            out.append({
                "location": key,
                "placement_zone": pz,
                "placement_zone_label": (pzones_doc.get(pz) or {}).get("label", pz),
                "part_type_id": pt.part_type_id,
                "name_pattern": pt.workbook_label_pattern or pt.label,
                "base_label": pt.label,
                "catalog_names": catalog_names,
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
                    if pt_id in ap_fits:
                        add(cat, apid, False)

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
        send_json(handler, {"part_types": [asdict(pt) for pt in results]})
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
            send_json(handler, {"products": [asdict(p) for p in svc.list_products_for_part_type(pt_id)]})
            return True
        if "/" in tail:
            return False
        pt = svc.get_part_type(tail)
        if pt is None:
            send_json(handler, {"error": f"unknown part_type_id: {tail}"}, status=404)
            return True
        send_json(handler, asdict(pt))
        return True

    if method == "GET" and path == _PRODUCTS_PATH:
        tag = qs.get("tag", [""])[0] or None
        if tag:
            results = svc.list_products_with_tag(tag)
        else:
            results = svc.list_products()
        send_json(handler, {"products": [asdict(p) for p in results]})
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
        send_json(handler, asdict(product))
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
        # Standard Duo / Standard Trio pills. See docs/TRACER_LIGHTHEAD_SELECTION.md.
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
        if not type_id:
            send_json(handler, {"error": "missing type"}, status=400)
            return True
        from ..services.config_service import load_config_file
        catalog_parts = (load_config_file("part_catalog.json", paths).get("parts") or [])
        catalog_fixture_ids = {p["part_id"] for p in catalog_parts if p.get("is_fixture")}
        catalog_default_locs = {
            p["part_id"]: p["default_location_key"]
            for p in catalog_parts if p.get("default_location_key")
        }
        mfrs_doc = svc.raw_doc().get("manufacturers") or {}
        pt_ids = [pt.part_type_id for pt in svc.list_part_types()
                  if pt.type_id == type_id and _pt_in_category(pt, category)]
        out: list[dict] = []
        seen: set[str] = set()
        for pid in pt_ids:
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
                is_fixture = bool(fits) and all(pt_id in catalog_fixture_ids for pt_id in fits)
                default_loc = next(
                    (catalog_default_locs[pt_id] for pt_id in fits if pt_id in catalog_default_locs),
                    ""
                )
                out.append({
                    "product_id": p.product_id, "model": p.model,
                    "manufacturer_id": p.manufacturer_id,
                    "manufacturer_label": mfr.get("label", p.manufacturer_id),
                    "skus": skus,
                    "fits_part_types": fits,
                    "is_fixture": is_fixture,
                    "default_location": default_loc,
                })
        out.sort(key=lambda x: x["model"])
        send_json(handler, {"products": out})
        return True

    if method == "GET" and path == _CATEGORY_LOCATIONS_PATH:
        # Location-last step: category-wide placement pool (category-level
        # placements — any product goes in any location in its category).
        type_id = qs.get("type", [""])[0]
        category = qs.get("category", [""])[0]
        if not type_id:
            send_json(handler, {"error": "missing type"}, status=400)
            return True
        locs = _resolve_category_locations(svc, type_id, category)
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

    return False
