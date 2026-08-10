"""SharePoint mirror for project records and build drafts.

Settings (Phase 2-β) flow through a PR-based review pipeline. Work data
(projects + drafts) is per-user state with last-writer-wins semantics —
no review, no PRs, just direct SharePoint reads and writes.

Two operations:
- ``mirror_*_to_cloud``: called from save_project / save_draft right after
  the local write. Pushes the file to SharePoint /Projects/ or /Drafts/.
  No-op outside cloud mode.
- ``sync_work_data``: called by the periodic sync loop in server.py.
  It synchronizes projects immediately.  Drafts are deliberately fetched
  only when a user opens one, so a new device never freezes while downloading
  an entire historical build archive.

Storage shape:
- Cloud: ``/Projects/{project_id}.json`` and ``/Drafts/{draft_id}.json``
  (flat, no subdirs — SharePointGraphProvider.list_files isn't recursive).
- Local: ``workspace/projects/{project_id}/project.json`` (subdir per
  project, leaves room for future artifacts) and
  ``workspace/drafts/{draft_id}.json`` (flat).

Errors never propagate. A failed mirror means the local save still
succeeded; the next sync pass picks it up. A failed sync means the
next pass tries again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from ...paths import AppPaths
from ...storage.safety import validate_safe_id
from ..adapters import wiring

logger = logging.getLogger(__name__)


PROJECTS_REMOTE_FOLDER = "Projects"
DRAFTS_REMOTE_FOLDER = "Drafts"

# Per-device state manifest tracking which records were present in cloud at
# the last sync. Diff between "what was in cloud last time" and "what is in
# cloud now" tells us which files were deleted by some other device (so we
# should also delete them locally) vs. which are local-only (so we should
# upload them). Without this, a missing-from-cloud file is ambiguous —
# could be deleted from cloud OR never made it to cloud.
#
# Schema v3 (current) stores per-file eTags plus local content hashes. The
# eTag identifies a cloud change; the hash tells us whether this device saved
# a newer local version while the remote eTag stayed the same.
# Schema v1 (just lists of IDs) auto-upgrades on first sync — every file
# is considered "missing eTag" and falls through to the slow-path
# content-fetch, populating eTags as it goes.
_STATE_FILENAME = ".cloud_state.json"
_STATE_SCHEMA_VERSION = 3
# A local write succeeded, but the next Graph listing has not yet supplied the
# replacement eTag. This must be distinct from an empty eTag, which some
# StorageProvider implementations legitimately use for every remote record.
_PENDING_UPLOAD_ETAG = "__dtm_pending_upload_confirmation__"

# A console setup (and a few other guided flows) can change a draft several
# times in quick succession.  Serialize and coalesce background mirrors so an
# earlier snapshot cannot finish after the final one and become the cloud copy
# that a later app launch pulls down.
_work_data_io_lock = threading.RLock()
_background_mirror_lock = threading.Lock()
_background_mirror_versions: dict[tuple[str, str], int] = {}
_background_mirror_running: set[tuple[str, str]] = set()


def _cloud_storage():
    """Return the active bundle's storage adapter, or None outside cloud mode.

    Single helper so every call site short-circuits the same way when cloud
    is disabled or the bundle failed to construct.
    """
    # Hard guard: NEVER let pytest-driven code paths reach real SharePoint.
    # PYTEST_CURRENT_TEST is set by pytest automatically while a test is
    # running; this short-circuit applies even if some test forgot to
    # monkey-patch the cloud flag or bundle. See tests/conftest.py for
    # the matching autouse fixture that's the primary defense.
    #
    # Tests that DO need to exercise the cloud code path with a fake
    # remote (test_shared_work_service, test_cloud_status_service) opt
    # back in by setting DTM_ALLOW_CLOUD_IN_TESTS=1 in their cloud_on
    # fixture — they're known to have installed a _FakeRemote bundle.
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return None
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return None
    try:
        bundle = wiring.get_active_bundle()
    except Exception:
        logger.exception("Could not get active bundle for shared-work I/O")
        return None
    try:
        if not bundle.identity.is_signed_in():
            return None
    except Exception:
        logger.exception("is_signed_in check failed during shared-work I/O")
        return None
    return bundle.storage


# ── Outbound: mirror local writes to SharePoint ─────────────────────────────


def mirror_project_to_cloud(project_id: str, local_path: Path) -> bool:
    """Push the project's project.json to SharePoint /Projects/.

    Returns True on success, False on no-op or failure. Callers should treat
    the return value as advisory: a False here doesn't roll back the local
    save — the next sync_work_data pass will retry.
    """
    return _mirror_to_cloud(
        kind="project", record_id=project_id, local_path=local_path,
        remote_folder=PROJECTS_REMOTE_FOLDER,
    )


def mirror_draft_to_cloud(draft_id: str, local_path: Path) -> bool:
    """Push the draft JSON to SharePoint /Drafts/."""
    return _mirror_to_cloud(
        kind="draft", record_id=draft_id, local_path=local_path,
        remote_folder=DRAFTS_REMOTE_FOLDER,
    )


# Fire-and-forget wrappers — used by save_project / save_draft so a Graph
# roundtrip doesn't block the local save response. The 60s sync_work_data
# loop is the safety net for any mirror that fails silently in the
# background; teammates see the change on their next sync regardless.

def mirror_project_to_cloud_in_background(project_id: str, local_path: Path) -> None:
    _queue_background_mirror(
        kind="project", record_id=project_id, local_path=local_path,
        remote_folder=PROJECTS_REMOTE_FOLDER,
    )


def mirror_draft_to_cloud_in_background(draft_id: str, local_path: Path) -> None:
    _queue_background_mirror(
        kind="draft", record_id=draft_id, local_path=local_path,
        remote_folder=DRAFTS_REMOTE_FOLDER,
    )


def _queue_background_mirror(*, kind: str, record_id: str, local_path: Path, remote_folder: str) -> None:
    """Ensure one worker pushes the newest saved version for a record.

    The worker deliberately reads *local_path* only after it owns the work
    lock.  If another save happens while an upload is in flight, it loops and
    sends the new file before allowing inbound sync to run.
    """
    key = (kind, record_id)
    with _background_mirror_lock:
        _background_mirror_versions[key] = _background_mirror_versions.get(key, 0) + 1
        if key in _background_mirror_running:
            return
        _background_mirror_running.add(key)
    threading.Thread(
        target=_drain_background_mirror,
        kwargs={
            "key": key, "record_id": record_id, "local_path": local_path,
            "remote_folder": remote_folder,
        },
        daemon=True,
        name=f"mirror-{kind}-{record_id}",
    ).start()


def _drain_background_mirror(
    *, key: tuple[str, str], record_id: str, local_path: Path, remote_folder: str,
) -> None:
    try:
        # Hold the same lock as inbound reconciliation across the full drain.
        # That prevents sync from seeing an intermediate remote snapshot after
        # a new local save has already queued its replacement.
        with _work_data_io_lock:
            while True:
                with _background_mirror_lock:
                    version = _background_mirror_versions.get(key, 0)
                _mirror_to_cloud_unlocked(
                    kind=key[0], record_id=record_id, local_path=local_path,
                    remote_folder=remote_folder,
                )
                with _background_mirror_lock:
                    if _background_mirror_versions.get(key) == version:
                        _background_mirror_versions.pop(key, None)
                        _background_mirror_running.discard(key)
                        return
    finally:
        # _mirror_to_cloud_unlocked handles ordinary I/O errors itself, but
        # never leave a record permanently marked as running if an unexpected
        # programmer/runtime error escapes the worker.
        with _background_mirror_lock:
            _background_mirror_running.discard(key)


def _mirror_to_cloud(*, kind: str, record_id: str, local_path: Path, remote_folder: str) -> bool:
    with _work_data_io_lock:
        return _mirror_to_cloud_unlocked(
            kind=kind, record_id=record_id, local_path=local_path, remote_folder=remote_folder,
        )


def _mirror_to_cloud_unlocked(*, kind: str, record_id: str, local_path: Path, remote_folder: str) -> bool:
    storage = _cloud_storage()
    if storage is None:
        return False
    try:
        validate_safe_id(record_id, label=f"{kind}_id")
    except ValueError:
        logger.exception("Refusing to mirror %s with unsafe id %r", kind, record_id)
        return False
    if not local_path.exists():
        logger.warning("%s file missing on disk; can't mirror: %s", kind.capitalize(), local_path)
        return False
    try:
        content = local_path.read_text(encoding="utf-8")
        storage.write_text(f"{remote_folder}/{record_id}.json", content)
        return True
    except Exception:
        logger.warning("Failed to mirror %s %s to cloud", kind, record_id)
        return False


def delete_project_from_cloud(project_id: str) -> bool:
    storage = _cloud_storage()
    if storage is None:
        return False
    try:
        storage.delete(f"{PROJECTS_REMOTE_FOLDER}/{project_id}.json")
        return True
    except FileNotFoundError:
        return True  # already gone
    except Exception:
        logger.warning("Failed to delete project %s from cloud", project_id)
        return False


def delete_draft_from_cloud(draft_id: str) -> bool:
    storage = _cloud_storage()
    if storage is None:
        return False
    try:
        storage.delete(f"{DRAFTS_REMOTE_FOLDER}/{draft_id}.json")
        return True
    except FileNotFoundError:
        return True
    except Exception:
        logger.warning("Failed to delete draft %s from cloud", draft_id)
        return False


SETTINGS_REMOTE_FOLDER = "Settings"


def save_setting_to_cloud(target_file: str, serialized_content: str) -> bool:
    """Direct SP mirror for /Settings/<subdir>/<id>.json on save.

    The proposal pipeline (save_via_proposal) creates a PR in
    dtm-shared-settings that the publish workflow eventually pushes to
    SharePoint. Eventually = hours, because GitHub Actions cron throttles
    schedules on low-traffic repos. That delay caused per-record entities
    saved on one device to never reach SP, which broke cross-device
    visibility for agencies/sales reps/presets.

    Direct write here makes SP authoritative immediately. The proposal
    still fires so the repo holds an audit record, but other devices
    can sync the new content within their normal 60s cycle instead of
    waiting on the workflow.

    No-op outside cloud mode. Returns True on success."""
    storage = _cloud_storage()
    if storage is None:
        return False
    try:
        storage.write_text(f"{SETTINGS_REMOTE_FOLDER}/{target_file}", serialized_content)
        return True
    except Exception:
        logger.warning("Failed to direct-save %s to SharePoint", target_file)
        return False


def save_setting_to_cloud_in_background(target_file: str, serialized_content: str) -> None:
    """Fire-and-forget wrapper for save_setting_to_cloud. Used from the
    save handlers so the response doesn't block on a Graph roundtrip."""
    import threading
    threading.Thread(
        target=save_setting_to_cloud,
        args=(target_file, serialized_content),
        daemon=True,
        name=f"mirror-setting-{target_file}",
    ).start()


