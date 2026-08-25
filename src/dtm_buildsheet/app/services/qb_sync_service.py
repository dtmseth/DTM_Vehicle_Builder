"""QuickBooks parts-sync orchestration (Phase 2, Slice A: read-only pull).

This slice is deliberately non-destructive:

- It READS Items from the connected QBO company.
- It READS ``parts_db.json`` only to mark which pulled items are already
  linked to a Vehicle Builder product (display hint).
- It WRITES only ``quickbooks_items_cache.json`` (workspace root, git-ignored)
  and the ``last_sync_utc`` timestamp in ``quickbooks_config.json``.

It NEVER writes ``parts_db.json``. Linking a QB item to a VB part (which does
add a ``qb_item_id`` to a product) is a separate, explicit, opt-in action
handled in a later slice.

Like the rest of the integration, this module never logs item names, prices,
or other company data.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from ...paths import AppPaths
from ..adapters.quickbooks.api_client import QuickBooksApiClient, QuickBooksApiError
from ..adapters.quickbooks.gateway import QuickBooksGatewayError
from ..adapters.quickbooks.oauth_client import QuickBooksOAuthError
from . import quickbooks_gateway_service, quickbooks_service

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "quickbooks_items_cache.json"
_SYNC_LOCK = threading.Lock()


def _cache_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _CACHE_FILENAME


def _parts_db_path(paths: AppPaths) -> Path:
    return paths.workspace_config_dir / "parts_db.json"


def _linked_map(paths: AppPaths) -> dict[str, str]:
    """Map qb_item_id → product_id for VB products already linked (read-only).

    Links live on each product's ``part_numbers[]`` entries (a product can hold
    many SKUs, each its own ``qb_item_id``). A legacy top-level ``qb_item_id`` is
    also honored for backward compatibility. Reads parts_db.json straight off disk
    so it reflects the current catalog — including links written by the offline
    ``qb_apply_links`` tool — without depending on any in-process cache. Returns an
    empty map if parts_db.json is absent or has no QB links yet.
    """
    path = _parts_db_path(paths)
    if not path.exists():
        return {}
    try:
        db = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        logger.warning("parts_db.json unreadable during QB sync; treating as no links")
        return {}
    linked: dict[str, str] = {}
    products = db.get("products", {}) if isinstance(db, dict) else {}
    if isinstance(products, dict):
        for product_id, product in products.items():
            product = product or {}
            # New schema: qb_item_id per part_number entry.
            for pn in product.get("part_numbers", []) or []:
                qb_id = str((pn or {}).get("qb_item_id", "")).strip()
                if qb_id:
                    linked[qb_id] = product_id
            # Legacy schema: single top-level qb_item_id.
            top = str(product.get("qb_item_id", "")).strip()
            if top:
                linked[top] = product_id
    return linked


def _enrich_with_links(items: list[dict], linked: dict[str, str]) -> tuple[list[dict], int]:
    """Stamp ``linked`` / ``linked_product_id`` onto each item from the link map.

    parts_db is the source of truth for link state, so this recomputes it rather
    than trusting any ``linked`` flag previously baked into the cache.
    """
    enriched = []
    linked_count = 0
    for item in items:
        product_id = linked.get(str(item.get("qb_item_id", "")))
        if product_id:
            linked_count += 1
        enriched.append({**item, "linked": bool(product_id), "linked_product_id": product_id or ""})
    return enriched, linked_count


def _read_cache(paths: AppPaths) -> dict:
    path = _cache_path(paths)
    if not path.exists():
        return {"last_sync_utc": None, "item_count": 0, "items": []}
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        logger.warning("quickbooks_items_cache.json unreadable; treating as empty")
    return {"last_sync_utc": None, "item_count": 0, "items": []}


def _write_cache(paths: AppPaths, cache: dict) -> None:
    path = _cache_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")


def _build_client(paths: AppPaths):
    """Local compatibility client for operations not yet centrally migrated.

    Central mode always fails closed here.  Only health and active-Item reads
    use the central gateway in this slice; no operation may fall back to a
    workstation's surviving keychain token once the feature flag is enabled.
    """
    if quickbooks_gateway_service.central_mode_enabled(paths):
        return None, {"ok": False, "error": "central_operation_not_migrated"}
    try:
        access_token = quickbooks_service.ensure_access_token(paths)
    except QuickBooksOAuthError as exc:
        msg = "not_connected" if "not_connected" in str(exc) else str(exc)
        return None, {"ok": False, "error": msg}

    realm_id = quickbooks_service.get_realm_id(paths)
    if not realm_id:
        return None, {"ok": False, "error": "no_realm_id"}

    environment = quickbooks_service.get_status(paths).get("environment", "production")
    client = QuickBooksApiClient(
        access_token=access_token, realm_id=realm_id, environment=environment
    )
    return client, None


def _fetch_active_items_locally(paths: AppPaths) -> list[dict]:
    client, error = _build_client(paths)
    if error:
        raise QuickBooksGatewayError(str(error.get("error") or "quickbooks_unavailable"))
    try:
        return client.fetch_active_items()
    except QuickBooksApiError as exc:
        # QuickBooksApiError is already reduced to its safe status/code/tid
        # summary by the local compatibility adapter.
        raise QuickBooksGatewayError(str(exc)) from None


def sync_items(paths: AppPaths) -> dict:
    """Pull active Items from QBO into the local cache. Read-only re: parts_db.

    Returns a status dict: ``{"ok": True, "item_count": n, "linked": l,
    "unlinked": u, "last_sync_utc": iso}`` or ``{"ok": False, "error": ...}``.
    """
    try:
        items = quickbooks_gateway_service.fetch_active_items(
            paths,
            local_provider=lambda: _fetch_active_items_locally(paths),
        )
    except QuickBooksGatewayError as exc:
        logger.warning("QuickBooks item sync failed: %s", exc.code)
        return {"ok": False, "error": exc.code}

    enriched, linked_count = _enrich_with_links(items, _linked_map(paths))

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache = {"last_sync_utc": now_iso, "item_count": len(enriched), "items": enriched}
    _write_cache(paths, cache)
    quickbooks_service.set_last_sync(paths, now_iso)

    logger.info("QB item sync complete: %d items (%d linked)", len(enriched), linked_count)
    return {
        "ok": True,
        "item_count": len(enriched),
        "linked": linked_count,
        "unlinked": len(enriched) - linked_count,
        "last_sync_utc": now_iso,
    }


def get_cached_items(paths: AppPaths) -> dict:
    """Return the locally cached pull (no network). Safe to call anytime.

    Link state is recomputed from the live parts_db on every read, so newly
    linked/unlinked parts show immediately without re-pulling from QuickBooks.
    """
    cache = _read_cache(paths)
    items = cache.get("items", [])
    enriched, linked_count = _enrich_with_links(items, _linked_map(paths))
    return {
        "ok": True,
        "last_sync_utc": cache.get("last_sync_utc"),
        "item_count": cache.get("item_count", len(enriched)),
        "linked": linked_count,
        "unlinked": len(enriched) - linked_count,
        "items": enriched,
    }


def find_cached_active_item_by_name(paths: AppPaths, name: str) -> dict | None:
    """Return one exact-name active Item from the latest local QB pull."""
    wanted = str(name or "").strip()
    if not wanted:
        return None
    items = _read_cache(paths).get("items", [])
    # Prefer literal case as QBO can contain both "MISC PART" and "Misc Part".
    for item in items:
        if str(item.get("name") or "").strip() == wanted:
            return item
    matches = [item for item in items
               if str(item.get("name") or "").strip().casefold() == wanted.casefold()]
    if len(matches) == 1:
        return matches[0]
    return None


# ── reconciliation (Slice C) ─────────────────────────────────────────────────
#
# Reconciliation is the "live catalog" half: it pushes QBO's authoritative
# sku / unit_price / active status onto parts the owner has ALREADY linked.
# It is deliberately bounded:
#   - Only QB-owned fields are written (qb_sku, qb_sales_description,
#     qb_unit_price, qb_inactive, qb_last_synced). The owner's categorization (model, manufacturer,
#     fits_part_types, tags, placements, …) is never touched.
#   - Only LINKED products are considered. Unlinked parts are never modified.
#   - Parts are never created or deleted. An item that vanished from QBO's
#     active set is flagged qb_inactive=true (and un-flagged if it returns).
#   - parts_db.json is written only when something actually changed, and only
#     through save_config_file (SharePoint direct-mirror), never a raw write.


def reconcile_linked_parts(paths: AppPaths) -> dict:
    """Update QB-owned fields on linked parts from the latest cached pull.

    Reads the items cache (which must come from a successful ``sync_items``)
    and applies QBO's sku/price/active status to linked products. Returns a
    stats dict. A no-op (no linked parts, or nothing changed) writes nothing.
    """
    import copy
    from datetime import datetime, timezone

    from .config_service import save_config_file
    from .parts_db_service import get_parts_db_service

    cache = _read_cache(paths)
    if not cache.get("last_sync_utc"):
        # Never reconcile against an empty/never-synced cache — that would flag
        # every linked part inactive.
        return {"ok": True, "updated": 0, "flagged_inactive": 0, "reactivated": 0,
                "reconciled_pending": 0, "skipped": "no_sync"}

    active_by_id = {i["qb_item_id"]: i for i in cache.get("items", [])}
    # name/sku → item, for matching pending parts that have now appeared in QBO.
    active_by_name: dict[str, dict] = {}
    for it in cache.get("items", []):
        for key in (it.get("name"), it.get("sku")):
            k = str(key or "").strip().lower()
            if k:
                active_by_name.setdefault(k, it)

    svc = get_parts_db_service(paths)
    doc = copy.deepcopy(svc.raw_doc())
    products = doc.get("products") or {}

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = 0
    flagged_inactive = 0
    reactivated = 0
    reconciled_pending = 0

    for product in products.values():
        qb_id = str(product.get("qb_item_id", "")).strip()
        linked_specs = []
        if qb_id:
            linked_specs.append(product)
        linked_specs.extend(
            pn for pn in (product.get("part_numbers") or [])
            if str(pn.get("qb_item_id", "")).strip()
        )

        for linked_spec in linked_specs:
            linked_id = str(linked_spec.get("qb_item_id", "")).strip()
            item = active_by_id.get(linked_id)
            if item is not None:
                changed = False
                if linked_spec.get("qb_sku") != item.get("sku", ""):
                    linked_spec["qb_sku"] = item.get("sku", "")
                    changed = True
                if linked_spec.get("qb_unit_price") != item.get("unit_price"):
                    linked_spec["qb_unit_price"] = item.get("unit_price")
                    changed = True
                if linked_spec.get("qb_sales_description", "") != item.get("description", ""):
                    linked_spec["qb_sales_description"] = item.get("description", "")
                    changed = True
                if linked_spec.get("qb_inactive"):
                    linked_spec["qb_inactive"] = False
                    reactivated += 1
                    changed = True
                if changed:
                    linked_spec["qb_last_synced"] = now_iso
                    updated += 1
            else:
                # Linked, but no longer in QBO's active set → flag (don't delete).
                if not linked_spec.get("qb_inactive"):
                    linked_spec["qb_inactive"] = True
                    linked_spec["qb_last_synced"] = now_iso
                    flagged_inactive += 1

    # Reconcile pending-QB parts: a SKU pre-added with qb_pending=true that has
    # now appeared in QBO gets linked (fill qb_item_id/sku/price, clear the flag)
    # so it stops billing as a "create item" note. Matches the part_number against
    # the QB item name or sku, like the link tool. See docs/PARTS_DB_AND_PICKER.md.
    for product in products.values():
        for pn in (product.get("part_numbers") or []):
            if not pn.get("qb_pending"):
                continue
            item = active_by_name.get(str(pn.get("part_number", "")).strip().lower())
            if item is None:
                continue
            pn["qb_item_id"] = str(item.get("qb_item_id", ""))
            pn["qb_sku"] = item.get("sku", "")
            pn["qb_unit_price"] = item.get("unit_price")
            pn["qb_sales_description"] = item.get("description", "")
            pn["qb_pending"] = False
            pn["qb_last_synced"] = now_iso
            reconciled_pending += 1

    total_changed = updated + flagged_inactive + reconciled_pending
    if total_changed:
        result = save_config_file("parts_db.json", doc, paths)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "save_failed")}
        svc.invalidate()

    logger.info(
        "QB reconcile: %d updated, %d flagged inactive, %d reactivated, %d pending linked",
        updated, flagged_inactive, reactivated, reconciled_pending,
    )
    return {
        "ok": True,
        "updated": updated,
        "flagged_inactive": flagged_inactive,
        "reactivated": reactivated,
        "reconciled_pending": reconciled_pending,
    }


def run_full_sync(paths: AppPaths) -> dict:
    """Pull active Items, then reconcile linked parts. Route + poller entry point."""
    # The startup poller and an estimate request can arrive together. Serialize
    # the pull/reconcile pair so neither reads a half-written cache or catalog.
    with _SYNC_LOCK:
        pull = sync_items(paths)
        if not pull.get("ok"):
            return pull
        if quickbooks_gateway_service.central_mode_enabled(paths):
            # This first central endpoint is a read-only catalog slice.  Do
            # not implicitly apply central data to parts_db until reviewed
            # catalog governance is migrated behind an Admin endpoint.
            return {**pull, "reconciled": {"ok": True, "skipped": "central_read_only_slice"}}
        recon = reconcile_linked_parts(paths)
        return {**pull, "reconciled": recon}


def refresh_estimate_catalog(paths: AppPaths) -> dict:
    """Refresh authoritative QB Item prices, blocking estimates on stale data."""
    result = run_full_sync(paths)
    reconciled = result.get("reconciled") if isinstance(result, dict) else None
    if not result.get("ok") or not isinstance(reconciled, dict) or not reconciled.get("ok"):
        logger.warning("QuickBooks estimate catalog refresh failed")
        return {"ok": False, "error": "pricing_refresh_failed"}
    return {"ok": True, "last_sync_utc": result.get("last_sync_utc")}


# ── customer → agency down-sync (Phase 3, first cut) ─────────────────────────
#
# Pulls QB Customers (top-level only) and upserts them into the agency store.
# Two-step reviewed flow: preview (no write) → import (write). The agency
# service owns the matching/upsert; this layer just fetches and delegates.


def preview_customer_import(paths: AppPaths) -> dict:
    """Fetch QB customers and report would-create / would-update. Writes nothing."""
    client, err = _build_client(paths)
    if err:
        return err
    try:
        customers = client.fetch_active_customers()
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks customer fetch failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    from . import agency_service, qb_customer_migration_service
    ignored_ids = qb_customer_migration_service.ignored_production_customer_ids(paths)
    customers = [
        customer for customer in customers
        if str(customer.get("qb_customer_id") or "") not in ignored_ids
    ]
    return agency_service.preview_qb_customer_import(customers, paths)


def import_customers(paths: AppPaths) -> dict:
    """Fetch QB customers and upsert them into agencies. Returns created/updated."""
    from . import qb_customer_migration_service
    if qb_customer_migration_service.customer_writes_blocked(paths):
        return {"ok": False, "error": "production_customer_migration_required"}
    client, err = _build_client(paths)
    if err:
        return err
    try:
        customers = client.fetch_active_customers()
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks customer fetch failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    from . import agency_service, qb_customer_migration_service
    ignored_ids = qb_customer_migration_service.ignored_production_customer_ids(paths)
    customers = [
        customer for customer in customers
        if str(customer.get("qb_customer_id") or "") not in ignored_ids
    ]
    result = agency_service.upsert_agencies_from_qb(customers, paths)
    logger.info(
        "QB customer import: %d created, %d updated",
        result.get("created", 0), result.get("updated", 0),
    )
    return result


def get_pricing_status(paths: AppPaths) -> dict:
    """Report whether the connected company uses QB customer price levels."""
    client, err = _build_client(paths)
    if err:
        return err
    try:
        prefs = client.fetch_preferences()
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks pricing preference fetch failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    using_levels = bool(prefs.get("using_price_levels"))
    return {
        "ok": True,
        "using_price_levels": using_levels,
        "warning": (
            "QuickBooks customer price levels are enabled. Vehicle Builder uses the "
            "reviewed local customer-pricing rule calculated from current Production "
            "Item list prices, because the Accounting API does not expose QBO's rule tables."
            if using_levels else ""
        ),
    }


def get_estimate_field_setup(paths: AppPaths) -> dict:
    """Return only the configured QB legacy sales-form field metadata.

    This is a read-only diagnostic for the estimate workflow. It exposes
    labels and QBO's positional ids, never the customer or vehicle values that
    would later be placed in those fields.
    """
    client, err = _build_client(paths)
    if err:
        return err
    try:
        preferences = client.fetch_preferences()
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks sales-form settings lookup failed: %s", exc)
        return {"ok": False, "error": "sales_form_settings_unavailable"}
    fields = preferences.get("sales_custom_fields") or []
    return {
        "ok": True,
        "fields": [
            {
                "definition_id": str(field.get("definition_id") or ""),
                "name": str(field.get("name") or ""),
            }
            for field in fields
            if str(field.get("definition_id") or "") and str(field.get("name") or "")
        ],
    }


def preview_estimate_customer(paths: AppPaths, project_id: str) -> dict:
    """Read the estimate's agency customer without creating anything."""
    from ...inputs import project_entry
    from . import agency_service

    try:
        project = project_entry.load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "unknown_project"}
    agency_id = (project.customer.agency_id or "").strip()
    agency = agency_service.get_agency(paths, agency_id) if agency_id else None
    if agency is None:
        return {"ok": False, "error": "no_agency"}

    local = agency_service.customer_profile_fields(agency)
    client, err = _build_client(paths)
    if err:
        return err

    if agency.qb_customer_id:
        raw = client.read_customer(agency.qb_customer_id)
        if raw is not None:
            customer = _normalized_customer_from_raw(raw)
            if customer.get("is_sub"):
                return {"ok": False, "error": "customer_is_sub"}
            profile = _merge_customer_profile(local, customer)
            return {
                "ok": True,
                "customer": {**customer, **profile},
                "customer_linked": True,
                "customer_complete": not agency_service.missing_estimate_customer_fields(profile),
                "missing_fields": agency_service.missing_estimate_customer_fields(profile),
            }

    finder = getattr(client, "find_top_level_customer_by_display_name", None)
    customer = finder(agency.name) if finder is not None else None
    if customer:
        profile = _merge_customer_profile(local, customer)
        return {
            "ok": True,
            "customer": {**customer, **profile},
            "customer_linked": True,
            "matched": True,
            "customer_complete": not agency_service.missing_estimate_customer_fields(profile),
            "missing_fields": agency_service.missing_estimate_customer_fields(profile),
        }
    return {
        "ok": True,
        "customer": local,
        "customer_linked": False,
        "customer_complete": not agency_service.missing_estimate_customer_fields(local),
        "missing_fields": agency_service.missing_estimate_customer_fields(local),
    }


