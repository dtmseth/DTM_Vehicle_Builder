from __future__ import annotations

import threading

from ...config.store import get_config_path, load_config, save_config
from ...paths import AppPaths

# Saving any of these files automatically triggers template regeneration.
TEMPLATE_REGEN_FILES = {
    "part_catalog.json",
    "vehicle_layouts.json",
    "parts_library.json",
    "workbook_rules.json",
}


def load_config_file(filename: str, paths: AppPaths) -> dict:
    return load_config(filename, paths)


def save_config_file(filename: str, data: object, paths: AppPaths) -> dict:
    try:
        normalized = save_config(filename, data, paths)
        result: dict = {
            "ok": True,
            "path": str(get_config_path(filename, paths)),
            "schema_version": normalized.get("schema_version", 1),
        }
        if filename in TEMPLATE_REGEN_FILES:
            # Trigger template regeneration as a background side-effect so the
            # save response returns immediately and the template stays in sync.
            from .template_service import generate_template
            threading.Thread(target=generate_template, args=(paths,), daemon=True).start()
            result["template_regen"] = "triggered"
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
