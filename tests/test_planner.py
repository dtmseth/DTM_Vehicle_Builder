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


def test_custom_part_is_manifest_only_without_an_unmapped_warning(config):
    part = PartInput(
        name="Vendor supplied cable kit", part_number="VND-042", quantity=2,
        picker_config={"custom_part": {
            "sku": "VND-042", "description": "Vendor supplied cable kit", "unit_price": 42.5,
        }},
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "CUSTOM-PART"}, parts=[part], notes={},
    )

    plan = build_plan(project, config)

    assert plan.warnings == []
    assert plan.planned_parts[0].part_id == "custom_part"
    assert plan.planned_parts[0].placements == []
    assert plan.planned_parts[0].on_diagram is False


def test_picker_part_type_resolves_a_descriptive_manifest_child(config):
    """Nested picker lines need not reuse legacy workbook display names."""
    faceplate = PartInput(
        name="Center Console · Face Plate 1 · Example",
        include=True,
        line_id="faceplate-1",
        part_type="special_face_plate",
        location="IN CENTER CONSOLE",
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "TEST"},
        parts=[faceplate],
        notes=[],
    )
    plan = build_plan(project, config)
    assert len(plan.planned_parts) == 1
    assert plan.planned_parts[0].part_id == "special_face_plate"
    assert not plan.warnings


def test_radio_antenna_renders_at_rear_left_roof(config):
    part = PartInput(
        name="Radio Antenna Top",
        include=True,
        line_id="whip-antenna",
        part_type="radio_antenna_top",
        part_number="WHIP STYLE",
        location="Rear left roof",
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "WHIP-REAR"},
        parts=[part],
        notes={},
    )

    planned = build_plan(project, config).planned_parts[0]

    assert [placement.view for placement in planned.placements] == ["side", "top", "rear"]
    rear = planned.placements[-1]
    assert rear.location_key == "REAR LEFT ROOF"
    assert rear.instances[0].asset_path == "lights/part_whip_style_side.png"
    assert rear.size_override == {"w": 0.12, "h": 0.4}


@pytest.mark.parametrize(
    ("part_type", "part_name", "expected_layer"),
    [
        ("push_bumper", "Push Bumper", -20),
        ("pit_bar", "Pit Bar", -15),
        ("wing_wraps", "Wing Wraps", -15),
    ],
)
def test_bumper_assembly_renders_below_lights(config, part_type, part_name, expected_layer):
    part = PartInput(
        name=part_name,
        include=True,
        line_id=f"{part_type}-layer",
        part_type=part_type,
        location="PUSH BUMPER",
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "BUMPER-LAYER"},
        parts=[part],
        notes={},
    )

    planned = build_plan(project, config).planned_parts[0]

    assert planned.placements
    assert {placement.layer for placement in planned.placements} == {expected_layer}


@pytest.mark.parametrize(("quantity", "sku"), [(1, "PSL1BB"), (2, "PSL2BB")])
def test_picker_pioneer_slimline_renders_selected_scene_head_count(config, quantity, sku):
    """No-color scene selections still render white modules at their saved qty."""
    part = PartInput(
        name="Front Scene 1",
        line_id=f"pioneer-{quantity}",
        part_type="front_scene",
        manufacturer="Whelen",
        # The picker stores the product model on the parent and the concrete
        # SKU in components, matching the live draft contract.
        part_number="Pioneer SlimLine",
        quantity=quantity,
        location="CENTER PLATE OF PB",
        components=[{"part_number": sku, "quantity": quantity}],
        picker_config={"count": quantity, "_noColor": True},
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": f"PIONEER-{quantity}"},
        parts=[part],
        notes={},
    )

    planned = build_plan(project, config).planned_parts[0]
    placement = planned.placements[0]

    assert planned.render_kind == "light"
    assert placement.size_class == "PN"
    assert placement.quantity_policy == "quantity_as_slots"
    assert len(placement.instances) == quantity
    assert all(instance.asset_path == "lights/sm_white_h.png" for instance in placement.instances)
    if quantity == 1:
        assert placement.anchor["x"] == pytest.approx(0.5)
        assert placement.pattern == "single"
    else:
        assert placement.pattern == "horizontal"


def test_pioneer_on_top_of_push_bumper_renders_one_centered_head(config):
    """A single Pioneer must not inherit the bumper location's mirror pair."""
    part = PartInput(
        name="Front Scene 1",
        line_id="pioneer-top-of-bumper",
        part_type="front_scene",
        manufacturer="Whelen",
        part_number="Pioneer SlimLine",
        quantity=1,
        location="TOP OF PUSH BUMPER",
        components=[{"part_number": "PSL1BB", "quantity": 1}],
        picker_config={"count": 1, "_noColor": True},
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "PIONEER-TOP-OF-BUMPER"},
        parts=[part],
        notes={},
    )

    placement = build_plan(project, config).planned_parts[0].placements[0]

    assert placement.pattern == "single"
    assert placement.anchor["x"] == pytest.approx(0.5)
    assert len(placement.instances) == 1


