"""Phase 3: dual-read fallback behavior.

The PR-1 service stands up parts_db.json reads with a workbook_rules.json
fallback so consumers don't break before the migration script (PR-2) emits
data. These tests pin the four name-keyed compat shims behave as designed:
 - parts_db wins when it has the answer
 - workbook_rules takes over when parts_db is empty / missing / partial
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.services import parts_db_service
from dtm_buildsheet.app.services.parts_db_service import PartsDbService
from dtm_buildsheet.paths import AppPaths


@pytest.fixture(autouse=True)
def _reset_singleton():
    parts_db_service.reset_for_testing()
    yield
    parts_db_service.reset_for_testing()


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), "utf-8")


def _seed_workbook_only(tmp_path: Path) -> AppPaths:
    """workbook_rules.json only — parts_db missing, fallback should engage."""
    _write(
        tmp_path / "workbook_rules.json",
        {
            "schema_version": 1,
            "template_sections": [],
            "part_rules": {
                "Forward Warning 1": {
                    "manufacturer": ["Whelen", "Federal Signal"],
                    "models": ["ION-T-1", "ION-T-T-T"],
                    "locations": ["GRILL", "PUSH_BUMPER_TOP"],
                    "colors": ["Red", "Blue"],
                    "quantities": [1, 2],
                    "lens": [],
                },
            },
        },
    )
    return AppPaths(workspace_config_dir=tmp_path)


def _seed_workbook_and_partial_db(tmp_path: Path) -> AppPaths:
    """Both files present; parts_db has the part but lacks some fields.

    Verifies the per-field fallthrough: parts_db wins where it has data,
    workbook_rules fills the gaps.
    """
    _write(
        tmp_path / "workbook_rules.json",
        {
            "schema_version": 1,
            "template_sections": [],
            "part_rules": {
                "Forward Warning 1": {
                    "manufacturer": ["Whelen"],
                    "models": ["ION-T-1"],
                    "locations": ["GRILL"],
                },
            },
        },
    )
    # parts_db has the part with a complete manufacturer/model chain, but no
    # compatible_locations_by_vehicle. locations_by_legacy_name should then
    # fall through to workbook_rules.
    _write(
        tmp_path / "parts_db.json",
        {
            "schema_version": 1,
            "parts": {
                "whelen_ion_t": {
                    "friendly_name": "Whelen ION T-Series",
                    "legacy_workbook_name": "Forward Warning 1",
                    "category": "lights",
                    "manufacturer_id": "whelen",
                    "models": [{"model_id": "ion_t_1", "model_number": "ION-T-1"}],
                },
            },
            "manufacturers": {"whelen": {"label": "Whelen"}},
        },
    )
    return AppPaths(workspace_config_dir=tmp_path)


# ── Pure fallback (parts_db missing) ─────────────────────────────────────────


class TestFallbackWhenDbMissing:
    def test_manufacturers_fall_through(self, tmp_path):
        paths = _seed_workbook_only(tmp_path)
        svc = PartsDbService(paths)
        assert svc.manufacturers_by_legacy_name("Forward Warning 1") == [
            "Whelen",
            "Federal Signal",
        ]

    def test_models_fall_through(self, tmp_path):
        paths = _seed_workbook_only(tmp_path)
        svc = PartsDbService(paths)
        assert svc.models_by_legacy_name("Forward Warning 1") == [
            "ION-T-1",
            "ION-T-T-T",
        ]

    def test_locations_fall_through(self, tmp_path):
        paths = _seed_workbook_only(tmp_path)
        svc = PartsDbService(paths)
        assert svc.locations_by_legacy_name("Forward Warning 1") == [
            "GRILL",
            "PUSH_BUMPER_TOP",
        ]

    def test_unknown_part_returns_empty_list(self, tmp_path):
        paths = _seed_workbook_only(tmp_path)
        svc = PartsDbService(paths)
        # workbook_rules has no entry for this name; fallback is also empty
        assert svc.manufacturers_by_legacy_name("Phantom Light") == []
        assert svc.models_by_legacy_name("Phantom Light") == []
        assert svc.locations_by_legacy_name("Phantom Light") == []


# ── Mixed: parts_db wins on fields it has; fallback fills the rest ───────────


class TestPartialDbFallback:
    def test_manufacturer_from_db_wins(self, tmp_path):
        svc = PartsDbService(_seed_workbook_and_partial_db(tmp_path))
        # parts_db.manufacturers["whelen"].label = "Whelen"
        assert svc.manufacturers_by_legacy_name("Forward Warning 1") == ["Whelen"]

    def test_models_from_db_wins(self, tmp_path):
        svc = PartsDbService(_seed_workbook_and_partial_db(tmp_path))
        assert svc.models_by_legacy_name("Forward Warning 1") == ["ION-T-1"]

    def test_locations_fall_through_when_db_has_none(self, tmp_path):
        svc = PartsDbService(_seed_workbook_and_partial_db(tmp_path))
        # parts_db has the part but no compatible_locations_by_vehicle
        # → falls back to workbook_rules locations
        assert svc.locations_by_legacy_name("Forward Warning 1") == ["GRILL"]
