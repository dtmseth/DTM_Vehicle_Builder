"""Tests for sync_shared_settings_at_startup() — the Phase 2e boot hook.

Startup must NEVER fail because of cloud-side problems. These tests cover
all the no-op paths (cloud off, not signed in, identity errors, gateway
raises) plus the happy path where files actually flow into the local cache.
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
from dtm_buildsheet.app.services.shared_settings_service import (
    sync_shared_settings_at_startup,
)
from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.storage.base import StorageProvider
from dtm_buildsheet.storage.local import LocalStorageProvider


# ── Fakes ────────────────────────────────────────────────────────────────────


class _FakeRemote(StorageProvider):
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files: dict[str, bytes] = dict(files or {})

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
        self.files.pop(path, None)

    def list_files(self, directory: str) -> list[str]:
        directory = directory.strip("/")
        prefix = f"{directory}/" if directory else ""
        # Mirror SharePointGraphProvider.list_files: direct children only,
        # no recursion into sub-folders.
        out = []
        for path in self.files:
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix):]
            if "/" in rest:
                continue
            out.append(path)
        return out


class _StubIdentity:
    def __init__(self, *, signed_in: bool, user: UserIdentity | None = None):
        self._signed_in = signed_in
        self._user = user or UserIdentity(
            user_id="u1",
            display_name="Test User",
            email="test@example.invalid",
            provider="stub",
        )

    def signin(self):
        return self._user

    def current_user(self):
        return self._user

    def signout(self):
        self._signed_in = False

    def is_signed_in(self):
        return self._signed_in


class _RaisingIdentity(_StubIdentity):
    def is_signed_in(self):  # type: ignore[override]
        raise RuntimeError("simulated identity check failure")


def _make_bundle(*, identity=None, storage=None) -> AdapterBundle:
    return AdapterBundle(
        storage=storage or LocalStorageProvider(),
        identity=identity or _StubIdentity(signed_in=True),
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
def workspace_paths(tmp_path: Path) -> AppPaths:
    """An AppPaths pinned to a tmp workspace so test runs don't touch real files.

    Overrides every dir the sync touches — including workspace_presets_dir,
    which otherwise defaults to the bundled-presets dir in dev mode and
    would have the sync writing .settings_etags.json into the source tree
    and trying to delete real bundled presets via the deletion-propagation
    step. Hermetic-by-default to keep the production bundled tree pristine.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    paths = AppPaths(
        workspace_dir=tmp_path,
        workspace_config_dir=config_dir,
        workspace_presets_dir=tmp_path / "presets",
    )
    return paths


# ── No-op paths ──────────────────────────────────────────────────────────────


def test_returns_none_when_cloud_disabled(cloud_off, workspace_paths):
    set_active_bundle(_make_bundle())
    assert sync_shared_settings_at_startup(workspace_paths) is None


def test_returns_none_when_not_signed_in(cloud_on, workspace_paths):
    set_active_bundle(_make_bundle(identity=_StubIdentity(signed_in=False)))
    assert sync_shared_settings_at_startup(workspace_paths) is None


def test_returns_none_when_identity_check_raises(cloud_on, workspace_paths):
    """Identity errors must not crash startup."""
    set_active_bundle(_make_bundle(identity=_RaisingIdentity(signed_in=True)))
    assert sync_shared_settings_at_startup(workspace_paths) is None


def test_returns_none_when_bundle_construction_fails(cloud_on, monkeypatch, workspace_paths):
    def boom():
        raise RuntimeError("bundle build failed")

    monkeypatch.setattr(wiring, "get_active_bundle", boom)
    assert sync_shared_settings_at_startup(workspace_paths) is None


# ── Happy path ───────────────────────────────────────────────────────────────


def test_syncs_remote_settings_into_workspace_config_dir(cloud_on, workspace_paths):
    remote = _FakeRemote(
        files={
            "Settings/parts_library.json": b'{"manufacturers": ["SETINA"]}',
            "Settings/build_rules.json": b'{"rules": []}',
            # Sibling subfolder content is ignored by flat list_files — proves
            # we're not accidentally syncing PendingChanges into Settings.
            "PendingChanges/abc.json": b"{}",
        }
    )
    set_active_bundle(_make_bundle(storage=remote))

    report = sync_shared_settings_at_startup(workspace_paths)
    assert report is not None
    assert sorted(report.updated) == ["build_rules.json", "parts_library.json"]
    assert (workspace_paths.workspace_config_dir / "parts_library.json").read_bytes() == (
        b'{"manufacturers": ["SETINA"]}'
    )
    assert (workspace_paths.workspace_config_dir / "build_rules.json").read_bytes() == (
        b'{"rules": []}'
    )


def test_swallows_sync_errors(cloud_on, monkeypatch, workspace_paths):
    """A sync that raises mid-flight must not break startup."""
    class _ExplodingRemote(_FakeRemote):
        def list_files(self, directory: str) -> list[str]:
            raise RuntimeError("simulated network failure")

    set_active_bundle(_make_bundle(storage=_ExplodingRemote()))
    # Must not raise. Returns None because sync didn't complete.
    assert sync_shared_settings_at_startup(workspace_paths) is None


# ── Per-record subdir sync (agencies / sales_reps / presets) ────────────────


