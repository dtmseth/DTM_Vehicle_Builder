"""Tests for ensure_signed_in_for_cloud() — the boot-time sign-in hook.

This is what makes fresh cloud-mode installs actually engage cloud mode
on the first launch (otherwise the storage adapter's interactive_ok=False
silently swallows the missing-token case and the user lands in local mode).
"""

from __future__ import annotations

import pytest

from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.adapters.interfaces import UserIdentity
from dtm_buildsheet.app.adapters.noop import (
    InMemoryChangeProposalGateway,
    NoOpNotificationGateway,
)
from dtm_buildsheet.app.adapters.wiring import (
    AdapterBundle,
    ensure_signed_in_for_cloud,
    set_active_bundle,
)
from dtm_buildsheet.storage.local import LocalStorageProvider


class _StubIdentity:
    def __init__(
        self,
        *,
        signed_in: bool = False,
        signin_raises: Exception | None = None,
        user: UserIdentity | None = None,
    ):
        self._signed_in = signed_in
        self._signin_raises = signin_raises
        self.signin_calls = 0
        self._user = user or UserIdentity(
            user_id="u1",
            display_name="Test User",
            email="test@example.invalid",
            provider="stub",
        )

    def signin(self) -> UserIdentity:
        self.signin_calls += 1
        if self._signin_raises:
            raise self._signin_raises
        self._signed_in = True
        return self._user

    def current_user(self):
        return self._user if self._signed_in else None

    def signout(self):
        self._signed_in = False

    def is_signed_in(self):
        return self._signed_in


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


# ── No-op when cloud disabled ────────────────────────────────────────────────


def test_returns_false_when_cloud_disabled(cloud_off):
    identity = _StubIdentity(signed_in=False)
    set_active_bundle(_make_bundle(identity=identity))
    assert ensure_signed_in_for_cloud() is False
    assert identity.signin_calls == 0  # critical: no surprise OAuth in local mode


# ── No-op when already signed in ─────────────────────────────────────────────


def test_returns_true_when_already_signed_in(cloud_on):
    identity = _StubIdentity(signed_in=True)
    set_active_bundle(_make_bundle(identity=identity))
    assert ensure_signed_in_for_cloud() is True
    assert identity.signin_calls == 0  # silent SSO worked, no interactive needed


# ── Interactive sign-in path ─────────────────────────────────────────────────


def test_triggers_interactive_signin_when_no_cached_account(cloud_on):
    """The whole point of this helper: fresh-install Windows path."""
    identity = _StubIdentity(signed_in=False)
    set_active_bundle(_make_bundle(identity=identity))
    assert ensure_signed_in_for_cloud() is True
    assert identity.signin_calls == 1
    assert identity.is_signed_in()


def test_background_check_never_triggers_interactive_signin(cloud_on):
    identity = _StubIdentity(signed_in=False)
    set_active_bundle(_make_bundle(identity=identity))
    assert ensure_signed_in_for_cloud(interactive=False) is False
    assert identity.signin_calls == 0


def test_swallows_signin_failure(cloud_on):
    """User cancels OAuth, network is down, etc. — startup must not crash."""
    identity = _StubIdentity(
        signed_in=False,
        signin_raises=RuntimeError("user cancelled OAuth"),
    )
    set_active_bundle(_make_bundle(identity=identity))
    assert ensure_signed_in_for_cloud() is False
    assert identity.signin_calls == 1  # tried once, failed, gave up


def test_swallows_bundle_construction_failure(cloud_on, monkeypatch):
    """A broken cloud bundle should not crash startup."""
    def boom():
        raise RuntimeError("bundle construction blew up")
    monkeypatch.setattr(wiring, "get_active_bundle", boom)
    assert ensure_signed_in_for_cloud() is False


def test_treats_is_signed_in_error_as_unsigned(cloud_on):
    """A flaky identity provider must trigger interactive — not silently skip."""
    class _RaisesOnCheck(_StubIdentity):
        def is_signed_in(self):
            raise RuntimeError("flaky network during signed-in check")

    identity = _RaisesOnCheck(signed_in=False)
    set_active_bundle(_make_bundle(identity=identity))
    assert ensure_signed_in_for_cloud() is True
    assert identity.signin_calls == 1
