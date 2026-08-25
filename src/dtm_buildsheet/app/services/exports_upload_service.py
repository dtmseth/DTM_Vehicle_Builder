"""Upload generated build artifacts to the company SharePoint library.

Customer-ready PDFs stay in the agency/year folder that the Builds UI opens.
Editable PowerPoint sources live under a deliberately separate internal tree,
which makes them much harder to mistake for customer deliverables while still
allowing another Builder workstation to hydrate and edit them.

Triggered from generation_service immediately after a successful local
write. Runs in a background thread so the generate response returns
fast; the cloud chip's spinner reflects the upload-in-progress state
via the same data_version mechanism that drives the project-list
auto-refresh.

Path layout in the target library (configurable via cloud_config.json):

    {exports_base_folder}/{agency}/{year}/{stable filename}.pdf
    {exports_base_folder}/_DTM Internal PowerPoint Sources/{agency}/{year}/{stable filename}.pptx

Sanitization is deliberate — agency names commonly have apostrophes,
slashes, and casing inconsistencies that SharePoint would reject or
normalize unpredictably. We collapse to a safe ASCII form and use that
for the folder name only; the file content is untouched.

Errors never propagate. A failed upload is logged + toasted; the local
copy stays untouched as the canonical reference. No automatic retry —
the operator can re-generate to retry.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

from ..adapters import wiring

logger = logging.getLogger(__name__)


# Graph upload sessions allow up to ~60 MiB per chunk. 4 MiB is the
# documented threshold below which simple PUT works; above that, sessions
# are required. We use ~10 MiB chunks — large enough to be efficient on
# typical connections, small enough that a single retry doesn't waste
# minutes of upload bandwidth on a flaky link.
_UPLOAD_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB
_GRAPH = "https://graph.microsoft.com/v1.0"
_MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024
_EXPORT_SUFFIXES = {".pdf", ".pptx"}
_INTERNAL_PPTX_FOLDER = "_DTM Internal PowerPoint Sources"
_EXPORT_TIMESTAMP = re.compile(
    r"_(?:[A-Z][a-z]{2}\d+_\d{4}_\d+-\d+(?:-\d+)?[AP]M|\d{8}_\d{6})$"
)

# Uploads run in background threads and the outbound queue can retry at the
# same time as an operator chooses Replace. Serialize the remote mutation and
# re-check source existence under this lock so a delayed retry cannot resurrect
# a version that cleanup just removed.
_remote_exports_lock = threading.RLock()

# Memoized drive_id lookup so we don't re-list /sites/{site_id}/drives on
# every export. Cleared by reset_cache() during tests.
_drive_id_cache: dict[str, str] = {}
_drive_id_lock = threading.Lock()


def reset_cache() -> None:
    """Forget the memoized drive_id. Used by tests."""
    with _drive_id_lock:
        _drive_id_cache.clear()


def _sanitize_segment(value: str) -> str:
    """Collapse a string to a SharePoint-friendly folder/file name segment.

    SharePoint rejects ~"#%*<>?/\\|: and trims trailing dots/spaces. Rather
    than maintaining a full block-list we restrict to a conservative
    allowlist of letters, digits, spaces, hyphens, underscores, and dots,
    then trim. Empty results become 'Unassigned' so an empty-agency
    project still has a home.
    """
    cleaned = re.sub(r"[^A-Za-z0-9 _.\-]+", " ", value).strip(" .")
    return cleaned or "Unassigned"


def portable_export_filename(value: str) -> str:
    """Return a basename from a path saved by macOS, Windows, or Linux."""
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()


def stable_export_stem(value: str) -> str:
    """Return the vehicle-specific portion of a timestamped export name."""
    return _EXPORT_TIMESTAMP.sub("", Path(portable_export_filename(value)).stem)


def canonical_export_filename(value: str) -> str:
    """Return the deterministic SharePoint filename for a local export.

    Local files keep timestamps so PowerPoint editing and crash recovery remain
    safe. SharePoint gets one stable filename per vehicle/artifact type, letting
    Graph's replace behavior provide a second line of defense against duplicate
    versions even when cleanup is interrupted.
    """
    safe_name = portable_export_filename(value)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _EXPORT_SUFFIXES:
        return safe_name
    return f"{stable_export_stem(safe_name)}{suffix}"


def _remote_export_folder_path(
    config, *, agency: str, year: str, suffix: str, legacy: bool = False,
) -> str:
    base = (config.exports_base_folder or "").strip().strip("/")
    segments = [base] if base else []
    if suffix.lower() == ".pptx" and not legacy:
        segments.append(_INTERNAL_PPTX_FOLDER)
    segments.extend((
        _sanitize_segment(agency),
        _sanitize_segment(year or "Unassigned"),
    ))
    return "/".join(segment for segment in segments if segment)


def _remote_export_path(
    config, *, agency: str, year: str, filename: str,
    legacy: bool = False, canonicalize: bool = True,
) -> str:
    safe_name = portable_export_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    folder = _remote_export_folder_path(
        config, agency=agency, year=year, suffix=suffix, legacy=legacy,
    )
    remote_name = canonical_export_filename(safe_name) if canonicalize else safe_name
    return "/".join(segment for segment in (folder, remote_name) if segment)


def _bundle_or_none(*, log_reason: bool = False):
    """Return the active cloud bundle, or None when uploads should skip.

    When ``log_reason`` is True, the reason for skipping is logged at INFO
    level so a quiet skip can still be diagnosed from the log."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return None
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        if log_reason:
            logger.info("Export upload skipped: cloud mode is disabled")
        return None
    try:
        bundle = wiring.get_active_bundle()
    except Exception:
        logger.exception("Could not get active bundle for export upload")
        return None
    try:
        if not bundle.identity.is_signed_in():
            if log_reason:
                logger.info("Export upload skipped: no signed-in Microsoft account")
            return None
    except Exception:
        logger.exception("is_signed_in check failed during export upload")
        return None
    return bundle


