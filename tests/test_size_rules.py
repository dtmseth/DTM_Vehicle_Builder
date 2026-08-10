from __future__ import annotations

import json
from dataclasses import replace

from dtm_buildsheet.domain.parts_db_models import PartType
from dtm_buildsheet.models import PartInput, ProjectInput
from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.planning.asset_resolver import size_class_for_part
from dtm_buildsheet.planning.planner import _parts_db_render_for_part, build_plan
from dtm_buildsheet.ppt_helpers import icon_size_in_inches


def test_explicit_parts_db_profile_is_used_for_a_part():
    manifest = {
        "size_rule_definitions": {
            "sm": {"views": {}},
            "lg": {"views": {}},
        },
    }

    assert size_class_for_part(
        "Pioneer SlimLine",
        manifest,
        explicit_size_class="sm",
    ) == "sm"


def test_unassigned_part_uses_small_profile():
    manifest = {
        "size_rule_definitions": {"sm": {"views": {}}},
    }

    assert size_class_for_part(
        "Pioneer SlimLine",
        manifest,
        explicit_size_class="does-not-exist",
    ) == "sm"


def test_parts_db_sku_override_is_returned_without_copying_dimensions():
    class FakePartsDb:
        def raw_doc(self):
            return {
                "products": {
                    "pioneer": {
                        "render": {"size_rule_id": "lg"},
                        "part_numbers": [
                            {"part_number": "PSL1BB", "size_rule_id": "sm"},
                        ],
                    },
                },
            }

    render = _parts_db_render_for_part(
        "Pioneer SlimLine",
        FakePartsDb(),
        candidates=["Pioneer SlimLine", "PSL1BB"],
    )

    assert render == {"size_rule_id": "sm"}


def test_parts_db_model_alias_resolves_legacy_product_identity():
    class FakePartsDb:
        def raw_doc(self):
            return {
                "products": {
                    "pioneer": {
                        "model": "Pioneer SlimLine",
                        "model_aliases": ["PIONEER"],
                        "render": {"size_rule_id": "PN"},
                        "part_numbers": [],
                    },
                },
            }

    assert _parts_db_render_for_part("PIONEER", FakePartsDb()) == {"size_rule_id": "PN"}


def test_profile_cache_reloads_after_size_rules_save(tmp_path, monkeypatch):
    from dtm_buildsheet import ppt_helpers

    manifest_path = tmp_path / "asset_manifest.json"
    manifest_path.write_text(json.dumps({
        "size_rule_definitions": {"PN": {"views": {"front": {"w": 1.0, "h": 0.22}}}}
    }), "utf-8")
    paths = replace(AppPaths(), workspace_config_dir=tmp_path)
    monkeypatch.setattr(ppt_helpers, "_manifest_cache", None)
    monkeypatch.setattr(ppt_helpers, "_manifest_cache_path", None)
    monkeypatch.setattr(ppt_helpers, "_manifest_cache_mtime_ns", None)

    first = icon_size_in_inches("light", "Front Scene 1", "PN", "h", "", "front", paths=paths)
    manifest_path.write_text(json.dumps({
        "size_rule_definitions": {"PN": {"views": {"front": {"w": 1.25, "h": 0.22}}}}
    }), "utf-8")
    second = icon_size_in_inches("light", "Front Scene 1", "PN", "h", "", "front", paths=paths)

    assert first == (1.0, 0.22)
    assert second == (1.25, 0.22)


def test_picker_plan_uses_part_type_profile_before_default(monkeypatch, config):
    class FakePartsDb:
        def get_part_type(self, part_type_id):
            assert part_type_id == "front_scene"
            return PartType(
                part_type_id="front_scene",
                label="Front Scene",
                type_id="lights",
                category="scene",
                render={"size_rule_id": "md", "default_color_profile": "single_white"},
            )

        def raw_doc(self):
            return {"products": {}}

    monkeypatch.setattr(
        "dtm_buildsheet.app.services.parts_db_service.get_parts_db_service",
        lambda paths: FakePartsDb(),
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "SIZE-RULE"},
        parts=[PartInput(
            name="Front Scene 1",
            line_id="scene-1",
            part_type="front_scene",
            part_number="Pioneer SlimLine",
            quantity=1,
            location="TOP OF PUSH BUMPER",
        )],
        notes={},
    )

    plan = build_plan(project, config)

    assert plan.planned_parts[0].placements[0].size_class == "md"


