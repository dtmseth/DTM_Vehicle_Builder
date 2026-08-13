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
from types import SimpleNamespace

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


def test_portable_export_filename_handles_windows_paths():
    assert exports_upload_service.portable_export_filename(
        r"C:\Users\Builder\output\Agency_Unit_2026.pdf"
    ) == "Agency_Unit_2026.pdf"


def test_stable_export_stem_groups_pptx_and_pdf_versions():
    assert exports_upload_service.stable_export_stem(
        "Agency_39_2026_Updated_Aug13_2026_11-18-12AM.pptx"
    ) == "Agency_39_2026_Updated"
    assert exports_upload_service.stable_export_stem(
        "Agency_39_2026_Updated_Aug12_2026_9-01-02AM.pdf"
    ) == "Agency_39_2026_Updated"


def test_download_export_hydrates_shared_pdf(tmp_path, monkeypatch):
    output = tmp_path / "output"
    paths = SimpleNamespace(workspace_output_dir=output)
    bundle = SimpleNamespace(storage=SimpleNamespace(_token_provider=lambda: "TOKEN"))
    config = SimpleNamespace(
        exports_enabled=True,
        exports_base_folder="Vehicle Builder Projects",
    )
    monkeypatch.setattr(exports_upload_service, "_bundle_or_none", lambda **kwargs: bundle)
    monkeypatch.setattr(exports_upload_service, "_get_export_drive_id", lambda b, c: "DRIVE")
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.load_cloud_config_from_env",
        lambda: config,
    )
    seen = {}
    def fake_get(url, **kwargs):
        seen["url"] = url
        return SimpleNamespace(status_code=200, content=b"%PDF-1.7\nshared")
    monkeypatch.setattr(exports_upload_service.requests, "get", fake_get)

    result = exports_upload_service.download_export(
        paths,
        source_path=r"C:\old-machine\Seth_Test_Unit_39.pdf",
        agency="Seth Test",
        year="2026",
    )

    assert result["ok"] is True and result["downloaded"] is True
    assert Path(result["path"]).read_bytes().startswith(b"%PDF-")
    assert "Vehicle%20Builder%20Projects/Seth%20Test/2026/Seth_Test_Unit_39.pdf" in seen["url"]


def test_delete_shared_exports_removes_all_vehicle_versions(monkeypatch):
    bundle = SimpleNamespace(storage=SimpleNamespace(_token_provider=lambda: "TOKEN"))
    config = SimpleNamespace(
        exports_enabled=True,
        exports_base_folder="Vehicle Builder Projects",
    )
    monkeypatch.setattr(exports_upload_service, "_bundle_or_none", lambda **kwargs: bundle)
    monkeypatch.setattr(exports_upload_service, "_get_export_drive_id", lambda b, c: "DRIVE")
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.load_cloud_config_from_env",
        lambda: config,
    )
    old_pptx = "Agency_39_2026_Updated_Aug12_2026_9-01-02AM.pptx"
    old_pdf = "Agency_39_2026_Updated_Aug12_2026_9-01-02AM.pdf"
    keep = "Agency_39_2026_Updated_Aug13_2026_11-18-12AM.pptx"
    unrelated = "Agency_40_2026_Updated_Aug12_2026_9-01-02AM.pdf"
    monkeypatch.setattr(
        exports_upload_service.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: {"value": [
                {"name": old_pptx, "file": {}},
                {"name": old_pdf, "file": {}},
                {"name": keep, "file": {}},
                {"name": unrelated, "file": {}},
            ]},
        ),
    )
    deleted_urls = []
    monkeypatch.setattr(
        exports_upload_service.requests,
        "delete",
        lambda url, **kwargs: (
            deleted_urls.append(url) or SimpleNamespace(status_code=204)
        ),
    )

    result = exports_upload_service.delete_shared_exports(
        agency="Agency", year="2026", filenames=[old_pptx], keep_filename=keep,
    )

    assert result["ok"] is True
    assert sorted(result["deleted"]) == sorted([old_pptx, old_pdf])
    assert all(unrelated not in url for url in deleted_urls)
    assert all(keep not in url for url in deleted_urls)


def test_cleanup_previous_exports_keeps_current_pair_and_removes_old_local_versions(
    tmp_path, monkeypatch,
):
    output = tmp_path / "output"
    output.mkdir()
    old_pptx = output / "Agency_39_2026_Updated_Aug12_2026_9-01-02AM.pptx"
    old_pdf = old_pptx.with_suffix(".pdf")
    keep_pptx = output / "Agency_39_2026_Updated_Aug13_2026_11-18-12AM.pptx"
    keep_pdf = keep_pptx.with_suffix(".pdf")
    unrelated = output / "Agency_40_2026_Updated_Aug12_2026_9-01-02AM.pdf"
    for candidate in (old_pptx, old_pdf, keep_pptx, keep_pdf, unrelated):
        candidate.write_bytes(b"test")
    monkeypatch.setattr(
        exports_upload_service,
        "delete_shared_exports",
        lambda **kwargs: {"ok": True, "deleted": [], "errors": []},
    )

    result = exports_upload_service.cleanup_previous_exports(
        SimpleNamespace(workspace_output_dir=output),
        agency="Agency",
        year="2026",
        filenames=[str(old_pptx), str(old_pdf)],
        keep_filenames=[str(keep_pptx), str(keep_pdf)],
    )

    assert result["ok"] is True
    assert not old_pptx.exists() and not old_pdf.exists()
    assert keep_pptx.exists() and keep_pdf.exists() and unrelated.exists()
