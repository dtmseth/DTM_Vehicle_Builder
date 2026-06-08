"""Status + profile-photo accessors for the cloud connection indicator UI.

The frontend chip in the header polls ``/api/cloud/status`` every minute (and
right after each save) to render the connection state. The user's profile
photo is fetched once per session and cached on disk so subsequent polls
return instantly without round-tripping to Microsoft Graph.

Designed to be safe to call from any state: cloud disabled, cloud enabled
but unsigned, signed in but photo unavailable, etc. Never raises — the
indicator should fail to a sensible "Local mode" state rather than break
the UI.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ...paths import AppPaths
from ..adapters import wiring

logger = logging.getLogger(__name__)


# Photo cache lives at the workspace root. Single file; the bytes Graph
# returns are usually JPEG but the precise format doesn't matter to the UI
# (browsers sniff). Cache TTL of 24h keeps the photo fresh-enough without
# hammering Graph on every UI poll.
_PHOTO_CACHE_FILENAME = ".cloud_photo.bin"
_PHOTO_CACHE_TTL_SECONDS = 24 * 60 * 60


def _photo_cache_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _PHOTO_CACHE_FILENAME


def get_status(paths: AppPaths) -> dict:
    """Return a dict describing the current cloud connection state.

    Shape:
      {
        "cloud_enabled": bool,
        "signed_in": bool,
        "user": { "display_name": str, "email": str, "user_id": str } | None,
        "has_photo": bool,
        "syncing": bool,           # spinner state for the indicator modal
        "data_version": int,       # bumps when sync changed local files
      }

    The UI watches data_version transitions to know when to re-fetch its
    project/draft lists — sync changes those files behind the UI's back,
    and without this signal the UI shows stale data until the next user
    navigation. Never raises; UI treats any unexpected shape as "Local mode".
    """
    syncing = _is_sync_in_progress()
    data_version = _data_version()

    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return _empty_status(syncing=syncing, cloud_enabled=False, data_version=data_version, paths=paths)

    try:
        bundle = wiring.get_active_bundle()
    except Exception:
        logger.exception("Could not get active bundle for cloud status")
        return _empty_status(syncing=syncing, cloud_enabled=True, data_version=data_version, paths=paths)

    try:
        if not bundle.identity.is_signed_in():
            return _empty_status(syncing=syncing, cloud_enabled=True, data_version=data_version, paths=paths)
        user = bundle.identity.current_user()
    except Exception:
        logger.exception("is_signed_in / current_user check failed")
        return _empty_status(syncing=syncing, cloud_enabled=True, data_version=data_version, paths=paths)

    if user is None:
        return _empty_status(syncing=syncing, cloud_enabled=True, data_version=data_version, paths=paths)

    # Lazy-load the photo if we haven't fetched it yet this session. Done
    # synchronously to keep the status endpoint single-call. If Graph is
    # slow this adds a one-time bump on the first status call; subsequent
    # polls return immediately from the cached file.
    has_photo = _ensure_photo_cached(paths, bundle.identity)

    return {
        "cloud_enabled": True,
        "signed_in": True,
        "user": {
            "display_name": user.display_name,
            "email": user.email,
            "user_id": user.user_id,
        },
        "has_photo": has_photo,
        "syncing": syncing,
        "data_version": data_version,
        "pending_queue": _queue_depth(paths),
        "pending_update": _pending_update(paths),
        "update_state": _update_state(paths),
        "changes": _changes_summary(),
    }


def _empty_status(*, syncing: bool, cloud_enabled: bool, data_version: int,
                  paths: AppPaths | None = None) -> dict:
    return {
        "cloud_enabled": cloud_enabled,
        "signed_in": False,
        "user": None,
        "has_photo": False,
        "syncing": syncing,
        "data_version": data_version,
        "pending_queue": {"proposals": 0, "exports": 0},
        "pending_update": None,
        "update_state": _update_state(paths) if paths is not None else None,
        "changes": _changes_summary(),
    }


def _pending_update(paths: AppPaths) -> dict | None:
    """Forward to update_check_service so the cloud chip can surface a
    "Update vX.Y.Z ready" banner when an installer is queued. Returns
    None on any error so the status response stays usable."""
    try:
        from .update_check_service import get_pending_update_info
        return get_pending_update_info(paths)
    except Exception:
        logger.exception("pending_update lookup failed")
        return None


def _update_state(paths: AppPaths) -> dict:
    """Single-line update state for the UI ('up_to_date', 'downloading',
    'ready', 'available', 'platform_unsupported'). Falls back to
    'up_to_date' on any error so the status response stays useful."""
    try:
        from .update_check_service import describe_update_state, check_for_update
        from ..adapters.wiring import _cloud_flag_enabled, get_active_bundle  # noqa: SLF001
        from ...config.store import load_config
        available = None
        if _cloud_flag_enabled():
            try:
                settings = load_config("app_settings.json", paths) or {}
                dismissed = list(settings.get("dismissed_update_versions", []) or [])
                info = check_for_update(get_active_bundle().storage, dismissed_versions=dismissed)
                if info is not None:
                    available = {"version": info.version, "filename": info.filename}
            except Exception:
                logger.exception("update_state: check_for_update failed")
        return describe_update_state(paths, available_info=available)
    except Exception:
        logger.exception("update_state lookup failed")
        from .update_check_service import get_embedded_version
        return {"state": "up_to_date", "current": get_embedded_version()}


def _queue_depth(paths: AppPaths) -> dict:
    """Forward to the outbound queue service. Never raises — empty depth
    on any error so a bad lookup doesn't break the status response."""
    try:
        from .outbound_queue import queue_depth
        return queue_depth(paths)
    except Exception:
        logger.exception("queue_depth lookup failed")
        return {"proposals": 0, "exports": 0}


