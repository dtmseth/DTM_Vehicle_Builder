"""Phase 3 (revised): parts_db.json + legacy_workbook_index.json validators.

Manufacturer-centric schema. Validates top-level shape, required product
keys (manufacturer_id, category_id, model), and part_numbers list shape.
Deep validation (cross-reference manufacturers, etc.) is deferred to
Phase 4.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.config.schemas import REQUIRED_CONFIG_FILES, validate_config_payload
from dtm_buildsheet.config.store import load_config, save_config
from dtm_buildsheet.paths import AppPaths


class TestRegistration:
    def test_parts_db_in_required(self):
        assert "parts_db.json" in REQUIRED_CONFIG_FILES

    def test_legacy_index_in_required(self):
        assert "legacy_workbook_index.json" in REQUIRED_CONFIG_FILES


# ── parts_db.json ────────────────────────────────────────────────────────────


class TestPartsDbValidator:
    def test_accepts_minimum_valid_doc(self):
        result = validate_config_payload("parts_db.json", {
            "schema_version": 1,
            "products": {
                "ok": {
                    "manufacturer_id": "whelen",
                    "category_id": "lights",
                    "model": "ION T-Series",
                },
            },
        })
        # Missing top-level blocks get filled in
        for key in ("categories", "manufacturers", "color_palette",
                    "location_zones", "location_zone_map", "part_types",
                    "option_axes_catalog", "naming_rules"):
            assert key in result

    def test_rejects_non_dict_products(self):
        with pytest.raises(ValueError, match="'products' must be an object"):
            validate_config_payload("parts_db.json", {"schema_version": 1, "products": []})

    def test_rejects_product_missing_manufacturer_id(self):
        with pytest.raises(ValueError, match="manufacturer_id"):
            validate_config_payload("parts_db.json", {
                "schema_version": 1,
                "products": {"x": {"category_id": "lights", "model": "Y"}},
            })

    def test_rejects_product_missing_category_id(self):
        with pytest.raises(ValueError, match="category_id"):
            validate_config_payload("parts_db.json", {
                "schema_version": 1,
                "products": {"x": {"manufacturer_id": "whelen", "model": "Y"}},
            })

    def test_rejects_product_missing_model(self):
        with pytest.raises(ValueError, match="model"):
            validate_config_payload("parts_db.json", {
                "schema_version": 1,
                "products": {"x": {"manufacturer_id": "whelen", "category_id": "lights"}},
            })

    def test_rejects_part_number_missing_part_number(self):
        with pytest.raises(ValueError, match="part_number"):
            validate_config_payload("parts_db.json", {
                "schema_version": 1,
                "products": {
                    "x": {
                        "manufacturer_id": "whelen",
                        "category_id": "lights",
                        "model": "Y",
                        "part_numbers": [{"friendly_name": "no part_number"}],
                    },
                },
            })

    def test_rejects_option_axes_non_dict(self):
        with pytest.raises(ValueError, match="option_axes"):
            validate_config_payload("parts_db.json", {
                "schema_version": 1,
                "products": {
                    "x": {
                        "manufacturer_id": "whelen",
                        "category_id": "lights",
                        "model": "Y",
                        "option_axes": [],  # wrong shape
                    },
                },
            })


class TestPartsDbRoundtrip:
    def test_save_then_load(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        doc = {
            "schema_version": 1,
            "products": {
                "whelen_ion_t": {
                    "manufacturer_id": "whelen",
                    "category_id": "lights",
                    "model": "ION T-Series",
                    "part_numbers": [{"part_number": "ION-T-RW"}],
                },
            },
        }
        save_config("parts_db.json", doc, paths)
        loaded = load_config("parts_db.json", paths)
        assert loaded["products"]["whelen_ion_t"]["model"] == "ION T-Series"


# ── legacy_workbook_index.json ───────────────────────────────────────────────


class TestLegacyIndexValidator:
    def test_accepts_minimum(self):
        result = validate_config_payload("legacy_workbook_index.json", {"schema_version": 1})
        assert result["part_type_to_products"] == {}
        assert result["model_string_to_product"] == {}

    def test_rejects_non_dict_map(self):
        with pytest.raises(ValueError, match="part_type_to_products"):
            validate_config_payload("legacy_workbook_index.json", {
                "schema_version": 1,
                "part_type_to_products": [],
            })

    def test_roundtrip(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        doc = {
            "schema_version": 1,
            "part_type_to_products": {"Forward Warning 1": ["whelen_ion_t"]},
            "model_string_to_product": {"ION": "whelen_ion_t"},
        }
        save_config("legacy_workbook_index.json", doc, paths)
        loaded = load_config("legacy_workbook_index.json", paths)
        assert loaded["model_string_to_product"]["ION"] == "whelen_ion_t"
