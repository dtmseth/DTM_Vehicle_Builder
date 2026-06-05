"""Auto-upload generated PPTX exports to a SharePoint folder outside the
vehicle-builder library so the whole company can access them via normal
SharePoint navigation (no app install needed on the consumer side).

Triggered from generation_service immediately after a successful local
write. Runs in a background thread so the generate response returns
fast; the cloud chip's spinner reflects the upload-in-progress state
via the same data_version mechanism that drives the project-list
auto-refresh.

Path layout in the target library (configurable via cloud_config.json):

    {exports_base_folder}/{agency}/{year}/{filename}.pptx

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


def _bundle_or_none():
    """Return the active cloud bundle, or None when uploads should skip."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return None
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return None
    try:
        bundle = wiring.get_active_bundle()
    except Exception:
        logger.exception("Could not get active bundle for export upload")
        return None
    try:
        if not bundle.identity.is_signed_in():
            return None
    except Exception:
        logger.exception("is_signed_in check failed during export upload")
        return None
    return bundle


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
) -> bool:
    """Synchronous upload entry point. Returns True on success.

    ``year`` is the project's build year; falls back to "Unassigned" when
    empty so the file still lands somewhere instead of failing. ``filename``
    defaults to the local file's name.
    """
    bundle = _bundle_or_none()
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

    base = (config.exports_base_folder or "").strip().strip("/")
    segments = [base] if base else []
    segments.append(_sanitize_segment(agency))
    segments.append(_sanitize_segment(year or "Unassigned"))
    segments.append(filename or local_pptx.name)
    remote_path = "/".join(s for s in segments if s)

    try:
        data = local_pptx.read_bytes()
    except OSError:
        logger.exception("Could not read local export %s", local_pptx)
        return False

    return _upload_via_session(token, drive_id, remote_path, data)


def upload_export_in_background(
    local_pptx: Path,
    *,
    agency: str,
    year: str,
    filename: Optional[str] = None,
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
        ok = upload_export(local_pptx, agency=agency, year=year, filename=filename)
        if not ok:
            # Only queue if cloud was supposed to handle this. The
            # upload_export() implementation short-circuits to False on
            # both transient and intentional reasons; we re-check the
            # cloud flag here so cloud-disabled installs don't queue
            # forever.
            try:
                from ..adapters import wiring
                # Don't queue in pytest, local mode, or when the local
                # file is gone (upload_export already returned False for
                # missing-file). The drain logic also no-ops gracefully
                # if any of these conditions changed by retry time.
                if (
                    not os.environ.get("PYTEST_CURRENT_TEST")
                    and wiring._cloud_flag_enabled()  # noqa: SLF001
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
                    )
            except Exception:
                logger.exception("Failed to queue export retry for %s", local_pptx.name)
        if on_complete is not None:
            try:
                on_complete(ok)
            except Exception:
                logger.exception("Export upload on_complete callback raised")

    threading.Thread(target=_worker, daemon=True, name=f"export-upload-{local_pptx.name}").start()