def save_settings_to_cloud_batch_in_background(items: list[tuple[str, str]]) -> None:
    """Mirror many settings files in ONE background thread (sequential).

    ``items`` are ``(remote_target_file, local_file_path)`` pairs. Each file is
    re-read from disk at upload time, and any that no longer exist are skipped —
    so a record the user deletes mid-import is never (re-)uploaded, which would
    otherwise resurrect it on the next sync. Bulk operations (e.g. importing
    hundreds of QB customers as agencies) must not spawn a thread per record;
    this walks the list on one daemon thread. No-op outside cloud mode."""
    import threading

    threading.Thread(
        target=_mirror_settings_batch, args=(items,), daemon=True, name="mirror-settings-batch"
    ).start()


def _mirror_settings_batch(items: list[tuple[str, str]]) -> int:
    """Synchronous body of the batch mirror. Returns the count uploaded.

    Skips items whose local file no longer exists so a deletion that races the
    import is not resurrected. Separated out for testability."""
    uploaded = 0
    for target_file, local_path in items:
        try:
            p = Path(local_path)
            if not p.exists():
                continue  # deleted since the import was queued — don't resurrect
            if save_setting_to_cloud(target_file, p.read_text(encoding="utf-8")):
                uploaded += 1
        except Exception:
            logger.exception("Batch settings mirror failed for %s", target_file)
    return uploaded


