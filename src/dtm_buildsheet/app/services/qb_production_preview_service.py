"""Isolated, read-only production QuickBooks catalog preview.

This is deliberately *not* the normal QB sync path.  It uses a separate
production OAuth profile, separate encrypted credentials, a separate item
cache, and a snapshot-pinned Builder catalog.  It can pull and compare item
data, but it never calls ``save_config_file`` and never writes ``parts_db``.

The owner reviews the field mapping and exception counts first.  Only a later,
explicitly approved mapping-apply feature may update catalog links.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
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


def _snapshot_root(paths: AppPaths) -> Path:
    return paths.workspace_dir / _SNAPSHOTS_DIRNAME


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
    return {
        "ok": True,
        "preview_only": True,
        "production_sync_enabled": False,
        "selected_snapshot": selected_summary,
        "snapshots": snapshots,
        "mapping_field": state.get("mapping_field", ""),
        "last_preview_utc": state.get("last_preview_utc"),
        "production_item_count": int(cache.get("item_count") or 0),
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
        items = client.fetch_active_items()
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks production catalog preview failed: %s", exc)
        return {"ok": False, "error": "production_catalog_pull_failed"}

    pulled_at = _iso_now()
    _write_json(
        _cache_path(paths),
        {"schema_version": 1, "last_preview_utc": pulled_at, "item_count": len(items), "items": items},
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
        "report": report.get("summary") if report.get("ok") else None,
        "error": report.get("error") if not report.get("ok") else None,
    }


def _normal(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


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

    catalog = _catalog_entries(document)
    excluded_keys = _baseline_exclusion_keys(directory, set(catalog))
    analyses: dict[str, dict] = {}
    all_matches: dict[str, list[dict]] = {}
    all_exceptions: dict[str, list[dict]] = {}
    for field in sorted(_ALLOWED_MAPPING_FIELDS):
        counts, exceptions, matches = _field_report(
            field=field, catalog=catalog, items=items, excluded_keys=excluded_keys
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
    report = {
        "schema_version": 1,
        "created_utc": _iso_now(),
        "snapshot": {
            "name": _state(paths).get("snapshot_name"),
            "created_utc": manifest.get("created_utc"),
            "catalog": manifest.get("catalog") or {},
        },
        "production_item_count": len(items),
        "baseline_exclusion_key_count": len(excluded_keys),
        "field_analysis": analyses,
        "selected_mapping_field": selected_field,
        "selected_summary": selected,
        "selected_blocker_count": blockers,
        "selected_exceptions": selected_exceptions[:300],
        "selected_exception_count": len(selected_exceptions),
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
