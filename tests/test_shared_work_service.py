"""Tests for shared_work_service — the SharePoint mirror for projects + drafts.

Every public function must be safe to call regardless of cloud state.
Local-mode tests verify no-op behavior. Cloud-mode tests verify the
content actually flows in both directions.
"""

from __future__ import annotations

import hashlib
import threading
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
from dtm_buildsheet.storage.base import FileMetadata, StorageProvider


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


class _EtagRemote(_FakeRemote):
    """In-memory remote with stable content-derived etags."""

    def list_files_with_metadata(self, directory: str) -> list[FileMetadata]:
        return [
            FileMetadata(path=path, etag=hashlib.sha256(self.files[path]).hexdigest())
            for path in self.list_files(directory)
        ]


class _ReadTrackingRemote(_EtagRemote):
    """Records content reads so startup work can be kept deliberately small."""

    def __init__(self) -> None:
        super().__init__()
        self.read_paths: list[str] = []

    def read_bytes(self, path: str) -> bytes:
        self.read_paths.append(path)
        return super().read_bytes(path)


class _BlockingRemote(_EtagRemote):
    """Lets a test queue a second save while the first upload is in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.first_write_started = threading.Event()
        self.release_first_write = threading.Event()
        self.final_write_finished = threading.Event()
        self.writes: list[bytes] = []

    def write_text(self, path: str, data: str) -> None:
        self.writes.append(data.encode("utf-8"))
        if len(self.writes) == 1:
            self.first_write_started.set()
            assert self.release_first_write.wait(timeout=1)
        super().write_text(path, data)
        if len(self.writes) >= 2:
            self.final_write_finished.set()


class _FailingWriteRemote(_EtagRemote):
    """Remote whose upload path is temporarily unavailable."""

    def write_text(self, path: str, data: str) -> None:
        raise OSError("SharePoint upload failed")


class _StaleReadAfterWriteRemote(_EtagRemote):
    """Simulate Graph listing/read propagation lag immediately after a write."""

    def __init__(self) -> None:
        super().__init__()
        self._stale_payloads: dict[str, bytes] = {}

    def write_text(self, path: str, data: str) -> None:
        if path in self.files:
            self._stale_payloads[path] = self.files[path]
        super().write_text(path, data)

    def read_bytes(self, path: str) -> bytes:
        if path in self._stale_payloads:
            return self._stale_payloads.pop(path)
        return super().read_bytes(path)


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
    monkeypatch.setenv("DTM_ALLOW_CLOUD_IN_TESTS", "1")


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


def test_background_mirror_drains_to_the_newest_draft_snapshot(cloud_on, paths):
    remote = _BlockingRemote()
    set_active_bundle(_make_bundle(storage=remote))
    local = paths.workspace_drafts_dir / "draft-abc.json"
    local.write_text('{"revision": 1}', "utf-8")

    shared_work_service.mirror_draft_to_cloud_in_background("draft-abc", local)
    assert remote.first_write_started.wait(timeout=1)

    local.write_text('{"revision": 2}', "utf-8")
    shared_work_service.mirror_draft_to_cloud_in_background("draft-abc", local)
    remote.release_first_write.set()

    assert remote.final_write_finished.wait(timeout=1)
    assert remote.writes == [b'{"revision": 1}', b'{"revision": 2}']
    assert remote.files["Drafts/draft-abc.json"] == b'{"revision": 2}'


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
    assert report["skipped_local_mode"] is True


def test_sync_pulls_projects_into_workspace(cloud_on, paths):
    remote = _FakeRemote()
    remote.files["Projects/proj-a.json"] = b'{"name": "A"}'
    remote.files["Projects/proj-b.json"] = b'{"name": "B"}'
    set_active_bundle(_make_bundle(storage=remote))

    report = shared_work_service.sync_work_data(paths)
    assert report["projects_updated"] == 2

    assert (paths.workspace_projects_dir / "proj-a" / "project.json").read_bytes() == b'{"name": "A"}'
    assert (paths.workspace_projects_dir / "proj-b" / "project.json").read_bytes() == b'{"name": "B"}'


def test_project_first_sync_defers_historical_draft_downloads(cloud_on, paths):
    remote = _ReadTrackingRemote()
    remote.files["Projects/proj-a.json"] = b'{"name": "A"}'
    remote.files["Drafts/draft-1.json"] = b'{"draft_id": "draft-1"}'
    remote.files["Drafts/draft-2.json"] = b'{"draft_id": "draft-2"}'
    set_active_bundle(_make_bundle(storage=remote))

    report = shared_work_service.sync_work_data(paths, include_drafts=False)

    assert report["projects_updated"] == 1
    assert report["drafts_deferred"] is True
    assert not (paths.workspace_drafts_dir / "draft-1.json").exists()
    assert remote.read_paths == ["Projects/proj-a.json"]


def test_hydrate_draft_downloads_only_the_requested_build(cloud_on, paths):
    remote = _ReadTrackingRemote()
    remote.files["Drafts/draft-1.json"] = b'{"draft_id": "draft-1"}'
    remote.files["Drafts/draft-2.json"] = b'{"draft_id": "draft-2"}'
    set_active_bundle(_make_bundle(storage=remote))

    assert shared_work_service.hydrate_draft_from_cloud("draft-1", paths) is True

    assert (paths.workspace_drafts_dir / "draft-1.json").read_bytes() == remote.files["Drafts/draft-1.json"]
    assert not (paths.workspace_drafts_dir / "draft-2.json").exists()
    assert remote.read_paths == ["Drafts/draft-1.json"]


def test_refresh_keeps_a_newer_local_draft(cloud_on, paths):
    remote = _ReadTrackingRemote()
    remote.files["Drafts/draft-1.json"] = (
        b'{"draft_id":"draft-1","updated_at":"2026-08-06T10:00:00+00:00","parts":[]}'
    )
    local = paths.workspace_drafts_dir / "draft-1.json"
    local_payload = (
        b'{"draft_id":"draft-1","updated_at":"2026-08-06T12:00:00+00:00","parts":[{"name":"new"}]}'
    )
    local.write_bytes(local_payload)
    set_active_bundle(_make_bundle(storage=remote))

    assert shared_work_service.hydrate_draft_from_cloud("draft-1", paths, refresh=True) is True
    assert local.read_bytes() == local_payload


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


def test_sync_keeps_a_newer_local_save_when_remote_etag_is_unchanged(cloud_on, paths):
    """A failed background upload must not let the next sync erase a draft."""
    remote = _EtagRemote()
    remote.files["Drafts/draft-1.json"] = b'{"v": 1}'
    set_active_bundle(_make_bundle(storage=remote))
    shared_work_service.sync_work_data(paths)

    local = paths.workspace_drafts_dir / "draft-1.json"
    local.write_bytes(b'{"v": 2}')
    report = shared_work_service.sync_work_data(paths)

    assert report["drafts_updated"] == 0
    assert report["drafts_uploaded"] == 1
    assert local.read_bytes() == b'{"v": 2}'
    assert remote.files["Drafts/draft-1.json"] == b'{"v": 2}'


def test_v2_state_preserves_newer_local_draft_when_upload_fails(cloud_on, paths):
    """A v2→v3 migration must not repeat the old overwrite-loss bug."""
    remote = _FailingWriteRemote()
    remote.files["Drafts/draft-1.json"] = (
        b'{"draft_id":"draft-1","updated_at":"2026-08-06T10:00:00+00:00","parts":[]}'
    )
    local = paths.workspace_drafts_dir / "draft-1.json"
    local_payload = (
        b'{"draft_id":"draft-1","updated_at":"2026-08-06T12:00:00+00:00","parts":[{"name":"new"}]}'
    )
    local.write_bytes(local_payload)
    # The prior app wrote only eTags, so this mirrors the affected machines.
    (paths.workspace_dir / ".cloud_state.json").write_text(json.dumps({
        "schema_version": 2,
        "projects": {},
        "drafts": {"draft-1": "old-etag"},
    }))
    set_active_bundle(_make_bundle(storage=remote))

    report = shared_work_service.sync_work_data(paths)

    assert report["drafts_updated"] == 0
    assert report["drafts_uploaded"] == 0
    assert local.read_bytes() == local_payload
    # A second sync must keep protecting it until an upload can succeed.
    shared_work_service.sync_work_data(paths)
    assert local.read_bytes() == local_payload


def test_v2_state_uploads_newer_local_draft_before_it_can_be_overwritten(cloud_on, paths):
    remote = _EtagRemote()
    remote.files["Drafts/draft-1.json"] = (
        b'{"draft_id":"draft-1","updated_at":"2026-08-06T10:00:00+00:00","parts":[]}'
    )
    local = paths.workspace_drafts_dir / "draft-1.json"
    local_payload = (
        b'{"draft_id":"draft-1","updated_at":"2026-08-06T12:00:00+00:00","parts":[{"name":"new"}]}'
    )
    local.write_bytes(local_payload)
    (paths.workspace_dir / ".cloud_state.json").write_text(json.dumps({
        "schema_version": 2,
        "projects": {},
        "drafts": {"draft-1": "old-etag"},
    }))
    set_active_bundle(_make_bundle(storage=remote))

    report = shared_work_service.sync_work_data(paths)

    assert report["drafts_updated"] == 0
    assert report["drafts_uploaded"] == 1
    assert local.read_bytes() == local_payload
    assert remote.files["Drafts/draft-1.json"] == local_payload


def test_sync_preserves_local_draft_while_graph_confirms_a_recent_upload(cloud_on, paths):
    """A stale post-upload read cannot roll back the successfully saved draft."""
    remote = _StaleReadAfterWriteRemote()
    remote.files["Drafts/draft-1.json"] = (
        b'{"draft_id":"draft-1","updated_at":"2026-08-06T10:00:00+00:00","parts":[]}'
    )
    local = paths.workspace_drafts_dir / "draft-1.json"
    local_payload = (
        b'{"draft_id":"draft-1","updated_at":"2026-08-06T12:00:00+00:00","parts":[{"name":"new"}]}'
    )
    local.write_bytes(local_payload)
    (paths.workspace_dir / ".cloud_state.json").write_text(json.dumps({
        "schema_version": 2,
        "projects": {},
        "drafts": {"draft-1": "old-etag"},
    }))
    set_active_bundle(_make_bundle(storage=remote))

    shared_work_service.sync_work_data(paths)
    report = shared_work_service.sync_work_data(paths)

    assert report["drafts_updated"] == 0
    assert report["drafts_uploaded"] == 1
    assert local.read_bytes() == local_payload
    assert remote.files["Drafts/draft-1.json"] == local_payload


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


# ── Reconciliation: deletion propagation + first-launch upload ──────────────


def test_sync_uploads_local_only_files_on_first_run(cloud_on, paths):
    """First-launch case: local has data, cloud is empty, state is empty.
    Reconciliation should push local up so cloud becomes the union."""
    remote = _FakeRemote()
    set_active_bundle(_make_bundle(storage=remote))

    # Seed a local project from before the cloud was wired.
    project_dir = paths.workspace_projects_dir / "legacy-1"
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text('{"legacy": true}', encoding="utf-8")
    # Same for a draft.
    (paths.workspace_drafts_dir / "draft-legacy.json").write_text(
        '{"draft": "legacy"}', encoding="utf-8"
    )

    report = shared_work_service.sync_work_data(paths)
    assert report["projects_uploaded"] == 1
    assert report["drafts_uploaded"] == 1
    assert remote.files["Projects/legacy-1.json"] == b'{"legacy": true}'
    assert remote.files["Drafts/draft-legacy.json"] == b'{"draft": "legacy"}'


def test_sync_propagates_deletion_from_cloud(cloud_on, paths):
    """Teammate deletes a project on their device → mirror removes from cloud.
    Our next sync sees state has X but cloud doesn't → delete locally."""
    remote = _FakeRemote()
    remote.files["Projects/proj-1.json"] = b'{"v": 1}'
    set_active_bundle(_make_bundle(storage=remote))

    # First sync: pulls proj-1, records it in state.
    shared_work_service.sync_work_data(paths)
    assert (paths.workspace_projects_dir / "proj-1" / "project.json").exists()

    # Teammate deletes; cloud copy is gone.
    del remote.files["Projects/proj-1.json"]
    report = shared_work_service.sync_work_data(paths)
    assert report["projects_deleted"] == 1
    assert not (paths.workspace_projects_dir / "proj-1").exists()