def cleanup_processed_proposals() -> dict:
    """Delete old /PendingChanges/ entries to keep the folder from growing.

    Each save/delete via the proposal pipeline writes a JSON record to
    SharePoint /PendingChanges/ for the pickup workflow to consume. The
    workflow reads it, creates a PR in dtm-shared-settings, but does NOT
    delete the original — those proposals accumulate forever.

    Heuristic for "this proposal is done":
      - Older than 12 hours: drop unconditionally. The pickup +
        publish workflow normally processes within minutes to a few
        hours (cron throttle is the worst case). Anything still around
        after half a day is processed, stuck, or both — removing it is
        harmless because the canonical state lives in /Settings/ which
        the direct-mirror writes maintain.
      - Cap deletions per cycle at 50 so a backlog doesn't stall the
        sync indefinitely.

    Returns {"checked": int, "deleted": int}. Never raises."""
    storage = _cloud_storage()
    if storage is None:
        return {"checked": 0, "deleted": 0}

    try:
        proposals = list(storage.list_files("PendingChanges"))
    except Exception:
        logger.exception("PendingChanges cleanup: list failed")
        return {"checked": 0, "deleted": 0}

    import json as _json
    from datetime import datetime, timezone

    now_ts = datetime.now(timezone.utc)
    deleted = 0
    checked = 0
    MAX_PER_CYCLE = 50
    AGE_CUTOFF_HOURS = 12

    for proposal_path in proposals:
        if checked >= MAX_PER_CYCLE:
            break
        if proposal_path.endswith(".meta.json"):
            continue
        checked += 1
        try:
            payload = _json.loads(storage.read_text(proposal_path))
        except Exception:
            continue
        submitted_at_str = str(payload.get("submitted_at", ""))
        try:
            submitted_at = datetime.fromisoformat(submitted_at_str)
        except Exception:
            continue
        age_hours = (now_ts - submitted_at).total_seconds() / 3600.0
        if age_hours < AGE_CUTOFF_HOURS:
            continue
        for p in (proposal_path, proposal_path + ".meta.json"):
            try:
                storage.delete(p)
            except FileNotFoundError:
                pass
            except Exception:
                logger.warning("PendingChanges cleanup: delete failed for %s", p)
        deleted += 1

    if deleted:
        logger.info("PendingChanges cleanup: %d processed proposal(s) removed", deleted)
    return {"checked": checked, "deleted": deleted}


