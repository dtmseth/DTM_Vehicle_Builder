from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services.preset_service import (
    list_presets,
    load_preset,
    load_preset_dict,
    save_preset,
    delete_preset,
    clone_preset,
    import_from_workbook,
    export_preset_workbook,
)
from ...domain.input_models import PartInput
from dataclasses import asdict


def route_presets(handler: BaseHTTPRequestHandler, method: str, path: str,
                  body: dict, paths: AppPaths) -> bool:
    """Return True if the request was handled."""

    # GET /api/presets
    if method == "GET" and path == "/api/presets":
        _json(handler, {"ok": True, "presets": list_presets(paths)})
        return True

    # GET /api/presets/{preset_id}/export-workbook
    if method == "GET" and path.endswith("/export-workbook"):
        preset_id = path[len("/api/presets/"):].removesuffix("/export-workbook")
        if preset_id and "/" not in preset_id:
            try:
                xlsx_bytes = export_preset_workbook(preset_id, paths)
                filename = f"{preset_id}_preset.xlsx"
                _xlsx(handler, xlsx_bytes, filename)
            except (FileNotFoundError, ValueError) as exc:
                _json(handler, {"ok": False, "error": str(exc)})
            return True

    # GET /api/presets/{preset_id}
    if method == "GET" and path.startswith("/api/presets/"):
        preset_id = path[len("/api/presets/"):]
        if preset_id and "/" not in preset_id:
            try:
                full  = load_preset_dict(preset_id, paths)
                parts = load_preset(preset_id, paths)
                _json(handler, {
                    "ok": True,
                    "preset_id": preset_id,
                    "parts": [asdict(p) for p in parts],
                    "placement_overrides": full.get("placement_overrides", {}),
                })
            except (FileNotFoundError, ValueError) as exc:
                _json(handler, {"ok": False, "error": str(exc)})
            return True

    # POST /api/presets/save
    if method == "POST" and path == "/api/presets/save":
        overwrite = bool(body.get("overwrite", False))
        _json(handler, save_preset(body, paths, overwrite=overwrite))
        return True

    # POST /api/presets/import-workbook
    if method == "POST" and path == "/api/presets/import-workbook":
        file_b64 = body.get("data", "")
        if not file_b64:
            _json(handler, {"ok": False, "error": "No file data provided"})
        else:
            _json(handler, import_from_workbook(file_b64, paths))
        return True

    # POST /api/presets/{preset_id}/clone
    if method == "POST" and path.startswith("/api/presets/") and path.endswith("/clone"):
        preset_id = path[len("/api/presets/"):].removesuffix("/clone")
        if preset_id and "/" not in preset_id:
            _json(handler, clone_preset(preset_id, paths))
            return True

    # DELETE /api/presets/{preset_id}
    if method == "DELETE" and path.startswith("/api/presets/"):
        preset_id = path[len("/api/presets/"):]
        if preset_id and "/" not in preset_id:
            _json(handler, delete_preset(preset_id, paths))
            return True

    return False


def _json(handler: BaseHTTPRequestHandler, payload: dict) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _xlsx(handler: BaseHTTPRequestHandler, data: bytes, filename: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.end_headers()
    handler.wfile.write(data)
