"""
Parametrized in-memory tests: every part in workbook_rules through the PIU planner.

No xlsx I/O — ProjectInput objects are built directly from config data.
Runs fast (~0.5s for all 130+ cases) and catches regressions in planning logic.

Two parametrize axes:
  1. test_part_survives_planner  — all 130 parts, first valid location, PIU vehicle
  2. test_location_option        — all (part, location) combos for parts with location options
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
from dtm_buildsheet.domain.plan_models import BuildPlan
from dtm_buildsheet.planning.planner import build_plan


# ── build parametrize lists at import time ────────────────────────────────────

def _read_workbook_rules() -> dict:
    try:
        from dtm_buildsheet.paths import ensure_workspace
        from dtm_buildsheet.config_store import load_config
        paths = ensure_workspace()
        return load_config("workbook_rules.json", paths)
    except Exception:
        return {}


_wr = _read_workbook_rules()
_part_rules: dict = _wr.get("part_rules", {})


def _all_parts() -> list[tuple[str, str]]:
    """Return (part_name, first_location_or_empty) for every part in template_sections."""
    result = []
    for section in _wr.get("template_sections", []):
        for entry in section.get("parts", []):
            name = entry.get("name", "")
            if not name:
                continue
            locs = _part_rules.get(name, {}).get("locations", [])
            result.append((name, locs[0] if locs else ""))
    return result


def _all_part_location_combos() -> list[tuple[str, str]]:
    """Return (part_name, location) for every location option a part has."""
    result = []
    for section in _wr.get("template_sections", []):
        for entry in section.get("parts", []):
            name = entry.get("name", "")
            if not name:
                continue
            locs = _part_rules.get(name, {}).get("locations", [])
            for loc in locs:
                result.append((name, loc))
    return result


_ALL_PARTS            = _all_parts()              # ~130 items
_ALL_PART_LOC_COMBOS  = _all_part_location_combos()  # ~300+ items


def _make_piu_project(*parts: PartInput) -> ProjectInput:
    return ProjectInput(
        info={
            "VehicleType": "PIU",
            "ProjectID":   "TEST-IN-MEMORY",
            "Agency":      "DTM Test",
            "NewVehicle":  {"MODEL": "Police Interceptor Utility"},
            "ExistingVehicle": {},
        },
        parts=list(parts),
        notes=[],
    )


def _make_part(name: str, location: str = "", color: str = "Red/Blue", qty: int = 1) -> PartInput:
    rule = _part_rules.get(name, {})
    return PartInput(
        name=name,
        include=True,
        new_or_used="NEW",
        source="DTM",
        manufacturer=(rule.get("manufacturer") or [""])[0],
        part_number=(rule.get("models") or [""])[0],
        location=location,
        raw_color=color if rule.get("colors") else "",
        quantity=qty,
        lens=(rule.get("lens") or [""])[0],
        notes="",
    )


# ── Layer 2a: every part through the planner ─────────────────────────────────

@pytest.mark.parametrize("part_name,location", _ALL_PARTS, ids=[n for n, _ in _ALL_PARTS])
def test_part_survives_planner(part_name, location, config):
    """build_plan() must not raise for any part in workbook_rules."""
    project = _make_piu_project(_make_part(part_name, location))
    plan = build_plan(project, config)
    assert isinstance(plan, BuildPlan)


@pytest.mark.parametrize("part_name,location", _ALL_PARTS, ids=[n for n, _ in _ALL_PARTS])
def test_part_appears_in_plan(part_name, location, config):
    """Every included part must appear in plan.planned_parts (never silently dropped)."""
    project = _make_piu_project(_make_part(part_name, location))
    plan    = build_plan(project, config)
    names   = {pp.part_name for pp in plan.planned_parts}
    assert part_name in names, (
        f"'{part_name}' was included but missing from plan.planned_parts"
    )


# ── Layer 2b: every location option through the planner ──────────────────────

@pytest.mark.parametrize(
    "part_name,location",
    _ALL_PART_LOC_COMBOS,
    ids=[f"{n}@{loc}" for n, loc in _ALL_PART_LOC_COMBOS],
)
def test_location_option_does_not_crash(part_name, location, config):
    """Every location option from part_rules must not crash the planner."""
    project = _make_piu_project(_make_part(part_name, location))
    plan    = build_plan(project, config)
    assert isinstance(plan, BuildPlan)


# ── Layer 2c: co-part interactions ───────────────────────────────────────────

class TestSirenSpeakerCoParts:
    """The only defined co-part rule: speaker 1 + speaker 2 + bracket."""

    def _speaker(self, n: int, location: str) -> PartInput:
        return _make_part(f"Siren Speaker {n}", location, color="")

    def _bracket(self) -> PartInput:
        return _make_part("Siren Speaker Bracket", "FOLLOW SPEAKER LOCATION", color="")

    def test_speaker1_alone(self, config):
        plan = build_plan(_make_piu_project(self._speaker(1, "TOP OF PUSH BUMPER")), config)
        assert isinstance(plan, BuildPlan)
        names = {pp.part_name for pp in plan.planned_parts}
        assert "Siren Speaker 1" in names

    def test_speaker2_alone(self, config):
        plan = build_plan(_make_piu_project(self._speaker(2, "UNDER PUSH BUMPER")), config)
        assert isinstance(plan, BuildPlan)
        names = {pp.part_name for pp in plan.planned_parts}
        assert "Siren Speaker 2" in names

    def test_both_speakers(self, config):
        project = _make_piu_project(
            self._speaker(1, "TOP OF PUSH BUMPER"),
            self._speaker(2, "UNDER PUSH BUMPER"),
        )
        plan = build_plan(project, config)
        assert isinstance(plan, BuildPlan)
        names = {pp.part_name for pp in plan.planned_parts}
        # At least one speaker must appear (co-part may suppress one)
        assert names & {"Siren Speaker 1", "Siren Speaker 2"}

    def test_both_speakers_with_bracket(self, config):
        project = _make_piu_project(
            self._speaker(1, "TOP OF PUSH BUMPER"),
            self._speaker(2, "UNDER PUSH BUMPER"),
            self._bracket(),
        )
        plan = build_plan(project, config)
        assert isinstance(plan, BuildPlan)

    def test_bracket_alone(self, config):
        plan = build_plan(_make_piu_project(self._bracket()), config)
        assert isinstance(plan, BuildPlan)


# ── Layer 2d: edge-case inputs ────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_parts_list(self, config):
        plan = build_plan(_make_piu_project(), config)
        assert isinstance(plan, BuildPlan)
        assert plan.planned_parts == []

    def test_part_with_qty_zero(self, config):
        part = _make_part("Roof Light Bar", "", qty=0)
        plan = build_plan(_make_piu_project(part), config)
        assert isinstance(plan, BuildPlan)

    def test_part_with_high_qty(self, config):
        part = _make_part("Forward Warning 1", "GRILL", qty=99)
        plan = build_plan(_make_piu_project(part), config)
        assert isinstance(plan, BuildPlan)

    def test_part_with_unknown_location(self, config):
        part = _make_part("Forward Warning 1", "TOTALLY INVALID LOCATION XYZ")
        plan = build_plan(_make_piu_project(part), config)
        assert isinstance(plan, BuildPlan)
        # Should produce a warning, not raise
        fw = next((pp for pp in plan.planned_parts if pp.part_name == "Forward Warning 1"), None)
        assert fw is not None

    def test_unknown_part_name(self, config):
        part = PartInput(name="Nonexistent Widget", include=True, quantity=1)
        plan = build_plan(_make_piu_project(part), config)
        assert isinstance(plan, BuildPlan)
        # Unmapped part still appears in planned_parts
        names = {pp.part_name for pp in plan.planned_parts}
        assert "Nonexistent Widget" in names

    def test_excluded_part_not_in_plan(self, config):
        included = _make_part("Roof Light Bar", "")
        excluded = PartInput(name="Forward Warning 1", include=False, quantity=1)
        plan = build_plan(_make_piu_project(included, excluded), config)
        names = {pp.part_name for pp in plan.planned_parts}
        assert "Forward Warning 1" not in names, "Excluded part appeared in plan"
        assert "Roof Light Bar" in names

    def test_all_parts_excluded(self, config):
        parts = [PartInput(name="Roof Light Bar", include=False, quantity=1)]
        plan  = build_plan(_make_piu_project(*parts), config)
        assert isinstance(plan, BuildPlan)
        assert plan.planned_parts == []
