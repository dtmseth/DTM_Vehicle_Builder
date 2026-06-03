"""Routes for the cloud connection indicator chip in the UI header."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services import cloud_status_service
from .http import send_json


def route_cloud_status(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    if method == "GET" and path == "/api/cloud/status":
        send_json(handler, cloud_status_service.get_status(paths))
        return True
    if method == "GET" and path == "/api/cloud/photo":
        data = cloud_status_service.get_cached_photo_bytes(paths)
        if not data:
            # No photo set, or cache empty / unreadable. The UI falls back
            # to initials when the <img> 404s.
            handler.send_response(404)
            handler.end_headers()
            return True
        # Browsers sniff the format from the bytes (Graph returns JPEG by
        # default but the header is irrelevant for correctness).
        handler.send_response(200)
        handler.send_header("Content-Type", "image/jpeg")
        handler.send_header("Content-Length", str(len(data)))
        # Browser cache for 1 hour to avoid refetching on every status poll.
        # Status reports a stable hash (mtime), so a forced refresh works.
        handler.send_header("Cache-Control", "private, max-age=3600")
        handler.end_headers()
        handler.wfile.write(data)
        return True
    return False
