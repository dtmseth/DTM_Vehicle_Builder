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
from datetime import datetime, timezone
from pathlib import Path

from ...paths import AppPaths
from ..adapters.quickbooks.api_client import QuickBooksApiClient, QuickBooksApiError
from ..adapters.quickbooks.oauth_client import QuickBooksOAuthError
from . import quickbooks_service

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "quickbooks_items_cache.json"


def _cache_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _CACHE_FILENAME


def _parts_db_path(paths: AppPaths) -> Path:
    return paths.workspace_config_dir / "parts_db.json"


def _linked_map(paths: AppPaths) -> dict[str, str]:
    """Map qb_item_id → product_id for VB products already linked (read-only).

    Returns an empty map if parts_db.json is absent or has no QB links yet —
    which is the current state, so nothing is ever treated as linked until the
    owner explicitly links it.
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
            qb_id = str((product or {}).get("qb_item_id", "")).strip()
            if qb_id:
                linked[qb_id] = product_id
    return linked


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


def sync_items(paths: AppPaths) -> dict:
    """Pull active Items from QBO into the local cache. Read-only re: parts_db.

    Returns a status dict: ``{"ok": True, "item_count": n, "linked": l,
    "unlinked": u, "last_sync_utc": iso}`` or ``{"ok": False, "error": ...}``.
    """
    try:
        access_token = quickbooks_service.ensure_access_token(paths)
    except QuickBooksOAuthError as exc:
        msg = "not_connected" if "not_connected" in str(exc) else str(exc)
        return {"ok": False, "error": msg}

    realm_id = quickbooks_service.get_realm_id(paths)
    if not realm_id:
        return {"ok": False, "error": "no_realm_id"}

    status = quickbooks_service.get_status(paths)
    environment = status.get("environment", "production")

    client = QuickBooksApiClient(
        access_token=access_token, realm_id=realm_id, environment=environment
    )
    try:
        items = client.fetch_active_items()
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks item sync failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    linked = _linked_map(paths)
    enriched = []
    linked_count = 0
    for item in items:
        product_id = linked.get(item["qb_item_id"])
        if product_id:
            linked_count += 1
        enriched.append({**item, "linked": bool(product_id), "linked_product_id": product_id or ""})

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
    """Return the locally cached pull (no network). Safe to call anytime."""
    cache = _read_cache(paths)
    items = cache.get("items", [])
    linked = sum(1 for i in items if i.get("linked"))
    return {
        "ok": True,
        "last_sync_utc": cache.get("last_sync_utc"),
        "item_count": cache.get("item_count", len(items)),
        "linked": linked,
        "unlinked": len(items) - linked,
        "items": items,
    }


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

    Writes ``qb_item_id`` / ``qb_sku`` / ``qb_unit_price`` / ``qb_last_synced``
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
            for field in ("qb_item_id", "qb_sku", "qb_unit_price", "qb_last_synced"):
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
