"""Persistence layer for ProjectRecord objects.

Projects live at:  workspace/projects/{project_id}/project.json

Each project gets its own sub-directory so future phases can drop additional
artifacts (generated PPTX, draft snapshots, etc.) next to the record without
polluting the flat projects list.
"""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..domain.project_codec import project_from_dict
from ..domain.project_models import BuildUnit, CustomerInfo, EquipmentPreferences, ProjectRecord
from ..paths import AppPaths
from ..storage.local import LocalStorageProvider
from ..storage.safety import assert_within_root, validate_safe_id


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


def save_project(project: ProjectRecord, paths: AppPaths) -> Path:
    """Persist *project* to disk and update its updated_at timestamp."""
    validate_safe_id(project.project_id, label="project_id")
    project.updated_at = _utcnow()
    path = _project_path(project.project_id, paths)
    LocalStorageProvider().write_text(str(path), json.dumps(asdict(project), indent=2) + "\n")
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
    return project_from_dict(data)


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
            results.append(project_from_dict(data))
        except Exception:
            pass
    results.sort(key=lambda p: p.updated_at, reverse=True)
    return results


def delete_project(project_id: str, paths: AppPaths) -> None:
    """Remove a project and its directory entirely.

    Raises FileNotFoundError if the project does not exist.
    """
    validate_safe_id(project_id, label="project_id")
    project_dir = _project_dir(project_id, paths)
    assert_within_root(project_dir, paths.workspace_projects_dir)
    if not project_dir.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    shutil.rmtree(project_dir)
