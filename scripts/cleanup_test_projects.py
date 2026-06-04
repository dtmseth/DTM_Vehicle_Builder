#!/usr/bin/env python3
"""One-shot cleanup of test-pattern project + draft records.

Run this on any machine that has the polluted data — the script reads
the local workspace, identifies records that match a test pattern,
deletes them locally, AND (in cloud mode) removes them from SharePoint
/Projects/ + /Drafts/ via the same delete path the app uses.

The state-tracked sync in shared_work_service.py then propagates the
deletions to every other device on its next iteration: state has the
record, cloud doesn't, local copy gets removed. So you only need to
run this script on ONE machine — the others catch up via normal sync.

Usage:
    .venv/bin/python scripts/cleanup_test_projects.py            # dry run
    .venv/bin/python scripts/cleanup_test_projects.py --apply    # delete

Test predicates are deliberately conservative — when in doubt the record
is kept. Edit the functions below if your test data has different shapes
than these defaults cover.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running directly from a repo checkout without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from dtm_buildsheet.paths import AppPaths, ensure_workspace  # noqa: E402


# Placeholder values that signal a record is junk — used across both
# project and draft predicates. Easy to extend if you need more matches.
_PLACEHOLDER_AGENCIES = {"Test PD", "Test", ""}
_PLACEHOLDER_NAMES = {"Test Customer", "Test", ""}
_PLACEHOLDER_QUOTE_NUMBERS = {"123456", "12345", ""}


def looks_like_test_project(data: dict) -> bool:
    """Return True if the project record matches a known test pattern."""
    customer = data.get("customer") or {}
    name = str(customer.get("name", "")).strip()
    agency = str(customer.get("agency", "")).strip()
    if agency in _PLACEHOLDER_AGENCIES and name in _PLACEHOLDER_NAMES:
        return True
    if agency == "Test PD":
        return True
    if name in {"Test Customer"}:
        return True
    return False


def looks_like_test_draft(data: dict) -> bool:
    """Return True if the draft matches a known test pattern.

    Drafts created during pipeline smoke tests typically have either a
    'Test PD' agency, placeholder quote numbers (123456), or no agency
    info at all paired with an empty parts list. Real drafts always
    have an agency name; we err toward keeping them.
    """
    vi = data.get("vehicle_info") or {}
    agency = str(vi.get("Agency", "")).strip()
    quote = str(vi.get("QuoteNumber", "")).strip()
    project_id = str(vi.get("ProjectID", "")).strip()
    parts = data.get("parts") or []

    if agency in {"Test PD"}:
        return True
    if quote in _PLACEHOLDER_QUOTE_NUMBERS and project_id in _PLACEHOLDER_QUOTE_NUMBERS:
        return True
    if not agency and not parts:
        return True  # empty stub draft
    return False


def _scan(directory: Path, predicate, filename: str | None = None):
    """Yield (record_id, data, path-to-delete) for every record matching predicate.

    For projects: directory contains subdir-per-record with `project.json`.
    For drafts: directory contains flat `{id}.json` files.
    """
    if not directory.exists():
        return
    if filename is None:
        # Projects layout — subdir per record.
        for record_dir in sorted(directory.iterdir()):
            if not record_dir.is_dir():
                continue
            record_path = record_dir / "project.json"
            if not record_path.exists():
                continue
            try:
                data = json.loads(record_path.read_text("utf-8"))
            except Exception:
                continue
            if predicate(data):
                yield record_dir.name, data, record_dir
    else:
        # Drafts layout — flat JSONs.
        for record_path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(record_path.read_text("utf-8"))
            except Exception:
                continue
            if predicate(data):
                yield record_path.stem, data, record_path


def _summarize_projects(projects):
    for project_id, data, _ in projects[:5]:
        customer = data.get("customer") or {}
        print(f"  - {project_id}  name={customer.get('name', '')!r:25s} "
              f"agency={customer.get('agency', '')!r}")
    if len(projects) > 5:
        print(f"  ... and {len(projects) - 5} more")


def _summarize_drafts(drafts):
    for draft_id, data, _ in drafts[:5]:
        vi = data.get("vehicle_info") or {}
        print(f"  - {draft_id}  agency={vi.get('Agency', '')!r:20s} "
              f"quote={vi.get('QuoteNumber', '')!r}  parts={len(data.get('parts') or [])}")
    if len(drafts) > 5:
        print(f"  ... and {len(drafts) - 5} more")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the records. Without this flag the script only reports.",
    )
    parser.add_argument(
        "--projects-only",
        action="store_true",
        help="Only scan/clean projects (skip drafts).",
    )
    parser.add_argument(
        "--drafts-only",
        action="store_true",
        help="Only scan/clean drafts (skip projects).",
    )
    args = parser.parse_args()

    paths = ensure_workspace()
    print(f"Workspace: {paths.workspace_dir}")

    project_candidates: list[tuple[str, dict, Path]] = []
    draft_candidates: list[tuple[str, dict, Path]] = []

    if not args.drafts_only:
        project_candidates = list(_scan(paths.workspace_projects_dir, looks_like_test_project))
        print(f"\nProjects: {len(project_candidates)} test record(s) found.")
        if project_candidates:
            _summarize_projects(project_candidates)
    if not args.projects_only:
        draft_candidates = list(_scan(paths.workspace_drafts_dir, looks_like_test_draft, filename="*.json"))
        print(f"\nDrafts: {len(draft_candidates)} test record(s) found.")
        if draft_candidates:
            _summarize_drafts(draft_candidates)

    total = len(project_candidates) + len(draft_candidates)
    if total == 0:
        return 0
    if not args.apply:
        print("\nDry run — re-run with --apply to actually delete.")
        return 0

    # Use the same delete_* the app uses so the cloud mirror gets removed
    # in lock-step. delete_*_from_cloud is a no-op outside cloud mode.
    from dtm_buildsheet.inputs.project_drafts import delete_draft  # noqa: E402
    from dtm_buildsheet.inputs.project_entry import delete_project  # noqa: E402

    failures = 0
    for project_id, _data, _dir in project_candidates:
        try:
            delete_project(project_id, paths)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ project {project_id}: {exc}")
            failures += 1
    for draft_id, _data, _path in draft_candidates:
        try:
            delete_draft(draft_id, paths.workspace_drafts_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ draft {draft_id}: {exc}")
            failures += 1

    deleted = total - failures
    print(f"\nDeleted {deleted} record(s); {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
