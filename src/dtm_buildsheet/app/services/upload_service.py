"""Durable, local-first project media uploads.

Browser-selected bytes are staged under the app workspace before any cloud
work starts.  SharePoint uploads therefore survive navigation, transient
provider failures, and process restarts.  HEIC/HEIF sources are normalized to
JPEG locally; the original Apple file is never uploaded to SharePoint.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from PIL import Image, ImageOps

from ...domain.project_models import BuildReferenceAsset, BuildReferenceAssignment
from ...inputs.project_entry import ProjectWriteConflict, load_project, save_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import (
    GraphDriveError,
    GraphDriveGateway,
    GraphUploadPaused,
)


logger = logging.getLogger(__name__)

_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
_FILE_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".zip",
}
_HEIF_SUFFIXES = {".heic", ".heif"}
_JPEG_NORMALIZE_SUFFIXES = _HEIF_SUFFIXES | {".webp"}
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024
_STAGE_CHUNK_BYTES = 1024 * 1024
_NONTERMINAL = {
    "awaiting_file", "staging", "queued", "converting", "waiting",
    "uploading", "verifying", "integrating",
}
_ACTIVE_PHASES = {"converting", "uploading", "verifying", "integrating"}
_JOB_LOCK = threading.RLock()
_HEIF_LOCK = threading.Lock()
_HEIF_REGISTERED = False
_CANCEL_EVENTS: dict[str, threading.Event] = {}


class _UploadCanceled(Exception):
    """Internal signal used when a user cancels local staging."""


class _StopSignal:
    """Combine app shutdown and per-job cancellation for Graph streaming."""

    def __init__(self, *events: threading.Event):
        self._events = events

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)


def _cancel_event(job_id: str) -> threading.Event:
    with _JOB_LOCK:
        return _CANCEL_EVENTS.setdefault(job_id, threading.Event())


def _clear_cancel_event(job_id: str) -> None:
    with _JOB_LOCK:
        _CANCEL_EVENTS.pop(job_id, None)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root(paths: AppPaths) -> Path:
    return paths.workspace_uploads_dir


def _jobs_dir(paths: AppPaths) -> Path:
    return _root(paths) / "jobs"


def _staging_dir(paths: AppPaths) -> Path:
    return _root(paths) / "staging"


def _job_path(paths: AppPaths, job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", str(job_id or "")):
        raise ValueError("Invalid upload job ID")
    return _jobs_dir(paths) / f"{job_id}.json"


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
    temporary.replace(path)


def _load_job(paths: AppPaths, job_id: str) -> dict:
    path = _job_path(paths, job_id)
    try:
        payload = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError("Upload job not found") from None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        raise ValueError("Upload job state is unreadable") from None
    if not isinstance(payload, dict) or payload.get("job_id") != job_id:
        raise ValueError("Upload job state is invalid")
    return payload


def _save_job(paths: AppPaths, job: dict) -> None:
    job["updated_at"] = _utcnow()
    _atomic_write(_job_path(paths, str(job["job_id"])), job)


def _update_job(paths: AppPaths, job_id: str, **changes) -> dict:
    with _JOB_LOCK:
        job = _load_job(paths, job_id)
        job.update(changes)
        _save_job(paths, job)
        return job


def _safe_file_name(value: str) -> str:
    name = PurePosixPath(str(value or "").replace("\\", "/")).name.strip(" .")
    if not name or name in {".", ".."}:
        raise ValueError("A valid filename is required")
    cleaned = re.sub(r'[~"#%*:<>?/\\|]+', "_", name).strip(" .")
    if not cleaned:
        raise ValueError("A valid filename is required")
    return cleaned[:180]


def _media_type(file_name: str) -> str:
    suffix = PurePosixPath(file_name).suffix.casefold()
    if suffix in _PHOTO_SUFFIXES:
        return "photo"
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    if suffix in _FILE_SUFFIXES:
        return "file"
    raise ValueError(
        "Unsupported file type. Upload photos, videos, PDFs, Office documents, text, CSV, or ZIP files."
    )


def _resolve_vehicle(project, unit_id: str, individual_id: str):
    unit = next((item for item in project.build_units if item.unit_id == unit_id), None)
    if unit is None:
        raise ValueError("The upload destination unit no longer exists")
    if individual_id:
        individual = next(
            (item for item in unit.individuals if item.individual_id == individual_id),
            None,
        )
        if individual is None:
            raise ValueError("The upload destination vehicle no longer exists")
        return unit, individual
    if unit.individuals:
        raise ValueError("Choose one vehicle before uploading completed media")
    return unit, unit


def create_upload_job(paths: AppPaths, body: dict, *, destination_kind: str) -> dict:
    project_id = str(body.get("project_id") or "").strip()
    project = load_project(project_id, paths)
    if project.project_status == "inactive":
        raise ValueError("Reactivate this project before uploading files")
    if destination_kind == "project" and project.project_status == "completed":
        raise ValueError("Reopen this project before uploading project media")
    original_name = _safe_file_name(str(body.get("file_name") or ""))
    media_type = _media_type(original_name)
    try:
        source_size = int(body.get("file_size") or 0)
    except (TypeError, ValueError):
        source_size = 0
    if source_size <= 0:
        raise ValueError("Empty files cannot be uploaded")
    if source_size > _MAX_UPLOAD_BYTES:
        raise ValueError("This file exceeds the 5 GB app upload limit")

    unit_id = str(body.get("unit_id") or "").strip()
    individual_id = str(body.get("individual_id") or "").strip()
    if destination_kind == "completed":
        if not unit_id:
            raise ValueError("Choose one vehicle before uploading completed media")
        _resolve_vehicle(project, unit_id, individual_id)

    job_id = uuid.uuid4().hex
    suffix = PurePosixPath(original_name).suffix.casefold()
    staged_path = _staging_dir(paths) / f"{job_id}{suffix}"
    job = {
        "schema_version": 1,
        "job_id": job_id,
        "project_id": project_id,
        "destination_kind": destination_kind,
        "unit_id": unit_id,
        "individual_id": individual_id,
        "original_name": original_name,
        "stored_name": original_name,
        "media_type": media_type,
        "content_type": str(body.get("content_type") or "application/octet-stream")[:160],
        "source_size": source_size,
        "upload_size": source_size,
        "bytes_staged": 0,
        "bytes_uploaded": 0,
        "sha256": "",
        "status": "awaiting_file",
        "phase": "Waiting for local file",
        "error": "",
        "attempts": 0,
        "next_retry_at": 0.0,
        "staged_path": str(staged_path),
        "upload_path": str(staged_path),
        "converted_from": "",
        "remote_path": "",
        "source_drive_id": "",
        "source_item_id": "",
        "source_web_url": "",
        "source_etag": "",
        "reference_id": "",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
        "completed_at": "",
        "acknowledged_at": "",
    }
    with _JOB_LOCK:
        _staging_dir(paths).mkdir(parents=True, exist_ok=True)
        _save_job(paths, job)
    return public_job(job)


def stage_upload_content(
    paths: AppPaths,
    job_id: str,
    source: BinaryIO,
    content_length: int,
) -> dict:
    cancel_event = _cancel_event(job_id)
    with _JOB_LOCK:
        job = _load_job(paths, job_id)
        if job.get("status") != "awaiting_file":
            raise ValueError("This upload is no longer waiting for file content")
        if content_length != int(job.get("source_size") or 0):
            raise ValueError("The selected file size changed before staging")
        free = shutil.disk_usage(_root(paths).parent).free
        if free < content_length + 128 * 1024 * 1024:
            raise ValueError("There is not enough local disk space to stage this upload")
        job.update(status="staging", phase="Copying into safe local staging", error="")
        _save_job(paths, job)

    final_path = Path(job["staged_path"])
    partial_path = final_path.with_suffix(final_path.suffix + ".part")
    digest = hashlib.sha256()
    written = 0
    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with partial_path.open("wb") as destination:
            while written < content_length:
                if cancel_event.is_set():
                    raise _UploadCanceled("Upload canceled")
                block = source.read(min(_STAGE_CHUNK_BYTES, content_length - written))
                if not block:
                    break
                destination.write(block)
                digest.update(block)
                written += len(block)
                if written == content_length or written % (8 * _STAGE_CHUNK_BYTES) == 0:
                    _update_job(paths, job_id, bytes_staged=written)
        if written != content_length:
            raise ValueError("The local file transfer ended before all bytes were received")
        partial_path.replace(final_path)
        queued = _update_job(
            paths,
            job_id,
            status="queued",
            phase="Queued for SharePoint",
            bytes_staged=written,
            sha256=digest.hexdigest(),
            error="",
        )
    except _UploadCanceled:
        partial_path.unlink(missing_ok=True)
        canceled = _update_job(
            paths, job_id, status="canceled", phase="Canceled", error="",
        )
        _clear_cancel_event(job_id)
        return public_job(canceled)
    except Exception as exc:
        partial_path.unlink(missing_ok=True)
        _update_job(paths, job_id, status="failed", phase="Staging failed", error=str(exc))
        raise
    start_upload_manager(paths)
    _manager_for(paths).wake()
    return public_job(queued)


def _register_heif() -> None:
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return
    with _HEIF_LOCK:
        if _HEIF_REGISTERED:
            return
        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            raise RuntimeError("HEIC conversion support is not installed") from None
        register_heif_opener(thumbnails=False)
        _HEIF_REGISTERED = True


def _prepare_upload_file(paths: AppPaths, job: dict) -> tuple[Path, dict]:
    source = Path(str(job.get("staged_path") or ""))
    if not source.is_file():
        raise FileNotFoundError("The staged source file is missing")
    suffix = source.suffix.casefold()
    if job.get("media_type") == "photo":
        if suffix in _HEIF_SUFFIXES:
            _register_heif()
        try:
            with Image.open(source) as opened:
                opened.verify()
        except Exception:
            raise ValueError(f"{job.get('original_name') or 'Photo'} is not a readable image") from None
    if suffix not in _JPEG_NORMALIZE_SUFFIXES:
        return source, job

    converted = _staging_dir(paths) / f"{job['job_id']}.jpg"
    temporary = converted.with_suffix(".jpg.part")
    with Image.open(source) as opened:
        normalized = ImageOps.exif_transpose(opened)
        if normalized.mode != "RGB":
            background = Image.new("RGB", normalized.size, "white")
            if "A" in normalized.getbands():
                background.paste(normalized, mask=normalized.getchannel("A"))
            else:
                background.paste(normalized.convert("RGB"))
            normalized = background
        normalized.save(temporary, "JPEG", quality=92, optimize=True, progressive=True)
    with Image.open(temporary) as check:
        check.verify()
    temporary.replace(converted)
    stored_name = f"{PurePosixPath(str(job['original_name'])).stem}.jpg"
    job = _update_job(
        paths,
        str(job["job_id"]),
        stored_name=stored_name,
        upload_path=str(converted),
        upload_size=converted.stat().st_size,
        converted_from=suffix.lstrip(".").upper(),
        bytes_uploaded=0,
    )
    return converted, job


def _destination(project, job: dict) -> tuple[str, str]:
    media_type = str(job.get("media_type") or "file")
    if job.get("destination_kind") == "project":
        base = str(project.company_year_folder_path or "").strip("/")
        if not base:
            raise ValueError("The project Company folder is not provisioned yet")
        folder = "Reference Photos & Videos" if media_type in {"photo", "video"} else "Project Files"
        return "company", f"{base}/{folder}"

    unit, holder = _resolve_vehicle(
        project,
        str(job.get("unit_id") or ""),
        str(job.get("individual_id") or ""),
    )
    del unit
    base = str(getattr(holder, "shop_vehicle_folder_path", "") or "").strip("/")
    if not base:
        raise ValueError("The vehicle Shop folder is not provisioned yet")
    folder = "Completed Build Photos" if media_type in {"photo", "video"} else "Technician Files"
    return "shop", f"{base}/{folder}"


def _gateway_for(library: str) -> GraphDriveGateway:
    from ..adapters.cloud.config import load_cloud_config_from_env

    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        raise GraphDriveError("Cloud mode is disabled")
    bundle = wiring.get_active_bundle()
    if not bundle.identity.is_signed_in():
        raise GraphDriveError("Sign in to Microsoft 365 to continue uploading")
    config = load_cloud_config_from_env()
    names = (
        (config.company_library_name, config.company_library_internal_name,
         config.exports_library_name, config.exports_library_internal_name)
        if library == "company"
        else (config.shop_library_name, config.shop_library_internal_name)
    )
    return GraphDriveGateway.from_active_cloud(
        config,
        library_names=tuple(name for name in names if name),
    )


def _unique_remote_path(gateway: GraphDriveGateway, folder: str, file_name: str) -> str:
    safe_name = _safe_file_name(file_name)
    stem = PurePosixPath(safe_name).stem
    suffix = PurePosixPath(safe_name).suffix
    for serial in range(1, 1001):
        candidate_name = safe_name if serial == 1 else f"{stem} ({serial}){suffix}"
        candidate = f"{folder.strip('/')}/{candidate_name}"
        if gateway.get_item_by_path(candidate, timeout_seconds=15) is None:
            return candidate
    raise ValueError("Too many files with the same name exist in the destination folder")


def _integrate_project_asset(paths: AppPaths, job: dict) -> str:
    if job.get("destination_kind") != "project":
        return ""
    project = load_project(str(job["project_id"]), paths)
    source_item_id = str(job.get("source_item_id") or "")
    existing = next(
        (asset for asset in project.reference_assets if asset.source_item_id == source_item_id),
        None,
    )
    if existing is not None:
        return existing.reference_id
    reference_id = str(job.get("reference_id") or "") or uuid.uuid4().hex
    assignments = []
    unit_id = str(job.get("unit_id") or "")
    if unit_id and job.get("media_type") == "photo":
        assignments.append(BuildReferenceAssignment(scope="unit_group", target_id=unit_id))
    project.reference_assets.append(BuildReferenceAsset(
        reference_id=reference_id,
        file_name=str(job.get("stored_name") or ""),
        media_type=str(job.get("media_type") or "file"),
        source_kind=(
            "company_reference"
            if job.get("media_type") in {"photo", "video"}
            else "company_project_file"
        ),
        source_drive_id=str(job.get("source_drive_id") or ""),
        source_item_id=source_item_id,
        source_path=str(job.get("remote_path") or ""),
        source_web_url=str(job.get("source_web_url") or ""),
        source_etag=str(job.get("source_etag") or ""),
        source_size=int(job.get("upload_size") or 0),
        assignments=assignments,
    ))
    save_project(project, paths)
    return reference_id


def _cleanup_staged_files(job: dict) -> None:
    for key in ("staged_path", "upload_path"):
        raw = str(job.get(key) or "")
        if raw:
            try:
                Path(raw).unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not remove completed upload staging file", exc_info=True)


def process_upload_job(
    paths: AppPaths,
    job_id: str,
    *,
    stop_event: threading.Event | None = None,
) -> dict:
    stop_event = stop_event or threading.Event()
    cancel_event = _cancel_event(job_id)
    stop_signal = _StopSignal(stop_event, cancel_event)
    try:
        job = _load_job(paths, job_id)
        if job.get("status") not in {"queued", "waiting", *_ACTIVE_PHASES}:
            return job
        if cancel_event.is_set() or job.get("status") == "canceled":
            return job
        if stop_event.is_set():
            return _update_job(paths, job_id, status="queued", phase="Paused")

        upload_path = Path(str(job.get("upload_path") or ""))
        if not job.get("source_item_id"):
            if not job.get("converted_from") and upload_path.suffix.casefold() in _JPEG_NORMALIZE_SUFFIXES:
                job = _update_job(paths, job_id, status="converting", phase="Converting to JPG", error="")
                upload_path, job = _prepare_upload_file(paths, job)
            else:
                upload_path, job = _prepare_upload_file(paths, job)
            if cancel_event.is_set():
                canceled = _update_job(paths, job_id, status="canceled", phase="Canceled")
                _cleanup_staged_files(canceled)
                return canceled
            project = load_project(str(job["project_id"]), paths)
            library, folder = _destination(project, job)
            gateway = _gateway_for(library)
            gateway.ensure_folder(folder)
            remote_path = str(job.get("remote_path") or "")
            recovered_item = None
            if remote_path:
                candidate = gateway.get_item_by_path(remote_path, timeout_seconds=15)
                if candidate is not None:
                    expected_size = int(job.get("upload_size") or upload_path.stat().st_size)
                    try:
                        candidate_size = int(candidate.get("size") or 0)
                    except (TypeError, ValueError):
                        candidate_size = 0
                    if candidate_size == expected_size:
                        recovered_item = candidate
                    else:
                        remote_path = ""
            if not remote_path:
                remote_path = _unique_remote_path(gateway, folder, str(job["stored_name"]))
                job = _update_job(paths, job_id, remote_path=remote_path)
            if recovered_item is None:
                job = _update_job(
                    paths,
                    job_id,
                    status="uploading",
                    phase="Uploading to SharePoint",
                    attempts=int(job.get("attempts") or 0) + 1,
                    error="",
                )

                def progress(uploaded: int, total: int) -> None:
                    if cancel_event.is_set():
                        return
                    _update_job(
                        paths, job_id, bytes_uploaded=uploaded, upload_size=total,
                        phase="Uploading to SharePoint",
                    )

                item = gateway.upload_local_file(
                    remote_path,
                    upload_path,
                    progress=progress,
                    stop_event=stop_signal,
                    conflict_behavior="fail",
                )
            else:
                item = recovered_item
            if cancel_event.is_set():
                item_id = str(item.get("id") or "")
                if item_id:
                    try:
                        gateway.delete_item(item_id)
                    except GraphDriveError:
                        logger.warning(
                            "Could not remove SharePoint item after upload cancellation",
                            exc_info=True,
                        )
                canceled = _update_job(paths, job_id, status="canceled", phase="Canceled")
                _cleanup_staged_files(canceled)
                return canceled
            item_name = str(item.get("name") or PurePosixPath(remote_path).name)
            if item_name != PurePosixPath(remote_path).name:
                remote_path = f"{PurePosixPath(remote_path).parent.as_posix()}/{item_name}"
            job = _update_job(
                paths,
                job_id,
                status="verifying",
                phase="Verifying SharePoint file",
                remote_path=remote_path,
                source_drive_id=gateway.drive_id,
                source_item_id=str(item.get("id") or ""),
                source_web_url=str(item.get("webUrl") or ""),
                source_etag=str(item.get("eTag") or item.get("@odata.etag") or ""),
                bytes_uploaded=int(job.get("upload_size") or upload_path.stat().st_size),
            )
            if not job.get("source_item_id"):
                raise GraphDriveError("SharePoint did not return a durable file identity")

        job = _update_job(paths, job_id, status="integrating", phase="Adding to project")
        reference_id = _integrate_project_asset(paths, job)
        job = _update_job(
            paths,
            job_id,
            status="complete",
            phase="Complete",
            reference_id=reference_id,
            completed_at=_utcnow(),
            acknowledged_at="",
            error="",
        )
        if job.get("destination_kind") == "completed":
            from .photo_gallery_service import invalidate_completed_gallery

            invalidate_completed_gallery()
        _cleanup_staged_files(job)
        _clear_cancel_event(job_id)
        return job
    except GraphUploadPaused:
        if cancel_event.is_set():
            job = _update_job(paths, job_id, status="canceled", phase="Canceled", error="")
            _cleanup_staged_files(job)
            _clear_cancel_event(job_id)
            return job
        return _update_job(paths, job_id, status="queued", phase="Paused", error="")
    except GraphDriveError as exc:
        job = _load_job(paths, job_id)
        delay = min(300, max(5, 5 * (2 ** min(int(job.get("attempts") or 0), 6))))
        conflict = "409" in str(exc) or "namealreadyexists" in str(exc).casefold()
        return _update_job(
            paths,
            job_id,
            status="waiting",
            phase="Waiting to retry",
            error=str(exc),
            next_retry_at=time.time() + delay,
            remote_path="" if conflict else str(job.get("remote_path") or ""),
        )
    except ProjectWriteConflict:
        return _update_job(
            paths,
            job_id,
            status="waiting",
            phase="Project changed; waiting to retry",
            error="The project changed while the upload finished. Retrying safely.",
            next_retry_at=time.time() + 2,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _update_job(paths, job_id, status="failed", phase="Needs attention", error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        logger.exception("Unexpected upload failure for %s", job_id)
        return _update_job(
            paths,
            job_id,
            status="failed",
            phase="Needs attention",
            error=f"Unexpected upload failure ({type(exc).__name__})",
        )


def public_job(job: dict) -> dict:
    public = {
        key: value for key, value in job.items()
        if key not in {"staged_path", "upload_path", "sha256"}
    }
    total = max(1, int(job.get("upload_size") or job.get("source_size") or 1))
    uploaded = int(job.get("bytes_uploaded") or 0)
    public["progress_percent"] = min(100, round(uploaded * 100 / total, 1))
    public["can_retry"] = bool(
        job.get("source_item_id")
        or Path(str(job.get("upload_path") or job.get("staged_path") or "")).is_file()
    )
    return public


def list_upload_jobs(paths: AppPaths) -> dict:
    jobs = []
    directory = _jobs_dir(paths)
    if directory.exists():
        for path in directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text("utf-8"))
                if isinstance(payload, dict):
                    jobs.append(public_job(payload))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                logger.warning("Ignoring unreadable upload job %s", path)
    jobs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    active = [item for item in jobs if item.get("status") in _NONTERMINAL]
    unacknowledged_complete = [
        item for item in jobs
        if item.get("status") == "complete" and not item.get("acknowledged_at")
    ]
    return {
        "ok": True,
        "jobs": jobs[:100],
        "active_count": len(active),
        "uploading_count": sum(item.get("status") in _ACTIVE_PHASES for item in active),
        "needs_attention_count": sum(item.get("status") == "failed" for item in jobs),
        "unacknowledged_complete_count": len(unacknowledged_complete),
    }


def acknowledge_completed_uploads(paths: AppPaths) -> dict:
    """Persist that terminal upload notifications have been seen."""

    acknowledged_at = _utcnow()
    acknowledged = 0
    directory = _jobs_dir(paths)
    if directory.exists():
        with _JOB_LOCK:
            for path in directory.glob("*.json"):
                try:
                    job = json.loads(path.read_text("utf-8"))
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    continue
                if (
                    not isinstance(job, dict)
                    or job.get("status") not in {"complete", "canceled"}
                    or job.get("acknowledged_at")
                ):
                    continue
                job["acknowledged_at"] = acknowledged_at
                job["updated_at"] = acknowledged_at
                _atomic_write(path, job)
                acknowledged += 1
    return {"ok": True, "acknowledged": acknowledged}


def has_active_uploads(paths: AppPaths) -> bool:
    return bool(list_upload_jobs(paths)["active_count"])


def upload_job_destination(paths: AppPaths, job_id: str) -> str:
    return str(_load_job(paths, job_id).get("destination_kind") or "")


def retry_upload(paths: AppPaths, job_id: str) -> dict:
    job = _load_job(paths, job_id)
    if job.get("status") not in {"failed", "waiting", "queued"}:
        raise ValueError("Only waiting or failed uploads can be retried")
    if not Path(str(job.get("upload_path") or job.get("staged_path") or "")).is_file() and not job.get("source_item_id"):
        raise ValueError("The staged source file is no longer available")
    _clear_cancel_event(job_id)
    job = _update_job(
        paths, job_id, status="queued", phase="Queued for SharePoint",
        error="", next_retry_at=0.0,
    )
    start_upload_manager(paths)
    _manager_for(paths).wake()
    return public_job(job)


def cancel_upload(paths: AppPaths, job_id: str) -> dict:
    job = _load_job(paths, job_id)
    if job.get("status") == "complete":
        raise ValueError("Completed uploads cannot be canceled")
    _cancel_event(job_id).set()
    job = _update_job(paths, job_id, status="canceled", phase="Canceled", error="")
    _cleanup_staged_files(job)
    return public_job(job)


class _UploadManager:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.stop_event = threading.Event()
        self.condition = threading.Condition()
        self.workers: dict[str, threading.Thread] = {}
        self.thread = threading.Thread(
            target=self._run,
            name="dtm-upload-coordinator",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def wake(self) -> None:
        with self.condition:
            self.condition.notify_all()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self._schedule_ready()
            with self.condition:
                self.condition.wait(timeout=2.0)

    def _schedule_ready(self) -> None:
        with _JOB_LOCK:
            for job_id, worker in list(self.workers.items()):
                if not worker.is_alive():
                    self.workers.pop(job_id, None)
            available = 2 - len(self.workers)
            if available <= 0:
                return
            status = list_upload_jobs(self.paths)
            now = time.time()
            candidates = [
                item for item in reversed(status["jobs"])
                if item.get("status") == "queued"
                or (
                    item.get("status") == "waiting"
                    and float(item.get("next_retry_at") or 0) <= now
                )
            ]
            for job in candidates[:available]:
                job_id = str(job["job_id"])
                if job_id in self.workers:
                    continue
                worker = threading.Thread(
                    target=process_upload_job,
                    args=(self.paths, job_id),
                    kwargs={"stop_event": self.stop_event},
                    name=f"dtm-upload-{job_id[:8]}",
                    daemon=True,
                )
                self.workers[job_id] = worker
                worker.start()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.wake()


_MANAGERS: dict[str, _UploadManager] = {}
_MANAGER_LOCK = threading.Lock()


def _manager_key(paths: AppPaths) -> str:
    return str(paths.workspace_uploads_dir.resolve())


def _manager_for(paths: AppPaths) -> _UploadManager:
    key = _manager_key(paths)
    with _MANAGER_LOCK:
        manager = _MANAGERS.get(key)
        if manager is None or manager.stop_event.is_set():
            manager = _UploadManager(paths)
            _MANAGERS[key] = manager
            manager.start()
        return manager


def start_upload_manager(paths: AppPaths) -> None:
    directory = _jobs_dir(paths)
    if directory.exists():
        with _JOB_LOCK:
            for path in directory.glob("*.json"):
                try:
                    job = json.loads(path.read_text("utf-8"))
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    continue
                status = str(job.get("status") or "")
                if status == "staging":
                    expected = int(job.get("source_size") or 0)
                    staged = Path(str(job.get("staged_path") or ""))
                    partial = staged.with_suffix(staged.suffix + ".part")
                    candidate = staged if staged.is_file() else partial
                    if expected > 0 and candidate.is_file() and candidate.stat().st_size == expected:
                        if candidate == partial:
                            partial.replace(staged)
                        digest = hashlib.sha256()
                        with staged.open("rb") as source:
                            for block in iter(lambda: source.read(_STAGE_CHUNK_BYTES), b""):
                                digest.update(block)
                        job.update(
                            status="queued",
                            phase="Resuming after restart",
                            bytes_staged=expected,
                            sha256=digest.hexdigest(),
                            error="",
                        )
                    else:
                        partial.unlink(missing_ok=True)
                        job.update(
                            status="failed",
                            phase="Local copy was interrupted",
                            error="Select the source file again to start a new upload.",
                        )
                    _atomic_write(path, job)
                elif status == "awaiting_file":
                    job.update(
                        status="failed",
                        phase="Local copy was interrupted",
                        error="Select the source file again to start a new upload.",
                    )
                    _atomic_write(path, job)
                elif status in _ACTIVE_PHASES:
                    job["status"] = "queued"
                    job["phase"] = "Resuming after restart"
                    _atomic_write(path, job)
    _manager_for(paths).wake()


def shutdown_upload_manager(paths: AppPaths) -> None:
    key = _manager_key(paths)
    with _MANAGER_LOCK:
        manager = _MANAGERS.pop(key, None)
    if manager is not None:
        manager.shutdown()