def _exports_target_configured() -> bool:
    """Return True when cloud_config.json defines an exports library.

    Used by the background worker to decide whether enqueueing a retry can
    ever succeed. When False, the upload is permanently disabled for this
    install and queueing would just thrash the drain loop forever."""
    try:
        from ..adapters.cloud.config import load_cloud_config_from_env
        return load_cloud_config_from_env().exports_enabled
    except Exception:
        return False


def _get_export_drive_id(bundle, config) -> Optional[str]:
    """Look up the SharePoint library drive_id by display name.

    First call hits Graph at /sites/{site_id}/drives; the result is cached
    per-config (keyed by site_id + library names) so subsequent exports
    are free. Returns None when the configured library isn't found —
    callers treat that as "uploads disabled for this run".
    """
    cache_key = (
        f"{config.sharepoint_site_id}|"
        f"{config.exports_library_name}|"
        f"{config.exports_library_internal_name}"
    )
    with _drive_id_lock:
        cached = _drive_id_cache.get(cache_key)
    if cached:
        return cached

    # Need to hit Graph. Reuse the bundle's MSAL token. We don't have a
    # direct API for this on the storage adapter so go through the bundle's
    # token_provider indirectly by inspecting the storage attribute. The
    # SharePointGraphProvider exposes its token_provider closure as
    # _token_provider; cheaper than threading a new method through the
    # whole abstract.
    storage = bundle.storage
    token_provider = getattr(storage, "_token_provider", None)
    if token_provider is None:
        logger.warning("Active storage adapter has no token provider; can't resolve exports drive")
        return None
    try:
        token = token_provider()
    except Exception:
        logger.exception("Token acquisition failed during exports drive lookup")
        return None

    url = f"{_GRAPH}/sites/{config.sharepoint_site_id}/drives"
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        resp.raise_for_status()
        drives = resp.json().get("value", [])
    except Exception:
        logger.exception("Could not list drives on site %s", config.sharepoint_site_id)
        return None

    candidates = {
        config.exports_library_name.strip().lower(),
        config.exports_library_internal_name.strip().lower(),
    } - {""}
    for drive in drives:
        name = str(drive.get("name", "")).strip().lower()
        if name and name in candidates:
            drive_id = str(drive.get("id", ""))
            if drive_id:
                with _drive_id_lock:
                    _drive_id_cache[cache_key] = drive_id
                logger.info(
                    "Resolved exports library %r to drive_id %s",
                    drive.get("name"), drive_id[:12] + "…",
                )
                return drive_id
    logger.warning(
        "Could not find an exports library matching %r / %r on site %s",
        config.exports_library_name, config.exports_library_internal_name,
        config.sharepoint_site_id,
    )
    return None


