"""Persistence layer for ProjectRecord objects.

Projects live at:  workspace/projects/{project_id}/project.json

Each project gets its own sub-directory so future phases can drop additional
artifacts (generated PPTX, draft snapshots, etc.) next to the record without
polluting the flat projects list.
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..domain.project_codec import project_from_dict
from ..domain.project_models import BuildUnit, CustomerInfo, EquipmentPreferences, ProjectRecord
from ..paths import AppPaths, relativize_output_path, resolve_output_path
from ..storage.local import LocalStorageProvider
from ..storage.safety import assert_within_root, validate_safe_id

_log = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── directory helpers ──────────────────────────────────────────────────────────

def _project_dir(project_id: str, paths: AppPaths) -> Path:
    return paths.workspace_projects_dir / project_id


def _project_path(project_id: str, paths: AppPaths) -> Path:
    return _project_dir(project_id, paths) / "project.json"


# ── public API ─────────────────────────────────────────────────────────────────

def new_project(
    project_id: str | None = None,
    customer: CustomerInfo | None = None,
    preferences: EquipmentPreferences | None = None,
    build_units: list[BuildUnit] | None = None,
) -> ProjectRecord:
    now = _utcnow()
    if project_id is None:
        pid = str(uuid.uuid4())
    else:
        validate_safe_id(project_id, label="project_id")
        pid = project_id.strip()
    return ProjectRecord(
        project_id=pid,
        created_at=now,
        updated_at=now,
        customer=customer or CustomerInfo(),
        preferences=preferences or EquipmentPreferences(),
        build_units=build_units or [],
    )


def _project_to_dict_portable(project: ProjectRecord, paths: AppPaths) -> dict:
    """Serialize to dict with output_path fields relativized to the workspace."""
    data = asdict(project)
    workspace = paths.workspace_dir
    for unit in data.get("build_units", []):
        if "output_path" in unit:
            unit["output_path"] = relativize_output_path(unit["output_path"], workspace)
        for ind in unit.get("individuals", []):
            if "output_path" in ind:
                ind["output_path"] = relativize_output_path(ind["output_path"], workspace)
    return data


def _project_from_dict_resolved(data: dict, paths: AppPaths) -> ProjectRecord:
    """Build a ProjectRecord with output_path fields resolved to absolute paths."""
    project = project_from_dict(data)
    workspace = paths.workspace_dir
    for unit in project.build_units:
        unit.output_path = resolve_output_path(unit.output_path, workspace)
        for ind in unit.individuals:
            ind.output_path = resolve_output_path(ind.output_path, workspace)
    return project


def save_project(project: ProjectRecord, paths: AppPaths) -> Path:
    """Persist *project* to disk and update its updated_at timestamp.

    In cloud mode, also mirrors the file up to SharePoint /Projects/
    immediately so teammates' next sync pass picks it up. Mirror failure
    is logged but doesn't fail the save — the periodic sync loop retries.
    """
    validate_safe_id(project.project_id, label="project_id")
    project.updated_at = _utcnow()
    path = _project_path(project.project_id, paths)
    data = _project_to_dict_portable(project, paths)
    LocalStorageProvider().write_text(str(path), json.dumps(data, indent=2) + "\n")
    # Deferred import to avoid a circular dependency at module import time
    # (services → inputs is the established direction; this module is in
    # inputs and shared_work_service is in services).
    # Fire-and-forget so the local save returns instantly. sync_work_data's
    # 60s timer is the safety net for any mirror that fails in the background.
    from ..app.services.shared_work_service import mirror_project_to_cloud_in_background
    mirror_project_to_cloud_in_background(project.project_id, path)
    return path


def save_project_operational_state(project: ProjectRecord, paths: AppPaths) -> Path:
    """Persist folder/publication metadata without making the design stale.

    ``updated_at`` represents user-authored project/build content and is used
    by render staleness checks. Background SharePoint provisioning must not
    advance it merely because an item ID, retry state, or portable path was
    learned after the PDF was generated.
    """
    validate_safe_id(project.project_id, label="project_id")
    path = _project_path(project.project_id, paths)
    data = _project_to_dict_portable(project, paths)
    LocalStorageProvider().write_text(str(path), json.dumps(data, indent=2) + "\n")
    from ..app.services.shared_work_service import mirror_project_to_cloud_in_background
    mirror_project_to_cloud_in_background(project.project_id, path)
    return path


def load_project(project_id: str, paths: AppPaths) -> ProjectRecord:
    """Load a project by ID.

    Raises FileNotFoundError if not found, ValueError if the file is malformed.
    """
    validate_safe_id(project_id, label="project_id")
    path = _project_path(project_id, paths)
    if not path.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    data = json.loads(LocalStorageProvider().read_text(str(path)))
    return _project_from_dict_resolved(data, paths)


def list_projects(paths: AppPaths) -> list[ProjectRecord]:
    """Return all projects sorted newest-first by updated_at; silently skips corrupt files."""
    projects_root = paths.workspace_projects_dir
    if not projects_root.exists():
        return []
    results: list[ProjectRecord] = []
    for project_dir in sorted(projects_root.iterdir()):
        if not project_dir.is_dir():
            continue
        record_file = project_dir / "project.json"
        if not record_file.exists():
            continue
        try:
            data = json.loads(LocalStorageProvider().read_text(str(record_file)))
            results.append(_project_from_dict_resolved(data, paths))
        except Exception:
            _log.exception("Skipping corrupt project file: %s", record_file)
    results.sort(key=lambda p: p.updated_at, reverse=True)
    return results


def delete_project(project_id: str, paths: AppPaths) -> None:
    """Remove a project and its directory entirely.

    Raises FileNotFoundError if the project does not exist. Also removes
    the cloud mirror in cloud mode — last-writer-wins applies to deletes
    too, so teammates' next sync drops the file from their workspace.
    """
    validate_safe_id(project_id, label="project_id")
    project_dir = _project_dir(project_id, paths)
    assert_within_root(project_dir, paths.workspace_projects_dir)
    if not project_dir.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    shutil.rmtree(project_dir)
    from ..app.services.shared_work_service import delete_project_from_cloud
    delete_project_from_cloud(project_id)