def test_inner_edge_fst_renders_ion_size_head_groups_not_bar_bitmap(config):
    part = PartInput(
        name="Interior Light Bar", line_id="fst-1", part_type="front_interior_light_bar",
        part_number="BSFW50Z", quantity=1, location="Front Interior Light Bar",
        raw_color="Red/White Blue/White",
        picker_config={"inner_edge": {
            "product_id": "whelen_fst", "lamp_count": 10,
            "mode": "duo", "secondary": "white", "coverage": "both",
        }},
    )
    project = ProjectInput(info={"VehicleType": "PIU", "ProjectID": "FST"}, parts=[part], notes={})
    planned = build_plan(project, config).planned_parts[0]
    placement = planned.placements[0]

    assert planned.render_kind == "light"
    assert placement.render_kind == "light"
    assert placement.pattern == "inner_edge_front"
    assert placement.size_class == "sm"  # same class used by ION lightheads
    assert placement.size_override == {"w": 0.31, "h": 0.114}
    assert placement.h_spacing == 1.05
    assert placement.h_spacing_units == "icon_width"
    assert len(placement.instances) == 10
    assert [instance.color_token for instance in placement.instances] == (
        ["blue-white"] * 5 + ["red-white"] * 5
    )
    assert all("interior-front" not in instance.asset_path for instance in placement.instances)
    assert [placement.view for placement in planned.placements] == ["front"]


def test_inner_edge_rst_renders_one_full_width_rear_row(config):
    part = PartInput(
        name="Interior Light Bar", line_id="rst-1", part_type="rear_interior_light_bar",
        part_number="BSRW12", quantity=1, location="Rear Interior Light Bar",
        raw_color="Red/Blue/Amber", explicit_color_profile="std_tri_rba",
        picker_config={"inner_edge": {
            "product_id": "whelen_rst", "lamp_count": 12,
            "mode": "trio", "secondary": "amber", "coverage": "both",
        }},
    )
    project = ProjectInput(info={"VehicleType": "PIU", "ProjectID": "RST"}, parts=[part], notes={})
    planned = build_plan(project, config).planned_parts[0]
    placement = planned.placements[0]

    assert placement.pattern == "inner_edge_rear"
    assert placement.location_key == "FIXTURE:REAR_INTERIOR_LIGHT_BAR"
    assert placement.size_override == {"w": 0.31, "h": 0.114}
    assert placement.h_spacing == 1.05
    assert len(placement.instances) == 12
    assert {instance.color_token for instance in placement.instances} == {"red-blue-amber"}
    assert [placement.view for placement in planned.placements] == ["rear"]


def test_outer_edge_renders_six_angled_rear_pillar_ions(config):
    part = PartInput(
        name="Rear Warning 1", line_id="outer-edge-1", part_type="warning_light",
        part_number="RPWD50", quantity=1, location="PILLARS",
        raw_color="Red/White Blue/White",
        picker_config={"outer_edge_pillar": {
            "product_id": "whelen_ion_rear_pillar", "housing_part_number": "RPWD50",
            "mode": "duo", "secondary": "white", "head_count": 6,
        }},
    )
    project = ProjectInput(info={"VehicleType": "PIU", "ProjectID": "OUTER"}, parts=[part], notes={})
    planned = build_plan(project, config).planned_parts[0]
    placement = planned.placements[0]

    assert planned.part_id == "outer_edge_pillar"
    assert planned.render_kind == "light"
    assert placement.view == "rear"
    assert placement.location_key == "PILLARS"
    assert placement.pattern == "outer_edge_pillars"
    assert placement.h_spacing == pytest.approx(0.59)
    assert placement.v_spacing == pytest.approx(0.045)
    assert placement.rotation == pytest.approx(-55)
    assert len(placement.instances) == 6
    assert [instance.slot_role for instance in placement.instances] == [
        "driver", "driver", "driver", "passenger", "passenger", "passenger",
    ]
    assert [instance.color_token for instance in placement.instances] == [
        "red-white", "red-white", "red-white", "blue-white", "blue-white", "blue-white",
    ]


