from __future__ import annotations

from dtm_buildsheet.app.services.draft_service import (
    handle_add_custom_part_to_draft,
    handle_update_custom_part_in_draft,
)
from dtm_buildsheet.config_loader import load_configs
from dtm_buildsheet.inputs.project_drafts import (
    draft_to_project_input,
    load_draft,
    new_draft,
    save_draft,
)
from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.planning.planner import build_plan


def _isolated_paths(tmp_path, app_paths: AppPaths) -> AppPaths:
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_drafts_dir=drafts,
        workspace_config_dir=app_paths.workspace_config_dir,
        workspace_assets_dir=app_paths.workspace_assets_dir,
        workspace_presets_dir=app_paths.workspace_presets_dir,
    )


def _draft(paths: AppPaths):
    draft = new_draft(vehicle_info={"VehicleType": "PIU", "ProjectID": "CUSTOM-LIGHT"})
    save_draft(draft, paths.workspace_drafts_dir)
    return draft


def test_custom_part_light_rendering_is_opt_in(tmp_path, app_paths):
    paths = _isolated_paths(tmp_path, app_paths)
    draft = _draft(paths)

    result = handle_add_custom_part_to_draft(draft.draft_id, {
        "sku": "CUSTOM-BRACKET",
        "description": "One-off mounting bracket",
        "unit_price": 75,
        "quantity": 1,
        "location": "CENTER CONSOLE",
    }, paths)

    assert result["ok"] is True
    saved = load_draft(draft.draft_id, paths.workspace_drafts_dir).parts[0]
    assert "custom_light" not in saved.picker_config
    plan = build_plan(draft_to_project_input(load_draft(draft.draft_id, paths.workspace_drafts_dir)), load_configs(paths))
    planned = next(part for part in plan.planned_parts if part.raw.line_id == saved.line_id)
    assert planned.render_kind == "none"
    assert planned.placements == []


def test_custom_light_uses_normal_picker_colors_and_standard_location(tmp_path, app_paths):
    paths = _isolated_paths(tmp_path, app_paths)
    draft = _draft(paths)

    result = handle_add_custom_part_to_draft(draft.draft_id, {
        "sku": "PROTO-LIGHT",
        "description": "Prototype warning light",
        "unit_price": 125,
        "quantity": 3,
        "location": "GRILL",
        "qb_import": {"estimate_id": "905", "line_id": "custom-light-line"},
        "custom_light": {
            "enabled": True,
            "size_rule_id": "md",
            "lens": "smoked",
            "heads": [
                {"colors": ["red", "white"]},
                {"colors": ["blue", "white"]},
                {"colors": ["amber", "white"]},
            ],
            "picker_config": {
                "mode": "custom", "colorsPerHead": "duo",
                "uniform": ["red", "white"], "splitSecondary": ["white"],
                "custom": [["red", "white"], ["blue", "white"], ["amber", "white"]],
                "count": 3, "lens": "smoked",
            },
        },
    }, paths)

    assert result["ok"] is True
    saved_draft = load_draft(draft.draft_id, paths.workspace_drafts_dir)
    saved = saved_draft.parts[0]
    assert saved.location == "GRILL"
    assert saved.lens == "smoked"
    assert saved.picker_config["custom_light"]["size_rule_id"] == "md"
    assert saved.picker_config["qb_import"] == {
        "estimate_id": "905", "line_id": "custom-light-line",
    }
    assert saved.picker_config["custom"] == [
        ["red", "white"], ["blue", "white"], ["amber", "white"],
    ]

    plan = build_plan(draft_to_project_input(saved_draft), load_configs(paths))
    planned = next(part for part in plan.planned_parts if part.raw.line_id == saved.line_id)
    assert planned.render_kind == "light"
    assert planned.on_diagram is True
    assert {placement.location_key for placement in planned.placements} == {"GRILL"}
    assert {placement.size_class for placement in planned.placements} == {"md"}
    assert [instance.color_token for instance in planned.placements[0].instances] == [
        "red-white", "blue-white", "white-amber",
    ]


