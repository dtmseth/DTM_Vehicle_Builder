#!/usr/bin/env python3
"""Browser smoke-suite runner (§8.1 Step 1c).

Usage (from the repo root):
    .venv/bin/python tools/ui_smoke/run_smoke.py            # all flows
    .venv/bin/python tools/ui_smoke/run_smoke.py tab_load   # one flow

Isolation model: ONE SUBPROCESS PER FLOW. Each child process builds its own
throwaway workspace, boots the app server in-process, launches a fresh
headless browser context, runs exactly one flow, and exits. That gives every
flow a hard page load AND a fresh app process/workspace (roadmap §3.1: no
flow may inherit DOM/JS state or server-side module caches from a previous
one; state bleed is a suite defect, not a retry candidate).

Not part of default pytest (needs Playwright + a running app). Requires:
    pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent


# ── child: run one flow hermetically ─────────────────────────────────────────

def run_child(flow_name: str) -> int:
    # Env + netguard must be in place before any dtm_buildsheet import runs.
    os.environ["DTM_CLOUD"] = "0"
    sys.path.insert(0, str(HERE))
    from flows import FLOWS
    from hermetic import NETGUARD_VIOLATIONS, build_workspace, boot_server, install_netguard

    install_netguard()
    tmp = Path(tempfile.mkdtemp(prefix=f"dtm_ui_smoke_{flow_name}_"))
    paths = build_workspace(tmp)
    base_url = boot_server(paths)

    console_errors: list[str] = []
    external_requests: list[str] = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()

        def on_route(route):
            host = urlparse(route.request.url).hostname or ""
            if host not in ("127.0.0.1", "localhost", "::1"):
                external_requests.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        # Browser-side capture: catches any external request the page makes
        # (CDN fonts, telemetry, absolute URLs). Server-side egress is caught
        # by the hermetic.py netguard — the two layers together are the
        # zero-Graph assertion.
        context.route("**/*", on_route)

        page = context.new_page()
        page.on(
            "console",
            lambda msg: console_errors.append(f"console.{msg.type}: {msg.text}")
            if msg.type == "error"
            else None,
        )
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

        flow_error: str | None = None
        try:
            FLOWS[flow_name](page, base_url)
        except Exception as exc:  # noqa: BLE001 — reported in the verdict
            flow_error = f"{type(exc).__name__}: {exc}"
        finally:
            # Some project-detail flows leave long-lived polling/fetch work in
            # the page. Navigate away first so Chromium can shut down cleanly
            # instead of waiting indefinitely on those page connections.
            try:
                page.goto("about:blank", wait_until="commit", timeout=5000)
            except Exception:
                pass
            browser.close()

    verdict = {
        "flow": flow_name,
        "ok": not (flow_error or console_errors or external_requests or NETGUARD_VIOLATIONS),
        "flow_error": flow_error,
        "console_errors": console_errors,
        "external_browser_requests": external_requests,
        "netguard_violations": list(NETGUARD_VIOLATIONS),
        "workspace": str(tmp),
    }
    print(json.dumps(verdict, indent=2))

    if verdict["ok"]:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print(f"[ui_smoke] workspace kept for debugging: {tmp}", file=sys.stderr)
    return 0 if verdict["ok"] else 1


# ── parent: one subprocess per flow ──────────────────────────────────────────

def main(argv: list[str]) -> int:
    if argv and argv[0] == "--child":
        return run_child(argv[1])

    sys.path.insert(0, str(HERE))
    from flows import FLOWS

    wanted = argv or list(FLOWS)
    unknown = [f for f in wanted if f not in FLOWS]
    if unknown:
        print(f"Unknown flow(s): {', '.join(unknown)}. Available: {', '.join(FLOWS)}")
        return 2

    failures = 0
    for name in wanted:
        print(f"── flow: {name} " + "─" * (60 - len(name)))
        proc = subprocess.run(
            [sys.executable, str(HERE / "run_smoke.py"), "--child", name],
            cwd=str(HERE.parents[1]),
        )
        if proc.returncode != 0:
            failures += 1

    print(f"\n{len(wanted) - failures}/{len(wanted)} flows passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