def _make_workspace_paths_with_subdirs(tmp_path):
    """Compatibility alias — the main workspace_paths fixture is now hermetic
    for all three subdirs, but the subdir-sync tests still use this helper
    name so existing call sites stay consistent.
    """
    from dtm_buildsheet.paths import AppPaths
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    paths = AppPaths(
        workspace_dir=tmp_path,
        workspace_config_dir=config_dir,
        workspace_presets_dir=tmp_path / "presets",
    )
    return paths


def test_subdir_sync_pulls_agencies(cloud_on, tmp_path):
    paths = _make_workspace_paths_with_subdirs(tmp_path)
    remote = _FakeRemote(files={
        "Settings/agencies/agency-1.json": b'{"name": "Stearns SO"}',
        "Settings/agencies/agency-2.json": b'{"name": "Saint Cloud PD"}',
    })
    set_active_bundle(_make_bundle(storage=remote))

    report = sync_shared_settings_at_startup(paths)
    assert report is not None
    assert (paths.workspace_dir / "agencies" / "agency-1.json").read_bytes() == b'{"name": "Stearns SO"}'
    assert (paths.workspace_dir / "agencies" / "agency-2.json").read_bytes() == b'{"name": "Saint Cloud PD"}'


def test_subdir_sync_pulls_sales_reps_and_presets(cloud_on, tmp_path):
    paths = _make_workspace_paths_with_subdirs(tmp_path)
    remote = _FakeRemote(files={
        "Settings/sales_reps/rep-1.json": b'{"name": "Cody"}',
        "Settings/presets/preset-1.json": b'{"label": "PIU Patrol"}',
    })
    set_active_bundle(_make_bundle(storage=remote))

    sync_shared_settings_at_startup(paths)
    assert (paths.workspace_dir / "sales_reps" / "rep-1.json").read_bytes() == b'{"name": "Cody"}'
    assert (paths.workspace_presets_dir / "preset-1.json").read_bytes() == b'{"label": "PIU Patrol"}'


def test_subdir_sync_propagates_deletions(cloud_on, tmp_path):
    """Per-record subdirs use last-writer-wins: deletions on cloud should
    remove the local copy too."""
    paths = _make_workspace_paths_with_subdirs(tmp_path)
    remote = _FakeRemote(files={
        "Settings/agencies/agency-1.json": b'{"name": "Stearns SO"}',
    })
    set_active_bundle(_make_bundle(storage=remote))

    # First sync: pulls agency-1 into local + records its eTag.
    sync_shared_settings_at_startup(paths)
    local_a1 = paths.workspace_dir / "agencies" / "agency-1.json"
    assert local_a1.exists()

    # Someone deletes agency-1 from cloud; next sync should remove it locally.
    del remote.files["Settings/agencies/agency-1.json"]
    sync_shared_settings_at_startup(paths)
    assert not local_a1.exists()


def test_subdir_sync_does_not_propagate_flat_settings_deletions(cloud_on, tmp_path):
    """The flat /Settings/ files have bundled defaults — never auto-delete."""
    paths = _make_workspace_paths_with_subdirs(tmp_path)
    remote = _FakeRemote(files={
        "Settings/vehicle_layouts.json": b'{"vehicles": {}}',
    })
    set_active_bundle(_make_bundle(storage=remote))

    sync_shared_settings_at_startup(paths)
    local_file = paths.workspace_config_dir / "vehicle_layouts.json"
    assert local_file.exists()

    # Cloud-side delete should NOT remove the local copy.
    del remote.files["Settings/vehicle_layouts.json"]
    sync_shared_settings_at_startup(paths)
    assert local_file.exists(), "flat /Settings/ files must preserve local on cloud-side delete"


def test_subdir_sync_skips_unchanged_via_etag(cloud_on, tmp_path):
    """eTag matching short-circuits content fetches the way the flat sync does."""
    paths = _make_workspace_paths_with_subdirs(tmp_path)
    remote = _FakeRemote(files={
        "Settings/presets/foo.json": b'{"label": "Foo"}',
    })

    # Track read_bytes calls so we can assert the eTag fast path is active.
    read_count = {"n": 0}
    original_read = remote.read_bytes

    def _counting_read(path):
        read_count["n"] += 1
        return original_read(path)
    remote.read_bytes = _counting_read  # type: ignore[method-assign]

    set_active_bundle(_make_bundle(storage=remote))

    sync_shared_settings_at_startup(paths)
    first_count = read_count["n"]
    # Hand-set an eTag on the file so the second sync sees a matching
    # one and skips the fetch. _FakeRemote.list_files_with_metadata returns
    # empty etag by default; for this assertion we override to a stable value.
    from dtm_buildsheet.storage.base import FileMetadata as _FM
    remote.list_files_with_metadata = lambda directory: [  # type: ignore[method-assign]
        _FM(path=p, etag="stable-etag-v1") for p in remote.list_files(directory)
    ]

    # First sync after eTag override: still fetches because state had no eTag.
    sync_shared_settings_at_startup(paths)
    after_first_etagged = read_count["n"]
    # Second sync with same eTag: should NOT fetch — proves the fast path works.
    sync_shared_settings_at_startup(paths)
    after_second_etagged = read_count["n"]
    assert after_second_etagged == after_first_etagged, (
        "matching eTag must short-circuit the content fetch"
    )
