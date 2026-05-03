"""
End-to-end round-trip tests for generated PIU workbooks.

Workbooks live in samples/generated/ and are committed to the repo.
Re-generate them any time with:
    python scripts/gen_test_workbooks.py

Each test class covers one workbook and verifies:
  1. load_input() parses it without error
  2. Expected fields and parts survive the parse
  3. build_plan() runs without raising on the result
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.inputs.excel_reader import load_input
from dtm_buildsheet.domain.input_models import ProjectInput
from dtm_buildsheet.planning.planner import build_plan
from dtm_buildsheet.config_store import load_config

GENERATED_DIR = Path(__file__).resolve().parents[1] / "samples" / "generated"


def _require(filename: str) -> Path:
    path = GENERATED_DIR / filename
    if not path.exists():
        pytest.skip(
            f"Generated workbook not found: {filename}\n"
            "Run: python scripts/gen_test_workbooks.py"
        )
    return path


def _expected_part_names(app_paths) -> set[str]:
    """All part names listed in workbook_rules template_sections."""
    wr = load_config("workbook_rules.json", app_paths)
    return {
        part["name"]
        for section in wr.get("template_sections", [])
        for part in section.get("parts", [])
        if part.get("name")
    }


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def piu_full(app_paths):
    return load_input(_require("piu_full_build.xlsx"))


@pytest.fixture(scope="module")
def piu_locs(app_paths):
    return load_input(_require("piu_location_sweep.xlsx"))


@pytest.fixture(scope="module")
def piu_mock(app_paths):
    return load_input(_require("mock_realistic_piu.xlsx"))


# ── piu_full_build.xlsx ───────────────────────────────────────────────────────

class TestPiuFullBuild:
    def test_is_project_input(self, piu_full):
        assert isinstance(piu_full, ProjectInput)

    def test_vehicle_type_piu(self, piu_full):
        assert piu_full.info["VehicleType"] == "PIU"

    def test_project_id_safe(self, piu_full):
        pid = piu_full.info["ProjectID"]
        assert pid and " " not in pid and "/" not in pid

    def test_agency_parsed(self, piu_full):
        assert piu_full.info.get("Agency")

    def test_quote_parsed(self, piu_full):
        assert piu_full.info.get("QuoteNumber")

    def test_vehicle_detail_parsed(self, piu_full):
        nv = piu_full.info.get("NewVehicle", {})
        assert nv.get("MAKE") == "Ford"
        assert nv.get("YEAR") == "2024"

    def test_all_parts_present(self, piu_full, app_paths):
        """Every part written by the generator must come back from load_input."""
        expected = _expected_part_names(app_paths)
        parsed   = {p.name for p in piu_full.parts}
        missing  = expected - parsed
        assert not missing, f"Parts not parsed from full build: {sorted(missing)}"

    def test_parts_have_valid_types(self, piu_full):
        for part in piu_full.parts:
            assert isinstance(part.include, bool),  f"'{part.name}' include is not bool"
            assert isinstance(part.quantity, int),   f"'{part.name}' quantity is not int"
            assert part.name,                         "empty part name"

    def test_all_parts_included_by_default(self, piu_full):
        excluded = [p for p in piu_full.parts if not p.include]
        assert not excluded, f"Parts unexpectedly excluded: {[p.name for p in excluded]}"

    def test_new_used_field_parsed(self, piu_full):
        assert any(p.new_or_used == "NEW" for p in piu_full.parts)

    def test_planner_runs(self, piu_full, config):
        plan = build_plan(piu_full, config)
        assert plan is not None

    def test_all_parts_reach_planner(self, piu_full, config):
        """No part should be silently dropped between load_input and build_plan,
        unless a co_part_rule explicitly suppresses it (e.g. Speaker 2 when Speaker 1 present)."""
        plan = build_plan(piu_full, config)
        planned_names = {pp.part_name for pp in plan.planned_parts}
        for p in piu_full.parts:
            if p.name in planned_names:
                continue
            spec = config.parts_by_name.get(p.name.upper(), {})
            assert spec.get("co_part_rules"), (
                f"'{p.name}' missing from plan.planned_parts "
                f"and has no co_part_rules to explain the omission"
            )

    def test_renderable_parts_get_placements_or_warn(self, piu_full, config):
        """Parts with render_kind != 'none' and a location should land on the diagram
        OR carry a warning explaining why they didn't."""
        plan = build_plan(piu_full, config)
        for pp in plan.planned_parts:
            if pp.render_kind == "none":
                continue
            if not pp.raw.location:
                continue
            assert pp.on_diagram or pp.warnings, (
                f"'{pp.part_name}' has render_kind='{pp.render_kind}', "
                f"location='{pp.raw.location}', but no placements and no warnings"
            )


