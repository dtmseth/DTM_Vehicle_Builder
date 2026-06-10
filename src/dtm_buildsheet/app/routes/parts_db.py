from __future__ import annotations

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...paths import AppPaths
from ..services.config_service import save_config_file
from ..services.parts_db_service import get_parts_db_service
from .http import send_json


_PREFIX = "/api/parts-db"
_CATEGORIES_PATH = f"{_PREFIX}/categories"
_MANUFACTURERS_PATH = f"{_PREFIX}/manufacturers"
_PRODUCTS_PATH = f"{_PREFIX}/products"
_ZONES_PREFIX = f"{_PREFIX}/zones/"


def route_parts_db(
    handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths
) -> bool:
    qs = parse_qs(urlparse(handler.path).query)
    svc = get_parts_db_service(paths)

    # GET /api/parts-db — full doc
    if method == "GET" and path == _PREFIX:
        send_json(handler, svc.raw_doc())
        return True

    # GET /api/parts-db/categories
    if method == "GET" and path == _CATEGORIES_PATH:
        send_json(handler, {"categories": [asdict(c) for c in svc.list_categories()]})
        return True

    # GET /api/parts-db/manufacturers[?category=]
    if method == "GET" and path == _MANUFACTURERS_PATH:
        category = qs.get("category", [""])[0]
        if category:
            mfgs = svc.list_manufacturers_in_category(category)
        else:
            doc = svc.raw_doc()
            mfgs_doc = doc.get("manufacturers") or {}
            from ..services.parts_db_service import _hydrate_manufacturer
            mfgs = [_hydrate_manufacturer(mid, spec) for mid, spec in mfgs_doc.items()]
        send_json(handler, {"manufacturers": [asdict(m) for m in mfgs]})
        return True

    # GET /api/parts-db/products[?category=&manufacturer=]
    if method == "GET" and path == _PRODUCTS_PATH:
        category = qs.get("category", [""])[0]
        manufacturer = qs.get("manufacturer", [""])[0]
        if category and manufacturer:
            products = [
                p for p in svc.list_products_by_category(category)
                if p.manufacturer_id == manufacturer
            ]
        elif category:
            products = svc.list_products_by_category(category)
        elif manufacturer:
            products = svc.list_products_by_manufacturer(manufacturer)
        else:
            products = svc.list_products()
        send_json(handler, {"products": [asdict(p) for p in products]})
        return True

    # GET /api/parts-db/products/{product_id}[/part-numbers]
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
            part_numbers = svc.list_part_numbers(product_id)
            send_json(handler, {"part_numbers": [asdict(pn) for pn in part_numbers]})
            return True
        if "/" in tail:
            return False
        product = svc.get_product(tail)
        if product is None:
            send_json(handler, {"error": f"unknown product_id: {tail}"}, status=404)
            return True
        send_json(handler, asdict(product))
        return True

    # GET /api/parts-db/zones/{zone_id}/products
    if method == "GET" and path.startswith(_ZONES_PREFIX) and path.endswith("/products"):
        zone_id = path[len(_ZONES_PREFIX) : -len("/products")]
        if not zone_id or "/" in zone_id:
            return False
        products = svc.products_compatible_with_zone(zone_id)
        send_json(handler, {"products": [asdict(p) for p in products]})
        return True

    # POST /api/parts-db — save full doc
    if method == "POST" and path == _PREFIX:
        result = save_config_file("parts_db.json", body, paths)
        svc.invalidate()
        send_json(handler, result)
        return True

    return False
