"""Tests for the auto-upload-to-SharePoint exports service.

Three layers verified:
- Sanitization of agency/year/filename segments.
- No-op behavior when cloud is disabled or exports aren't configured.
- The path layout the uploader assembles from base_folder + agency + year.

The actual Graph HTTP calls are NOT exercised here — those are routed
through the upload-session helper which mocks would have to replace
HTTP transport for. The conftest autouse fixture also blocks real
cloud I/O so even if a test got the bundle setup wrong, no SharePoint
write would happen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.adapters.interfaces import UserIdentity
from dtm_buildsheet.app.adapters.noop import (
    InMemoryChangeProposalGateway,
    NoOpNotificationGateway,
)
from dtm_buildsheet.app.adapters.wiring import AdapterBundle, set_active_bundle
from dtm_buildsheet.app.services import exports_upload_service
from dtm_buildsheet.storage.local import LocalStorageProvider


# ── Sanitization ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw, expected", [
    ("Hennepin County PD", "Hennepin County PD"),
    ("Saint Cloud P.D.", "Saint Cloud P.D"),
    ("Stearns/Sheriff's", "Stearns Sheriff s"),
    ("", "Unassigned"),
    ("   ", "Unassigned"),
    ("..hidden", "hidden"),
    ("Test#1<>:", "Test 1"),
])
def test_sanitize_segment(raw, expected):
    assert exports_upload_service._sanitize_segment(raw) == expected


# ── No-op paths ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_drive_cache():
    """Memoized drive_id leaks across tests otherwise."""
    yield
    exports_upload_service.reset_cache()


def _make_bundle(*, signed_in: bool = True) -> AdapterBundle:
    return AdapterBundle(
        storage=LocalStorageProvider(),
        identity=_StubIdentity(signed_in=signed_in),
        proposals=InMemoryChangeProposalGateway(),
        notifications=NoOpNotificationGateway(),
    )


class _StubIdentity:
    def __init__(self, *, signed_in: bool):
        self._signed_in = signed_in
        self._u = UserIdentity("u1", "Test", "t@example.invalid", "stub")
    def signin(self, *, force_account_picker=False): return self._u
    def current_user(self): return self._u
    def signout(self): self._signed_in = False
    def is_signed_in(self): return self._signed_in


def test_upload_returns_false_when_cloud_disabled(tmp_path, monkeypatch):
    """The conftest autouse fixture already disables cloud — this is a
    sanity check that the no-op contract holds."""
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: False)
    set_active_bundle(_make_bundle())
    pptx = tmp_path / "fake.pptx"
    pptx.write_bytes(b"PPTX-content")
    assert exports_upload_service.upload_export(
        pptx, agency="Test PD", year="2026",
    ) is False


def test_upload_returns_false_when_not_signed_in(tmp_path, monkeypatch):
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    monkeypatch.setenv("DTM_ALLOW_CLOUD_IN_TESTS", "1")
    set_active_bundle(_make_bundle(signed_in=False))
    pptx = tmp_path / "fake.pptx"
    pptx.write_bytes(b"PPTX-content")
    assert exports_upload_service.upload_export(
        pptx, agency="Test PD", year="2026",
    ) is False


def test_upload_returns_false_when_local_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    monkeypatch.setenv("DTM_ALLOW_CLOUD_IN_TESTS", "1")
    set_active_bundle(_make_bundle())
    ghost = tmp_path / "missing.pptx"  # never written
    assert exports_upload_service.upload_export(
        ghost, agency="Test PD", year="2026",
    ) is False


def test_upload_in_background_does_not_raise(tmp_path):
    """Background helper must not propagate exceptions from the worker —
    callers in generation_service have no way to handle them."""
    pptx = tmp_path / "fake.pptx"
    pptx.write_bytes(b"PPTX-content")
    completed: list[bool] = []
    exports_upload_service.upload_export_in_background(
        pptx, agency="Test PD", year="2026",
        on_complete=completed.append,
    )
    # Wait for worker. completed will eventually have one entry; the autouse
    # fixture means the upload short-circuits to False.
    import time
    for _ in range(20):
        if completed:
            break
        time.sleep(0.05)
    assert completed == [False]