def delete_setting_from_cloud(target_file: str, *, attempts: int = 3) -> bool:
    """Directly delete a /Settings/<subdir>/<id>.json (and its .meta.json
    sidecar) from SharePoint right away.

    Belt-and-suspenders for the per-record settings entities (agencies,
    sales reps, presets): the proposal pipeline does the "official"
    deletion through dtm-shared-settings, but the publish workflow can
    be hours late due to GitHub Actions' cron throttling on low-traffic
    repos. Direct delete makes the cloud copy disappear immediately so
    other devices' next sync sees it as gone without waiting on the
    workflow round-trip. The proposal still fires so the repo record
    stays in sync.

    No-op outside cloud mode (returns True — nothing to delete is success).
    ``target_file`` is the same shape used by save_via_proposal — e.g.
    ``"agencies/abc-123.json"``. Transient Graph failures (e.g. 429 throttling
    during a bulk delete) are retried with backoff so a delete actually sticks
    instead of silently leaving the cloud copy to resurrect on the next sync.
    """
    import time

    storage = _cloud_storage()
    if storage is None:
        return True  # no cloud copy to remove
    remote = f"{SETTINGS_REMOTE_FOLDER}/{target_file}"
    ok = True
    for path in (remote, remote + ".meta.json"):
        deleted = False
        for attempt in range(attempts):
            try:
                storage.delete(path)
                deleted = True
                break
            except FileNotFoundError:
                deleted = True  # already gone
                break
            except Exception:
                if attempt == attempts - 1:
                    logger.warning(
                        "Failed to direct-delete %s from SharePoint after %d attempts",
                        path, attempts,
                    )
                else:
                    time.sleep(2 ** attempt)  # 1s, 2s backoff
        ok = ok and deleted
    return ok


# ── Inbound: pull cloud changes into local cache ─────────────────────────────


