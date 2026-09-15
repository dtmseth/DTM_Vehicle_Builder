#!/usr/bin/env python3
"""Compact, change-aware local verification.

Passing command output is captured and reduced to one summary line. Failures
show only the first failure because the next useful action is to fix it, not
to continue printing hundreds of unrelated passes.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PYTEST_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("hosted", "request_context", "wiring.py", "operations_access_service.py"), (
        "tests/test_hosted_boundary.py", "tests/test_request_access_service.py",
        "tests/test_cloud_adapters.py", "tests/test_operations_read_api.py",
    )),
    (("headless", "pilot", "paths.py", "__init__.py"), (
        "tests/test_local_pilot.py", "tests/test_paths.py", "tests/test_server_resilience.py",
    )),
    (("export_service.py",), ("tests/test_exports.py", "tests/test_local_pilot.py")),
    (("calendar",), ("tests/test_calendar.py", "tests/test_calendar_workspace.py")),
    (("operations", "operations_policy.py"), (
        "tests/test_operations_backend.py",
        "tests/test_operations_read_api.py",
        "tests/test_project_operations_sync.py",
    )),
    (("request_access_service.py", "app/server.py", "ui/js/tabs.js"), (
        "tests/test_request_access_service.py",
        "tests/test_operations_read_api.py",
        "tests/test_server_resilience.py",
    )),
    (("ui/js/projects/", "routes/projects.py", "project_service.py"), (
        "tests/test_projects_api.py",
        "tests/test_project_operations_sync.py",
        "tests/test_project_codec.py",
    )),
    (("agency_service.py",), (
        "tests/test_agency_service.py",
        "tests/test_qb_customer_sync.py",
    )),
    (("quickbooks", "qb_"), (
        "tests/test_qb_sync_service.py",
        "tests/test_qb_customer_sync.py",
        "tests/test_qb_estimate_service.py",
        "tests/test_quickbooks_service.py",
        "tests/test_quickbooks_route_errors.py",
    )),
    (("reference_photo", "photo_gallery"), (
        "tests/test_reference_photo_service.py",
        "tests/test_reference_photos.py",
        "tests/test_photo_gallery_service.py",
    )),
    (("finalization", "shop_publication"), (
        "tests/test_finalization_service.py",
        "tests/test_shop_publication_service.py",
    )),
    (("parts_db", "part_picker", "manifest_editor"), (
        "tests/test_parts_db_service.py",
        "tests/test_parts_db_routes.py",
        "tests/test_parts_db_schema_validation.py",
    )),
    (("render_ppt", "planning/", "planner.py"), (
        "tests/test_planner.py",
        "tests/test_render_ppt.py",
        "tests/golden",
    )),
)

SMOKE_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("project_types", "project_models", "project_codec", "project_service", "ui/js/projects/", "calendar", "finalization", "render_ppt"), ("service_project",)),
    (("ui/", "app/server.py", "request_access_service.py", "operations", "calendar"), ("tab_load",)),
    (("ui/js/projects/detail_builds.js",), (
        "overview_unit_notes_and_preconfig_qb",
        "final_build_signoff",
        "quickbooks_estimate_review_modal",
        "quickbooks_batch_project_checklist",
    )),
    (("part_picker", "manifest_editor", "parts_db"), (
        "picker_browse_tree",
        "part_details_and_console",
        "picker_multi_add",
    )),
    (("preview_canvas", "render_ppt"), ("preview_drag_mirroring",)),
)


def _git_changed_files() -> list[str]:
    commands = (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    files: set[str] = set()
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
        files.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    # User-owned artifacts are never implementation inputs (py_compile would
    # otherwise create __pycache__ inside an untracked output/ or tmp/ tree).
    return sorted(name for name in files if not name.startswith(("output/", "tmp/")))


def _targets_for(files: list[str], rules, *, include_changed_tests: bool = False) -> list[str]:
    selected: set[str] = set()
    for file_name in files:
        if file_name.startswith("docs/") or file_name == "AGENTS.md":
            continue
        lowered = file_name.lower()
        for needles, targets in rules:
            if any(needle in lowered for needle in needles):
                selected.update(targets)
        if include_changed_tests and file_name.startswith("tests/") and file_name.endswith(".py"):
            selected.add(file_name)
    return sorted(selected)


def _summary(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if " passed" in line or " failed" in line or " skipped" in line:
            return line.strip("= ")
    return lines[-1] if lines else "completed"


def _run(label: str, command: list[str]) -> bool:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    elapsed = time.monotonic() - started
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode == 0:
        print(f"PASS  {label} ({elapsed:.1f}s) — {_summary(combined)}")
        return True
    print(f"FAIL  {label} ({elapsed:.1f}s)")
    if combined:
        print(combined)
    return False


def _syntax_files(files: list[str]) -> tuple[list[str], list[str]]:
    python_files = [name for name in files if name.endswith(".py") and (ROOT / name).is_file()]
    js_files = [name for name in files if name.endswith(".js") and (ROOT / name).is_file()]
    return python_files, js_files


def _run_js_syntax(files: list[str]) -> bool:
    started = time.monotonic()
    for file_name in files:
        result = subprocess.run(
            ["node", "--check", file_name], cwd=ROOT, capture_output=True, text=True
        )
        if result.returncode:
            print(f"FAIL  JS syntax: {file_name} ({time.monotonic() - started:.1f}s)")
            details = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            if details:
                print(details)
            return False
    print(f"PASS  JS syntax ({len(files)} file{'s' if len(files) != 1 else ''}, {time.monotonic() - started:.1f}s)")
    return True


def _run_changed(*, skip_smoke: bool) -> bool:
    files = _git_changed_files()
    python_files, js_files = _syntax_files(files)
    ok = True
    if python_files:
        ok = _run("Python syntax", [sys.executable, "-m", "py_compile", *python_files]) and ok
    if js_files:
        ok = _run_js_syntax(js_files) and ok

    tests = _targets_for(files, PYTEST_RULES, include_changed_tests=True)
    if tests:
        ok = _run(
            f"focused pytest ({len(tests)} target{'s' if len(tests) != 1 else ''})",
            [sys.executable, "-m", "pytest", "--maxfail=1", *tests],
        ) and ok
    else:
        print("SKIP  pytest — no changed code mapped to a test area")

    smokes = [] if skip_smoke else _targets_for(files, SMOKE_RULES)
    if smokes:
        ok = _run(
            f"focused browser smoke ({len(smokes)} flow{'s' if len(smokes) != 1 else ''})",
            [sys.executable, "tools/ui_smoke/run_smoke.py", *smokes],
        ) and ok
    elif not skip_smoke:
        print("SKIP  browser smoke — no changed UI area mapped to a flow")
    return ok


def _run_release(*, skip_smoke: bool) -> bool:
    ok = _run(
        "release pytest",
        [sys.executable, "-m", "pytest", "--maxfail=1"],
    )
    if ok and not skip_smoke:
        ok = _run("release browser smoke", [sys.executable, "tools/ui_smoke/run_smoke.py"])
    return ok


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("changed", "release"), nargs="?", default="changed")
    parser.add_argument("--skip-smoke", action="store_true", help="skip browser flows")
    args = parser.parse_args(argv)
    passed = (
        _run_release(skip_smoke=args.skip_smoke)
        if args.profile == "release"
        else _run_changed(skip_smoke=args.skip_smoke)
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
