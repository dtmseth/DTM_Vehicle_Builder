"""Routes for the QuickBooks Online integration (Settings → QuickBooks).

GET:
- /api/quickbooks/status    — connection state (no secrets)
- /api/quickbooks/auth-url  — start the OAuth handshake (returns a URL)
- /api/quickbooks/callback  — OAuth redirect target; always 302s, never HTML
- /api/quickbooks/items     — locally cached pulled items (no network)
- /api/quickbooks/customers/preview — dry-run count of a customer import
- /api/quickbooks/pricing-status — read-only price-level capability check
- /api/quickbooks/customer-pricing — shared Retail manufacturer discounts
- /api/quickbooks/production-preview/* — isolated production catalog mapping preview

POST:
- /api/quickbooks/settings    — save client_id / client_secret / env / redirect
- /api/quickbooks/disconnect  — revoke + clear stored tokens
- /api/quickbooks/sync        — pull active Items from QBO into the cache
- /api/quickbooks/link-item   — attach a QB item to an existing VB product
- /api/quickbooks/unlink-item — detach a QB item from its VB product
- /api/quickbooks/customers/import — upsert QB customers into agencies
- /api/quickbooks/customer-pricing/default — save the reviewed shared Retail rule
- /api/quickbooks/production-preview/create-snapshot — create/select a local immutable baseline
- /api/quickbooks/push-vehicle-job — legacy per-vehicle sub-customer (job) bridge
- /api/quickbooks/projects/preview — preview a vehicle's local QBO Project link
- /api/quickbooks/projects/bind — link a vehicle to a real QBO Project locally
- /api/quickbooks/estimates/bind — verify and store a read-only existing Estimate link
- /api/quickbooks/estimates/search — search Estimate numbers for unit quote references
- /api/quickbooks/estimates/reconcile-quotes — verify and link saved current quote numbers
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
import secrets
import uuid
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.interfaces import OperationsRepositoryError
from ..services import (
    customer_pricing_service,
    qb_acceptance_service,
    qb_estimate_service,
    qb_production_preview_service,
    qb_sync_service,
    quickbooks_service,
)
from ..services.operations_access_service import (
    actor_from_access_session,
    describe_access_session,
)
from ..services.operations_service import OperationsService, OperationsServiceError

logger = logging.getLogger(__name__)


def _estimate_call(operation: str, callback, *args, **kwargs) -> dict:
    """Keep estimate route failures JSON-shaped without exposing internals."""
    try:
        return callback(*args, **kwargs)
    except Exception:  # noqa: BLE001 - this is the HTTP safety boundary
        reference = secrets.token_hex(4)
        logger.exception("QuickBooks estimate %s failed [reference=%s]", operation, reference)
        return {
            "ok": False,
            "error": "estimate_request_failed",
            "detail": "The app could not complete the QuickBooks estimate request.",
            "reference": reference,
        }


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


def _share_estimate_observation(result: dict, *, individual_id: str) -> dict:
    """Copy safe Estimate metadata into Operations for non-QBO users."""

    observation = result.get("observation")
    if not result.get("ok") or not isinstance(observation, dict):
        return result
    try:
        bundle = wiring.get_active_bundle()
        if bundle.operations is None:
            result["operations_sync"] = {
                "ok": True, "skipped": "operations_not_configured",
            }
            return result
        if bundle.operations_writer is None:
            result["operations_sync"] = {
                "ok": False, "error": "Operations write access is not configured",
            }
            return result
        session = describe_access_session(
            bundle=bundle,
            cloud_enabled=wiring._cloud_flag_enabled(),  # noqa: SLF001
        )
        actor = actor_from_access_session(session)
        if actor is None:
            result["operations_sync"] = {
                "ok": False,
                "error": "Sign in with Microsoft 365 to share the Estimate status",
            }
            return result
        current = bundle.operations_writer.get_vehicle(individual_id)
        if current is None:
            result["operations_sync"] = {
                "ok": False,
                "error": "The Estimate was connected, but its Operations vehicle was not found",
            }
            return result
        mutation = OperationsService(bundle.operations_writer).observe_qbo_estimate(
            vehicle_id=individual_id,
            actor=actor,
            request_id=str(uuid.uuid4()),
            source_client="builder_desktop",
            expected_revision=current.revision,
            **observation,
        )
        result["operations_sync"] = {
            "ok": True,
            "revision": mutation.record.revision,
            "acceptance_status": mutation.record.acceptance_status.value,
            "acceptance_source": mutation.record.acceptance_source,
        }
    except (OperationsServiceError, OperationsRepositoryError, ValueError, RuntimeError):
        logger.exception("Connected Estimate could not be shared to Operations")
        result["operations_sync"] = {
            "ok": False,
            "error": "The Estimate was connected, but its shared status could not be updated",
        }
    return result


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
    if method == "POST" and path == "/api/quickbooks/projects/preview":
        _send_json(
            handler,
            qb_estimate_service.preview_project_binding(
                paths,
                project_id=body.get("project_id", ""),
                individual_id=body.get("individual_id", ""),
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
                accept_auto_name=bool(body.get("accept_auto_name", False)),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/list":
        _send_json(handler, _estimate_call('list', qb_estimate_service.list_available_estimates,
            paths, project_id=body.get('project_id', ''), individual_id=body.get('individual_id', ''),
            start_position=body.get('start_position', 1)))
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/search":
        _send_json(handler, _estimate_call(
            "search",
            qb_estimate_service.search_quote_estimates,
            paths,
            query=body.get("query", ""),
            project_id=body.get("project_id", ""),
            individual_id=body.get("individual_id", ""),
        ))
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/reconcile-quotes":
        result = _estimate_call(
            "reconcile quote references",
            qb_estimate_service.reconcile_quote_references,
            paths,
        )
        if result.get("ok"):
            result["acceptance_refresh"] = _estimate_call(
                "refresh accepted quote references",
                qb_acceptance_service.run_connected_refresh,
                paths,
            )
        _send_json(handler, result)
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/bind":
        _send_json(
            handler,
            _share_estimate_observation(
                _estimate_call(
                    "connection",
                    qb_estimate_service.bind_estimate,
                    paths,
                    project_id=body.get("project_id", ""),
                    individual_id=body.get("individual_id", ""),
                    qb_estimate_id=body.get("qb_estimate_id", ""),
                    replace_existing=body.get("replace_existing", False),
                ),
                individual_id=str(body.get("individual_id") or ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/bind-project":
        _send_json(
            handler,
            _estimate_call(
                "project connection",
                qb_estimate_service.bind_project_estimate,
                paths,
                project_id=body.get("project_id", ""),
                qb_estimate_id=body.get("qb_estimate_id", ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/unbind-project":
        _send_json(
            handler,
            _estimate_call(
                "project disconnection",
                qb_estimate_service.unbind_project_estimate,
                paths,
                project_id=body.get("project_id", ""),
                qb_estimate_id=body.get("qb_estimate_id", ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/validate":
        _send_json(
            handler,
            _estimate_call(
                "validation",
                qb_estimate_service.validate_estimate,
                paths,
                project_id=body.get("project_id", ""),
                individual_id=body.get("individual_id", ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/create":
        _send_json(
            handler,
            _share_estimate_observation(
                _estimate_call(
                    "creation",
                    qb_estimate_service.create_estimate,
                    paths,
                    project_id=body.get("project_id", ""),
                    individual_id=body.get("individual_id", ""),
                    memo=body.get("memo", ""),
                    customer_confirmed=bool(body.get("customer_confirmed", False)),
                    customer_fields=body.get("customer_fields") or None,
                    existing_action=body.get("existing_action", ""),
                    attach_pdf=bool(body.get("attach_pdf", False)),
                    pricing_mode=body.get("pricing_mode", "retail"),
                    custom_pricing=body.get("custom_pricing") or None,
                    additional_charges=body.get("additional_charges") or None,
                    overwrite_qb_changes=bool(body.get("overwrite_qb_changes", False)),
                ),
                individual_id=str(body.get("individual_id") or ""),
            ),
        )
        return True
    if method == "POST" and path == "/api/quickbooks/estimates/create-batch":
        _send_json(
            handler,
            _estimate_call(
                "batch creation",
                qb_estimate_service.create_estimates_batch,
                paths,
                project_id=body.get("project_id", ""),
                individual_ids=body.get("individual_ids") or None,
                memo=body.get("memo", ""),
                attach_pdf=bool(body.get("attach_pdf", False)),
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
        if result.get("ok"):
            # The periodic worker may be sleeping after a disconnected startup
            # pass. Wake it so Items and Customers/Agencies both refresh as
            # soon as this user finishes connecting.
            from ..services import qb_sync_service

            qb_sync_service.request_background_sync()
        _redirect(handler, "/?qb=connected" if result.get("ok") else "/?qb=error")
    return True