def sync_work_data(paths: AppPaths, *, include_drafts: bool = True) -> dict:
    """Reconcile local workspaces with SharePoint.

    Cloud is the source of truth for remote changes. On each sync:
      1. Pull every cloud file to local (content-equality skips no-ops),
         except a local save made after the same remote eTag was recorded.
      2. Files in the last-known cloud set but absent from cloud now → DELETE
         locally (some other device deleted them and we need to follow).
      3. Files in local but in neither cloud nor the last-known set → UPLOAD
         (they were created here and never made it to cloud, OR they're
         legacy data from before mirror was wired).

    ``include_drafts`` is retained for explicit maintenance reconciliation
    and test coverage.  Normal app startup and periodic sync pass ``False``:
    project records are enough to populate the overview, while opening a
    build retrieves only that one draft through ``hydrate_draft_from_cloud``.
    Returns a counts dict the periodic loop logs. Never raises.
    """
    with _work_data_io_lock:
        return _sync_work_data_unlocked(paths, include_drafts=include_drafts)


def _sync_work_data_unlocked(paths: AppPaths, *, include_drafts: bool) -> dict:
    """Reconcile work data while no background upload can interleave."""
    storage = _cloud_storage()
    if storage is None:
        return {
            "projects_updated": 0, "projects_deleted": 0, "projects_uploaded": 0,
            "drafts_updated": 0,   "drafts_deleted": 0,   "drafts_uploaded": 0,
            "drafts_deferred": not include_drafts,
            "skipped_local_mode": True,
        }

    state = _load_state(paths)
    proj = _reconcile_projects(
        storage, paths, _state_as_etag_map(state.get("projects")),
        _state_as_hash_map(state.get("project_hashes")),
    )
    draft_etags = _state_as_etag_map(state.get("drafts"))
    draft_hashes = _state_as_hash_map(state.get("draft_hashes"))
    if include_drafts:
        draf = _reconcile_drafts(storage, paths, draft_etags, draft_hashes)
    else:
        # Retain draft state untouched.  Walking hundreds of historical
        # builds at launch is slow enough to trigger Graph throttling and can
        # make the native shell look frozen.  A selected build is hydrated on
        # demand instead, one safe request at a time.
        draf = {
            "current_etags": draft_etags,
            "current_hashes": draft_hashes,
            "updated": 0,
            "deleted": 0,
            "uploaded": 0,
        }
    _save_state(paths, {
        "schema_version": _STATE_SCHEMA_VERSION,
        "projects": proj["current_etags"],
        "drafts":   draf["current_etags"],
        "project_hashes": proj["current_hashes"],
        "draft_hashes": draf["current_hashes"],
    })

    if proj["updated"] or proj["deleted"] or proj["uploaded"] or draf["updated"] or draf["deleted"] or draf["uploaded"]:
        logger.info(
            "Synced work data: projects(updated=%d, deleted=%d, uploaded=%d) "
            "drafts(updated=%d, deleted=%d, uploaded=%d)",
            proj["updated"], proj["deleted"], proj["uploaded"],
            draf["updated"], draf["deleted"], draf["uploaded"],
        )
    return {
        "projects_updated":  proj["updated"],
        "projects_deleted":  proj["deleted"],
        "projects_uploaded": proj["uploaded"],
        "drafts_updated":  draf["updated"],
        "drafts_deleted":  draf["deleted"],
        "drafts_uploaded": draf["uploaded"],
        "drafts_deferred": not include_drafts,
        "skipped_local_mode": False,
    }


