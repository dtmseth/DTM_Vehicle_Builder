from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services import temporary_tag_service
from .http import send_json


ROUTE_PREFIX = "/api/temporary-tags"


def route_temporary_tags(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    try:
        if method == "GET" and path == ROUTE_PREFIX:
            send_json(handler, temporary_tag_service.list_batches(paths))
            return True
        if method == "GET" and path == f"{ROUTE_PREFIX}/candidates":
            send_json(handler, temporary_tag_service.list_vehicle_candidates(paths))
            return True
        if method != "POST":
            return False
        if path == f"{ROUTE_PREFIX}/new":
            send_json(handler, {"ok": True, "record": temporary_tag_service.new_batch()})
            return True
        if path == f"{ROUTE_PREFIX}/save":
            send_json(handler, temporary_tag_service.save_batch(body, paths))
            return True
        if path == f"{ROUTE_PREFIX}/open-pdf":
            send_json(handler, temporary_tag_service.open_batch_pdf(
                str(body.get("batch_id") or ""),
                paths,
                allow_incomplete=bool(body.get("allow_incomplete", False)),
            ))
            return True
        if path == f"{ROUTE_PREFIX}/print-pdf":
            send_json(handler, temporary_tag_service.print_batch_pdf(
                str(body.get("batch_id") or ""),
                paths,
                allow_incomplete=bool(body.get("allow_incomplete", False)),
            ))
            return True
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, status=400)
        return True
    return False
