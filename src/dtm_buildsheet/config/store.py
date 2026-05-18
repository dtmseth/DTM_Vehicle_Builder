from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..paths import AppPaths, ensure_workspace
from ..storage.local import LocalStorageProvider
from .migrations import migrate
from .schemas import REQUIRED_CONFIG_FILES, validate_config_payload

_BACKUP_LIMIT = 20


def _backup_config(path: Path) -> None:
    """Copy *path* to a history sub-directory before overwriting it."""
    if not path.exists():
        return
    history_dir = path.parent / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = history_dir / f"{path.name}.{ts}.bak"
    shutil.copy2(path, backup)
    # Cap to the newest _BACKUP_LIMIT backups for this config file
    pattern = f"{path.name}.*.bak"
    existing = sorted(history_dir.glob(pattern))
    for old in existing[:-_BACKUP_LIMIT]:
        try:
            old.unlink()
        except OSError:
            pass


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
    _backup_config(path)
    LocalStorageProvider().write_text(str(path), json.dumps(normalized, indent=2) + "\n")
    return normalized
