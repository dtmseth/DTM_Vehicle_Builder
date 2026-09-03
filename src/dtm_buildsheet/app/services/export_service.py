from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from ...paths import AppPaths
from ...storage.safety import assert_within_root

_log = logging.getLogger(__name__)


def _find_previous_pdf_versions(pdf_path: Path) -> list[str]:
    """Find older PDF exports with the same stable vehicle identity."""
    from .exports_upload_service import stable_export_stem

    stable_stem = stable_export_stem(pdf_path.name)
    return [
        str(p) for p in sorted(pdf_path.parent.glob("*.pdf"))
        if p.name != pdf_path.name and stable_export_stem(p.name) == stable_stem
    ]


def _stamp_export_on_project(
    body: dict, pdf_path: Path, paths: AppPaths | None,
) -> dict | None:
    """Update the project record with the PDF path + author + timestamp.

    No-op when the body doesn't include enough context (project_id +
    unit_id) or when the project can't be loaded. The UI sends the IDs
    along with the export call now so this hook stays in one place
    instead of leaking another /api/project/save round-trip into the UI.
    """
    if paths is None:
        return None
    project_id = str(body.get("project_id", "") or "").strip()
    unit_id = str(body.get("unit_id", "") or "").strip()
    individual_id = str(body.get("individual_id", "") or "").strip()
    if not project_id or not unit_id:
        return None
    try:
        from datetime import datetime, timezone
        from ...inputs.project_entry import load_project, save_project
        from .draft_service import _current_user_display_name
        project = load_project(project_id, paths)
        now = datetime.now(timezone.utc).isoformat()
        by = _current_user_display_name()
        shop_republish = None
        for bu in project.build_units:
            if bu.unit_id != unit_id:
                continue
            if individual_id:
                for ind in bu.individuals or []:
                    if ind.individual_id == individual_id:
                        if ind.status == "finalized" and ind.shop_pdf_item_id:
                            shop_republish = {
                                "required": True,
                                "project_id": project_id,
                                "unit_id": unit_id,
                                "individual_id": individual_id,
                                "current_shop_pdf_path": ind.shop_pdf_path,
                            }
                        ind.pdf_path = str(pdf_path)
                        ind.last_exported_at = now
                        ind.last_exported_by = by
                        from .company_vehicle_folder_service import company_vehicle_folders_configured
                        if company_vehicle_folders_configured():
                            ind.company_publication_status = "pending"
                            ind.company_publication_error = ""
                        break
            else:
                bu.pdf_path = str(pdf_path)
                bu.last_exported_at = now
                bu.last_exported_by = by
            break
        save_project(project, paths)
        return shop_republish
    except Exception:
        _log.exception("Could not stamp PDF metadata on project %s", project_id)
        return None


def _maybe_upload_pdf(pdf_path: Path, body: dict) -> None:
    """Queue a SharePoint export upload for PDFs when agency/year context exists."""
    agency = str(body.get("agency", "") or "")
    year = str(body.get("year", "") or "")
    if not agency and not year:
        return
    try:
        from .company_vehicle_folder_service import company_vehicle_folders_configured
        if company_vehicle_folders_configured():
            # Cutover is exclusive: never split a new PDF between the legacy
            # root and Vehicle Project Database.
            return
        from .exports_upload_service import upload_export_in_background
        upload_export_in_background(
            pdf_path, agency=agency, year=year,
            canonicalize=body.get("preserve_sharepoint_version") is not True,
        )
    except Exception:
        pass


def _finish_pdf_export(result: dict, pdf_path: Path, body: dict, paths: AppPaths | None) -> dict:
    """Upload/stamp a completed PDF and apply explicit version cleanup."""
    from .pdf_reference_links import add_build_reference_links
    link_result = add_build_reference_links(pdf_path, body, paths)
    result["reference_links_added"] = link_result.get("links_added", 0)
    if not link_result.get("ok"):
        result["reference_links_error"] = link_result.get("error", "reference_link_annotation_failed")
    if link_result.get("reference_errors"):
        result["reference_photo_errors"] = link_result["reference_errors"]
    _maybe_upload_pdf(pdf_path, body)
    shop_republish = _stamp_export_on_project(body, pdf_path, paths)
    if shop_republish:
        result["shop_republish"] = shop_republish
    if paths is not None:
        try:
            from .company_vehicle_folder_service import schedule_company_vehicle_pdf
            schedule_company_vehicle_pdf(
                str(body.get("project_id") or ""),
                str(body.get("unit_id") or ""),
                str(body.get("individual_id") or ""),
                paths,
            )
        except Exception:
            _log.exception("Could not schedule Company vehicle PDF publication")
    if body.get("replace_previous_exports") and paths is not None:
        try:
            from .exports_upload_service import cleanup_previous_exports
            result["cleanup"] = cleanup_previous_exports(
                paths,
                agency=str(body.get("agency", "") or ""),
                year=str(body.get("year", "") or ""),
                filenames=[
                    str(value or "") for value in body.get("previous_export_paths", [])
                    if str(value or "").strip()
                ],
                keep_filenames=[str(body.get("output_path", "") or ""), pdf_path.name],
            )
        except Exception:
            _log.exception("Could not clean up previous PDF export versions")
            result["cleanup"] = {"ok": False, "errors": ["shared_export_delete_failed"]}
    return result