def _upload_via_session(token: str, drive_id: str, remote_path: str, data: bytes) -> bool:
    """Upload large bytes to /drives/{drive_id}/root:{remote_path} using a
    Graph upload session. Returns True on success.

    Path needs a leading slash; we make sure. Failures are logged with
    enough context to debug from the workflow logs.
    """
    remote_path = "/" + remote_path.lstrip("/")
    create_url = f"{_GRAPH}/drives/{drive_id}/root:{remote_path}:/createUploadSession"
    try:
        resp = requests.post(
            create_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
            timeout=30,
        )
        resp.raise_for_status()
        upload_url = resp.json()["uploadUrl"]
    except Exception:
        logger.exception("Could not create upload session for %s", remote_path)
        return False

    total = len(data)
    for offset in range(0, total, _UPLOAD_CHUNK_SIZE):
        chunk = data[offset:offset + _UPLOAD_CHUNK_SIZE]
        last = offset + len(chunk) - 1
        range_header = f"bytes {offset}-{last}/{total}"
        try:
            chunk_resp = requests.put(
                upload_url,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": range_header,
                },
                data=chunk,
                timeout=120,
            )
            # 202 = chunk accepted, 200/201 = final chunk written.
            if chunk_resp.status_code not in (200, 201, 202):
                logger.error(
                    "Upload chunk %s failed for %s: HTTP %d",
                    range_header, remote_path, chunk_resp.status_code,
                )
                return False
        except Exception:
            logger.exception("Upload chunk %s raised for %s", range_header, remote_path)
            return False

    logger.info("Uploaded export %s (%d bytes)", remote_path, total)
    return True


def upload_export(
    local_pptx: Path,
    *,
    agency: str,
    year: str,
    filename: Optional[str] = None,
    canonicalize: bool = True,
) -> bool:
    """Synchronous upload entry point. Returns True on success.

    ``year`` is the project's build year; falls back to "Unassigned" when
    empty so the file still lands somewhere instead of failing. ``filename``
    defaults to the local file's name.
    """
    bundle = _bundle_or_none(log_reason=True)
    if bundle is None:
        return False
    if not local_pptx.exists():
        logger.warning("Export upload skipped — local file missing: %s", local_pptx)
        return False

    # Late import — avoids a top-level dependency on the cloud config
    # module when this service is loaded outside cloud mode.
    from ..adapters.cloud.config import load_cloud_config_from_env

    try:
        config = load_cloud_config_from_env()
    except Exception:
        logger.exception("Could not load cloud config for export upload")
        return False
    if not config.exports_enabled:
        logger.info(
            "Export upload skipped: cloud_config.json has no exports_library_name. "
            "Add exports_library_name / exports_library_internal_name / exports_base_folder "
            "to %s to enable SharePoint auto-upload.",
            local_pptx.name,
        )
        return False  # not configured for this install

    drive_id = _get_export_drive_id(bundle, config)
    if not drive_id:
        return False

    token_provider = getattr(bundle.storage, "_token_provider", None)
    if token_provider is None:
        return False
    try:
        token = token_provider()
    except Exception:
        logger.exception("Token acquisition failed during export upload")
        return False

    remote_path = _remote_export_path(
        config,
        agency=agency,
        year=year,
        filename=filename or local_pptx.name,
        canonicalize=canonicalize,
    )

    with _remote_exports_lock:
        # Cleanup may have removed an obsolete local source while this worker
        # waited behind another upload. Do not let a stale queue/thread put it
        # back into SharePoint afterward.
        if not local_pptx.exists():
            logger.info("Export upload cancelled because the source was replaced: %s", local_pptx)
            return False
        try:
            data = local_pptx.read_bytes()
        except OSError:
            logger.exception("Could not read local export %s", local_pptx)
            return False

        return _upload_via_session(token, drive_id, remote_path, data)


