"""Data model for build-time validation results.

Rules live in build_rules.json; the engine that evaluates them lives in
rules/engine.py.  This module only holds the result types so any layer of
the stack can depend on them without importing the engine.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RuleSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationMessage:
    rule_id: str
    severity: RuleSeverity
    message: str
    part_name: str | None = None
    suggested_fix: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "message": self.message,
            "part_name": self.part_name,
            "suggested_fix": self.suggested_fix,
        }


@dataclass
class ValidationResult:
    messages: list[ValidationMessage] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(m.severity == RuleSeverity.ERROR for m in self.messages)

    @property
    def has_warnings(self) -> bool:
        return any(m.severity == RuleSeverity.WARNING for m in self.messages)

    def errors(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.severity == RuleSeverity.ERROR]

    def warnings(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.severity == RuleSeverity.WARNING]

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
            "messages": [m.to_dict() for m in self.messages],
        }
