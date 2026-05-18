from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...paths import AppPaths
from ..services.agency_service import (
    handle_delete_agency,
    handle_list_agencies,
    handle_save_agency,
    handle_search_agencies,
)


def route_agencies(
    handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths
) -> bool:
    qs = parse_qs(urlparse(handler.path).query)
    if method == "GET" and path == "/api/agencies":
        _json(handler, handle_list_agencies(paths))
        return True
    if method == "GET" and path == "/api/agencies/search":
        _json(handler, handle_search_agencies(qs.get("q", [""])[0], paths))
        return True
    if method == "POST" and path == "/api/agency/save":
        _json(handler, handle_save_agency(body, paths))
        return True
    if method == "DELETE" and path.startswith("/api/agency/"):
        agency_id = path[len("/api/agency/"):]
        if agency_id and "/" not in agency_id:
            _json(handler, handle_delete_agency(agency_id, paths))
            return True
    return False


def _json(handler: BaseHTTPRequestHandler, payload: dict) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
