from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path

from ...config.store import load_config
from ...paths import AppPaths
from ...template_builder import build_template


def get_template_path(paths: AppPaths) -> Path:
    settings = load_config("app_settings.json", paths) or {}
    save_dir = settings.get("template_save_dir", "")
    if save_dir and Path(save_dir).is_dir():
        return Path(save_dir) / "build_sheet_template_v2.xlsx"
    return paths.workspace_dir / "build_sheet_template_v2.xlsx"


def get_template_info(paths: AppPaths) -> dict:
    p = get_template_path(paths)
    if p.exists():
        return {"ok": True, "exists": True, "mtime": p.stat().st_mtime, "path": str(p)}
    return {"ok": True, "exists": False, "mtime": None, "path": str(p)}


def generate_template(paths: AppPaths) -> dict:
    try:
        out_path = build_template(paths, out_path=get_template_path(paths))
        return {"ok": True, "path": str(out_path), "filename": out_path.name}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "detail": traceback.format_exc()}


def pick_folder() -> dict:
    try:
        if sys.platform == "darwin":
            r = subprocess.run(
                ["osascript", "-e", "POSIX path of (choose folder)"],
                capture_output=True, text=True, timeout=60,
            )
            path = r.stdout.strip()
        elif sys.platform == "win32":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
                "[void]$f.ShowDialog();"
                "Write-Output $f.SelectedPath"
            )
            r = subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True, text=True, timeout=60,
            )
            path = r.stdout.strip()
        else:
            return {"ok": False, "error": "Folder picker not supported on this platform"}
        if not path:
            return {"ok": False, "error": "Cancelled"}
        return {"ok": True, "path": path}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
