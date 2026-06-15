"""Routes for the QuickBooks Online integration (Settings → QuickBooks).

GET:
- /api/quickbooks/status    — connection state (no secrets)
- /api/quickbooks/auth-url  — start the OAuth handshake (returns a URL)
- /api/quickbooks/callback  — OAuth redirect target; always 302s, never HTML

POST:
- /api/quickbooks/settings    — save client_id / client_secret / env / redirect
- /api/quickbooks/disconnect  — revoke + clear stored tokens

All JSON responses set ``Cache-Control: no-store`` (security standard). The
callback never echoes the authorization code or any token into an HTML body;
it issues a server-side 302 to a clean URL to avoid Referer-header leakage.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...paths import AppPaths
from ..services import quickbooks_service

logger = logging.getLogger(__name__)


def _send_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _redirect(handler: BaseHTTPRequestHandler, location: str) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()


def route_quickbooks(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    if method == "GET" and path == "/api/quickbooks/status":
        _send_json(handler, quickbooks_service.get_status(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/auth-url":
        _send_json(handler, quickbooks_service.generate_auth_url(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/callback":
        return _handle_callback(handler, paths)
    if method == "POST" and path == "/api/quickbooks/settings":
        _send_json(
            handler,
            quickbooks_service.save_settings(
                paths,
                client_id=body.get("client_id", ""),
                client_secret=body.get("client_secret", ""),
                environment=body.get("environment", "production"),
                redirect_uri=body.get("redirect_uri", ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/disconnect":
        _send_json(handler, quickbooks_service.disconnect(paths))
        return True
    return False


def _handle_callback(handler: BaseHTTPRequestHandler, paths: AppPaths) -> bool:
    query = parse_qs(urlparse(handler.path).query)
    code = (query.get("code") or [""])[0]
    state = (query.get("state") or [""])[0]
    realm_id = (query.get("realmId") or [""])[0]
    error = (query.get("error") or [""])[0]

    if error:
        # User declined or Intuit returned an error. Never echo it as HTML.
        _redirect(handler, "/?qb=error")
        return True

    result = quickbooks_service.complete_authorization(
        paths, code=code, realm_id=realm_id, state=state
    )
    _redirect(handler, "/?qb=connected" if result.get("ok") else "/?qb=error")
    return True
