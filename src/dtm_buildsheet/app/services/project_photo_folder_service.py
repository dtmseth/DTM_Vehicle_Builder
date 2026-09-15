"""Reconcile one project's Company Files photo inbox with project metadata.

The year-level inbox remains unassigned. Each physical vehicle's Company
``Build Reference Photos`` folder assigns new files to its unit group. Scans
resolve durable folder IDs, preserve explicit unassignments, and never publish,
move, delete, or download source media.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import PurePosixPath

from ...domain.project_models import BuildReferenceAsset, BuildReferenceAssignment
from ...inputs.project_entry import load_project, save_project, save_project_operational_state
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
_JOBS: dict[tuple[str, str], Future] = {}
_RESULTS: dict[tuple[str, str], tuple[float, str, dict]] = {}


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


def project_photo_sources(project) -> list[dict]:
    """Exact registered parents; names never identify the vehicle/group."""
    sources = []
    if project.company_year_folder_path:
        sources.append({
            "parent_path": project.company_year_folder_path.strip("/"),
            "parent_id": project.company_year_folder_id,
            "subfolder": "Reference Photos & Videos",
            "unit_id": "", "individual_id": "",
        })
    for unit in project.build_units:
        for individual in unit.individuals:
            if individual.company_vehicle_folder_path:
                sources.append({
                    "parent_path": individual.company_vehicle_folder_path.strip("/"),
                    "parent_id": individual.company_vehicle_folder_id,
                    "subfolder": "Build Reference Photos",
                    "unit_id": unit.unit_id,
                    "individual_id": individual.individual_id,
                })
    return sources


def _source_signature(project) -> str:
    # Also invalidates scans when a vehicle is added, moved, or regrouped.
    import json
    return json.dumps(project_photo_sources(project), sort_keys=True)


def _resolved_source_path(source, gateway) -> str:
    parent_path = source["parent_path"]
    if source["parent_id"]:
        from .vehicle_folder_provisioning_service import _drive_item_locator
        item = gateway.get_item(source["parent_id"])
        if not item or not isinstance(item.get("folder"), dict):
            raise ValueError("The registered photo parent is unavailable")
        parent_path, _, _ = _drive_item_locator(item)
    portable = PurePosixPath(parent_path)
    if not parent_path or portable.is_absolute() or ".." in portable.parts:
        raise ValueError("The registered photo parent path is unavailable")
    return f"{parent_path}/{source['subfolder']}"


def scan_project_photo_folder(project, *, gateway=None) -> dict:
    """Scan the year inbox and every registered Company vehicle reference folder."""
    folder_path = project_photo_folder_path(project)
    sources = project_photo_sources(project)
    base = {"ok": True, "folder_path": folder_path,
            "source_signature": _source_signature(project), "photos": [], "warnings": []}
    if not sources:
        return {**base, "available": False}
    if gateway is None:
        cloud_off_test = (
            os.environ.get("PYTEST_CURRENT_TEST")
            and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS")
        )
        if cloud_off_test or not wiring._cloud_flag_enabled():  # noqa: SLF001
            return {**base, "available": False}
        try:
            gateway = _cloud_gateway()
        except Exception:
            logger.info("Project photo folders are unavailable", exc_info=True)
            return {**base, "available": False,
                    "warnings": ["Project photos could not be checked."]}

    photos, scanned_folders, warnings = [], [], []
    visited = 0
    for source in sources:
        try:
            root = _resolved_source_path(source, gateway)
            if root.casefold() in {p.casefold() for p in scanned_folders}:
                raise ValueError("Multiple vehicles share a reference folder")
            scanned_folders.append(root)
            stack = [(root, 0)]
            while stack:
                current, depth = stack.pop()
                try:
                    children = gateway.list_children(current, timeout_seconds=8)
                except FileNotFoundError:
                    if current == root:
                        warnings.append("A reference folder is missing; folder provisioning must finish before discovery.")
                    continue
                for item in children:
                    visited += 1
                    if visited > _MAX_ITEMS:
                        raise ValueError("Photo scan limit reached")
                    name = str(item.get("name") or "").strip()
                    if not name or "/" in name or "\\" in name or name in {".", ".."}:
                        continue
                    item_path = f"{current}/{name}"
                    if isinstance(item.get("folder"), dict):
                        if depth >= _MAX_DEPTH:
                            raise ValueError("Photo folder depth limit reached")
                        stack.append((item_path, depth + 1))
                        continue
                    if PurePosixPath(name).suffix.casefold() not in _PHOTO_SUFFIXES:
                        continue
                    photos.append({
                        "file_name": name, "media_type": "photo",
                        "source_kind": "company_reference",
                        "source_drive_id": gateway.drive_id,
                        "source_item_id": str(item.get("id") or ""),
                        "source_path": item_path,
                        "source_web_url": str(item.get("webUrl") or ""),
                        "source_etag": str(item.get("eTag") or item.get("@odata.etag") or ""),
                        "source_size": max(0, int(item.get("size") or 0)),
                        "unit_id": source["unit_id"],
                        "individual_id": source["individual_id"],
                    })
        except Exception:
            logger.info("Could not completely scan a project photo folder", exc_info=True)
            warnings.append("Project photo discovery is incomplete. Check folder access and retry; existing assignments were kept.")
            break
    photos.sort(key=lambda item: (item["source_path"].casefold(), item["file_name"].casefold()))
    return {**base, "available": not warnings, "photos": photos,
            "scanned_folders": scanned_folders, "warnings": list(dict.fromkeys(warnings))}


def reconcile_project_photo_folder(project_id: str, result: dict, paths: AppPaths) -> dict:
    """Assign newly discovered vehicle photos once; keep manual changes intact."""
    # An already-running publication must finish before we record changed
    # references; queued/retry publications then see the review gate.
    from .shop_publication_service import _publication_lock
    with _publication_lock:
        return _reconcile_project_photo_folder(project_id, result, paths)


def _reconcile_project_photo_folder(project_id: str, result: dict, paths: AppPaths) -> dict:
    if not result.get("ok") or not result.get("available") or result.get("warnings"):
        return {**result, "changed": 0, "added": 0, "removed": 0}
    project = load_project(project_id, paths)
    folder_path = project_photo_folder_path(project)
    if result.get("source_signature") != _source_signature(project):
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
    content_changed = False
    review_units: set[str] = set()
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
        asset = by_identity.get(identity)
        path_match = by_path.get(path_key)
        # A different file uploaded under an old filename is a different asset.
        if asset is None and path_match is not None and not (
            path_match.source_drive_id and path_match.source_item_id
            and item.get("source_drive_id") and item.get("source_item_id")
        ):
            asset = path_match
        was_new = asset is None
        if asset is None:
            asset = BuildReferenceAsset(reference_id=str(uuid.uuid4()))
            project.reference_assets.append(asset)
            by_identity[identity] = asset
            by_path[path_key] = asset
            added += 1
        unit_id = str(item.get("unit_id") or "")
        previous_path = str(asset.source_path or "").replace("\\", "/").strip("/").casefold()
        inbox_prefix = f"{folder_path.strip('/').casefold()}/" if folder_path else ""
        moved_from_inbox = bool(
            inbox_prefix and previous_path.startswith(inbox_prefix)
            and not path_key.startswith(inbox_prefix)
            and asset.source_kind == "company_reference" and not asset.assignments
        )
        # SharePoint moves retain the same item ID. An unassigned inbox photo
        # dropped into a vehicle folder needs its first group assignment too.
        # Once scanned there, later refreshes preserve explicit unassignment.
        if unit_id and (was_new or moved_from_inbox):
            asset.assignments.append(BuildReferenceAssignment(
                scope="unit_group", target_id=unit_id,
                sort_order=1 + max((assignment.sort_order
                                   for candidate in project.reference_assets
                                   for assignment in candidate.assignments
                                   if assignment.scope == "unit_group" and assignment.target_id == unit_id), default=-1),
            ))
            content_changed = True
            review_units.add(unit_id)
        old_content = (asset.source_etag, asset.source_size)
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
        if not was_new and asset.assignments and old_content != (asset.source_etag, asset.source_size):
            content_changed = True
            for unit in project.build_units:
                if any(a.scope == "project" or (a.scope == "unit_group" and a.target_id == unit.unit_id)
                       or (a.scope == "individual" and a.target_id in {v.individual_id for v in unit.individuals})
                       for a in asset.assignments):
                    review_units.add(unit.unit_id)

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
    review_required = False
    for unit in project.build_units:
        if unit.unit_id not in review_units:
            continue
        for vehicle in unit.individuals:
            if vehicle.status == "finalized":
                vehicle.shop_publication_status = "reference_review_required"
                vehicle.shop_publication_error = "Review changed references and export/update the PDF before approving Shop publication."
                review_required = True
    if total_changed:
        if content_changed:
            save_project(project, paths)
        else:
            save_project_operational_state(project, paths)
    if review_required:
        result = {**result, "warnings": [*result.get("warnings", []),
                  "Reference photos changed on a finalized build. Review them and export/update the PDF before approving an updated Shop package."]}
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
    folder_path = _source_signature(project)
    cache_key = (str(paths.workspace_projects_dir.resolve()), project_id)
    if not project_photo_sources(project):
        return {
            "ok": True, "loading": False, "available": False,
            "changed": 0, "warnings": [],
        }

    with _LOCK:
        cached = _RESULTS.get(cache_key)
        if cached and cached[1] != folder_path:
            _RESULTS.pop(cache_key, None)
            cached = None
        if (
            cached and not refresh
            and time.monotonic() - cached[0] < _RESULT_TTL_SECONDS
        ):
            return {
                **cached[2], "loading": False,
                "changed": 0, "added": 0, "removed": 0,
            }
        future = _JOBS.get(cache_key)

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
            if _JOBS.get(cache_key) is future:
                _JOBS.pop(cache_key, None)
            _RESULTS[cache_key] = (time.monotonic(), folder_path, response)
        return response

    if future is None:
        with _LOCK:
            future = _JOBS.get(cache_key)
            if future is None:
                _JOBS[cache_key] = _EXECUTOR.submit(_scan_job, project_id, paths)
    return {
        "ok": True, "loading": True, "available": True,
        "changed": 0, "warnings": [],
    }
