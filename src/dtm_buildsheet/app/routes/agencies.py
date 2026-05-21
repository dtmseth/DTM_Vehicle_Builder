from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...paths import AppPaths
from ..services.agency_service import (
    handle_delete_agency,
    handle_list_agencies,
    handle_save_agency,
    handle_search_agencies,
)
from .http import send_json


def route_agencies(
    handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths
) -> bool:
    qs = parse_qs(urlparse(handler.path).query)
    if method == "GET" and path == "/api/agencies":
        send_json(handler, handle_list_agencies(paths))
        return True
    if method == "GET" and path == "/api/agencies/search":
        send_json(handler, handle_search_agencies(qs.get("q", [""])[0], paths))
        return True
    if method == "POST" and path == "/api/agency/save":
        send_json(handler, handle_save_agency(body, paths))
        return True
    if method == "DELETE" and path.startswith("/api/agency/"):
        agency_id = path[len("/api/agency/"):]
        if agency_id and "/" not in agency_id:
            send_json(handler, handle_delete_agency(agency_id, paths))
            return True
    return False
