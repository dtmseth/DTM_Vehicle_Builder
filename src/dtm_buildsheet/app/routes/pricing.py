"""HTTP boundary for the local Pricing Center workflow."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services import pricing_center_service as service

ROUTE_PREFIX = "/api/pricing/"
logger = logging.getLogger(__name__)


def _json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    content = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(content)


def _download(handler: BaseHTTPRequestHandler, content: bytes, mime: str, filename: str) -> None:
    safe_filename = filename.replace('"', "")
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Content-Disposition", f'attachment; filename="{safe_filename}"')
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(content)


def route_pricing(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    if not path.startswith(ROUTE_PREFIX):
        return False
    try:
        if method == "GET" and path == "/api/pricing/summary":
            _json(handler, service.summary(paths))
        elif method == "GET" and path == "/api/pricing/rules":
            _json(handler, service.list_rules(paths))
        elif method == "GET" and path == "/api/pricing/presets":
            _json(handler, service.list_presets(paths))
        elif method == "GET" and path == "/api/pricing/scope-options":
            _json(handler, service.scope_options(paths))
        elif method == "GET" and path == "/api/pricing/scope-options/refresh":
            _json(handler, service.scope_options(paths, refresh=True))
        elif method == "GET" and path.startswith("/api/pricing/download/"):
            _download(handler, *service.get_artifact(paths, path.rsplit("/", 1)[-1]))
        elif method == "POST" and path == "/api/pricing/import/inspect":
            _json(handler, service.inspect_price_list(paths, body))
        elif method == "POST" and path == "/api/pricing/import/confirm":
            _json(handler, service.confirm_mapping(paths, body))
        elif method == "POST" and path == "/api/pricing/import/resume":
            _json(handler, service.resume_import(paths, body))
        elif method == "POST" and path == "/api/pricing/import/rule-preview":
            _json(handler, service.rule_preview(paths, body))
        elif method == "POST" and path == "/api/pricing/import/delete":
            _json(handler, service.delete_import(paths, body))
        elif method == "POST" and path == "/api/pricing/inventory/upload":
            _json(handler, service.upload_snapshot(paths, body))
        elif method == "POST" and path == "/api/pricing/inventory/coverage":
            _json(handler, service.inventory_coverage(paths, body))
        elif method == "POST" and path == "/api/pricing/rules/save":
            _json(handler, service.save_rule(paths, body))
        elif method == "POST" and path == "/api/pricing/rules/delete":
            _json(handler, service.delete_rule(paths, body))
        elif method == "POST" and path == "/api/pricing/presets/save":
            _json(handler, service.save_preset(paths, body))
        elif method == "POST" and path == "/api/pricing/reconcile":
            _json(handler, service.reconcile(paths, body))
        elif method == "POST" and path == "/api/pricing/review":
            _json(handler, service.get_review(paths, body))
        elif method == "POST" and path == "/api/pricing/review/update":
            _json(handler, service.update_review_row(paths, body))
        elif method == "POST" and path == "/api/pricing/review/bulk":
            _json(handler, service.bulk_update_review_rows(paths, body))
        elif method == "POST" and path == "/api/pricing/review/settings":
            _json(handler, service.update_review_settings(paths, body))
        elif method == "POST" and path == "/api/pricing/review/finalize":
            _json(handler, service.finalize_review(paths, body))
        elif method == "POST" and path == "/api/pricing/export":
            _json(handler, service.create_export(paths, body))
        elif method == "POST" and path == "/api/pricing/export/bulk":
            _json(handler, service.create_bulk_export(paths, body))
        elif method == "POST" and path == "/api/pricing/export/mark-imported":
            _json(handler, service.mark_imported(paths, body))
        elif method == "POST" and path == "/api/pricing/export/mark-all-imported":
            _json(handler, service.mark_all_imported(paths, body))
        elif method == "POST" and path == "/api/pricing/api/plan":
            _json(handler, service.api_plan(paths, body))
        elif method == "POST" and path == "/api/pricing/api/apply":
            _json(handler, service.apply_api_updates(paths, body))
        else:
            return False
    except service.PricingCenterError as exc:
        _json(handler, {"ok": False, "error": "validation_error", "detail": str(exc)}, 400)
    except Exception as exc:
        logger.error("Pricing Center request failed: %s", type(exc).__name__)
        _json(handler, {"ok": False, "error": "pricing_center_failed", "detail": "Pricing Center could not complete that action."}, 500)
    return True
