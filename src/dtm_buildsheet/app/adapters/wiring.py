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
    ProposalCategory,
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
    # Delegate to the cloud config module so env-var AND on-disk
    # cloud_config.json are both honored. Kept as a thin wrapper so any code
    # importing this name keeps working.
    from .cloud.config import cloud_enabled

    return cloud_enabled()


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


def save_via_proposal(
    target_file: str,
    serialized_content: str,
    summary: str,
    *,
    category: ProposalCategory,
) -> dict:
    """Submit a settings change as a proposal. No-op outside cloud mode.

    Callers must have already written the local copy. The proposal is an
    additional step that ships the change to the team via the settings repo;
    it does not replace the local write. Local stays canonical until the
    next ``SharedSettingsService.sync_all()`` overwrites it with the merged
    version on app startup.

    Returns a dict with `proposed`: True when a proposal was actually
    submitted, False otherwise (cloud disabled, not signed in, or the gateway
    raised). The return value is intended to be merged into the route's JSON
    response so the UI can decide which toast to show.
    """
    if not _cloud_flag_enabled():
        return {"proposed": False, "reason": "cloud disabled"}

    bundle = get_active_bundle()
    try:
        if not bundle.identity.is_signed_in():
            return {"proposed": False, "reason": "not signed in"}
        user = bundle.identity.current_user()
    except Exception:
        logger.exception("Identity check failed while submitting proposal")
        return {"proposed": False, "reason": "identity error"}
    if user is None:
        return {"proposed": False, "reason": "not signed in"}

    try:
        status = bundle.proposals.submit_proposal(
            target_file=target_file,
            new_content=serialized_content,
            summary=summary,
            user=user,
            category=category,
        )
    except Exception:
        logger.exception("Failed to submit proposal for %s", target_file)
        return {"proposed": False, "reason": "submit failed"}

    return {
        "proposed": True,
        "proposal_id": status.proposal_id,
        "category": category,
    }
