from __future__ import annotations

import logging
import traceback

_log = logging.getLogger(__name__)

from ...generator import generate_build_sheet
from ...inputs.project_drafts import (
    BuildDraft,
    DraftPart,
    delete_draft,
    draft_from_project_input,
    draft_part_from_payload,
    draft_summary,
    draft_to_project_input,
    find_part_by_line_id,
    list_drafts,
    load_draft,
    new_draft,
    save_draft,
)
from ...naming import safe_id
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
    An empty override dict removes that key (treated as a reset).
    """
    try:
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        key = body.get("key", "")
        override = body.get("override", {})
        if not key:
            return {"ok": False, "error": "key required"}
        if override:
            draft.placement_overrides[key] = override
            draft.user_modified = True
        else:
            draft.placement_overrides.pop(key, None)
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "key": key}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_overrides_batch(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Save multiple placement overrides atomically.

    Body: {"overrides": {"key1": {...}, "key2": {...}}}
    Empty dict value for a key removes that override (treated as a reset).
    Sets user_modified when at least one non-empty override is written.
    """
    try:
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        overrides = body.get("overrides", {})
        if not isinstance(overrides, dict):
            return {"ok": False, "error": "overrides must be a dict"}
        has_real_change = False
        for key, value in overrides.items():
            if value:
                draft.placement_overrides[key] = value
                has_real_change = True
            else:
                draft.placement_overrides.pop(key, None)
        if has_real_change:
            draft.user_modified = True
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "count": len(overrides)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_add_part_to_draft(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Append a new part to the draft's parts list."""
    try:
        clean_id = safe_id(draft_id)
        if not clean_id or clean_id != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        if not body.get("name", "").strip():
            return {"ok": False, "error": "name is required"}
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        part = draft_part_from_payload(body, paths)
        draft.parts.append(part)
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "part_added",
            "line_id": part.line_id,
            "name": part.name,
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "line_id": part.line_id, "draft_summary": draft_summary(draft)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_update_part_in_draft(draft_id: str, line_id: str, body: dict, paths: AppPaths) -> dict:
    """Merge updated fields onto an existing part identified by line_id."""
    try:
        clean_draft_id = safe_id(draft_id)
        if not clean_draft_id or clean_draft_id != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        clean_line_id = safe_id(line_id)
        if not clean_line_id or clean_line_id != line_id:
            return {"ok": False, "error": "invalid line_id"}
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        result = find_part_by_line_id(draft, line_id)
        if result is None:
            return {"ok": False, "error": f"Part not found: {line_id}"}
        idx, existing = result
        # Build a merged body: existing fields, overridden by incoming body
        from dataclasses import asdict
        merged = asdict(existing)
        merged.update({k: v for k, v in body.items() if k != "line_id"})
        merged["line_id"] = line_id
        draft.parts[idx] = draft_part_from_payload(merged, paths)
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "part_updated",
            "line_id": line_id,
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "line_id": line_id, "draft_summary": draft_summary(draft)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_remove_part_from_draft(draft_id: str, line_id: str, paths: AppPaths) -> dict:
    """Remove the part with the given line_id from the draft."""
    try:
        clean_draft_id = safe_id(draft_id)
        if not clean_draft_id or clean_draft_id != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        clean_line_id = safe_id(line_id)
        if not clean_line_id or clean_line_id != line_id:
            return {"ok": False, "error": "invalid line_id"}
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        result = find_part_by_line_id(draft, line_id)
        if result is None:
            return {"ok": False, "error": f"Part not found: {line_id}"}
        idx, removed = result
        draft.parts.pop(idx)
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "part_removed",
            "line_id": line_id,
            "name": removed.name,
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "line_id": line_id, "draft_summary": draft_summary(draft)}
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

        # Resolve project-level export directory from project_output_root setting.
        # Falls through to legacy output_save_dir handled by finalize_output().
        _project_export_dir = None
        _proj_id_param = body.get("project_id", "")
        if _proj_id_param:
            try:
                from ...inputs.project_entry import load_project
                from ...inputs.project_dirs import ensure_project_output_dir
                from ...config.store import load_config
                _proj_rec = load_project(_proj_id_param, paths)

                # Freshen UNIT ID, YEAR, and BuildType from the current project
                # data so values set after draft creation are reflected in output.
                for _bu in _proj_rec.build_units:
                    for _idx, _ind in enumerate(_bu.individuals):
                        if _ind.draft_id == draft_id:
                            _nv = dict(project.info.get("NewVehicle") or {})
                            _nv["UNIT ID"] = _ind.unit_number or f"Unit-{_idx + 1}"
                            _ind_year = _ind.year or _proj_rec.customer.build_year or ""
                            if _ind_year:
                                _nv["YEAR"] = _ind_year
                            project.info["NewVehicle"] = _nv
                            project.info["BuildType"] = _bu.build_type or project.info.get("BuildType", "")
                            break

                _settings = load_config("app_settings.json", paths) or {}
                _root = _settings.get("project_output_root", "").strip()
                if _root:
                    _agency = (_proj_rec.customer.agency or "").strip()
                    _year = (_proj_rec.customer.build_year or "").strip()
                    _project_export_dir = ensure_project_output_dir(
                        _root, _agency, _year
                    )
            except Exception:
                _log.exception("Could not resolve project export dir for draft %s", draft_id)

        # generate_build_sheet expects a Path to an xlsx — for GUI-built drafts
        # we don't have one, so we generate from the ProjectInput directly via
        # the planning + rendering pipeline.
        import json
        from ...config.loader import load_configs
        from ...planning.planner import build_plan
        from ...planning.override_applier import apply_overrides
        from ...render_ppt import render_plan_to_ppt
        from ...reporting import render_markdown_summary
        from ...storage.local import LocalStorageProvider

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

        storage = LocalStorageProvider()
        storage.write_text(str(plan_path), json.dumps(plan.to_dict(), indent=2))
        storage.write_text(str(summary_path), render_markdown_summary(plan))

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
        import re as _re
        from pathlib import Path as _Path
        # Pull agency + year off the project record for the SharePoint
        # auto-upload's folder layout. _agency/_year were computed above
        # for the local export-dir path; reuse them so the cloud upload
        # lands at the same {agency}/{year}/ shape as the local copy.
        export = finalize_output(
            ppt_path,
            paths,
            project_export_dir=_project_export_dir,
            agency=_agency or project.info.get("Agency", ""),
            year=_year or project.info.get("BuildYear", "") or _ind_year,
        )

        # Detect rename: if the caller supplied the previous output path and the
        # stable filename prefix (everything before the timestamp) has changed,
        # the old file is now an orphan.  Return it so the UI can prompt the user.
        _ts_pat = _re.compile(r'_[A-Z][a-z]{2}\d+_\d{4}_\d+-\d+-\d+[AP]M$')
        _existing_path_str = body.get("existing_output_path", "")
        name_changed: dict | None = None
        if _existing_path_str:
            _old = _Path(_existing_path_str)
            _new = _Path(export["output_path"])
            _old_prefix = _ts_pat.sub("", _old.stem)
            _new_prefix = _ts_pat.sub("", _new.stem)
            if _old_prefix != _new_prefix and _old.exists():
                name_changed = {
                    "old_path": str(_old),
                    "old_name": _old.name,
                    "new_path": export["output_path"],
                    "new_name": export["output_name"],
                }

        result: dict = {
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
        if name_changed:
            result["name_changed"] = name_changed
        return result
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "log": "\n".join(log_lines)}
    except Exception as exc:
        log_lines.extend(["ERROR: " + str(exc), traceback.format_exc()])
        return {"ok": False, "error": str(exc), "log": "\n".join(log_lines)}