def _is_sync_in_progress() -> bool:
    """Late import to break the server.py ↔ services circular at import time.

    Uses the visible-spinner predicate, not the raw flag — quiet periodic
    syncs report False here so the UI chip stays calm."""
    try:
        from .. import server as _server
        return bool(_server.is_sync_in_progress_visible())
    except Exception:
        return False


def _changes_summary() -> dict | None:
    try:
        from .. import server as _server
        return _server.get_sync_changes_summary()
    except Exception:
        return None


def _data_version() -> int:
    try:
        from .. import server as _server
        return int(_server.get_data_version())
    except Exception:
        return 0


def get_cached_photo_bytes(paths: AppPaths) -> bytes | None:
    """Return the on-disk profile photo, or None if missing/empty.

    The route handler streams these bytes to the browser. Returning None
    causes the route to send a 404 so the UI can fall back to initials.
    """
    path = _photo_cache_path(paths)
    if not path.exists():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        logger.exception("Could not read cached photo at %s", path)
        return None
    return data if data else None


def _ensure_photo_cached(paths: AppPaths, identity) -> bool:
    """Make sure a fresh-enough photo is on disk. Returns whether one exists.

    "Fresh enough" = the cache file exists AND was written within the TTL
    window. Anything older triggers a refetch. A refetch failure preserves
    the stale file (better something than nothing) but doesn't crash.
    """
    path = _photo_cache_path(paths)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < _PHOTO_CACHE_TTL_SECONDS:
            return True
        # Otherwise fall through to refetch.

    if not hasattr(identity, "fetch_user_photo"):
        # LocalIdentityProvider and any future non-M365 provider lack this
        # method — treat as "no photo available" without complaint.
        return path.exists()

    try:
        data = identity.fetch_user_photo()
    except Exception:
        logger.exception("fetch_user_photo raised; keeping any stale cache")
        return path.exists()

    if not data:
        # Microsoft returns 404 for users with no photo. We honor that by
        # caching the absence (touch a zero-byte file so the TTL applies)
        # so we don't hammer Graph asking the same question every minute.
        try:
            path.write_bytes(b"")
        except OSError:
            logger.exception("Could not touch empty photo cache at %s", path)
        return False

    try:
        path.write_bytes(data)
    except OSError:
        logger.exception("Could not write photo cache at %s", path)
        return False
    return True
