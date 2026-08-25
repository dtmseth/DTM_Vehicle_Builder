"""Hermetic launch helpers for the browser smoke harness (§8.1 Step 1c).

Everything in this package is harness-side: zero production-code changes.
The app's HTTP surface is booted in-process (``Handler`` + ``_ReuseHTTPServer``
from ``dtm_buildsheet.app.server``) against a throwaway workspace, with cloud
hard-disabled and a process-wide network tripwire that blocks and records any
non-loopback egress.

Design notes (full rationale in docs/audit/UI_SMOKE_SPEC.md):

- The pytest cloud guard (``PYTEST_CURRENT_TEST``) does NOT protect this
  harness — the app runs live. Isolation is layered instead:
    1. ``DTM_CLOUD=0`` in the environment. This is load-bearing:
       ``cloud/config.py`` reads the module-level ``WORKSPACE_DIR`` constant
       (the repo's live workspace in dev, where cloud_config.json has
       ``enabled: true``), NOT the injected AppPaths — so a hermetic
       workspace alone would still enter cloud mode. The env var wins.
    2. A throwaway workspace via ``dataclasses.replace`` on ``AppPaths``
       (same hermetic-AppPaths concept as docs/audit/GOLDEN_MASTER_SPEC.md §5.3),
       with no cloud_config.json ever seeded into it.
    3. The netguard below: any DNS lookup or socket connect to a
       non-loopback host from the app/server process raises and is recorded.
- We do NOT call ``ensure_workspace()``: it seeds cloud_config.json from
  resources/default_data/ by design (teammate first-launch convenience),
  which is exactly what a hermetic run must not have.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import socket
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "workspace"

# Violations recorded by the netguard. A flow passes only if this is empty.
NETGUARD_VIOLATIONS: list[str] = []

_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_loopback(host: object) -> bool:
    h = str(host).strip("[]").lower()
    return h in _LOOPBACK_NAMES or h.startswith("127.")


def install_netguard() -> None:
    """Block + record any attempt by THIS process to reach a non-loopback host.

    Must be installed before the app server handles any request. Graph and
    SharePoint traffic originates in the Python server (requests/msal), not
    the browser, so the zero-Graph assertion has to live at this level —
    Playwright's network capture only sees browser-originated requests.

    ``getaddrinfo`` catches everything that resolves a hostname (requests,
    msal, urllib all do); the ``connect`` patch is the backstop for
    direct-to-IP dials. Playwright itself is unaffected: its driver is a
    subprocess reached over stdio pipes, and the browser is a separate
    process that only talks back to 127.0.0.1.
    """
    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            NETGUARD_VIOLATIONS.append(f"getaddrinfo:{host}")
            raise socket.gaierror(f"ui_smoke netguard blocked DNS lookup: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = guarded_getaddrinfo

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        # AF_UNIX addresses are str/bytes paths — always local, pass through.
        if isinstance(address, tuple) and address and not _is_loopback(address[0]):
            NETGUARD_VIOLATIONS.append(f"connect:{address!r}")
            raise OSError(f"ui_smoke netguard blocked connect: {address!r}")
        return real_connect(self, address)

    socket.socket.connect = guarded_connect


def build_workspace(root: Path):
    """Create a fresh throwaway workspace under *root* and return a hermetic
    ``AppPaths`` pointed at it.

    Seeding mirrors what ``ensure_workspace()`` does for a bundled install
    (top-level ``*.json`` from resources/config, full assets/presets trees),
    minus the cloud_config.json seeding, plus an optional committed fixtures
    overlay (``tools/ui_smoke/fixtures/workspace/``) for the stateful flows.
    """
    from dtm_buildsheet.paths import (
        ASSETS_DIR,
        BUNDLED_PRESETS_DIR,
        DEFAULT_CONFIG_DIR,
        AppPaths,
    )

    ws = root / "workspace"
    overrides = {
        "workspace_dir": ws,
        "workspace_config_dir": ws / "config",
        "workspace_assets_dir": ws / "assets",
        "workspace_input_dir": ws / "input",
        "workspace_output_dir": ws / "output",
        "workspace_drafts_dir": ws / "drafts",
        "workspace_presets_dir": ws / "presets",
        "workspace_projects_dir": ws / "projects",
    }
    for d in overrides.values():
        d.mkdir(parents=True, exist_ok=True)

    for src in sorted(DEFAULT_CONFIG_DIR.glob("*.json")):
        shutil.copyfile(src, overrides["workspace_config_dir"] / src.name)
    shutil.copytree(ASSETS_DIR, overrides["workspace_assets_dir"], dirs_exist_ok=True)
    shutil.copytree(BUNDLED_PRESETS_DIR, overrides["workspace_presets_dir"], dirs_exist_ok=True)

    if FIXTURES_DIR.exists():
        shutil.copytree(FIXTURES_DIR, ws, dirs_exist_ok=True)

    assert not (ws / "cloud_config.json").exists(), "hermetic workspace must have no cloud_config.json"
    return dataclasses.replace(AppPaths(), **overrides)


def boot_server(paths) -> str:
    """Boot the app's HTTP surface in-process against *paths*; return base URL.

    Replicates ``app.server.main()`` minus: the pywebview window / browser
    open, the queued-installer check, and the periodic-sync + QuickBooks
    background threads (both are inert no-ops with cloud off / no QB company
    configured; excluding them keeps background nondeterminism out of smoke
    timing — see UI_SMOKE_SPEC.md §2.4 for the faithfulness argument).

    Binds port 0 (OS-assigned) so a running dev instance on 7655 never
    collides with a smoke run; the UI uses relative URLs throughout, so the
    port is invisible to it.
    """
    assert os.environ.get("DTM_CLOUD") == "0", "DTM_CLOUD=0 must be set before booting"
    assert NETGUARD_VIOLATIONS is not None  # netguard module state exists

    from dtm_buildsheet.app import server as app_server
    from dtm_buildsheet.app.services import agency_service, qb_sync_service, sales_rep_service

    app_server._setup_logging(paths.workspace_dir)
    agency_service.warmup_cache(paths)
    sales_rep_service.warmup_cache(paths)

    # Agency smoke flows exercise the local save/default-preference contract,
    # not the optional QuickBooks mirror.  Keep the harness from opening the
    # workstation's real OS-keychain store while handling that local request.
    qb_sync_service.push_agency_after_save = lambda _paths, _agency_id: {
        "ok": True,
        "skipped": "ui_smoke",
    }

    app_server.Handler.paths = paths
    server = app_server._ReuseHTTPServer(("127.0.0.1", 0), app_server.Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="ui-smoke-server").start()
    port = server.server_address[1]
    return f"http://127.0.0.1:{port}"
