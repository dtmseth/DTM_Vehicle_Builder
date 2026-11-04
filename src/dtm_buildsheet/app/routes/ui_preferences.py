from __future__ import annotations

from ...paths import AppPaths
from ..services import ui_preferences_service


def get_preferences(paths: AppPaths) -> dict:
    return ui_preferences_service.load_preferences(paths)


def save_theme(body: dict, paths: AppPaths) -> dict:
    return ui_preferences_service.save_theme((body or {}).get("theme"), paths)
