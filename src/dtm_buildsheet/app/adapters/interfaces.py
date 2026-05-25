from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class UserIdentity:
    """Identity returned by an IdentityProvider after a successful sign-in.

    `provider` names the concrete adapter so downstream code can branch when it
    truly must (e.g. surfacing "Signed in as Jane (M365)"). `user_id` is the
    adapter's stable identifier — opaque to callers.
    """

    user_id: str
    display_name: str
    email: str
    provider: str
    extra: dict[str, str] = field(default_factory=dict)


ProposalState = Literal["pending", "approved", "rejected", "merged", "unknown"]

# Two-tier review policy introduced in Phase 2-β. The pickup workflow opens a
# PR either way; "general" proposals get auto-merged immediately, "advanced"
# proposals wait for owner review on github.com.
ProposalCategory = Literal["general", "advanced"]


@dataclass(frozen=True)
class ProposalStatus:
    """Status snapshot for a settings change proposal."""

    proposal_id: str
    target_file: str
    summary: str
    submitted_by: str
    submitted_at: str
    state: ProposalState
    review_url: str = ""


class IdentityProvider(ABC):
    """Authenticates the local user and exposes their identity.

    First implementation in Phase 2a is M365IdentityProvider. Future variants
    (customer-facing, external sale) substitute different providers without
    touching service code.
    """

    @abstractmethod
    def signin(self) -> UserIdentity: ...

    @abstractmethod
    def current_user(self) -> UserIdentity | None: ...

    @abstractmethod
    def signout(self) -> None: ...

    @abstractmethod
    def is_signed_in(self) -> bool: ...


class ChangeProposalGateway(ABC):
    """Submits a settings-file change for asynchronous review.

    The Phase 2a SharePoint implementation drops a JSON into /PendingChanges/
    where a GitHub Action picks it up and opens a PR. Other adapters might POST
    to a backend, enqueue locally, or short-circuit straight to a merge.
    """

    @abstractmethod
    def submit_proposal(
        self,
        target_file: str,
        new_content: str,
        summary: str,
        user: UserIdentity,
        *,
        category: ProposalCategory,
    ) -> ProposalStatus: ...

    @abstractmethod
    def list_my_proposals(self, user: UserIdentity) -> list[ProposalStatus]: ...


class NotificationGateway(ABC):
    """Fans out notifications about settings updates and app releases.

    Phase 2a wires this to Power Automate via marker files on SharePoint. A
    NoOp implementation is a perfectly valid choice for variants that don't
    surface notifications.
    """

    @abstractmethod
    def notify_settings_updated(self, filename: str, summary: str) -> None: ...

    @abstractmethod
    def notify_release_published(self, version: str, platform: str) -> None: ...
