from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from ..services.draft_service import (
    handle_delete_draft,
    handle_generate_from_draft,
    handle_get_draft,
    handle_list_drafts,
    handle_save_draft,
    handle_save_override,
    handle_save_overrides_batch,
)
from ...paths import AppPaths


def route_drafts(handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths) -> bool:
    """Return True if the request was handled."""

    # GET /api/draft/list
    if method == "GET" and path == "/api/draft/list":
        _json(handler, handle_list_drafts(paths))
        return True

    # POST /api/draft/save
    if method == "POST" and path == "/api/draft/save":
        _json(handler, handle_save_draft(body, paths))
        return True

    # POST /api/draft/generate
    if method == "POST" and path == "/api/draft/generate":
        _json(handler, handle_generate_from_draft(body, paths))
        return True

    # POST /api/draft/{id}/overrides/batch
    if method == "POST" and path.startswith("/api/draft/") and path.endswith("/overrides/batch"):
        inner = path[len("/api/draft/"):-len("/overrides/batch")]
        if inner and "/" not in inner:
            _json(handler, handle_save_overrides_batch(inner, body, paths))
            return True

    # POST /api/draft/{id}/override
    if method == "POST" and path.startswith("/api/draft/") and path.endswith("/override"):
        # path: /api/draft/{id}/override
        inner = path[len("/api/draft/"):-len("/override")]
        if inner and "/" not in inner:
            _json(handler, handle_save_override(inner, body, paths))
            return True

    # GET /api/draft/{id}
    if method == "GET" and path.startswith("/api/draft/"):
        draft_id = path[len("/api/draft/"):]
        if draft_id and "/" not in draft_id:
            _json(handler, handle_get_draft(draft_id, paths))
            return True

    # DELETE /api/draft/{id}
    if method == "DELETE" and path.startswith("/api/draft/"):
        draft_id = path[len("/api/draft/"):]
        if draft_id and "/" not in draft_id:
            _json(handler, handle_delete_draft(draft_id, paths))
            return True

    return False


def _json(handler: BaseHTTPRequestHandler, payload: dict) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
