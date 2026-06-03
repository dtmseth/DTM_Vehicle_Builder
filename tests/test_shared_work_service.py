"""Tests for shared_work_service — the SharePoint mirror for projects + drafts.

Every public function must be safe to call regardless of cloud state.
Local-mode tests verify no-op behavior. Cloud-mode tests verify the
content actually flows in both directions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.adapters.interfaces import UserIdentity
from dtm_buildsheet.app.adapters.noop import (
    InMemoryChangeProposalGateway,
    NoOpNotificationGateway,
)
from dtm_buildsheet.app.adapters.wiring import AdapterBundle, set_active_bundle
from dtm_buildsheet.app.services import shared_work_service
from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.storage.base import StorageProvider


# ── Fakes ────────────────────────────────────────────────────────────────────


class _FakeRemote(StorageProvider):
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: str, data: str) -> None:
        self.files[path] = data.encode("utf-8")

    def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_bytes(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def delete(self, path: str) -> None:
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]

    def list_files(self, directory: str) -> list[str]:
        directory = directory.strip("/")
        prefix = f"{directory}/" if directory else ""
        return [p for p in self.files if p.startswith(prefix) and "/" not in p[len(prefix):]]


class _StubIdentity:
    def is_signed_in(self): return True
    def current_user(self):
        return UserIdentity("u1", "Test", "test@example.invalid", "stub")
    def signin(self): return self.current_user()
    def signout(self): pass


def _make_bundle(*, storage):
    return AdapterBundle(
        storage=storage,
        identity=_StubIdentity(),
        proposals=InMemoryChangeProposalGateway(),
        notifications=NoOpNotificationGateway(),
    )


@pytest.fixture(autouse=True)
def reset_bundle():
    yield
    wiring._active_bundle = None  # noqa: SLF001


@pytest.fixture
def cloud_off(monkeypatch):
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: False)


@pytest.fixture
def cloud_on(monkeypatch):
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    p = AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=tmp_path / "projects",
        workspace_drafts_dir=tmp_path / "drafts",
    )
    p.workspace_projects_dir.mkdir(parents=True, exist_ok=True)
    p.workspace_drafts_dir.mkdir(parents=True, exist_ok=True)
    return p


# ── Outbound mirror ──────────────────────────────────────────────────────────


def test_mirror_project_is_noop_when_cloud_disabled(cloud_off, paths):
    project_dir = paths.workspace_projects_dir / "proj-1"
    project_dir.mkdir()
    local = project_dir / "project.json"
    local.write_text('{"hello": "world"}', "utf-8")
    assert shared_work_service.mirror_project_to_cloud("proj-1", local) is False


def test_mirror_project_uploads_to_sharepoint(cloud_on, paths):
    remote = _FakeRemote()
    set_active_bundle(_make_bundle(storage=remote))

    project_dir = paths.workspace_projects_dir / "proj-1"
    project_dir.mkdir()
    local = project_dir / "project.json"
    local.write_text('{"name": "Test Project"}', "utf-8")

    assert shared_work_service.mirror_project_to_cloud("proj-1", local) is True
    assert "Projects/proj-1.json" in remote.files
    assert remote.files["Projects/proj-1.json"] == b'{"name": "Test Project"}'


def test_mirror_draft_uploads_to_sharepoint(cloud_on, paths):
    remote = _FakeRemote()
    set_active_bundle(_make_bundle(storage=remote))

    local = paths.workspace_drafts_dir / "draft-abc.json"
    local.write_text('{"draft_id": "draft-abc"}', "utf-8")

    assert shared_work_service.mirror_draft_to_cloud("draft-abc", local) is True
    assert "Drafts/draft-abc.json" in remote.files


def test_mirror_rejects_unsafe_ids(cloud_on, paths):
    """Path traversal in record_id must not write anywhere on SharePoint."""
    remote = _FakeRemote()
    set_active_bundle(_make_bundle(storage=remote))
    bogus = paths.workspace_drafts_dir / "weird.json"
    bogus.write_text("{}", "utf-8")
    assert shared_work_service.mirror_draft_to_cloud("../escape", bogus) is False
    assert remote.files == {}


def test_mirror_skips_missing_local_file(cloud_on, paths):
    remote = _FakeRemote()
    set_active_bundle(_make_bundle(storage=remote))
    # Path doesn't exist; mirror returns False without raising.
    assert shared_work_service.mirror_project_to_cloud(
        "proj-1", paths.workspace_projects_dir / "proj-1" / "project.json"
    ) is False


# ── Inbound sync ─────────────────────────────────────────────────────────────


def test_sync_work_data_is_noop_when_cloud_disabled(cloud_off, paths):
    report = shared_work_service.sync_work_data(paths)
    assert report == {
        "projects_updated": 0,
        "drafts_updated": 0,
        "skipped_local_mode": True,
    }


def test_sync_pulls_projects_into_workspace(cloud_on, paths):
    remote = _FakeRemote()
    remote.files["Projects/proj-a.json"] = b'{"name": "A"}'
    remote.files["Projects/proj-b.json"] = b'{"name": "B"}'
    set_active_bundle(_make_bundle(storage=remote))

    report = shared_work_service.sync_work_data(paths)
    assert report["projects_updated"] == 2

    assert (paths.workspace_projects_dir / "proj-a" / "project.json").read_bytes() == b'{"name": "A"}'
    assert (paths.workspace_projects_dir / "proj-b" / "project.json").read_bytes() == b'{"name": "B"}'


def test_sync_skips_unchanged_files(cloud_on, paths):
    """Byte-for-byte equality means we don't write through unchanged content."""
    remote = _FakeRemote()
    remote.files["Drafts/draft-1.json"] = b'{"x": 1}'
    set_active_bundle(_make_bundle(storage=remote))

    # First sync: writes locally.
    r1 = shared_work_service.sync_work_data(paths)
    assert r1["drafts_updated"] == 1
    # Second sync: same content remotely, no write counted.
    r2 = shared_work_service.sync_work_data(paths)
    assert r2["drafts_updated"] == 0