def download_export(
    paths,
    *,
    source_path: str = "",
    filename: str = "",
    agency: str,
    year: str,
) -> dict:
    """Hydrate a shared export into this install's approved output folder.

    Project records are shared, but their historical absolute paths are not
    portable between computers. The portable identity is the export filename
    plus the same agency/year folder layout used by ``upload_export``.
    """
    safe_name = portable_export_filename(filename or source_path)
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or safe_name in {".", ".."} or suffix not in _EXPORT_SUFFIXES:
        return {"ok": False, "error": "invalid_shared_export"}

    bundle = _bundle_or_none(log_reason=True)
    if bundle is None:
        return {"ok": False, "error": "shared_exports_unavailable"}

    from ..adapters.cloud.config import load_cloud_config_from_env
    try:
        config = load_cloud_config_from_env()
    except Exception:
        logger.exception("Could not load cloud config for shared export download")
        return {"ok": False, "error": "shared_exports_unavailable"}
    if not config.exports_enabled:
        return {"ok": False, "error": "shared_exports_not_configured"}

    drive_id = _get_export_drive_id(bundle, config)
    token_provider = getattr(bundle.storage, "_token_provider", None)
    if not drive_id or token_provider is None:
        return {"ok": False, "error": "shared_exports_unavailable"}
    try:
        token = token_provider()
    except Exception:
        logger.exception("Token acquisition failed during shared export download")
        return {"ok": False, "error": "shared_exports_unavailable"}

    # New exports use a canonical filename, with PowerPoint sources separated
    # from customer PDFs. Fall back through the transitional paths so project
    # records created before this layout change remain portable.
    candidate_paths = [
        _remote_export_path(
            config, agency=agency, year=year, filename=safe_name,
            canonicalize=False,
        ),
        _remote_export_path(
            config, agency=agency, year=year, filename=safe_name,
        ),
    ]
    if suffix == ".pptx":
        candidate_paths.extend((
            _remote_export_path(
                config, agency=agency, year=year, filename=safe_name,
                legacy=True, canonicalize=False,
            ),
            _remote_export_path(
                config, agency=agency, year=year, filename=safe_name,
                legacy=True,
            ),
        ))
    candidate_paths = list(dict.fromkeys(candidate_paths))

    response = None
    for remote_path in candidate_paths:
        encoded_path = quote(remote_path, safe="/")
        url = f"{_GRAPH}/drives/{drive_id}/root:/{encoded_path}:/content"
        try:
            candidate_response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=120,
            )
        except Exception:
            logger.exception("Shared export download request failed")
            return {"ok": False, "error": "shared_export_download_failed"}
        if candidate_response.status_code == 404:
            continue
        response = candidate_response
        break
    if response is None:
        return {"ok": False, "error": "shared_export_not_found"}
    if response.status_code != 200:
        logger.warning("Shared export download failed: HTTP %s", response.status_code)
        return {"ok": False, "error": "shared_export_download_failed"}
    data = response.content
    if not data or len(data) > _MAX_DOWNLOAD_BYTES:
        return {"ok": False, "error": "shared_export_invalid"}
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        return {"ok": False, "error": "shared_export_invalid"}
    if suffix == ".pptx" and not data.startswith(b"PK"):
        return {"ok": False, "error": "shared_export_invalid"}

    target = paths.workspace_output_dir / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".download")
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
    except OSError:
        logger.exception("Could not save shared export into the local output folder")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "error": "shared_export_save_failed"}
    logger.info("Downloaded shared export %s", safe_name)
    return {"ok": True, "path": str(target), "downloaded": True}


