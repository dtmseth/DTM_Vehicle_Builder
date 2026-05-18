from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...paths import AppPaths
from ..services.sales_rep_service import (
    handle_delete_rep,
    handle_list_reps,
    handle_save_rep,
    handle_search_reps,
)


def route_sales_reps(
    handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths
) -> bool:
    qs = parse_qs(urlparse(handler.path).query)
    if method == "GET" and path == "/api/sales-reps":
        _json(handler, handle_list_reps(paths))
        return True
    if method == "GET" and path == "/api/sales-reps/search":
        _json(handler, handle_search_reps(qs.get("q", [""])[0], paths))
        return True
    if method == "POST" and path == "/api/sales-rep/save":
        _json(handler, handle_save_rep(body, paths))
        return True
    if method == "DELETE" and path.startswith("/api/sales-rep/"):
        rep_id = path[len("/api/sales-rep/"):]
        if rep_id and "/" not in rep_id:
            _json(handler, handle_delete_rep(rep_id, paths))
            return True
    return False


def _json(handler: BaseHTTPRequestHandler, payload: dict) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
