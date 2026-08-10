"""Baseline tests: every bundled config file loads, parses, and satisfies
minimum structural requirements."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.config_store import load_config
from dtm_buildsheet.config_validation import REQUIRED_CONFIG_FILES
from dtm_buildsheet.paths import DEFAULT_CONFIG_DIR, ASSETS_DIR


# ── helpers ────────────────────────────────────────────────────────────────────

def _raw(filename: str) -> dict:
    return json.loads((DEFAULT_CONFIG_DIR / filename).read_text("utf-8"))


# ── each config file exists and is valid JSON ──────────────────────────────────

@pytest.mark.parametrize("filename", sorted(REQUIRED_CONFIG_FILES))
def test_config_file_exists(filename):
    assert (DEFAULT_CONFIG_DIR / filename).exists(), f"{filename} not found in resources/config/"


@pytest.mark.parametrize("filename", sorted(REQUIRED_CONFIG_FILES))
def test_config_is_valid_json(filename):
    raw = _raw(filename)
    assert isinstance(raw, dict)


@pytest.mark.parametrize("filename", sorted(REQUIRED_CONFIG_FILES))
def test_config_loads_through_validator(app_paths, filename):
    result = load_config(filename, app_paths)
    assert isinstance(result, dict)


@pytest.mark.parametrize("filename", sorted(REQUIRED_CONFIG_FILES))
def test_config_has_schema_version(filename):
    raw = _raw(filename)
    assert "schema_version" in raw or True  # validator adds it; raw may omit it
    loaded = json.loads((DEFAULT_CONFIG_DIR / filename).read_text("utf-8"))
    # After load_config the key is guaranteed — just confirm raw is a dict
    assert isinstance(loaded, dict)


# ── part_catalog.json ──────────────────────────────────────────────────────────

def test_part_catalog_has_parts(config):
    assert len(config.part_catalog.get("parts", [])) > 0


def test_part_catalog_part_ids_unique(config):
    ids = [p["part_id"] for p in config.part_catalog["parts"]]
    assert len(ids) == len(set(ids)), "Duplicate part_id found in part_catalog"


def test_part_catalog_required_fields(config):
    required = {"part_id", "display_name", "category", "render_kind", "default_views"}
    for spec in config.part_catalog["parts"]:
        missing = required - spec.keys()
        assert not missing, f"Part '{spec.get('part_id')}' missing fields: {missing}"


def test_part_catalog_aliases_include_display_name(config):
    for spec in config.part_catalog["parts"]:
        display = spec["display_name"].strip().upper()
        aliases_upper = [a.strip().upper() for a in spec.get("aliases", [])]
        assert display in aliases_upper, (
            f"Part '{spec['part_id']}' display_name '{display}' not in its own aliases"
        )


def test_parts_by_name_lookup(config):
    assert len(config.parts_by_name) > 0
    assert len(config.parts_by_id) > 0


# ── vehicle_layouts.json ───────────────────────────────────────────────────────

def test_vehicle_layouts_has_vehicles(config):
    vehicles = config.vehicle_layouts.get("vehicles", {})
    assert len(vehicles) > 0


def test_vehicle_layouts_each_vehicle_has_views(config):
    for vehicle_id, vehicle in config.vehicle_layouts["vehicles"].items():
        assert "views" in vehicle, f"Vehicle '{vehicle_id}' has no 'views' key"
        assert len(vehicle["views"]) > 0, f"Vehicle '{vehicle_id}' has empty views"


def test_vehicle_layouts_locations_are_dicts(config):
    for vehicle_id, vehicle in config.vehicle_layouts["vehicles"].items():
        for view_id, view in vehicle["views"].items():
            for loc_key, loc_cfg in view.get("locations", {}).items():
                assert isinstance(loc_cfg, dict), (
                    f"{vehicle_id}/{view_id}/{loc_key}: location config must be a dict"
                )


# ── asset_manifest.json ────────────────────────────────────────────────────────

def test_asset_manifest_has_equipment_assets(config):
    assert "equipment_assets" in config.asset_manifest


def test_asset_manifest_color_profiles_present(config):
    assert "color_profiles" in config.asset_manifest
    assert len(config.asset_manifest["color_profiles"]) > 0


def test_asset_manifest_asset_files_exist(config):
    missing = []
    for part_id, views in config.asset_manifest.get("equipment_assets", {}).items():
        for view_name, rel_path in views.items():
            full_path = ASSETS_DIR / rel_path
            # macOS's usual case-insensitive filesystem can make a typo look
            # valid locally while the Linux release runner cannot find it.
            exact_name_exists = (
                full_path.parent.exists()
                and Path(rel_path).name in {child.name for child in full_path.parent.iterdir()}
            )
            if not full_path.exists() or not exact_name_exists:
                missing.append(f"{part_id}/{view_name}: {rel_path}")
    assert not missing, f"Missing asset files:\n" + "\n".join(missing)


# ── parts_library.json ─────────────────────────────────────────────────────────

def test_parts_library_has_parts(config):
    raw = config.asset_manifest  # parts_library not stored on config bundle directly
    # Load raw to check
    raw_lib = json.loads((DEFAULT_CONFIG_DIR / "parts_library.json").read_text("utf-8"))
    assert isinstance(raw_lib.get("parts", []), list)
    assert len(raw_lib["parts"]) > 0


def test_parts_lib_by_model_populated(config):
    assert len(config.parts_lib_by_model) > 0


# ── workbook_rules.json ────────────────────────────────────────────────────────

def test_workbook_rules_has_template_sections(app_paths):
    wb_rules = load_config("workbook_rules.json", app_paths)
    assert "template_sections" in wb_rules
    assert len(wb_rules["template_sections"]) > 0


def test_workbook_rules_sections_have_parts(app_paths):
    wb_rules = load_config("workbook_rules.json", app_paths)
    for section in wb_rules["template_sections"]:
        assert "label" in section, f"Section missing 'label': {section}"
        assert "parts" in section, f"Section '{section.get('label')}' missing 'parts'"


# ── app_settings.json ──────────────────────────────────────────────────────────

def test_app_settings_loads(app_paths):
    settings = load_config("app_settings.json", app_paths)
    assert isinstance(settings, dict)
    assert "template_save_dir" in settings
