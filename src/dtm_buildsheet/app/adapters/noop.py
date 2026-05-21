from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .interfaces import (
    ChangeProposalGateway,
    IdentityProvider,
    NotificationGateway,
    ProposalStatus,
    UserIdentity,
)

_LOCAL_USER = UserIdentity(
    user_id="local",
    display_name="Local User",
    email="local@example.invalid",
    provider="local",
)


class LocalIdentityProvider(IdentityProvider):
    """IdentityProvider for builds with no cloud auth (dev, tests, bundled-local mode).

    Sign-in is a no-op that returns a stable synthetic identity. Useful before
    the M365 adapter lands and as the default in tests.
    """

    def signin(self) -> UserIdentity:
        return _LOCAL_USER

    def current_user(self) -> UserIdentity | None:
        return _LOCAL_USER

    def signout(self) -> None:
        return None

    def is_signed_in(self) -> bool:
        return True


class InMemoryChangeProposalGateway(ChangeProposalGateway):
    """Holds proposals in process memory. For tests and local-only builds.

    Real review workflow comes from SharePointPendingChangesGateway in 2a.
    """

    def __init__(self) -> None:
        self._proposals: list[ProposalStatus] = []

    def submit_proposal(
        self,
        target_file: str,
        new_content: str,
        summary: str,
        user: UserIdentity,
    ) -> ProposalStatus:
        status = ProposalStatus(
            proposal_id=str(uuid.uuid4()),
            target_file=target_file,
            summary=summary,
            submitted_by=user.display_name or user.user_id,
            submitted_at=datetime.now(timezone.utc).isoformat(),
            state="pending",
        )
        self._proposals.append(status)
        return status

    def list_my_proposals(self, user: UserIdentity) -> list[ProposalStatus]:
        marker = user.display_name or user.user_id
        return [p for p in self._proposals if p.submitted_by == marker]


class NoOpNotificationGateway(NotificationGateway):
    """Drops every notification on the floor. Default for non-team variants."""

    def notify_settings_updated(self, filename: str, summary: str) -> None:
        return None

    def notify_release_published(self, version: str, platform: str) -> None:
        return None
