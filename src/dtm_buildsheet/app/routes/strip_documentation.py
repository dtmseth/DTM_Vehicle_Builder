from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services import strip_documentation_service
from .http import send_json


ROUTE_PREFIX = "/api/strip-documentation"


def route_strip_documentation(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    if method != "POST":
        return False
    try:
        if path == f"{ROUTE_PREFIX}/from-project":
            record = strip_documentation_service.record_from_project(
                str(body.get("project_id") or ""),
                str(body.get("unit_id") or ""),
                str(body.get("individual_id") or ""),
                paths,
            )
            send_json(handler, {"ok": True, "record": record})
            return True
        if path == f"{ROUTE_PREFIX}/from-sale":
            record = strip_documentation_service.record_from_sale(
                str(body.get("record_id") or ""), paths,
            )
            send_json(handler, {"ok": True, "record": record})
            return True
        if path == f"{ROUTE_PREFIX}/save":
            send_json(handler, strip_documentation_service.save_record(body, paths))
            return True
        if path == f"{ROUTE_PREFIX}/save-intake":
            send_json(handler, strip_documentation_service.save_intake_record(body, paths))
            return True
        if path == f"{ROUTE_PREFIX}/save-technician":
            send_json(handler, strip_documentation_service.save_technician_record(body, paths))
            return True
        if path == f"{ROUTE_PREFIX}/begin-technician":
            send_json(
                handler,
                strip_documentation_service.begin_technician_documentation(
                    str(body.get("record_id") or ""), paths,
                ),
            )
            return True
        if path == f"{ROUTE_PREFIX}/open-pdf":
            send_json(
                handler,
                strip_documentation_service.open_record_pdf(
                    str(body.get("record_id") or ""), paths,
                ),
            )
            return True
    except (FileNotFoundError, ValueError) as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, status=400)
        return True
    return False
