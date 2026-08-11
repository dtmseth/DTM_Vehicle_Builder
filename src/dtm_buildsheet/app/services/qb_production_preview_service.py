"""Isolated, read-only production QuickBooks catalog preview.

This is deliberately *not* the normal QB sync path.  It uses a separate
production OAuth profile, separate encrypted credentials, a separate item
cache, and a snapshot-pinned Builder catalog.  It can pull and compare item
data, but it never calls ``save_config_file`` and never writes ``parts_db``.

The owner reviews the field mapping and exception counts first.  Only a later,
explicitly approved mapping-apply feature may update catalog links.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ...paths import AppPaths
from ..adapters.quickbooks.api_client import QuickBooksApiClient, QuickBooksApiError
from ..adapters.quickbooks.oauth_client import QuickBooksOAuthError
from . import quickbooks_service

logger = logging.getLogger(__name__)

_PROFILE = quickbooks_service.PRODUCTION_PREVIEW_PROFILE
_SNAPSHOTS_DIRNAME = "quickbooks_migration_snapshots"
_STATE_FILENAME = "quickbooks_production_mapping_state.json"
_CACHE_FILENAME = "quickbooks_production_preview_items_cache.json"
_REPORT_FILENAME = "quickbooks_production_mapping_report.json"
_PLAN_FILENAME = "quickbooks_production_mapping_plan.json"
_HISTORICAL_PLAN_FILENAME = "quickbooks_production_historical_link_plan.json"
_ALLOWED_MAPPING_FIELDS = {"name", "sku"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _STATE_FILENAME


def _cache_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _CACHE_FILENAME


def _report_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _REPORT_FILENAME


def _plan_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _PLAN_FILENAME


def _historical_plan_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _HISTORICAL_PLAN_FILENAME


def _snapshot_root(paths: AppPaths) -> Path:
    return paths.workspace_dir / _SNAPSHOTS_DIRNAME


def _snapshot_label(value: str) -> str:
    label = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    if not label:
        label = "catalog-review"
    return label[:48]


def _catalog_counts(document: dict) -> dict[str, int]:
    products = document.get("products")
    if not isinstance(products, dict):
        raise ValueError("invalid_parts_db")
    part_numbers = [
        part
        for product in products.values()
        if isinstance(product, dict)
        for part in (product.get("part_numbers") or [])
        if isinstance(part, dict)
    ]
    return {
        "products": len(products),
        "part_numbers": len(part_numbers),
        "linked_part_numbers": sum(bool(str(part.get("qb_item_id") or "").strip()) for part in part_numbers),
        "pending_part_numbers": sum(part.get("qb_pending") is True for part in part_numbers),
    }


def _copy_snapshot_file(source: Path, destination: Path) -> dict[str, object]:
    shutil.copy2(source, destination)
    os.chmod(destination, 0o444)
    return {
        "file": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
    }


def create_baseline_snapshot(paths: AppPaths, label: str = "") -> dict:
    """Create and select a local-only immutable catalog comparison baseline."""
    parts_path = paths.workspace_config_dir / "parts_db.json"
    try:
        parts_document = json.loads(parts_path.read_text(encoding="utf-8"))
        catalog = _catalog_counts(parts_document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {"ok": False, "error": "invalid_parts_db"}

    cache_path = paths.workspace_dir / "quickbooks_items_cache.json"
    standard_config = _read_json(paths.workspace_dir / "quickbooks_config.json", {})
    cache_document = None
    if standard_config.get("environment") == "sandbox" and cache_path.is_file():
        try:
            candidate = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict) and isinstance(candidate.get("items") or [], list):
                cache_document = candidate
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            cache_document = None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_name = f"{timestamp}-{_snapshot_label(label)}"
    directory = _snapshot_root(paths) / snapshot_name
    if directory.exists():
        return {"ok": False, "error": "snapshot_already_exists"}

    directory.mkdir(parents=True)
    try:
        files = {"parts_db": _copy_snapshot_file(parts_path, directory / "parts_db.json")}
        if cache_document is not None:
            files["sandbox_items_cache"] = _copy_snapshot_file(
                cache_path, directory / "sandbox_quickbooks_items_cache.json"
            )
        manifest = {
            "schema_version": 1,
            "snapshot_type": "quickbooks_production_mapping_baseline",
            "created_utc": _iso_now(),
            "label": _snapshot_label(label),
            "catalog": catalog,
            "sandbox_items_cache": (
                {
                    "items": len(cache_document.get("items") or []),
                    "last_sync_utc": cache_document.get("last_sync_utc"),
                }
                if cache_document is not None
                else None
            ),
            "files": files,
            "safety": {
                "contains_credentials": False,
                "contains_oauth_tokens": False,
                "restore_rule": "Never restore automatically. Owner review is required before any catalog rollback.",
                "production_sync": "disabled until a production mapping is reviewed and approved",
            },
        }
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o444)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        logger.exception("Could not create QuickBooks production mapping baseline")
        return {"ok": False, "error": "snapshot_create_failed"}

    selected = select_snapshot(paths, snapshot_name)
    if not selected.get("ok"):
        return selected
    return {
        "ok": True,
        "snapshot_name": snapshot_name,
        "snapshot": selected.get("selected_snapshot"),
        "status": selected,
    }


def _default_state() -> dict:
    return {
        "schema_version": 1,
        "snapshot_name": "",
        "mapping_field": "",
        "last_preview_utc": None,
    }


def _state(paths: AppPaths) -> dict:
    merged = _default_state()
    persisted = _read_json(_state_path(paths), {})
    for key in merged:
        if key in persisted:
            merged[key] = persisted[key]
    return merged


def _snapshot_name(value: str) -> str:
    candidate = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", candidate):
        raise ValueError("invalid_snapshot_name")
    return candidate


def _snapshot_directory(paths: AppPaths, name: str) -> Path:
    root = _snapshot_root(paths).resolve()
    directory = (root / _snapshot_name(name)).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("invalid_snapshot_name") from exc
    return directory


def _valid_snapshot(paths: AppPaths, name: str) -> tuple[dict, Path] | None:
    try:
        directory = _snapshot_directory(paths, name)
    except ValueError:
        return None
    manifest = _read_json(directory / "manifest.json", {})
    if manifest.get("snapshot_type") != "quickbooks_production_mapping_baseline":
        return None
    file_spec = ((manifest.get("files") or {}).get("parts_db") or {})
    parts_file = directory / str(file_spec.get("file") or "")
    if not parts_file.is_file() or file_spec.get("sha256") != _sha256(parts_file):
        return None
    cache_spec = ((manifest.get("files") or {}).get("sandbox_items_cache") or {})
    if cache_spec:
        cache_file = directory / str(cache_spec.get("file") or "")
        if not cache_file.is_file() or cache_spec.get("sha256") != _sha256(cache_file):
            return None
    return manifest, directory


def list_snapshots(paths: AppPaths) -> dict:
    """List valid local mapping baselines without exposing their full contents."""
    root = _snapshot_root(paths)
    snapshots = []
    if root.exists():
        for directory in sorted((item for item in root.iterdir() if item.is_dir()), reverse=True):
            valid = _valid_snapshot(paths, directory.name)
            if valid is None:
                continue
            manifest, _ = valid
            snapshots.append(
                {
                    "name": directory.name,
                    "created_utc": manifest.get("created_utc"),
                    "label": manifest.get("label", ""),
                    "catalog": manifest.get("catalog") or {},
                    "has_sandbox_items_cache": bool(manifest.get("sandbox_items_cache")),
                }
            )
    return {"ok": True, "snapshots": snapshots}


def select_snapshot(paths: AppPaths, snapshot_name: str) -> dict:
    valid = _valid_snapshot(paths, snapshot_name)
    if valid is None:
        return {"ok": False, "error": "snapshot_not_found_or_invalid"}
    state = _state(paths)
    state["snapshot_name"] = _snapshot_name(snapshot_name)
    state["mapping_field"] = ""
    state["last_preview_utc"] = None
    _write_json(_state_path(paths), state)
    _report_path(paths).unlink(missing_ok=True)
    _plan_path(paths).unlink(missing_ok=True)
    _historical_plan_path(paths).unlink(missing_ok=True)
    return get_status(paths)


def _selected_snapshot(paths: AppPaths) -> tuple[dict, Path] | None:
    name = str(_state(paths).get("snapshot_name") or "")
    return _valid_snapshot(paths, name) if name else None


def _snapshot_document(paths: AppPaths) -> tuple[dict, dict, Path] | None:
    selected = _selected_snapshot(paths)
    if selected is None:
        return None
    manifest, directory = selected
    parts_spec = ((manifest.get("files") or {}).get("parts_db") or {})
    parts_path = directory / str(parts_spec.get("file") or "parts_db.json")
    document = _read_json(parts_path, {})
    if not isinstance(document.get("products"), dict):
        return None
    return manifest, document, directory


def get_status(paths: AppPaths) -> dict:
    snapshots = list_snapshots(paths)["snapshots"]
    state = _state(paths)
    selected = _selected_snapshot(paths)
    selected_summary = None
    if selected is not None:
        manifest, _ = selected
        selected_summary = {
            "name": state["snapshot_name"],
            "created_utc": manifest.get("created_utc"),
            "catalog": manifest.get("catalog") or {},
            "has_sandbox_items_cache": bool(manifest.get("sandbox_items_cache")),
        }
    cache = _read_json(_cache_path(paths), {"item_count": 0, "last_preview_utc": None, "items": []})
    active_count = int(cache.get("active_item_count", cache.get("item_count", 0)) or 0)
    inactive_count = int(cache.get("inactive_item_count") or 0)
    return {
        "ok": True,
        "preview_only": True,
        "production_sync_enabled": False,
        "selected_snapshot": selected_summary,
        "snapshots": snapshots,
        "mapping_field": state.get("mapping_field", ""),
        "last_preview_utc": state.get("last_preview_utc"),
        "production_item_count": active_count,
        "production_active_item_count": active_count,
        "production_inactive_item_count": inactive_count,
        "production_total_item_count": active_count + inactive_count,
        "connection": quickbooks_service.get_status(paths, profile=_PROFILE),
    }


def save_connection(
    paths: AppPaths,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict:
    if _selected_snapshot(paths) is None:
        return {"ok": False, "error": "snapshot_required"}
    parsed = urlparse((redirect_uri or "").strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return {"ok": False, "error": "production_redirect_must_be_https"}
    result = quickbooks_service.save_settings(
        paths,
        client_id=client_id,
        client_secret=client_secret,
        environment="production",
        redirect_uri=redirect_uri,
        profile=_PROFILE,
    )
    if result.get("ok") is False:
        return result
    return get_status(paths)


def generate_auth_url(paths: AppPaths) -> dict:
    if _selected_snapshot(paths) is None:
        return {"ok": False, "error": "snapshot_required"}
    return quickbooks_service.generate_auth_url(paths, profile=_PROFILE)


def disconnect(paths: AppPaths) -> dict:
    result = quickbooks_service.disconnect(paths, profile=_PROFILE)
    return {**result, "preview_only": True, "production_sync_enabled": False}


def _build_client(paths: AppPaths) -> tuple[QuickBooksApiClient | None, dict | None]:
    status = quickbooks_service.get_status(paths, profile=_PROFILE)
    if status.get("environment") != "production":
        return None, {"ok": False, "error": "production_profile_required"}
    try:
        token = quickbooks_service.ensure_access_token(paths, profile=_PROFILE)
    except QuickBooksOAuthError as exc:
        return None, {"ok": False, "error": "not_connected" if "not_connected" in str(exc) else "authorization_failed"}
    realm_id = quickbooks_service.get_realm_id(paths, profile=_PROFILE)
    if not realm_id:
        return None, {"ok": False, "error": "no_realm_id"}
    return QuickBooksApiClient(access_token=token, realm_id=realm_id, environment="production"), None


def pull_production_catalog(paths: AppPaths) -> dict:
    """Read the live Item catalog into an isolated cache and build a comparison.

    This function has no path to the normal reconciliation service and cannot
    update ``parts_db.json``.  It is the only production API read required for
    the first mapping review.
    """
    if _selected_snapshot(paths) is None:
        return {"ok": False, "error": "snapshot_required"}
    client, error = _build_client(paths)
    if error:
        return error
    assert client is not None
    try:
        active_items = [{**item, "active": True} for item in client.fetch_active_items()]
        inactive_items = [{**item, "active": False} for item in client.fetch_inactive_items()]
        items = active_items + inactive_items
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks production catalog preview failed: %s", exc)
        return {"ok": False, "error": "production_catalog_pull_failed"}

    pulled_at = _iso_now()
    _write_json(
        _cache_path(paths),
        {
            "schema_version": 2,
            "last_preview_utc": pulled_at,
            "item_count": len(items),
            "active_item_count": len(active_items),
            "inactive_item_count": len(inactive_items),
            "items": items,
        },
    )
    state = _state(paths)
    state["last_preview_utc"] = pulled_at
    _write_json(_state_path(paths), state)
    report = build_mapping_report(paths)
    return {
        "ok": report.get("ok") is True,
        "preview_only": True,
        "production_sync_enabled": False,
        "item_count": len(items),
        "active_item_count": len(active_items),
        "inactive_item_count": len(inactive_items),
        "report": report.get("summary") if report.get("ok") else None,
        "error": report.get("error") if not report.get("ok") else None,
    }


def _normal(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _raw_name(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _historical_name(value: object) -> str:
    return re.sub(r"\s*\(deleted\)\s*$", "", _raw_name(value), flags=re.IGNORECASE)


def _same_price(left: object, right: object) -> bool:
    try:
        return abs(float(left) - float(right)) < 0.005
    except (TypeError, ValueError):
        return left is None and right is None


def _historical_link_plan(
    *,
    snapshot_name: str,
    directory: Path,
    document: dict,
    items: list[dict],
    cache_sha256: str,
) -> dict:
    """Match prior sandbox links to production using export lineage evidence."""
    sandbox_cache = _read_json(directory / "sandbox_quickbooks_items_cache.json", {})
    sandbox_by_id = {
        str(item.get("qb_item_id") or ""): item
        for item in (sandbox_cache.get("items") or [])
        if isinstance(item, dict) and str(item.get("qb_item_id") or "")
    }
    production = [item for item in items if item.get("type") != "Category"]
    by_raw_name: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    by_description: dict[str, list[dict]] = {}
    for item in production:
        by_raw_name.setdefault(_raw_name(item.get("name")), []).append(item)
        by_name.setdefault(_historical_name(item.get("name")), []).append(item)
        description_key = _normal(item.get("description"))
        if description_key:
            by_description.setdefault(description_key, []).append(item)

    matches: list[dict] = []
    exceptions: list[dict] = []
    basis_counts: dict[str, int] = {}
    linked_rows = [
        row
        for rows in _catalog_entries(document).values()
        for row in rows
        if row["was_linked"]
    ]
    for builder in linked_rows:
        sandbox = sandbox_by_id.get(builder["baseline_qb_item_id"])
        if sandbox is None:
            exceptions.append({"kind": "sandbox_item_missing", "builder": builder})
            continue

        # Prefer the literal production Name. Some exported companies retain
        # both an active SKU and an older ``SKU (deleted)`` Item with the same
        # description. The active/raw-name record is the correct successor;
        # stripping ``(deleted)`` is only a fallback for genuinely retired SKUs.
        candidates = by_raw_name.get(_raw_name(sandbox.get("name")), [])
        basis = "exact_name"
        if len(candidates) != 1:
            candidates = by_name.get(_historical_name(sandbox.get("name")), [])
            basis = "historical_deleted_name"
        if len(candidates) != 1:
            description_key = _normal(sandbox.get("description"))
            description_candidates = by_description.get(description_key, []) if description_key else []
            same_type = [
                item for item in description_candidates
                if str(item.get("type") or "") == str(sandbox.get("type") or "")
            ]
            candidates = same_type or description_candidates
            basis = "exact_description"

        if len(candidates) != 1:
            sandbox_name = _normal(sandbox.get("name"))
            sandbox_description = _normal(sandbox.get("description"))
            candidates = [
                item for item in production
                if _normal(item.get("name")) == f"{sandbox_name}B"
                and sandbox_description
                and _normal(item.get("description")).startswith(sandbox_description)
                and str(item.get("type") or "") == str(sandbox.get("type") or "")
            ]
            basis = "name_variant_description_prefix"

        if len(candidates) != 1:
            exceptions.append(
                {
                    "kind": "historical_match_ambiguous" if candidates else "historical_match_missing",
                    "builder": builder,
                    "sandbox_item": {
                        "qb_item_id": sandbox.get("qb_item_id", ""),
                        "name": sandbox.get("name", ""),
                        "type": sandbox.get("type", ""),
                    },
                    "production_candidates": [
                        {"qb_item_id": item.get("qb_item_id", ""), "name": item.get("name", "")}
                        for item in candidates[:5]
                    ],
                }
            )
            continue

        item = candidates[0]
        basis_counts[basis] = basis_counts.get(basis, 0) + 1
        differences = ["production_item_id"]
        if not str(item.get("sku") or "").strip():
            differences.append("blank_qb_sku_uses_builder_part_number")
        if _raw_name(item.get("name")) != _raw_name(sandbox.get("name")):
            differences.append("name_changed")
        if _normal(item.get("description")) == _normal(sandbox.get("description")) and str(
            item.get("description") or ""
        ) != str(sandbox.get("description") or ""):
            differences.append("description_formatting_only")
        elif _normal(item.get("description")) != _normal(sandbox.get("description")):
            differences.append("description_changed")
        if not _same_price(item.get("unit_price"), sandbox.get("unit_price")):
            differences.append("price_changed_production_wins")
        if item.get("active") is False:
            differences.append("inactive_production_item")
        if str(item.get("type") or "") != str(sandbox.get("type") or ""):
            differences.append("type_changed")
        matches.append(
            {
                "builder": builder,
                "sandbox_item": {
                    "qb_item_id": str(sandbox.get("qb_item_id") or ""),
                    "name": str(sandbox.get("name") or ""),
                    "type": str(sandbox.get("type") or ""),
                    "unit_price": sandbox.get("unit_price"),
                },
                "production_item": {
                    "qb_item_id": str(item.get("qb_item_id") or ""),
                    "name": str(item.get("name") or ""),
                    "sku": str(item.get("sku") or ""),
                    "description": str(item.get("description") or ""),
                    "unit_price": item.get("unit_price"),
                    "type": str(item.get("type") or ""),
                    "active": item.get("active") is not False,
                },
                "match_basis": basis,
                "confidence": "high",
                "format_differences": differences,
                "planned_qb_fields": {
                    "qb_item_id": str(item.get("qb_item_id") or ""),
                    "qb_sku": str(item.get("sku") or ""),
                    "qb_sales_description": str(item.get("description") or ""),
                    "qb_unit_price": item.get("unit_price"),
                    "qb_inactive": item.get("active") is False,
                },
            }
        )

    unique_production_ids = {row["production_item"]["qb_item_id"] for row in matches}
    summary = {
        "previously_linked_rows": len(linked_rows),
        "matched_rows": len(matches),
        "unmatched_rows": len(exceptions),
        "unique_sandbox_items": len({row["builder"]["baseline_qb_item_id"] for row in matches}),
        "unique_production_items": len(unique_production_ids),
        "shared_link_rows": len(matches) - len(unique_production_ids),
        "active_matches": sum(row["production_item"]["active"] for row in matches),
        "inactive_matches": sum(not row["production_item"]["active"] for row in matches),
        "blank_sku_matches": sum(not row["production_item"]["sku"] for row in matches),
        "type_change_count": sum("type_changed" in row["format_differences"] for row in matches),
        "match_basis": basis_counts,
    }
    return {
        "schema_version": 1,
        "created_utc": _iso_now(),
        "snapshot_name": snapshot_name,
        "production_cache_sha256": cache_sha256,
        "application_status": "locked_not_applied",
        "summary": summary,
        "matches": matches,
        "exceptions": exceptions,
        "activation_requirements": {
            "standard_profile_must_be_production": True,
            "sandbox_background_polling_must_be_stopped": True,
            "production_item_cache_required": True,
            "owner_approval_required": True,
        },
        "compatibility": {
            "identifier": "Production QuickBooks Name is the vendor SKU; QBO Sku may be blank.",
            "runtime_lookup": "Builder keeps part_number for selection/display and uses production qb_item_id for QBO operations.",
            "inactive": "Inactive historical Items remain linked and are marked qb_inactive; they are never deleted.",
            "pricing": "Production unit price and sales description replace the sandbox-owned QB fields at activation.",
            "shared_links": "Historically shared Item links are preserved for duplicate Builder rows.",
        },
    }


def _catalog_entries(document: dict) -> dict[str, list[dict]]:
    entries: dict[str, list[dict]] = {}
    manufacturers = document.get("manufacturers") or {}
    for product_id, product in (document.get("products") or {}).items():
        if not isinstance(product, dict):
            continue
        manufacturer = (manufacturers.get(product.get("manufacturer_id"), {}) or {}).get("label", "")
        for part in product.get("part_numbers") or []:
            if not isinstance(part, dict):
                continue
            part_number = str(part.get("part_number") or "").strip()
            key = _normal(part_number)
            if not key:
                continue
            entries.setdefault(key, []).append(
                {
                    "product_id": product_id,
                    "manufacturer": manufacturer,
                    "model": str(product.get("model") or ""),
                    "part_number": part_number,
                    "baseline_qb_item_id": str(part.get("qb_item_id") or ""),
                    "was_linked": bool(str(part.get("qb_item_id") or "").strip()),
                    "pending_qb": part.get("qb_pending") is True,
                }
            )
    return entries


def _baseline_exclusion_keys(directory: Path, catalog_keys: set[str]) -> set[str]:
    cache_path = directory / "sandbox_quickbooks_items_cache.json"
    cache = _read_json(cache_path, {})
    excluded: set[str] = set()
    for item in cache.get("items") or []:
        if not isinstance(item, dict):
            continue
        for value in (item.get("name"), item.get("sku")):
            key = _normal(value)
            if key and key not in catalog_keys:
                excluded.add(key)
    return excluded


def _items_index(items: list[dict], field: str) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for item in items:
        key = _normal(item.get(field))
        if key:
            index.setdefault(key, []).append(item)
    return index


def _field_report(
    *,
    field: str,
    catalog: dict[str, list[dict]],
    items: list[dict],
    excluded_keys: set[str],
) -> tuple[dict, list[dict], list[dict]]:
    index = _items_index(items, field)
    matched_ids: set[str] = set()
    counts = {
        "catalog_exact": 0,
        "catalog_ambiguous": 0,
        "catalog_missing": 0,
        "pending_missing": 0,
        "production_only": 0,
        "intentionally_excluded": 0,
        "production_key_blank": 0,
    }
    exceptions: list[dict] = []
    matches: list[dict] = []

    for key, builder_rows in catalog.items():
        candidates = index.get(key, [])
        if len(builder_rows) == 1 and len(candidates) == 1:
            item = candidates[0]
            item_id = str(item.get("qb_item_id") or "")
            matched_ids.add(item_id)
            counts["catalog_exact"] += 1
            matches.append(
                {
                    "builder": builder_rows[0],
                    "production_item_id": item_id,
                    "production_name": str(item.get("name") or ""),
                    "production_sku": str(item.get("sku") or ""),
                }
            )
            continue
        if len(builder_rows) > 1 or len(candidates) > 1:
            counts["catalog_ambiguous"] += 1
            exceptions.append(
                {
                    "kind": "ambiguous",
                    "key": key,
                    "builder_count": len(builder_rows),
                    "production_count": len(candidates),
                    "builder_examples": builder_rows[:3],
                    "production_examples": [
                        {"qb_item_id": str(item.get("qb_item_id") or ""), "name": item.get("name", ""), "sku": item.get("sku", "")}
                        for item in candidates[:3]
                    ],
                }
            )
            continue
        entry = builder_rows[0]
        if entry["pending_qb"]:
            counts["pending_missing"] += 1
            kind = "pending_builder_item"
        else:
            counts["catalog_missing"] += 1
            kind = "builder_only"
        exceptions.append({"kind": kind, "key": key, "builder_examples": [entry]})

    for item in items:
        item_id = str(item.get("qb_item_id") or "")
        if item_id in matched_ids:
            continue
        key = _normal(item.get(field))
        if not key:
            counts["production_key_blank"] += 1
            exceptions.append(
                {"kind": "production_key_blank", "qb_item_id": item_id, "name": item.get("name", ""), "sku": item.get("sku", "")}
            )
            continue
        alternate_keys = {_normal(item.get("name")), _normal(item.get("sku"))}
        alternate_keys.discard("")
        if alternate_keys & excluded_keys:
            counts["intentionally_excluded"] += 1
            continue
        counts["production_only"] += 1
        exceptions.append(
            {"kind": "production_only", "key": key, "qb_item_id": item_id, "name": item.get("name", ""), "sku": item.get("sku", "")}
        )

    counts["production_items_with_field"] = sum(1 for item in items if _normal(item.get(field)))
    counts["production_items_total"] = len(items)
    counts["catalog_total"] = sum(len(rows) for rows in catalog.values())
    return counts, exceptions, matches


def build_mapping_report(paths: AppPaths) -> dict:
    snapshot = _snapshot_document(paths)
    if snapshot is None:
        return {"ok": False, "error": "snapshot_required"}
    manifest, document, directory = snapshot
    cache = _read_json(_cache_path(paths), {})
    items = [item for item in (cache.get("items") or []) if isinstance(item, dict)]
    if not items:
        return {"ok": False, "error": "production_catalog_not_pulled"}
    active_items = [item for item in items if item.get("active") is not False]

    catalog = _catalog_entries(document)
    excluded_keys = _baseline_exclusion_keys(directory, set(catalog))
    analyses: dict[str, dict] = {}
    all_matches: dict[str, list[dict]] = {}
    all_exceptions: dict[str, list[dict]] = {}
    for field in sorted(_ALLOWED_MAPPING_FIELDS):
        counts, exceptions, matches = _field_report(
            field=field, catalog=catalog, items=active_items, excluded_keys=excluded_keys
        )
        analyses[field] = counts
        all_matches[field] = matches
        all_exceptions[field] = exceptions

    selected_field = str(_state(paths).get("mapping_field") or "")
    selected = analyses.get(selected_field, {})
    selected_exceptions = all_exceptions.get(selected_field, [])
    blockers = 0
    if selected:
        blockers = sum(
            int(selected.get(key, 0))
            for key in ("catalog_ambiguous", "catalog_missing", "pending_missing", "production_only", "production_key_blank")
        )
    historical_plan = _historical_link_plan(
        snapshot_name=str(_state(paths).get("snapshot_name") or ""),
        directory=directory,
        document=document,
        items=items,
        cache_sha256=_sha256(_cache_path(paths)),
    )
    _write_json(_historical_plan_path(paths), historical_plan)
    report = {
        "schema_version": 1,
        "created_utc": _iso_now(),
        "snapshot": {
            "name": _state(paths).get("snapshot_name"),
            "created_utc": manifest.get("created_utc"),
            "catalog": manifest.get("catalog") or {},
        },
        "production_item_count": len(active_items),
        "production_inactive_item_count": len(items) - len(active_items),
        "baseline_exclusion_key_count": len(excluded_keys),
        "field_analysis": analyses,
        "selected_mapping_field": selected_field,
        "selected_summary": selected,
        "selected_blocker_count": blockers,
        "selected_exceptions": selected_exceptions[:300],
        "selected_exception_count": len(selected_exceptions),
        "historical_link_summary": historical_plan["summary"],
        "preview_only": True,
        "production_sync_enabled": False,
    }
    _write_json(_report_path(paths), report)
    return {"ok": True, "report": report, "summary": report["selected_summary"] or report["field_analysis"]}


def get_mapping_report(paths: AppPaths) -> dict:
    report = _read_json(_report_path(paths), {})
    if not report:
        return build_mapping_report(paths)
    return {"ok": True, "report": report, "summary": report.get("selected_summary") or report.get("field_analysis")}


def set_mapping_field(paths: AppPaths, field: str) -> dict:
    field = str(field or "").strip().lower()
    if field not in _ALLOWED_MAPPING_FIELDS:
        return {"ok": False, "error": "invalid_mapping_field"}
    if _selected_snapshot(paths) is None:
        return {"ok": False, "error": "snapshot_required"}
    state = _state(paths)
    state["mapping_field"] = field
    _write_json(_state_path(paths), state)
    return build_mapping_report(paths)


def prepare_auto_mapping_plan(paths: AppPaths) -> dict:
    """Persist the exact-match plan, but intentionally do not apply it."""
    report_result = build_mapping_report(paths)
    if not report_result.get("ok"):
        return report_result
    report = report_result["report"]
    field = report.get("selected_mapping_field")
    if field not in _ALLOWED_MAPPING_FIELDS:
        return {"ok": False, "error": "mapping_field_required", "report": report}
    snapshot = _snapshot_document(paths)
    assert snapshot is not None
    _, document, _ = snapshot
    cache = _read_json(_cache_path(paths), {})
    catalog = _catalog_entries(document)
    excluded = _baseline_exclusion_keys(snapshot[2], set(catalog))
    _, _, matches = _field_report(
        field=field,
        catalog=catalog,
        items=[item for item in (cache.get("items") or []) if isinstance(item, dict)],
        excluded_keys=excluded,
    )
    plan = {
        "schema_version": 1,
        "created_utc": _iso_now(),
        "snapshot_name": report["snapshot"]["name"],
        "mapping_field": field,
        "exact_matches": matches,
        "exact_match_count": len(matches),
        "unresolved_exception_count": int(report.get("selected_exception_count") or 0),
        "application_status": "prepared_not_applied",
        "safety": (
            "This plan contains only unambiguous exact matches and never modifies parts_db.json. "
            "Every exception remains untouched. A separate owner-approved apply step is required."
        ),
    }
    _write_json(_plan_path(paths), plan)
    return {
        "ok": True,
        "preview_only": True,
        "production_sync_enabled": False,
        "exact_match_count": len(matches),
        "unresolved_exception_count": plan["unresolved_exception_count"],
        "application_status": plan["application_status"],
    }


def _apply_historical_plan_to_document(document: dict, plan: dict, *, applied_utc: str) -> tuple[dict, dict]:
    """Return a catalog with only the reviewed production QB fields replaced."""
    if plan.get("application_status") != "locked_not_applied":
        raise ValueError("historical_plan_not_locked")
    summary = plan.get("summary") or {}
    if int(summary.get("unmatched_rows") or 0) != 0:
        raise ValueError("historical_plan_has_exceptions")
    if int(summary.get("matched_rows") or 0) != int(summary.get("previously_linked_rows") or 0):
        raise ValueError("historical_plan_incomplete")

    updated = copy.deepcopy(document)
    products = updated.get("products") or {}
    changed_rows = 0
    inactive_rows = 0
    for match in plan.get("matches") or []:
        if match.get("confidence") != "high":
            raise ValueError("historical_plan_not_high_confidence")
        builder = match.get("builder") or {}
        product_id = str(builder.get("product_id") or "")
        part_number = str(builder.get("part_number") or "").strip()
        baseline_qb_item_id = str(builder.get("baseline_qb_item_id") or "").strip()
        product = products.get(product_id)
        if not isinstance(product, dict):
            raise ValueError(f"activation_product_missing:{product_id}")
        candidates = [
            row for row in (product.get("part_numbers") or [])
            if isinstance(row, dict)
            and str(row.get("part_number") or "").strip() == part_number
            and str(row.get("qb_item_id") or "").strip() == baseline_qb_item_id
        ]
        if len(candidates) != 1:
            raise ValueError(f"activation_baseline_row_changed:{product_id}:{part_number}")

        planned = match.get("planned_qb_fields") or {}
        production_item_id = str(planned.get("qb_item_id") or "").strip()
        if not production_item_id:
            raise ValueError(f"activation_production_item_missing:{product_id}:{part_number}")
        row = candidates[0]
        row["qb_item_id"] = production_item_id
        row["qb_sku"] = str(planned.get("qb_sku") or "")
        row["qb_sales_description"] = str(planned.get("qb_sales_description") or "")
        row["qb_unit_price"] = planned.get("qb_unit_price")
        row["qb_inactive"] = bool(planned.get("qb_inactive"))
        row["qb_last_synced"] = applied_utc
        changed_rows += 1
        inactive_rows += int(row["qb_inactive"])

    if changed_rows != int(summary.get("matched_rows") or 0):
        raise ValueError("activation_row_count_mismatch")
    return updated, {"updated_rows": changed_rows, "inactive_rows": inactive_rows}


def activate_historical_mapping(paths: AppPaths, *, owner_approved: bool = False) -> dict:
    """Promote the reviewed production profile and apply its locked lineage plan.

    This is intentionally not exposed as an HTTP route. The desktop app must
    be stopped first so the sandbox poller cannot race the profile/cache swap.
    The caller must also explicitly pass ``owner_approved=True``.
    """
    if not owner_approved:
        return {"ok": False, "error": "owner_approval_required"}

    selected = _selected_snapshot(paths)
    if selected is None:
        return {"ok": False, "error": "snapshot_required"}
    manifest, directory = selected
    parts_spec = (manifest.get("files") or {}).get("parts_db") or {}
    baseline_path = directory / str(parts_spec.get("file") or "parts_db.json")
    parts_path = paths.workspace_config_dir / "parts_db.json"
    plan_path = _historical_plan_path(paths)
    cache_path = _cache_path(paths)
    try:
        if _sha256(baseline_path) != str(parts_spec.get("sha256") or ""):
            raise ValueError("baseline_hash_mismatch")
        if _sha256(parts_path) != _sha256(baseline_path):
            raise ValueError("current_catalog_changed_since_baseline")
        plan = _read_json(plan_path, {})
        if plan.get("snapshot_name") != _state(paths).get("snapshot_name"):
            raise ValueError("historical_plan_snapshot_mismatch")
        if plan.get("production_cache_sha256") != _sha256(cache_path):
            raise ValueError("production_cache_changed_since_plan")
        preview_status = quickbooks_service.get_status(paths, profile=_PROFILE)
        if preview_status.get("environment") != "production" or not preview_status.get("connected"):
            raise ValueError("production_preview_connection_required")

        document = json.loads(parts_path.read_text(encoding="utf-8"))
        applied_utc = _iso_now()
        updated_document, stats = _apply_historical_plan_to_document(
            document, plan, applied_utc=applied_utc
        )
        preview_config = quickbooks_service._load_config(paths, _PROFILE)
        preview_blob = quickbooks_service._profile_store(_PROFILE).load()
        if not all(preview_blob.get(key) for key in ("client_secret", "refresh_token", "realm_id")):
            raise ValueError("production_preview_credentials_incomplete")
        preview_cache = _read_json(cache_path, {})
        active_items = [
            dict(item) for item in (preview_cache.get("items") or [])
            if isinstance(item, dict) and item.get("active") is not False
        ]
        if len(active_items) != int(preview_cache.get("active_item_count") or 0):
            raise ValueError("production_active_cache_count_mismatch")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    default_config_path = quickbooks_service._config_path(paths)
    default_cache_path = paths.workspace_dir / "quickbooks_items_cache.json"
    original_config_bytes = default_config_path.read_bytes() if default_config_path.exists() else None
    original_cache_bytes = default_cache_path.read_bytes() if default_cache_path.exists() else None
    original_parts_bytes = parts_path.read_bytes()
    default_store = quickbooks_service._profile_store("default")
    preview_store = quickbooks_service._profile_store(_PROFILE)
    original_default_blob = default_store.load()
    original_preview_blob = dict(preview_blob)
    original_preview_config = dict(preview_config)

    try:
        production_config = dict(preview_config)
        production_config["environment"] = "production"
        production_config["connection_status"] = "connected"
        production_config["last_sync_utc"] = applied_utc
        default_store.save(dict(preview_blob))
        quickbooks_service._save_config(paths, production_config)

        linked_ids = {
            str(match["planned_qb_fields"]["qb_item_id"]): str(match["builder"]["product_id"])
            for match in plan.get("matches") or []
        }
        seeded_items = [
            {
                **item,
                "linked": str(item.get("qb_item_id") or "") in linked_ids,
                "linked_product_id": linked_ids.get(str(item.get("qb_item_id") or ""), ""),
            }
            for item in active_items
        ]
        from . import qb_sync_service
        qb_sync_service._write_cache(paths, {
            "last_sync_utc": applied_utc,
            "item_count": len(seeded_items),
            "items": seeded_items,
        })

        from .config_service import save_config_file
        save_result = save_config_file("parts_db.json", updated_document, paths)
        if not save_result.get("ok"):
            raise RuntimeError(str(save_result.get("error") or "parts_db_save_failed"))

        retired_blob = dict(preview_blob)
        for key in ("access_token", "refresh_token", "realm_id"):
            retired_blob.pop(key, None)
        preview_store.save(retired_blob)
        retired_config = dict(preview_config)
        retired_config["connection_status"] = "disconnected"
        retired_config["token_expiry_utc"] = ""
        retired_config["refresh_expiry_utc"] = ""
        retired_config["hard_expiry_utc"] = ""
        quickbooks_service._save_config(paths, retired_config, _PROFILE)

        applied_plan = dict(plan)
        applied_plan["application_status"] = "applied"
        applied_plan["applied_utc"] = applied_utc
        applied_plan["activation"] = {
            **stats,
            "standard_profile": "production",
            "standard_active_cache_items": len(seeded_items),
            "preview_profile_retired_without_revocation": True,
        }
        _write_json(plan_path, applied_plan)
    except Exception as exc:  # noqa: BLE001 — rollback every local activation surface
        default_store.save(original_default_blob)
        preview_store.save(original_preview_blob)
        quickbooks_service._save_config(paths, original_preview_config, _PROFILE)
        if original_config_bytes is None:
            default_config_path.unlink(missing_ok=True)
        else:
            default_config_path.write_bytes(original_config_bytes)
        if original_cache_bytes is None:
            default_cache_path.unlink(missing_ok=True)
        else:
            default_cache_path.write_bytes(original_cache_bytes)
        parts_path.write_bytes(original_parts_bytes)
        return {"ok": False, "error": f"activation_rolled_back:{type(exc).__name__}"}

    return {
        "ok": True,
        "application_status": "applied",
        **stats,
        "standard_active_cache_items": len(seeded_items),
        "preview_profile_retired": True,
    }
