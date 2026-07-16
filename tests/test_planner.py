"""Baseline tests: planner.build_plan produces a valid BuildPlan."""
from __future__ import annotations

import pytest

from dtm_buildsheet.models import (
    BuildPlan,
    PartInput,
    PlannedPart,
    ProjectInput,
)
from dtm_buildsheet.planner import build_plan


# ── basic build_plan contract ──────────────────────────────────────────────────

def test_build_plan_returns_build_plan(stearns_input, config):
    plan = build_plan(stearns_input, config)
    assert isinstance(plan, BuildPlan)


def test_build_plan_has_version(stearns_input, config):
    plan = build_plan(stearns_input, config)
    assert plan.version


def test_build_plan_planned_parts_is_list(stearns_input, config):
    plan = build_plan(stearns_input, config)
    assert isinstance(plan.planned_parts, list)


def test_build_plan_has_planned_parts(stearns_input, config):
    plan = build_plan(stearns_input, config)
    assert len(plan.planned_parts) > 0


def test_build_plan_project_info_preserved(stearns_input, config):
    plan = build_plan(stearns_input, config)
    assert plan.project.get("VehicleType") == stearns_input.info.get("VehicleType")
    assert plan.project.get("ProjectID") == stearns_input.info.get("ProjectID")


def test_build_plan_warnings_is_list(stearns_input, config):
    plan = build_plan(stearns_input, config)
    assert isinstance(plan.warnings, list)


def test_build_plan_notes_is_dict(stearns_input, config):
    plan = build_plan(stearns_input, config)
    assert isinstance(plan.notes, dict)


# ── unmapped parts produce warnings, not exceptions ───────────────────────────

def test_unmapped_part_gets_warning_not_exception(config):
    fake_part = PartInput(name="Definitely Not A Real Part XYZ999", include=True)
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "TEST"},
        parts=[fake_part],
        notes=[],
    )
    plan = build_plan(project, config)
    unmapped = [p for p in plan.planned_parts if p.part_id == "unmapped"]
    assert len(unmapped) == 1
    assert unmapped[0].warnings


def test_excluded_parts_not_in_plan(config):
    excluded = PartInput(name="Light Bar", include=False)
    included = PartInput(name="Light Bar", include=True, location="roof")
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "TEST"},
        parts=[excluded, included],
        notes=[],
    )
    plan = build_plan(project, config)
    # Only the included one should appear
    assert len([p for p in plan.planned_parts if p.part_name == "Light Bar"]) <= 1


def test_empty_parts_list_does_not_crash(config):
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "EMPTY"},
        parts=[],
        notes=[],
    )
    plan = build_plan(project, config)
    assert isinstance(plan, BuildPlan)
    assert plan.planned_parts == []


# ── unknown vehicle type falls back gracefully ────────────────────────────────

def test_unknown_vehicle_type_does_not_crash(config):
    project = ProjectInput(
        info={"VehicleType": "MARS_ROVER", "ProjectID": "ALIEN"},
        parts=[],
        notes=[],
    )
    plan = build_plan(project, config)
    assert isinstance(plan, BuildPlan)


# ── PlannedPart structure ──────────────────────────────────────────────────────

def test_planned_parts_are_planned_part_instances(stearns_input, config):
    plan = build_plan(stearns_input, config)
    for part in plan.planned_parts:
        assert isinstance(part, PlannedPart)


def test_planned_parts_have_part_ids(stearns_input, config):
    plan = build_plan(stearns_input, config)
    for part in plan.planned_parts:
        assert part.part_id, f"PlannedPart missing part_id: {part.part_name}"


# ── to_dict serialization ──────────────────────────────────────────────────────

def test_to_dict_returns_dict(stearns_input, config):
    plan = build_plan(stearns_input, config)
    d = plan.to_dict()
    assert isinstance(d, dict)


def test_to_dict_has_required_keys(stearns_input, config):
    plan = build_plan(stearns_input, config)
    d = plan.to_dict()
    for key in ("version", "project", "planned_parts", "warnings", "notes"):
        assert key in d, f"to_dict() missing key '{key}'"


def test_to_dict_planned_parts_are_dicts(stearns_input, config):
    plan = build_plan(stearns_input, config)
    d = plan.to_dict()
    for item in d["planned_parts"]:
        assert isinstance(item, dict)


