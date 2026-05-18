"""Serves config-driven dropdown options for the project UI.

The canonical list lives in resources/config/project_options.json (bundled) and
is optionally overridden by workspace/config/project_options.json (user-editable
after first run in bundled mode; dev mode reads directly from the source tree).
"""
from __future__ import annotations

import json

from ...paths import AppPaths, DEFAULT_CONFIG_DIR


def load_project_options(paths: AppPaths) -> dict:
    """Return the project_options dict, reading workspace copy first, falling back to bundled."""
    workspace_copy = paths.workspace_config_dir / "project_options.json"
    if workspace_copy.exists():
        try:
            return json.loads(workspace_copy.read_text("utf-8"))
        except Exception:
            pass
    bundled = DEFAULT_CONFIG_DIR / "project_options.json"
    if bundled.exists():
        return json.loads(bundled.read_text("utf-8"))
    return {
        "schema_version": 1,
        "build_types": ["Patrol", "Admin", "Unmarked", "K-9", "Fire"],
        "camera_brands": [],
        "lighting_brands": [],
        "bumper_brands": [],
        "cage_brands": [],
    }


def handle_get_project_options(paths: AppPaths) -> dict:
    try:
        options = load_project_options(paths)
        return {"ok": True, "options": options}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
