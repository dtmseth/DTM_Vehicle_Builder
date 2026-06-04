"""SharePoint mirror for project records and build drafts.

Settings (Phase 2-β) flow through a PR-based review pipeline. Work data
(projects + drafts) is per-user state with last-writer-wins semantics —
no review, no PRs, just direct SharePoint reads and writes.

Two operations:
- ``mirror_*_to_cloud``: called from save_project / save_draft right after
  the local write. Pushes the file to SharePoint /Projects/ or /Drafts/.
  No-op outside cloud mode.
- ``sync_work_data``: called by the periodic sync loop in server.py.
  Pulls every file from /Projects/ and /Drafts/ on SharePoint and writes
  any that differ from the local copy. Content-equality decides changes —
  no clock comparison, since SharePoint and the local filesystem don't
  share a reference frame.

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

import json
import logging
import shutil
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
_STATE_FILENAME = ".cloud_state.json"
_STATE_SCHEMA_VERSION = 1


def _cloud_storage():
    """Return the active bundle's storage adapter, or None outside cloud mode.

    Single helper so every call site short-circuits the same way when cloud
    is disabled or the bundle failed to construct.
    """
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


def _mirror_to_cloud(*, kind: str, record_id: str, local_path: Path, remote_folder: str) -> bool:
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
        logger.exception("Failed to mirror %s %s to cloud", kind, record_id)
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
        logger.exception("Failed to delete project %s from cloud", project_id)
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
        logger.exception("Failed to delete draft %s from cloud", draft_id)
        return False


# ── Inbound: pull cloud changes into local cache ─────────────────────────────


def sync_work_data(paths: AppPaths) -> dict:
    """Reconcile local project + draft workspaces with SharePoint.

    Cloud is the source of truth. On each sync:
      1. Pull every cloud file to local (content-equality skips no-ops).
      2. Files in the last-known cloud set but absent from cloud now → DELETE
         locally (some other device deleted them and we need to follow).
      3. Files in local but in neither cloud nor the last-known set → UPLOAD
         (they were created here and never made it to cloud, OR they're
         legacy data from before mirror was wired).

    First sync on every device makes cloud the union of all known data, then
    every subsequent sync converges. Returns a counts dict the periodic
    loop logs. Never raises.
    """
    storage = _cloud_storage()
    if storage is None:
        return {
            "projects_updated": 0, "projects_deleted": 0, "projects_uploaded": 0,
            "drafts_updated": 0,   "drafts_deleted": 0,   "drafts_uploaded": 0,
            "skipped_local_mode": True,
        }

    state = _load_state(paths)
    proj = _reconcile_projects(storage, paths, set(state.get("projects", [])))
    draf = _reconcile_drafts(storage, paths, set(state.get("drafts", [])))
    _save_state(paths, {
        "schema_version": _STATE_SCHEMA_VERSION,
        "projects": sorted(proj["current_ids"]),
        "drafts":   sorted(draf["current_ids"]),
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
        "skipped_local_mode": False,
    }


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


# ── Reconciliation: projects ─────────────────────────────────────────────────


def _reconcile_projects(storage, paths: AppPaths, last_known: set[str]) -> dict:
    paths.workspace_projects_dir.mkdir(parents=True, exist_ok=True)
    try:
        remote_files = storage.list_files(PROJECTS_REMOTE_FOLDER)
    except FileNotFoundError:
        remote_files = []
    except Exception:
        logger.exception("Could not list remote projects; keeping last-known state")
        return {"current_ids": last_known, "updated": 0, "deleted": 0, "uploaded": 0}

    # Step 1: pull every cloud project (content-equality skips no-ops).
    remote_ids: set[str] = set()
    updated = 0
    for remote_path in remote_files:
        if not remote_path.endswith(".json") or remote_path.endswith(".meta.json"):
            continue
        name = remote_path.rsplit("/", 1)[-1]
        project_id = name[: -len(".json")]
        try:
            validate_safe_id(project_id, label="project_id")
        except ValueError:
            logger.warning("Skipping remote project with unsafe id: %r", project_id)
            continue
        try:
            payload = storage.read_bytes(remote_path)
        except Exception:
            logger.exception("Could not read remote project %s", remote_path)
            continue
        remote_ids.add(project_id)
        local_dir = paths.workspace_projects_dir / project_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / "project.json"
        if local_path.exists() and local_path.read_bytes() == payload:
            continue
        try:
            local_path.write_bytes(payload)
            updated += 1
        except OSError:
            logger.exception("Could not write local project %s", local_path)

    # Step 2: enumerate what we actually have locally right now.
    local_ids: set[str] = set()
    for project_dir in paths.workspace_projects_dir.iterdir():
        if project_dir.is_dir() and (project_dir / "project.json").exists():
            local_ids.add(project_dir.name)

    # Step 3: deletions — anything we last saw in cloud but isn't there now.
    deleted = 0
    for project_id in last_known - remote_ids:
        if project_id not in local_ids:
            continue
        try:
            shutil.rmtree(paths.workspace_projects_dir / project_id)
            local_ids.discard(project_id)
            deleted += 1
        except OSError:
            logger.exception("Could not delete local project %s", project_id)

    # Step 4: uploads — local-only files that have never been in cloud.
    uploaded = 0
    for project_id in local_ids - remote_ids - last_known:
        local_path = paths.workspace_projects_dir / project_id / "project.json"
        if mirror_project_to_cloud(project_id, local_path):
            remote_ids.add(project_id)
            uploaded += 1

    return {
        "current_ids": remote_ids,
        "updated": updated,
        "deleted": deleted,
        "uploaded": uploaded,
    }


# ── Reconciliation: drafts ───────────────────────────────────────────────────


def _reconcile_drafts(storage, paths: AppPaths, last_known: set[str]) -> dict:
    paths.workspace_drafts_dir.mkdir(parents=True, exist_ok=True)
    try:
        remote_files = storage.list_files(DRAFTS_REMOTE_FOLDER)
    except FileNotFoundError:
        remote_files = []
    except Exception:
        logger.exception("Could not list remote drafts; keeping last-known state")
        return {"current_ids": last_known, "updated": 0, "deleted": 0, "uploaded": 0}

    remote_ids: set[str] = set()
    updated = 0
    for remote_path in remote_files:
        if not remote_path.endswith(".json") or remote_path.endswith(".meta.json"):
            continue
        name = remote_path.rsplit("/", 1)[-1]
        draft_id = name[: -len(".json")]
        try:
            validate_safe_id(draft_id, label="draft_id")
        except ValueError:
            logger.warning("Skipping remote draft with unsafe id: %r", draft_id)
            continue
        try:
            payload = storage.read_bytes(remote_path)
        except Exception:
            logger.exception("Could not read remote draft %s", remote_path)
            continue
        remote_ids.add(draft_id)
        local_path = paths.workspace_drafts_dir / name
        if local_path.exists() and local_path.read_bytes() == payload:
            continue
        try:
            local_path.write_bytes(payload)
            updated += 1
        except OSError:
            logger.exception("Could not write local draft %s", local_path)

    local_ids: set[str] = set()
    for path in paths.workspace_drafts_dir.glob("*.json"):
        if path.is_file():
            local_ids.add(path.stem)

    deleted = 0
    for draft_id in last_known - remote_ids:
        if draft_id not in local_ids:
            continue
        try:
            (paths.workspace_drafts_dir / f"{draft_id}.json").unlink()
            local_ids.discard(draft_id)
            deleted += 1
        except OSError:
            logger.exception("Could not delete local draft %s", draft_id)

    uploaded = 0
    for draft_id in local_ids - remote_ids - last_known:
        local_path = paths.workspace_drafts_dir / f"{draft_id}.json"
        if mirror_draft_to_cloud(draft_id, local_path):
            remote_ids.add(draft_id)
            uploaded += 1

    return {
        "current_ids": remote_ids,
        "updated": updated,
        "deleted": deleted,
        "uploaded": uploaded,
    }