def test_to_dict_omits_empty_components_but_keeps_selected_components(config):
    plain = PartInput(name="Light Bar", part_number="EB2DEDE", location="ROOF LIGHT BAR")
    with_components = PartInput(
        name="Push Bumper",
        manufacturer="Setina",
        part_number="PB450L",
        location="Push Bumper",
        components=[{"part_number": "BK1001ITU20", "quantity": 1}],
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "COMPONENTS"},
        parts=[plain, with_components],
        notes={},
    )

    rows = {p["raw"]["part_number"]: p["raw"] for p in build_plan(project, config).to_dict()["planned_parts"]}
    assert "components" not in rows["EB2DEDE"]
    assert rows["PB450L"]["components"] == [{"part_number": "BK1001ITU20", "quantity": 1}]


# ── second sample workbook also plans ─────────────────────────────────────────

def test_test_build_plans_successfully(test_build_input, config):
    plan = build_plan(test_build_input, config)
    assert isinstance(plan, BuildPlan)
    assert len(plan.planned_parts) > 0


# ── tracer housing SKUs render as their lamp-row shape (picker-created) ────────

def _tracer_plan(config, sku, qty=2):
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    proj = ProjectInput(
        info={"VehicleType": "PIU"},
        parts=[PartInput(name="Side Warning 1", part_number=sku, location="ON RUNNING BOARD",
                         quantity=qty, line_id="t1", raw_color="Red/Blue/White", lens="clear")],
        notes={})
    return build_plan(proj, config)


def test_tracer_sku_remaps_to_lamp_row_render(config):
    # TCRWX5 (picker-created, synthesized side_warning spec) must remap to the
    # tracer_5lamp render: 5 lamp shapes in a row, on the diagram.
    plan = _tracer_plan(config, "TCRWX5")
    pp = next(p for p in plan.planned_parts if p.raw.part_number == "TCRWX5")
    assert pp.part_id == "tracer_5lamp"
    assert pp.on_diagram is True
    slots = sum(len(getattr(pl, "instances", []) or []) for pl in (pp.placements or []))
    assert slots == 5


def test_tracer_6lamp_sku_remaps(config):
    plan = _tracer_plan(config, "TCRWX6")
    pp = next(p for p in plan.planned_parts if p.raw.part_number == "TCRWX6")
    assert pp.part_id == "tracer_6lamp"
    slots = sum(len(getattr(pl, "instances", []) or []) for pl in (pp.placements or []))
    assert slots == 6


def test_roof_bar_resolves_bar_asset(config):
    # Picker-created roof bar (synthesized spec) must resolve a bar_assets image
    # (asset_key "roof"), not render blank.
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    proj = ProjectInput(
        info={"VehicleType": "PIU"},
        parts=[PartInput(name="Light Bar 1", part_number="EB2DEDE", location="ROOF LIGHT BAR",
                         quantity=1, line_id="b1", lens="smoked")],
        notes={})
    pp = next(p for p in build_plan(proj, config).planned_parts if p.raw.part_number == "EB2DEDE")
    assert pp.render_kind == "bar" and pp.on_diagram is True
    assets = [i.asset_path for pl in (pp.placements or []) for i in (getattr(pl, "instances", []) or [])]
    assert assets and all(a for a in assets), "bar should resolve an asset in every placement"


def _setina_lighted_bumper_plan(config, sku):
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    proj = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "PB450L"},
        parts=[PartInput(name="Push Bumper", manufacturer="Setina", part_number=sku,
                         location="Push Bumper", quantity=1, line_id="pb1")],
        notes={})
    return build_plan(proj, config)


def test_picker_push_bumper_uses_parts_db_fixture_size_metadata(config):
    plan = _setina_lighted_bumper_plan(config, "BK1001ITU20")
    bumper = next(p for p in plan.planned_parts if p.part_name == "Push Bumper")
    placements = {p.view: p for p in bumper.placements}

    assert bumper.part_id == "push_bumper"
    assert bumper.render_kind == "equipment"
    assert bumper.on_diagram is True
    assert placements["front"].size_override == {"w": 2.75, "h": 2.52}
    assert placements["side"].size_override == {"w": 0.43, "h": 1.56}
    assert placements["top"].size_override == {"w": 0.342, "h": 1.434}
    assert placements["front"].instances[0].asset_path == "equipment/push_bumper_front.png"


def test_setina_pb450l2_injects_render_only_top_tube_lights(config):
    plan = _setina_lighted_bumper_plan(config, "BK2017ITU20")
    assert [p.part_name for p in plan.planned_parts].count("Push Bumper") == 1
    included = [p for p in plan.planned_parts if p.raw.notes.startswith("Included with Setina")]
    assert len(included) == 1
    placement = included[0].placements[0]
    assert placement.location_key == "TOP TUBE"
    assert placement.slot_indices == [0, 3]
    assert len(placement.instances) == 2
    assert {i.color_token for i in placement.instances} == {"red-blue-white"}
    assert placement.line_id == "pb1:included-top-tube"


