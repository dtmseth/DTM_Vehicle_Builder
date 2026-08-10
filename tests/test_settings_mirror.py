"""Tests for the bulk settings mirror + cloud-delete robustness.

These guard the two bugs behind the "imported agencies won't delete"
report: the batch mirror resurrecting deleted records, and silent
cloud-delete failures.
"""

from __future__ import annotations

import pytest

import dtm_buildsheet.app.services.shared_work_service as sw


class _FakeStorage:
    def __init__(self):
        self.written: dict[str, str] = {}
        self.deleted: list[str] = []
        self.fail_deletes_times = 0  # transient-failure counter

    def write_text(self, path, content):
        self.written[path] = content

    def delete(self, path):
        if self.fail_deletes_times > 0:
            self.fail_deletes_times -= 1
            raise RuntimeError("429 throttled")
        self.deleted.append(path)


@pytest.fixture
def storage(monkeypatch):
    s = _FakeStorage()
    monkeypatch.setattr(sw, "_cloud_storage", lambda: s)
    return s


# ── batch mirror skips deleted files (race fix) ──────────────────────────────


def test_batch_mirror_uploads_existing_files(tmp_path, storage):
    a = tmp_path / "a.json"; a.write_text("A", encoding="utf-8")
    b = tmp_path / "b.json"; b.write_text("B", encoding="utf-8")
    uploaded = sw._mirror_settings_batch(
        [("agencies/a.json", str(a)), ("agencies/b.json", str(b))]
    )
    assert uploaded == 2
    assert storage.written["Settings/agencies/a.json"] == "A"


def test_batch_mirror_skips_file_deleted_mid_import(tmp_path, storage):
    a = tmp_path / "a.json"; a.write_text("A", encoding="utf-8")
    gone = tmp_path / "gone.json"  # never created — simulates a delete during import
    uploaded = sw._mirror_settings_batch(
        [("agencies/a.json", str(a)), ("agencies/gone.json", str(gone))]
    )
    assert uploaded == 1
    assert "Settings/agencies/gone.json" not in storage.written  # not resurrected


# ── cloud delete: no-cloud success, retry, surfaced failure ──────────────────


def test_delete_returns_true_when_no_cloud(monkeypatch):
    monkeypatch.setattr(sw, "_cloud_storage", lambda: None)
    assert sw.delete_setting_from_cloud("agencies/x.json") is True


def test_delete_retries_transient_failure(storage, monkeypatch):
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda *_: None)
    storage.fail_deletes_times = 1  # first delete throws, retry succeeds
    ok = sw.delete_setting_from_cloud("agencies/x.json")
    assert ok is True
    assert "Settings/agencies/x.json" in storage.deleted


def test_delete_reports_failure_after_exhausting_retries(storage, monkeypatch):
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda *_: None)
    storage.fail_deletes_times = 99  # always fails
    ok = sw.delete_setting_from_cloud("agencies/x.json", attempts=2)
    assert ok is False
