from __future__ import annotations

import json
from pathlib import Path

from ..paths import AppPaths, ensure_workspace
from .migrations import migrate
from .schemas import REQUIRED_CONFIG_FILES, validate_config_payload


def get_config_path(filename: str, paths: AppPaths | None = None) -> Path:
    if filename not in REQUIRED_CONFIG_FILES:
        raise ValueError(f"Unknown config file: {filename}")
    active_paths = paths or ensure_workspace()
    return active_paths.workspace_config_dir / filename


def load_json_file(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def load_config(filename: str, paths: AppPaths | None = None) -> dict:
    raw = load_json_file(get_config_path(filename, paths))
    migrated = migrate(filename, raw)
    return validate_config_payload(filename, migrated)


def save_config(filename: str, data: object, paths: AppPaths | None = None) -> dict:
    active_paths = paths or ensure_workspace()
    migrated = migrate(filename, data if isinstance(data, dict) else {})
    normalized = validate_config_payload(filename, migrated)
    path = get_config_path(filename, active_paths)
    path.write_text(json.dumps(normalized, indent=2) + "\n", "utf-8")
    return normalized
