"""Routes for the cloud connection indicator chip in the UI header.

GET endpoints:
- /api/cloud/status — JSON state used by both the chip and the modal
- /api/cloud/photo  — bytes of the cached profile photo (404 if absent)

POST endpoints (modal actions):
- /api/cloud/sync     — synchronous full sync; returns when done
- /api/cloud/signout  — wipe the cached MSAL account
- /api/cloud/signin   — trigger the interactive OAuth flow

All POSTs return ``{"ok": bool, ...}``. The handlers never raise — they
catch bundle errors and surface them as a human-readable ``error`` field.
"""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..adapters import wiring
from ..services import cloud_status_service
from .http import send_json

logger = logging.getLogger(__name__)


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
        handler.send_response(200)
        handler.send_header("Content-Type", "image/jpeg")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "private, max-age=3600")
        handler.end_headers()
        handler.wfile.write(data)
        return True
    if method == "POST" and path == "/api/cloud/sync":
        send_json(handler, _force_sync(paths))
        return True
    if method == "POST" and path == "/api/cloud/signout":
        send_json(handler, _signout())
        return True
    if method == "POST" and path == "/api/cloud/signin":
        # POST body can pass {"force_account_picker": true} to force the
        # OAuth account chooser — Switch User sends that; first-launch
        # sign-in sends a plain object and gets the default silent-when-
        # possible flow.
        send_json(handler, _signin(force_account_picker=bool(body.get("force_account_picker"))))
        return True
    return False


def _force_sync(paths: AppPaths) -> dict:
    """Trigger an immediate sync cycle from the modal's 'Force sync' button."""
    try:
        # Late import to avoid pulling server.py at module load time.
        from .. import server as _server
        report = _server.run_sync_now(paths)
    except Exception as exc:
        logger.exception("Force-sync raised")
        return {"ok": False, "error": str(exc)}
    return report


def _signout() -> dict:
    """Wipe the cached MSAL account so the next launch (or signin) re-prompts.

    Doesn't revoke the token server-side — only this machine forgets. Cloud
    photo cache is left in place; refresh on next signin will overwrite it.
    """
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return {"ok": False, "error": "Cloud mode is disabled"}
    try:
        bundle = wiring.get_active_bundle()
        bundle.identity.signout()
    except Exception as exc:
        logger.exception("Signout raised")
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


def _signin(*, force_account_picker: bool = False) -> dict:
    """Trigger the interactive OAuth flow — opens browser + waits for redirect.

    ``force_account_picker`` makes the OAuth endpoint show the account
    chooser even when the browser is already signed into a Microsoft
    account. Switch User passes True; routine sign-in (boot, after a
    failed silent attempt) leaves it False so users with only one
    plausible account don't see an unnecessary picker.
    """
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return {"ok": False, "error": "Cloud mode is disabled"}
    try:
        bundle = wiring.get_active_bundle()
        identity = bundle.identity.signin(force_account_picker=force_account_picker)
    except Exception as exc:
        logger.exception("Interactive signin raised")
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "user": {
            "display_name": identity.display_name,
            "email": identity.email,
        },
    }
