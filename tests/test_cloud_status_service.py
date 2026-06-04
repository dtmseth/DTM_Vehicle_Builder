"""Tests for cloud_status_service — the header indicator's data source.

The service must NEVER raise from get_status() because it's polled every
60s in the UI and a single bad poll shouldn't crash anything visible. The
no-op paths (cloud disabled, signed out, identity raises) are at least as
important as the happy path.
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
from dtm_buildsheet.app.services import cloud_status_service
from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.storage.local import LocalStorageProvider


# ── Stub identity providers ─────────────────────────────────────────────────


class _StubIdentity:
    def __init__(
        self,
        *,
        signed_in: bool = True,
        user: UserIdentity | None = None,
        photo_bytes: bytes | None = None,
        photo_raises: Exception | None = None,
    ):
        self._signed_in = signed_in
        self._user = user or UserIdentity(
            user_id="u1",
            display_name="Seth Miller",
            email="seth@dtmfleet.com",
            provider="m365",
        )
        self._photo_bytes = photo_bytes
        self._photo_raises = photo_raises
        self.photo_calls = 0

    def signin(self): return self._user
    def current_user(self): return self._user if self._signed_in else None
    def signout(self): self._signed_in = False
    def is_signed_in(self): return self._signed_in

    def fetch_user_photo(self):
        self.photo_calls += 1
        if self._photo_raises:
            raise self._photo_raises
        return self._photo_bytes


def _make_bundle(*, identity=None) -> AdapterBundle:
    return AdapterBundle(
        storage=LocalStorageProvider(),
        identity=identity or _StubIdentity(),
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
    return AppPaths(workspace_dir=tmp_path)


# ── get_status ──────────────────────────────────────────────────────────────


def test_status_reports_local_mode_when_cloud_disabled(cloud_off, paths):
    set_active_bundle(_make_bundle())
    s = cloud_status_service.get_status(paths)
    assert s["cloud_enabled"] is False
    assert s["signed_in"] is False
    assert s["user"] is None
    assert s["has_photo"] is False
    assert s["syncing"] is False
    # data_version is a monotonic counter; just confirm it's an int.
    assert isinstance(s["data_version"], int)


def test_status_includes_syncing_flag_when_sync_in_progress(cloud_off, paths, monkeypatch):
    """The modal needs this flag to drive its spinner UI."""
    from dtm_buildsheet.app.services import cloud_status_service as svc
    monkeypatch.setattr(svc, "_is_sync_in_progress", lambda: True)
    set_active_bundle(_make_bundle())
    s = svc.get_status(paths)
    assert s["syncing"] is True


def test_status_reports_signed_out_when_no_cached_account(cloud_on, paths):
    set_active_bundle(_make_bundle(identity=_StubIdentity(signed_in=False)))
    s = cloud_status_service.get_status(paths)
    assert s["cloud_enabled"] is True
    assert s["signed_in"] is False
    assert s["user"] is None
    assert s["has_photo"] is False


def test_status_reports_connected_when_signed_in(cloud_on, paths):
    identity = _StubIdentity(photo_bytes=b"\xff\xd8\xff\xe0fake-jpeg")
    set_active_bundle(_make_bundle(identity=identity))
    s = cloud_status_service.get_status(paths)
    assert s["cloud_enabled"] is True
    assert s["signed_in"] is True
    assert s["user"]["display_name"] == "Seth Miller"
    assert s["user"]["email"] == "seth@dtmfleet.com"
    assert s["has_photo"] is True
    # Photo got cached to workspace.
    cached = paths.workspace_dir / ".cloud_photo.bin"
    assert cached.read_bytes() == b"\xff\xd8\xff\xe0fake-jpeg"


def test_status_handles_user_with_no_photo(cloud_on, paths):
    """Graph 404 → fetch_user_photo returns None → cache stays a zero-byte
    sentinel so we don't ask again every poll."""
    set_active_bundle(_make_bundle(identity=_StubIdentity(photo_bytes=None)))
    s = cloud_status_service.get_status(paths)
    assert s["has_photo"] is False
    cached = paths.workspace_dir / ".cloud_photo.bin"
    assert cached.exists() and cached.read_bytes() == b""


def test_status_survives_identity_check_failure(cloud_on, paths):
    """is_signed_in raises → reported as signed_out, no crash."""
    class Bad(_StubIdentity):
        def is_signed_in(self): raise RuntimeError("flaky network")
    set_active_bundle(_make_bundle(identity=Bad()))
    s = cloud_status_service.get_status(paths)
    assert s["signed_in"] is False


def test_status_survives_photo_fetch_failure(cloud_on, paths):
    """Graph fetch raises → status still returns; has_photo reflects cache."""
    set_active_bundle(_make_bundle(
        identity=_StubIdentity(photo_raises=RuntimeError("graph down"))
    ))
    s = cloud_status_service.get_status(paths)
    assert s["signed_in"] is True
    assert s["has_photo"] is False  # nothing cached, fetch failed silently


# ── get_cached_photo_bytes ─────────────────────────────────────────────────


def test_cached_photo_returns_bytes_when_file_present(paths):
    (paths.workspace_dir / ".cloud_photo.bin").write_bytes(b"jpeg-data")
    assert cloud_status_service.get_cached_photo_bytes(paths) == b"jpeg-data"


def test_cached_photo_returns_none_for_empty_sentinel(paths):
    """Zero-byte cache means 'we asked Graph, user has no photo'. 404 from UI."""
    (paths.workspace_dir / ".cloud_photo.bin").write_bytes(b"")
    assert cloud_status_service.get_cached_photo_bytes(paths) is None


def test_cached_photo_returns_none_when_missing(paths):
    assert cloud_status_service.get_cached_photo_bytes(paths) is None


# ── Photo cache TTL ──────────────────────────────────────────────────────────


def test_status_uses_cached_photo_within_ttl(cloud_on, paths):
    """A fresh cached photo means no Graph round-trip on subsequent polls."""
    identity = _StubIdentity(photo_bytes=b"first")
    set_active_bundle(_make_bundle(identity=identity))
    cloud_status_service.get_status(paths)
    cloud_status_service.get_status(paths)
    cloud_status_service.get_status(paths)
    # Photo fetched exactly once; subsequent polls used the cache.
    assert identity.photo_calls == 1
