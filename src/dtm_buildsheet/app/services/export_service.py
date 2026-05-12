from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def _find_previous_pdf_versions(pdf_path: Path) -> list[str]:
    """Find older PDF exports with the same Agency_Unit_Year_Updated_ prefix."""
    prefix = re.sub(r'_[A-Z][a-z]{2}\d+_\d{4}_\d+-\d+-\d+[AP]M$', '', pdf_path.stem) + '_'
    return [
        str(p) for p in sorted(pdf_path.parent.glob(f"{prefix}*.pdf"))
        if p.name != pdf_path.name
    ]


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
    try:
        import comtypes.client  # type: ignore[import]
        powerpoint = comtypes.client.CreateObject("Powerpoint.Application")
        powerpoint.Visible = 1
        prs = powerpoint.Presentations.Open(str(pptx_path))
        prs.SaveAs(str(pdf_path), 32)  # 32 = ppSaveAsPDF
        prs.Close()
        powerpoint.Quit()
        if pdf_path.exists():
            return {"ok": True, "pdf_path": str(pdf_path), "pdf_name": pdf_path.name,
                    "previous_versions": _find_previous_pdf_versions(pdf_path)}
        return {"ok": False, "error": "PDF not created by PowerPoint COM"}
    except Exception as exc:
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

def export_to_pdf(body: dict) -> dict:
    """Convert an existing PPTX file to PDF.

    Tries LibreOffice first (cross-platform), then PowerPoint COM on Windows.
    Returns {"ok": True, "pdf_path": ..., "pdf_name": ...} or {"ok": False, "error": ...}.
    """
    pptx_path_str = body.get("output_path", "")
    if not pptx_path_str:
        return {"ok": False, "error": "output_path is required"}

    pptx_path = Path(pptx_path_str)
    if not pptx_path.exists():
        return {"ok": False, "error": f"PPTX file not found: {pptx_path.name}"}
    if pptx_path.suffix.lower() != ".pptx":
        return {"ok": False, "error": "output_path must point to a .pptx file"}

    pdf_path = pptx_path.with_suffix(".pdf")

    # 1. Try LibreOffice (available on macOS, Linux, and optionally Windows)
    soffice = _find_soffice()
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
                return {"ok": True, "pdf_path": str(pdf_path), "pdf_name": pdf_path.name,
                        "previous_versions": _find_previous_pdf_versions(pdf_path)}
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
            return result
        # Fall through to final error so the AppleScript failure message is surfaced
        # only when PowerPoint itself isn't available.
        if "not running" not in result.get("error", "").lower() and \
                "not installed" not in result.get("error", "").lower():
            return result

    # 3. Windows fallback: PowerPoint COM automation
    if sys.platform == "win32":
        return _export_via_powerpoint_com(pptx_path, pdf_path)

    return {
        "ok": False,
        "error": (
            "PDF export requires LibreOffice or Microsoft PowerPoint. "
            "Install LibreOffice from libreoffice.org and try again."
        ),
    }


def open_file(body: dict) -> dict:
    """Open a file with the OS default application."""
    path = body.get("path", "")
    if not path or not Path(path).exists():
        return {"ok": False, "error": "File not found"}
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