def test_sync_updates_when_remote_changes(cloud_on, paths):
    remote = _FakeRemote()
    remote.files["Drafts/draft-1.json"] = b'{"v": 1}'
    set_active_bundle(_make_bundle(storage=remote))
    shared_work_service.sync_work_data(paths)

    # Remote gets a new version; next sync picks it up.
    remote.files["Drafts/draft-1.json"] = b'{"v": 2}'
    r = shared_work_service.sync_work_data(paths)
    assert r["drafts_updated"] == 1
    assert (paths.workspace_drafts_dir / "draft-1.json").read_bytes() == b'{"v": 2}'


def test_sync_ignores_unsafe_remote_ids(cloud_on, paths):
    remote = _FakeRemote()
    remote.files["Projects/safe.json"] = b'{"safe": true}'
    remote.files["Projects/..escape.json"] = b'{"unsafe": true}'
    set_active_bundle(_make_bundle(storage=remote))

    report = shared_work_service.sync_work_data(paths)
    assert report["projects_updated"] == 1
    # The traversal candidate must not have landed anywhere on disk.
    assert not (paths.workspace_dir.parent / "escape.json").exists()


def test_sync_survives_missing_remote_folder(cloud_on, paths):
    """SharePoint /Projects/ never existing must not crash sync."""
    class _Missing(_FakeRemote):
        def list_files(self, directory):  # type: ignore[override]
            raise FileNotFoundError(directory)
    set_active_bundle(_make_bundle(storage=_Missing()))
    report = shared_work_service.sync_work_data(paths)
    assert report["projects_updated"] == 0
    assert report["drafts_updated"] == 0


# ── Delete ───────────────────────────────────────────────────────────────────


def test_delete_project_from_cloud_removes_remote_file(cloud_on):
    remote = _FakeRemote()
    remote.files["Projects/proj-x.json"] = b"{}"
    set_active_bundle(_make_bundle(storage=remote))
    assert shared_work_service.delete_project_from_cloud("proj-x") is True
    assert "Projects/proj-x.json" not in remote.files


def test_delete_returns_true_when_already_gone(cloud_on):
    remote = _FakeRemote()
    set_active_bundle(_make_bundle(storage=remote))
    # File doesn't exist remotely; delete is idempotent.
    assert shared_work_service.delete_project_from_cloud("ghost") is True
