from __future__ import annotations

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...paths import AppPaths
from ..services.config_service import save_config_file
from ..services.parts_db_service import get_parts_db_service
from .http import send_json


_PREFIX = "/api/parts-db"
_PARTS_PREFIX = f"{_PREFIX}/parts"


def route_parts_db(
    handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths
) -> bool:
    qs = parse_qs(urlparse(handler.path).query)
    svc = get_parts_db_service(paths)

    if method == "GET" and path == _PREFIX:
        send_json(handler, svc.raw_doc())
        return True

    if method == "GET" and path == _PARTS_PREFIX:
        category = qs.get("category", [""])[0]
        if category:
            parts = svc.list_parts_by_category(category)
        else:
            parts = [
                p
                for c in (svc.raw_doc().get("part_categories") or {})
                for p in svc.list_parts_by_category(c)
            ]
        send_json(handler, {"parts": [asdict(p) for p in parts]})
        return True

    if method == "GET" and path.startswith(_PARTS_PREFIX + "/"):
        # /api/parts-db/parts/{part_id}  OR  /api/parts-db/parts/{part_id}/locations
        tail = path[len(_PARTS_PREFIX) + 1 :]
        if not tail:
            return False
        if tail.endswith("/locations"):
            part_id = tail[: -len("/locations")]
            if not part_id or "/" in part_id:
                return False
            vehicle = qs.get("vehicle", [""])[0]
            if not vehicle:
                send_json(handler, {"error": "vehicle query parameter required"}, status=400)
                return True
            locations = svc.list_compatible_locations(part_id, vehicle)
            send_json(handler, {"locations": [asdict(loc) for loc in locations]})
            return True
        if "/" in tail:
            return False
        part_spec = (svc.raw_doc().get("parts") or {}).get(tail)
        if not part_spec:
            send_json(handler, {"error": f"unknown part_id: {tail}"}, status=404)
            return True
        from ..services.parts_db_service import _hydrate_part
        send_json(handler, asdict(_hydrate_part(tail, part_spec)))
        return True

    if method == "POST" and path == _PREFIX:
        result = save_config_file("parts_db.json", body, paths)
        # Invalidate the cached doc so the next GET reflects the save.
        svc.invalidate()
        send_json(handler, result)
        return True

    return False
