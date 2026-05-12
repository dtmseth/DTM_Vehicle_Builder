from __future__ import annotations

import base64
import logging
import mimetypes
import subprocess
from pathlib import Path

from ...paths import AppPaths, ASSETS_DIR

_log = logging.getLogger(__name__)


def _git_stage(*paths: Path) -> None:
    """Stage paths so they're included in the next commit."""
    try:
        subprocess.run(["git", "add", "--"] + [str(p) for p in paths], check=True)
    except subprocess.CalledProcessError as exc:
        _log.warning("git stage failed: %s", exc)


def list_assets(paths: AppPaths) -> dict:
    files = []
    for asset in sorted(paths.workspace_assets_dir.rglob("*")):
        if asset.is_file() and not asset.name.startswith("."):
            rel = asset.relative_to(paths.workspace_assets_dir)
            files.append({
                "path": str(rel).replace("\\", "/"),
                "folder": str(rel.parent).replace("\\", "/"),
                "name": asset.name,
                "size": asset.stat().st_size,
            })
    return {"ok": True, "files": files}


def serve_asset(rel_path: str, paths: AppPaths) -> tuple[int, bytes, str]:
    """Return (status_code, body, content_type) for a raw asset file request."""
    safe = (paths.workspace_assets_dir / rel_path).resolve()
    root = paths.workspace_assets_dir.resolve()
    if not safe.is_relative_to(root) or not safe.exists():
        _log.debug("Asset not found: rel=%s safe=%s root=%s", rel_path, safe, root)
        return 404, b"Not found", "text/plain"
    ctype = mimetypes.guess_type(str(safe))[0] or "application/octet-stream"
    return 200, safe.read_bytes(), ctype


def upload_asset(body: dict, paths: AppPaths) -> dict:
    try:
        folder = body.get("folder", "equipment")
        filename = Path(body.get("filename", "upload.png")).name
        data = base64.b64decode(body["data"])
        dest_dir = paths.workspace_assets_dir / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        dest.write_bytes(data)
        rel = str(dest.relative_to(paths.workspace_assets_dir)).replace("\\", "/")
        if paths.workspace_assets_dir == ASSETS_DIR:
            _git_stage(dest)
        return {"ok": True, "path": rel, "url": f"/assets/{rel}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def delete_asset(body: dict, paths: AppPaths) -> dict:
    try:
        folder = body.get("folder", "")
        filename = Path(body.get("filename", "")).name
        if not folder or not filename:
            return {"ok": False, "error": "Missing folder or filename"}
        target = (paths.workspace_assets_dir / folder / filename).resolve()
        assets_root = paths.workspace_assets_dir.resolve()
        if not target.is_relative_to(assets_root):
            return {"ok": False, "error": "Invalid asset path"}
        existed = target.exists()
        if existed:
            target.unlink()
        if existed and paths.workspace_assets_dir == ASSETS_DIR:
            _git_stage(target)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
