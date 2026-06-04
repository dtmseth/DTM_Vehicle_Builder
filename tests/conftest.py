from __future__ import annotations

import os
from pathlib import Path

import pytest

from dtm_buildsheet.config_loader import load_configs
from dtm_buildsheet.input_reader import load_input
from dtm_buildsheet.paths import ensure_workspace


# ── CRITICAL: hard-block real cloud I/O for every test ───────────────────────
# Without this, any test that calls save_project / save_draft / save_agency /
# save_preset / handle_save_rep on a developer machine with cloud_config.json
# in the workspace silently mirrors its fixtures up to the real SharePoint —
# /Projects/, /Drafts/, /PendingChanges/, /Settings/agencies/, etc. all end
# up polluted with Test PD / Test Customer junk that the developer didn't
# create and has to clean up by hand.
#
# Three guards working together:
#   1. Autouse fixture (here) sets DTM_CLOUD=0 + monkeypatches
#      wiring._cloud_flag_enabled to False before every single test.
#   2. The same fixture installs a LocalStorageProvider-backed bundle so
#      even if a test somehow re-enables the flag, the storage adapter is
#      filesystem-only.
#   3. Defense-in-depth check in shared_work_service._cloud_storage() and
#      wiring.save_via_proposal() refuses to operate when
#      PYTEST_CURRENT_TEST is set in the environment — pytest sets that
#      automatically. Even a future test that monkeypatches around the
#      conftest fixture would still get blocked at the call site.
#
# Tests that need to exercise cloud behavior (test_shared_work_service,
# test_cloud_status_service, etc.) opt back in via their own cloud_on
# fixture that monkeypatches the flag back to True AFTER setting up a
# fake remote — never the real SharePoint.


@pytest.fixture(autouse=True)
def _block_real_cloud(monkeypatch):
    """Disable cloud mode + install a local-only bundle for every test."""
    monkeypatch.setenv("DTM_CLOUD", "0")
    from dtm_buildsheet.app.adapters import wiring
    from dtm_buildsheet.app.adapters.wiring import build_local_bundle, set_active_bundle

    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: False)
    set_active_bundle(build_local_bundle())
    yield
    # Tear down the bundle override so test-state doesn't leak across runs.
    wiring._active_bundle = None  # noqa: SLF001


SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples" / "input"

def _sample_workbooks() -> list[Path]:
    return sorted(SAMPLES_DIR.glob("*.xlsx"))

# Primary sample — first xlsx found in samples/input/
_samples = _sample_workbooks()
PRIMARY_XLS = _samples[0] if _samples else None
SECONDARY_XLS = _samples[1] if len(_samples) > 1 else PRIMARY_XLS


@pytest.fixture(scope="session")
def app_paths():
    return ensure_workspace()


@pytest.fixture(scope="session")
def config(app_paths):
    return load_configs(app_paths)


@pytest.fixture(scope="session")
def stearns_input():
    return load_input(PRIMARY_XLS)


@pytest.fixture(scope="session")
def test_build_input():
    return load_input(SECONDARY_XLS)
