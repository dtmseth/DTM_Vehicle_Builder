"""Tests for the Phase 9 rule engine."""
from __future__ import annotations

import pytest

from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
from dtm_buildsheet.domain.rules import RuleSeverity, ValidationMessage, ValidationResult
from dtm_buildsheet.rules.engine import run_rules


# ── helpers ───────────────────────────────────────────────────────────────────

def _project(parts: list[dict], vehicle_type: str = "TAHOE") -> ProjectInput:
    part_inputs = [
        PartInput(
            name=p["name"],
            include=p.get("include", True),
            location=p.get("location", ""),
        )
        for p in parts
    ]
    return ProjectInput(
        info={"VehicleType": vehicle_type, "ProjectID": "TEST"},
        parts=part_inputs,
        notes=[],
    )


def _rules(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "rules": {
            "incompatible_parts": [],
            "required_dependencies": [],
            "vehicle_compatibility": [],
            "location_compatibility": [],
            "part_groups": [],
            "presets": [],
        },
    }
    base["rules"].update(overrides)
    return base


# ── ValidationResult ──────────────────────────────────────────────────────────

class TestValidationResult:
    def test_empty_no_errors(self):
        r = ValidationResult()
        assert not r.has_errors
        assert not r.has_warnings

    def test_warning_detected(self):
        r = ValidationResult(messages=[
            ValidationMessage("r1", RuleSeverity.WARNING, "msg")
        ])
        assert r.has_warnings
        assert not r.has_errors

    def test_error_detected(self):
        r = ValidationResult(messages=[
            ValidationMessage("r1", RuleSeverity.ERROR, "msg")
        ])
        assert r.has_errors

    def test_errors_filter(self):
        r = ValidationResult(messages=[
            ValidationMessage("r1", RuleSeverity.WARNING, "w"),
            ValidationMessage("r2", RuleSeverity.ERROR, "e"),
        ])
        assert len(r.errors()) == 1
        assert len(r.warnings()) == 1

    def test_to_dict_shape(self):
        r = ValidationResult(messages=[
            ValidationMessage("r1", RuleSeverity.WARNING, "msg", part_name="Part A")
        ])
        d = r.to_dict()
        assert d["has_errors"] is False
        assert d["has_warnings"] is True
        assert len(d["messages"]) == 1
        m = d["messages"][0]
        assert m["rule_id"] == "r1"
        assert m["severity"] == "warning"
        assert m["message"] == "msg"
        assert m["part_name"] == "Part A"


# ── incompatible_parts ────────────────────────────────────────────────────────

class TestIncompatibleParts:
    def _rules_with_incompat(self, parts, max_count=1, severity="warning"):
        return _rules(incompatible_parts=[{
            "rule_id": "ic_test",
            "severity": severity,
            "parts": parts,
            "max_count": max_count,
            "message": "Conflict",
        }])

    def test_single_part_no_conflict(self):
        project = _project([{"name": "Part A"}])
        result = run_rules(project, self._rules_with_incompat(["Part A", "Part B"]))
        assert not result.messages

    def test_two_parts_fires(self):
        project = _project([{"name": "Part A"}, {"name": "Part B"}])
        result = run_rules(project, self._rules_with_incompat(["Part A", "Part B"]))
        assert len(result.messages) == 1
        assert result.messages[0].rule_id == "ic_test"

    def test_three_parts_max_two_no_fire(self):
        project = _project([{"name": "Part A"}, {"name": "Part B"}])
        result = run_rules(project, self._rules_with_incompat(
            ["Part A", "Part B", "Part C"], max_count=2
        ))
        assert not result.messages

    def test_three_parts_max_two_fires(self):
        project = _project([{"name": "Part A"}, {"name": "Part B"}, {"name": "Part C"}])
        result = run_rules(project, self._rules_with_incompat(
            ["Part A", "Part B", "Part C"], max_count=2
        ))
        assert len(result.messages) == 1

    def test_excluded_part_not_counted(self):
        project = _project([
            {"name": "Part A", "include": True},
            {"name": "Part B", "include": False},
        ])
        result = run_rules(project, self._rules_with_incompat(["Part A", "Part B"]))
        assert not result.messages

    def test_case_insensitive(self):
        project = _project([{"name": "part a"}, {"name": "PART B"}])
        result = run_rules(project, self._rules_with_incompat(["Part A", "Part B"]))
        assert len(result.messages) == 1

    def test_severity_error(self):
        project = _project([{"name": "Part A"}, {"name": "Part B"}])
        result = run_rules(project, self._rules_with_incompat(
            ["Part A", "Part B"], severity="error"
        ))
        assert result.messages[0].severity == RuleSeverity.ERROR


# ── required_dependencies ─────────────────────────────────────────────────────

