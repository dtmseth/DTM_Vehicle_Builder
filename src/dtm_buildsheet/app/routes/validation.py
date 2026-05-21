from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ..services.validation_service import validate_draft, validate_form
from ...paths import AppPaths
from .http import send_json


def route_validation(handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths) -> bool:
    """Return True if the request was handled."""

    # POST /api/validate  — validate a form submission
    if method == "POST" and path == "/api/validate":
        send_json(handler, validate_form(body, paths))
        return True

    # GET /api/validate/draft/{id}  — validate a saved draft
    if method == "GET" and path.startswith("/api/validate/draft/"):
        draft_id = path[len("/api/validate/draft/"):]
        if draft_id and "/" not in draft_id:
            send_json(handler, validate_draft(draft_id, paths))
            return True

    return False
