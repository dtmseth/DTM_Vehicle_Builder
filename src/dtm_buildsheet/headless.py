"""Disposable, cloud-off local prototype. Never a public hosting entry point.

Run in a fresh process: python -m dtm_buildsheet.headless --workspace /tmp/...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
from urllib.parse import urlparse


def prepare_environment(workspace: Path, *, container: bool = False) -> Path:
    if "dtm_buildsheet.paths" in sys.modules:
        raise RuntimeError("Start headless in a fresh process before importing application paths")
    if any(os.environ.get(key) for key in ("CONTAINER_APP_NAME", "WEBSITE_INSTANCE_ID", "K_REVISION")):
        raise ValueError("The Stage 1 pilot cannot run in a deployed environment")
    if not workspace.is_absolute():
        raise ValueError("Pilot workspace must be absolute")
    workspace = workspace.resolve()
    roots = [Path("/pilot-data")] if container else [Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()]
    if not any(workspace != root and workspace.is_relative_to(root) for root in roots):
        raise ValueError(f"Use a dedicated disposable workspace below {roots[0]} or /tmp")
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").exists() and workspace.is_relative_to(checkout):
        raise ValueError("Pilot data must remain outside the checkout")
    marker = workspace / ".dtm-local-pilot"
    if workspace.exists() and any(workspace.iterdir()) and not marker.is_file():
        raise ValueError("Refusing a nonempty workspace without a pilot marker")
    if workspace.exists() and any(p.is_symlink() for p in workspace.rglob("*")):
        raise ValueError("Pilot workspace must not contain symlinks")
    workspace.mkdir(parents=True, exist_ok=True)
    marker.write_text("Local synthetic data only; not a hosted workspace.\n")
    os.environ["DTM_CLOUD"] = "0"
    os.environ["DTM_LOCAL_PILOT"] = "1"
    os.environ["DTM_WORKSPACE_DIR"] = str(workspace)
    # No inherited test bypass or workstation provider configuration.
    os.environ.pop("DTM_ALLOW_CLOUD_IN_TESTS", None)
    return workspace


def install_egress_guard() -> list[str]:
    """Fail closed on Python-originated egress and native process launches.

    An audit hook is a tripwire, not an OS sandbox. The container additionally
    uses an internal network; LibreOffice has no external network access there.
    """
    violations: list[str] = []

    def audit(event, args):
        blocked = event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname",
                            "os.system", "os.posix_spawn", "os.spawn"}
        if event == "subprocess.Popen":
            command = args[1]
            blocked = not (
                isinstance(command, (list, tuple))
                and Path(str(command[0])).name in {"soffice", "libreoffice"}
                and "--headless" in command and "--convert-to" in command
            )
        if blocked:
            violations.append(event)
            raise PermissionError(f"Local pilot blocked {event}")

    sys.addaudithook(audit)
    return violations


def make_handler(violations):
    from .app.server import Handler

    class PilotHandler(Handler):
        def _request_allowed(self, method, path):
            # Basic local-browser protection; this is not Stage 2 session auth.
            authority = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if authority not in {f"localhost:{self.server.server_port}",
                                 f"127.0.0.1:{self.server.server_port}"} or (
                origin and origin != f"http://{authority}"
            ):
                self._send(403, b'{"ok":false,"error":"Local origin required"}', "application/json")
                return False
            blocked = (
                path.startswith(("/api/quickbooks/", "/api/update/"))
                or (path.startswith("/api/cloud/") and path != "/api/cloud/status")
                or path == "/open"
                or any(term in path for term in ("pick-folder", "show-folder", "open-folder"))
            )
            if blocked:
                # Application-level failure keeps the existing UI error contract.
                self._api({"ok": False, "error": "Unavailable in the local pilot. Use Downloads for generated files."})
                return False
            return super()._request_allowed(method, path)

        def _artifacts(self):
            root = self.paths.workspace_output_dir.resolve()
            artifacts = {}
            for file in sorted(root.rglob("*")):
                if (file.is_file() and not file.is_symlink()
                        and file.resolve().is_relative_to(root)
                        and file.suffix.lower() in {".pptx", ".pdf"}):
                    artifact_id = hashlib.sha256(file.relative_to(root).as_posix().encode()).hexdigest()
                    artifacts[artifact_id] = file
            return artifacts

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/healthz" or path.startswith("/api/pilot/"):
                if not self._request_allowed("GET", path):
                    return
                if path == "/healthz":
                    self._api({"ok": True, "mode": "local-pilot", "cloud_enabled": False,
                               "provider_workers": False, "blocked_egress_attempts": len(violations)})
                elif path == "/api/pilot/artifacts":
                    self._api({"ok": True, "artifacts": [
                        {"name": file.name, "url": f"/api/pilot/download/{key}",
                         "bytes": file.stat().st_size}
                        for key, file in self._artifacts().items()
                    ]})
                elif path.startswith("/api/pilot/download/"):
                    file = self._artifacts().get(path.rsplit("/", 1)[-1])
                    if file is None:
                        self._send(404, b"Artifact not found", "text/plain")
                        return
                    from urllib.parse import quote
                    data = file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf" if file.suffix == ".pdf" else
                                     "application/vnd.openxmlformats-officedocument.presentationml.presentation")
                    self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(file.name)}")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._send(404, b"Not found", "text/plain")
                return
            super().do_GET()

        def _serve_ui(self):
            from .app.server import _UI_FILE, _APP_VERSION
            html = _UI_FILE.read_text().replace("{{APP_VERSION}}", _APP_VERSION)
            html = html.replace("</body>", '<script src="/ui/js/local_pilot.js"></script></body>')
            self._send(200, html.encode(), "text/html; charset=utf-8")

    return PilotHandler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7665)
    parser.add_argument("--seed-fixtures", action="store_true", help="seed once; preserve later edits")
    args = parser.parse_args(argv)
    container = Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()
    if args.host != "127.0.0.1" and not container:
        parser.error("Non-loopback binding is only allowed inside a local container")
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535")
    try:
        prepare_environment(args.workspace, container=container)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    violations = install_egress_guard()
    from .paths import AppPaths
    from .pilot_fixtures import initialize_workspace
    paths = AppPaths()
    initialize_workspace(paths, seed=args.seed_fixtures)
    from .app.server import create_http_server, _setup_logging
    _setup_logging(paths.workspace_dir)
    server = create_http_server(paths, host=args.host, port=args.port, handler_class=make_handler(violations))
    # Drain in-flight local requests (including conversion) before exiting.
    server.daemon_threads = False
    # Explicitly no desktop main(), updater, cloud, QBO or acceptance workers.
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    worker = threading.Thread(target=server.serve_forever, name="local-pilot-http")
    worker.start()
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}",
                      "mode": "local-pilot", "workspace": str(paths.workspace_dir)}), flush=True)
    try:
        stop.wait()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
        from .app.services.photo_gallery_service import shutdown_photo_gallery_workers
        shutdown_photo_gallery_workers()
        print(json.dumps({"stopped": True, "blocked_egress_attempts": len(violations)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