def test_outer_edge_trio_renders_the_same_color_on_all_six_heads(config):
    part = PartInput(
        name="Rear Warning 1", line_id="outer-edge-trio", part_type="warning_light",
        part_number="RPWT50", quantity=1, location="PILLARS",
        raw_color="Red/Blue/Amber", explicit_color_profile="std_tri_rba",
        picker_config={"outer_edge_pillar": {
            "product_id": "whelen_ion_rear_pillar", "housing_part_number": "RPWT50",
            "mode": "trio", "secondary": "amber", "head_count": 6,
        }},
    )
    project = ProjectInput(info={"VehicleType": "PIU", "ProjectID": "OUTER-TRIO"}, parts=[part], notes={})
    placement = build_plan(project, config).planned_parts[0].placements[0]

    assert placement.pattern == "outer_edge_pillars"
    assert {instance.color_token for instance in placement.instances} == {"red-blue-amber"}


@pytest.mark.parametrize(("name", "expected_view"), [
    ("Front Interior Light Bar", "front"),
    ("Rear Interior Light Bar", "rear"),
])
def test_legacy_interior_light_bars_do_not_render_in_top_view(name, expected_view, config):
    """The same rule applies to legacy workbook lines without picker metadata."""
    part = PartInput(name=name, quantity=1)
    project = ProjectInput(info={"VehicleType": "PIU", "ProjectID": "INTERIOR"}, parts=[part], notes={})

    planned = build_plan(project, config).planned_parts[0]

    assert [placement.view for placement in planned.placements] == [expected_view]


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


def test_tracer_3lamp_sku_uses_its_fixture_without_a_manual_location(config):
    plan = _tracer_plan(config, "TCRWX3")
    pp = next(p for p in plan.planned_parts if p.raw.part_number == "TCRWX3")
    assert pp.part_id == "tracer_3lamp"
    assert pp.on_diagram is True
    assert sum(len(pl.instances) for pl in pp.placements) == 3


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


@pytest.mark.parametrize(
    ("part_type", "name", "part_number", "expected_assets"),
    [
        (
            "pit_bar", "Pit Bar", "PIT BARS",
            {"front": "lights/westin_unknown_front.png", "side": "lights/westin_pit_bar_elitexd_side.png"},
        ),
        (
            "wing_wraps", "Wing Wraps", "WING WRAPS",
            {"front": "equipment/wing_wraps_front.png", "side": "equipment/westin_wing_wrap_elitexd_side.png"},
        ),
    ],
)
def test_picker_bumper_add_ons_use_parts_db_fixture_render_metadata(
    config, part_type, name, part_number, expected_assets,
):
    """Picker-built bumper add-ons must not fall back to a text location."""
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput

    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "FIXTURE-ADD-ONS"},
        parts=[PartInput(
            name=name, part_number=part_number, quantity=1, line_id="picker-line",
            part_type=part_type,
        )],
        notes={},
    )

    planned = build_plan(project, config).planned_parts[0]
    placements = {placement.view: placement for placement in planned.placements}

    assert planned.on_diagram is True
    assert set(placements) == set(expected_assets)
    assert all(placement.is_fixture for placement in placements.values())
    assert {
        view: placement.instances[0].asset_path
        for view, placement in placements.items()
    } == expected_assets
    if part_type == "wing_wraps":
        assert len(placements["front"].instances) == 2
        assert len(placements["side"].instances) == 1
        assert placements["front"].pattern == "mirror"
        assert placements["front"].anchor["x"] == 0.5


def test_wing_wrap_artwork_suppresses_only_the_overlapping_pit_bar_render(config):
    """Wing-wrap artwork includes the Pit Bar, which still stays on the manifest."""
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "WRAP-COMBO"},
        parts=[
            PartInput(name="Pit Bar", part_number="PIT BARS", quantity=1, line_id="pit", part_type="pit_bar"),
            PartInput(name="Wing Wraps", part_number="WING WRAPS", quantity=1, line_id="wrap", part_type="wing_wraps"),
        ],
        notes={},
    )

    planned = build_plan(project, config).planned_parts

    pit_bar = next(part for part in planned if part.part_name == "Pit Bar")
    wing_wraps = next(part for part in planned if part.part_name == "Wing Wraps")
    assert pit_bar.placements == []
    assert pit_bar.on_diagram is False
    assert {placement.view for placement in wing_wraps.placements} == {"front", "side"}


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


def test_custom_picker_location_uses_its_saved_vehicle_dot(config):
    """The shop-facing custom name must not leave a rendered part unplaced."""
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    part = PartInput(
        name="Siren Speaker 1", part_type="siren_speaker", part_number="SA315P",
        location="Behind grille — lower opening", quantity=1, line_id="custom-speaker",
        picker_config={"custom_location": {
            "label": "Behind grille — lower opening",
            "render_location": "TOP OF PUSH BUMPER",
        }},
    )
    project = ProjectInput(info={"VehicleType": "PIU", "ProjectID": "CUSTOM-LOCATION"}, parts=[part], notes={})

    planned = build_plan(project, config).planned_parts[0]
    assert planned.raw.location == "Behind grille — lower opening"
    assert planned.placements[0].location_key == "TOP OF PUSH BUMPER"


