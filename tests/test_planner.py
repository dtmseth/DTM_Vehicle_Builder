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


def test_build_plan_notes_is_list(stearns_input, config):
    plan = build_plan(stearns_input, config)
    assert isinstance(plan.notes, list)


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


# ── second sample workbook also plans ─────────────────────────────────────────

def test_test_build_plans_successfully(test_build_input, config):
    plan = build_plan(test_build_input, config)
    assert isinstance(plan, BuildPlan)
    assert len(plan.planned_parts) > 0
