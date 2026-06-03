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
from pathlib import Path

from ...paths import AppPaths
from ...storage.safety import validate_safe_id
from ..adapters import wiring

logger = logging.getLogger(__name__)


PROJECTS_REMOTE_FOLDER = "Projects"
DRAFTS_REMOTE_FOLDER = "Drafts"


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
    """Pull every project + draft from SharePoint to the local workspace.

    Returns a small report dict that the periodic loop logs. Never raises.
    Content equality decides whether a write happens — anything that
    matches the local copy byte-for-byte is skipped.
    """
    storage = _cloud_storage()
    if storage is None:
        return {"projects_updated": 0, "drafts_updated": 0, "skipped_local_mode": True}

    projects_updated = _sync_projects(storage, paths)
    drafts_updated = _sync_drafts(storage, paths)
    if projects_updated or drafts_updated:
        logger.info(
            "Synced work data: %d project(s), %d draft(s) updated",
            projects_updated, drafts_updated,
        )
    return {
        "projects_updated": projects_updated,
        "drafts_updated": drafts_updated,
        "skipped_local_mode": False,
    }


def _sync_projects(storage, paths: AppPaths) -> int:
    try:
        remote_files = storage.list_files(PROJECTS_REMOTE_FOLDER)
    except FileNotFoundError:
        return 0
    except Exception:
        logger.exception("Could not list remote projects")
        return 0

    updated = 0
    for remote_path in remote_files:
        if not remote_path.endswith(".json"):
            continue
        name = remote_path.rsplit("/", 1)[-1]
        project_id = name[:-len(".json")]
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

        local_dir = paths.workspace_projects_dir / project_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / "project.json"
        if local_path.exists() and local_path.read_bytes() == payload:
            continue
        try:
            local_path.write_bytes(payload)
            updated += 1
        except OSError:
            logger.exception("Could not write local project file %s", local_path)
    return updated


def _sync_drafts(storage, paths: AppPaths) -> int:
    try:
        remote_files = storage.list_files(DRAFTS_REMOTE_FOLDER)
    except FileNotFoundError:
        return 0
    except Exception:
        logger.exception("Could not list remote drafts")
        return 0

    updated = 0
    drafts_dir = paths.workspace_drafts_dir
    drafts_dir.mkdir(parents=True, exist_ok=True)
    for remote_path in remote_files:
        if not remote_path.endswith(".json"):
            continue
        name = remote_path.rsplit("/", 1)[-1]
        draft_id = name[:-len(".json")]
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

        local_path = drafts_dir / name
        if local_path.exists() and local_path.read_bytes() == payload:
            continue
        try:
            local_path.write_bytes(payload)
            updated += 1
        except OSError:
            logger.exception("Could not write local draft file %s", local_path)
    return updated
