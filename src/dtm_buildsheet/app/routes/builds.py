from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services.build_state_service import get_render_status, open_show_folder
from .http import send_json


def route_builds(handler: BaseHTTPRequestHandler, method: str, path: str,
                 body: dict, paths: AppPaths) -> bool:
    """POST /api/build/render-status, /api/build/show-folder.

    Returns True if the request was handled."""
    if method != "POST":
        return False
    if path == "/api/build/render-status":
        send_json(handler, get_render_status(body, paths))
        return True
    if path == "/api/build/show-folder":
        send_json(handler, open_show_folder(body))
        return True
    return False
