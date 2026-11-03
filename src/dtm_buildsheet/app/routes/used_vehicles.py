from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services import used_vehicle_service
from .http import send_json


ROUTE_PREFIX = "/api/used-vehicles"


def route_used_vehicles(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    try:
        if method == "GET" and path == ROUTE_PREFIX:
            send_json(handler, used_vehicle_service.list_records(paths))
            return True
        if method != "POST":
            return False
        if path == f"{ROUTE_PREFIX}/suggest":
            send_json(handler, used_vehicle_service.suggest_records(
                agency_name=str(body.get("agency_name") or ""),
                vin=str(body.get("vin") or ""),
                unit_number=str(body.get("unit_number") or ""),
                paths=paths,
            ))
            return True
        if path == f"{ROUTE_PREFIX}/build-suggestions":
            send_json(handler, used_vehicle_service.build_suggestions(
                str(body.get("agency_name") or ""), paths,
            ))
            return True
        if path == f"{ROUTE_PREFIX}/link-build":
            send_json(handler, used_vehicle_service.link_to_build(
                str(body.get("used_vehicle_id") or ""),
                str(body.get("project_id") or ""),
                str(body.get("unit_id") or ""),
                str(body.get("individual_id") or ""),
                paths,
            ))
            return True
        if path == f"{ROUTE_PREFIX}/relationships":
            send_json(handler, used_vehicle_service.update_relationships(body, paths))
            return True
    except (FileNotFoundError, ValueError) as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, status=400)
        return True
    return False
