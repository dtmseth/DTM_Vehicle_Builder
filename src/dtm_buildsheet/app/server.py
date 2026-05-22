from __future__ import annotations

import json
import logging
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ..paths import AppPaths, ensure_workspace
from .routes import agencies as agency_routes
from .routes import sales_reps as sales_rep_routes
from .services import agency_service, sales_rep_service
from .routes import assets as asset_routes
from .routes import config as config_routes
from .routes import drafts as draft_routes
from .routes import exports as export_routes
from .routes import generation as generation_routes
from .routes import preview as preview_routes
from .routes import presets as preset_routes
from .routes import projects as project_routes
from .routes import templates as template_routes
from .routes import updates as update_routes
from .routes import validation as validation_routes
from .services.template_service import pick_folder as _pick_folder

PORT = 7655
_UI_FILE = Path(__file__).parent.parent / "ui" / "index.html"
_UI_DIR = Path(__file__).parent.parent / "ui"

try:
    from importlib.metadata import version as _pkg_version
    _APP_VERSION = f"v{_pkg_version('dtm-buildsheet')}"
except Exception:
    _APP_VERSION = "dev"

_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    paths: AppPaths = AppPaths()

    def log_message(self, fmt, *args):
        pass

    # ── GET ───────────────────────────────────────────────────────────────────

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            self._serve_ui()
        elif path == "/status":
            self._api(generation_routes.get_status(self.paths))
        elif path in config_routes.GET_ROUTES:
            self._api(config_routes.get_config(path, self.paths))
        elif path == "/api/template/info":
            self._api(template_routes.get_info(self.paths))
        elif path == "/api/template/pick-folder":
            self._api(template_routes.get_pick_folder())
        elif path == "/api/generate/pick-folder":
            self._api(generation_routes.get_pick_export_folder())
        elif path == "/api/assets/list":
            self._api(asset_routes.get_list(self.paths))
        elif path.startswith("/assets/"):
            status, body, ctype = asset_routes.get_asset(path[len("/assets/"):], self.paths)
            self._send(status, body, ctype)
        elif path.startswith("/api/validate/"):
            if not validation_routes.route_validation(self, "GET", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/draft/") or path == "/api/draft/list":
            if not draft_routes.route_drafts(self, "GET", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/presets" or path.startswith("/api/presets/"):
            if not preset_routes.route_presets(self, "GET", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/agencies" or path == "/api/agencies/search":
            if not agency_routes.route_agencies(self, "GET", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/sales-reps" or path == "/api/sales-reps/search":
            if not sales_rep_routes.route_sales_reps(self, "GET", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/project/pick-output-root":
            self._api(_pick_folder())
        elif path == "/api/projects" or path.startswith("/api/project/"):
            if not project_routes.route_projects(self, "GET", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/update/"):
            if not update_routes.route_updates(self, "GET", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/ui/"):
            self._serve_static(path[len("/ui/"):])
        elif path == "/favicon.ico":
            self._send(204, b"", "text/plain")
        else:
            self._send(404, b"Not found", "text/plain")

    # ── POST ──────────────────────────────────────────────────────────────────

    def do_POST(self):
        body = self._read_json()
        path = urlparse(self.path).path

        if path == "/parse":
            self._api(generation_routes.post_parse(body, self.paths))
        elif path == "/generate":
            self._api(generation_routes.post_generate(body, self.paths))
        elif path == "/api/generate/delete-old":
            self._api(generation_routes.post_delete_old(body, self.paths))
        elif path == "/open":
            self._api(export_routes.post_open(body, self.paths))
        elif path == "/api/export/pdf":
            self._api(export_routes.post_pdf(body, self.paths))
        elif path in config_routes.POST_ROUTES:
            self._api(config_routes.post_save(path, body, self.paths))
        elif path == "/api/assets/upload":
            self._api(asset_routes.post_upload(body, self.paths))
        elif path == "/api/assets/delete":
            self._api(asset_routes.post_delete(body, self.paths))
        elif path == "/api/template/generate":
            self._api(template_routes.post_generate(body, self.paths))
        elif path == "/api/validate":
            if not validation_routes.route_validation(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/preview/plan":
            if not preview_routes.route_preview(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/draft/"):
            if not draft_routes.route_drafts(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/presets/save" or path == "/api/presets/import-workbook" or (path.startswith("/api/presets/") and path.endswith("/clone")):
            if not preset_routes.route_presets(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/agency/save":
            if not agency_routes.route_agencies(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/sales-rep/save":
            if not sales_rep_routes.route_sales_reps(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/project/save" or path.startswith("/api/project/"):
            if not project_routes.route_projects(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/update/"):
            if not update_routes.route_updates(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        else:
            self._send(404, b"Not found", "text/plain")

    # ── DELETE ────────────────────────────────────────────────────────────────

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/presets/"):
            if not preset_routes.route_presets(self, "DELETE", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/agency/"):
            if not agency_routes.route_agencies(self, "DELETE", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/sales-rep/"):
            if not sales_rep_routes.route_sales_reps(self, "DELETE", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/draft/"):
            if not draft_routes.route_drafts(self, "DELETE", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/project/"):
            if not project_routes.route_projects(self, "DELETE", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        else:
            self._send(404, b"Not found", "text/plain")

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _serve_ui(self):
        html = (
            _UI_FILE.read_text("utf-8")
            if _UI_FILE.exists()
            else f"<h1>UI file not found: {_UI_FILE}</h1>"
        )
        html = html.replace("{{APP_VERSION}}", _APP_VERSION)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_static(self, rel_path: str):
        file_path = (_UI_DIR / rel_path).resolve()
        # Prevent path traversal outside _UI_DIR
        try:
            file_path.relative_to(_UI_DIR.resolve())
        except ValueError:
            self._send(403, b"Forbidden", "text/plain")
            return
        if not file_path.exists() or not file_path.is_file():
            self._send(404, b"Not found", "text/plain")
            return
        suffix = file_path.suffix.lower()
        ctype = _MIME_TYPES.get(suffix, "application/octet-stream")
        self._send(200, file_path.read_bytes(), ctype)

    def _read_json(self) -> dict:
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


class _ReuseHTTPServer(HTTPServer):
    allow_reuse_address = True


def _port_is_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _setup_logging(workspace_dir: Path) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    log_file = workspace_dir / "dtm_buildsheet.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )


def main(paths: AppPaths | None = None):
    if paths is None:
        _setup_logging(AppPaths().workspace_dir)
    active_paths = paths or ensure_workspace()
    if paths is not None:
        _setup_logging(active_paths.workspace_dir)
    Handler.paths = active_paths

    # Warm per-record collection caches at startup so the one-shot legacy
    # migration (Phase 1) fires immediately on launch rather than on first
    # user interaction with the agency/sales-rep services.
    agency_service.warmup_cache(active_paths)
    sales_rep_service.warmup_cache(active_paths)

    if _port_is_busy(PORT):
        raise SystemExit(
            f"Port {PORT} is already in use. Close the other app instance and try again."
        )

    server = _ReuseHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"DTM Vehicle Builder GUI -> {url}")
    print(f"Workspace -> {active_paths.workspace_dir}")

    try:
        import webview
        threading.Thread(target=server.serve_forever, daemon=True).start()
        window = webview.create_window(
            "DTM Vehicle Builder", url, width=1280, height=800, min_size=(900, 600)
        )
        webview.start()
        server.shutdown()
    except ImportError:
        print("Press Ctrl-C to quit.\n")
        threading.Thread(
            target=lambda: (time.sleep(0.4), webbrowser.open(url)), daemon=True
        ).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
