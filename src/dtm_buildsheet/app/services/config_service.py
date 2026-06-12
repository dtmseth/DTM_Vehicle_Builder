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

# Per-file review category. All entries below are "general" → auto-merged
# in the dtm-shared-settings publish workflow. The "advanced" category
# existed before 2026-06-11 and required manual PR review; owner removed
# it because no one else touches these files and the PR-cron delay hurt
# iteration. Audit trail is still produced (the proposal still fires),
# but propagation no longer waits on the publish workflow — direct-mirror
# below handles within-60s sync to every device.
#
# Files not in this map save locally only. app_settings.json is per-user
# UI state; project_options.json is kept local by owner preference.
CONFIG_PROPOSAL_CATEGORY: dict[str, ProposalCategory] = {
    "vehicle_layouts.json":         "general",
    "build_rules.json":             "general",
    "part_catalog.json":            "general",
    "parts_library.json":           "general",
    "workbook_rules.json":          "general",
    "asset_manifest.json":          "general",
    "parts_db.json":                "general",
    "legacy_workbook_index.json":   "general",
}

# Files that also direct-mirror to SharePoint /Settings/ on save, alongside
# the proposal pipeline. Mirrors the per-record entity pattern (agencies,
# sales_reps, presets) — proposal is the audit trail, direct-mirror is
# the fast cross-device propagation. Together they bound the latency at
# the 60s sync interval rather than the cron-throttled publish workflow.
_DIRECT_MIRROR_FILES = {
    "vehicle_layouts.json",
    "build_rules.json",
    "part_catalog.json",
    "parts_library.json",
    "workbook_rules.json",
    "asset_manifest.json",
    "parts_db.json",
    "legacy_workbook_index.json",
}


def load_config_file(filename: str, paths: AppPaths) -> dict:
    return load_config(filename, paths)


def save_config_file(filename: str, data: object, paths: AppPaths) -> dict:
    try:
        normalized = save_config(filename, data, paths)
        serialized = json.dumps(normalized, indent=2) + "\n"
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
                serialized_content=serialized,
                summary=f"Update {filename}",
                category=category,
            )
            result.update(proposal_result)

        # Direct-mirror to SharePoint /Settings/ for the fast-propagation set.
        # Fire-and-forget; the response returns without waiting on Graph.
        if filename in _DIRECT_MIRROR_FILES:
            from .shared_work_service import save_setting_to_cloud_in_background
            save_setting_to_cloud_in_background(filename, serialized)

        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
