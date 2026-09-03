from __future__ import annotations

import re
from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services.photo_gallery_service import (
    get_gallery_media,
    get_thumbnail_cache_status,
    start_thumbnail_cache_prepare,
)
from .http import send_json


_PHOTO_ROUTE = re.compile(r"^/api/photo-gallery/([a-f0-9]{32})/(thumbnail|content)$")


def route_photo_gallery(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    paths: AppPaths,
) -> bool:
    if method == "GET" and path == "/api/photo-gallery/cache-status":
        send_json(handler, get_thumbnail_cache_status(paths))
        return True
    if method == "POST" and path == "/api/photo-gallery/cache-prepare":
        send_json(handler, start_thumbnail_cache_prepare(paths))
        return True
    match = _PHOTO_ROUTE.fullmatch(path)
    if method != "GET" or match is None:
        return False
    token, variant = match.groups()
    status, data, content_type, filename, cache_state = get_gallery_media(token, variant, paths)
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header(
        "Cache-Control",
        "private, max-age=31536000, immutable"
        if status == 200 and cache_state == "ready" else "no-store",
    )
    handler.send_header("X-DTM-Thumbnail-State", cache_state)
    if status == 202:
        handler.send_header("Retry-After", "1" if variant == "content" else "2")
        handler.send_header("X-DTM-Thumbnail-State", "preparing")
    if status == 200 and variant == "content" and filename:
        safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
        handler.send_header("Content-Disposition", f'inline; filename="{safe_name}"')
    handler.end_headers()
    handler.wfile.write(data)
    return True
