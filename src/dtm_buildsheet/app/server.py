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
from .services.shared_settings_service import sync_shared_settings_at_startup
from .routes import assets as asset_routes
from .routes import builds as build_routes
from .routes import cloud_status as cloud_status_routes
from .routes import config as config_routes
from .routes import drafts as draft_routes
from .routes import exports as export_routes
from .routes import generation as generation_routes
from .routes import preview as preview_routes
from .routes import parts_db as parts_db_routes
from .routes import presets as preset_routes
from .routes import projects as project_routes
from .routes import quickbooks as quickbooks_routes
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
        elif path == "/api/parts-db" or path.startswith("/api/parts-db/"):
            if not parts_db_routes.route_parts_db(self, "GET", path, {}, self.paths):
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
        elif path.startswith("/api/cloud/"):
            if not cloud_status_routes.route_cloud_status(self, "GET", path, {}, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/quickbooks/"):
            if not quickbooks_routes.route_quickbooks(self, "GET", path, {}, self.paths):
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
        elif path.startswith("/api/build/"):
            if not build_routes.route_builds(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/presets/save" or path == "/api/presets/import-workbook" or (path.startswith("/api/presets/") and path.endswith("/clone")):
            if not preset_routes.route_presets(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/agency/save":
            if not agency_routes.route_agencies(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path == "/api/parts-db" or path.startswith("/api/parts-db/"):
            if not parts_db_routes.route_parts_db(self, "POST", path, body, self.paths):
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
        elif path.startswith("/api/cloud/"):
            if not cloud_status_routes.route_cloud_status(self, "POST", path, body, self.paths):
                self._send(404, b"Not found", "text/plain")
        elif path.startswith("/api/quickbooks/"):
            if not quickbooks_routes.route_quickbooks(self, "POST", path, body, self.paths):
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


def _wait_for_server_ready(port: int, *, timeout_seconds: float = 5.0) -> bool:
    """Wait until the HTTP server is accepting connections."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


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


# Interval between background syncs of /Settings/, /Projects/, /Drafts/.
# 60s is the sweet spot: short enough that teammates see changes within
# ~2 min worst-case (60s app poll + ~30s workflow pipeline), low enough
# bandwidth that even a busy team-of-10 only generates ~10 list_files
# calls per minute against SharePoint.
_PERIODIC_SYNC_INTERVAL_SECONDS = 60


# Serialize concurrent sync invocations. Without this, the periodic loop
# and /api/cloud/sync (the modal's "Force Sync" button) could run
# simultaneously: each sets _sync_in_progress True, the faster one finishes
# and sets it back to False mid-way through the other, the API reports
# "synced!" while work is still in flight. Lock makes "force sync" wait
# for any in-progress periodic sync to finish before starting its own pass.
_sync_lock = threading.Lock()
_sync_in_progress = False  # noqa: PLW0603 — see run_sync_now() for the contract
# When True, the UI suppresses the cloud-chip spinner while a sync cycle is
# in flight. Periodic 60s background syncs always run quiet — the user
# doesn't see a spinner for the polling/checking phase that 99% of cycles
# never finds any changes in. Manual force-sync flips this off so the
# explicit user-triggered action still gets a spinner.
_sync_quiet = False  # noqa: PLW0603

# Most-recent sync's change list, e.g.
#   {"summary": "2 agencies added · 1 project modified", "expires_at": <unix>}
# Set after each sync that actually transferred something. Cleared by the
# status-endpoint hook once expires_at is in the past so the modal
# briefly shows what changed and then quietly goes away.
_last_sync_changes: dict | None = None  # noqa: PLW0603
_SYNC_CHANGES_DISPLAY_SECONDS = 10

# Unix timestamp until which the cloud chip should keep spinning AFTER a
# quiet periodic sync finished with actual transfers. Without this the
# quiet sync would only ever bump the modal "changes" row without giving
# the user any visual indication that data was just moving. Holding the
# spinner for 3s after transfer is enough that a glance at the chip
# catches the activity.
_visible_hold_until: float = 0.0  # noqa: PLW0603
_VISIBLE_HOLD_AFTER_TRANSFER_SECONDS = 3.0

# Monotonically-increasing counter incremented every time a sync produces
# observable changes (updated/deleted/uploaded files). Surfaced in the
# /api/cloud/status response so the UI can detect "data changed under me"
# and re-fetch its lists without waiting for the user to click around.
_data_version = 0  # noqa: PLW0603 — see _bump_data_version()


def is_sync_in_progress() -> bool:
    """True while a sync (initial or periodic or forced) is mid-flight."""
    return _sync_in_progress


def get_data_version() -> int:
    """Return the current data-version counter for the cloud status payload."""
    return _data_version


def is_sync_in_progress_visible() -> bool:
    """Status-endpoint hook: True only when the cloud chip SHOULD spin.

    Three conditions surface the spinner:
      1. Force-sync is running (raw flag set, quiet=False).
      2. A quiet periodic sync just transferred something and we're
         still inside the brief hold window so a glance at the chip
         catches the activity (_visible_hold_until > now).
    """
    if _sync_in_progress and not _sync_quiet:
        return True
    if _visible_hold_until > _now_unix():
        return True
    return False


def get_sync_changes_summary() -> dict | None:
    """Return the most-recent change summary if it hasn't aged out yet.

    Auto-clears the slot once the display window has elapsed so the modal
    naturally goes back to "nothing to show" without an explicit reset."""
    global _last_sync_changes
    snap = _last_sync_changes
    if snap is None:
        return None
    if snap.get("expires_at", 0) < _now_unix():
        _last_sync_changes = None
        return None
    return {"summary": snap["summary"], "items": snap.get("items", [])}


def _now_unix() -> float:
    return time.time()


def _record_change_summary(work_report: dict, settings_report,
                           queue_report: dict, update_report: dict | None) -> None:
    """Build a human-readable summary of what just got synced, and stash it
    for the next few cloud_status polls so the modal can show it.

    Settings updates come back as a list of filenames; we collapse them to
    counts per kind (agencies, sales reps, presets, general configs).
    Work data already comes back as counts. Queue items are retry
    successes, surfaced as "queued change(s) sent". Update queue is the
    auto-update installer reaching the .queued_installer dir.
    """
    global _last_sync_changes
    items: list[str] = []

    if settings_report and settings_report.updated:
        kinds: dict[str, int] = {}
        for name in settings_report.updated:
            kind = "settings"
            if name.startswith("agencies/"):
                kind = "agencies"
            elif name.startswith("sales_reps/"):
                kind = "sales reps"
            elif name.startswith("presets/"):
                kind = "presets"
            kinds[kind] = kinds.get(kind, 0) + 1
        for kind, n in kinds.items():
            items.append(f"{n} {kind} updated")

    proj_up = work_report.get("projects_updated") or 0
    proj_del = work_report.get("projects_deleted") or 0
    proj_pushed = work_report.get("projects_uploaded") or 0
    draft_up = work_report.get("drafts_updated") or 0
    draft_del = work_report.get("drafts_deleted") or 0
    draft_pushed = work_report.get("drafts_uploaded") or 0
    if proj_up: items.append(f"{proj_up} project{'s' if proj_up != 1 else ''} updated")
    if proj_del: items.append(f"{proj_del} project{'s' if proj_del != 1 else ''} deleted")
    if proj_pushed: items.append(f"{proj_pushed} project{'s' if proj_pushed != 1 else ''} uploaded")
    if draft_up: items.append(f"{draft_up} draft{'s' if draft_up != 1 else ''} updated")
    if draft_del: items.append(f"{draft_del} draft{'s' if draft_del != 1 else ''} deleted")
    if draft_pushed: items.append(f"{draft_pushed} draft{'s' if draft_pushed != 1 else ''} uploaded")

    if queue_report.get("proposals_succeeded"):
        n = queue_report["proposals_succeeded"]
        items.append(f"{n} queued change{'s' if n != 1 else ''} sent")
    if queue_report.get("exports_succeeded"):
        n = queue_report["exports_succeeded"]
        items.append(f"{n} export{'s' if n != 1 else ''} uploaded")

    if update_report and update_report.get("queued"):
        items.append(f"app update v{update_report['queued']} downloaded")

    if not items:
        return
    _last_sync_changes = {
        "summary": " · ".join(items),
        "items": items,
        "expires_at": _now_unix() + _SYNC_CHANGES_DISPLAY_SECONDS,
    }
    global _visible_hold_until
    _visible_hold_until = _now_unix() + _VISIBLE_HOLD_AFTER_TRANSFER_SECONDS


def _bump_data_version() -> None:
    global _data_version
    _data_version += 1


def run_sync_now(active_paths: AppPaths, *, quiet: bool = False) -> dict:
    """Run a single sync cycle synchronously and return a small report.

    Called by /api/cloud/sync from the modal AND by the periodic loop.
    Serialized through ``_sync_lock`` so two concurrent callers don't
    race on the in-progress flag.

    ``quiet`` is True for the periodic 60s background loop — the UI
    hides the cloud-chip spinner during quiet syncs because most of them
    are pure "check, nothing to do" passes. The user only sees the
    spinner when they explicitly clicked Force Sync Now (non-quiet) OR
    when a quiet sync surfaces a change list (rendered briefly in the
    modal so they can see what landed).
    """
    global _sync_in_progress, _sync_quiet
    logger = logging.getLogger(__name__)
    report: dict = {"ok": True}
    with _sync_lock:
        _sync_in_progress = True
        _sync_quiet = quiet
        try:
            # Sign-in step is included so "Force Sync Now" can also recover
            # an app that lost its cached token between launches.
            from .adapters.wiring import ensure_signed_in_for_cloud
            ensure_signed_in_for_cloud()

            settings_report = sync_shared_settings_at_startup(active_paths)
            settings_changed = bool(settings_report and settings_report.updated)
            report["settings"] = (
                {
                    "updated": settings_report.updated,
                    "unchanged_count": len(settings_report.unchanged),
                    "failed_count": len(settings_report.failed),
                }
                if settings_report
                else None
            )

            agency_service.warmup_cache(active_paths, force=True)
            sales_rep_service.warmup_cache(active_paths, force=True)

            from .services.shared_work_service import sync_work_data
            work_report = sync_work_data(active_paths)
            report["work"] = work_report

            work_changed = bool(
                work_report.get("projects_updated") or work_report.get("projects_deleted")
                or work_report.get("projects_uploaded")
                or work_report.get("drafts_updated") or work_report.get("drafts_deleted")
                or work_report.get("drafts_uploaded")
            )

            # Drain any cloud writes that failed at save time. The
            # proposal and export paths enqueue failures here; drain
            # retries them now that we know cloud is reachable (we just
            # finished a sync). Bumps data_version when something landed
            # so the UI knows to refresh.
            from .services.outbound_queue import drain_queue
            queue_report = drain_queue(active_paths)
            report["queue"] = queue_report
            queue_changed = bool(
                queue_report.get("proposals_succeeded")
                or queue_report.get("exports_succeeded")
            )

            # Sweep processed entries out of /PendingChanges/ so it doesn't
            # accumulate forever. The pickup workflow reads from there but
            # doesn't delete; everything older than 12h is either applied
            # or stuck and safe to drop.
            try:
                from .services.shared_work_service import cleanup_processed_proposals
                pending_cleanup = cleanup_processed_proposals()
                report["pending_cleanup"] = pending_cleanup
            except Exception:
                logger.exception("PendingChanges cleanup failed")

            # Background download of any newer release into the queue dir
            # so the next restart (or explicit "Restart now" click) installs
            # it silently. Pulls the user's dismissed-versions list so a
            # dismissed update doesn't keep getting re-fetched.
            update_changed = False
            update_report: dict = {}
            try:
                from .adapters.wiring import get_active_bundle
                from .services.update_check_service import download_pending_update_if_any
                from ..config.store import load_config
                _settings = load_config("app_settings.json", active_paths) or {}
                _dismissed = list(_settings.get("dismissed_update_versions", []) or [])
                update_report = download_pending_update_if_any(
                    get_active_bundle().storage,
                    active_paths,
                    dismissed_versions=_dismissed,
                )
                report["update"] = update_report
                update_changed = bool(update_report.get("queued"))
            except Exception:
                logger.exception("Sync: background update check failed")

            if settings_changed or work_changed or queue_changed or update_changed:
                _bump_data_version()
                _record_change_summary(work_report, settings_report, queue_report,
                                       update_report if update_changed else None)
        except Exception as exc:
            logger.exception("Sync cycle failed")
            report = {"ok": False, "error": str(exc)}
        finally:
            _sync_in_progress = False
            _sync_quiet = False
    return report


def _periodic_sync_loop(active_paths: AppPaths) -> None:
    """Background loop that re-syncs shared settings + work data on a timer.

    First iteration fires immediately (without sleeping) so the cloud
    bootstrap runs off the main thread: the HTTP server is already up
    while sign-in + initial sync proceed in parallel. Subsequent
    iterations sleep first.

    Runs forever as a daemon thread; the process exits when the main
    thread does. Each iteration is wrapped so a sync exception doesn't
    kill the loop — the next tick gets a fresh attempt.
    """
    import time

    logger = logging.getLogger(__name__)
    first = True
    while True:
        if not first:
            time.sleep(_PERIODIC_SYNC_INTERVAL_SECONDS)
        first = False
        try:
            run_sync_now(active_paths, quiet=True)
        except Exception:
            logger.exception("Periodic sync iteration failed; will retry in %ds",
                             _PERIODIC_SYNC_INTERVAL_SECONDS)


def main(paths: AppPaths | None = None):
    if paths is None:
        _setup_logging(AppPaths().workspace_dir)
    active_paths = paths or ensure_workspace()
    if paths is not None:
        _setup_logging(active_paths.workspace_dir)

    # Boot-time silent install: if last session queued an installer, run it
    # now (Windows only) and exit so the installer's CloseApplications hook
    # can replace our binaries cleanly. The installer auto-launches the new
    # version when it finishes (see installer.iss [Run] section).
    try:
        import sys as _sys
        from .services.update_check_service import consume_queued_installer
        if consume_queued_installer(active_paths):
            logging.getLogger(__name__).info(
                "Queued installer launched; exiting so it can replace this version"
            )
            _sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        logging.getLogger(__name__).exception(
            "Boot-time queued-installer check failed; continuing normal startup"
        )

    Handler.paths = active_paths

    # Warm per-record collection caches at startup so the one-shot legacy
    # migration (Phase 1) fires immediately on launch rather than on first
    # user interaction with the agency/sales-rep services.
    agency_service.warmup_cache(active_paths)
    sales_rep_service.warmup_cache(active_paths)

    # Cloud bootstrap (sign-in + initial sync) runs in the periodic sync
    # thread's first iteration, NOT on the main thread. This keeps the
    # HTTP server snappy — the UI loads immediately and the cloud
    # indicator chip lights up as soon as the first sync completes. The
    # loop then ticks every 60s to pull teammates' changes. Periodic
    # sync is no-op outside cloud mode (early returns inside the helpers).
    threading.Thread(
        target=_periodic_sync_loop,
        args=(active_paths,),
        daemon=True,
        name="periodic-sync",
    ).start()

    # QuickBooks: pull + reconcile linked parts at startup and every 30 min.
    # No-op until the owner has connected a company (guarded inside).
    try:
        from .services import qb_sync_service
        qb_sync_service.start_background_sync(active_paths)
    except Exception:
        logging.getLogger(__name__).warning("QuickBooks background sync did not start")

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
        _wait_for_server_ready(PORT)
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
