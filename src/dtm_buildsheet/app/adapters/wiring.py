from __future__ import annotations

import logging
import os
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

logger = logging.getLogger(__name__)


CLOUD_ENV_FLAG = "DTM_CLOUD"


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
    work added `build_internal_team_bundle()` alongside this one; the choice
    between them is build-time / env-driven, not runtime user config.
    """
    return AdapterBundle(
        storage=LocalStorageProvider(),
        identity=LocalIdentityProvider(),
        proposals=InMemoryChangeProposalGateway(),
        notifications=NoOpNotificationGateway(),
    )


def build_internal_team_bundle() -> AdapterBundle:
    """Internal-team bundle: SharePoint storage + M365 identity.

    Phase 2a slice — read path only. The proposal and notification gateways
    remain NoOps here; they're wired in once the write path (GitHub Actions
    pickup + Power Automate Flow B) lands.

    Requires DTM_AZURE_TENANT_ID, DTM_AZURE_CLIENT_ID, DTM_SHAREPOINT_SITE_ID,
    DTM_SHAREPOINT_DRIVE_ID. Raises CloudConfigMissing if any is unset.
    """
    # Imports are deferred so the local bundle keeps working without the
    # msal / requests dependencies installed (e.g. in stripped-down builds).
    from .cloud.config import load_cloud_config_from_env
    from .cloud.m365_identity_provider import M365IdentityProvider
    from .cloud.msal_client import MsalClient
    from .cloud.sharepoint_graph_provider import SharePointGraphProvider
    from .cloud.sharepoint_proposals_gateway import SharePointPendingChangesGateway

    config = load_cloud_config_from_env()
    msal_client = MsalClient(config)
    storage = SharePointGraphProvider(
        config,
        token_provider=lambda: msal_client.acquire_token(interactive_ok=False),
    )
    return AdapterBundle(
        storage=storage,
        identity=M365IdentityProvider(msal_client),
        proposals=SharePointPendingChangesGateway(storage),
        notifications=NoOpNotificationGateway(),
    )


def _cloud_flag_enabled() -> bool:
    raw = os.environ.get(CLOUD_ENV_FLAG, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _select_default_bundle() -> AdapterBundle:
    if not _cloud_flag_enabled():
        return build_local_bundle()
    try:
        return build_internal_team_bundle()
    except Exception:  # noqa: BLE001 — config missing / msal not importable / etc.
        logger.exception(
            "%s=1 but cloud bundle failed to initialize; falling back to local",
            CLOUD_ENV_FLAG,
        )
        return build_local_bundle()


_active_bundle: AdapterBundle | None = None


def get_active_bundle() -> AdapterBundle:
    """Return the process-wide adapter bundle, constructing it on first call.

    Default selection is gated by the ``DTM_CLOUD`` env var: unset (or any
    falsy value) keeps the local bundle. Phase 2 cutover is a build-time flip
    of this env var, not a UI toggle.
    """
    global _active_bundle
    if _active_bundle is None:
        _active_bundle = _select_default_bundle()
    return _active_bundle


def set_active_bundle(bundle: AdapterBundle) -> None:
    """Override the active bundle. Intended for tests and the bootstrap path."""
    global _active_bundle
    _active_bundle = bundle
