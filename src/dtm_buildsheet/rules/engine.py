"""Rule engine: evaluates build_rules.json against a ProjectInput.

run_rules(project, build_rules_config) -> ValidationResult

Supported rule types
--------------------
incompatible_parts
    A set of parts where at most `max_count` (default 1) may be included
    simultaneously.  Fires when the count exceeds the limit.

required_dependencies
    Part A requires at least one part from `requires_any` to also be included.
    Fires when A is present but none of the required parts are.

vehicle_compatibility
    Part A is only valid on the listed `allowed_vehicles`.  Fires when A is
    included on a vehicle type that is not in the list.

location_compatibility
    Part A is only valid in locations from `allowed_locations`.  Fires when A
    is included with a location that is not in the allowed set (and a location
    was actually specified).

part_groups
    A named group of parts where at most `max_count` may be included.
    Fires when the included count exceeds `max_count`.

presets
    Named bundles of parts (data only — no validation logic).
"""
from __future__ import annotations

from ..domain.input_models import ProjectInput
from ..domain.rules import RuleSeverity, ValidationMessage, ValidationResult


def _norm(value: str) -> str:
    """Normalize a part name for case-insensitive comparison."""
    return value.strip().upper()


def _severity(raw: str) -> RuleSeverity:
    return RuleSeverity.ERROR if raw.lower() == "error" else RuleSeverity.WARNING


def run_rules(project: ProjectInput, build_rules_config: dict) -> ValidationResult:
    """Evaluate all rules in build_rules_config against project.

    Only included parts (part.include == True) are considered.
    """
    rules = build_rules_config.get("rules", {})
    result = ValidationResult()

    # Build normalised set of included part names and their location strings
    included_names: set[str] = set()
    part_locations: dict[str, str] = {}  # normalised name → raw location

    for part in project.parts:
        if not part.include:
            continue
        key = _norm(part.name)
        included_names.add(key)
        if part.location:
            part_locations[key] = part.location

    vehicle_type = _norm(project.info.get("VehicleType", ""))

    # ── incompatible_parts ──────────────────────────────────────────────────
    for rule in rules.get("incompatible_parts", []):
        rule_id = rule.get("rule_id", "?")
        severity = _severity(rule.get("severity", "warning"))
        max_count = int(rule.get("max_count", 1))
        conflicting = [n for n in rule.get("parts", []) if _norm(n) in included_names]
        if len(conflicting) > max_count:
            result.messages.append(
                ValidationMessage(
                    rule_id=rule_id,
                    severity=severity,
                    message=rule.get("message", f"Too many conflicting parts selected: {', '.join(conflicting)}"),
                    part_name=", ".join(conflicting),
                )
            )

    # ── required_dependencies ───────────────────────────────────────────────
    for rule in rules.get("required_dependencies", []):
        rule_id = rule.get("rule_id", "?")
        severity = _severity(rule.get("severity", "warning"))
        part_name = rule.get("part", "")
        if _norm(part_name) not in included_names:
            continue
        required_any = rule.get("requires_any", [])
        if required_any and not any(_norm(r) in included_names for r in required_any):
            result.messages.append(
                ValidationMessage(
                    rule_id=rule_id,
                    severity=severity,
                    message=rule.get(
                        "message",
                        f"'{part_name}' requires one of: {', '.join(required_any)}",
                    ),
                    part_name=part_name,
                    suggested_fix=f"Add one of: {', '.join(required_any)}",
                )
            )

    # ── vehicle_compatibility ───────────────────────────────────────────────
    for rule in rules.get("vehicle_compatibility", []):
        rule_id = rule.get("rule_id", "?")
        severity = _severity(rule.get("severity", "warning"))
        part_name = rule.get("part", "")
        if _norm(part_name) not in included_names:
            continue
        allowed = {_norm(v) for v in rule.get("allowed_vehicles", [])}
        if allowed and vehicle_type not in allowed:
            result.messages.append(
                ValidationMessage(
                    rule_id=rule_id,
                    severity=severity,
                    message=rule.get(
                        "message",
                        f"'{part_name}' is not configured for vehicle type '{project.info.get('VehicleType', '?')}'",
                    ),
                    part_name=part_name,
                )
            )

    # ── location_compatibility ──────────────────────────────────────────────
    for rule in rules.get("location_compatibility", []):
        rule_id = rule.get("rule_id", "?")
        severity = _severity(rule.get("severity", "warning"))
        part_name = rule.get("part", "")
        part_key = _norm(part_name)
        if part_key not in included_names:
            continue
        location = part_locations.get(part_key, "")
        if not location:
            continue
        allowed = {_norm(loc) for loc in rule.get("allowed_locations", [])}
        if allowed and _norm(location) not in allowed:
            result.messages.append(
                ValidationMessage(
                    rule_id=rule_id,
                    severity=severity,
                    message=rule.get(
                        "message",
                        f"'{part_name}' is not valid in location '{location}'",
                    ),
                    part_name=part_name,
                    suggested_fix=f"Valid locations: {', '.join(rule.get('allowed_locations', []))}",
                )
            )

    # ── part_groups ─────────────────────────────────────────────────────────
    for rule in rules.get("part_groups", []):
        rule_id = rule.get("rule_id", "?")
        severity = _severity(rule.get("severity", "warning"))
        max_count = int(rule.get("max_count", 1))
        present = [n for n in rule.get("parts", []) if _norm(n) in included_names]
        if len(present) > max_count:
            group_name = rule.get("group_name", "Part group")
            result.messages.append(
                ValidationMessage(
                    rule_id=rule_id,
                    severity=severity,
                    message=rule.get(
                        "message",
                        f"{group_name}: at most {max_count} part(s) from "
                        f"{', '.join(rule.get('parts', []))} should be selected "
                        f"(found {len(present)})",
                    ),
                    part_name=", ".join(present),
                )
            )

    return result
