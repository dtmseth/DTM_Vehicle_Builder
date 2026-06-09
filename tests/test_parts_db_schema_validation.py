"""Phase 3: parts_db.json validator coverage.

Phase 3 validation is intentionally minimal — see plan §1 and the doctring on
`_validate_parts_db` in config/schemas.py. Deep validation lands in Phase 4
when users can edit through the UI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.config.schemas import REQUIRED_CONFIG_FILES, validate_config_payload
from dtm_buildsheet.config.store import load_config, save_config
from dtm_buildsheet.paths import AppPaths


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), "utf-8")


class TestRegistration:
    def test_in_required_config_files(self):
        assert "parts_db.json" in REQUIRED_CONFIG_FILES


class TestValidator:
    def test_accepts_minimum_valid_doc(self):
        result = validate_config_payload(
            "parts_db.json",
            {
                "schema_version": 1,
                "parts": {
                    "ok_part": {
                        "friendly_name": "OK",
                        "category": "lights",
                    },
                },
            },
        )
        # Missing top-level blocks get filled in with empty dicts
        for key in (
            "part_categories",
            "location_zones",
            "locations",
            "build_sections",
            "manufacturers",
            "color_palette",
            "naming_rules",
        ):
            assert key in result

    def test_rejects_non_dict_parts(self):
        with pytest.raises(ValueError, match="'parts' must be an object"):
            validate_config_payload(
                "parts_db.json",
                {"schema_version": 1, "parts": []},
            )

    def test_rejects_part_missing_friendly_name(self):
        with pytest.raises(ValueError, match="friendly_name"):
            validate_config_payload(
                "parts_db.json",
                {
                    "schema_version": 1,
                    "parts": {"broken": {"category": "lights"}},
                },
            )

    def test_rejects_part_missing_category(self):
        with pytest.raises(ValueError, match="category"):
            validate_config_payload(
                "parts_db.json",
                {
                    "schema_version": 1,
                    "parts": {"broken": {"friendly_name": "X"}},
                },
            )

    def test_rejects_model_missing_model_id(self):
        with pytest.raises(ValueError, match="model_id"):
            validate_config_payload(
                "parts_db.json",
                {
                    "schema_version": 1,
                    "parts": {
                        "ok": {
                            "friendly_name": "X",
                            "category": "lights",
                            "models": [{"model_number": "X-1"}],  # no model_id
                        },
                    },
                },
            )


class TestRoundtrip:
    def test_save_then_load(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        doc = {
            "schema_version": 1,
            "parts": {
                "whelen_ion_t": {
                    "friendly_name": "Whelen ION T",
                    "category": "lights",
                    "models": [{"model_id": "ion_t_1"}],
                },
            },
        }
        save_config("parts_db.json", doc, paths)
        loaded = load_config("parts_db.json", paths)
        assert loaded["parts"]["whelen_ion_t"]["friendly_name"] == "Whelen ION T"
