from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from ...domain.operations_models import OperationsEvent, VehicleOperations


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
    roles: frozenset[str] = field(default_factory=frozenset)


ProposalState = Literal["pending", "approved", "rejected", "merged", "unknown"]

# Two-tier review policy introduced in Phase 2-β. The pickup workflow opens a
# PR either way; "general" proposals get auto-merged immediately, "advanced"
# proposals wait for owner review on github.com.
ProposalCategory = Literal["general", "advanced"]

# What the pickup workflow should do with the target file. Schema v3 added
# "delete" so deleting an agency / sales-rep / preset propagates through the
# same PR pipeline that creates them. "upsert" is the original behavior:
# write new_content to the target file. Default is "upsert" for backwards
# compatibility — schema v2 payloads have no action field.
ProposalAction = Literal["upsert", "delete"]


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
    def signin(self, *, force_account_picker: bool = False) -> UserIdentity:
        """Run the interactive sign-in flow and return the user's identity.

        ``force_account_picker=True`` is honored by providers that show an
        account chooser (the M365 provider, primarily). Set when the call
        is a user-initiated Switch User so a cached browser session can't
        silently win the OAuth round-trip. Routine first-launch sign-in
        leaves it False.
        """
        ...

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
        action: ProposalAction = "upsert",
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


class OperationsRepositoryError(RuntimeError):
    """Base error for operations persistence adapters."""


class OperationsConflictError(OperationsRepositoryError):
    """The expected operations revision no longer matches storage."""


class OperationsAlreadyExistsError(OperationsRepositoryError):
    """An operations record already exists for the durable vehicle ID."""


class OperationsRepository(ABC):
    """Persistence port for current operations state and immutable events.

    Concrete repositories must commit a current-record mutation and its event
    as one idempotent logical operation. SharePoint may need reconciliation to
    provide that contract because it has no cross-list transaction.
    """

    @abstractmethod
    def get_vehicle(self, vehicle_id: str) -> VehicleOperations | None: ...

    @abstractmethod
    def list_vehicles(self) -> list[VehicleOperations]: ...

    @abstractmethod
    def create_vehicle(
        self,
        record: VehicleOperations,
        event: OperationsEvent,
    ) -> VehicleOperations: ...

    @abstractmethod
    def commit_transition(
        self,
        record: VehicleOperations,
        event: OperationsEvent,
        *,
        expected_revision: int,
    ) -> VehicleOperations: ...

    @abstractmethod
    def find_event_by_request_id(self, request_id: str) -> OperationsEvent | None: ...

    @abstractmethod
    def list_events(self, vehicle_id: str) -> list[OperationsEvent]:
        """Return applied history without repairing or otherwise writing storage."""
        ...

    @abstractmethod
    def delete_project(self, project_id: str) -> tuple[int, int]:
        """Delete current rows and events for one exact Builder project ID."""
        ...