def delete_shared_exports(
    *, agency: str, year: str, filenames: list[str],
    keep_filename: str = "", keep_filenames: list[str] | None = None,
) -> dict:
    """Delete prior versions from both the current and legacy folder layouts.

    The current canonical PPTX/PDF pair is protected by its full remote path,
    not merely by filename. That distinction lets cleanup remove a legacy
    public PPTX even when it has the same basename as the protected internal
    source.
    """
    requested_names = {
        portable_export_filename(name) for name in filenames
        if portable_export_filename(name)
        and Path(portable_export_filename(name)).suffix.lower() in _EXPORT_SUFFIXES
    }
    stable_stems = {stable_export_stem(name) for name in requested_names}
    if not requested_names:
        return {"ok": True, "deleted": [], "errors": []}
    bundle = _bundle_or_none(log_reason=True)
    if bundle is None:
        return {"ok": False, "deleted": [], "errors": ["shared_exports_unavailable"]}
    from ..adapters.cloud.config import load_cloud_config_from_env
    try:
        config = load_cloud_config_from_env()
        drive_id = _get_export_drive_id(bundle, config)
        token_provider = getattr(bundle.storage, "_token_provider", None)
        token = token_provider() if token_provider is not None else ""
    except Exception:
        logger.exception("Could not prepare shared export cleanup")
        return {"ok": False, "deleted": [], "errors": ["shared_export_delete_failed"]}
    if not config.exports_enabled or not drive_id or not token:
        return {"ok": False, "deleted": [], "errors": ["shared_exports_unavailable"]}

    keep_names = {
        portable_export_filename(name)
        for name in [keep_filename, *(keep_filenames or [])]
        if portable_export_filename(name)
        and Path(portable_export_filename(name)).suffix.lower() in _EXPORT_SUFFIXES
    }
    keep_paths = {
        _remote_export_path(
            config, agency=agency, year=year, filename=name,
        )
        for name in keep_names
    }

    public_folder = _remote_export_folder_path(
        config, agency=agency, year=year, suffix=".pdf",
    )
    internal_folder = _remote_export_folder_path(
        config, agency=agency, year=year, suffix=".pptx",
    )
    folder_specs = {
        public_folder: _EXPORT_SUFFIXES,        # PDF + legacy public PPTX
        internal_folder: {".pptx"},           # current PowerPoint sources
    }

    # Seed targets from the explicit project paths. Listing below broadens the
    # set to every timestamped version with the same stable vehicle identity.
    targets: dict[str, str] = {}
    for name in requested_names:
        suffix = Path(name).suffix.lower()
        candidates = {
            _remote_export_path(
                config, agency=agency, year=year, filename=name,
            ),
            _remote_export_path(
                config, agency=agency, year=year, filename=name,
                canonicalize=False,
            ),
        }
        if suffix == ".pptx":
            candidates.update((
                _remote_export_path(
                    config, agency=agency, year=year, filename=name,
                    legacy=True,
                ),
                _remote_export_path(
                    config, agency=agency, year=year, filename=name,
                    legacy=True, canonicalize=False,
                ),
            ))
        for remote_path in candidates:
            if remote_path not in keep_paths:
                targets[remote_path] = Path(remote_path).name

    with _remote_exports_lock:
        for folder_path, allowed_suffixes in folder_specs.items():
            list_url = (
                f"{_GRAPH}/drives/{drive_id}/root:/"
                f"{quote(folder_path, safe='/')}:/children"
            )
            try:
                while list_url:
                    listing = requests.get(
                        list_url,
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "name,file", "$top": "999"},
                        timeout=30,
                    )
                    if listing.status_code == 404:
                        break
                    if listing.status_code != 200:
                        logger.warning(
                            "Shared export listing failed for %s: HTTP %s",
                            folder_path, listing.status_code,
                        )
                        break
                    envelope = listing.json()
                    for item in envelope.get("value", []):
                        candidate = portable_export_filename(item.get("name", ""))
                        suffix = Path(candidate).suffix.lower()
                        remote_path = f"{folder_path}/{candidate}"
                        if (
                            isinstance(item.get("file"), dict)
                            and suffix in allowed_suffixes
                            and stable_export_stem(candidate) in stable_stems
                            and remote_path not in keep_paths
                        ):
                            targets[remote_path] = candidate
                    list_url = str(envelope.get("@odata.nextLink") or "")
            except Exception:
                logger.exception("Could not list prior shared export versions in %s", folder_path)

        deleted, errors = [], []
        for remote_path, display_name in sorted(targets.items()):
            url = f"{_GRAPH}/drives/{drive_id}/root:/{quote(remote_path, safe='/')}"
            try:
                response = requests.delete(
                    url, headers={"Authorization": f"Bearer {token}"}, timeout=30,
                )
                if response.status_code in (204, 404):
                    deleted.append(display_name)
                else:
                    logger.warning("Shared export delete failed: HTTP %s", response.status_code)
                    errors.append(display_name)
            except Exception:
                logger.exception("Shared export delete request failed")
                errors.append(display_name)
    return {"ok": not errors, "deleted": deleted, "errors": errors}


