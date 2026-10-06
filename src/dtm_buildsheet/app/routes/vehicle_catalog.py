from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from ..services import vehicle_catalog_service

ROUTE_PREFIX = "/api/vehicle-catalog/"


def route_vehicle_catalog(handler, method: str, path: str) -> bool:
    if method != "GET" or not path.startswith(ROUTE_PREFIX):
        return False
    parsed = urlparse(handler.path)
    query = parse_qs(parsed.query)
    cache_path = handler.paths.workspace_dir / "vehicle_catalog_cache.json"
    try:
        if path == f"{ROUTE_PREFIX}police":
            data = vehicle_catalog_service.list_police_vehicles(query.get("year", [""])[0])
        elif path == f"{ROUTE_PREFIX}makes":
            data = vehicle_catalog_service.list_makes(
                query.get("year", [""])[0], query.get("query", [""])[0],
                cache_path=cache_path,
            )
        elif path == f"{ROUTE_PREFIX}models":
            data = vehicle_catalog_service.list_models(
                query.get("year", [""])[0], query.get("make", [""])[0],
                cache_path=cache_path,
            )
        else:
            return False
        payload = {"ok": True, "source": "NHTSA vPIC", "items": data}
    except (ValueError, vehicle_catalog_service.VehicleCatalogError) as exc:
        payload = {"ok": False, "error": str(exc), "items": []}
    handler._send(
        200,
        json.dumps(payload).encode("utf-8"),
        "application/json",
        cache_control="no-store",
    )
    return True
