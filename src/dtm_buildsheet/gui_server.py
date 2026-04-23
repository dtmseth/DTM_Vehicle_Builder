#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config_store import get_config_path, load_config, save_config
from .generator import generate_build_sheet
from .input_reader import load_input
from .paths import AppPaths, ensure_workspace
from .template_builder import build_template


PORT = 7655
UI_FILE = Path(__file__).with_name("gui_ui.html")
CONFIG_ROUTES = {
    "/api/catalog": "part_catalog.json",
    "/api/layouts": "vehicle_layouts.json",
    "/api/manifest": "asset_manifest.json",
    "/api/parts-library": "parts_library.json",
    "/api/workbook-rules": "workbook_rules.json",
    "/api/app-settings": "app_settings.json",
}


class Handler(BaseHTTPRequestHandler):
    paths = ensure_workspace()

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_ui()
        elif path == "/status":
            self._api(self._handle_status())
        elif path in CONFIG_ROUTES:
            self._api(load_config(CONFIG_ROUTES[path], self.paths))
        elif path == "/api/template/info":
            self._api(self._handle_template_info())
        elif path == "/api/template/pick-folder":
            self._api(self._handle_pick_folder())
        elif path == "/api/assets/list":
            self._api(self._handle_assets_list())
        elif path.startswith("/assets/"):
            self._serve_asset(path[len("/assets/"):])
        elif path == "/favicon.ico":
            self._send(204, b"", "text/plain")
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        body = self._read_json()
        path = urlparse(self.path).path
        routes = {
            "/parse": self._handle_parse,
            "/generate": self._handle_generate,
            "/open": self._handle_open,
            "/api/catalog/save": lambda b: self._save_json("part_catalog.json", b),
            "/api/layouts/save": lambda b: self._save_json("vehicle_layouts.json", b),
            "/api/manifest/save": lambda b: self._save_json("asset_manifest.json", b),
            "/api/assets/upload": self._handle_asset_upload,
            "/api/assets/delete": self._handle_asset_delete,
            "/api/template/generate": self._handle_template_generate,
            "/api/parts-library/save": lambda b: self._save_json("parts_library.json", b),
            "/api/workbook-rules/save": lambda b: self._save_json("workbook_rules.json", b),
            "/api/app-settings/save": lambda b: self._save_json("app_settings.json", b),
        }
        handler = routes.get(path)
        if handler:
            self._api(handler(body))
        else:
            self._send(404, b"Not found", "text/plain")

    def _serve_ui(self):
        html = UI_FILE.read_text("utf-8") if UI_FILE.exists() else f"<h1>UI file not found: {UI_FILE}</h1>"
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_asset(self, rel_path: str):
        safe = (self.paths.workspace_assets_dir / rel_path).resolve()
        root = self.paths.workspace_assets_dir.resolve()
        if not str(safe).startswith(str(root)) or not safe.exists():
            self._send(404, b"Not found", "text/plain")
            return
        ctype = mimetypes.guess_type(str(safe))[0] or "application/octet-stream"
        self._send(200, safe.read_bytes(), ctype)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _api(self, data: dict):
        self._send(200, json.dumps(data).encode("utf-8"), "application/json")

    def _save_json(self, filename: str, data: object) -> dict:
        try:
            normalized = save_config(filename, data, self.paths)
            return {"ok": True, "path": str(get_config_path(filename, self.paths)), "schema_version": normalized.get("schema_version", 1)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _save_xlsx(self, body: dict) -> Path:
        raw = base64.b64decode(body["data"])
        fname = Path(body.get("filename", "upload.xlsx")).name
        dest = self.paths.workspace_input_dir / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return dest

    def _handle_status(self) -> dict:
        for workbook in sorted(self.paths.workspace_input_dir.glob("*.xlsx")):
            if "template" not in workbook.name.lower():
                return {"ok": True, "existing_file": workbook.name}
        return {"ok": True, "existing_file": None}

    def _handle_assets_list(self) -> dict:
        files = []
        for asset in sorted(self.paths.workspace_assets_dir.rglob("*")):
            if asset.is_file() and not asset.name.startswith("."):
                rel = asset.relative_to(self.paths.workspace_assets_dir)
                files.append({"path": str(rel).replace("\\", "/"), "folder": str(rel.parent).replace("\\", "/"), "name": asset.name, "size": asset.stat().st_size})
        return {"ok": True, "files": files}

    def _handle_parse(self, body: dict) -> dict:
        try:
            path = self._save_xlsx(body)
            project = load_input(path)
            return {
                "ok": True,
                "info": project.info,
                "parts": [{"name": p.name, "location": p.location, "color": p.raw_color, "qty": p.quantity, "include": p.include} for p in project.parts],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _handle_generate(self, body: dict) -> dict:
        log_lines: list[str] = []
        try:
            path = self._save_xlsx(body)
            log_lines.append(f"Reading: {path.name}")
            project = load_input(path)
            log_lines.append(f"Vehicle type: {project.info.get('VehicleType', '?')}")
            log_lines.append(f"Parts found: {len(project.parts)}")
            result = generate_build_sheet(path, self.paths)
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
            import traceback
            log_lines.extend(["ERROR: " + str(exc), traceback.format_exc()])
            return {"ok": False, "error": str(exc), "log": "\n".join(log_lines)}

    def _handle_open(self, body: dict) -> dict:
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

    def _handle_asset_upload(self, body: dict) -> dict:
        try:
            folder = body.get("folder", "equipment")
            filename = Path(body.get("filename", "upload.png")).name
            data = base64.b64decode(body["data"])
            dest_dir = self.paths.workspace_assets_dir / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename
            dest.write_bytes(data)
            rel = str(dest.relative_to(self.paths.workspace_assets_dir)).replace("\\", "/")
            return {"ok": True, "path": rel, "url": f"/assets/{rel}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _handle_asset_delete(self, body: dict) -> dict:
        try:
            folder = body.get("folder", "")
            filename = Path(body.get("filename", "")).name
            if not folder or not filename:
                return {"ok": False, "error": "Missing folder or filename"}
            target = (self.paths.workspace_assets_dir / folder / filename).resolve()
            assets_root = self.paths.workspace_assets_dir.resolve()
            if not str(target).startswith(str(assets_root)):
                return {"ok": False, "error": "Invalid asset path"}
            if target.exists():
                target.unlink()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _get_template_path(self) -> Path:
        settings = load_config("app_settings.json", self.paths) or {}
        save_dir = settings.get("template_save_dir", "")
        if save_dir and Path(save_dir).is_dir():
            return Path(save_dir) / "build_sheet_template_v2.xlsx"
        return self.paths.workspace_dir / "build_sheet_template_v2.xlsx"

    def _handle_template_info(self) -> dict:
        p = self._get_template_path()
        if p.exists():
            return {"ok": True, "exists": True, "mtime": p.stat().st_mtime, "path": str(p)}
        return {"ok": True, "exists": False, "mtime": None, "path": str(p)}

    def _handle_template_generate(self, body: dict) -> dict:
        try:
            out_path = build_template(self.paths, out_path=self._get_template_path())
            return {"ok": True, "path": str(out_path), "filename": out_path.name}
        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc), "detail": traceback.format_exc()}

    def _handle_pick_folder(self) -> dict:
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


class _ReuseHTTPServer(HTTPServer):
    allow_reuse_address = True


def _port_is_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main(paths: AppPaths | None = None):
    active_paths = paths or ensure_workspace()
    Handler.paths = active_paths
    if _port_is_busy(PORT):
        raise SystemExit(f"Port {PORT} is already in use. Close the other app instance and try again.")
    server = _ReuseHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"DTM Vehicle Builder GUI -> {url}")
    print(f"Workspace -> {active_paths.workspace_dir}")

    try:
        import webview
        # webview must own the main thread (macOS requirement), so server runs in background
        threading.Thread(target=server.serve_forever, daemon=True).start()
        window = webview.create_window("DTM Vehicle Builder", url, width=1280, height=800, min_size=(900, 600))
        webview.start()
        server.shutdown()
    except ImportError:
        print("Press Ctrl-C to quit.\n")
        threading.Thread(target=lambda: (time.sleep(0.4), webbrowser.open(url)), daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


if __name__ == "__main__":
    main()
