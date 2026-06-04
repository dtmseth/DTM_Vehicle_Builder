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
    """An AppPaths pinned to a tmp workspace so test runs don't touch real files."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    paths = AppPaths(
        workspace_dir=tmp_path,
        workspace_config_dir=config_dir,
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
