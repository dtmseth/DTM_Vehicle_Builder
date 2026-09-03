"""Read-only discovery of reusable media within one agency's file trees."""
from __future__ import annotations

import logging
import os
import hashlib
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from ...domain.vehicle_naming import safe_vehicle_folder_name, vehicle_display_name, vehicle_model_label
from ...inputs.project_entry import list_projects, load_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway


logger = logging.getLogger(__name__)
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
_MAX_VISITED_ITEMS = 3000
_MAX_DEPTH = 8
_CACHE_REFRESH_SECONDS = 300
_DISCOVERY_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dtm-reference")
_DISCOVERY_LOCK = threading.RLock()
_DISCOVERY_JOBS: dict[str, Future] = {}


class ReferenceBrowseGateway(Protocol):
    drive_id: str
    def list_children(self, remote_path: str) -> list[dict]: ...


@dataclass(frozen=True)
class _BrowseRoot:
    gateway: ReferenceBrowseGateway
    path: str
    source_kind: str


def _agency_segment(value: str) -> str:
    cleaned = safe_vehicle_folder_name(value)
    return cleaned if cleaned != "Unidentified Vehicle" else "Unassigned Agency"


def _media_type(folder_name: str, file_name: str, source_kind: str) -> str:
    suffix = PurePosixPath(file_name).suffix.casefold()
    if source_kind == "company_reference":
        if suffix in _VIDEO_SUFFIXES:
            return "video"
        if suffix in _PHOTO_SUFFIXES:
            return "photo"
        return ""
    return "photo" if suffix in _PHOTO_SUFFIXES else ""


def _discover_root(root: _BrowseRoot) -> tuple[list[dict], list[str]]:
    discovered: list[dict] = []
    warnings: list[str] = []
    visited = 0
    stack: list[tuple[str, int, bool]] = [(root.path.strip("/"), 0, False)]
    target_folders = (
        {"reference photos & videos", "build reference photos", "reference videos"}
        if root.source_kind == "company_reference"
        else {"completed build photos"}
    )
    while stack and visited < _MAX_VISITED_ITEMS:
        current, depth, inherited_target = stack.pop()
        try:
            children = root.gateway.list_children(current)
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception("Could not browse reference library path")
            warnings.append(f"Could not read {root.source_kind.replace('_', ' ')} media.")
            break
        visited += len(children)
        folder_name = PurePosixPath(current).name.casefold()
        inside_target = inherited_target or folder_name in target_folders
        for item in children:
            name = str(item.get("name") or "").strip()
            if not name or "/" in name or "\\" in name:
                continue
            item_path = "/".join(part for part in (current, name) if part)
            is_folder = isinstance(item.get("folder"), dict)
            if is_folder:
                child_target = inside_target or name.casefold() in target_folders
                if depth < _MAX_DEPTH:
                    stack.append((item_path, depth + 1, child_target))
                continue
            if not inside_target:
                continue
            media_type = _media_type(PurePosixPath(current).name, name, root.source_kind)
            if not media_type:
                continue
            discovered.append({
                "file_name": name,
                "media_type": media_type,
                "source_kind": root.source_kind,
                "source_drive_id": root.gateway.drive_id,
                "source_item_id": str(item.get("id") or ""),
                "source_path": item_path,
                "source_web_url": str(item.get("webUrl") or ""),
                "source_etag": str(item.get("eTag") or item.get("@odata.etag") or ""),
                "source_size": max(0, int(item.get("size") or 0)),
            })
    if stack:
        warnings.append("The agency media list was truncated; narrow the source folders before retrying.")
    return discovered, warnings


def discover_agency_reference_media(
    project_id: str,
    paths: AppPaths,
    *,
    agency: str = "",
    roots: list[_BrowseRoot] | None = None,
) -> dict:
    """Return Company references/videos and Shop completed photos for agency."""
    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    agency = str(agency or project.customer.agency or "").strip()
    if not agency:
        return {"ok": False, "error": "Add an agency before browsing reference photos."}
    if roots is None:
        try:
            roots = _cloud_roots(agency)
        except RuntimeError as exc:
            return {"ok": True, "available": False, "references": [], "warnings": [str(exc)]}

    references: list[dict] = []
    warnings: list[str] = []
    for root in roots:
        items, root_warnings = _discover_root(root)
        references.extend(items)
        warnings.extend(root_warnings)
    unique: dict[tuple[str, str], dict] = {}
    for item in references:
        key = (item["source_drive_id"], item["source_item_id"] or item["source_path"])
        unique[key] = item
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            item["source_kind"], item["source_path"].casefold(), item["file_name"].casefold(),
        ),
    )
    return {
        "ok": True,
        "available": bool(roots),
        "agency": agency,
        "references": _add_source_context(agency, ordered, paths),
        "warnings": warnings,
    }


