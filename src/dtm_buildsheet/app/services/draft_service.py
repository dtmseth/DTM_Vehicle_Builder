from __future__ import annotations

import traceback

from ...generator import generate_build_sheet
from ...inputs.project_drafts import (
    BuildDraft,
    DraftPart,
    delete_draft,
    draft_from_project_input,
    draft_summary,
    draft_to_project_input,
    list_drafts,
    load_draft,
    new_draft,
    save_draft,
)
from ...paths import AppPaths


def handle_list_drafts(paths: AppPaths) -> dict:
    drafts = list_drafts(paths.workspace_drafts_dir)
    return {"ok": True, "drafts": [draft_summary(d) for d in drafts]}


def handle_get_draft(draft_id: str, paths: AppPaths) -> dict:
    try:
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        from dataclasses import asdict
        return {"ok": True, "draft": asdict(draft)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_draft(body: dict, paths: AppPaths) -> dict:
    try:
        draft_id = body.get("draft_id")
        if draft_id:
            try:
                draft = load_draft(draft_id, paths.workspace_drafts_dir)
            except FileNotFoundError:
                draft = new_draft()
                draft.draft_id = draft_id
        else:
            draft = new_draft()

        draft.vehicle_info = body.get("vehicle_info", draft.vehicle_info)
        draft.notes = body.get("notes", draft.notes)
        draft.placement_overrides = body.get("placement_overrides", draft.placement_overrides)
        draft.validation_messages = body.get("validation_messages", draft.validation_messages)

        if "parts" in body:
            draft.parts = [DraftPart(**p) for p in body["parts"]]

        if "audit_entry" in body:
            draft.audit_trail.append(body["audit_entry"])

        path = save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft.draft_id, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_delete_draft(draft_id: str, paths: AppPaths) -> dict:
    try:
        delete_draft(draft_id, paths.workspace_drafts_dir)
        return {"ok": True}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_override(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Merge a single placement override into draft.placement_overrides.

    Body: {"key": "{part_id}:{view}", "override": {visible, rotation, ...}}
    """
    try:
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        key = body.get("key", "")
        override = body.get("override", {})
        if not key:
            return {"ok": False, "error": "key required"}
        draft.placement_overrides[key] = override
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "key": key}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_overrides_batch(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Save multiple placement overrides atomically.

    Body: {"overrides": {"key1": {...}, "key2": {...}}}
    Empty dict value for a key clears that override.
    """
    try:
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        overrides = body.get("overrides", {})
        if not isinstance(overrides, dict):
            return {"ok": False, "error": "overrides must be a dict"}
        draft.placement_overrides.update(overrides)
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "count": len(overrides)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_generate_from_draft(body: dict, paths: AppPaths) -> dict:
    log_lines: list[str] = []
    try:
        draft_id = body.get("draft_id", "")
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        project = draft_to_project_input(draft)
        log_lines.append(f"Draft: {draft_id}")
        log_lines.append(f"Vehicle type: {project.info.get('VehicleType', '?')}")
        log_lines.append(f"Parts: {len(project.parts)}")

        # generate_build_sheet expects a Path to an xlsx — for GUI-built drafts
        # we don't have one, so we generate from the ProjectInput directly via
        # the planning + rendering pipeline.
        import json
        from ...config.loader import load_configs
        from ...planning.planner import build_plan
        from ...planning.override_applier import apply_overrides
        from ...render_ppt import render_plan_to_ppt
        from ...reporting import render_markdown_summary

        config = load_configs(paths)
        plan = build_plan(project, config)

        if draft.placement_overrides:
            plan = apply_overrides(plan, draft.placement_overrides)
            log_lines.append(f"Applied {len(draft.placement_overrides)} placement override(s).")

        project_id = project.info.get("ProjectID", "DRAFT")
        out_dir = paths.workspace_output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        ppt_path = render_plan_to_ppt(plan, paths)
        plan_path = out_dir / f"BuildPlan_{project_id}.json"
        summary_path = out_dir / f"BuildSummary_{project_id}.md"

        plan_path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
        summary_path.write_text(render_markdown_summary(plan), encoding="utf-8")

        placements_count = sum(len(pp.placements) for pp in plan.planned_parts)
        log_lines.append(f"Wrote: {ppt_path.name}")

        all_warnings: list[str] = list(plan.warnings)
        for pp in plan.planned_parts:
            all_warnings.extend(pp.warnings)
            for pl in pp.placements:
                all_warnings.extend(pl.warnings)
                for inst in pl.instances:
                    all_warnings.extend(inst.warnings)

        from .generation_service import finalize_output
        export = finalize_output(ppt_path, paths)

        return {
            "ok": True,
            "output_name": export["output_name"],
            "output_path": export["output_path"],
            "previous_versions": export["previous_versions"],
            "plan_path": str(plan_path),
            "summary_path": str(summary_path),
            "parts_count": len(plan.planned_parts),
            "placements_count": placements_count,
            "warnings_count": len(all_warnings),
            "all_warnings": all_warnings,
            "log": "\n".join(log_lines),
        }
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "log": "\n".join(log_lines)}
    except Exception as exc:
        log_lines.extend(["ERROR: " + str(exc), traceback.format_exc()])
        return {"ok": False, "error": str(exc), "log": "\n".join(log_lines)}