def test_setina_pb450l4_injects_four_top_tube_lights(config):
    plan = _setina_lighted_bumper_plan(config, "BK2019ITU20")
    included = [p for p in plan.planned_parts if p.raw.notes.startswith("Included with Setina")]
    assert len(included) == 1
    placement = included[0].placements[0]
    assert placement.location_key == "TOP TUBE"
    assert placement.slot_indices is None
    assert len(placement.instances) == 4


def test_setina_pb450l6_adds_side_push_bumper_lights(config):
    plan = _setina_lighted_bumper_plan(config, "BK1001ITU20")
    included = [p for p in plan.planned_parts if p.raw.notes.startswith("Included with Setina")]
    assert len(included) == 2
    placements = {p.placements[0].location_key: p.placements[0] for p in included}
    assert len(placements["TOP TUBE"].instances) == 4
    assert len(placements["SIDE OF PUSH BUMPER"].instances) == 2


def _siren_plan(config, qty):
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    proj = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "SIREN"},
        parts=[PartInput(name="Siren Speaker", part_number="SA315P", location="TOP OF PUSH BUMPER",
                         quantity=qty, line_id="s1")],
        notes={})
    return build_plan(proj, config)


def test_siren_speaker_qty_one_uses_parts_db_render_metadata(config):
    plan = _siren_plan(config, 1)
    pp = next(p for p in plan.planned_parts if p.raw.part_number == "SA315P")
    assert pp.part_id == "siren_speaker"
    assert pp.render_kind == "equipment"
    assert pp.on_diagram is True
    placement = pp.placements[0]
    assert placement.pattern == "single"
    assert placement.anchor["x"] == 0.5
    assert placement.size_override == {"w": 0.569, "h": 0.65}
    assert len(placement.instances) == 1
    assert placement.instances[0].asset_path == "equipment/siren_speaker_wo_bracket_front.png"


def test_siren_speaker_qty_two_renders_two_slots(config):
    plan = _siren_plan(config, 2)
    pp = next(p for p in plan.planned_parts if p.raw.part_number == "SA315P")
    placement = pp.placements[0]
    assert placement.pattern == "mirror"
    assert len(placement.instances) == 2


def test_numbered_siren_speaker_uses_parts_db_render_metadata(config):
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    proj = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "SIREN-NUMBERED"},
        parts=[PartInput(name="Siren Speaker 1", part_number="SA315P",
                         location="TOP OF PUSH BUMPER", quantity=1, line_id="s1")],
        notes={})
    pp = next(p for p in build_plan(proj, config).planned_parts if p.raw.part_number == "SA315P")
    placement = pp.placements[0]
    assert pp.part_id == "siren_speaker"
    assert placement.size_override == {"w": 0.569, "h": 0.65}
    assert placement.instances[0].asset_path == "equipment/siren_speaker_wo_bracket_front.png"


def test_picker_opticom_uses_preemption_parts_db_render_metadata(config):
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    proj = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "OPTICOM"},
        parts=[PartInput(name="Opticom", part_number="PREEMPTION LIGHT HEAD",
                         location="IN LIGHT BAR", quantity=1, line_id="o1")],
        notes={})
    pp = next(p for p in build_plan(proj, config).planned_parts if p.raw.part_number == "PREEMPTION LIGHT HEAD")
    assert pp.part_id == "preemption"
    assert pp.render_kind == "equipment"
    assert pp.on_diagram is True
    placement = pp.placements[0]
    assert placement.location_key == "IN LIGHT BAR"
    assert placement.size_override == {"w": 0.41, "h": 0.14}
    assert placement.instances[0].asset_path == "equipment/opticom_front.png"


def test_separate_numbered_siren_speakers_keep_distinct_slots(config):
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    proj = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "SIREN-NUMBERED-PAIR"},
        parts=[
            PartInput(name="Siren Speaker 1", part_number="SA315P",
                      location="TOP OF PUSH BUMPER", quantity=1, line_id="s1"),
            PartInput(name="Siren Speaker 2", part_number="SA315P",
                      location="TOP OF PUSH BUMPER", quantity=1, line_id="s2"),
        ],
        notes={})
    speakers = [p for p in build_plan(proj, config).planned_parts if p.raw.part_number == "SA315P"]
    assert [p.placements[0].slot_indices for p in speakers] == [[0], [1]]
    assert all(p.placements[0].pattern == "mirror" for p in speakers)
    assert all(p.placements[0].size_override == {"w": 0.569, "h": 0.65} for p in speakers)
