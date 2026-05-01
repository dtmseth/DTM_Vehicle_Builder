from __future__ import annotations

import base64
import os
import subprocess
import sys
import traceback
from pathlib import Path

from ...generator import generate_build_sheet
from ...input_reader import load_input
from ...paths import AppPaths


def save_xlsx_bytes(body: dict, paths: AppPaths) -> Path:
    raw = base64.b64decode(body["data"])
    fname = Path(body.get("filename", "upload.xlsx")).name
    dest = paths.workspace_input_dir / fname
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def handle_status(paths: AppPaths) -> dict:
    for workbook in sorted(paths.workspace_input_dir.glob("*.xlsx")):
        if "template" not in workbook.name.lower():
            return {"ok": True, "existing_file": workbook.name}
    return {"ok": True, "existing_file": None}


def parse_workbook(body: dict, paths: AppPaths) -> dict:
    try:
        path = save_xlsx_bytes(body, paths)
        project = load_input(path)

        # Auto-create a draft so the UI can request a preview and save overrides
        from ...inputs.project_drafts import draft_from_project_input, save_draft
        draft = draft_from_project_input(project)
        save_draft(draft, paths.workspace_drafts_dir)

        return {
            "ok": True,
            "draft_id": draft.draft_id,
            "info": project.info,
            "parts": [
                {
                    "name": p.name,
                    "location": p.location,
                    "color": p.raw_color,
                    "qty": p.quantity,
                    "include": p.include,
                }
                for p in project.parts
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def generate_build_sheet_handler(body: dict, paths: AppPaths) -> dict:
    log_lines: list[str] = []
    try:
        path = save_xlsx_bytes(body, paths)
        log_lines.append(f"Reading: {path.name}")
        project = load_input(path)
        log_lines.append(f"Vehicle type: {project.info.get('VehicleType', '?')}")
        log_lines.append(f"Parts found: {len(project.parts)}")
        result = generate_build_sheet(path, paths)
        log_lines.append(f"Wrote: {result.ppt_path.name}")
        return {
            "ok": True,
            "output_name": result.ppt_path.name,
            "output_path": str(result.ppt_path),
            "plan_path": str(result.plan_path),
            "summary_path": str(result.summary_path),
            "parts_count": result.parts_count,
            "placements_count": result.placements_count,
            "warnings_count": len(result.warnings),
            "all_warnings": result.warnings,
            "log": "\n".join(log_lines),
        }
    except Exception as exc:
        log_lines.extend(["ERROR: " + str(exc), traceback.format_exc()])
        return {"ok": False, "error": str(exc), "log": "\n".join(log_lines)}
