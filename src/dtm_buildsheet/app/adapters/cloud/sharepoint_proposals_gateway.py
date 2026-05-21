from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from ....storage.base import StorageProvider
from ..interfaces import ChangeProposalGateway, ProposalStatus, UserIdentity

logger = logging.getLogger(__name__)


# Folder on the SharePoint drive that holds pending proposals. The pickup
# GitHub Action lists this folder every five minutes.
PENDING_REMOTE_FOLDER = "PendingChanges"

# Schema version for the proposal JSON payload. Bump when the on-wire shape
# changes; the pickup workflow checks this and refuses unknown versions.
PROPOSAL_SCHEMA_VERSION = 1


def _slugify(value: str) -> str:
    """Produce a filename-safe slug for the submitter portion of proposal IDs."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "user"


class SharePointPendingChangesGateway(ChangeProposalGateway):
    """`ChangeProposalGateway` that drops proposals onto SharePoint /PendingChanges/.

    Each proposal is a single JSON file at ``/PendingChanges/{proposal_id}.json``.
    A GitHub Actions cron in ``dtm-shared-settings`` lists the folder every
    five minutes, opens a PR with the proposed content, and deletes the source
    file once the PR is up. ``list_my_proposals`` therefore only shows
    proposals that haven't been picked up yet — once they become a PR, status
    lives on github.com.
    """

    def __init__(
        self,
        storage: StorageProvider,
        *,
        remote_folder: str = PENDING_REMOTE_FOLDER,
    ) -> None:
        self._storage = storage
        self._remote_folder = remote_folder.strip("/")

    def submit_proposal(
        self,
        target_file: str,
        new_content: str,
        summary: str,
        user: UserIdentity,
    ) -> ProposalStatus:
        proposal_id = str(uuid.uuid4())
        submitted_at = datetime.now(timezone.utc).isoformat()
        slug = _slugify(user.display_name or user.user_id)

        payload = {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "proposal_id": proposal_id,
            "target_file": target_file,
            "summary": summary,
            "submitted_by": user.display_name or user.user_id,
            "submitted_by_email": user.email,
            "submitted_by_user_id": user.user_id,
            "submitted_by_slug": slug,
            "submitted_at": submitted_at,
            "new_content": new_content,
        }

        remote_path = f"{self._remote_folder}/{proposal_id}.json"
        self._storage.write_text(remote_path, json.dumps(payload, indent=2))

        return ProposalStatus(
            proposal_id=proposal_id,
            target_file=target_file,
            summary=summary,
            submitted_by=user.display_name or user.user_id,
            submitted_at=submitted_at,
            state="pending",
        )

    def list_my_proposals(self, user: UserIdentity) -> list[ProposalStatus]:
        try:
            remote_files = self._storage.list_files(self._remote_folder)
        except FileNotFoundError:
            return []

        out: list[ProposalStatus] = []
        for remote_path in remote_files:
            if not remote_path.endswith(".json"):
                continue
            try:
                raw = self._storage.read_text(remote_path)
                payload = json.loads(raw)
            except FileNotFoundError:
                # Picked up and deleted by the workflow between list and read.
                continue
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning("Skipping malformed proposal file: %s", remote_path)
                continue

            if not _belongs_to_user(payload, user):
                continue

            out.append(
                ProposalStatus(
                    proposal_id=str(payload.get("proposal_id", "")),
                    target_file=str(payload.get("target_file", "")),
                    summary=str(payload.get("summary", "")),
                    submitted_by=str(payload.get("submitted_by", "")),
                    submitted_at=str(payload.get("submitted_at", "")),
                    state="pending",
                )
            )
        return out


def _belongs_to_user(payload: dict, user: UserIdentity) -> bool:
    """Match a proposal payload against a user identity.

    Prefer the immutable Azure user_id; fall back to email and display name
    for proposals written before user_id became part of the payload.
    """
    user_id = str(payload.get("submitted_by_user_id", "")).strip()
    if user_id:
        return user_id == user.user_id
    email = str(payload.get("submitted_by_email", "")).strip().lower()
    if email:
        return email == (user.email or "").lower()
    return str(payload.get("submitted_by", "")) == (user.display_name or user.user_id)