def test_custom_light_rejects_incomplete_head_assignments(tmp_path, app_paths):
    paths = _isolated_paths(tmp_path, app_paths)
    draft = _draft(paths)

    result = handle_add_custom_part_to_draft(draft.draft_id, {
        "sku": "PROTO-LIGHT",
        "description": "Prototype warning light",
        "unit_price": 125,
        "quantity": 2,
        "location": "GRILL",
        "custom_light": {
            "enabled": True,
            "size_rule_id": "sm",
            "heads": [{"colors": ["red"]}],
        },
    }, paths)

    assert result["ok"] is False
    assert result["error"] == "assign one color configuration to each custom light head"
    assert load_draft(draft.draft_id, paths.workspace_drafts_dir).parts == []


def test_custom_light_preserves_normal_free_placement(tmp_path, app_paths):
    paths = _isolated_paths(tmp_path, app_paths)
    draft = _draft(paths)

    result = handle_add_custom_part_to_draft(draft.draft_id, {
        "sku": "PROTO-FREE",
        "description": "Free placed custom light",
        "unit_price": 90,
        "quantity": 2,
        "location": "CUSTOM GRILLE ROW",
        "custom_light": {
            "enabled": True,
            "size_rule_id": "sm",
            "lens": "clear",
            "heads": [{"colors": ["red"]}, {"colors": ["blue"]}],
            "picker_config": {
                "mode": "custom", "colorsPerHead": "single",
                "uniform": ["red"], "splitSecondary": [],
                "custom": [["red"], ["blue"]], "count": 2, "lens": "clear",
                "custom_location": {
                    "label": "CUSTOM GRILLE ROW", "render_location": "",
                    "placements": {"front": [
                        {"x": 0.42, "y": 0.7, "head_index": 0, "group_id": "row"},
                        {"x": 0.58, "y": 0.7, "head_index": 1, "group_id": "row"},
                    ]},
                    "anchors": {"front": {"x": 0.5, "y": 0.7}},
                    "spacing": 0.16, "layout": "even",
                },
            },
        },
    }, paths)

    assert result["ok"] is True
    saved_draft = load_draft(draft.draft_id, paths.workspace_drafts_dir)
    saved = saved_draft.parts[0]
    assert saved.picker_config["custom_location"]["placements"]["front"][1]["head_index"] == 1

    plan = build_plan(draft_to_project_input(saved_draft), load_configs(paths))
    planned = next(part for part in plan.planned_parts if part.raw.line_id == saved.line_id)
    assert [placement.location_key for placement in planned.placements] == [
        "CUSTOM:FRONT:1", "CUSTOM:FRONT:2",
    ]
    assert [placement.instances[0].color_token for placement in planned.placements] == [
        "red", "blue",
    ]


def test_custom_light_update_preserves_split_picker_mode(tmp_path, app_paths):
    paths = _isolated_paths(tmp_path, app_paths)
    draft = _draft(paths)
    added = handle_add_custom_part_to_draft(draft.draft_id, {
        "sku": "PROTO-SPLIT", "description": "Split custom light",
        "unit_price": 100, "quantity": 1, "location": "GRILL",
    }, paths)
    assert added["ok"] is True

    result = handle_update_custom_part_in_draft(draft.draft_id, added["line_id"], {
        "sku": "PROTO-SPLIT", "description": "Split custom light",
        "unit_price": 100, "quantity": 2, "location": "TAIL LIGHTS",
        "custom_light": {
            "enabled": True, "size_rule_id": "lg", "lens": "clear",
            "heads": [{"colors": ["red", "white"]}, {"colors": ["blue", "white"]}],
            "picker_config": {
                "mode": "split", "colorsPerHead": "duo",
                "uniform": ["red", "white"], "splitSecondary": ["white"],
                "custom": [["red", "white"], ["blue", "white"]],
                "count": 2, "lens": "clear",
            },
        },
    }, paths)

    assert result["ok"] is True
    saved = load_draft(draft.draft_id, paths.workspace_drafts_dir).parts[0]
    assert saved.location == "TAIL LIGHTS"
    assert saved.picker_config["mode"] == "split"
    assert saved.picker_config["colorsPerHead"] == "duo"
    assert saved.raw_color == "Red/White / Blue/White"
    assert saved.driver_color == "Red/White"
    assert saved.passenger_color == "Blue/White"