def cleanup_previous_exports(
    paths,
    *,
    agency: str,
    year: str,
    filenames: list[str],
    keep_filenames: list[str],
) -> dict:
    """Remove all older local/shared versions for explicitly identified vehicles."""
    old_stems = {stable_export_stem(value) for value in filenames if value}
    keep_names = {portable_export_filename(value) for value in keep_filenames if value}
    deleted_local, errors = [], []
    with _remote_exports_lock:
        try:
            candidates = [
                candidate for candidate in paths.workspace_output_dir.iterdir()
                if candidate.is_file()
                and candidate.suffix.lower() in _EXPORT_SUFFIXES
                and stable_export_stem(candidate.name) in old_stems
                and candidate.name not in keep_names
            ]
        except OSError:
            candidates = []
        for candidate in sorted(candidates):
            try:
                candidate.unlink()
                deleted_local.append(candidate.name)
            except OSError:
                errors.append(candidate.name)
        shared = delete_shared_exports(
            agency=agency,
            year=year,
            filenames=filenames,
            keep_filenames=list(keep_names),
        )
        errors.extend(shared.get("errors", []))
    return {
        "ok": not errors,
        "deleted_local": deleted_local,
        "deleted_shared": shared.get("deleted", []),
        "errors": errors,
    }


def upload_export_in_background(
    local_pptx: Path,
    *,
    agency: str,
    year: str,
    filename: Optional[str] = None,
    canonicalize: bool = True,
    on_complete=None,
) -> None:
    """Fire-and-forget background upload. Used by generation_service so the
    generate response returns immediately.

    ``on_complete(success: bool)`` is called from the worker thread when
    the upload finishes. The server.py data_version counter is the
    intended consumer — bumping it lets the UI know to refresh / toast.

    Failed uploads are enqueued for retry (when cloud is enabled). The
    sync loop drains the queue on every iteration; even if the app is
    closed mid-upload, next launch re-tries automatically.
    """
    def _worker():
        ok = upload_export(
            local_pptx, agency=agency, year=year, filename=filename,
            canonicalize=canonicalize,
        )
        if not ok:
            # Only queue if cloud was supposed to handle this. The
            # upload_export() implementation short-circuits to False on
            # both transient and intentional reasons; we re-check the
            # cloud flag here so cloud-disabled installs don't queue
            # forever.
            try:
                from ..adapters import wiring
                # Only queue when retrying could plausibly succeed: cloud is
                # enabled, an exports target is configured, the file is
                # still on disk, and we're not in pytest. Anything else is
                # a permanent skip — queueing would just thrash the drain
                # loop forever (the v2.2.x exports_* config drift bug).
                if (
                    not os.environ.get("PYTEST_CURRENT_TEST")
                    and wiring._cloud_flag_enabled()  # noqa: SLF001
                    and _exports_target_configured()
                    and local_pptx.exists()
                ):
                    from ...paths import AppPaths
                    from .outbound_queue import enqueue_export
                    enqueue_export(
                        AppPaths(),
                        local_path=local_pptx,
                        agency=agency,
                        year=year,
                        filename=filename,
                        canonicalize=canonicalize,
                    )
            except Exception:
                logger.exception("Failed to queue export retry for %s", local_pptx.name)
        if on_complete is not None:
            try:
                on_complete(ok)
            except Exception:
                logger.exception("Export upload on_complete callback raised")

    threading.Thread(target=_worker, daemon=True, name=f"export-upload-{local_pptx.name}").start()
