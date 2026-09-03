"""Reconcile one project's Company Files photo inbox with project metadata.

The year-level ``Reference Photos & Videos`` folder is the canonical inbox for
unassigned project photos. Users may add files through OneDrive or SharePoint;
this service discovers only that exact project's folder and never moves,
deletes, or downloads source media.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import PurePosixPath

from ...domain.project_models import BuildReferenceAsset
from ...inputs.project_entry import load_project, save_project_operational_state
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway
from .reference_photo_service import _asset_source_identity, _source_identity


logger = logging.getLogger(__name__)
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
_MAX_ITEMS = 3000
_MAX_DEPTH = 8
_RESULT_TTL_SECONDS = 30
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dtm-project-photos")
_LOCK = threading.RLock()
_JOBS: dict[str, Future] = {}
_RESULTS: dict[str, tuple[float, str, dict]] = {}


def project_photo_folder_path(project) -> str:
    year_path = str(project.company_year_folder_path or "").replace("\\", "/").strip("/")
    return f"{year_path}/Reference Photos & Videos" if year_path else ""


def _cloud_gateway() -> GraphDriveGateway:
    from ..adapters.cloud.config import load_cloud_config_from_env

    config = load_cloud_config_from_env()
    return GraphDriveGateway.from_active_cloud(config, library_names=(
        config.company_library_name,
        config.company_library_internal_name,
        config.exports_library_name,
        config.exports_library_internal_name,
    ), timeout_seconds=8)


def scan_project_photo_folder(project, *, gateway=None) -> dict:
    """Return supported photos under one exact year-level inbox."""
    folder_path = project_photo_folder_path(project)
    if not folder_path:
        return {"ok": True, "available": False, "folder_path": "", "photos": [], "warnings": []}
    if gateway is None:
        cloud_off_test = (
            os.environ.get("PYTEST_CURRENT_TEST")
            and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS")
        )
        if cloud_off_test or not wiring._cloud_flag_enabled():  # noqa: SLF001
            return {
                "ok": True, "available": False, "folder_path": folder_path,
                "photos": [], "warnings": [],
            }
        try:
            gateway = _cloud_gateway()
        except Exception:
            logger.info("Project photo folder is unavailable", exc_info=True)
            return {
                "ok": True, "available": False, "folder_path": folder_path,
                "photos": [], "warnings": ["Project photos could not be checked."],
            }

    photos: list[dict] = []
    stack: list[tuple[str, int]] = [(folder_path, 0)]
    try:
        while stack and len(photos) < _MAX_ITEMS:
            current, depth = stack.pop()
            try:
                children = gateway.list_children(current, timeout_seconds=8)
            except FileNotFoundError:
                if current == folder_path:
                    return {
                        "ok": True, "available": True, "folder_path": folder_path,
                        "photos": [], "warnings": [],
                    }
                continue
            for item in children:
                name = str(item.get("name") or "").strip()
                if not name or "/" in name or "\\" in name:
                    continue
                item_path = f"{current}/{name}"
                if isinstance(item.get("folder"), dict):
                    if depth < _MAX_DEPTH:
                        stack.append((item_path, depth + 1))
                    continue
                if PurePosixPath(name).suffix.casefold() not in _PHOTO_SUFFIXES:
                    continue
                photos.append({
                    "file_name": name,
                    "media_type": "photo",
                    "source_kind": "company_reference",
                    "source_drive_id": gateway.drive_id,
                    "source_item_id": str(item.get("id") or ""),
                    "source_path": item_path,
                    "source_web_url": str(item.get("webUrl") or ""),
                    "source_etag": str(item.get("eTag") or item.get("@odata.etag") or ""),
                    "source_size": max(0, int(item.get("size") or 0)),
                })
    except Exception:
        logger.exception("Could not scan project photo folder")
        return {
            "ok": True, "available": False, "folder_path": folder_path,
            "photos": [], "warnings": ["Project photos could not be checked."],
        }
    warnings = (
        ["The project photo folder contains too many items to show all at once."]
        if stack else []
    )
    photos.sort(key=lambda item: (item["source_path"].casefold(), item["file_name"].casefold()))
    return {
        "ok": True, "available": True, "folder_path": folder_path,
        "photos": photos, "warnings": warnings,
    }


def reconcile_project_photo_folder(project_id: str, result: dict, paths: AppPaths) -> dict:
    """Add new inbox files as unassigned photos and refresh durable metadata."""
    if not result.get("ok") or not result.get("available") or result.get("warnings"):
        return {**result, "changed": 0, "added": 0, "removed": 0}
    project = load_project(project_id, paths)
    folder_path = project_photo_folder_path(project)
    if not folder_path or folder_path != str(result.get("folder_path") or ""):
        return {**result, "changed": 0, "added": 0, "removed": 0}

    exclusions = set(project.reference_source_exclusions)
    by_identity = {
        identity: asset
        for asset in project.reference_assets
        if (identity := _asset_source_identity(asset))
    }
    by_path = {
        str(asset.source_path or "").replace("\\", "/").strip("/").casefold(): asset
        for asset in project.reference_assets
        if str(asset.source_path or "").strip()
    }
    discovered_identities: set[str] = set()
    discovered_paths: set[str] = set()
    metadata_updates = added = 0
    for item in result.get("photos") or []:
        identity = _source_identity(
            drive_id=item.get("source_drive_id", ""),
            item_id=item.get("source_item_id", ""),
            source_path=item.get("source_path", ""),
        )
        path_key = str(item.get("source_path") or "").replace("\\", "/").strip("/").casefold()
        discovered_identities.add(identity)
        discovered_paths.add(path_key)
        if identity in exclusions or f"path:{path_key}" in exclusions:
            continue
        asset = by_identity.get(identity) or by_path.get(path_key)
        was_new = asset is None
        if asset is None:
            asset = BuildReferenceAsset(reference_id=str(uuid.uuid4()))
            project.reference_assets.append(asset)
            by_identity[identity] = asset
            by_path[path_key] = asset
            added += 1
        before = (
            asset.file_name, asset.media_type, asset.source_kind,
            asset.source_drive_id, asset.source_item_id, asset.source_path,
            asset.source_web_url, asset.source_etag, asset.source_size,
        )
        asset.file_name = str(item.get("file_name") or "")
        asset.media_type = "photo"
        asset.source_kind = "company_reference"
        asset.source_drive_id = str(item.get("source_drive_id") or "")
        asset.source_item_id = str(item.get("source_item_id") or "")
        asset.source_path = str(item.get("source_path") or "")
        asset.source_web_url = str(item.get("source_web_url") or "")
        asset.source_etag = str(item.get("source_etag") or "")
        asset.source_size = max(0, int(item.get("source_size") or 0))
        after = (
            asset.file_name, asset.media_type, asset.source_kind,
            asset.source_drive_id, asset.source_item_id, asset.source_path,
            asset.source_web_url, asset.source_etag, asset.source_size,
        )
        if before != after and not was_new:
            metadata_updates += 1

    prefix = f"{folder_path.strip('/').casefold()}/"
    remaining = []
    removed = 0
    for asset in project.reference_assets:
        path_key = str(asset.source_path or "").replace("\\", "/").strip("/").casefold()
        identity = _asset_source_identity(asset)
        is_inbox = asset.source_kind == "company_reference" and path_key.startswith(prefix)
        missing = identity not in discovered_identities and path_key not in discovered_paths
        if is_inbox and missing and not asset.assignments:
            removed += 1
            continue
        remaining.append(asset)
    project.reference_assets = remaining
    total_changed = added + metadata_updates + removed
    if total_changed:
        save_project_operational_state(project, paths)
    return {
        **result, "changed": total_changed, "added": added, "removed": removed,
    }


def _scan_job(project_id: str, paths: AppPaths) -> dict:
    try:
        project = load_project(project_id, paths)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return scan_project_photo_folder(project)


def handle_sync_project_photo_folder(
    project_id: str,
    paths: AppPaths,
    *,
    refresh: bool = False,
) -> dict:
    """Pollable non-blocking reconciliation for the current project only."""
    try:
        project = load_project(project_id, paths)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    folder_path = project_photo_folder_path(project)
    if not folder_path:
        return {
            "ok": True, "loading": False, "available": False,
            "changed": 0, "warnings": [],
        }

    with _LOCK:
        cached = _RESULTS.get(project_id)
        if cached and cached[1] != folder_path:
            _RESULTS.pop(project_id, None)
            cached = None
        if (
            cached and not refresh
            and time.monotonic() - cached[0] < _RESULT_TTL_SECONDS
        ):
            return {
                **cached[2], "loading": False,
                "changed": 0, "added": 0, "removed": 0,
            }
        future = _JOBS.get(project_id)

    if future is not None and future.done():
        try:
            result = future.result()
            if result.get("ok"):
                result = reconcile_project_photo_folder(project_id, result, paths)
        except Exception:
            logger.exception("Project photo reconciliation failed")
            result = {
                "ok": True, "available": False,
                "warnings": ["Project photos could not be checked."], "changed": 0,
            }
        response = {**result, "loading": False}
        with _LOCK:
            if _JOBS.get(project_id) is future:
                _JOBS.pop(project_id, None)
            _RESULTS[project_id] = (time.monotonic(), folder_path, response)
        return response

    if future is None:
        with _LOCK:
            future = _JOBS.get(project_id)
            if future is None:
                _JOBS[project_id] = _EXECUTOR.submit(_scan_job, project_id, paths)
    return {
        "ok": True, "loading": True, "available": True,
        "changed": 0, "warnings": [],
    }
