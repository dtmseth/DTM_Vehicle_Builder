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
import os
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
#
# Schema v2 (current) additionally stores per-file eTags so we can skip the
# content fetch when the cloud copy is provably unchanged. The eTag is
# whatever Graph returned at the last sync; if it matches what Graph
# returns now, the file hasn't changed and we can leave local alone.
# Schema v1 (just lists of IDs) auto-upgrades on first sync — every file
# is considered "missing eTag" and falls through to the slow-path
# content-fetch, populating eTags as it goes.
_STATE_FILENAME = ".cloud_state.json"
_STATE_SCHEMA_VERSION = 2


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
    import threading
    threading.Thread(
        target=mirror_project_to_cloud,
        args=(project_id, local_path),
        daemon=True,
        name=f"mirror-project-{project_id}",
    ).start()


def mirror_draft_to_cloud_in_background(draft_id: str, local_path: Path) -> None:
    import threading
    threading.Thread(
        target=mirror_draft_to_cloud,
        args=(draft_id, local_path),
        daemon=True,
        name=f"mirror-draft-{draft_id}",
    ).start()


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
    proj = _reconcile_projects(storage, paths, _state_as_etag_map(state.get("projects")))
    draf = _reconcile_drafts(storage, paths, _state_as_etag_map(state.get("drafts")))
    _save_state(paths, {
        "schema_version": _STATE_SCHEMA_VERSION,
        "projects": proj["current_etags"],
        "drafts":   draf["current_etags"],
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


# ── Reconciliation: projects ─────────────────────────────────────────────────


def _reconcile_projects(storage, paths: AppPaths, last_known: dict[str, str]) -> dict:
    return _reconcile_records(
        storage,
        paths,
        last_known,
        remote_folder=PROJECTS_REMOTE_FOLDER,
        id_label="project_id",
        local_record_path=lambda paths_, rid: paths_.workspace_projects_dir / rid / "project.json",
        list_local_ids=_list_local_project_ids,
        delete_local=_delete_local_project,
        mirror_to_cloud=mirror_project_to_cloud,
        ensure_local_root=lambda paths_: paths_.workspace_projects_dir.mkdir(parents=True, exist_ok=True),
    )


# ── Reconciliation: drafts ───────────────────────────────────────────────────


def _reconcile_drafts(storage, paths: AppPaths, last_known: dict[str, str]) -> dict:
    return _reconcile_records(
        storage,
        paths,
        last_known,
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
        logger.exception("Could not list remote %s; keeping last-known state", remote_folder)
        return {"current_etags": last_known, "updated": 0, "deleted": 0, "uploaded": 0}

    # Step 1: walk the cloud listing. eTag match against state means we
    # know the cloud copy is unchanged AND we know local should also be
    # up-to-date (we wrote that eTag last time we synced it). Skip the
    # fetch entirely — this is the fast path for typical 60s cycles where
    # nothing has changed.
    remote_etags: dict[str, str] = {}
    updated = 0
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
        if entry.etag and prior_etag == entry.etag and local_path.exists():
            # Fast path: cloud unchanged since last sync, local present.
            continue
        try:
            payload = storage.read_bytes(remote_path)
        except Exception:
            logger.exception("Could not read remote %s %s", id_label, remote_path)
            # Preserve the prior etag so we try again next iteration.
            if prior_etag:
                remote_etags[record_id] = prior_etag
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if local_path.exists() and local_path.read_bytes() == payload:
            continue
        try:
            local_path.write_bytes(payload)
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
            deleted += 1
        except OSError:
            logger.exception("Could not delete local %s %s", id_label, record_id)

    # Step 3: local-only files → upload them so cloud becomes the union.
    uploaded = 0
    for record_id in local_ids - remote_ids - set(last_known):
        local_path = local_record_path(paths, record_id)
        if mirror_to_cloud(record_id, local_path):
            # First sync after upload: we don't know the eTag yet (Graph
            # returns it but write_text doesn't surface it). Mark with
            # empty string so the NEXT sync's listing fills in the eTag.
            remote_etags[record_id] = ""
            uploaded += 1

    return {
        "current_etags": remote_etags,
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
