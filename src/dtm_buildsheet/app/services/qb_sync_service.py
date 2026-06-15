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


def _linked_item_ids(paths: AppPaths) -> set[str]:
    """Collect qb_item_id values already present on VB products (read-only).

    Returns an empty set if parts_db.json is absent or has no QB links yet —
    which is the current state, so nothing is ever treated as linked until the
    owner explicitly links it.
    """
    path = _parts_db_path(paths)
    if not path.exists():
        return set()
    try:
        db = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        logger.warning("parts_db.json unreadable during QB sync; treating as no links")
        return set()
    linked: set[str] = set()
    products = db.get("products", {}) if isinstance(db, dict) else {}
    if isinstance(products, dict):
        for product in products.values():
            qb_id = str((product or {}).get("qb_item_id", "")).strip()
            if qb_id:
                linked.add(qb_id)
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

    linked_ids = _linked_item_ids(paths)
    enriched = []
    linked_count = 0
    for item in items:
        is_linked = item["qb_item_id"] in linked_ids
        if is_linked:
            linked_count += 1
        enriched.append({**item, "linked": is_linked})

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