def test_sync_does_not_delete_local_only_legacy_data(cloud_on, paths):
    """A local file that was never in cloud + isn't in cloud now should be
    uploaded (first-run case), not silently deleted."""
    remote = _FakeRemote()
    set_active_bundle(_make_bundle(storage=remote))

    # Local has a project; state and cloud are empty.
    project_dir = paths.workspace_projects_dir / "local-only"
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text('{"x": 1}', encoding="utf-8")

    report = shared_work_service.sync_work_data(paths)
    assert report["projects_deleted"] == 0
    assert report["projects_uploaded"] == 1
    # Local copy is untouched.
    assert (project_dir / "project.json").exists()


def test_state_manifest_persists_between_syncs(cloud_on, paths):
    """Without persistence, every sync would treat all cloud files as 'new'
    and skip the deletion-propagation step."""
    remote = _FakeRemote()
    remote.files["Projects/proj-x.json"] = b"{}"
    set_active_bundle(_make_bundle(storage=remote))

    shared_work_service.sync_work_data(paths)
    state_file = paths.workspace_dir / ".cloud_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text("utf-8"))
    assert "proj-x" in state["projects"]


def test_sync_handles_corrupt_state_manifest(cloud_on, paths):
    """A corrupt state file shouldn't crash sync — treat as empty + rebuild."""
    (paths.workspace_dir / ".cloud_state.json").write_text("not json")
    remote = _FakeRemote()
    remote.files["Projects/proj-1.json"] = b"{}"
    set_active_bundle(_make_bundle(storage=remote))
    report = shared_work_service.sync_work_data(paths)
    assert report["projects_updated"] == 1


import json  # noqa: E402 — used in the test above, kept local to avoid changing the module-level imports


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
