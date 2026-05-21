from __future__ import annotations

from dataclasses import dataclass

from ...storage.base import StorageProvider
from ...storage.local import LocalStorageProvider
from .interfaces import (
    ChangeProposalGateway,
    IdentityProvider,
    NotificationGateway,
)
from .noop import (
    InMemoryChangeProposalGateway,
    LocalIdentityProvider,
    NoOpNotificationGateway,
)


@dataclass(frozen=True)
class AdapterBundle:
    """The concrete set of adapters chosen for this build.

    Services that need adapters take an `AdapterBundle` (or individual fields)
    via constructor injection. They never import a concrete adapter class.
    """

    storage: StorageProvider
    identity: IdentityProvider
    proposals: ChangeProposalGateway
    notifications: NotificationGateway


def build_local_bundle() -> AdapterBundle:
    """Local-only bundle: filesystem storage, synthetic identity, in-memory proposals.

    Used by tests and by builds that don't talk to the cloud yet. The Phase 2a
    work will add `build_internal_team_bundle()` alongside this one, wiring up
    SharePoint + M365 + the GitHub-Actions-backed proposal gateway + Power
    Automate. The choice is made at build/package time, not runtime.
    """
    return AdapterBundle(
        storage=LocalStorageProvider(),
        identity=LocalIdentityProvider(),
        proposals=InMemoryChangeProposalGateway(),
        notifications=NoOpNotificationGateway(),
    )


_active_bundle: AdapterBundle | None = None


def get_active_bundle() -> AdapterBundle:
    """Return the process-wide adapter bundle, constructing it on first call.

    Defaults to the local bundle. Phase 2a will replace this with a build-time
    selection (env var or packaging flag) once the SharePoint adapters land.
    """
    global _active_bundle
    if _active_bundle is None:
        _active_bundle = build_local_bundle()
    return _active_bundle


def set_active_bundle(bundle: AdapterBundle) -> None:
    """Override the active bundle. Intended for tests and the bootstrap path."""
    global _active_bundle
    _active_bundle = bundle