# ── agency → customer up-sync (Phase 3, Slice 2) ─────────────────────────────
#
# The mirror in the other direction: when an agency is saved, create or update
# its QB Customer in the background. This is the only place the integration
# writes to QuickBooks. Bounded and re-entrancy-safe:
#   - Connection-gated and pytest-gated (the background entry no-ops otherwise).
#   - On first create, the new Customer.Id is written back via
#     agency_service.set_qb_customer_id — NOT handle_save_agency — so the
#     write-back never re-triggers another push.
#   - Updates are sparse and touch only the agency customer-profile fields;
#     QBO stays the source of truth for accounting-only Customer fields.


def push_agency(paths: AppPaths, agency_id: str) -> dict:
    """Create or update the QB Customer that mirrors a VB agency.

    Returns ``{"ok": True, "qb_customer_id": id, "action": "created"|"updated"}``
    or ``{"ok": False, "error": ...}``. Safe to call directly (tests) or via
    ``push_agency_in_background``.
    """
    from . import agency_service, qb_customer_migration_service

    if qb_customer_migration_service.customer_writes_blocked(paths):
        return {"ok": False, "error": "production_customer_migration_required"}

    record = agency_service.get_agency(paths, agency_id)
    if record is None:
        return {"ok": False, "error": "unknown_agency"}

    client, err = _build_client(paths)
    if err:
        return err

    fields = agency_service.customer_profile_fields(record)

    try:
        # CustomerType IDs are company-local, so resolve Retail by name instead
        # of persisting or hard-coding the production company's current ID.
        retail_type_id = client.find_customer_type_by_name("Retail")
        if not retail_type_id:
            return {"ok": False, "error": "retail_customer_type_not_found"}
        fields["customer_type_id"] = retail_type_id
        existing_id = (record.qb_customer_id or "").strip()
        if existing_id:
            current = client.read_customer(existing_id)
            if current is not None:
                client.update_customer(existing_id, current.get("SyncToken", "0"), fields)
                logger.info("QB agency push: updated existing customer")
                return {"ok": True, "qb_customer_id": existing_id, "action": "updated"}
            # Linked Id no longer exists in QBO (deleted there) → recreate.

        # A newly-created app agency may already exist in QuickBooks (for
        # example after a customer spreadsheet import). Link that top-level
        # Customer instead of creating a duplicate. We deliberately do not
        # overwrite its profile during this automatic background path.
        finder = getattr(client, "find_top_level_customer_by_display_name", None)
        matched = finder(record.name) if finder is not None else None
        if matched:
            matched_id = str(matched.get("qb_customer_id", "")).strip()
            if matched_id:
                current = client.read_customer(matched_id)
                if current is not None:
                    client.update_customer(
                        matched_id,
                        current.get("SyncToken", "0"),
                        {"customer_type_id": retail_type_id},
                    )
                agency_service.merge_missing_customer_profile(record, matched)
                agency_service.set_qb_customer_id(paths, agency_id, matched_id)
                logger.info("QB agency push: linked existing customer")
                return {"ok": True, "qb_customer_id": matched_id, "action": "linked"}

        result = client.create_customer(fields)
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks agency push failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    new_id = result.get("qb_customer_id", "")
    if new_id:
        agency_service.set_qb_customer_id(paths, agency_id, new_id)
    logger.info("QB agency push: created customer")
    return {"ok": True, "qb_customer_id": new_id, "action": "created"}