def hydrate_draft_from_cloud(
    draft_id: str,
    paths: AppPaths,
    *,
    refresh: bool = False,
) -> bool:
    """Ensure one requested draft is available in the local workspace.

    This is the narrow counterpart to the project-first background sync.  It
    never performs a folder listing and never overwrites a newer local save.
    If a cached draft cannot be refreshed, the cached copy remains usable;
    callers only receive ``False`` when no local or cloud copy exists.
    """
    try:
        validate_safe_id(draft_id, label="draft_id")
    except ValueError:
        logger.warning("Refusing to hydrate draft with unsafe id: %r", draft_id)
        return False

    local_path = paths.workspace_drafts_dir / f"{draft_id}.json"
    with _work_data_io_lock:
        local_exists = local_path.exists()
        if local_exists and not refresh:
            return True

        storage = _cloud_storage()
        if storage is None:
            return local_exists
        try:
            remote_payload = storage.read_bytes(f"{DRAFTS_REMOTE_FOLDER}/{draft_id}.json")
        except FileNotFoundError:
            return local_exists
        except Exception:
            if local_exists:
                logger.warning("Could not refresh cloud draft %s; using cached copy", draft_id)
                return True
            logger.warning("Could not retrieve requested cloud draft %s", draft_id)
            return False

        if local_exists:
            try:
                local_payload = local_path.read_bytes()
            except OSError:
                logger.warning("Could not read cached draft %s before cloud refresh", draft_id)
                return True
            if local_payload == remote_payload:
                return True
            if _local_record_is_newer(local_payload, remote_payload):
                logger.warning("Preserving newer local draft %s during cloud refresh", draft_id)
                return True

        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(remote_payload)
        except OSError:
            logger.warning("Could not cache requested cloud draft %s", draft_id)
            return local_exists
        return True


# ── State manifest ───────────────────────────────────────────────────────────


def _state_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _STATE_FILENAME


