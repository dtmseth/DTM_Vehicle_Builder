from __future__ import annotations

import base64
import re
import shutil
import traceback
from pathlib import Path

from ...config.store import load_config
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
    """Returns the user-configured export directory, or None to use the workspace default."""
    settings = load_config("app_settings.json", paths) or {}
    save_dir = settings.get("output_save_dir", "").strip()
    if save_dir and Path(save_dir).is_dir():
        return Path(save_dir)
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
    Copy ppt_path to the configured export directory (if set).
    project_export_dir takes priority over the global output_save_dir setting.
    Returns {output_path, output_name, previous_versions}.
    No conflict logic — the timestamp in the filename ensures uniqueness.

    In cloud mode (and only when ``exports_library_name`` is configured),
    the final PPTX is also auto-uploaded to a SharePoint folder on the
    company's separate library — in the background, so the response returns
    immediately. agency / year drive the {library}/{base}/{agency}/{year}/
    layout. Missing values get sanitized to "Unassigned" upstream.
    """
    export_dir = project_export_dir if (project_export_dir and project_export_dir.is_dir()) else get_output_save_dir(paths)
    if export_dir is None:
        result_path = ppt_path
        result = {
            "output_path": str(ppt_path),
            "output_name": ppt_path.name,
            "previous_versions": [],
        }
    else:
        export_dir.mkdir(parents=True, exist_ok=True)
        dest = export_dir / ppt_path.name
        shutil.copy2(ppt_path, dest)
        previous = _find_previous_versions(dest, export_dir)
        result_path = dest
        result = {
            "output_path": str(dest),
            "output_name": dest.name,
            "previous_versions": previous,
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

    export_dir = get_output_save_dir(paths)
    if export_dir is None:
        return {"ok": False, "error": "No export directory configured"}

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
