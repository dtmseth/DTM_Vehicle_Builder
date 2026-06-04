"""Tests for the multi-layer guard that blocks real cloud I/O during tests.

These tests are deliberately paranoid — if any of them ever fail, a future
test run could silently mirror its fixtures to the real SharePoint. We
verify all three guards (conftest autouse fixture, PYTEST_CURRENT_TEST
env var check, no real bundle constructed) independently.

If you find yourself needing to disable a guard to make a test pass:
DON'T. Set up a fake remote and explicitly enable cloud mode for THAT
test only — there's a pattern for that in test_shared_work_service.py.
"""

from __future__ import annotations

import os
from pathlib import Path

from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.adapters.wiring import save_via_proposal
from dtm_buildsheet.app.services import shared_work_service


def test_pytest_current_test_env_var_is_always_set_during_tests():
    """Sanity check the precondition: pytest sets this env var for us.
    Used by the inline guards in _cloud_storage and save_via_proposal."""
    assert os.environ.get("PYTEST_CURRENT_TEST"), (
        "PYTEST_CURRENT_TEST should be set during a pytest run — the inline "
        "cloud-isolation guards depend on it"
    )


def test_conftest_disables_cloud_flag():
    """The autouse fixture in tests/conftest.py must leave cloud disabled."""
    assert wiring._cloud_flag_enabled() is False  # noqa: SLF001


def test_conftest_installs_local_bundle():
    """Even if cloud were enabled, the bundle should be local-only."""
    bundle = wiring.get_active_bundle()
    # LocalStorageProvider has no network surface; ensure we got that one
    # (not SharePointGraphProvider which would talk to real Graph).
    from dtm_buildsheet.storage.local import LocalStorageProvider
    assert isinstance(bundle.storage, LocalStorageProvider)


def test_cloud_storage_refuses_when_pytest_env_var_set(monkeypatch):
    """Override the conftest defaults — try to force cloud on with a fake
    bundle — and verify the PYTEST_CURRENT_TEST guard still blocks I/O."""
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    # Don't set the bundle; pretend a test tried to skip the override.
    assert shared_work_service._cloud_storage() is None


def test_save_via_proposal_refuses_in_test_env(monkeypatch):
    """save_via_proposal must short-circuit even with a 'real' cloud config."""
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    result = save_via_proposal(
        target_file="agencies/test-id.json",
        serialized_content='{"hello": "world"}',
        summary="should never reach cloud",
        category="general",
    )
    assert result == {"proposed": False, "reason": "test environment"}


def test_mirror_project_refuses_in_test_env(monkeypatch, tmp_path):
    """mirror_project_to_cloud goes through _cloud_storage so the env-var
    guard there should also block this path."""
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    fake_local = tmp_path / "project.json"
    fake_local.write_text('{"x": 1}', "utf-8")
    assert shared_work_service.mirror_project_to_cloud("proj-1", fake_local) is False


def test_ensure_signed_in_refuses_in_test_env(monkeypatch):
    """No OAuth prompts during pytest, even if a test re-enables cloud."""
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)
    assert wiring.ensure_signed_in_for_cloud() is False