def push_agency_in_background(paths: AppPaths, agency_id: str) -> None:
    """Fire ``push_agency`` on a daemon thread. No-ops under pytest or when
    QuickBooks is not connected, so the agency save path can call it blindly."""
    import os
    import threading

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    from . import qb_customer_migration_service
    if qb_customer_migration_service.customer_writes_blocked(paths):
        return
    try:
        if not quickbooks_gateway_service.connection_health(paths).get("connected"):
            return
    except Exception:  # noqa: BLE001 — never let a status read break the save
        return

    def _run():
        try:
            push_agency(paths, agency_id)
        except Exception:  # noqa: BLE001 — background mirror must never raise
            logger.warning("QuickBooks agency background push failed")

    threading.Thread(target=_run, name="qb-agency-push", daemon=True).start()


def push_agency_after_save(paths: AppPaths, agency_id: str) -> dict:
    """Synchronously mirror one saved agency so the UI can report failures."""
    import os
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"ok": True, "skipped": "pytest"}
    from . import qb_customer_migration_service
    if qb_customer_migration_service.customer_writes_blocked(paths):
        return {"ok": False, "error": "production_customer_migration_required"}
    try:
        if not quickbooks_gateway_service.connection_health(paths).get("connected"):
            return {"ok": True, "skipped": "not_connected"}
    except Exception:
        return {"ok": False, "error": "quickbooks_status_unavailable"}
    return push_agency(paths, agency_id)


