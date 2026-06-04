#!/usr/bin/env python3
"""One-shot cleanup of "Test PD" / "Test Customer" project records.

Run this on any machine that has the polluted data — the script reads
the local workspace, identifies test records, deletes them, and (in
cloud mode) removes them from SharePoint /Projects/ too. The sync
deletion on SharePoint will reach other machines on their next sync
cycle — but those machines need to run this script themselves to wipe
their local copies, since the sync layer doesn't reconcile deletions
(by design; protects against a transient cloud outage nuking everyone's
local data).

Usage:
    .venv/bin/python scripts/cleanup_test_projects.py            # dry run
    .venv/bin/python scripts/cleanup_test_projects.py --apply    # actually delete

Identifies test records by exact-match on agency name "Test PD" or
customer name "Test Customer" / empty strings — change the predicates
below if you need a different match.
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


def looks_like_test_record(data: dict) -> bool:
    """Return True if the project record matches the Test PD pattern."""
    customer = data.get("customer") or {}
    name = str(customer.get("name", "")).strip()
    agency = str(customer.get("agency", "")).strip()
    if agency == "Test PD":
        return True
    if name in {"Test Customer", "Test"}:
        return True
    if not name and not agency and len(data.get("build_units", [])) <= 1:
        return True  # empty placeholder created by accidental wizard save
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the records. Without this flag the script only reports.",
    )
    args = parser.parse_args()

    paths = ensure_workspace()
    print(f"Workspace: {paths.workspace_projects_dir}")
    projects_dir = paths.workspace_projects_dir
    if not projects_dir.exists():
        print("  (no projects directory)")
        return 0

    candidates: list[tuple[str, dict, Path]] = []
    kept = 0
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        record_path = project_dir / "project.json"
        if not record_path.exists():
            continue
        try:
            data = json.loads(record_path.read_text("utf-8"))
        except Exception:
            # Don't touch unreadable records — could be in-progress writes.
            print(f"  ?? unreadable: {project_dir.name}")
            continue
        if looks_like_test_record(data):
            candidates.append((project_dir.name, data, project_dir))
        else:
            kept += 1

    print(f"\nFound {len(candidates)} test record(s); {kept} real record(s) will be kept.")
    if not candidates:
        return 0

    # Sample the first few so the user sees what they're deleting.
    for project_id, data, _ in candidates[:5]:
        customer = data.get("customer") or {}
        print(
            f"  - {project_id}  name={customer.get('name', '')!r:25s} "
            f"agency={customer.get('agency', '')!r}"
        )
    if len(candidates) > 5:
        print(f"  ... and {len(candidates) - 5} more")

    if not args.apply:
        print("\nDry run — re-run with --apply to actually delete.")
        return 0

    # Use the same delete_project that the app uses, so the cloud mirror
    # gets removed in lock-step with the local file. No need to handle
    # cloud-vs-local mode here; delete_project_from_cloud is a no-op
    # outside cloud mode.
    from dtm_buildsheet.inputs.project_entry import delete_project  # noqa: E402

    failures = 0
    for project_id, _data, _dir in candidates:
        try:
            delete_project(project_id, paths)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {project_id}: {exc}")
            failures += 1
    deleted = len(candidates) - failures
    print(f"\nDeleted {deleted} record(s); {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