def test_custom_tracer_uses_multi_head_fixture_geometry(tmp_path, app_paths):
    paths = _isolated_paths(tmp_path, app_paths)
    draft = _draft(paths)

    result = handle_add_custom_part_to_draft(draft.draft_id, {
        "sku": "CUSTOM-TRACER", "description": "Custom five-head running-board light",
        "unit_price": 450, "quantity": 1, "location": "FIXTURE:TRACER_5LAMP",
        "custom_light": {
            "enabled": True, "render_style": "tracer_5lamp",
            "size_rule_id": "sm", "lens": "clear",
            "heads": [{"colors": ["red", "white"]}],
            "picker_config": {
                "mode": "uniform", "colorsPerHead": "duo",
                "uniform": ["red", "white"], "splitSecondary": ["white"],
                "custom": [["red", "white"]], "count": 1, "lens": "clear",
            },
        },
    }, paths)

    assert result["ok"] is True
    saved_draft = load_draft(draft.draft_id, paths.workspace_drafts_dir)
    saved = saved_draft.parts[0]
    assert saved.picker_config["custom_light"]["render_style"] == "tracer_5lamp"
    plan = build_plan(draft_to_project_input(saved_draft), load_configs(paths))
    planned = next(part for part in plan.planned_parts if part.raw.line_id == saved.line_id)
    assert planned.part_id == "tracer_5lamp"
    assert planned.render_kind == "light"
    assert len(planned.placements) == 1
    assert len(planned.placements[0].instances) == 5
    assert planned.placements[0].pattern == "horizontal"
    assert {instance.color_token for instance in planned.placements[0].instances} == {"red-white"}

    # Tahoe layouts historically carried an empty Tracer pattern, collapsing
    # all heads onto one point. Fixture normalization must keep the same
    # contiguous row geometry used by the PIU.
    saved_draft.vehicle_info["VehicleType"] = "TAHOE"
    tahoe_plan = build_plan(draft_to_project_input(saved_draft), load_configs(paths))
    tahoe_tracer = next(part for part in tahoe_plan.planned_parts if part.raw.line_id == saved.line_id)
    tahoe_placement = tahoe_tracer.placements[0]
    assert tahoe_placement.pattern == "horizontal"
    assert tahoe_placement.h_spacing == 1
    assert tahoe_placement.h_spacing_units == "icon_width"
    assert len(tahoe_placement.instances) == 5


def test_custom_bar_styles_reuse_normal_bar_assets(tmp_path, app_paths):
    paths = _isolated_paths(tmp_path, app_paths)
    draft = _draft(paths)
    common_light = {
        "enabled": True, "size_rule_id": "sm", "lens": "smoked",
        "heads": [{"colors": ["red", "blue"]}],
        "picker_config": {
            "mode": "uniform", "colorsPerHead": "duo",
            "uniform": ["red", "blue"], "splitSecondary": [],
            "custom": [["red", "blue"]], "count": 1, "lens": "smoked",
        },
    }
    front = handle_add_custom_part_to_draft(draft.draft_id, {
        "sku": "CUSTOM-ILB", "description": "Custom front interior bar",
        "unit_price": 900, "quantity": 1, "location": "INTERIOR LIGHT BAR (FRONT)",
        "custom_light": {**common_light, "render_style": "interior_light_bar_front"},
    }, paths)
    roof = handle_add_custom_part_to_draft(draft.draft_id, {
        "sku": "CUSTOM-ROOF", "description": "Custom roof bar",
        "unit_price": 1200, "quantity": 1, "location": "ROOF LIGHT BAR",
        "custom_light": {**common_light, "render_style": "roof_light_bar"},
    }, paths)

    assert front["ok"] is True
    assert roof["ok"] is True
    saved_draft = load_draft(draft.draft_id, paths.workspace_drafts_dir)
    plan = build_plan(draft_to_project_input(saved_draft), load_configs(paths))
    planned = {part.raw.part_number: part for part in plan.planned_parts}
    assert planned["CUSTOM-ILB"].render_kind == "bar"
    assert {placement.asset_key for placement in planned["CUSTOM-ILB"].placements} == {"interior-front"}
    assert {placement.view for placement in planned["CUSTOM-ILB"].placements} == {"front"}
    assert planned["CUSTOM-ROOF"].render_kind == "bar"
    assert {placement.asset_key for placement in planned["CUSTOM-ROOF"].placements} == {"roof"}