def _normalized_customer_from_raw(raw: dict) -> dict:
    """Normalize the QBO Customer fields stored by the estimate flow."""
    from ..adapters.quickbooks.api_client import _normalize_customer
    return _normalize_customer(raw)


def _has_customer_value(value: object) -> bool:
    return value is not None and bool(str(value).strip())


def _merge_customer_profile(local: dict, remote: dict, supplied: dict | None = None) -> dict:
    """Combine app, explicit confirmation, and QB values without data loss.

    Explicit non-empty confirmation values win. Existing app values win over
    QBO values (the same additive policy as the pull). QBO fills only gaps.
    """
    from ...domain.agency_models import CUSTOMER_PROFILE_FIELDS

    merged = {field: local.get(field) for field in CUSTOMER_PROFILE_FIELDS}
    for field, value in (supplied or {}).items():
        if field in merged and _has_customer_value(value):
            merged[field] = value
    for field in CUSTOMER_PROFILE_FIELDS:
        if not _has_customer_value(merged.get(field)) and _has_customer_value(remote.get(field)):
            merged[field] = remote[field]
    return merged


def ensure_top_level_customer(
    paths: AppPaths,
    project,
    *,
    client,
    confirmed: bool = False,
    fields: dict | None = None,
) -> dict:
    """Resolve the agency's top-level Customer without creating a job.

    An existing QB link is authoritative. If there is no link, an exact
    top-level name match is reused. A new Customer is created only after the UI
    explicitly confirms the customer fields, which prevents an estimate click
    from silently creating a malformed customer.
    """
    from . import agency_service

    agency_id = (project.customer.agency_id or "").strip()
    agency = agency_service.get_agency(paths, agency_id) if agency_id else None
    if agency is None:
        return {"ok": False, "error": "no_agency"}

    supplied = fields or {}
    local_fields = agency_service.customer_profile_fields(agency)

    customer = None
    customer_id = (agency.qb_customer_id or "").strip()
    if customer_id:
        raw = client.read_customer(customer_id)
        if raw is not None:
            customer = _normalized_customer_from_raw(raw)
            if customer.get("is_sub"):
                return {"ok": False, "error": "customer_is_sub"}
        else:
            customer_id = ""

    if not customer_id:
        finder = getattr(client, "find_top_level_customer_by_display_name", None)
        if finder is not None:
            customer = finder(local_fields["name"])
        else:
            # Compatibility for test doubles and older adapters. The real
            # client uses the top-level-filtering method above.
            existing_id = client.find_customer_by_display_name(local_fields["name"])
            raw = client.read_customer(existing_id) if existing_id else None
            customer = _normalized_customer_from_raw(raw) if raw else None
        if customer:
            customer_id = str(customer.get("qb_customer_id", "")).strip()
            if customer_id:
                agency_service.set_qb_customer_id(paths, agency.agency_id, customer_id)

    effective_fields = _merge_customer_profile(local_fields, customer or {}, supplied)

    if not customer_id:
        if not confirmed:
            return {
                "ok": False,
                "error": "customer_required",
                "customer": effective_fields,
            }
        missing = agency_service.missing_estimate_customer_fields(effective_fields)
        if missing:
            return {
                "ok": False,
                "error": "customer_incomplete",
                "customer": effective_fields,
                "missing_fields": missing,
            }
        try:
            retail_type_id = client.find_customer_type_by_name("Retail")
            if not retail_type_id:
                return {"ok": False, "error": "retail_customer_type_not_found"}
            created = client.create_customer({
                **effective_fields, "customer_type_id": retail_type_id,
            })
        except QuickBooksApiError as exc:
            logger.warning("QuickBooks customer create failed: %s", exc)
            return {"ok": False, "error": str(exc)}
        customer_id = str(created.get("qb_customer_id", "")).strip()
        if not customer_id:
            return {"ok": False, "error": "customer_create_failed"}
        agency_service.set_qb_customer_id(paths, agency.agency_id, customer_id)
        customer = {"qb_customer_id": customer_id, **effective_fields, "is_sub": False}
    else:
        missing = agency_service.missing_estimate_customer_fields(effective_fields)
        if missing:
            return {
                "ok": False,
                "error": "customer_incomplete",
                "customer": effective_fields,
                "missing_fields": missing,
            }
        if confirmed:
            # This is an explicit user confirmation in the estimate dialog.
            # Only a sparse Customer update is made; no financial document is
            # created unless the profile is complete and this function returns
            # successfully to the estimate service. Updating even when the
            # merged app profile is already complete ensures newly entered
            # addresses/contact fields reach the linked QB Customer too.
            try:
                current = client.read_customer(customer_id)
                sync_token = (current or {}).get("SyncToken", (customer or {}).get("sync_token", "0"))
                retail_type_id = client.find_customer_type_by_name("Retail")
                if not retail_type_id:
                    return {"ok": False, "error": "retail_customer_type_not_found"}
                client.update_customer(customer_id, sync_token, {
                    **effective_fields, "customer_type_id": retail_type_id,
                })
            except QuickBooksApiError as exc:
                logger.warning("QuickBooks customer profile update failed: %s", exc)
                return {"ok": False, "error": str(exc)}
            customer = {**(customer or {}), **effective_fields, "qb_customer_id": customer_id}

    # Persist the profile confirmed above, or the additional fields retrieved
    # from an already-complete QB Customer. This never schedules another QB
    # write; it only makes future pulls/estimates use the same local profile.
    agency_service.update_agency_customer_profile(paths, agency.agency_id, effective_fields)

    customer_name = str((customer or {}).get("name", "") or effective_fields["name"]).strip()
    if customer_name and not project.customer.name:
        project.customer.name = customer_name
    if customer_name and not project.customer.agency:
        project.customer.agency = customer_name
    if customer:
        if not project.customer.contact:
            project.customer.contact = str(customer.get("contact_name", "")).strip()
        if not project.customer.phone:
            project.customer.phone = str(customer.get("contact_phone", "")).strip()
        if not project.customer.email:
            project.customer.email = str(customer.get("contact_email", "")).strip()

    return {
        "ok": True,
        "qb_customer_id": customer_id,
        # Keep every existing QB attribute but overlay the additive profile.
        # A linked customer response can be sparse (for example a fake/test
        # client or a QBO response without PrimaryPhone), while the local
        # agency profile may already have the phone the estimate form needs.
        "customer": {**(customer or {}), **effective_fields},
        "customer_source": "existing" if not confirmed else "confirmed",
    }


