from __future__ import annotations

import json

import pytest

from dtm_buildsheet.app.adapters.cloud.sharepoint_proposals_gateway import (
    PENDING_REMOTE_FOLDER,
    PROPOSAL_SCHEMA_VERSION,
    SharePointPendingChangesGateway,
    _slugify,
)
from dtm_buildsheet.app.adapters.interfaces import UserIdentity
from dtm_buildsheet.storage.base import StorageProvider


# ── Fixtures ─────────────────────────────────────────────────────────────────


class _FakeRemote(StorageProvider):
    """In-memory StorageProvider for gateway-level tests."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: str, data: str) -> None:
        self.files[path] = data.encode("utf-8")

    def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_bytes(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def delete(self, path: str) -> None:
        self.files.pop(path, None)

    def list_files(self, directory: str) -> list[str]:
        directory = directory.strip("/")
        prefix = f"{directory}/" if directory else ""
        return [p for p in self.files if p.startswith(prefix)]


@pytest.fixture
def remote() -> _FakeRemote:
    return _FakeRemote()


@pytest.fixture
def gateway(remote: _FakeRemote) -> SharePointPendingChangesGateway:
    return SharePointPendingChangesGateway(remote)


@pytest.fixture
def seth() -> UserIdentity:
    return UserIdentity(
        user_id="azure-guid-seth",
        display_name="Seth Miller",
        email="seth@dtmfleet.com",
        provider="m365",
    )


@pytest.fixture
def chris() -> UserIdentity:
    return UserIdentity(
        user_id="azure-guid-chris",
        display_name="Chris Example",
        email="chris@dtmfleet.com",
        provider="m365",
    )


# ── submit_proposal ──────────────────────────────────────────────────────────


def test_submit_proposal_writes_uuid_json_file(gateway, remote, seth):
    status = gateway.submit_proposal(
        target_file="parts_library.json",
        new_content='{"manufacturers": ["SETINA"]}',
        summary="Add SETINA to manufacturers",
        user=seth,
        category="advanced",
    )

    assert status.state == "pending"
    assert status.target_file == "parts_library.json"
    assert status.summary == "Add SETINA to manufacturers"
    assert status.submitted_by == "Seth Miller"

    expected_path = f"{PENDING_REMOTE_FOLDER}/{status.proposal_id}.json"
    assert expected_path in remote.files
    payload = json.loads(remote.files[expected_path])

    assert payload["schema_version"] == PROPOSAL_SCHEMA_VERSION
    assert payload["schema_version"] == 3  # Phase 2 close: action field added
    assert payload["proposal_id"] == status.proposal_id
    assert payload["target_file"] == "parts_library.json"
    assert payload["category"] == "advanced"
    assert payload["action"] == "upsert"  # default when not specified
    assert payload["summary"] == "Add SETINA to manufacturers"
    assert payload["submitted_by"] == "Seth Miller"
    assert payload["submitted_by_email"] == "seth@dtmfleet.com"
    assert payload["submitted_by_user_id"] == "azure-guid-seth"
    assert payload["submitted_by_slug"] == "seth-miller"
    assert payload["new_content"] == '{"manufacturers": ["SETINA"]}'
    assert payload["submitted_at"]  # nonempty ISO timestamp


def test_submit_proposal_records_general_category(gateway, remote, seth):
    status = gateway.submit_proposal(
        target_file="agencies/agency-123.json",
        new_content="{}",
        summary="Add Hennepin County PD",
        user=seth,
        category="general",
    )
    payload = json.loads(remote.files[f"{PENDING_REMOTE_FOLDER}/{status.proposal_id}.json"])
    assert payload["category"] == "general"
    assert payload["target_file"] == "agencies/agency-123.json"


def test_submit_proposal_records_delete_action(gateway, remote, seth):
    """Delete proposals carry action='delete' so the pickup workflow knows
    to git-rm the target instead of writing new_content."""
    status = gateway.submit_proposal(
        target_file="agencies/agency-123.json",
        new_content="",  # ignored when action=delete
        summary="Delete agency: Hennepin County PD",
        user=seth,
        category="general",
        action="delete",
    )
    payload = json.loads(remote.files[f"{PENDING_REMOTE_FOLDER}/{status.proposal_id}.json"])
    assert payload["category"] == "general"
    assert payload["action"] == "delete"
    assert payload["target_file"] == "agencies/agency-123.json"


def test_submit_proposal_ids_are_unique(gateway, seth):
    a = gateway.submit_proposal("foo.json", "{}", "first", seth, category="advanced")
    b = gateway.submit_proposal("foo.json", "{}", "second", seth, category="advanced")
    assert a.proposal_id != b.proposal_id


def test_submit_proposal_preserves_content_verbatim(gateway, remote, seth):
    new_content = json.dumps({"weird": "café 🚓", "nested": {"a": [1, 2, 3]}}, indent=2)
    status = gateway.submit_proposal(
        "vehicle_layouts.json", new_content, "test", seth, category="advanced"
    )
    payload = json.loads(remote.files[f"{PENDING_REMOTE_FOLDER}/{status.proposal_id}.json"])
    assert payload["new_content"] == new_content


# ── list_my_proposals ────────────────────────────────────────────────────────


def test_list_my_proposals_filters_to_current_user(gateway, seth, chris):
    a = gateway.submit_proposal("parts_library.json", "{}", "seth one", seth, category="advanced")
    b = gateway.submit_proposal("build_rules.json", "{}", "seth two", seth, category="advanced")
    gateway.submit_proposal("parts_library.json", "{}", "chris one", chris, category="advanced")

    seth_list = gateway.list_my_proposals(seth)
    assert sorted(p.proposal_id for p in seth_list) == sorted([a.proposal_id, b.proposal_id])

    chris_list = gateway.list_my_proposals(chris)
    assert len(chris_list) == 1
    assert chris_list[0].submitted_by == "Chris Example"


def test_list_my_proposals_returns_empty_when_folder_missing(gateway, seth):
    # No files written yet — remote.list_files returns []; not an error.
    assert gateway.list_my_proposals(seth) == []


def test_list_my_proposals_skips_malformed_files(gateway, remote, seth, caplog):
    # Drop a malformed file alongside a good one.
    remote.write_text(f"{PENDING_REMOTE_FOLDER}/garbage.json", "not json")
    good = gateway.submit_proposal("foo.json", "{}", "good one", seth, category="advanced")

    out = gateway.list_my_proposals(seth)
    assert [p.proposal_id for p in out] == [good.proposal_id]


def test_list_my_proposals_skips_non_json_entries(gateway, remote, seth):
    # SharePoint might surface a stray README.txt; we ignore it.
    remote.write_text(f"{PENDING_REMOTE_FOLDER}/README.txt", "ignore me")
    submitted = gateway.submit_proposal("foo.json", "{}", "real", seth, category="advanced")
    out = gateway.list_my_proposals(seth)
    assert [p.proposal_id for p in out] == [submitted.proposal_id]


def test_list_my_proposals_handles_pickup_race(gateway, remote, seth):
    """File listed but deleted before read — must not raise."""
    submitted = gateway.submit_proposal("foo.json", "{}", "race", seth, category="advanced")
    remote_path = f"{PENDING_REMOTE_FOLDER}/{submitted.proposal_id}.json"

    original_read = remote.read_text

    def racing_read(path: str) -> str:
        if path == remote_path:
            raise FileNotFoundError(path)
        return original_read(path)

    remote.read_text = racing_read  # type: ignore[method-assign]
    assert gateway.list_my_proposals(seth) == []


def test_list_my_proposals_matches_legacy_proposals_by_email(gateway, remote, seth):
    """Proposals written before user_id existed should still match on email."""
    legacy_path = f"{PENDING_REMOTE_FOLDER}/legacy.json"
    remote.write_text(
        legacy_path,
        json.dumps(
            {
                "schema_version": PROPOSAL_SCHEMA_VERSION,
                "proposal_id": "legacy",
                "target_file": "foo.json",
                "summary": "legacy proposal",
                "submitted_by": "Seth Miller",
                "submitted_by_email": "seth@dtmfleet.com",
                "submitted_at": "2026-05-21T00:00:00+00:00",
                "new_content": "{}",
            }
        ),
    )
    out = gateway.list_my_proposals(seth)
    assert [p.proposal_id for p in out] == ["legacy"]


# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Seth Miller", "seth-miller"),
        ("Chris O'Brien", "chris-o-brien"),
        ("seth@dtmfleet.com", "seth-dtmfleet-com"),
        ("   ", "user"),
        ("", "user"),
        ("ALLCAPS", "allcaps"),
    ],
)
def test_slugify(raw, expected):
    assert _slugify(raw) == expected