def _load_state(paths: AppPaths) -> dict:
    path = _state_path(paths)
    if not path.exists():
        return {"schema_version": _STATE_SCHEMA_VERSION, "projects": [], "drafts": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Corrupt cloud state manifest at %s; treating as empty", path)
        return {"schema_version": _STATE_SCHEMA_VERSION, "projects": [], "drafts": []}
    if not isinstance(data, dict):
        return {"schema_version": _STATE_SCHEMA_VERSION, "projects": [], "drafts": []}
    return data


def _save_state(paths: AppPaths, state: dict) -> None:
    try:
        path = _state_path(paths)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("Could not write cloud state manifest")


def _state_as_etag_map(raw) -> dict[str, str]:
    """Normalize a state-file 'projects'/'drafts' value into an {id: etag} dict.

    Schema v2 stores it natively as a dict. Schema v1 (and dev-machines that
    upgraded from before) stored a flat list of IDs — treated here as
    {id: ""} so every file falls through to the slow-path fetch on first
    sync after upgrade, populating eTags as it goes.
    """
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        return {str(item): "" for item in raw}
    return {}


def _state_as_hash_map(raw) -> dict[str, str]:
    """Normalize stored local-content hashes; pre-v3 state has none."""
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    return {}


def _content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _record_updated_at(payload: bytes) -> datetime | None:
    """Read a record's UTC update marker without trusting filesystem clocks.

    Both shared draft and project records carry ``updated_at``.  It is used
    only while migrating pre-v3 cloud state, where there is no saved local
    content hash to distinguish an unsynced local edit from a remote update.
    """
    try:
        raw = json.loads(payload.decode("utf-8"))
        value = raw.get("updated_at") if isinstance(raw, dict) else None
        if not isinstance(value, str) or not value.strip():
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _local_record_is_newer(local_payload: bytes, remote_payload: bytes) -> bool:
    """Whether migration safety should preserve the local record.

    A missing/invalid timestamp deliberately falls back to the documented
    cloud-authoritative behavior rather than making an uncertain overwrite.
    """
    local_updated = _record_updated_at(local_payload)
    remote_updated = _record_updated_at(remote_payload)
    return bool(local_updated and remote_updated and local_updated > remote_updated)


# ── Reconciliation: projects ─────────────────────────────────────────────────


def _reconcile_projects(
    storage, paths: AppPaths, last_known: dict[str, str], last_hashes: dict[str, str],
) -> dict:
    return _reconcile_records(
        storage,
        paths,
        last_known,
        last_hashes,
        remote_folder=PROJECTS_REMOTE_FOLDER,
        id_label="project_id",
        local_record_path=lambda paths_, rid: paths_.workspace_projects_dir / rid / "project.json",
        list_local_ids=_list_local_project_ids,
        delete_local=_delete_local_project,
        mirror_to_cloud=mirror_project_to_cloud,
        ensure_local_root=lambda paths_: paths_.workspace_projects_dir.mkdir(parents=True, exist_ok=True),
    )


# ── Reconciliation: drafts ───────────────────────────────────────────────────


def _reconcile_drafts(
    storage, paths: AppPaths, last_known: dict[str, str], last_hashes: dict[str, str],
) -> dict:
    return _reconcile_records(
        storage,
        paths,
        last_known,
        last_hashes,
        remote_folder=DRAFTS_REMOTE_FOLDER,
        id_label="draft_id",
        local_record_path=lambda paths_, rid: paths_.workspace_drafts_dir / f"{rid}.json",
        list_local_ids=_list_local_draft_ids,
        delete_local=_delete_local_draft,
        mirror_to_cloud=mirror_draft_to_cloud,
        ensure_local_root=lambda paths_: paths_.workspace_drafts_dir.mkdir(parents=True, exist_ok=True),
    )


# ── Shared reconciliation engine ─────────────────────────────────────────────


def _reconcile_records(
    storage,
    paths: AppPaths,
    last_known: dict[str, str],
    last_hashes: dict[str, str],
    *,
    remote_folder: str,
    id_label: str,
    local_record_path,
    list_local_ids,
    delete_local,
    mirror_to_cloud,
    ensure_local_root,
) -> dict:
    """Single body shared by projects and drafts reconciliation.

    The two record kinds differ only in how their IDs map to local paths
    and how they're enumerated/deleted on disk. Everything else (eTag
    short-circuit, deletion propagation, local-only upload) is identical.
    """
    ensure_local_root(paths)
    try:
        remote_entries = storage.list_files_with_metadata(remote_folder)
    except FileNotFoundError:
        remote_entries = []
    except Exception:
        logger.warning("Could not list remote %s; keeping last-known state", remote_folder)
        return {
            "current_etags": last_known, "current_hashes": last_hashes,
            "updated": 0, "deleted": 0, "uploaded": 0,
        }

    # Step 1: walk the cloud listing. eTag match against state means we
    # know the cloud copy is unchanged AND we know local should also be
    # up-to-date (we wrote that eTag last time we synced it). Skip the
    # fetch entirely — this is the fast path for typical 60s cycles where
    # nothing has changed.
    remote_etags: dict[str, str] = {}
    current_hashes: dict[str, str] = {}
    updated = 0
    uploaded = 0
    for entry in remote_entries:
        remote_path = entry.path
        if not remote_path.endswith(".json") or remote_path.endswith(".meta.json"):
            continue
        name = remote_path.rsplit("/", 1)[-1]
        record_id = name[: -len(".json")]
        try:
            validate_safe_id(record_id, label=id_label)
        except ValueError:
            logger.warning("Skipping remote %s with unsafe id: %r", id_label, record_id)
            continue
        remote_etags[record_id] = entry.etag
        prior_etag = last_known.get(record_id)
        local_path = local_record_path(paths, record_id)
        if (entry.etag and prior_etag == entry.etag and local_path.exists()
                and record_id in last_hashes):
            # The remote copy has not changed since our last sync.  If the
            # local checksum did change, it is an unsynced local save, not a
            # collaborator update; upload it rather than erasing it with the
            # known-old cloud content on the next app launch.
            local_payload = local_path.read_bytes()
            local_hash = _content_hash(local_payload)
            if last_hashes.get(record_id) == local_hash:
                current_hashes[record_id] = local_hash
                continue
            if mirror_to_cloud(record_id, local_path):
                remote_etags[record_id] = _PENDING_UPLOAD_ETAG
                current_hashes[record_id] = local_hash
                uploaded += 1
            else:
                # Keep the previous cloud version + local hash state so this
                # same local change is retried on the next sync.
                remote_etags[record_id] = prior_etag
                if record_id in last_hashes:
                    current_hashes[record_id] = last_hashes[record_id]
            continue
        try:
            payload = storage.read_bytes(remote_path)
        except Exception:
            logger.warning("Could not read remote %s %s", id_label, remote_path)
            # Preserve the prior etag so we try again next iteration.
            if prior_etag:
                remote_etags[record_id] = prior_etag
            if record_id in last_hashes:
                current_hashes[record_id] = last_hashes[record_id]
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if local_path.exists():
            local_payload = local_path.read_bytes()
            local_hash = _content_hash(local_payload)
            if local_payload == payload:
                current_hashes[record_id] = local_hash
                continue
            if prior_etag == _PENDING_UPLOAD_ETAG and record_id in last_hashes:
                # We successfully wrote this record on the previous pass, but
                # Graph has not yet returned its replacement eTag.  A read of
                # the prior payload during that short propagation window must
                # never undo the local save. Re-send it until a listing
                # confirms the new cloud version.
                logger.warning(
                    "Awaiting cloud confirmation for local %s %s; preserving local save",
                    id_label, record_id,
                )
                if mirror_to_cloud(record_id, local_path):
                    uploaded += 1
                remote_etags[record_id] = _PENDING_UPLOAD_ETAG
                current_hashes[record_id] = local_hash
                continue
            # v1/v2 state has no local checksum.  Do not make the first v3
            # sync after an upgrade silently replace a newer local save with
            # a stale cloud file when a background upload just failed.  The
            # timestamp lives inside the record, so this remains meaningful
            # across devices unlike filesystem mtimes.
            if record_id not in last_hashes and _local_record_is_newer(local_payload, payload):
                logger.warning(
                    "Preserving newer local %s %s while migrating cloud sync state",
                    id_label, record_id,
                )
                if mirror_to_cloud(record_id, local_path):
                    # The next listing will confirm the new eTag. Until then
                    # retain the local checksum so the stale remote cannot
                    # be treated as authoritative in this process.
                    remote_etags[record_id] = _PENDING_UPLOAD_ETAG
                    current_hashes[record_id] = local_hash
                    uploaded += 1
                else:
                    # Do not write a local hash on a failed migration upload:
                    # the next sync must compare the timestamps again instead
                    # of assuming this copy already reached SharePoint.
                    remote_etags[record_id] = entry.etag
                continue
        try:
            local_path.write_bytes(payload)
            current_hashes[record_id] = _content_hash(payload)
            updated += 1
        except OSError:
            logger.exception("Could not write local %s file %s", id_label, local_path)

    remote_ids = set(remote_etags)

    # Step 2: deletions propagated from cloud → wipe locally.
    local_ids = set(list_local_ids(paths))
    deleted = 0
    for record_id in set(last_known) - remote_ids:
        if record_id not in local_ids:
            continue
        try:
            delete_local(paths, record_id)
            local_ids.discard(record_id)
            current_hashes.pop(record_id, None)
            deleted += 1
        except OSError:
            logger.exception("Could not delete local %s %s", id_label, record_id)

    # Step 3: local-only files → upload them so cloud becomes the union.
    for record_id in local_ids - remote_ids - set(last_known):
        local_path = local_record_path(paths, record_id)
        if mirror_to_cloud(record_id, local_path):
            # First sync after upload: we don't know the eTag yet (Graph
            # returns it but write_text doesn't surface it). Mark it as
            # pending so an immediately stale read cannot overwrite local;
            # the NEXT sync's listing replaces this with Graph's real eTag.
            remote_etags[record_id] = _PENDING_UPLOAD_ETAG
            current_hashes[record_id] = _content_hash(local_path.read_bytes())
            uploaded += 1

    return {
        "current_etags": remote_etags,
        "current_hashes": current_hashes,
        "updated": updated,
        "deleted": deleted,
        "uploaded": uploaded,
    }


def _list_local_project_ids(paths: AppPaths):
    if not paths.workspace_projects_dir.exists():
        return []
    return [
        d.name
        for d in paths.workspace_projects_dir.iterdir()
        if d.is_dir() and (d / "project.json").exists()
    ]


def _list_local_draft_ids(paths: AppPaths):
    if not paths.workspace_drafts_dir.exists():
        return []
    return [p.stem for p in paths.workspace_drafts_dir.glob("*.json") if p.is_file()]


def _delete_local_project(paths: AppPaths, project_id: str) -> None:
    shutil.rmtree(paths.workspace_projects_dir / project_id)


def _delete_local_draft(paths: AppPaths, draft_id: str) -> None:
    (paths.workspace_drafts_dir / f"{draft_id}.json").unlink()
