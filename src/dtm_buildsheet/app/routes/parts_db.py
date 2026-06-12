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

    # POST endpoints ──────────────────────────────────────────────────────

    if method == "POST" and path == _PREFIX:
        result = save_config_file("parts_db.json", body, paths)
        svc.invalidate()
        send_json(handler, result)
        return True

    if method == "POST" and path == _VALIDATE_PATH:
        part_type_id = body.get("part_type_id", "")
        product_id = body.get("product_id", "")
        location_id = body.get("location_id", "")
        send_json(handler, svc.validate_placement(part_type_id, product_id, location_id))
        return True

    return False
