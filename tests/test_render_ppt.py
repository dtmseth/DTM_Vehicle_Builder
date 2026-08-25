"""Baseline tests: render_ppt produces a valid, openable .pptx file."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from dtm_buildsheet.models import PartInput, ProjectInput
from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.planner import build_plan
from dtm_buildsheet.render_ppt import (
    _build_accessory_map,
    _placement_key,
    _render_failures_for_view,
    _stack_parts_above_vehicle,
    _vertical_mirror_slot_is_reflected,
    render_plan_to_ppt,
)
from dtm_buildsheet.ppt_helpers import (
    FOOTER_H,
    SLIDE_H_EMU,
    SLIDE_W_EMU,
    _manifest_groups,
    _badge_label,
    _legend_callouts,
    add_render_exception_slides,
    place_legend,
)


@pytest.fixture(scope="module")
def rendered_pptx(tmp_path_factory, stearns_input, config):
    out_dir = tmp_path_factory.mktemp("output")
    paths = AppPaths(
        project_root=config.paths.project_root,
        package_dir=config.paths.package_dir,
        resources_dir=config.paths.resources_dir,
        assets_dir=config.paths.assets_dir,
        templates_dir=config.paths.templates_dir,
        workspace_dir=config.paths.workspace_dir,
        workspace_config_dir=config.paths.workspace_config_dir,
        workspace_assets_dir=config.paths.workspace_assets_dir,
        workspace_input_dir=config.paths.workspace_input_dir,
        workspace_output_dir=out_dir,
        samples_dir=config.paths.samples_dir,
    )
    plan = build_plan(stearns_input, config)
    ppt_path = render_plan_to_ppt(plan, paths)
    return ppt_path


def test_render_produces_file(rendered_pptx):
    assert rendered_pptx.exists(), f"Expected output file at {rendered_pptx}"


def test_render_file_has_reasonable_size(rendered_pptx):
    size = rendered_pptx.stat().st_size
    assert size > 10_000, f"Output file is suspiciously small: {size} bytes"


def test_render_file_has_pptx_extension(rendered_pptx):
    assert rendered_pptx.suffix == ".pptx"


def test_render_output_is_openable_by_pptx(rendered_pptx):
    prs = Presentation(str(rendered_pptx))
    assert prs is not None


def test_render_has_slides(rendered_pptx):
    prs = Presentation(str(rendered_pptx))
    assert len(prs.slides) > 0


def test_render_has_multiple_slides(rendered_pptx):
    prs = Presentation(str(rendered_pptx))
    # Expect at least a cover + one vehicle view + manifest
    assert len(prs.slides) >= 3


@pytest.mark.parametrize(
    ("anchor_y", "expected"),
    [
        (0.17, [False, True]),
        (0.83, [True, False]),
        (0.50, [False, True]),
    ],
)
def test_vertical_mirror_reflects_only_the_non_anchor_slot(anchor_y, expected):
    placement = SimpleNamespace(
        pattern="vertical_mirror",
        anchor={"y": anchor_y},
        instances=[SimpleNamespace(), SimpleNamespace()],
    )

    assert [
        _vertical_mirror_slot_is_reflected(placement, index)
        for index in range(len(placement.instances))
    ] == expected


def test_render_second_sample(tmp_path_factory, test_build_input, config):
    out_dir = tmp_path_factory.mktemp("output2")
    paths = AppPaths(
        project_root=config.paths.project_root,
        package_dir=config.paths.package_dir,
        resources_dir=config.paths.resources_dir,
        assets_dir=config.paths.assets_dir,
        templates_dir=config.paths.templates_dir,
        workspace_dir=config.paths.workspace_dir,
        workspace_config_dir=config.paths.workspace_config_dir,
        workspace_assets_dir=config.paths.workspace_assets_dir,
        workspace_input_dir=config.paths.workspace_input_dir,
        workspace_output_dir=out_dir,
        samples_dir=config.paths.samples_dir,
    )
    plan = build_plan(test_build_input, config)
    ppt_path = render_plan_to_ppt(plan, paths)
    assert ppt_path.exists()
    prs = Presentation(str(ppt_path))
    assert len(prs.slides) > 0


def test_dual_shroud_renders_housing_around_two_t_series_heads(tmp_path, config):
    paths = AppPaths(
        project_root=config.paths.project_root,
        package_dir=config.paths.package_dir,
        resources_dir=config.paths.resources_dir,
        assets_dir=config.paths.assets_dir,
        templates_dir=config.paths.templates_dir,
        workspace_dir=config.paths.workspace_dir,
        workspace_config_dir=config.paths.workspace_config_dir,
        workspace_assets_dir=config.paths.workspace_assets_dir,
        workspace_input_dir=config.paths.workspace_input_dir,
        workspace_output_dir=tmp_path,
        samples_dir=config.paths.samples_dir,
    )
    parent = PartInput(
        name="Rear Warning 1", part_number="TST0D", part_type="warning_light",
        location="LOWER CARGO WINDOW", raw_color="Red/White", quantity=4,
        line_id="t-series-parent",
        picker_config={
            "mode": "uniform", "colorsPerHead": "duo",
            "uniform": ["red", "white"], "count": 4,
        },
    )
    shroud = PartInput(
        name="Rear Warning 1 · T-Series Shroud", part_number="THSG2", quantity=2,
        line_id="dual-shrouds", parent_line_id=parent.line_id,
        accessory_category="shroud",
        picker_config={"accessory_quantity": {
            "parent_units_per_item": 2, "render_parent_group": "dual_shroud",
        }},
    )
    plan = build_plan(ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "DUAL-SHROUD"},
        parts=[parent, shroud], notes={},
    ), config)

    prs = Presentation(str(render_plan_to_ppt(plan, paths)))
    compound_groups = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.shape_type != MSO_SHAPE_TYPE.GROUP:
                continue
            children = list(shape.shapes)
            has_housing = any(
                child.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
                and child.auto_shape_type == MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE
                for child in children
            )
            picture_count = sum(child.shape_type == MSO_SHAPE_TYPE.PICTURE for child in children)
            if has_housing and picture_count >= 2:
                compound_groups.append(shape)

    assert compound_groups, "expected a rounded shroud housing grouped with two T-Series pictures"


def test_concealed_speaker_renders_translucent_with_mount_callout(tmp_path, config):
    paths = AppPaths(
        project_root=config.paths.project_root,
        package_dir=config.paths.package_dir,
        resources_dir=config.paths.resources_dir,
        assets_dir=config.paths.assets_dir,
        templates_dir=config.paths.templates_dir,
        workspace_dir=config.paths.workspace_dir,
        workspace_config_dir=config.paths.workspace_config_dir,
        workspace_assets_dir=config.paths.workspace_assets_dir,
        workspace_input_dir=config.paths.workspace_input_dir,
        workspace_output_dir=tmp_path,
        samples_dir=config.paths.samples_dir,
    )
    speaker = PartInput(
        name="Siren Speaker", part_number="SA315P", part_type="siren_speaker",
        location="BEHIND GRILL (CENTER)", quantity=1, line_id="concealed-speaker",
    )
    plan = build_plan(ProjectInput(
        info={"VehicleType": "PIU", "ProjectID": "CONCEALED-SPEAKER"},
        parts=[speaker], notes={},
    ), config)

    prs = Presentation(str(render_plan_to_ppt(plan, paths)))
    front_slide = next(
        slide for slide in prs.slides
        if any("FRONT VIEW" in getattr(shape, "text", "") for shape in slide.shapes)
    )
    alpha_values = [
        alpha.get("amt")
        for shape in front_slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
        for alpha in shape._element.findall(".//" + qn("a:alphaModFix"))
    ]

    assert "48000" in alpha_values
    assert any(
        getattr(shape, "text", "").strip() == "BEHIND GRILLE"
        for shape in front_slide.shapes
    )


def test_render_failure_legend_only_lists_failed_current_view_components():
    """Diagram callouts are render diagnostics, not a second manifest."""
    def part(name, *, location, warnings=(), placements=(), line_id=""):
        return SimpleNamespace(
            part_name=name,
            raw=SimpleNamespace(
                line_id=line_id,
                location=location,
                notes="",
                part_number="",
            ),
            warnings=list(warnings),
            placements=list(placements),
        )

    asset_failure = SimpleNamespace(
        view="front", location_key="BUMPER", color_profile="standard", line_id="asset-line"
    )
    top_failure = SimpleNamespace(
        view="top", location_key="ROOF", color_profile="standard", line_id="top-line"
    )
    asset_part = part(
        "Front Scene", location="BUMPER", placements=[asset_failure], line_id="asset-line"
    )
    plan = SimpleNamespace(planned_parts=[
        part("Manifest-only item", location="EQUIPMENT TRAY", warnings=["No views configured"]),
        part("Missing fixture", location="WINDSHIELD", warnings=["front: no fixture coords"]),
        asset_part,
        part("Top-only failure", location="ROOF", placements=[top_failure], line_id="top-line"),
    ])

    items = _render_failures_for_view(
        plan,
        "front",
        {_placement_key(asset_part, asset_failure): ["Missing asset (front): assets/missing.png"]},
    )

    assert [(item.name, item.location) for item in items] == [
        ("Missing fixture", "WINDSHIELD"),
        ("Front Scene", "BUMPER"),
    ]
    assert items[0].notes == "front: no fixture coords"
    assert items[1].notes == "Missing asset (front): assets/missing.png"


def test_manifest_groups_use_separate_customer_facing_categories():
    def planned(name, *, category="", render_kind="equipment", part_type=""):
        return SimpleNamespace(
            category=category,
            render_kind=render_kind,
            raw=SimpleNamespace(
                name=name,
                include=True,
                notes="",
                part_number="",
                location="",
                part_type=part_type,
            ),
            placements=[],
        )

    groups = _manifest_groups([
        planned("Front Warning", category="warning", render_kind="light"),
        planned("Pit Bar", part_type="pit_bar"),
        planned("Push Bumper", part_type="push_bumper"),
        planned("Radio Head", part_type="radio_head"),
        planned("Shop-Supplied Item", category="custom", render_kind="none", part_type="custom_part"),
    ])

    assert [(label, [entry.name for entry in entries]) for label, entries in groups] == [
        ("Lighting", ["Front Warning"]),
        ("Structural Equipment", ["Push Bumper", "Pit Bar"]),
        ("Equipment & Electronics", ["Radio Head"]),
        ("Other / Custom", ["Shop-Supplied Item"]),
    ]


def test_manifest_groups_order_lighting_by_function_before_name():
    def planned(name, part_type):
        return SimpleNamespace(
            category="warning",
            render_kind="light",
            raw=SimpleNamespace(
                name=name,
                include=True,
                notes="",
                part_number="",
                location="",
                part_type=part_type,
            ),
            placements=[],
        )

    groups = _manifest_groups([
        planned("Zulu Tracer", "tracer_2_lamp"),
        planned("Alpha Interior", "front_interior_light_bar"),
        planned("Bravo Warning", "warning_light"),
        planned("Charlie Scene", "front_scene"),
        planned("Delta Bar", "roof_light_bar"),
    ])

    assert [entry.name for entry in groups[0][1]] == [
        "Bravo Warning", "Charlie Scene", "Alpha Interior", "Delta Bar", "Zulu Tracer",
    ]


def test_manifest_promotes_selected_skus_and_keeps_guided_components_and_accessories():
    def planned(name, *, line_id, parent_line_id="", components=(), part_number="", part_type="warning_light",
                location="GRILL", lens="", comment=""):
        return SimpleNamespace(
            category="warning",
            render_kind="light",
            placements=[],
            raw=SimpleNamespace(
                name=name,
                include=True,
                notes="Install with supplied hardware",
                comment=comment,
                part_number=part_number,
                location=location,
                part_type=part_type,
                line_id=line_id,
                parent_line_id=parent_line_id,
                components=list(components),
                picker_config={},
                manufacturer="Whelen",
                raw_color="",
                lens=lens,
                quantity=1,
                new_or_used="New",
                source="",
            ),
        )

    parent = planned(
        "Forward Warning", line_id="parent", part_number="ION",
        components=[
            {"part_number": "IONDUO", "quantity": 2, "color": "Red/Blue"},
            {"label": "Mounting location", "location": "Upper grill", "detail": "Centered"},
        ],
        lens="Smoked", comment="Confirm final aiming with the customer.",
    )
    accessory = planned(
        "Forward Warning · Bracket", line_id="child", parent_line_id="parent",
        part_number="BRKT-1", part_type="bracket_mount",
    )

    groups = _manifest_groups([accessory, parent])

    assert [(entry.name, entry.part_number, entry.location, entry.indent) for entry in groups[0][1]] == [
        ("Forward Warning", "IONDUO", "GRILL", 0),
        ("Mounting location", "", "Upper grill", 1),
        ("Bracket", "BRKT-1", "GRILL", 1),
    ]
    selected_sku = groups[0][1][0]
    assert "Lens: Smoked" in selected_sku.detail
    assert selected_sku.comment == "Confirm final aiming with the customer."


def test_manifest_combines_standard_duo_skus_into_one_compact_shop_row():
    raw = SimpleNamespace(
        name="Forward Warning 1", include=True, notes="", comment="Aim evenly",
        part_number="ION", location="UPPER GRILLE", part_type="warning_light",
        line_id="duo", parent_line_id="", manufacturer="Whelen",
        raw_color="Red/White / Blue/White", driver_color="Red/White",
        passenger_color="Blue/White", lens="Smoked", quantity=4,
        new_or_used="New", source="",
        picker_config={"colorsPerHead": "duo", "mode": "split"},
        components=[
            {"part_number": "3SBCCDCR", "quantity": 2, "color": "Blue/White"},
            {"part_number": "3SRCCDCR", "quantity": 2, "color": "Red/White"},
        ],
    )
    planned = SimpleNamespace(
        category="warning", render_kind="light", placements=[], raw=raw,
    )

    entries = _manifest_groups([planned])[0][1]

    assert len(entries) == 1
    assert entries[0].name == "Forward Warning 1"
    assert entries[0].part_number == "3SBCCDCR / 3SRCCDCR"
    assert entries[0].quantity == 4
    assert entries[0].location == "UPPER GRILLE"
    assert entries[0].detail == "Blue/White (passenger)  ·  Red/White (driver)  ·  Lens: Smoked"
    assert "\n" not in entries[0].detail


def test_build_legend_groups_direct_child_parts_with_their_parent():
    def planned(name, *, line_id, parent_line_id="", part_number="", accessory_of=None):
        return SimpleNamespace(
            part_name=name,
            accessory_of=accessory_of,
            raw=SimpleNamespace(
                line_id=line_id,
                parent_line_id=parent_line_id,
                part_number=part_number,
                notes="",
            ),
        )

    parent = planned("Control Head 1", line_id="control-head", part_number="CCTL7")
    child = planned(
        "Control Head 1 · Magnetic Mic", line_id="mic", parent_line_id="control-head",
        part_number="MMSU-1",
    )
    legacy_child = planned(
        "Siren Amplifier Harness", line_id="legacy", part_number="SAH-1",
        accessory_of="Siren Amplifier",
    )

    assert _build_accessory_map(SimpleNamespace(
        planned_parts=[parent, child, legacy_child]
    )) == {
        "control-head": [("Magnetic Mic", "MMSU-1")],
        "Siren Amplifier": [("Siren Amplifier Harness", "SAH-1")],
    }


def test_build_legend_card_displays_children_by_parent_line_id():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    parent = SimpleNamespace(
        name="Control Head 1", line_id="control-head", location="",
        manufacturer="Whelen", part_number="CCTL7", color="", lens="",
        new_or_used="New", source="", is_reused=False, quantity=2,
    )

    place_legend(
        slide, [parent], [],
        {"control-head": [("Magnetic Mic", "MMSU-1")]},
        view="front",
    )

    text = "\n".join(
        shape.text for shape in slide.shapes if getattr(shape, "has_text_frame", False)
    )
    assert "+ Magnetic Mic  ·  MMSU-1" in text
    assert "QTY: 2" in text


def test_manifest_hides_fixture_ids_and_locations_repeating_the_part_name():
    def planned(name, *, location, placements=()):
        return SimpleNamespace(
            category="warning",
            render_kind="light",
            placements=list(placements),
            raw=SimpleNamespace(
                name=name, include=True, notes="", comment="", part_number="IONDUO",
                location=location, part_type="warning_light", line_id=name,
                parent_line_id="", components=[], picker_config={}, manufacturer="Whelen",
                raw_color="Red/Blue", lens="Smoked", quantity=1, new_or_used="New", source="",
            ),
        )

    fixture = planned("Tracer", location="FIXTURE:TRACER_5LAMP")
    repeated = planned(
        "Front Interior Light Bar · Inner Edge Lighthead",
        location="Interior Light Bar (Front)",
    )

    entries = _manifest_groups([fixture, repeated])[0][1]

    assert [entry.location for entry in entries] == ["", ""]


def test_manifest_groups_bumper_and_siren_systems_and_hides_picker_process_details():
    def planned(name, *, part_type, notes="", components=(), part_number="", quantity=1):
        return SimpleNamespace(
            category="equipment",
            render_kind="equipment",
            placements=[],
            raw=SimpleNamespace(
                name=name, include=True, notes=notes, comment="", part_number=part_number,
                location="", part_type=part_type, line_id=name, parent_line_id="",
                components=list(components), picker_config={}, manufacturer="Whelen",
                raw_color="", lens="", quantity=quantity, new_or_used="New", source="",
            ),
        )

    groups = _manifest_groups([
        planned("Wing Wraps", part_type="wing_wraps"),
        planned("Pit Bar", part_type="pit_bar"),
        # Legacy rows lack the newer part_type identifier; they still need to
        # sit with their bumper-system peers in the customer-facing manifest.
        planned("Push Bumper", part_type=""),
        planned("Howler", part_type="howler"),
        planned("Siren Speaker 1", part_type="siren_speaker", part_number="SA315P"),
        planned(
            "Control Head 1", part_type="control_head",
            notes="PA mic: Driver's door · Magnetic mic",
            components=[
                {"part_number": "CCTL7"},
                {"label": "PA Mic", "location": "Driver's door", "detail": "Magnetic mic"},
            ],
        ),
        planned(
            "Radio Communications", part_type="radio_head",
            notes="Radio Communications — guided system details",
            components=[
                {"label": "Radio microphone", "detail": "Uses the selected center-console mic clip"},
                {"label": "Radio speaker", "location": "Back of center console", "detail": "Shop mounting location"},
            ],
        ),
    ])
    entries = {label: rows for label, rows in groups}

    structural_names = [entry.name for entry in entries["Structural Equipment"]]
    assert structural_names[:3] == ["Push Bumper", "Pit Bar", "Wing Wraps"]
    equipment_names = [entry.name for entry in entries["Equipment & Electronics"]]
    assert equipment_names[:2] == ["Siren Speaker(s)", "Howler"]

    control_head_rows = [entry for entry in entries["Equipment & Electronics"] if entry.name == "Control Head 1"]
    assert len(control_head_rows) == 1
    assert "PA mic: Driver's door" in control_head_rows[0].detail
    assert "PA Mic" not in equipment_names
    assert "guided system" not in "\n".join(
        f"{entry.description}\n{entry.detail}" for entry in entries["Equipment & Electronics"]
    ).casefold()
    radio_speaker = next(entry for entry in entries["Equipment & Electronics"] if entry.name == "Radio speaker")
    assert radio_speaker.location == "Back of center console"
    assert radio_speaker.detail == ""


def test_ppt_vehicle_stays_below_negative_layer_bumper_and_lights():
    from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    vehicle = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, 0, 0, 1, 1)
    bumper = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, 0, 0, 1, 1)
    light = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, 0, 0, 1, 1)

    _stack_parts_above_vehicle(
        slide, vehicle._element,
        [(light._element, 0), (bumper._element, -20)],
    )

    elements = list(slide.shapes._spTree)
    assert elements.index(vehicle._element) < elements.index(bumper._element) < elements.index(light._element)


def test_blank_legacy_status_maps_to_new_even_when_old_source_text_is_present():
    text, _ = _badge_label(SimpleNamespace(
        new_or_used="", source="Customer supplied", is_reused=False,
    ))

    assert text == "■ NEW"


def test_visual_part_callouts_show_comment_and_used_source():
    part = SimpleNamespace(
        supply_type="customer_supplied", customer_condition="used",
        customer_source="Retired Unit 12", new_or_used="Used", source="Retired Unit 12",
        comment="Confirm antenna routing with customer.",
    )

    assert _legend_callouts(part) == [
        "NOTE: Confirm antenna routing with customer.",
        "USED SOURCE: Retired Unit 12",
    ]


def test_render_exception_detail_pages_paginate_without_crossing_footer():
    prs = Presentation()
    prs.slide_width = SLIDE_W_EMU
    prs.slide_height = SLIDE_H_EMU
    failures = [
        SimpleNamespace(
            name=f"Unresolved Front Component {index}",
            location="FRONT BUMPER / WINDSHIELD",
            notes="front: The placement asset and coordinates could not be resolved for this item.",
        )
        for index in range(30)
    ]

    pages_added = add_render_exception_slides(
        prs, [("front", failures)], paths=None, footer_text="Test footer"
    )

    assert pages_added >= 2
    rendered_rows = 0
    for slide in prs.slides:
        tables = [shape for shape in slide.shapes if shape.has_table]
        assert len(tables) == 1
        table_shape = tables[0]
        assert table_shape.top + table_shape.height <= prs.slide_height - FOOTER_H
        rendered_rows += len(table_shape.table.rows) - 1  # exclude repeated header
    assert rendered_rows == len(failures)