class TestRequiredDependencies:
    def _rules_with_dep(self, part, requires_any, severity="warning"):
        return _rules(required_dependencies=[{
            "rule_id": "dep_test",
            "severity": severity,
            "part": part,
            "requires_any": requires_any,
            "message": "Dependency missing",
        }])

    def test_part_absent_no_fire(self):
        project = _project([{"name": "Other Part"}])
        result = run_rules(project, self._rules_with_dep("Widget", ["Base"]))
        assert not result.messages

    def test_part_present_dep_present(self):
        project = _project([{"name": "Widget"}, {"name": "Base"}])
        result = run_rules(project, self._rules_with_dep("Widget", ["Base"]))
        assert not result.messages

    def test_part_present_dep_absent_fires(self):
        project = _project([{"name": "Widget"}])
        result = run_rules(project, self._rules_with_dep("Widget", ["Base"]))
        assert len(result.messages) == 1
        assert result.messages[0].part_name == "Widget"
        assert result.messages[0].suggested_fix is not None

    def test_requires_any_one_present(self):
        project = _project([{"name": "Widget"}, {"name": "Alt Base"}])
        result = run_rules(project, self._rules_with_dep("Widget", ["Base", "Alt Base"]))
        assert not result.messages

    def test_excluded_dependent_no_fire(self):
        project = _project([{"name": "Widget", "include": False}])
        result = run_rules(project, self._rules_with_dep("Widget", ["Base"]))
        assert not result.messages

    def test_case_insensitive(self):
        project = _project([{"name": "WIDGET"}])
        result = run_rules(project, self._rules_with_dep("widget", ["base"]))
        assert len(result.messages) == 1


# ── vehicle_compatibility ─────────────────────────────────────────────────────

class TestVehicleCompatibility:
    def _rules_with_vc(self, part, allowed_vehicles, severity="warning"):
        return _rules(vehicle_compatibility=[{
            "rule_id": "vc_test",
            "severity": severity,
            "part": part,
            "allowed_vehicles": allowed_vehicles,
            "message": "Not compatible",
        }])

    def test_compatible_vehicle_no_fire(self):
        project = _project([{"name": "Roof Light"}], vehicle_type="TAHOE")
        result = run_rules(project, self._rules_with_vc("Roof Light", ["TAHOE", "PIU"]))
        assert not result.messages

    def test_incompatible_vehicle_fires(self):
        project = _project([{"name": "Roof Light"}], vehicle_type="CHARGER")
        result = run_rules(project, self._rules_with_vc("Roof Light", ["TAHOE", "PIU"]))
        assert len(result.messages) == 1

    def test_part_absent_no_fire(self):
        project = _project([{"name": "Other Part"}], vehicle_type="CHARGER")
        result = run_rules(project, self._rules_with_vc("Roof Light", ["TAHOE"]))
        assert not result.messages

    def test_empty_allowed_no_fire(self):
        project = _project([{"name": "Roof Light"}], vehicle_type="CHARGER")
        result = run_rules(project, self._rules_with_vc("Roof Light", []))
        assert not result.messages

    def test_case_insensitive(self):
        project = _project([{"name": "Roof Light"}], vehicle_type="tahoe")
        result = run_rules(project, self._rules_with_vc("Roof Light", ["TAHOE"]))
        assert not result.messages


# ── location_compatibility ────────────────────────────────────────────────────

class TestLocationCompatibility:
    def _rules_with_loc(self, part, allowed_locations, severity="warning"):
        return _rules(location_compatibility=[{
            "rule_id": "loc_test",
            "severity": severity,
            "part": part,
            "allowed_locations": allowed_locations,
            "message": "Wrong location",
        }])

    def test_allowed_location_no_fire(self):
        project = _project([{"name": "Light Bar", "location": "Roof"}])
        result = run_rules(project, self._rules_with_loc("Light Bar", ["Roof"]))
        assert not result.messages

    def test_disallowed_location_fires(self):
        project = _project([{"name": "Light Bar", "location": "Trunk"}])
        result = run_rules(project, self._rules_with_loc("Light Bar", ["Roof"]))
        assert len(result.messages) == 1
        assert result.messages[0].suggested_fix is not None

    def test_no_location_no_fire(self):
        project = _project([{"name": "Light Bar", "location": ""}])
        result = run_rules(project, self._rules_with_loc("Light Bar", ["Roof"]))
        assert not result.messages

    def test_case_insensitive(self):
        project = _project([{"name": "Light Bar", "location": "ROOF"}])
        result = run_rules(project, self._rules_with_loc("Light Bar", ["Roof"]))
        assert not result.messages


# ── part_groups ───────────────────────────────────────────────────────────────

class TestPartGroups:
    def _rules_with_group(self, parts, max_count=1, severity="warning"):
        return _rules(part_groups=[{
            "rule_id": "grp_test",
            "severity": severity,
            "group_name": "Test Group",
            "parts": parts,
            "max_count": max_count,
            "message": "Too many from group",
        }])

    def test_one_from_group_no_fire(self):
        project = _project([{"name": "Part A"}])
        result = run_rules(project, self._rules_with_group(["Part A", "Part B", "Part C"]))
        assert not result.messages

    def test_two_from_group_fires_max_one(self):
        project = _project([{"name": "Part A"}, {"name": "Part B"}])
        result = run_rules(project, self._rules_with_group(
            ["Part A", "Part B", "Part C"], max_count=1
        ))
        assert len(result.messages) == 1

    def test_two_from_group_no_fire_max_two(self):
        project = _project([{"name": "Part A"}, {"name": "Part B"}])
        result = run_rules(project, self._rules_with_group(
            ["Part A", "Part B", "Part C"], max_count=2
        ))
        assert not result.messages

    def test_excluded_not_counted(self):
        project = _project([
            {"name": "Part A", "include": True},
            {"name": "Part B", "include": False},
        ])
        result = run_rules(project, self._rules_with_group(
            ["Part A", "Part B"], max_count=1
        ))
        assert not result.messages


