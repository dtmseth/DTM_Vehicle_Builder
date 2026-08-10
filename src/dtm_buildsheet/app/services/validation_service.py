from __future__ import annotations

from ...config.loader import load_configs
from ...domain.rules import ValidationResult
from ...inputs.gui_entry import project_input_from_form
from ...inputs.project_drafts import draft_to_project_input
from ...paths import AppPaths
from ...rules.engine import run_rules
from .draft_service import load_draft_for_request


def validate_form(body: dict, paths: AppPaths) -> dict:
    """Validate a GUI form submission dict against the rule engine."""
    try:
        project = project_input_from_form(body)
        config = load_configs(paths)
        result = run_rules(project, config.build_rules)
        return {"ok": True, **result.to_dict()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def validate_draft(draft_id: str, paths: AppPaths) -> dict:
    """Validate a saved draft by ID."""
    try:
        draft = load_draft_for_request(draft_id, paths)
        project = draft_to_project_input(draft)
        config = load_configs(paths)
        result = run_rules(project, config.build_rules)
        return {"ok": True, "draft_id": draft_id, **result.to_dict()}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
