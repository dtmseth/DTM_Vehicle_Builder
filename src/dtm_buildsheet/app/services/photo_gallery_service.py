"""Fast, local-first photo galleries for project references and completed builds.

Project records remain the authority for which exact folders/assets may be
viewed.  The browser receives opaque, process-local tokens instead of local
paths, Graph credentials, or arbitrary drive-item access.  Completed-folder
enumeration and thumbnail generation run on a bounded background executor so
the local HTTP server remains responsive while OneDrive/SharePoint hydrates.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import mimetypes
import os
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps

from ...domain.project_models import BuildReferenceAsset
from ...domain.reference_photos import resolve_build_reference_photos
from ...domain.vehicle_naming import vehicle_display_name
from ...inputs.project_entry import list_projects, load_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway
from .build_state_service import find_synced_library_folder
from .reference_media_service import cached_reference_media, resolve_reference_media


logger = logging.getLogger(__name__)
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
_MAX_GALLERY_ITEMS = 3000
_MAX_GALLERY_DEPTH = 8
_RESULT_TTL_SECONDS = 300
_SHARED_THUMBNAIL_ROOT = "Settings/_DTM Photo Thumbnail Cache/v2"
_THUMBNAIL_FOREGROUND_WAIT_SECONDS = 2.5
_FULL_RESOLUTION_TIMEOUT_SECONDS = 18
_MAX_FULL_RESOLUTION_BYTES = 75 * 1024 * 1024
_SCAN_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dtm-photo-scan")
_THUMBNAIL_FOREGROUND_EXECUTOR = ThreadPoolExecutor(
    max_workers=6, thread_name_prefix="dtm-photo-visible",
)
_THUMBNAIL_EXACT_EXECUTOR = ThreadPoolExecutor(
    max_workers=3, thread_name_prefix="dtm-photo-exact",
)
_PREVIEW_BACKGROUND_EXECUTOR = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="dtm-photo-preview",
)
_THUMBNAIL_PREP_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="dtm-photo-prepare",
)
_FULL_RESOLUTION_EXECUTOR = ThreadPoolExecutor(
    max_workers=3, thread_name_prefix="dtm-photo-full",
)
_LOCK = threading.RLock()
_PRIORITY_CONDITION = threading.Condition(_LOCK)
_SHUTDOWN_EVENT = threading.Event()


@dataclass(frozen=True)
class _PhotoSource:
    token: str
    project_id: str
    file_name: str
    source_kind: str
    source_drive_id: str = ""
    source_item_id: str = ""
    source_path: str = ""
    source_web_url: str = ""
    source_etag: str = ""
    source_size: int = 0
    local_path: str = ""
    label: str = ""
    note: str = ""
    origin: str = ""
    assignment_state: str = ""


@dataclass(frozen=True)
class _CompletedFolder:
    remote_path: str
    label: str
    unit_id: str
    individual_id: str = ""


_SOURCES: dict[str, _PhotoSource] = {}
_THUMBNAIL_JOBS: dict[str, Future] = {}
_THUMBNAIL_JOB_PRIORITY: dict[str, str] = {}
_PREVIEW_JOBS: dict[str, Future] = {}
_PREVIEW_JOB_PRIORITY: dict[str, str] = {}
_SCAN_JOBS: dict[str, Future] = {}
_SCAN_RESULTS: dict[str, tuple[float, list[dict], list[str]]] = {}
_SHARED_THUMBNAIL_FOLDERS: set[str] = set()
_CACHE_PREP_JOBS: dict[str, Future] = {}
_CACHE_PREP_STATES: dict[str, dict] = {}
_FULL_RESOLUTION_JOBS: dict[str, Future] = {}
_FULL_RESOLUTION_CURRENT_TOKEN = ""


def _token_for(_project_id: str, item: dict) -> str:
    drive_id = str(item.get("source_drive_id") or "")
    item_id = str(item.get("source_item_id") or "")
    if drive_id and item_id:
        identity = "|".join((
            "graph", drive_id, item_id, str(item.get("source_etag") or ""),
        ))
    else:
        identity = "|".join((
            "local",
            str(item.get("local_path") or item.get("source_path") or ""),
            str(item.get("source_etag") or ""),
            str(item.get("file_name") or ""),
        ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _register(project_id: str, item: dict) -> dict:
    token = _token_for(project_id, item)
    source = _PhotoSource(
        token=token,
        project_id=project_id,
        file_name=Path(str(item.get("file_name") or "photo")).name,
        source_kind=str(item.get("source_kind") or "company_reference"),
        source_drive_id=str(item.get("source_drive_id") or ""),
        source_item_id=str(item.get("source_item_id") or ""),
        source_path=str(item.get("source_path") or ""),
        source_web_url=str(item.get("source_web_url") or ""),
        source_etag=str(item.get("source_etag") or ""),
        source_size=max(0, int(item.get("source_size") or 0)),
        local_path=str(item.get("local_path") or ""),
        label=str(item.get("label") or ""),
        note=str(item.get("note") or ""),
        origin=str(item.get("origin") or ""),
        assignment_state=str(item.get("assignment_state") or ""),
    )
    with _LOCK:
        _SOURCES[token] = source
        # Bound process-local authorization state. Tokens are deterministic,
        # so an evicted source is restored the next time its gallery opens.
        while len(_SOURCES) > 6000:
            evicted = next(iter(_SOURCES))
            _SOURCES.pop(evicted)
            future = _THUMBNAIL_JOBS.pop(evicted, None)
            _THUMBNAIL_JOB_PRIORITY.pop(evicted, None)
            preview = _PREVIEW_JOBS.pop(evicted, None)
            _PREVIEW_JOB_PRIORITY.pop(evicted, None)
            full_resolution = _FULL_RESOLUTION_JOBS.pop(evicted, None)
            if future is not None:
                future.cancel()
            if preview is not None:
                preview.cancel()
            if full_resolution is not None:
                full_resolution.cancel()
    return {
        "photo_token": token,
        "source_key": f"{source.source_drive_id}::{source.source_item_id or source.source_path}",
        "file_name": source.file_name,
        "source_kind": source.source_kind,
        "source_path": source.source_path,
        "source_web_url": source.source_web_url,
        "source_size": source.source_size,
        "label": source.label,
        "note": source.note,
        "origin": source.origin,
        "assignment_state": source.assignment_state,
        "thumbnail_url": f"/api/photo-gallery/{token}/thumbnail",
        "content_url": f"/api/photo-gallery/{token}/content",
    }


def decorate_photo_items(project_id: str, items: list[dict], paths: AppPaths) -> list[dict]:
    """Register portable items, return safe gallery payloads, and prefetch."""
    decorated = [_register(project_id, item) for item in items]
    for item in decorated:
        _schedule_preview(item["photo_token"], paths, foreground=False)
    return decorated


def reference_sources_from_tokens(project_id: str, tokens: list[str]) -> list[dict]:
    """Resolve only gallery sources authorized for the originating project."""
    wanted = list(dict.fromkeys(str(token or "").strip() for token in tokens))
    if not wanted or len(wanted) > 300:
        return []
    sources: list[dict] = []
    with _LOCK:
        for token in wanted:
            source = _SOURCES.get(token)
            if source is None or source.project_id != project_id:
                continue
            sources.append({
                "file_name": source.file_name,
                "media_type": "photo",
                "source_kind": source.source_kind,
                "source_drive_id": source.source_drive_id,
                "source_item_id": source.source_item_id,
                "source_path": source.source_path,
                "source_web_url": source.source_web_url,
                "source_etag": source.source_etag,
                "source_size": source.source_size,
            })
    return sources


def _reference_items(project, *, unit_id: str, individual_id: str) -> list[dict]:
    if unit_id:
        return [
            {
                **asset_to_source(item.asset),
                "note": item.assignment.note,
                "origin": item.origin,
                "assignment_state": "legacy" if item.origin in {"project", "individual"} else "assigned",
            }
            for item in resolve_build_reference_photos(
                project, unit_id=unit_id, individual_id=individual_id,
            )
        ]

    items: list[dict] = []
    group_labels = {
        unit.unit_id: " · ".join(filter(None, (
            str(unit.vehicle_model or "").strip(),
            str(unit.build_type or "").strip(),
        ))) or "Unit group"
        for unit in project.build_units
    }
    for asset in project.reference_assets:
        if asset.media_type != "photo":
            continue
        notes = []
        origins = []
        for assignment in asset.assignments:
            if assignment.note and assignment.note not in notes:
                notes.append(assignment.note)
            if assignment.scope not in origins:
                origins.append(assignment.scope)
        group_names = [
            group_labels.get(assignment.target_id, "Unit group")
            for assignment in asset.assignments
            if assignment.scope == "unit_group"
        ]
        if not asset.assignments:
            label = "Unassigned"
            assignment_state = "unassigned"
        elif group_names:
            label = "Assigned: " + ", ".join(dict.fromkeys(group_names))
            assignment_state = "assigned"
        elif "project" in origins:
            label = "Legacy project-wide reference"
            assignment_state = "legacy"
        else:
            label = "Legacy unit-only reference"
            assignment_state = "legacy"
        items.append({
            **asset_to_source(asset),
            "note": " · ".join(notes),
            "origin": ", ".join(origins),
            "label": label,
            "assignment_state": assignment_state,
        })
    return items


def asset_to_source(asset: BuildReferenceAsset) -> dict:
    return {
        "file_name": asset.file_name,
        "source_kind": asset.source_kind,
        "source_drive_id": asset.source_drive_id,
        "source_item_id": asset.source_item_id,
        "source_path": asset.source_path,
        "source_web_url": asset.source_web_url,
        "source_etag": asset.source_etag,
        "source_size": asset.source_size,
    }


def _completed_folders(project, *, unit_id: str, individual_id: str) -> list[_CompletedFolder]:
    folders: list[_CompletedFolder] = []
    for unit in project.build_units:
        if unit_id and unit.unit_id != unit_id:
            continue
        if unit.individuals:
            for index, individual in enumerate(unit.individuals, 1):
                if individual_id and individual.individual_id != individual_id:
                    continue
                base = str(individual.shop_vehicle_folder_path or "").strip("/")
                if base:
                    folders.append(_CompletedFolder(
                        remote_path=f"{base}/Completed Build Photos",
                        label=vehicle_display_name(project, unit, individual, ordinal=index),
                        unit_id=unit.unit_id,
                        individual_id=individual.individual_id,
                    ))
        elif not individual_id:
            base = str(getattr(unit, "shop_vehicle_folder_path", "") or "").strip("/")
            if base:
                folders.append(_CompletedFolder(
                    remote_path=f"{base}/Completed Build Photos",
                    label=vehicle_display_name(project, unit, None),
                    unit_id=unit.unit_id,
                ))
    return folders


def _local_folder_items(folder: Path, completed: _CompletedFolder) -> list[dict]:
    items: list[dict] = []
    try:
        candidates = folder.rglob("*")
        for candidate in candidates:
            if len(items) >= _MAX_GALLERY_ITEMS:
                break
            try:
                if not candidate.is_file() or candidate.suffix.casefold() not in _PHOTO_SUFFIXES:
                    continue
                stat = candidate.stat()
                relative = candidate.relative_to(folder).as_posix()
            except (OSError, ValueError):
                continue
            items.append({
                "file_name": candidate.name,
                "source_kind": "shop_completed",
                "source_path": f"{completed.remote_path}/{relative}",
                "source_etag": f"local:{stat.st_mtime_ns}:{stat.st_size}",
                "source_size": stat.st_size,
                "local_path": str(candidate.resolve()),
                "label": completed.label,
                "_unit_id": completed.unit_id,
                "_individual_id": completed.individual_id,
            })
    except OSError:
        logger.exception("Could not enumerate locally synced completed photos")
    return items


def _graph_folder_items(gateway: GraphDriveGateway, completed: _CompletedFolder) -> list[dict]:
    items: list[dict] = []
    stack: list[tuple[str, int]] = [(completed.remote_path, 0)]
    while stack and len(items) < _MAX_GALLERY_ITEMS:
        if _SHUTDOWN_EVENT.is_set():
            break
        current, depth = stack.pop()
        try:
            children = gateway.list_children(current, timeout_seconds=8)
        except FileNotFoundError:
            continue
        for child in children:
            name = str(child.get("name") or "").strip()
            if not name or "/" in name or "\\" in name:
                continue
            path = f"{current}/{name}"
            if isinstance(child.get("folder"), dict):
                if depth < _MAX_GALLERY_DEPTH:
                    stack.append((path, depth + 1))
                continue
            if PurePosixPath(name).suffix.casefold() not in _PHOTO_SUFFIXES:
                continue
            items.append({
                "file_name": name,
                "source_kind": "shop_completed",
                "source_drive_id": gateway.drive_id,
                "source_item_id": str(child.get("id") or ""),
                "source_path": path,
                "source_web_url": str(child.get("webUrl") or ""),
                "source_etag": str(child.get("eTag") or child.get("@odata.etag") or ""),
                "source_size": max(0, int(child.get("size") or 0)),
                "label": completed.label,
                "_unit_id": completed.unit_id,
                "_individual_id": completed.individual_id,
            })
    return items


def _scan_completed(folders: list[_CompletedFolder]) -> tuple[list[dict], list[str]]:
    from ..adapters.cloud.config import load_cloud_config_from_env

    warnings: list[str] = []
    items: list[dict] = []
    try:
        config = load_cloud_config_from_env()
    except Exception:
        return [], ["Shop photo storage is not configured on this device."]

    unresolved: list[_CompletedFolder] = []
    for completed in folders:
        if _SHUTDOWN_EVENT.is_set():
            return items, warnings
        local = find_synced_library_folder(
            config.shop_library_name,
            config.shop_library_internal_name,
            completed.remote_path,
        )
        if local is not None:
            items.extend(_local_folder_items(local, completed))
        else:
            unresolved.append(completed)

    if unresolved:
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
            warnings.append("Completed photos are unavailable in cloud-off mode.")
        elif not wiring._cloud_flag_enabled():  # noqa: SLF001
            warnings.append("Completed photos are unavailable in cloud-off mode unless the Shop folder is synced locally.")
        else:
            try:
                gateway = GraphDriveGateway.from_active_cloud(config, library_names=(
                    config.shop_library_name,
                    config.shop_library_internal_name,
                ), timeout_seconds=8)
                for completed in unresolved:
                    if _SHUTDOWN_EVENT.is_set():
                        break
                    items.extend(_graph_folder_items(gateway, completed))
            except Exception:
                logger.exception("Could not enumerate completed-build photos")
                warnings.append("Could not load completed photos from Shop Documents.")

    unique: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (
            str(item.get("source_drive_id") or "local"),
            str(item.get("source_item_id") or item.get("local_path") or item.get("source_path")),
        )
        unique[key] = item
    ordered = sorted(unique.values(), key=lambda item: (
        str(item.get("label") or "").casefold(),
        str(item.get("source_path") or "").casefold(),
    ))
    return ordered, warnings


def _scan_key(project_id: str, folders: list[_CompletedFolder]) -> str:
    raw = project_id + "|" + "|".join(folder.remote_path for folder in folders)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _completed_presence(items: list[dict]) -> dict:
    targets: dict[str, int] = {}
    for item in items:
        unit_id = str(item.get("_unit_id") or "")
        individual_id = str(item.get("_individual_id") or "")
        if not unit_id:
            continue
        key = f"{unit_id}::{individual_id}"
        targets[key] = targets.get(key, 0) + 1
    return {"project": bool(items), "targets": targets}


def _presence_cache_path(scan_key: str, paths: AppPaths) -> Path:
    return (
        paths.workspace_reference_cache_dir
        / "completed-presence-v1"
        / f"{scan_key}.json"
    )


def _load_completed_presence(scan_key: str, paths: AppPaths) -> dict:
    """Load last verified file presence for an immediate project-card paint."""
    try:
        payload = json.loads(_presence_cache_path(scan_key, paths).read_text("utf-8"))
        if payload.get("scan_key") != scan_key:
            raise ValueError("Completed-photo presence cache key mismatch")
        presence = payload.get("presence") or {}
        targets = presence.get("targets") or {}
        if not isinstance(targets, dict):
            raise ValueError("Completed-photo presence targets are invalid")
        return {
            "project": bool(presence.get("project")),
            "targets": {
                str(key): max(0, int(value or 0))
                for key, value in targets.items()
            },
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {"project": False, "targets": {}}


def _save_completed_presence(
    scan_key: str,
    items: list[dict],
    warnings: list[str],
    paths: AppPaths,
) -> None:
    """Persist only authoritative scans; transient cloud failures keep known state."""
    if warnings or _SHUTDOWN_EVENT.is_set():
        return
    destination = _presence_cache_path(scan_key, paths)
    temporary = destination.with_suffix(".tmp")
    payload = {
        "scan_key": scan_key,
        "saved_at": time.time(),
        "presence": _completed_presence(items),
    }
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, sort_keys=True), "utf-8")
        temporary.replace(destination)
    except OSError:
        logger.debug("Could not persist completed-photo presence", exc_info=True)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def handle_photo_gallery(project_id: str, body: dict, paths: AppPaths) -> dict:
    try:
        project = load_project(project_id, paths)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    kind = str(body.get("kind") or "reference").strip().casefold()
    unit_id = str(body.get("unit_id") or "").strip()
    individual_id = str(body.get("individual_id") or "").strip()
    presence_only = bool(body.get("presence_only"))
    if kind == "reference":
        folder_sync = {
            "loading": False, "changed": 0, "warnings": [],
        }
        if bool(body.get("discover_folder")) and not unit_id:
            from .project_photo_folder_service import handle_sync_project_photo_folder

            folder_sync = handle_sync_project_photo_folder(
                project_id, paths, refresh=bool(body.get("refresh")),
            )
            if not folder_sync.get("ok"):
                return folder_sync
            if not folder_sync.get("loading") and folder_sync.get("changed"):
                project = load_project(project_id, paths)
        items = _reference_items(project, unit_id=unit_id, individual_id=individual_id)
        return {
            "ok": True,
            "loading": bool(folder_sync.get("loading")),
            "kind": kind,
            "photos": [] if presence_only else decorate_photo_items(project_id, items, paths),
            "warnings": list(folder_sync.get("warnings") or []),
            "project_changed": int(folder_sync.get("changed") or 0),
        }
    if kind != "completed":
        return {"ok": False, "error": "Photo gallery kind must be reference or completed."}

    folders = _completed_folders(project, unit_id=unit_id, individual_id=individual_id)
    if not folders:
        return {
            "ok": True,
            "loading": False,
            "kind": kind,
            "photos": [],
            "presence": {"project": False, "targets": {}},
            "warnings": ["This build does not have a provisioned Completed Build Photos folder yet."],
        }
    key = _scan_key(project_id, folders)
    last_presence = _load_completed_presence(key, paths)
    refresh = bool(body.get("refresh"))
    with _LOCK:
        cached = _SCAN_RESULTS.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < _RESULT_TTL_SECONDS:
            _saved_at, items, warnings = cached
            presence = _completed_presence(items)
            _save_completed_presence(key, items, warnings, paths)
            return {
                "ok": True, "loading": False, "kind": kind,
                "photos": [] if presence_only else decorate_photo_items(project_id, items, paths),
                "presence": presence,
                "warnings": warnings,
            }
        future = _SCAN_JOBS.get(key)
        if future is not None and future.done():
            try:
                items, warnings = future.result()
            except Exception:
                logger.exception("Completed-photo background scan failed")
                items, warnings = [], ["Could not load completed photos."]
            _SCAN_RESULTS[key] = (time.monotonic(), items, warnings)
            _SCAN_JOBS.pop(key, None)
            presence = _completed_presence(items)
            _save_completed_presence(key, items, warnings, paths)
            return {
                "ok": True, "loading": False, "kind": kind,
                "photos": [] if presence_only else decorate_photo_items(project_id, items, paths),
                "presence": presence,
                "warnings": warnings,
            }
        if future is None:
            _SCAN_JOBS[key] = _SCAN_EXECUTOR.submit(_scan_completed, folders)
    return {
        "ok": True, "loading": True, "kind": kind, "photos": [],
        "presence": last_presence, "warnings": [],
    }


def _thumbnail_path(token: str, paths: AppPaths) -> Path:
    # v2 invalidates older Graph-generated thumbnails that could contain baked-in
    # portrait letterboxing. New thumbnails are generated from exact source bytes.
    return paths.workspace_reference_cache_dir / "thumbnails-v2" / f"{token}.jpg"


def _preview_path(token: str, paths: AppPaths) -> Path:
    """Persistent fast preview used while the exact thumbnail is prepared."""
    return paths.workspace_reference_cache_dir / "thumbnail-previews-v1" / f"{token}.jpg"


def _full_resolution_path(source: _PhotoSource, paths: AppPaths) -> Path:
    suffix = Path(source.file_name).suffix.casefold()
    if suffix not in _PHOTO_SUFFIXES:
        suffix = ".jpg"
    return (
        paths.workspace_reference_cache_dir
        / "gallery-full-v1"
        / source.token[:2]
        / f"{source.token}{suffix}"
    )


def _source_asset(source: _PhotoSource) -> BuildReferenceAsset:
    return BuildReferenceAsset(
        reference_id=f"gallery-{source.token}",
        file_name=source.file_name,
        source_kind=source.source_kind,
        source_drive_id=source.source_drive_id,
        source_item_id=source.source_item_id,
        source_path=source.source_path,
        source_web_url=source.source_web_url,
        source_etag=source.source_etag,
        source_size=source.source_size,
    )


def _cached_full_resolution(source: _PhotoSource, paths: AppPaths) -> Path | None:
    local_copy = _full_resolution_path(source, paths)
    try:
        if local_copy.is_file() and local_copy.stat().st_size > 0:
            return local_copy
    except OSError:
        pass
    if source.local_path:
        return None
    cached = cached_reference_media(_source_asset(source), paths)
    return cached.path if cached is not None else None


def _full_resolution_is_active() -> bool:
    return any(not future.done() for future in _FULL_RESOLUTION_JOBS.values())


def _wait_for_full_resolution_priority() -> bool:
    """Pause new thumbnail network work while an opened original downloads."""
    with _PRIORITY_CONDITION:
        while _full_resolution_is_active() and not _SHUTDOWN_EVENT.is_set():
            _PRIORITY_CONDITION.wait(timeout=0.2)
    return not _SHUTDOWN_EVENT.is_set()


def _build_full_resolution(source: _PhotoSource, paths: AppPaths) -> Path | None:
    cached = _cached_full_resolution(source, paths)
    if cached is not None or _SHUTDOWN_EVENT.is_set():
        return cached
    try:
        if source.local_path:
            original = Path(source.local_path)
            size = original.stat().st_size
            if size <= 0 or size > _MAX_FULL_RESOLUTION_BYTES:
                return None
            destination = _full_resolution_path(source, paths)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".download")
            with original.open("rb") as input_stream, temporary.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            if _SHUTDOWN_EVENT.is_set():
                temporary.unlink(missing_ok=True)
                return None
            temporary.replace(destination)
            return destination
        resolved = resolve_reference_media(
            _source_asset(source),
            paths,
            download_timeout_seconds=_FULL_RESOLUTION_TIMEOUT_SECONDS,
        )
        return resolved.path
    except (OSError, shutil.Error):
        logger.warning("Could not cache full-resolution photo %s", source.file_name)
        return None


def _finish_full_resolution(_token: str, _future: Future) -> None:
    with _PRIORITY_CONDITION:
        _PRIORITY_CONDITION.notify_all()


def _schedule_full_resolution(
    source: _PhotoSource,
    paths: AppPaths,
) -> Future | None:
    global _FULL_RESOLUTION_CURRENT_TOKEN

    if _SHUTDOWN_EVENT.is_set():
        return None
    with _PRIORITY_CONDITION:
        current = _FULL_RESOLUTION_JOBS.get(source.token)
        if current is not None:
            return current
        # A user stepping through the viewer should not queue behind work for
        # photos they have already left. Running downloads may finish and seed
        # the cache; queued obsolete downloads are cancelled.
        for token, future in list(_FULL_RESOLUTION_JOBS.items()):
            if token != source.token and not future.done() and future.cancel():
                _FULL_RESOLUTION_JOBS.pop(token, None)
        _FULL_RESOLUTION_CURRENT_TOKEN = source.token
        future = _FULL_RESOLUTION_EXECUTOR.submit(
            _build_full_resolution, source, paths,
        )
        _FULL_RESOLUTION_JOBS[source.token] = future
        future.add_done_callback(
            lambda completed, token=source.token: _finish_full_resolution(token, completed)
        )
        _PRIORITY_CONDITION.notify_all()
        return future


def _write_thumbnail(data: bytes, destination: Path) -> None:
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((640, 480), Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        image.save(temporary, "JPEG", quality=84, optimize=True)
        temporary.replace(destination)


def _source_thumbnail_gateway(source: _PhotoSource) -> GraphDriveGateway | None:
    if not source.source_drive_id or not source.source_item_id:
        return None
    try:
        bundle = wiring.get_active_bundle()
        token_provider = getattr(bundle.storage, "_token_provider", None)
        if token_provider is None:
            return None
        return GraphDriveGateway(
            token=token_provider(), drive_id=source.source_drive_id,
        )
    except Exception:
        logger.debug("Source photo preview is unavailable", exc_info=True)
        return None


def _build_preview(source: _PhotoSource, paths: AppPaths) -> Path | None:
    """Build a small displayable preview without hydrating the original file."""
    destination = _preview_path(source.token, paths)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    if _SHUTDOWN_EVENT.is_set():
        return None
    if not _wait_for_full_resolution_priority():
        return None
    try:
        gateway = _source_thumbnail_gateway(source)
        if gateway is not None:
            data = gateway.download_thumbnail(
                source.source_item_id, size="large", timeout_seconds=8,
            )
        elif source.local_path:
            data = Path(source.local_path).read_bytes()
        else:
            return None
        _write_thumbnail(data, destination)
        return destination
    except Exception:
        logger.debug("Could not build fast photo preview for %s", source.file_name)
        return None


def _shared_thumbnail_remote_path(token: str) -> str:
    return f"{_SHARED_THUMBNAIL_ROOT}/{token[:2]}/{token}.jpg"


def _shared_thumbnail_gateway(source: _PhotoSource) -> GraphDriveGateway | None:
    """Return the Company Files cache gateway for stable Graph sources only."""
    if _SHUTDOWN_EVENT.is_set():
        return None
    if not (source.source_drive_id and source.source_item_id and source.source_etag):
        return None
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return None
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return None
    try:
        from ..adapters.cloud.config import load_cloud_config_from_env

        config = load_cloud_config_from_env()
        bundle = wiring.get_active_bundle()
        token_provider = getattr(bundle.storage, "_token_provider", None)
        if token_provider is None or not config.sharepoint_drive_id:
            return None
        return GraphDriveGateway(
            token=token_provider(), drive_id=config.sharepoint_drive_id,
        )
    except Exception:
        logger.debug("Shared photo-thumbnail cache is unavailable", exc_info=True)
        return None


def _download_shared_thumbnail(
    source: _PhotoSource,
    destination: Path,
    gateway: GraphDriveGateway,
) -> bool:
    if _SHUTDOWN_EVENT.is_set():
        return False
    try:
        item = gateway.get_item_by_path(
            _shared_thumbnail_remote_path(source.token), timeout_seconds=2,
        )
        if item is None or isinstance(item.get("folder"), dict):
            return False
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            return False
        if _SHUTDOWN_EVENT.is_set():
            return False
        _write_thumbnail(gateway.download_item(item_id, timeout_seconds=4), destination)
        return True
    except Exception:
        logger.debug("Shared photo thumbnail could not be downloaded", exc_info=True)
        return False


def _upload_shared_thumbnail(
    source: _PhotoSource,
    thumbnail: Path,
    gateway: GraphDriveGateway,
) -> None:
    if _SHUTDOWN_EVENT.is_set():
        return
    remote_path = _shared_thumbnail_remote_path(source.token)
    remote_folder = str(PurePosixPath(remote_path).parent)
    try:
        if gateway.get_item_by_path(remote_path, timeout_seconds=2) is not None:
            return
        with _LOCK:
            folder_ready = remote_folder in _SHARED_THUMBNAIL_FOLDERS
        if not folder_ready:
            gateway.ensure_folder(remote_folder, timeout_seconds=2)
            with _LOCK:
                _SHARED_THUMBNAIL_FOLDERS.add(remote_folder)
        if _SHUTDOWN_EVENT.is_set():
            return
        gateway.upload_file(
            remote_path, thumbnail.read_bytes(), timeout_seconds=4,
        )
    except Exception:
        # The local thumbnail is still valid; shared caching is an accelerator,
        # never a reason to make a gallery fail.
        logger.debug("Shared photo thumbnail could not be uploaded", exc_info=True)


def _build_thumbnail(source: _PhotoSource, paths: AppPaths) -> Path | None:
    destination = _thumbnail_path(source.token, paths)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    if _SHUTDOWN_EVENT.is_set():
        return None
    if not _wait_for_full_resolution_priority():
        return None
    shared_gateway = _shared_thumbnail_gateway(source)
    if shared_gateway is not None and _download_shared_thumbnail(
        source, destination, shared_gateway,
    ):
        return destination
    try:
        if source.local_path:
            data = Path(source.local_path).read_bytes()
        else:
            resolved = resolve_reference_media(
                _source_asset(source), paths, download_timeout_seconds=12,
            )
            if resolved.path is None:
                return None
            data = resolved.path.read_bytes()
        _write_thumbnail(data, destination)
        if shared_gateway is not None and not _SHUTDOWN_EVENT.is_set():
            _upload_shared_thumbnail(source, destination, shared_gateway)
        return destination
    except Exception:
        logger.warning("Could not build photo thumbnail for %s", source.file_name)
        return None


def _schedule_thumbnail(
    token: str,
    paths: AppPaths,
    *,
    foreground: bool,
) -> Future | None:
    if _SHUTDOWN_EVENT.is_set():
        return None
    with _LOCK:
        source = _SOURCES.get(token)
        if source is None:
            return None
        if _thumbnail_path(token, paths).is_file():
            return None
        current = _THUMBNAIL_JOBS.get(token)
        if current is not None and not current.done():
            if foreground and _THUMBNAIL_JOB_PRIORITY.get(token) == "background":
                # A queued background task can be cancelled and promoted. If
                # it is already running, let that one request finish instead
                # of downloading the same source twice.
                if current.cancel():
                    current = None
                else:
                    return current
            else:
                return current
        future = _THUMBNAIL_EXACT_EXECUTOR.submit(_build_thumbnail, source, paths)
        _THUMBNAIL_JOBS[token] = future
        _THUMBNAIL_JOB_PRIORITY[token] = "foreground" if foreground else "background"
        return future


def _schedule_preview(
    token: str,
    paths: AppPaths,
    *,
    foreground: bool,
) -> Future | None:
    if _SHUTDOWN_EVENT.is_set():
        return None
    with _LOCK:
        source = _SOURCES.get(token)
        if source is None:
            return None
        if _preview_path(token, paths).is_file() or _thumbnail_path(token, paths).is_file():
            return None
        current = _PREVIEW_JOBS.get(token)
        if current is not None and not current.done():
            if foreground and _PREVIEW_JOB_PRIORITY.get(token) == "background":
                if current.cancel():
                    current = None
                else:
                    return current
            else:
                return current
        executor = (
            _THUMBNAIL_FOREGROUND_EXECUTOR
            if foreground else _PREVIEW_BACKGROUND_EXECUTOR
        )
        future = executor.submit(_build_preview, source, paths)
        _PREVIEW_JOBS[token] = future
        _PREVIEW_JOB_PRIORITY[token] = "foreground" if foreground else "background"
        return future


def _cache_prep_key(paths: AppPaths) -> str:
    return str(paths.workspace_projects_dir.resolve())


def _photo_catalog_fingerprint(projects) -> str:
    """Hash only durable project photo identities, not unrelated project edits."""
    payload = []
    for project in sorted(projects, key=lambda item: item.project_id):
        references = sorted((
            (
                asset.reference_id,
                asset.file_name,
                asset.media_type,
                asset.source_kind,
                asset.source_drive_id,
                asset.source_item_id,
                asset.source_path,
                asset.source_etag,
                int(asset.source_size or 0),
            )
            for asset in project.reference_assets
        ))
        payload.append((project.project_id, references))
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _photo_catalog_cache_path(paths: AppPaths) -> Path:
    return paths.workspace_reference_cache_dir / "photo-catalog-v1.json"


def _load_photo_catalog_fingerprint(paths: AppPaths) -> str:
    try:
        payload = json.loads(_photo_catalog_cache_path(paths).read_text("utf-8"))
        return str(payload.get("fingerprint") or "")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return ""


def _save_photo_catalog_fingerprint(paths: AppPaths, fingerprint: str) -> None:
    destination = _photo_catalog_cache_path(paths)
    temporary = destination.with_suffix(".tmp")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({
            "fingerprint": fingerprint,
            "saved_at": time.time(),
        }, sort_keys=True), "utf-8")
        temporary.replace(destination)
    except OSError:
        logger.debug("Could not persist photo catalog fingerprint", exc_info=True)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _finish_cache_prep(key: str, future: Future) -> None:
    if future.cancelled() or _SHUTDOWN_EVENT.is_set():
        return
    try:
        error = future.exception()
    except Exception as exc:  # pragma: no cover - defensive executor boundary
        error = exc
    if error is None:
        return
    logger.exception("Photo thumbnail preparation failed", exc_info=error)
    with _LOCK:
        state = _CACHE_PREP_STATES.get(key)
        if state is not None:
            state["phase"] = "error"


def _prepare_thumbnail_cache(
    paths: AppPaths,
    key: str,
    projects=None,
    fingerprint: str = "",
) -> None:
    """Register changed project-photo metadata and warm small previews."""
    projects = list(projects) if projects is not None else list_projects(paths)
    fingerprint = fingerprint or _photo_catalog_fingerprint(projects)
    with _LOCK:
        state = _CACHE_PREP_STATES[key]
        state.update({"phase": "checking", "projects_total": len(projects)})

    for index, project in enumerate(projects, 1):
        if _SHUTDOWN_EVENT.is_set():
            return
        reference_items = _reference_items(project, unit_id="", individual_id="")
        for item in reference_items:
            token = _register(project.project_id, item)["photo_token"]
            _schedule_preview(token, paths, foreground=False)

        with _LOCK:
            state = _CACHE_PREP_STATES[key]
            state["projects_done"] = index

    if not _SHUTDOWN_EVENT.is_set():
        _save_photo_catalog_fingerprint(paths, fingerprint)
    with _LOCK:
        _CACHE_PREP_STATES[key]["phase"] = "preparing"


def start_thumbnail_cache_prepare(paths: AppPaths) -> dict:
    """Skip unchanged catalogs; warm only newly known project-photo sources."""
    if _SHUTDOWN_EVENT.is_set():
        return get_thumbnail_cache_status(paths)
    key = _cache_prep_key(paths)
    projects = list_projects(paths)
    fingerprint = _photo_catalog_fingerprint(projects)
    unchanged = fingerprint == _load_photo_catalog_fingerprint(paths)
    with _LOCK:
        future = _CACHE_PREP_JOBS.get(key)
        state = _CACHE_PREP_STATES.get(key)
        if future is None and state is None:
            if unchanged:
                _CACHE_PREP_STATES[key] = {
                    "phase": "complete",
                    "projects_done": len(projects),
                    "projects_total": len(projects),
                }
                return get_thumbnail_cache_status(paths)
            _CACHE_PREP_STATES[key] = {
                "phase": "checking", "projects_done": 0,
                "projects_total": len(projects),
            }
            future = _THUMBNAIL_PREP_EXECUTOR.submit(
                _prepare_thumbnail_cache, paths, key, projects, fingerprint,
            )
            _CACHE_PREP_JOBS[key] = future
            future.add_done_callback(lambda completed, prep_key=key: _finish_cache_prep(prep_key, completed))
    return get_thumbnail_cache_status(paths)


def get_thumbnail_cache_status(paths: AppPaths) -> dict:
    """Return local-only progress for the header connection/status chip."""
    prep_key = _cache_prep_key(paths)
    with _LOCK:
        tokens = list(_SOURCES)
        jobs = {token: _THUMBNAIL_JOBS.get(token) for token in tokens}
        preview_jobs = {token: _PREVIEW_JOBS.get(token) for token in tokens}
        prep_future = _CACHE_PREP_JOBS.get(prep_key)
        prep_state = dict(_CACHE_PREP_STATES.get(prep_key) or {})
        full_jobs = {
            token: future
            for token, future in _FULL_RESOLUTION_JOBS.items()
            if not future.done()
        }
        full_token = _FULL_RESOLUTION_CURRENT_TOKEN
        full_source = _SOURCES.get(full_token)
    ready = failed = working = 0
    for token in tokens:
        try:
            cached = (
                _thumbnail_path(token, paths).is_file()
                or _preview_path(token, paths).is_file()
            )
        except OSError:
            cached = False
        if cached:
            ready += 1
            continue
        # Preview preparation is the global warm-up contract. An exact job is
        # on-demand and must not leave progress stuck after a preview failed.
        preview_future = preview_jobs.get(token)
        display_future = preview_future if preview_future is not None else jobs.get(token)
        if display_future is not None and not display_future.done():
            working += 1
        elif display_future is not None and display_future.done():
            failed += 1
    prep_active = prep_future is not None and not prep_future.done()
    full_active = bool(full_jobs)
    active = full_active or prep_active or working > 0
    if full_active:
        phase = "full_resolution"
    elif prep_active:
        phase = str(prep_state.get("phase") or "checking")
    elif working:
        phase = "preparing"
    elif prep_state.get("phase") == "error":
        phase = "error"
    else:
        phase = "complete" if prep_state else "idle"
    return {
        "ok": True,
        "active": active,
        "phase": phase,
        "total": len(tokens),
        "ready": ready,
        "preparing": working,
        "failed": failed,
        "projects_done": int(prep_state.get("projects_done") or 0),
        "projects_total": int(prep_state.get("projects_total") or 0),
        "full_resolution_active": full_active,
        "full_resolution_count": len(full_jobs),
        "full_resolution_file": full_source.file_name if full_source is not None else "",
    }


def shutdown_photo_gallery_workers() -> None:
    """Cancel queued photo work so closing the app cannot drain the whole cache."""
    _SHUTDOWN_EVENT.set()
    with _LOCK:
        futures = [
            *(_SCAN_JOBS.values()),
            *(_THUMBNAIL_JOBS.values()),
            *(_PREVIEW_JOBS.values()),
            *(_CACHE_PREP_JOBS.values()),
            *(_FULL_RESOLUTION_JOBS.values()),
        ]
    for future in futures:
        future.cancel()
    for executor in (
        _THUMBNAIL_PREP_EXECUTOR,
        _PREVIEW_BACKGROUND_EXECUTOR,
        _THUMBNAIL_EXACT_EXECUTOR,
        _THUMBNAIL_FOREGROUND_EXECUTOR,
        _SCAN_EXECUTOR,
        _FULL_RESOLUTION_EXECUTOR,
    ):
        executor.shutdown(wait=False, cancel_futures=True)
    with _PRIORITY_CONDITION:
        _PRIORITY_CONDITION.notify_all()


def get_gallery_media(token: str, variant: str, paths: AppPaths) -> tuple[int, bytes, str, str, str]:
    """Return status, bytes, content type, filename, and cache state."""
    with _LOCK:
        source = _SOURCES.get(token)
    if source is None:
        return 404, b"Not found", "text/plain", "", "missing"
    if variant == "thumbnail":
        path = _thumbnail_path(token, paths)
        if path.is_file():
            return 200, path.read_bytes(), "image/jpeg", source.file_name, "ready"

        preview_path = _preview_path(token, paths)
        if preview_path.is_file():
            _schedule_thumbnail(token, paths, foreground=True)
            return 200, preview_path.read_bytes(), "image/jpeg", source.file_name, "preview"

        with _LOCK:
            previous_preview = _PREVIEW_JOBS.get(token)
        preview_future = (
            previous_preview
            if previous_preview is not None and previous_preview.done()
            else _schedule_preview(token, paths, foreground=True)
        )
        deadline = time.monotonic() + _THUMBNAIL_FOREGROUND_WAIT_SECONDS
        while time.monotonic() < deadline:
            if path.is_file() or preview_path.is_file():
                break
            if preview_future is not None and preview_future.done():
                break
            time.sleep(0.05)
        if path.is_file():
            return 200, path.read_bytes(), "image/jpeg", source.file_name, "ready"
        if preview_path.is_file():
            return 200, preview_path.read_bytes(), "image/jpeg", source.file_name, "preview"
        if preview_future is not None and not preview_future.done():
            return 202, b"Preparing", "text/plain", source.file_name, "preparing"
        exact_future = _schedule_thumbnail(token, paths, foreground=True)
        if exact_future is not None and not exact_future.done():
            return 202, b"Preparing", "text/plain", source.file_name, "preparing"
        if path.is_file():
            return 200, path.read_bytes(), "image/jpeg", source.file_name, "ready"
        return 404, b"Not found", "text/plain", "", "missing"
    if variant != "content":
        return 404, b"Not found", "text/plain", "", "missing"
    path = _cached_full_resolution(source, paths)
    future = None
    if path is not None:
        with _LOCK:
            completed = _FULL_RESOLUTION_JOBS.get(token)
            if completed is not None and completed.done():
                _FULL_RESOLUTION_JOBS.pop(token, None)
    if path is None:
        future = _schedule_full_resolution(source, paths)
        if future is not None and not future.done():
            return 202, b"Downloading", "text/plain", source.file_name, "preparing"
        if future is not None:
            try:
                path = future.result()
            except Exception:
                logger.warning("Full-resolution photo preparation failed", exc_info=True)
                path = None
            with _LOCK:
                if _FULL_RESOLUTION_JOBS.get(token) is future:
                    _FULL_RESOLUTION_JOBS.pop(token, None)
    if path is None or not path.is_file():
        return 404, b"Not found", "text/plain", "", "missing"
    try:
        content_type = mimetypes.guess_type(source.file_name)[0] or "application/octet-stream"
        return 200, path.read_bytes(), content_type, source.file_name, "ready"
    except OSError:
        return 404, b"Not found", "text/plain", "", "missing"
