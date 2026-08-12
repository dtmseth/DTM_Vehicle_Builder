"""Routes for the QuickBooks Online integration (Settings → QuickBooks).

GET:
- /api/quickbooks/status    — connection state (no secrets)
- /api/quickbooks/auth-url  — start the OAuth handshake (returns a URL)
- /api/quickbooks/callback  — OAuth redirect target; always 302s, never HTML
- /api/quickbooks/items     — locally cached pulled items (no network)
- /api/quickbooks/customers/preview — dry-run count of a customer import
- /api/quickbooks/pricing-status — read-only price-level capability check
- /api/quickbooks/customer-pricing — shared Default manufacturer discounts
- /api/quickbooks/production-preview/* — isolated production catalog mapping preview

POST:
- /api/quickbooks/settings    — save client_id / client_secret / env / redirect
- /api/quickbooks/disconnect  — revoke + clear stored tokens
- /api/quickbooks/sync        — pull active Items from QBO into the cache
- /api/quickbooks/link-item   — attach a QB item to an existing VB product
- /api/quickbooks/unlink-item — detach a QB item from its VB product
- /api/quickbooks/customers/import — upsert QB customers into agencies
- /api/quickbooks/customer-pricing/default — save the reviewed shared Default rule
- /api/quickbooks/production-preview/create-snapshot — create/select a local immutable baseline
- /api/quickbooks/push-vehicle-job — legacy per-vehicle sub-customer (job) bridge
- /api/quickbooks/projects/bind — link a vehicle to a real QBO Project locally
- /api/quickbooks/estimates/customer-preview — read the estimate's top-level customer
- /api/quickbooks/estimates/validate — dry-run a vehicle's estimate (no network)
- /api/quickbooks/estimates/create — create one vehicle's estimate
- /api/quickbooks/estimates/create-batch — create estimates for many vehicles

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
from ..services import (
    customer_pricing_service,
    qb_estimate_service,
    qb_production_preview_service,
    qb_sync_service,
    quickbooks_service,
)

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
    if method == "GET" and path == "/api/quickbooks/production-preview/status":
        _send_json(handler, qb_production_preview_service.get_status(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/production-preview/snapshots":
        _send_json(handler, qb_production_preview_service.list_snapshots(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/production-preview/report":
        _send_json(handler, qb_production_preview_service.get_mapping_report(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/auth-url":
        _send_json(handler, quickbooks_service.generate_auth_url(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/callback":
        return _handle_callback(handler, paths)
    if method == "GET" and path == "/api/quickbooks/items":
        _send_json(handler, qb_sync_service.get_cached_items(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/pricing-status":
        _send_json(handler, qb_sync_service.get_pricing_status(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/customer-pricing":
        _send_json(handler, customer_pricing_service.get_default_rule(paths))
        return True
    if method == "GET" and path == "/api/quickbooks/estimate-field-setup":
        _send_json(handler, qb_sync_service.get_estimate_field_setup(paths))
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/customer-preview":
        _send_json(
            handler,
            qb_sync_service.preview_estimate_customer(paths, body.get("project_id", "")),
        )
        return True
    if method == "GET" and path == "/api/quickbooks/customers/preview":
        _send_json(handler, qb_sync_service.preview_customer_import(paths))
        return True
    if method == "POST" and path == "/api/quickbooks/sync":
        _send_json(handler, qb_sync_service.run_full_sync(paths))
        return True
    if method == "POST" and path == "/api/quickbooks/customer-pricing/default":
        _send_json(handler, customer_pricing_service.save_default_rule(paths, body))
        return True
    if method == "POST" and path == "/api/quickbooks/production-preview/select-snapshot":
        _send_json(
            handler,
            qb_production_preview_service.select_snapshot(paths, body.get("snapshot_name", "")),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/production-preview/create-snapshot":
        _send_json(
            handler,
            qb_production_preview_service.create_baseline_snapshot(paths, body.get("label", "")),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/production-preview/settings":
        _send_json(
            handler,
            qb_production_preview_service.save_connection(
                paths,
                client_id=body.get("client_id", ""),
                client_secret=body.get("client_secret", ""),
                redirect_uri=body.get("redirect_uri", ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/production-preview/auth-url":
        _send_json(handler, qb_production_preview_service.generate_auth_url(paths))
        return True
    if method == "POST" and path == "/api/quickbooks/production-preview/pull":
        _send_json(handler, qb_production_preview_service.pull_production_catalog(paths))
        return True
    if method == "POST" and path == "/api/quickbooks/production-preview/mapping-field":
        _send_json(
            handler,
            qb_production_preview_service.set_mapping_field(paths, body.get("field", "")),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/production-preview/prepare-plan":
        _send_json(handler, qb_production_preview_service.prepare_auto_mapping_plan(paths))
        return True
    if method == "POST" and path == "/api/quickbooks/production-preview/disconnect":
        _send_json(handler, qb_production_preview_service.disconnect(paths))
        return True
    if method == "POST" and path == "/api/quickbooks/link-item":
        _send_json(
            handler,
            qb_sync_service.link_item(
                paths,
                qb_item_id=body.get("qb_item_id", ""),
                product_id=body.get("product_id", ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/unlink-item":
        _send_json(
            handler,
            qb_sync_service.unlink_item(paths, qb_item_id=body.get("qb_item_id", "")),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/customers/import":
        _send_json(handler, qb_sync_service.import_customers(paths))
        return True
    if method == "POST" and path == "/api/quickbooks/push-vehicle-job":
        _send_json(
            handler,
            qb_sync_service.push_vehicle_job(
                paths, body.get("project_id", ""), body.get("individual_id", "")
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/projects/bind":
        _send_json(
            handler,
            qb_estimate_service.bind_project(
                paths,
                project_id=body.get("project_id", ""),
                individual_id=body.get("individual_id", ""),
                qb_project_id=body.get("qb_project_id", ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/validate":
        _send_json(
            handler,
            qb_estimate_service.validate_estimate(
                paths,
                project_id=body.get("project_id", ""),
                individual_id=body.get("individual_id", ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/create":
        _send_json(
            handler,
            qb_estimate_service.create_estimate(
                paths,
                project_id=body.get("project_id", ""),
                individual_id=body.get("individual_id", ""),
                memo=body.get("memo", ""),
                customer_confirmed=bool(body.get("customer_confirmed", False)),
                customer_fields=body.get("customer_fields") or None,
                existing_action=body.get("existing_action", ""),
                attach_pdf=bool(body.get("attach_pdf", False)),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/create-batch":
        _send_json(
            handler,
            qb_estimate_service.create_estimates_batch(
                paths,
                project_id=body.get("project_id", ""),
                individual_ids=body.get("individual_ids") or None,
                memo=body.get("memo", ""),
            ),
        )
        return True
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

    result = quickbooks_service.complete_authorization(paths, code=code, realm_id=realm_id, state=state)
    if result.get("ok") and result.get("profile") == quickbooks_service.PRODUCTION_PREVIEW_PROFILE:
        _redirect(handler, "/?qb=production-preview-connected")
    else:
        _redirect(handler, "/?qb=connected" if result.get("ok") else "/?qb=error")
    return True
