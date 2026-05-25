from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from dtm_buildsheet.app.adapters import (
    ChangeProposalGateway,
    IdentityProvider,
    NotificationGateway,
    ProposalStatus,
    UserIdentity,
)
from dtm_buildsheet.app.adapters.noop import (
    InMemoryChangeProposalGateway,
    LocalIdentityProvider,
    NoOpNotificationGateway,
)
from dtm_buildsheet.app.adapters.wiring import (
    AdapterBundle,
    build_local_bundle,
    get_active_bundle,
    set_active_bundle,
)
from dtm_buildsheet.storage.base import StorageProvider
from dtm_buildsheet.storage.local import LocalStorageProvider


# ── StorageProvider interface ─────────────────────────────────────────────────


def test_storage_interface_declares_bytes_methods():
    abstract = StorageProvider.__abstractmethods__
    assert "read_text" in abstract
    assert "write_text" in abstract
    assert "read_bytes" in abstract
    assert "write_bytes" in abstract
    assert "delete" in abstract
    assert "list_files" in abstract


def test_local_storage_round_trips_bytes(tmp_path: Path):
    storage = LocalStorageProvider()
    target = tmp_path / "blob.bin"
    payload = b"\x00\x01\x02hello\xff"
    storage.write_bytes(str(target), payload)
    assert storage.read_bytes(str(target)) == payload


def test_local_storage_satisfies_extended_interface():
    # LocalStorageProvider must remain instantiable now that the abstract base
    # demands read_bytes + write_bytes.
    LocalStorageProvider()  # no TypeError


# ── IdentityProvider ──────────────────────────────────────────────────────────


def test_identity_provider_interface_shape():
    abstract = IdentityProvider.__abstractmethods__
    assert abstract == {"signin", "current_user", "signout", "is_signed_in"}


def test_local_identity_provider_returns_stable_user():
    provider = LocalIdentityProvider()
    assert provider.is_signed_in() is True
    user = provider.signin()
    assert isinstance(user, UserIdentity)
    assert user.provider == "local"
    assert provider.current_user() == user
    provider.signout()  # tolerated, but identity remains for this adapter
    assert provider.is_signed_in() is True


# ── ChangeProposalGateway ─────────────────────────────────────────────────────


def test_proposal_gateway_interface_shape():
    abstract = ChangeProposalGateway.__abstractmethods__
    assert abstract == {"submit_proposal", "list_my_proposals"}


def test_in_memory_proposal_gateway_records_and_lists():
    gateway = InMemoryChangeProposalGateway()
    user = LocalIdentityProvider().signin()

    other = UserIdentity(
        user_id="other",
        display_name="Other Person",
        email="other@example.invalid",
        provider="local",
    )

    first = gateway.submit_proposal(
        target_file="config/parts_library.json",
        new_content="{}",
        summary="tweak library",
        user=user,
        category="advanced",
    )
    second = gateway.submit_proposal(
        target_file="config/build_rules.json",
        new_content="{}",
        summary="adjust rule",
        user=user,
        category="advanced",
    )
    gateway.submit_proposal(
        target_file="config/build_rules.json",
        new_content="{}",
        summary="someone else's change",
        user=other,
        category="advanced",
    )

    assert isinstance(first, ProposalStatus)
    assert first.state == "pending"
    assert first.proposal_id != second.proposal_id

    mine = gateway.list_my_proposals(user)
    assert {p.proposal_id for p in mine} == {first.proposal_id, second.proposal_id}
    assert gateway.list_my_proposals(other)[0].submitted_by == "Other Person"


# ── NotificationGateway ───────────────────────────────────────────────────────


def test_notification_gateway_interface_shape():
    abstract = NotificationGateway.__abstractmethods__
    assert abstract == {"notify_settings_updated", "notify_release_published"}


def test_noop_notification_gateway_is_silent():
    gateway = NoOpNotificationGateway()
    # Returns None and never raises.
    assert gateway.notify_settings_updated("parts_library.json", "edit") is None
    assert gateway.notify_release_published("1.3.0", "mac") is None


# ── Wiring ───────────────────────────────────────────────────────────────────


def test_build_local_bundle_returns_concrete_adapters():
    bundle = build_local_bundle()
    assert isinstance(bundle, AdapterBundle)
    assert isinstance(bundle.storage, StorageProvider)
    assert isinstance(bundle.identity, IdentityProvider)
    assert isinstance(bundle.proposals, ChangeProposalGateway)
    assert isinstance(bundle.notifications, NotificationGateway)


def test_get_active_bundle_is_overridable():
    original = get_active_bundle()
    try:
        replacement = build_local_bundle()
        set_active_bundle(replacement)
        assert get_active_bundle() is replacement
    finally:
        set_active_bundle(original)


# ── Guardrails for future adapter authors ────────────────────────────────────


@pytest.mark.parametrize(
    "interface",
    [IdentityProvider, ChangeProposalGateway, NotificationGateway],
)
def test_interfaces_are_pure_abstract_bases(interface):
    # Each interface ABC should be instantiation-blocked until subclassed.
    with pytest.raises(TypeError):
        interface()  # type: ignore[abstract]
    # And every declared method should be marked abstract — no concrete logic
    # hidden in the base.
    for name in interface.__abstractmethods__:
        method = inspect.getattr_static(interface, name)
        assert getattr(method, "__isabstractmethod__", False) is True