def _add_source_context(agency: str, references: list[dict], paths: AppPaths) -> list[dict]:
    """Attach filter metadata inferred from durable project folder paths."""
    matches: list[tuple[str, dict]] = []
    agency_key = agency.strip().casefold()
    for project in list_projects(paths):
        if str(project.customer.agency or "").strip().casefold() != agency_key:
            continue
        common = {
            "source_agency": str(project.customer.agency or agency),
            "source_build_year": str(project.customer.build_year or ""),
        }
        for unit in project.build_units:
            group_context = {
                **common,
                "source_vehicle_make": "",
                "source_vehicle_model": vehicle_model_label(unit),
                "source_build_type": str(unit.build_type or ""),
                "source_vehicle_name": vehicle_display_name(project, unit, None),
            }
            for folder_path in (unit.company_group_folder_path, unit.shop_group_folder_path):
                if folder_path:
                    matches.append((str(folder_path).strip("/"), group_context))
            for ordinal, individual in enumerate(unit.individuals, 1):
                individual_context = {
                    **group_context,
                    "source_vehicle_make": str(individual.make or ""),
                    "source_vehicle_model": vehicle_model_label(unit, individual),
                    "source_vehicle_name": vehicle_display_name(
                        project, unit, individual, ordinal=ordinal,
                    ),
                }
                for folder_path in (
                    individual.company_vehicle_folder_path,
                    individual.shop_vehicle_folder_path,
                ):
                    if folder_path:
                        matches.append((str(folder_path).strip("/"), individual_context))
        for year_path in (project.company_year_folder_path, project.shop_year_folder_path):
            if year_path:
                matches.append((str(year_path).strip("/"), {
                    **common,
                    "source_vehicle_make": "",
                    "source_vehicle_model": "",
                    "source_build_type": "",
                    "source_vehicle_name": "",
                }))
    matches.sort(key=lambda item: len(item[0]), reverse=True)

    enriched: list[dict] = []
    for reference in references:
        source_path = str(reference.get("source_path") or "").strip("/")
        context = next((
            metadata for prefix, metadata in matches
            if source_path == prefix or source_path.startswith(f"{prefix}/")
        ), None)
        enriched.append({
            **reference,
            "source_agency": agency,
            "source_build_year": "",
            "source_vehicle_make": "",
            "source_vehicle_model": "",
            "source_build_type": "",
            "source_vehicle_name": "",
            **(context or {}),
        })
    return enriched


def _cache_path(agency: str, paths: AppPaths):
    key = hashlib.sha256(agency.strip().casefold().encode("utf-8")).hexdigest()[:24]
    return paths.workspace_reference_cache_dir / "library" / f"{key}.json"


def _load_cached_discovery(agency: str, paths: AppPaths) -> tuple[dict | None, float]:
    path = _cache_path(agency, paths)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("agency", "").strip().casefold() != agency.strip().casefold():
            return None, 0
        return payload.get("result"), float(payload.get("saved_at") or 0)
    except Exception:
        return None, 0


