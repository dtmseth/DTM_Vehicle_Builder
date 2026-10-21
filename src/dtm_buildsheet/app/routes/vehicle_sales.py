from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services import vehicle_sale_service
from .http import send_json


ROUTE_PREFIX = "/api/vehicle-sales"


def route_vehicle_sales(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    if method == "GET" and path == ROUTE_PREFIX:
        send_json(handler, vehicle_sale_service.list_records(paths))
        return True
    if method != "POST":
        return False
    try:
        if path == f"{ROUTE_PREFIX}/new":
            send_json(handler, vehicle_sale_service.new_record(paths))
            return True
        if path == f"{ROUTE_PREFIX}/from-vehicle":
            record = vehicle_sale_service.record_for_vehicle(
                str(body.get("project_id") or ""),
                str(body.get("unit_id") or ""),
                str(body.get("individual_id") or ""),
                paths,
            )
            send_json(handler, {"ok": True, "record": record})
            return True
        if path == f"{ROUTE_PREFIX}/lookup":
            record = vehicle_sale_service.find_record_for_vehicle(
                str(body.get("project_id") or ""),
                str(body.get("individual_id") or ""),
                paths,
            )
            send_json(handler, {"ok": True, "record": record})
            return True
        if path == f"{ROUTE_PREFIX}/matches":
            send_json(
                handler,
                vehicle_sale_service.find_build_vehicle_matches(
                    vin=str(body.get("vin") or ""),
                    agency=str(body.get("agency") or ""),
                    unit_number=str(body.get("unit_number") or ""),
                    exclude_project_id=str(body.get("exclude_project_id") or ""),
                    paths=paths,
                ),
            )
            return True
        if path == f"{ROUTE_PREFIX}/save":
            send_json(handler, vehicle_sale_service.save_record(body, paths))
            return True
        if path == f"{ROUTE_PREFIX}/open-pdf":
            send_json(
                handler,
                vehicle_sale_service.open_record_pdf(str(body.get("record_id") or ""), paths),
            )
            return True
        if path == f"{ROUTE_PREFIX}/print-pdf":
            send_json(
                handler,
                vehicle_sale_service.print_record_pdf(str(body.get("record_id") or ""), paths),
            )
            return True
        if path == f"{ROUTE_PREFIX}/delete":
            send_json(
                handler,
                vehicle_sale_service.delete_record(
                    str(body.get("record_id") or ""),
                    str(body.get("confirmation") or ""),
                    paths,
                ),
            )
            return True
    except (FileNotFoundError, ValueError) as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, status=400)
        return True
    return False

