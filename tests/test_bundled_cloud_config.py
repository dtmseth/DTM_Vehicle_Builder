"""Sanity-check the bundled cloud_config.json defaults.

This file is what gets seeded into a teammate's workspace on first launch.
If the JSON is malformed or critical keys are missing, cloud mode silently
falls back to local on every new install — a regression we want a test to
catch before it ships.
"""

from __future__ import annotations

import json

from dtm_buildsheet.paths import DEFAULT_DATA_DIR


REQUIRED_KEYS = {
    "enabled",
    "tenant_id",
    "client_id",
    "sharepoint_site_id",
    "sharepoint_drive_id",
}


def test_bundled_cloud_config_exists_and_is_well_formed():
    path = DEFAULT_DATA_DIR / "cloud_config.json"
    assert path.exists(), f"bundled cloud_config.json missing at {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    missing = REQUIRED_KEYS - set(data)
    assert not missing, f"bundled cloud_config.json missing keys: {sorted(missing)}"


def test_bundled_cloud_config_enables_cloud_mode():
    """If enabled is False, the first-launch experience is local mode —
    almost certainly a regression. Catch it before it ships."""
    path = DEFAULT_DATA_DIR / "cloud_config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["enabled"] is True, (
        "bundled cloud_config.json should enable cloud mode by default"
    )


def test_bundled_cloud_config_values_are_non_empty_strings():
    """Empty IDs would pass the missing-key check but fail at runtime."""
    path = DEFAULT_DATA_DIR / "cloud_config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("tenant_id", "client_id", "sharepoint_site_id", "sharepoint_drive_id"):
        assert isinstance(data[key], str) and data[key].strip(), (
            f"bundled cloud_config.json: {key} must be a non-empty string"
        )