def test_custom_picker_location_can_be_manifest_only_without_a_render_spot(config):
    """A named custom location need not fabricate a vehicle placement."""
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    part = PartInput(
        name="Siren Speaker 1", part_type="siren_speaker", part_number="SA315P",
        location="Behind grille — lower opening", quantity=1, line_id="custom-no-render",
        picker_config={"custom_location": {
            "label": "Behind grille — lower opening",
        }},
    )
    project = ProjectInput(info={"VehicleType": "PIU", "ProjectID": "CUSTOM-NO-RENDER"}, parts=[part], notes={})

    planned = build_plan(project, config).planned_parts[0]

    assert planned.raw.location == "Behind grille — lower opening"
    assert planned.placements == []
    assert planned.on_diagram is False
    assert planned.warnings == []


def test_custom_picker_location_renders_each_free_point_across_views(config):
    """Free picker points are persisted as exact per-view render coordinates."""
    from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
    part = PartInput(
        name="Siren Speaker 1", part_type="siren_speaker", part_number="SA315P",
        location="Custom speaker mount", quantity=1, line_id="free-custom-speaker",
        picker_config={"custom_location": {
            "label": "Custom speaker mount",
            "placements": {
                "front": [{"x": 0.21, "y": 0.63}, {"x": 0.79, "y": 0.63}],
                "side": [{"x": 0.44, "y": 0.54}],
            },
        }},
    )
    project = ProjectInput(info={"VehicleType": "PIU", "ProjectID": "FREE-CUSTOM-LOCATION"}, parts=[part], notes={})

    planned = build_plan(project, config).planned_parts[0]
    placements = planned.placements
    assert [(p.view, p.location_key) for p in placements] == [
        ("front", "CUSTOM:FRONT:1"),
        ("front", "CUSTOM:FRONT:2"),
        ("side", "CUSTOM:SIDE:1"),
    ]
    assert [p.anchor for p in placements] == [
        {"x": 0.21, "y": 0.63, "units": "relative_image"},
        {"x": 0.79, "y": 0.63, "units": "relative_image"},
        {"x": 0.44, "y": 0.54, "units": "relative_image"},
    ]


def test_direct_ion_sku_at_custom_point_resolves_its_colored_asset(config):
    part = PartInput(
        name="Side Warning 1", part_type="warning_light", part_number="IONJ",
        raw_color="Red/Blue", location="Custom ION mount", quantity=1, line_id="custom-ion",
        picker_config={"custom_location": {
            "label": "Custom ION mount",
            "placements": {"side": [{"x": 0.42, "y": 0.31}]},
        }},
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "CUSTOM-ION"}, parts=[part], notes={},
    )

    instance = build_plan(project, config).planned_parts[0].placements[0].instances[0]
    assert instance.asset_path == "lights/sm_red-blue_h.png"


def test_split_ion_at_neutral_custom_point_uses_a_concrete_side_asset(config):
    """Edina regression: a center-role free point must not become a red dot."""
    part = PartInput(
        name="Forward Warning 1", part_type="warning_light", part_number="ION",
        raw_color="Red/White / Blue/White", driver_color="Red/White",
        passenger_color="Blue/White", location="Front Center Grill", quantity=4,
        line_id="edina-front-ion",
        components=[
            {"part_number": "XI2D", "color": "Red/White", "quantity": 2},
            {"part_number": "XI2E", "color": "Blue/White", "quantity": 2},
        ],
        picker_config={"custom_location": {
            "label": "Front Center Grill",
            "placements": {"front": [{"x": 0.4938, "y": 0.6122}]},
        }},
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "EDINA-FRONT-ION"},
        parts=[part], notes={},
    )

    instance = build_plan(project, config).planned_parts[0].placements[0].instances[0]
    assert instance.slot_role == "center"
    assert instance.color_token == "red-white"
    assert instance.asset_path == "lights/sm_red-white_h.png"


def test_guided_radio_antenna_uses_its_individual_condition(config):
    parent = PartInput(
        name="Radio Control Head", part_type="radio_head", new_or_used="New", line_id="radio-system",
        components=[{
            "label": "Radio antenna", "part_type": "radio_antenna_top",
            "location": "Rear left roof", "detail": "Whip style", "quantity": 1,
            "new_or_used": "Reused",
        }],
    )
    project = ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "RADIO-COMPONENT-CONDITION"},
        parts=[parent], notes={},
    )

    antenna = next(
        planned for planned in build_plan(project, config).planned_parts
        if planned.raw.part_type == "radio_antenna_top"
    )
    assert antenna.raw.new_or_used == "Reused"


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
