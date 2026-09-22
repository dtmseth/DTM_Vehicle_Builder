"""Additively mirror Shop completed-build media into Company Files.

Shop Documents remains the capture/source location.  Each cloud sweep copies
new or changed files to the matching vehicle's Company ``Completed Build
Photos`` folder.  Destination-only files are deliberately retained: a source
cleanup must never silently delete the Company's copy.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import PurePosixPath
from typing import Protocol

from ...inputs.project_entry import list_projects
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway


logger = logging.getLogger(__name__)
_mirror_lock = threading.RLock()
_schedule_lock = threading.Lock()
_scheduled_worker: threading.Thread | None = None
_last_automatic_sweep = 0.0
_AUTOMATIC_SWEEP_INTERVAL_SECONDS = 15 * 60
_MAX_FILES_PER_VEHICLE = 3000
_MAX_FOLDER_DEPTH = 8
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}


class CompletedPhotoGateway(Protocol):
    def ensure_folder(self, remote_path: str) -> dict: ...
    def list_children(self, remote_path: str, *, timeout_seconds: float = 30) -> list[dict]: ...
    def download_item(self, item_id: str, *, timeout_seconds: float = 120) -> bytes: ...
    def upload_file(self, remote_path: str, data: bytes, *, timeout_seconds: float = 120) -> dict: ...


def _configured() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return False
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return False
    try:
        from ..adapters.cloud.config import load_cloud_config_from_env

        config = load_cloud_config_from_env()
        return bool(
            config.company_provisioning_target_configured
            and config.shop_provisioning_target_configured
        )
    except Exception:
        return False


def _gateways():
    from ..adapters.cloud.config import load_cloud_config_from_env

    config = load_cloud_config_from_env()
    company = GraphDriveGateway.from_active_cloud(
        config,
        library_names=(
            config.company_library_name,
            config.company_library_internal_name,
            config.exports_library_name,
            config.exports_library_internal_name,
        ),
    )
    shop = GraphDriveGateway.from_active_cloud(
        config,
        library_names=(config.shop_library_name, config.shop_library_internal_name),
    )
    return company, shop


def _graph_hash(item: dict) -> str:
    file_facet = item.get("file")
    hashes = file_facet.get("hashes") if isinstance(file_facet, dict) else None
    if not isinstance(hashes, dict):
        return ""
    for key in ("sha256Hash", "sha1Hash", "quickXorHash"):
        value = str(hashes.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    return ""


def _same_graph_content(source: dict, target: dict) -> bool:
    if int(source.get("size") or 0) != int(target.get("size") or 0):
        return False
    source_hash = _graph_hash(source)
    target_hash = _graph_hash(target)
    return bool(source_hash and target_hash and source_hash == target_hash)


def _safe_child_name(item: dict) -> str:
    name = str(item.get("name") or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return ""
    return name


def _mirror_vehicle_folder(
    *,
    company: CompletedPhotoGateway,
    shop: CompletedPhotoGateway,
    source_root: str,
    target_root: str,
) -> dict[str, int]:
    counts = {"copied": 0, "updated": 0, "unchanged": 0, "files": 0}
    stack: list[tuple[str, str, int]] = [(source_root, target_root, 0)]
    while stack and counts["files"] < _MAX_FILES_PER_VEHICLE:
        source_folder, target_folder, depth = stack.pop()
        source_children = shop.list_children(source_folder)
        try:
            company_children = company.list_children(target_folder)
        except FileNotFoundError:
            company.ensure_folder(target_folder)
            company_children = []
        target_children = {
            name.casefold(): item
            for item in company_children
            for name in [_safe_child_name(item)]
            if name
        }
        for source in source_children:
            name = _safe_child_name(source)
            if not name:
                continue
            source_path = f"{source_folder}/{name}"
            target_path = f"{target_folder}/{name}"
            target = target_children.get(name.casefold())
            if isinstance(source.get("folder"), dict):
                if depth >= _MAX_FOLDER_DEPTH:
                    continue
                if target is None:
                    company.ensure_folder(target_path)
                stack.append((source_path, target_path, depth + 1))
                continue
            source_id = str(source.get("id") or "").strip()
            if not source_id or PurePosixPath(name).suffix.casefold() not in _PHOTO_SUFFIXES:
                continue
            counts["files"] += 1
            if target is not None and not isinstance(target.get("folder"), dict):
                if _same_graph_content(source, target):
                    counts["unchanged"] += 1
                    continue
                source_bytes = shop.download_item(source_id)
                target_id = str(target.get("id") or "").strip()
                if target_id:
                    target_bytes = company.download_item(target_id)
                    if hashlib.sha256(source_bytes).digest() == hashlib.sha256(target_bytes).digest():
                        counts["unchanged"] += 1
                        continue
                company.upload_file(target_path, source_bytes)
                counts["updated"] += 1
                continue
            source_bytes = shop.download_item(source_id)
            company.upload_file(target_path, source_bytes)
            counts["copied"] += 1
    return counts


def mirror_completed_build_photos(
    paths: AppPaths,
    *,
    company_gateway: CompletedPhotoGateway | None = None,
    shop_gateway: CompletedPhotoGateway | None = None,
    force: bool = False,
) -> dict:
    """Mirror all registered vehicle folders, throttled for periodic sync."""
    supplied = company_gateway is not None and shop_gateway is not None
    if not supplied and not _configured():
        return {
            "enabled": False, "vehicles": 0, "copied": 0,
            "updated": 0, "unchanged": 0, "failed": 0,
        }
    global _last_automatic_sweep
    with _mirror_lock:
        now = time.monotonic()
        if (
            not supplied and not force and _last_automatic_sweep
            and now - _last_automatic_sweep < _AUTOMATIC_SWEEP_INTERVAL_SECONDS
        ):
            return {
                "enabled": True, "throttled": True, "vehicles": 0,
                "copied": 0, "updated": 0, "unchanged": 0, "failed": 0,
            }
        if not supplied:
            company_gateway, shop_gateway = _gateways()
        assert company_gateway is not None and shop_gateway is not None
        report = {
            "enabled": True, "throttled": False, "vehicles": 0,
            "copied": 0, "updated": 0, "unchanged": 0, "failed": 0,
        }
        for project in list_projects(paths):
            if project.project_status == "inactive":
                continue
            for unit in project.build_units:
                for individual in unit.individuals:
                    company_base = str(individual.company_vehicle_folder_path or "").strip("/")
                    shop_base = str(individual.shop_vehicle_folder_path or "").strip("/")
                    if not company_base or not shop_base:
                        continue
                    report["vehicles"] += 1
                    try:
                        counts = _mirror_vehicle_folder(
                            company=company_gateway,
                            shop=shop_gateway,
                            source_root=f"{shop_base}/Completed Build Photos",
                            target_root=f"{company_base}/Completed Build Photos",
                        )
                    except FileNotFoundError:
                        # Folder provisioning will create the source on its own
                        # retry path; there is nothing to mirror yet.
                        continue
                    except Exception:
                        report["failed"] += 1
                        logger.exception(
                            "Completed-photo mirror failed for vehicle %s",
                            individual.individual_id,
                        )
                        continue
                    for key in ("copied", "updated", "unchanged"):
                        report[key] += counts[key]
        if not supplied:
            _last_automatic_sweep = time.monotonic()
        return report


def schedule_completed_photo_mirror(paths: AppPaths, *, force: bool = False) -> dict:
    """Start a non-blocking mirror sweep without delaying ordinary cloud sync."""
    if not _configured():
        return {"enabled": False, "scheduled": False, "running": False}
    global _scheduled_worker
    with _schedule_lock:
        if _scheduled_worker is not None and _scheduled_worker.is_alive():
            return {"enabled": True, "scheduled": False, "running": True}
        if (
            not force and _last_automatic_sweep
            and time.monotonic() - _last_automatic_sweep
            < _AUTOMATIC_SWEEP_INTERVAL_SECONDS
        ):
            return {"enabled": True, "scheduled": False, "running": False}
        _scheduled_worker = threading.Thread(
            target=mirror_completed_build_photos,
            kwargs={"paths": paths, "force": force},
            name="completed-photo-mirror",
            daemon=True,
        )
        _scheduled_worker.start()
        return {"enabled": True, "scheduled": True, "running": True}
