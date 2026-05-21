"""Adapter boundary for cloud / identity / proposal / notification integrations.

Phase 2 (per docs/ROADMAP.md §6) introduces four ports-and-adapters interfaces.
The storage interface lives in `dtm_buildsheet.storage.base`; the other three
are defined in this package alongside the wiring that assembles a concrete
adapter bundle at build time.

Services depend on these interfaces, never on a specific cloud SDK.
"""

from .interfaces import (
    ChangeProposalGateway,
    IdentityProvider,
    NotificationGateway,
    ProposalStatus,
    UserIdentity,
)

__all__ = [
    "ChangeProposalGateway",
    "IdentityProvider",
    "NotificationGateway",
    "ProposalStatus",
    "UserIdentity",
]