# ── legacy per-vehicle job bridge (backward compatibility) ───────────────────
#
# Older builds may still need to inspect or explicitly maintain a QBO
# sub-customer/job, so this endpoint remains available. New estimate creation
# does not call it; new estimates use the agency's top-level Customer directly.


def _find_individual(project, individual_id: str):
    """Return (build_unit, individual) for the unit id, or (None, None)."""
    for bu in project.build_units:
        for ind in bu.individuals:
            if ind.individual_id == individual_id:
                return bu, ind
    return None, None


def _job_display_name(project, build_unit, unit) -> str:
    """A unique, human-readable job name: '<year> <model> · Unit N · Q<quote>'.

    QBO requires DisplayName to be globally unique, so we fold in the unit
    number and quote number; if neither is present we suffix a short id slice
    so two unnamed vehicles on one project don't collide.
    """
    year = (project.customer.build_year or unit.year or "").strip()
    model = (unit.model or build_unit.vehicle_model or "").strip()
    head = " ".join(p for p in (year, model) if p) or "Vehicle"
    tail: list[str] = []
    if unit.unit_number:
        tail.append(f"Unit {unit.unit_number}")
    if project.customer.quote_number:
        tail.append(f"Q{project.customer.quote_number}")
    if not tail:
        tail.append(unit.individual_id[:8])
    return f"{head} · " + " · ".join(tail)


