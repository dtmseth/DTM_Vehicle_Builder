from __future__ import annotations

import base64
import re
import traceback
from pathlib import Path

from ...generator import generate_build_sheet
from ...input_reader import load_input
from ...paths import AppPaths
from ...storage.local import LocalStorageProvider


def save_xlsx_bytes(body: dict, paths: AppPaths) -> Path:
    raw = base64.b64decode(body["data"])
    fname = Path(body.get("filename", "upload.xlsx")).name  # basename only
    dest = paths.workspace_input_dir / fname
    LocalStorageProvider().write_bytes(str(dest), raw)
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


def get_output_save_dir(paths: AppPaths) -> Path | None:
    """Legacy compatibility hook.

    Generated build sheets now stay in the app workspace output directory.
    SharePoint distribution is handled by exports_upload_service after the
    local write succeeds, so user-configured export folders are ignored.
    """
    return None


def _find_previous_versions(ppt_path: Path, export_dir: Path) -> list[str]:
    """Find older exports with the same Agency_Unit_Year_Updated_ prefix."""
    # Filename pattern: Agency_Unit_Year_Updated_Mmm DD_YYYY_H-MMAM.pptx
    # Strip the _Mmm DD_YYYY_... timestamp suffix to get the stable prefix
    prefix = re.sub(r'_[A-Z][a-z]{2}\d+_\d{4}_\d+-\d+-\d+[AP]M$', '', ppt_path.stem) + '_'
    return [
        str(p) for p in sorted(export_dir.glob(f"{prefix}*.pptx"))
        if p.name != ppt_path.name
    ]


def finalize_output(
    ppt_path: Path,
    paths: AppPaths,
    project_export_dir: Path | None = None,
    *,
    agency: str = "",
    year: str = "",
) -> dict:
    """
    Keep ppt_path in the app workspace output directory.
    Returns {output_path, output_name, previous_versions}.
    No conflict logic — the timestamp in the filename ensures uniqueness.

    In cloud mode (and only when ``exports_library_name`` is configured),
    the final PPTX is also auto-uploaded to a SharePoint folder on the
    company's separate library — in the background, so the response returns
    immediately. agency / year drive the {library}/{base}/{agency}/{year}/
    layout. Missing values get sanitized to "Unassigned" upstream.
    """
    result_path = ppt_path
    result = {
        "output_path": str(ppt_path),
        "output_name": ppt_path.name,
        "previous_versions": _find_previous_versions(ppt_path, ppt_path.parent),
    }

    # Fire the SharePoint auto-upload from the canonical final path. The
    # service is a no-op outside cloud mode and when exports aren't
    # configured, so callers without agency/year context still get correct
    # local-only behavior.
    try:
        from .exports_upload_service import upload_export_in_background
        from .. import server as _server

        def _on_complete(ok: bool) -> None:
            if ok:
                # Same data_version counter the UI watches for sync changes —
                # bump it so the cloud chip refreshes and tells the user the
                # upload finished.
                try:
                    _server._bump_data_version()  # noqa: SLF001
                except Exception:
                    pass

        upload_export_in_background(
            result_path,
            agency=agency,
            year=year,
            on_complete=_on_complete,
        )
    except Exception:
        # Don't let the auto-upload setup affect the local-write contract.
        pass

    return result


def handle_delete_old(body: dict, paths: AppPaths) -> dict:
    """
    POST /api/generate/delete-old — delete a list of previous-version pptx files.
    Only allows deleting files inside the configured export directory.
    """
    file_paths: list[str] = body.get("paths", [])
    if not file_paths:
        return {"ok": False, "error": "No paths provided"}

    export_dir = paths.workspace_output_dir

    deleted, errors = [], []
    for fp in file_paths:
        p = Path(fp)
        try:
            # Safety: only delete files that live inside the configured export dir
            p.resolve().relative_to(export_dir.resolve())
        except ValueError:
            errors.append(f"{p.name}: not in export folder")
            continue
        if p.exists():
            p.unlink()
            deleted.append(p.name)
        else:
            errors.append(f"{p.name}: not found")

    return {"ok": True, "deleted": deleted, "errors": errors}


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

        # Standalone Tools tab — no ProjectRecord context, but the parsed
        # workbook carries Agency / BuildYear that we can use for the
        # SharePoint upload folder layout. Falls back to "Unassigned" inside
        # the uploader when missing.
        export = finalize_output(
            result.ppt_path, paths,
            agency=str(project.info.get("Agency", "")),
            year=str(project.info.get("BuildYear", "")),
        )

        return {
            "ok": True,
            "output_name": export["output_name"],
            "output_path": export["output_path"],
            "previous_versions": export["previous_versions"],
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
