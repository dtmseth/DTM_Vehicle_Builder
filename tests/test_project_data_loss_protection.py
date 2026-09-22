"""Focused regression coverage for high-value project-note persistence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.services.project_service import (
    handle_save_individual_notes,
    handle_save_project,
)
from dtm_buildsheet.app.services.shared_work_service import (
    _merge_project_note_data,
    _write_project_to_cloud_losslessly,
)
from dtm_buildsheet.inputs.project_entry import (
    ProjectWriteConflict,
    load_project,
    save_project,
)
from dtm_buildsheet.paths import AppPaths, BUNDLED_PRESETS_DIR


def _paths(tmp_path: Path) -> AppPaths:
    projects = tmp_path / "projects"
    drafts = tmp_path / "drafts"
    projects.mkdir()
    drafts.mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=projects,
        workspace_drafts_dir=drafts,
        bundled_presets_dir=BUNDLED_PRESETS_DIR,
        workspace_presets_dir=tmp_path / "presets",
    )


def _body(*, notes: str = "Original build note", project_notes: str = "") -> dict:
    return {
        "customer": {"agency": "Test PD", "build_year": "2026"},
        "project_notes": project_notes,
        "build_units": [{
            "unit_id": "patrol",
            "vehicle_model": "PIU",
            "build_type": "Patrol",
            "quantity": 1,
            "individuals": [{
                "individual_id": "vehicle-1",
                "notes": notes,
            }],
        }],
    }


def test_stale_whole_project_save_cannot_blank_existing_build_note(tmp_path):
    paths = _paths(tmp_path)
    created = handle_save_project(_body(), paths)
    loaded = load_project(created["project_id"], paths)
    revision = loaded.updated_at

    result = handle_save_project({
        "project_id": created["project_id"],
        "expected_updated_at": revision,
        "expected_record_revision": loaded.record_revision,
        "build_units": [{
            "unit_id": "patrol",
            "vehicle_model": "PIU",
            "build_type": "Patrol",
            "quantity": 1,
            "individuals": [{"individual_id": "vehicle-1", "notes": ""}],
        }],
    }, paths)

    assert result["ok"] is False
    assert result["error_code"] == "unit_notes_precondition_required"
    saved = load_project(created["project_id"], paths)
    assert saved.build_units[0].individuals[0].notes == "Original build note"


def test_compare_and_set_note_edit_retains_prior_value_and_rejects_stale_retry(tmp_path):
    paths = _paths(tmp_path)
    created = handle_save_project(_body(), paths)
    project_id = created["project_id"]

    changed = handle_save_individual_notes(
        project_id,
        "patrol",
        "vehicle-1",
        {"notes": "Updated build note", "expected_notes": "Original build note"},
        paths,
    )
    stale = handle_save_individual_notes(
        project_id,
        "patrol",
        "vehicle-1",
        {"notes": "", "expected_notes": "Original build note"},
        paths,
    )

    assert changed["ok"] is True
    assert changed["notes_updated_at"]
    assert stale["ok"] is False
    assert stale["error_code"] == "stale_unit_notes"
    saved = load_project(project_id, paths).build_units[0].individuals[0]
    assert saved.notes == "Updated build note"
    assert [entry["notes"] for entry in saved.notes_history] == ["Original build note"]


def test_explicit_current_note_clear_is_versioned_and_recoverable(tmp_path):
    paths = _paths(tmp_path)
    created = handle_save_project(_body(), paths)

    result = handle_save_individual_notes(
        created["project_id"],
        "patrol",
        "vehicle-1",
        {"notes": "", "expected_notes": "Original build note"},
        paths,
    )

    assert result["ok"] is True
    saved = load_project(created["project_id"], paths).build_units[0].individuals[0]
    assert saved.notes == ""
    assert saved.notes_updated_at
    assert saved.notes_history[-1]["notes"] == "Original build note"


def test_stale_whole_project_save_cannot_blank_project_note(tmp_path):
    paths = _paths(tmp_path)
    created = handle_save_project(_body(project_notes="Keep indoors until pickup."), paths)
    loaded = load_project(created["project_id"], paths)
    revision = loaded.updated_at

    result = handle_save_project({
        "project_id": created["project_id"],
        "expected_updated_at": revision,
        "expected_record_revision": loaded.record_revision,
        "project_notes": "",
    }, paths)

    assert result["ok"] is False
    assert result["error_code"] == "project_notes_precondition_required"
    assert load_project(created["project_id"], paths).project_notes == "Keep indoors until pickup."


def test_stale_project_revision_blocks_all_whole_record_changes(tmp_path):
    paths = _paths(tmp_path)
    created = handle_save_project(_body(), paths)
    stale = load_project(created["project_id"], paths)
    stale_revision = stale.updated_at
    stale_record_revision = stale.record_revision
    handle_save_individual_notes(
        created["project_id"],
        "patrol",
        "vehicle-1",
        {"notes": "Newer note", "expected_notes": "Original build note"},
        paths,
    )

    result = handle_save_project({
        "project_id": created["project_id"],
        "expected_updated_at": stale_revision,
        "expected_record_revision": stale_record_revision,
        "customer": {"agency": "Stale overwrite"},
    }, paths)

    assert result["ok"] is False
    assert result["error_code"] == "stale_project_revision"
    saved = load_project(created["project_id"], paths)
    assert saved.customer.agency == "Test PD"
    assert saved.build_units[0].individuals[0].notes == "Newer note"


def test_storage_rejects_stale_background_writer_and_archives_prior_version(tmp_path):
    paths = _paths(tmp_path)
    created = handle_save_project(_body(), paths)
    first = load_project(created["project_id"], paths)
    stale_background_copy = load_project(created["project_id"], paths)
    first.customer.contact = "Current contact"
    save_project(first, paths)

    stale_background_copy.company_folder_status = "provisioned"
    with pytest.raises(ProjectWriteConflict):
        save_project(stale_background_copy, paths)

    saved = load_project(created["project_id"], paths)
    assert saved.customer.contact == "Current contact"
    assert saved.company_folder_status != "provisioned"
    assert list((paths.workspace_projects_dir / created["project_id"] / ".history").glob("*.json"))


class _VersionedCloud:
    def __init__(self, content: str, revision: str = "etag-1") -> None:
        self.content = content
        self.revision = revision

    def read_versioned_text(self, _path: str):
        return self.content, self.revision

    def write_versioned_text(self, _path: str, content: str, expected: str):
        assert expected == self.revision
        self.content = content
        self.revision = "etag-2"
        return self.revision


def test_cloud_project_compare_and_set_blocks_cross_device_overwrite(tmp_path):
    local_path = tmp_path / "projects" / "project-1" / "project.json"
    local_path.parent.mkdir(parents=True)
    local = {
        "project_id": "project-1",
        "created_at": "2026-09-21T00:00:00+00:00",
        "updated_at": "2026-09-21T03:00:00+00:00",
        "record_revision": "local-new",
        "record_parent_revision": "common-base",
        "customer": {"agency": "Local edit"},
    }
    remote = {
        "project_id": "project-1",
        "created_at": "2026-09-21T00:00:00+00:00",
        "updated_at": "2026-09-21T02:00:00+00:00",
        "record_revision": "remote-new",
        "record_parent_revision": "common-base",
        "customer": {"agency": "Remote edit"},
    }
    local_text = json.dumps(local, indent=2) + "\n"
    remote_text = json.dumps(remote, indent=2) + "\n"
    local_path.write_text(local_text)
    cloud = _VersionedCloud(remote_text)

    saved = _write_project_to_cloud_losslessly(
        cloud, "Projects/project-1.json", local_text, local_path
    )

    assert saved is False
    assert json.loads(cloud.content)["customer"]["agency"] == "Remote edit"
    assert json.loads(local_path.read_text())["customer"]["agency"] == "Local edit"
    assert (local_path.parent / ".sync_conflict.json").exists()
    assert len(list((local_path.parent / ".history").glob("*.json"))) == 2


def test_cloud_project_compare_and_set_accepts_direct_descendant(tmp_path):
    local_path = tmp_path / "projects" / "project-1" / "project.json"
    local_path.parent.mkdir(parents=True)
    remote = {
        "project_id": "project-1",
        "updated_at": "2026-09-21T01:00:00+00:00",
        "record_revision": "common-base",
    }
    local = {
        "project_id": "project-1",
        "updated_at": "2026-09-21T02:00:00+00:00",
        "record_revision": "local-new",
        "record_parent_revision": "common-base",
    }
    local_text = json.dumps(local, indent=2) + "\n"
    local_path.write_text(local_text)
    cloud = _VersionedCloud(json.dumps(remote, indent=2) + "\n")

    saved = _write_project_to_cloud_losslessly(
        cloud, "Projects/project-1.json", local_text, local_path
    )

    assert saved is True
    assert json.loads(cloud.content)["record_revision"] == "local-new"


def test_cloud_compare_and_set_accepts_coalesced_descendant(tmp_path):
    local_path = tmp_path / "projects" / "project-1" / "project.json"
    local_path.parent.mkdir(parents=True)
    remote = {
        "project_id": "project-1",
        "updated_at": "2026-09-21T01:00:00+00:00",
        "record_revision": "cloud-base",
    }
    local = {
        "project_id": "project-1",
        "updated_at": "2026-09-21T03:00:00+00:00",
        "record_revision": "local-third-save",
        "record_parent_revision": "local-second-save",
        "record_ancestor_revisions": ["local-second-save", "local-first-save", "cloud-base"],
    }
    local_text = json.dumps(local, indent=2) + "\n"
    local_path.write_text(local_text)
    cloud = _VersionedCloud(json.dumps(remote, indent=2) + "\n")

    saved = _write_project_to_cloud_losslessly(
        cloud, "Projects/project-1.json", local_text, local_path
    )

    assert saved is True
    assert json.loads(cloud.content)["record_revision"] == "local-third-save"


def test_cloud_etag_race_preserves_local_and_winning_remote_versions(tmp_path):
    local_path = tmp_path / "projects" / "project-1" / "project.json"
    local_path.parent.mkdir(parents=True)
    base = {
        "project_id": "project-1",
        "updated_at": "2026-09-21T01:00:00+00:00",
        "record_revision": "common-base",
    }
    local = {
        **base,
        "updated_at": "2026-09-21T02:00:00+00:00",
        "record_revision": "local-new",
        "record_parent_revision": "common-base",
    }
    winning_remote = {
        **base,
        "updated_at": "2026-09-21T02:00:01+00:00",
        "record_revision": "remote-new",
        "record_parent_revision": "common-base",
    }
    local_text = json.dumps(local, indent=2) + "\n"
    local_path.write_text(local_text)

    class RacingCloud(_VersionedCloud):
        def write_versioned_text(self, _path: str, _content: str, _expected: str):
            self.content = json.dumps(winning_remote, indent=2) + "\n"
            self.revision = "etag-2"
            raise RuntimeError("precondition failed")

    cloud = RacingCloud(json.dumps(base, indent=2) + "\n")

    saved = _write_project_to_cloud_losslessly(
        cloud, "Projects/project-1.json", local_text, local_path
    )

    assert saved is False
    assert json.loads(local_path.read_text())["record_revision"] == "local-new"
    assert json.loads(cloud.content)["record_revision"] == "remote-new"
    assert (local_path.parent / ".sync_conflict.json").exists()
    revisions = {
        json.loads(path.read_text())["record_revision"]
        for path in (local_path.parent / ".history").glob("*.json")
    }
    assert revisions == {"local-new", "remote-new"}


def _project_payload(
    *,
    note: str,
    record_updated: str,
    note_updated: str = "",
    history: list[dict[str, str]] | None = None,
    record_revision: str = "",
) -> bytes:
    return (json.dumps({
        "project_id": "project-1",
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": record_updated,
        "record_revision": record_revision,
        "customer": {},
        "preferences": {},
        "project_notes": "",
        "build_units": [{
            "unit_id": "patrol",
            "individuals": [{
                "individual_id": "vehicle-1",
                "notes": note,
                "notes_updated_at": note_updated,
                "notes_history": history or [],
            }],
        }],
    }, indent=2) + "\n").encode()


def test_cloud_merge_recovers_legacy_nonempty_note_from_stale_blank():
    local = _project_payload(
        note="Recovered build note",
        record_updated="2026-09-21T14:52:33+00:00",
        record_revision="local-revision",
    )
    remote = _project_payload(
        note="",
        record_updated="2026-09-21T19:08:59+00:00",
        record_revision="remote-revision",
    )

    merged = json.loads(_merge_project_note_data(local, remote))
    individual = merged["build_units"][0]["individuals"][0]

    assert individual["notes"] == "Recovered build note"
    assert individual["notes_updated_at"] == "2026-09-21T14:52:33+00:00"
    assert merged["record_parent_revision"] == "remote-revision"
    assert merged["record_revision"] not in {"local-revision", "remote-revision"}


def test_cloud_merge_honors_newer_explicit_clear_and_keeps_prior_text():
    local = _project_payload(
        note="Prior build note",
        note_updated="2026-09-21T14:52:33+00:00",
        record_updated="2026-09-21T14:52:33+00:00",
    )
    remote = _project_payload(
        note="",
        note_updated="2026-09-21T19:08:59+00:00",
        record_updated="2026-09-21T19:08:59+00:00",
    )

    merged = json.loads(_merge_project_note_data(local, remote))
    individual = merged["build_units"][0]["individuals"][0]

    assert individual["notes"] == ""
    assert individual["notes_updated_at"] == "2026-09-21T19:08:59+00:00"
    assert [entry["notes"] for entry in individual["notes_history"]] == ["Prior build note"]