def push_vehicle_job(paths: AppPaths, project_id: str, individual_id: str) -> dict:
    """Create (or reuse) the QBO sub-customer/job for one vehicle.

    Ensures the agency's Customer exists first. Idempotent: if the unit already
    carries a qb_job_id, or a job with the computed DisplayName already exists
    in QBO, that one is reused rather than duplicated. Writes qb_job_id back.
    """
    from ...inputs import project_entry
    from . import agency_service

    try:
        project = project_entry.load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "unknown_project"}
    build_unit, unit = _find_individual(project, individual_id)
    if unit is None:
        return {"ok": False, "error": "unknown_unit"}

    agency_id = (project.customer.agency_id or "").strip()
    agency = agency_service.get_agency(paths, agency_id) if agency_id else None
    if agency is None:
        return {"ok": False, "error": "no_agency"}

    # Make sure the parent Customer exists in QBO (create it if this agency has
    # never been pushed up). push_agency writes qb_customer_id back.
    if not agency.qb_customer_id:
        pushed = push_agency(paths, agency_id)
        if not pushed.get("ok"):
            return pushed
        agency = agency_service.get_agency(paths, agency_id)
    parent_id = agency.qb_customer_id
    if not parent_id:
        return {"ok": False, "error": "agency_not_in_qb"}

    if unit.qb_job_id:
        return {"ok": True, "qb_job_id": unit.qb_job_id, "action": "exists"}

    client, err = _build_client(paths)
    if err:
        return err

    name = _job_display_name(project, build_unit, unit)
    try:
        existing = client.find_customer_by_display_name(name)
        if existing:
            job_id = existing
            action = "linked"
        else:
            job_id = client.create_job(parent_id, name).get("qb_customer_id", "")
            action = "created"
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks vehicle-job push failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    if not job_id:
        return {"ok": False, "error": "no_job_id"}

    unit.qb_job_id = job_id
    project_entry.save_project(project, paths)
    logger.info("QB vehicle job %s", action)
    return {"ok": True, "qb_job_id": job_id, "display_name": name, "action": action}