# ── empty / missing rules ─────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_rules(self):
        project = _project([{"name": "Part A"}])
        result = run_rules(project, {"rules": {}})
        assert not result.messages

    def test_no_rules_key(self):
        project = _project([{"name": "Part A"}])
        result = run_rules(project, {})
        assert not result.messages

    def test_no_included_parts(self):
        project = _project([{"name": "Part A", "include": False}])
        rules = _rules(required_dependencies=[{
            "rule_id": "r1", "severity": "warning",
            "part": "Part A", "requires_any": ["Part B"],
            "message": "msg",
        }])
        result = run_rules(project, rules)
        assert not result.messages

    def test_multiple_rules_can_all_fire(self):
        project = _project([{"name": "Widget"}, {"name": "Gadget"}])
        rules = _rules(
            incompatible_parts=[{
                "rule_id": "ic1", "severity": "warning",
                "parts": ["Widget", "Gadget"], "max_count": 1, "message": "conflict",
            }],
            required_dependencies=[{
                "rule_id": "dep1", "severity": "warning",
                "part": "Widget", "requires_any": ["Base"], "message": "dep missing",
            }],
        )
        result = run_rules(project, rules)
        assert len(result.messages) == 2


# ── integration: bundled build_rules.json ─────────────────────────────────────

class TestBundledRules:
    """Smoke-test the real bundled build_rules.json against synthetic projects."""

    @pytest.fixture
    def bundled_rules(self):
        from dtm_buildsheet.config.loader import load_configs
        config = load_configs()
        return config.build_rules

    def test_bundled_rules_loads(self, bundled_rules):
        assert "rules" in bundled_rules

    def test_tracer_conflict_fires(self, bundled_rules):
        project = _project([
            {"name": "2-Lamp Tracer"},
            {"name": "5-Lamp Tracer"},
        ])
        result = run_rules(project, bundled_rules)
        rule_ids = [m.rule_id for m in result.messages]
        assert "incompat_tracers" in rule_ids

    def test_tracer_single_ok(self, bundled_rules):
        project = _project([{"name": "2-Lamp Tracer"}])
        result = run_rules(project, bundled_rules)
        rule_ids = [m.rule_id for m in result.messages]
        assert "incompat_tracers" not in rule_ids

    def test_speaker_bracket_without_speaker_fires(self, bundled_rules):
        project = _project([{"name": "Siren Speaker Bracket"}])
        result = run_rules(project, bundled_rules)
        rule_ids = [m.rule_id for m in result.messages]
        assert "dep_speaker_bracket" in rule_ids

    def test_speaker_bracket_with_speaker_ok(self, bundled_rules):
        project = _project([
            {"name": "Siren Speaker Bracket"},
            {"name": "Siren Speaker 1"},
        ])
        result = run_rules(project, bundled_rules)
        rule_ids = [m.rule_id for m in result.messages]
        assert "dep_speaker_bracket" not in rule_ids

    def test_radar_mount_without_radar_fires(self, bundled_rules):
        project = _project([{"name": "Front Radar Antenna Mount"}])
        result = run_rules(project, bundled_rules)
        rule_ids = [m.rule_id for m in result.messages]
        assert "dep_radar_front_mount" in rule_ids

    def test_radar_mount_with_radar_ok(self, bundled_rules):
        project = _project([
            {"name": "Front Radar Antenna Mount"},
            {"name": "Radar"},
        ])
        result = run_rules(project, bundled_rules)
        rule_ids = [m.rule_id for m in result.messages]
        assert "dep_radar_front_mount" not in rule_ids

    def test_no_parts_no_messages(self, bundled_rules):
        project = _project([])
        result = run_rules(project, bundled_rules)
        assert not result.messages


# ── planner integration ───────────────────────────────────────────────────────

class TestPlannerIntegration:
    """Verify rule messages reach BuildPlan.warnings."""

    def test_rule_warnings_in_build_plan(self):
        from dtm_buildsheet.config.loader import load_configs
        from dtm_buildsheet.planning.planner import build_plan

        config = load_configs()
        project = ProjectInput(
            info={"VehicleType": "TAHOE", "ProjectID": "TEST",
                  "NewVehicle": {}, "ExistingVehicle": {}},
            parts=[
                PartInput(name="2-Lamp Tracer", include=True),
                PartInput(name="5-Lamp Tracer", include=True),
            ],
            notes=[],
        )
        plan = build_plan(project, config)
        rule_warnings = [w for w in plan.warnings if w.startswith("[RULE]") or w.startswith("[ERROR]")]
        assert any("incompat_tracers" in w or "tracer" in w.lower() for w in rule_warnings)
