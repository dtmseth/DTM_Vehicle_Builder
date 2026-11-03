"""Shopmonkey connection, cleanup, and guarded inventory-write routes."""

from __future__ import annotations

import json
import logging
import secrets
from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services import shopmonkey_service

logger = logging.getLogger(__name__)

ROUTE_PREFIX = "/api/shopmonkey"


def _send_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def route_shopmonkey(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    try:
        if method == "GET" and path == f"{ROUTE_PREFIX}/status":
            _send_json(handler, shopmonkey_service.get_status())
            return True
        if method == "GET" and path == f"{ROUTE_PREFIX}/cleanup":
            _send_json(handler, shopmonkey_service.cleanup_report(paths))
            return True
        if method == "GET" and path == f"{ROUTE_PREFIX}/pricing":
            _send_json(handler, shopmonkey_service.get_pricing_settings())
            return True
        if method == "GET" and path == f"{ROUTE_PREFIX}/pricing/references":
            _send_json(handler, shopmonkey_service.pricing_reference_data())
            return True
        vehicle_prefix = f"{ROUTE_PREFIX}/customers/"
        vehicle_suffix = "/vehicles"
        if method == "GET" and path.startswith(vehicle_prefix) and path.endswith(vehicle_suffix):
            customer_id = path[len(vehicle_prefix):-len(vehicle_suffix)]
            _send_json(handler, shopmonkey_service.customer_vehicles(customer_id))
            return True
        if method == "POST" and path == f"{ROUTE_PREFIX}/connect":
            _send_json(handler, shopmonkey_service.connect(body.get("api_key", "")))
            return True
        if method == "POST" and path == f"{ROUTE_PREFIX}/test":
            _send_json(handler, shopmonkey_service.test_connection())
            return True
        if method == "POST" and path == f"{ROUTE_PREFIX}/disconnect":
            _send_json(handler, shopmonkey_service.disconnect())
            return True
        if method == "POST" and path == f"{ROUTE_PREFIX}/pricing/save":
            _send_json(handler, shopmonkey_service.save_pricing_settings(
                body.get("config"), body.get("expected_revision", "")
            ))
            return True
        if method == "POST" and path == f"{ROUTE_PREFIX}/inventory/snapshot":
            _send_json(handler, shopmonkey_service.create_inventory_snapshot(paths))
            return True
        if method == "POST" and path == f"{ROUTE_PREFIX}/inventory/estimate-line-breaks":
            _send_json(handler, shopmonkey_service.ensure_estimate_line_breaks())
            return True
    except Exception:  # noqa: BLE001 - keep this external boundary JSON-shaped
        reference = secrets.token_hex(4)
        logger.exception("Shopmonkey route failed [reference=%s]", reference)
        _send_json(handler, {
            "ok": False,
            "error": "shopmonkey_request_failed",
            "detail": "The app could not complete the Shopmonkey request.",
            "reference": reference,
        })
        return True
    return False
