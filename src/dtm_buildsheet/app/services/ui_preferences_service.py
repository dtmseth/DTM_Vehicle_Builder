"""Durable, machine-local UI preferences that survive app updates."""

from __future__ import annotations

import json
from pathlib import Path

from ...paths import AppPaths
from ...storage.local import LocalStorageProvider

_FILENAME = "ui_preferences.json"
_VALID_THEMES = {"light", "dark"}


def _path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _FILENAME


def load_preferences(paths: AppPaths) -> dict:
    """Return local preferences without creating or seeding a shared file."""

    path = _path(paths)
    if not path.is_file():
        return {"ok": True, "theme": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"ok": True, "theme": ""}
    theme = str(payload.get("theme") or "").strip().lower() if isinstance(payload, dict) else ""
    return {"ok": True, "theme": theme if theme in _VALID_THEMES else ""}


def save_theme(theme: object, paths: AppPaths) -> dict:
    """Persist one validated theme in the OS user's application-data folder."""

    normalized = str(theme or "").strip().lower()
    if normalized not in _VALID_THEMES:
        return {"ok": False, "error": "Theme must be light or dark."}
    payload = {"schema_version": 1, "theme": normalized}
    try:
        LocalStorageProvider().write_text(
            str(_path(paths)),
            json.dumps(payload, indent=2) + "\n",
        )
    except OSError:
        return {"ok": False, "error": "Theme preference could not be saved."}
    return {"ok": True, "theme": normalized}