def test_current_data_has_no_legacy_text_size_rules(config):
    assert config.asset_manifest["part_number_size_rules"] == {}


def test_current_parts_db_carries_every_migrated_light_profile(config):
    db = json.loads((config.paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))
    products = db["products"]
    expected_product_profiles = {
        "whelen_ion": "sm",
        "whelen_ion_t_hd_array": "sm",
        "whelen_surface_mount_ion": "sm",
        "whelen_ion_v_series": "sm",
        "whelen_vxe": "sq",
        "whelen_vertex": "rd",
        "whelen_m4": "md",
        "soundoff_m4": "md",
        "soundoff_mpower": "sm",
        "soundoff_mpower_3_fascia": "sm",
        "soundoff_mpower_4_fascia": "sm",
        "soundoff_nforce": "sm",
        "soundoff_nforce_deck_grille": "sm",
        "soundoff_intersector": "sm",
        "whelen_u_series": "sm",
        "whelen_mirror_beams": "sm",
        "whelen_2_lamp_tracer": "tracer",
        "whelen_tracer_3_lamp": "tracer",
        "whelen_tracer_5_lamp": "tracer",
        "whelen_tracer_6_lamp": "tracer",
        "whelen_mini_t_series": "sq",
        "whelen_t_series": "sm",
        "whelen_mega_t_series": "long",
        "whelen_field_series": "tracer",
        "whelen_pioneer_micro": "PN",
        "whelen_pioneer_nano": "PN",
        "whelen_pioneer_plus": "PN",
        "whelen_pioneer_slimline": "PN",
        "feniex_am900": "md",
        "whelen_round_lighthead": "rd",
    }

    assert {
        product_id: products[product_id].get("render", {}).get("size_rule_id")
        for product_id in expected_product_profiles
    } == expected_product_profiles
    assert products["whelen_round_lighthead"]["model_aliases"] == ["3", "6"]
    assert products["whelen_pioneer_slimline"]["model_aliases"] == ["PIONEER"]
    assert products["whelen_vxe"]["model_aliases"] == ["VXE"]
    assert products["feniex_am900"]["model_aliases"] == ["AM-900"]
    assert db["part_types"]["siren_speaker"]["render"]["size_per_view"]


def test_every_retired_light_identity_has_an_explicit_parts_db_profile(config):
    db = json.loads((config.paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))

    class RawPartsDb:
        def raw_doc(self):
            return db

    expected = {
        "3": "rd",
        "6": "rd",
        "ION": "sm",
        "T-ION": "sm",
        "SURFACE MOUNT ION": "sm",
        "STANDARD MOUNT ION": "sm",
        "VXE": "sq",
        "VERTEX": "rd",
        "M4": "md",
        "MPOWER": "sm",
        "M-POWER": "sm",
        "N-FORCE": "sm",
        "NFORCE": "sm",
        "U-SERIES": "sm",
        "MIRROR BEAMS": "sm",
        "INTERSECTORS": "sm",
        "2 LAMP TRACER": "tracer",
        "MINI T-SERIES": "sq",
        "T-SERIES": "sm",
        "FIELD SERIES": "tracer",
        "PIONEER": "PN",
        "AM-900": "md",
        "MEGA T-SERIES": "long",
        "TRACER 5 LAMP": "tracer",
        "TRACER 6 LAMP": "tracer",
    }

    for identity, profile_id in expected.items():
        assert _parts_db_render_for_part(identity, RawPartsDb()) == {
            "size_rule_id": profile_id
        }
