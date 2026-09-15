#!/usr/bin/env python3
"""Exercise the real pilot UI, save, generation, PDF and browser downloads.

Use --launch-workspace for native measurements, or --url for a local container.
All artifacts/results must stay outside the checkout. Requires Playwright and
PyMuPDF in the test client, not in the running application's container.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def api(url, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(url + path, data=data, headers={"Content-Type": "application/json"}), timeout=150) as response:
        result = json.load(response)
    if result.get("ok") is False:
        raise RuntimeError(result)
    return result


class Sampler:
    """Sample process-tree RSS and OS-reported CPU; not container/cgroup accounting."""
    def __init__(self, pid):
        self.pid = pid
        self.peak_kib = 0
        self.latest = {}
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self.run)
        self.worker.start()

    def run(self):
        while not self.stop.is_set():
            result = subprocess.run(["ps", "-axo", "pid=,ppid=,rss=,%cpu="], capture_output=True, text=True, check=True)
            rows = [line.split() for line in result.stdout.splitlines() if len(line.split()) == 4]
            children = {self.pid}
            while True:
                expanded = children | {int(pid) for pid, parent, _, _ in rows if int(parent) in children}
                if expanded == children:
                    break
                children = expanded
            selected = [row for row in rows if int(row[0]) in children]
            rss = sum(int(row[2]) for row in selected)
            self.peak_kib = max(self.peak_kib, rss)
            self.latest = {"rss_mib": round(rss / 1024, 2),
                           "os_reported_cpu_percent": round(sum(float(row[3]) for row in selected), 2)}
            self.stop.wait(0.2)

    def finish(self):
        self.stop.set()
        self.worker.join()


def launch(workspace, log):
    env = dict(os.environ, DTM_CLOUD="0")
    for key in ("DTM_LOCAL_PILOT", "DTM_WORKSPACE_DIR", "PYTEST_CURRENT_TEST", "DTM_ALLOW_CLOUD_IN_TESTS"):
        env.pop(key, None)
    started = time.monotonic()
    process = subprocess.Popen([
        sys.executable, "-m", "dtm_buildsheet.headless", "--workspace", str(workspace),
        "--seed-fixtures", "--port", "0",
    ], env=env, stdout=subprocess.PIPE, stderr=log, text=True)
    try:
        if not select.select([process.stdout], [], [], 30)[0]:
            raise RuntimeError("Pilot startup timed out")
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("Pilot startup failed; inspect server.log")
        startup = json.loads(line)
        api(startup["url"], "/healthz")
        return process, startup["url"], round(time.monotonic() - started, 3)
    except BaseException:
        process.terminate()
        process.wait(timeout=150)
        raise


def stop_server(process):
    started = time.monotonic()
    process.terminate()
    process.wait(timeout=150)
    assert process.returncode == 0, process.returncode
    return round(time.monotonic() - started, 3)


def exercise(url, results, report, sampler, *, ui_only=False):
    from playwright.sync_api import sync_playwright
    errors, external, http_errors = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)

        def route(request):
            if urlparse(request.request.url).netloc != urlparse(url).netloc:
                external.append(request.request.url)
                request.abort()
            else:
                request.continue_()

        context.route("**/*", route)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("response", lambda response: http_errors.append({"status": response.status, "url": response.url})
                if response.status >= 400 else None)
        page.on("dialog", lambda dialog: dialog.accept())
        started = time.monotonic()
        page.goto(url, wait_until="networkidle")
        report["ui_initial_load_seconds"] = round(time.monotonic() - started, 3)
        started = time.monotonic()
        page.click(".htab[data-tab='projects']")
        page.click('[data-project-list-status="started"]')
        page.get_by_role("button", name="Open", exact=True).first.click()
        page.wait_for_selector("#proj-detail-view:not([hidden])")
        page.locator(".proj-build-card--openable .proj-build-card-label").first.click()
        field = page.locator('[data-pbe-note-category="INSTALLATION NOTES"]')
        try:
            field.wait_for(state="visible")
        except Exception:
            page.screenshot(path=str(results / "editor-failure.png"), full_page=True)
            (results / "editor-failure.html").write_text(page.content())
            report.update(browser_errors=errors, browser_http_errors=http_errors,
                          external_browser_requests=external)
            raise
        report["ui_open_editor_seconds"] = round(time.monotonic() - started, 3)
        started = time.monotonic()
        field.fill("Synthetic UI save verified. Route wiring behind trim and label all fuses.")
        page.wait_for_function("document.getElementById('pbe-final-notes-status').textContent === 'Notes saved'")
        report["ui_save_seconds"] = round(time.monotonic() - started, 3)
        page.screenshot(path=str(results / "editor.png"), full_page=True)
        saved = [api(url, f"/api/draft/pilot-{label}-draft")["draft"] for label in ("typical", "dense")]
        assert any("Synthetic UI save verified." in str(draft["notes"]) for draft in saved)
        report["ui_edit_saved"] = True
        report["exports"] = []
        for label in (() if ui_only else ("typical", "dense")):
            if sampler:
                sampler.peak_kib = 0
            started = time.monotonic()
            generated = api(url, "/api/draft/generate", {"draft_id": f"pilot-{label}-draft",
                                                         "project_id": f"pilot-{label}"})
            pptx_seconds = time.monotonic() - started
            assert generated["placements_count"] > 0, generated
            assert not any("Unmapped part" in warning or "Reference photo unavailable" in warning
                           for warning in generated["all_warnings"]), generated
            started = time.monotonic()
            pdf = api(url, "/api/export/pdf", {
                "output_path": generated["output_path"], "project_id": f"pilot-{label}",
                "unit_id": f"{label}-group", "individual_id": f"{label}-vehicle",
            })
            pdf_seconds = time.monotonic() - started
            peak_mib = round(sampler.peak_kib / 1024, 2) if sampler else None
            page.locator(".local-pilot-panel summary").click()
            if not page.locator(".local-pilot-panel").evaluate("el => el.open"):
                page.locator(".local-pilot-panel summary").click()
            page.get_by_role("button", name="Refresh downloads", exact=True).click()
            for name in (generated["output_name"], pdf["pdf_name"]):
                with page.expect_download() as download_info:
                    page.get_by_role("link", name=name, exact=True).click()
                download = download_info.value
                destination = results / f"{label}{Path(name).suffix}"
                download.save_as(destination)
                assert destination.stat().st_size > 1000
                # Compare the browser download with the server artifact bytes.
                artifact = next(item for item in api(url, "/api/pilot/artifacts")["artifacts"] if item["name"] == name)
                with urlopen(url + artifact["url"], timeout=30) as response:
                    assert hashlib.sha256(destination.read_bytes()).digest() == hashlib.sha256(response.read()).digest()
            import fitz
            with fitz.open(results / f"{label}.pdf") as document:
                pages = len(document)
                assert pages >= (10 if label == "dense" else 5)
                if label == "dense":
                    assert sum("Synthetic mounting example" in page.get_text() for page in document) >= 3
                fonts = sorted({font[3] for page in document for font in page.get_fonts()})
            report["exports"].append({
                "fixture": label, "parts": generated["parts_count"], "placements": generated["placements_count"],
                "pptx_seconds": round(pptx_seconds, 3), "pdf_seconds": round(pdf_seconds, 3),
                "sampled_peak_process_tree_rss_mib": peak_mib, "pages": pages, "pdf_fonts": fonts,
                "pptx_bytes": (results / f"{label}.pptx").stat().st_size,
                "pdf_bytes": (results / f"{label}.pdf").stat().st_size,
                "warnings": dict(Counter(generated["all_warnings"])),
            })
        report["health"] = api(url, "/healthz")
        report["browser_errors"] = errors
        report["browser_http_errors"] = http_errors
        report["external_browser_requests"] = external
        assert report["health"]["blocked_egress_attempts"] == 0
        assert not errors and not external, (errors, external)
        page.goto("about:blank")
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-workspace", type=Path)
    parser.add_argument("--url")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--ui-only", action="store_true", help="interactive/save proof without exports")
    args = parser.parse_args()
    if bool(args.launch_workspace) == bool(args.url):
        parser.error("Choose --launch-workspace or --url")
    root = Path(__file__).resolve().parents[2]
    if args.results.resolve().is_relative_to(root):
        parser.error("Results must be outside the checkout")
    if args.results.exists() and any(args.results.iterdir()):
        parser.error("Use a new empty results directory")
    if args.url and urlparse(args.url).hostname not in {"localhost", "127.0.0.1"}:
        parser.error("Only a local pilot URL is allowed")
    args.results.mkdir(parents=True, exist_ok=True)
    report = {"platform": platform.platform(), "architecture": platform.machine(),
              "python": platform.python_version(), "environment": "native" if args.launch_workspace else "external local container",
              "container_sizing_verified": False}
    process = sampler = None
    with (args.results / "server.log").open("w") as log:
        try:
            if args.launch_workspace:
                process, url, report["cold_start_seconds"] = launch(args.launch_workspace, log)
                report["first_shutdown_seconds"] = stop_server(process)
                process = None
                process, url, report["warm_start_seconds"] = launch(args.launch_workspace, log)
                sampler = Sampler(process.pid)
                time.sleep(5)
                report["idle_process_tree"] = dict(sampler.latest)
            else:
                url = args.url
            exercise(url, args.results, report, sampler, ui_only=args.ui_only)
            report["ok"] = True
        except Exception as exc:
            report["ok"] = False
            report["error"] = str(exc)
            raise
        finally:
            if sampler:
                sampler.finish()
            if process:
                report["shutdown_seconds"] = stop_server(process)
            (args.results / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
