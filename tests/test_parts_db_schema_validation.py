"""Phase 3 (schema v2): parts_db.json + legacy_workbook_index.json validators."""
from __future__ import annotations

import pytest

from dtm_buildsheet.config.schemas import REQUIRED_CONFIG_FILES, validate_config_payload
from dtm_buildsheet.config.store import load_config, save_config
from dtm_buildsheet.paths import AppPaths


class TestRegistration:
    def test_parts_db_in_required(self):
        assert "parts_db.json" in REQUIRED_CONFIG_FILES

    def test_legacy_index_in_required(self):
        assert "legacy_workbook_index.json" in REQUIRED_CONFIG_FILES


class TestPartsDbValidator:
    def test_accepts_minimum_valid_doc(self):
        result = validate_config_payload("parts_db.json", {
            "schema_version": 2,
            "products": {
                "ok": {"manufacturer_id": "whelen", "model": "ION T"},
            },
            "part_types": {
                "forward_warning": {"label": "Forward Warning", "type_id": "lights"},
            },
        })
        # All top-level keys get filled
        for key in ("types", "sections", "zones", "sub_zones", "build_attributes",
                    "tags", "manufacturers", "placements", "placement_zones",
                    "services", "preference_filters", "color_palette", "naming_rules"):
            assert key in result

    def test_rejects_non_dict_products(self):
        with pytest.raises(ValueError, match="'products' must be an object"):
            validate_config_payload("parts_db.json", {"products": []})

    def test_rejects_product_missing_manufacturer_id(self):
        with pytest.raises(ValueError, match="manufacturer_id"):
            validate_config_payload("parts_db.json", {
                "products": {"x": {"model": "Y"}},
            })

    def test_rejects_product_missing_model(self):
        with pytest.raises(ValueError, match="model"):
            validate_config_payload("parts_db.json", {
                "products": {"x": {"manufacturer_id": "whelen"}},
            })

    def test_rejects_product_non_list_fits(self):
        with pytest.raises(ValueError, match="fits_part_types"):
            validate_config_payload("parts_db.json", {
                "products": {"x": {"manufacturer_id": "whelen", "model": "Y",
                                    "fits_part_types": "not a list"}},
            })

    def test_rejects_product_non_list_location_options(self):
        with pytest.raises(ValueError, match="location_options"):
            validate_config_payload("parts_db.json", {
                "products": {"x": {"manufacturer_id": "whelen", "model": "Y",
                                    "location_options": "not a list"}},
            })

    def test_rejects_product_non_string_fixed_location(self):
        with pytest.raises(ValueError, match="fixed_location"):
            validate_config_payload("parts_db.json", {
                "products": {"x": {"manufacturer_id": "whelen", "model": "Y",
                                    "fixed_location": ["ON REAR PARTITION"]}},
            })

    def test_rejects_part_type_missing_label(self):
        with pytest.raises(ValueError, match="label"):
            validate_config_payload("parts_db.json", {
                "part_types": {"x": {"type_id": "lights"}},
            })

    def test_rejects_part_type_tree_position_missing_zone(self):
        with pytest.raises(ValueError, match="zone"):
            validate_config_payload("parts_db.json", {
                "part_types": {"x": {
                    "label": "X", "type_id": "lights",
                    "tree_positions": [{"section": "exterior"}],
                }},
            })


class TestPartsDbRoundtrip:
    def test_save_then_load(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        doc = {
            "schema_version": 2,
            "products": {
                "whelen_ion_t": {"manufacturer_id": "whelen", "model": "ION T",
                                  "part_numbers": [{"part_number": "ION-T-RW"}]},
            },
            "part_types": {
                "forward_warning": {
                    "label": "Forward Warning", "type_id": "lights",
                    "tree_positions": [{"section": "exterior", "zone": "front"}],
                },
            },
        }
        save_config("parts_db.json", doc, paths)
        loaded = load_config("parts_db.json", paths)
        assert loaded["products"]["whelen_ion_t"]["model"] == "ION T"


class TestLegacyIndexValidator:
    def test_accepts_minimum(self):
        result = validate_config_payload("legacy_workbook_index.json", {"schema_version": 1})
        assert result["part_type_to_products"] == {}

    def test_rejects_non_dict_map(self):
        with pytest.raises(ValueError, match="part_type_to_products"):
            validate_config_payload("legacy_workbook_index.json", {"part_type_to_products": []})
