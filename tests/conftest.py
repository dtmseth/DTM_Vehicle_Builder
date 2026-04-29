from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.config_loader import load_configs
from dtm_buildsheet.input_reader import load_input
from dtm_buildsheet.paths import ensure_workspace


SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples" / "input"
STEARNS_XLS = SAMPLES_DIR / "Stearns_Test_Build.xlsx"
TEST_BUILD_XLS = SAMPLES_DIR / "Test Build.xlsx"


@pytest.fixture(scope="session")
def app_paths():
    return ensure_workspace()


@pytest.fixture(scope="session")
def config(app_paths):
    return load_configs(app_paths)


@pytest.fixture(scope="session")
def stearns_input():
    return load_input(STEARNS_XLS)


@pytest.fixture(scope="session")
def test_build_input():
    return load_input(TEST_BUILD_XLS)