# ── background sync (Slice C) ─────────────────────────────────────────────────

_POLL_INTERVAL_SECONDS = 30 * 60
_bg_thread = None


def start_background_sync(paths: AppPaths, *, interval_seconds: int = _POLL_INTERVAL_SECONDS) -> None:
    """Kick a daemon thread that runs a full sync now and every interval.

    No-ops under pytest and never starts twice. Each pass runs only when the
    connection is live; any error is swallowed so the poller keeps going.
    """
    import os
    import threading
    import time

    global _bg_thread
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if _bg_thread is not None and _bg_thread.is_alive():
        return

    def _loop():
        while True:
            try:
                if quickbooks_gateway_service.connection_health(paths).get("connected"):
                    run_full_sync(paths)
            except Exception:  # noqa: BLE001 — poller must never die
                logger.warning("QuickBooks background sync pass failed")
            time.sleep(interval_seconds)

    _bg_thread = threading.Thread(target=_loop, name="qb-sync-poll", daemon=True)
    _bg_thread.start()


# ── linking (Slice B) ────────────────────────────────────────────────────────
#
# Linking is the only path that writes parts_db.json, and it does so through
# the normal config-save pipeline (save_config_file → SharePoint direct-mirror)
# — never a raw write — so a link survives the next shared-settings sync.
# It is additive: it sets QB fields on one product and touches nothing else.


