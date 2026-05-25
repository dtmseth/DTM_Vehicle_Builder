from __future__ import annotations

import json
import threading

from ...config.store import get_config_path, load_config, save_config
from ...paths import AppPaths
from ..adapters.interfaces import ProposalCategory
from ..adapters.wiring import save_via_proposal

# Saving any of these files automatically triggers template regeneration.
TEMPLATE_REGEN_FILES = {
    "part_catalog.json",
    "vehicle_layouts.json",
    "parts_library.json",
    "workbook_rules.json",
}

# Phase 2-β two-tier review policy. Maps a config filename to the review
# category. Files not in this map save locally only — no proposal is
# submitted. app_settings.json and project_options.json are intentionally
# left out: the former is per-user UI state, the latter is the wizard
# dropdowns that the user explicitly asked to keep local for now.
CONFIG_PROPOSAL_CATEGORY: dict[str, ProposalCategory] = {
    "vehicle_layouts.json": "advanced",
    "build_rules.json": "advanced",
    "part_catalog.json": "advanced",
    "parts_library.json": "advanced",
    "workbook_rules.json": "advanced",
    "asset_manifest.json": "advanced",
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

        category = CONFIG_PROPOSAL_CATEGORY.get(filename)
        if category is not None:
            proposal_result = save_via_proposal(
                target_file=filename,
                serialized_content=json.dumps(normalized, indent=2) + "\n",
                summary=f"Update {filename}",
                category=category,
            )
            result.update(proposal_result)
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
