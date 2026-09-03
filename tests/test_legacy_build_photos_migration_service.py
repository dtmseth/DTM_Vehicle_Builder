from __future__ import annotations

import json

import pytest

from dtm_buildsheet.app.services import agency_service
from dtm_buildsheet.app.services.legacy_build_photos_migration_service import (
    JOINT_AGENCY_ABBREVIATION,
    JOINT_AGENCY_NAME,
    LEGACY_PHOTO_GROUPS,
    create_completed_projects,
    ensure_joint_agency,
)
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path):
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=tmp_path / "projects",
        workspace_drafts_dir=tmp_path / "drafts",
        workspace_output_dir=tmp_path / "output",
    )


@pytest.fixture(autouse=True)
def _clear_agency_cache():
    agency_service._cache.clear()
    yield
    agency_service._cache.clear()


def _seed_reviewed_agencies(paths):
    names = sorted({group.agency_name for group in LEGACY_PHOTO_GROUPS})
    for index, name in enumerate(names):
        if name == JOINT_AGENCY_NAME:
            continue
        result = agency_service.handle_save_agency({
            "agency_id": f"agency-{index}",
            "name": name,
        }, paths)
        assert result["ok"] is True


def test_joint_agency_creation_is_idempotent_and_never_requires_qb(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    mirrored = []
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.legacy_build_photos_migration_service.save_setting_to_cloud",
        lambda target, payload: mirrored.append((target, payload)) or True,
    )

    first, created = ensure_joint_agency(paths, mirror_to_cloud=True)
    second, created_again = ensure_joint_agency(paths, mirror_to_cloud=True)

    assert created is True
    assert created_again is False
    assert first.agency_id == second.agency_id
    assert first.name == JOINT_AGENCY_NAME
    assert first.abbreviation == JOINT_AGENCY_ABBREVIATION
    assert len(agency_service.load_agencies(paths)) == 1
    assert len(mirrored) == 2


def test_sparse_completed_projects_are_deterministic_and_idempotent(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _seed_reviewed_agencies(paths)
    ensure_joint_agency(paths, mirror_to_cloud=False)
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.shared_work_service.mirror_project_to_cloud_in_background",
        lambda *_args: None,
    )

    first = create_completed_projects(paths, completed_at="2026-08-27T00:00:00+00:00")
    second = create_completed_projects(paths, completed_at="2026-08-27T00:00:00+00:00")

    assert first["project_count"] == 35
    assert first["group_count"] == 46
    assert len(first["created"]) == 35
    assert second["created"] == []
    assert second["updated"] == []
    project_files = sorted((tmp_path / "projects").glob("*/project.json"))
    assert len(project_files) == 35
    payloads = [json.loads(path.read_text("utf-8")) for path in project_files]
    assert sum(len(item["build_units"]) for item in payloads) == 46
    assert {item["project_status"] for item in payloads} == {"completed"}
    assert {item["completed_by"] for item in payloads} == {"Legacy Build Photos migration"}
