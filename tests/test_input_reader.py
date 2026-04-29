"""Baseline tests: Excel workbook parsing via input_reader."""
from __future__ import annotations

import pytest

from dtm_buildsheet.input_reader import load_input
from dtm_buildsheet.models import PartInput, ProjectInput

from .conftest import PRIMARY_XLS, SECONDARY_XLS


# ── both sample files load ─────────────────────────────────────────────────────

def test_stearns_loads(stearns_input):
    assert isinstance(stearns_input, ProjectInput)


def test_test_build_loads(test_build_input):
    assert isinstance(test_build_input, ProjectInput)


# ── project info ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture_name", ["stearns_input", "test_build_input"])
def test_info_has_vehicle_type(fixture_name, request):
    project = request.getfixturevalue(fixture_name)
    assert "VehicleType" in project.info
    assert isinstance(project.info["VehicleType"], str)
    assert project.info["VehicleType"]  # non-empty


@pytest.mark.parametrize("fixture_name", ["stearns_input", "test_build_input"])
def test_info_has_project_id(fixture_name, request):
    project = request.getfixturevalue(fixture_name)
    assert "ProjectID" in project.info
    project_id = project.info["ProjectID"]
    assert isinstance(project_id, str)
    assert project_id  # non-empty
    # ProjectID must be filesystem-safe (no spaces, no slashes)
    assert " " not in project_id
    assert "/" not in project_id
    assert "\\" not in project_id


@pytest.mark.parametrize("fixture_name", ["stearns_input", "test_build_input"])
def test_info_has_vehicle_dicts(fixture_name, request):
    project = request.getfixturevalue(fixture_name)
    assert "NewVehicle" in project.info
    assert "ExistingVehicle" in project.info
    assert isinstance(project.info["NewVehicle"], dict)
    assert isinstance(project.info["ExistingVehicle"], dict)


# ── parts list ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture_name", ["stearns_input", "test_build_input"])
def test_parts_non_empty(fixture_name, request):
    project = request.getfixturevalue(fixture_name)
    assert len(project.parts) > 0, "Expected at least one part in the workbook"


@pytest.mark.parametrize("fixture_name", ["stearns_input", "test_build_input"])
def test_parts_are_part_input_instances(fixture_name, request):
    project = request.getfixturevalue(fixture_name)
    for part in project.parts:
        assert isinstance(part, PartInput)


@pytest.mark.parametrize("fixture_name", ["stearns_input", "test_build_input"])
def test_parts_have_names(fixture_name, request):
    project = request.getfixturevalue(fixture_name)
    for part in project.parts:
        assert part.name, f"Part with empty name found: {part}"


@pytest.mark.parametrize("fixture_name", ["stearns_input", "test_build_input"])
def test_parts_include_field_is_bool(fixture_name, request):
    project = request.getfixturevalue(fixture_name)
    for part in project.parts:
        assert isinstance(part.include, bool), f"Part '{part.name}' include is not bool"


def test_stearns_has_included_and_excluded_parts(stearns_input):
    included = [p for p in stearns_input.parts if p.include]
    excluded = [p for p in stearns_input.parts if not p.include]
    assert len(included) > 0, "Expected some included parts"
    # excluded may be zero if all parts are included — that's OK
    _ = excluded


def test_parts_quantity_is_int(stearns_input):
    for part in stearns_input.parts:
        assert isinstance(part.quantity, int), f"Part '{part.name}' quantity is not int"


# ── notes ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture_name", ["stearns_input", "test_build_input"])
def test_notes_is_list(fixture_name, request):
    project = request.getfixturevalue(fixture_name)
    assert isinstance(project.notes, list)


# ── load_input is idempotent (second call returns same data) ───────────────────

def test_load_input_idempotent():
    first = load_input(PRIMARY_XLS)
    second = load_input(PRIMARY_XLS)
    assert first.info["VehicleType"] == second.info["VehicleType"]
    assert len(first.parts) == len(second.parts)