def _find_cached_item(paths: AppPaths, qb_item_id: str) -> dict | None:
    for item in _read_cache(paths).get("items", []):
        if item.get("qb_item_id") == qb_item_id:
            return item
    return None


def _update_cache_link(paths: AppPaths, qb_item_id: str, product_id: str) -> None:
    cache = _read_cache(paths)
    for item in cache.get("items", []):
        if item.get("qb_item_id") == qb_item_id:
            item["linked"] = bool(product_id)
            item["linked_product_id"] = product_id
    _write_cache(paths, cache)


def link_item(paths: AppPaths, *, qb_item_id: str, product_id: str) -> dict:
    """Attach a QB item to an existing VB product (explicit, additive).

    Writes ``qb_item_id`` / ``qb_sku`` / ``qb_sales_description`` /
    ``qb_unit_price`` / ``qb_last_synced``
    onto the chosen product and saves through the config pipeline. Rejects the
    link if the item is already linked elsewhere or the product already carries
    a different QB item, so the mapping stays one-to-one.
    """
    import copy
    from datetime import datetime, timezone

    from .config_service import save_config_file
    from .parts_db_service import get_parts_db_service

    if not qb_item_id or not product_id:
        return {"ok": False, "error": "missing_argument"}

    item = _find_cached_item(paths, qb_item_id)
    if item is None:
        return {"ok": False, "error": "unknown_item"}

    svc = get_parts_db_service(paths)
    doc = copy.deepcopy(svc.raw_doc())
    products = doc.get("products") or {}
    product = products.get(product_id)
    if product is None:
        return {"ok": False, "error": "unknown_product"}

    # Enforce a one-to-one mapping.
    for pid, other in products.items():
        if pid != product_id and str(other.get("qb_item_id", "")).strip() == qb_item_id:
            return {"ok": False, "error": "item_already_linked", "linked_product_id": pid}
    existing = str(product.get("qb_item_id", "")).strip()
    if existing and existing != qb_item_id:
        return {"ok": False, "error": "product_already_linked", "existing_qb_item_id": existing}

    product["qb_item_id"] = qb_item_id
    product["qb_sku"] = item.get("sku", "")
    product["qb_unit_price"] = item.get("unit_price")
    product["qb_sales_description"] = item.get("description", "")
    product["qb_last_synced"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = save_config_file("parts_db.json", doc, paths)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "save_failed")}
    svc.invalidate()
    _update_cache_link(paths, qb_item_id, product_id)
    logger.info("QB item linked to product")
    return {"ok": True, "product_id": product_id}


def unlink_item(paths: AppPaths, *, qb_item_id: str) -> dict:
    """Detach a QB item from whatever product carries it (additive reverse).

    Removes only the QB fields from the product; everything else is untouched.
    """
    import copy

    from .config_service import save_config_file
    from .parts_db_service import get_parts_db_service

    if not qb_item_id:
        return {"ok": False, "error": "missing_argument"}

    svc = get_parts_db_service(paths)
    doc = copy.deepcopy(svc.raw_doc())
    products = doc.get("products") or {}

    target_id = None
    for pid, product in products.items():
        if str(product.get("qb_item_id", "")).strip() == qb_item_id:
            target_id = pid
            for field in (
                "qb_item_id", "qb_sku", "qb_unit_price", "qb_sales_description", "qb_last_synced"
            ):
                product.pop(field, None)
            break

    if target_id is None:
        # Nothing in parts_db carries it; just clear the cache flag.
        _update_cache_link(paths, qb_item_id, "")
        return {"ok": True, "product_id": ""}

    result = save_config_file("parts_db.json", doc, paths)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "save_failed")}
    svc.invalidate()
    _update_cache_link(paths, qb_item_id, "")
    logger.info("QB item unlinked from product")
    return {"ok": True, "product_id": target_id}