# ── LibreOffice discovery ──────────────────────────────────────────────────────

_SOFFICE_CANDIDATES = [
    # macOS default install
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    # Homebrew (Intel + Apple Silicon)
    "/usr/local/bin/soffice",
    "/opt/homebrew/bin/soffice",
    # Linux
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    # Windows
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def _find_soffice() -> str | None:
    """Return the first usable soffice binary, or None."""
    for candidate in _SOFFICE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    # Also check PATH
    import shutil
    return shutil.which("soffice") or shutil.which("libreoffice")


# ── PowerPoint COM (Windows only) ─────────────────────────────────────────────

def _export_via_powerpoint_com(pptx_path: Path, pdf_path: Path) -> dict:
    t0 = time.monotonic()
    def _step(label: str, started: float) -> float:
        now = time.monotonic()
        _log.info("PPT-COM %s took %.2fs", label, now - started)
        return now
    try:
        import comtypes.client  # type: ignore[import]
        t = _step("import", t0)
        powerpoint = comtypes.client.CreateObject("Powerpoint.Application")
        t = _step("CreateObject", t)
        powerpoint.Visible = 1
        prs = powerpoint.Presentations.Open(str(pptx_path))
        t = _step(f"Presentations.Open({pptx_path.name})", t)
        prs.SaveAs(str(pdf_path), 32)  # 32 = ppSaveAsPDF
        t = _step("SaveAs(PDF)", t)
        prs.Close()
        t = _step("Close", t)
        powerpoint.Quit()
        _step("Quit", t)
        _log.info("PPT-COM total %.2fs for %s", time.monotonic() - t0, pptx_path.name)
        if pdf_path.exists():
            return {"ok": True, "pdf_path": str(pdf_path), "pdf_name": pdf_path.name,
                    "previous_versions": _find_previous_pdf_versions(pdf_path)}
        return {"ok": False, "error": "PDF not created by PowerPoint COM"}
    except Exception as exc:
        _log.exception("PPT-COM failed after %.2fs", time.monotonic() - t0)
        return {"ok": False, "error": f"PowerPoint COM failed: {exc}"}


# ── PowerPoint AppleScript (macOS only) ──────────────────────────────────────

def _export_via_applescript(pptx_path: Path, pdf_path: Path) -> dict:
    """Use Microsoft PowerPoint on macOS via osascript to save as PDF."""
    script = f"""
tell application "Microsoft PowerPoint"
    set wasRunning to (count of presentations) > 0
    open POSIX file "{pptx_path}"
    set thePresentation to active presentation
    save thePresentation in POSIX file "{pdf_path}" as save as PDF
    close thePresentation saving no
end tell
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=120,
        )
        if result.returncode == 0 and pdf_path.exists():
            return {"ok": True, "pdf_path": str(pdf_path), "pdf_name": pdf_path.name,
                    "previous_versions": _find_previous_pdf_versions(pdf_path)}
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        msg = stderr or stdout or "AppleScript returned non-zero exit code"
        # Normalise "not installed" signals so the caller can fall through gracefully
        if "not find" in msg.lower() or "microsoft powerpoint" in msg.lower():
            return {"ok": False, "error": f"Microsoft PowerPoint not installed: {msg}"}
        return {"ok": False, "error": f"AppleScript PDF export failed: {msg}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Microsoft PowerPoint timed out during PDF export"}
    except FileNotFoundError:
        return {"ok": False, "error": "osascript not found — not installed"}
    except Exception as exc:
        return {"ok": False, "error": f"AppleScript error: {exc}"}


# ── Public API ────────────────────────────────────────────────────────────────

def _allowed_roots(paths: AppPaths | None, extra_roots: list[Path] | None = None) -> list[Path]:
    """Return the list of directory roots that open/export operations may target."""
    if paths is None:
        return []
    roots = [paths.workspace_output_dir]
    from ...app.services.generation_service import get_output_save_dir
    export_dir = get_output_save_dir(paths)
    if export_dir is not None:
        roots.append(export_dir)
    if extra_roots:
        roots.extend(extra_roots)
    return roots


def _check_allowed(path: Path, roots: list[Path]) -> str | None:
    """Return an error message if *path* is not inside any of *roots*, else None."""
    if not roots:
        return None  # no workspace context — skip check (e.g. tests)
    for root in roots:
        try:
            assert_within_root(path, root)
            return None
        except ValueError:
            continue
    return f"Access denied: '{path.name}' is outside allowed output directories"


def export_to_pdf(body: dict, paths: AppPaths | None = None) -> dict:
    """Convert an existing PPTX file to PDF.

    Tries LibreOffice first (cross-platform), then PowerPoint COM on Windows.
    Returns {"ok": True, "pdf_path": ..., "pdf_name": ...} or {"ok": False, "error": ...}.
    """
    _t_export_start = time.monotonic()
    pptx_path_str = body.get("output_path", "")
    if not pptx_path_str:
        return {"ok": False, "error": "output_path is required"}

    if paths is not None:
        project_id = str(body.get("project_id") or "").strip()
        unit_id = str(body.get("unit_id") or "").strip()
        individual_id = str(body.get("individual_id") or "").strip()
        if project_id and unit_id and individual_id:
            try:
                from ...domain.vehicle_naming import vehicle_identity_ready
                from ...inputs.project_entry import load_project
                project = load_project(project_id, paths)
                build_unit = next(item for item in project.build_units if item.unit_id == unit_id)
                individual = next(
                    item for item in build_unit.individuals
                    if item.individual_id == individual_id
                )
            except (FileNotFoundError, StopIteration):
                return {"ok": False, "error": "vehicle_not_found"}
            if not vehicle_identity_ready(individual):
                return {
                    "ok": False,
                    "error": "vehicle_identifier_required",
                    "message": "Add a unit number or VIN before exporting this vehicle.",
                }

    pptx_path = Path(pptx_path_str)
    _log.info("export_to_pdf start: %s", pptx_path)
    if not pptx_path.exists() and paths is not None:
        agency = str(body.get("agency", "") or "").strip()
        year = str(body.get("year", "") or "").strip()
        if agency or year:
            from .exports_upload_service import download_export
            hydrated = download_export(
                paths, source_path=pptx_path_str, agency=agency, year=year,
            )
            if hydrated.get("ok"):
                pptx_path = Path(hydrated["path"])
            else:
                return hydrated
    if not pptx_path.exists():
        return {"ok": False, "error": f"PPTX file not found: {pptx_path.name}"}
    if pptx_path.suffix.lower() != ".pptx":
        return {"ok": False, "error": "output_path must point to a .pptx file"}

    # Allow the actual pptx parent dir (covers project-specific export dirs)
    err = _check_allowed(pptx_path, _allowed_roots(paths, extra_roots=[pptx_path.parent]))
    if err:
        return {"ok": False, "error": err}

    pdf_path = pptx_path.with_suffix(".pdf")

    # 1. Try LibreOffice (available on macOS, Linux, and optionally Windows)
    soffice = _find_soffice()
    _log.info("export_to_pdf path-select: soffice=%s platform=%s", bool(soffice), sys.platform)
    if soffice:
        try:
            result = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(pdf_path.parent),
                    str(pptx_path),
                ],
                capture_output=True,
                timeout=120,
            )
            if result.returncode == 0 and pdf_path.exists():
                return _finish_pdf_export(
                    {"ok": True, "pdf_path": str(pdf_path), "pdf_name": pdf_path.name,
                     "previous_versions": _find_previous_pdf_versions(pdf_path)},
                    pdf_path, body, paths,
                )
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if stderr:
                return {"ok": False, "error": f"LibreOffice conversion failed: {stderr}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "LibreOffice timed out during PDF conversion"}
        except Exception as exc:
            return {"ok": False, "error": f"LibreOffice error: {exc}"}

    # 2. macOS fallback: automate Microsoft PowerPoint via AppleScript
    if sys.platform == "darwin":
        result = _export_via_applescript(pptx_path, pdf_path)
        if result["ok"]:
            return _finish_pdf_export(result, pdf_path, body, paths)
        # Fall through to final error so the AppleScript failure message is surfaced
        # only when PowerPoint itself isn't available.
        if "not running" not in result.get("error", "").lower() and \
                "not installed" not in result.get("error", "").lower():
            return result

    # 3. Windows fallback: PowerPoint COM automation
    if sys.platform == "win32":
        result = _export_via_powerpoint_com(pptx_path, pdf_path)
        if result.get("ok"):
            result = _finish_pdf_export(result, pdf_path, body, paths)
        _log.info("export_to_pdf finish (COM) total=%.2fs ok=%s",
                  time.monotonic() - _t_export_start, result.get("ok"))
        return result

    return {
        "ok": False,
        "error": (
            "PDF export requires LibreOffice or Microsoft PowerPoint. "
            "Install LibreOffice from libreoffice.org and try again."
        ),
    }


def handle_export_all_pdf(project_id: str, paths: AppPaths) -> dict:
    """Generate a PPTX + PDF for every draft in a project and return a results list."""
    from ...inputs.project_entry import load_project

    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}

    exported: list[dict] = []
    errors:   list[dict] = []

    for unit in project.build_units:
        individuals = unit.individuals or []
        if individuals:
            for ind in individuals:
                if not ind.draft_id:
                    errors.append({"unit_id": unit.unit_id, "individual_id": ind.individual_id,
                                   "error": "No draft created yet"})
                    continue
                _do_export(
                    ind.draft_id, unit, paths, exported, errors,
                    project_id=project_id,
                    agency=project.customer.agency,
                    year=project.customer.build_year,
                    individual_id=ind.individual_id,
                )
        else:
            if not unit.draft_id:
                errors.append({"unit_id": unit.unit_id, "error": "No draft created yet"})
                continue
            _do_export(
                unit.draft_id, unit, paths, exported, errors,
                project_id=project_id,
                agency=project.customer.agency,
                year=project.customer.build_year,
            )

    return {"ok": True, "exported": exported, "errors": errors}


def _do_export(
    draft_id: str,
    unit,
    paths: AppPaths,
    exported: list,
    errors: list,
    project_id: str = "",
    agency: str = "",
    year: str = "",
    individual_id: str = "",
) -> None:
    from .draft_service import handle_generate_from_draft

    gen = handle_generate_from_draft({"draft_id": draft_id, "project_id": project_id}, paths)
    if not gen.get("ok"):
        errors.append({"draft_id": draft_id, "unit_id": unit.unit_id,
                       "error": gen.get("error", "Generation failed")})
        return

    pptx_path = gen.get("output_path")
    if not pptx_path:
        errors.append({"draft_id": draft_id, "unit_id": unit.unit_id,
                       "error": "No output_path returned from generation"})
        return

    pdf_res = export_to_pdf({
        "output_path": pptx_path,
        "agency": agency,
        "year": year,
        "project_id": project_id,
        "unit_id": unit.unit_id,
        "individual_id": individual_id,
    }, paths)
    if pdf_res.get("ok"):
        exported_item = {
            "draft_id": draft_id,
            "unit_id": unit.unit_id,
            "individual_id": individual_id,
            "pdf_name": pdf_res["pdf_name"],
            "pdf_path": pdf_res["pdf_path"],
        }
        if pdf_res.get("shop_republish"):
            exported_item["shop_republish"] = pdf_res["shop_republish"]
        exported.append(exported_item)
    else:
        errors.append({"draft_id": draft_id, "unit_id": unit.unit_id,
                       "error": pdf_res.get("error", "PDF conversion failed")})


def open_file(body: dict, paths: AppPaths | None = None) -> dict:
    """Open a file with the OS default application."""
    path = body.get("path", "")
    if (not path or not Path(path).exists()) and paths is not None:
        agency = str(body.get("agency", "") or "").strip()
        year = str(body.get("year", "") or "").strip()
        if path and (agency or year):
            from .exports_upload_service import download_export
            hydrated = download_export(
                paths, source_path=str(path), agency=agency, year=year,
            )
            if hydrated.get("ok"):
                path = hydrated["path"]
            else:
                return hydrated
    if not path or not Path(path).exists():
        return {"ok": False, "error": "File not found"}

    err = _check_allowed(Path(path), _allowed_roots(paths))
    if err:
        return {"ok": False, "error": err}
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
        return {"ok": True, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
