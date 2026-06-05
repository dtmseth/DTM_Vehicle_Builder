from __future__ import annotations

import logging
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..adapters.wiring import get_active_bundle
from ..services import update_check_service
from ..services.config_service import load_config_file, save_config_file
from .http import send_json

logger = logging.getLogger(__name__)


def route_updates(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    if method == "GET" and path == "/api/update/check":
        send_json(handler, _check(paths))
        return True
    if method == "POST" and path == "/api/update/dismiss":
        send_json(handler, _dismiss(body, paths))
        return True
    if method == "POST" and path == "/api/update/download":
        send_json(handler, _download(body, paths))
        return True
    if method == "POST" and path == "/api/update/install-now":
        send_json(handler, update_check_service.install_now(paths))
        return True
    return False


# ── Endpoint handlers ────────────────────────────────────────────────────────


def _check(paths: AppPaths) -> dict:
    settings = load_config_file("app_settings.json", paths)
    bundle = get_active_bundle()
    info = update_check_service.check_for_update(
        bundle.storage,
        dismissed_versions=settings.get("dismissed_update_versions", []),
    )
    return {
        "current_version": update_check_service.get_embedded_version(),
        "platform": update_check_service.current_platform(),
        "available": info is not None,
        "info": asdict(info) if info else None,
    }


def _dismiss(body: dict, paths: AppPaths) -> dict:
    version = (body or {}).get("version", "").strip()
    if not version:
        return {"ok": False, "error": "missing version"}
    settings = load_config_file("app_settings.json", paths)
    dismissed = list(settings.get("dismissed_update_versions", []))
    if version not in dismissed:
        dismissed.append(version)
        settings["dismissed_update_versions"] = dismissed
        save_config_file("app_settings.json", settings, paths)
    return {"ok": True, "dismissed": dismissed}


def _download(body: dict, paths: AppPaths) -> dict:
    version = (body or {}).get("version", "").strip()
    if not version:
        return {"ok": False, "error": "missing version"}

    bundle = get_active_bundle()
    info = update_check_service.check_for_update(
        bundle.storage,
        dismissed_versions=[],  # ignore dismissals — user explicitly asked
    )
    if info is None or info.version != version:
        return {
            "ok": False,
            "error": f"version {version} no longer available",
        }

    try:
        local_path = update_check_service.download_update(bundle.storage, info)
    except Exception as exc:  # noqa: BLE001 — storage adapter surfaces many errors
        logger.exception("update download failed")
        return {"ok": False, "error": str(exc)}

    update_check_service.reveal_in_file_manager(local_path)
    return {"ok": True, "local_path": str(local_path)}
