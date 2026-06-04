"""Tests for app.adapters.wiring.save_via_proposal().

The helper is a no-op outside cloud mode and a thin pass-through to the
active bundle's ChangeProposalGateway inside cloud mode. Tests cover both
paths plus the failure modes the routes rely on (not signed in, gateway
raises) since those decide which toast the UI shows.
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
    save_via_proposal,
    set_active_bundle,
)
from dtm_buildsheet.storage.local import LocalStorageProvider


# ── Fakes ────────────────────────────────────────────────────────────────────


class _RaisingProposals(InMemoryChangeProposalGateway):
    def submit_proposal(self, *args, **kwargs):
        raise RuntimeError("simulated gateway failure")


class _StubIdentity:
    def __init__(self, *, signed_in: bool = True, user: UserIdentity | None = None):
        self._signed_in = signed_in
        self._user = user

    def signin(self):
        return self._user

    def current_user(self):
        return self._user

    def signout(self):
        self._signed_in = False

    def is_signed_in(self):
        return self._signed_in


def _make_bundle(*, identity=None, proposals=None) -> AdapterBundle:
    return AdapterBundle(
        storage=LocalStorageProvider(),
        identity=identity or _StubIdentity(
            user=UserIdentity(
                user_id="u1",
                display_name="Test User",
                email="test@example.invalid",
                provider="stub",
            ),
        ),
        proposals=proposals or InMemoryChangeProposalGateway(),
        notifications=NoOpNotificationGateway(),
    )


@pytest.fixture(autouse=True)
def reset_bundle():
    yield
    # Force the next test to re-construct from env defaults.
    wiring._active_bundle = None  # noqa: SLF001


@pytest.fixture
def cloud_off(monkeypatch):
    """Force the cloud-flag check off regardless of env or cloud_config.json."""
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: False)
    # Bypass the autouse test-env guard so the cloud-disabled code path
    # actually gets exercised. Safe because the flag itself is off — no
    # real I/O can happen even if the guard is bypassed.
    monkeypatch.setenv("DTM_ALLOW_CLOUD_IN_TESTS", "1")


@pytest.fixture
def cloud_on(monkeypatch):
    """Force the cloud-flag check on regardless of env or cloud_config.json."""
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    # Opt back into cloud paths against fake remotes — the
    # autouse PYTEST_CURRENT_TEST guard in shared_work_service /
    # wiring otherwise blocks every test from reaching cloud code.
    monkeypatch.setenv("DTM_ALLOW_CLOUD_IN_TESTS", "1")


# ── No-op when cloud disabled ────────────────────────────────────────────────


def test_returns_noop_when_cloud_disabled(cloud_off):
    set_active_bundle(_make_bundle())

    result = save_via_proposal(
        target_file="agencies/abc.json",
        serialized_content="{}",
        summary="test",
        category="general",
    )
    assert result == {"proposed": False, "reason": "cloud disabled"}


# ── Cloud-enabled paths ──────────────────────────────────────────────────────


def test_submits_when_cloud_enabled_and_signed_in(cloud_on):
    proposals = InMemoryChangeProposalGateway()
    bundle = _make_bundle(proposals=proposals)
    set_active_bundle(bundle)

    result = save_via_proposal(
        target_file="presets/foo.json",
        serialized_content='{"a": 1}',
        summary="Add preset foo",
        category="general",
    )
    assert result["proposed"] is True
    assert result["category"] == "general"
    assert result["proposal_id"]
    # The in-memory gateway recorded it under the test user.
    listed = proposals.list_my_proposals(bundle.identity.current_user())
    assert len(listed) == 1
    assert listed[0].target_file == "presets/foo.json"


def test_skips_when_not_signed_in(cloud_on):
    bundle = _make_bundle(identity=_StubIdentity(signed_in=False, user=None))
    set_active_bundle(bundle)

    result = save_via_proposal(
        target_file="agencies/abc.json",
        serialized_content="{}",
        summary="test",
        category="general",
    )
    assert result == {"proposed": False, "reason": "not signed in"}


def test_skips_when_current_user_returns_none(cloud_on):
    bundle = _make_bundle(identity=_StubIdentity(signed_in=True, user=None))
    set_active_bundle(bundle)

    result = save_via_proposal(
        target_file="agencies/abc.json",
        serialized_content="{}",
        summary="test",
        category="general",
    )
    assert result == {"proposed": False, "reason": "not signed in"}


def test_handles_gateway_failure(cloud_on):
    """Helper must never raise — routes rely on the dict response shape."""
    bundle = _make_bundle(proposals=_RaisingProposals())
    set_active_bundle(bundle)

    result = save_via_proposal(
        target_file="agencies/abc.json",
        serialized_content="{}",
        summary="test",
        category="advanced",
    )
    assert result == {"proposed": False, "reason": "submit failed"}