# ── piu_location_sweep.xlsx ───────────────────────────────────────────────────

class TestPiuLocationSweep:
    def test_is_project_input(self, piu_locs):
        assert isinstance(piu_locs, ProjectInput)

    def test_vehicle_type_piu(self, piu_locs):
        assert piu_locs.info["VehicleType"] == "PIU"

    def test_many_rows(self, piu_locs):
        # Every part with location options appears once per location — expect > 100 rows
        assert len(piu_locs.parts) > 100, (
            f"Expected >100 part rows in location sweep, got {len(piu_locs.parts)}"
        )

    def test_all_parts_have_locations(self, piu_locs):
        missing = [p.name for p in piu_locs.parts if not p.location]
        assert not missing, f"Location-sweep rows with no location: {missing[:10]}"

    def test_location_values_are_strings(self, piu_locs):
        for p in piu_locs.parts:
            assert isinstance(p.location, str), f"'{p.name}' location is not str"

    def test_planner_runs(self, piu_locs, config):
        plan = build_plan(piu_locs, config)
        assert plan is not None

    def test_known_locations_produce_placements(self, piu_locs, config):
        """At least some of the location-sweep parts should end up on the diagram."""
        plan = build_plan(piu_locs, config)
        on_diagram = [pp for pp in plan.planned_parts if pp.on_diagram]
        assert on_diagram, "No parts placed on diagram from location sweep — all misses"


# ── mock_realistic_piu.xlsx ───────────────────────────────────────────────────

class TestMockRealisticPiu:
    def test_is_project_input(self, piu_mock):
        assert isinstance(piu_mock, ProjectInput)

    def test_vehicle_type_piu(self, piu_mock):
        assert piu_mock.info["VehicleType"] == "PIU"

    def test_agency_is_riverside(self, piu_mock):
        assert "Riverside" in (piu_mock.info.get("Agency") or "")

    def test_quote_parsed(self, piu_mock):
        assert piu_mock.info.get("QuoteNumber") == "RCS-2026-041"

    def test_contact_parsed(self, piu_mock):
        assert piu_mock.info.get("PrimaryContact")

    def test_vehicle_detail_parsed(self, piu_mock):
        nv = piu_mock.info.get("NewVehicle", {})
        assert nv.get("MODEL", "").upper().startswith("POLICE")

    def test_parts_non_empty(self, piu_mock):
        assert len(piu_mock.parts) >= 30

    def test_key_parts_present(self, piu_mock):
        names = {p.name for p in piu_mock.parts}
        for expected in [
            "Roof Light Bar",
            "Forward Warning 1",
            "Siren Speaker 1",
            "Siren Speaker 2",
            "Front Partition",
            "Gunlock 1",
            "Radar",
        ]:
            assert expected in names, f"Expected '{expected}' in mock realistic build"

    def test_speaker_pair_both_present(self, piu_mock):
        names = {p.name for p in piu_mock.parts}
        assert "Siren Speaker 1" in names
        assert "Siren Speaker 2" in names

    def test_planner_runs(self, piu_mock, config):
        plan = build_plan(piu_mock, config)
        assert plan is not None

    def test_light_bar_on_diagram(self, piu_mock, config):
        plan = build_plan(piu_mock, config)
        lb = next((pp for pp in plan.planned_parts if pp.part_name == "Roof Light Bar"), None)
        assert lb is not None, "Roof Light Bar missing from plan"
        assert lb.on_diagram or lb.warnings, "Roof Light Bar: no placements and no warnings"

    def test_co_part_speaker_skip(self, piu_mock, config):
        """With both speakers present, the co-part rule should suppress one
        OR both should appear — the key is the plan doesn't raise."""
        plan = build_plan(piu_mock, config)
        speakers = [pp for pp in plan.planned_parts
                    if "Siren Speaker" in pp.part_name]
        # At least one speaker must be in the plan
        assert speakers, "No siren speakers reached the plan"
