from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.config_loader import load_configs
from dtm_buildsheet.input_reader import load_input
from dtm_buildsheet.paths import ensure_workspace


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