def _save_cached_discovery(agency: str, result: dict, paths: AppPaths) -> None:
    path = _cache_path(agency, paths)
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({
            "agency": agency,
            "saved_at": time.time(),
            "result": result,
        }, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        logger.exception("Could not write agency reference-library cache")
        temporary.unlink(missing_ok=True)


def _enrich_thumbnails(project_id: str, result: dict, paths: AppPaths) -> dict:
    from .photo_gallery_service import decorate_photo_items

    references = list(result.get("references") or [])
    photo_indexes = [
        index for index, item in enumerate(references)
        if item.get("media_type") == "photo"
    ]
    decorated = decorate_photo_items(
        project_id, [references[index] for index in photo_indexes], paths,
    )
    for index, gallery_item in zip(photo_indexes, decorated):
        references[index] = {**references[index], **gallery_item}
    return {**result, "references": references}


def _refresh_source_context(agency: str, result: dict, paths: AppPaths) -> dict:
    """Upgrade older cached discovery payloads before applying UI filters."""
    return {
        **result,
        "agency": agency,
        "references": _add_source_context(
            agency, list(result.get("references") or []), paths,
        ),
    }


def _start_discovery(project_id: str, agency: str, paths: AppPaths) -> Future:
    key = agency.strip().casefold()
    with _DISCOVERY_LOCK:
        future = _DISCOVERY_JOBS.get(key)
        if future is None or future.done():
            future = _DISCOVERY_EXECUTOR.submit(
                discover_agency_reference_media, project_id, paths, agency=agency,
            )
            _DISCOVERY_JOBS[key] = future
        return future


def handle_discover_references(
    project_id: str,
    paths: AppPaths,
    *,
    agency: str = "",
) -> dict:
    """Return cached media immediately while a bounded background refresh runs."""
    try:
        project = load_project(project_id, paths)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    requested_agency = str(agency or "").strip()
    agency_names = {
        str(item.customer.agency or "").strip().casefold(): str(item.customer.agency or "").strip()
        for item in list_projects(paths)
        if str(item.customer.agency or "").strip()
    }
    if requested_agency:
        agency = agency_names.get(requested_agency.casefold(), "")
        if not agency:
            return {"ok": False, "error": "Select an agency that exists in the app."}
    else:
        agency = str(project.customer.agency or "").strip()
    if not agency:
        return {"ok": False, "error": "Add an agency before browsing reference photos."}
    key = agency.casefold()
    with _DISCOVERY_LOCK:
        future = _DISCOVERY_JOBS.get(key)
        if future is not None and future.done():
            try:
                result = future.result()
            except Exception:
                logger.exception("Agency reference-library refresh failed")
                result = {"ok": False, "error": "Could not browse agency media."}
            _DISCOVERY_JOBS.pop(key, None)
            if result.get("ok"):
                result = _refresh_source_context(agency, result, paths)
                if result.get("available"):
                    _save_cached_discovery(agency, result, paths)
                return {**_enrich_thumbnails(project_id, result, paths), "loading": False}
            return result

    cached, saved_at = _load_cached_discovery(agency, paths)
    if cached is not None:
        cached = _refresh_source_context(agency, cached, paths)
        stale = time.time() - saved_at >= _CACHE_REFRESH_SECONDS
        if stale:
            _start_discovery(project_id, agency, paths)
        return {
            **_enrich_thumbnails(project_id, cached, paths),
            "loading": False,
            "refreshing": stale,
        }

    _start_discovery(project_id, agency, paths)
    return {
        "ok": True,
        "available": True,
        "agency": agency,
        "references": [],
        "warnings": [],
        "loading": True,
    }


def _cloud_roots(agency: str) -> list[_BrowseRoot]:
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        raise RuntimeError("Agency photo browsing is unavailable in cloud-off mode.")
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        raise RuntimeError("Agency photo browsing is unavailable in cloud-off mode.")
    from ..adapters.cloud.config import load_cloud_config_from_env
    config = load_cloud_config_from_env()
    agency_name = _agency_segment(agency)
    roots: list[_BrowseRoot] = []
    try:
        company_gateway = GraphDriveGateway.from_active_cloud(config, library_names=(
            config.company_library_name,
            config.company_library_internal_name,
            config.exports_library_name,
            config.exports_library_internal_name,
        ))
        roots.append(_BrowseRoot(
            company_gateway,
            "/".join((config.company_vehicle_root.strip("/") or "Vehicle Project Database", agency_name)),
            "company_reference",
        ))
    except Exception:
        logger.info("Company reference library is unavailable")
    try:
        shop_gateway = GraphDriveGateway.from_active_cloud(config, library_names=(
            config.shop_library_name,
            config.shop_library_internal_name,
        ))
        roots.append(_BrowseRoot(
            shop_gateway,
            "/".join((config.shop_build_photos_root.strip("/") or "Shop Project Database", agency_name)),
            "shop_completed",
        ))
    except Exception:
        logger.info("Shop completed-photo library is unavailable")
    if not roots:
        raise RuntimeError("The Company/Shop photo libraries are not configured for this install.")
    return roots
