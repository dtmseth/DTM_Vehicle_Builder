#!/usr/bin/env python3
"""Survey + delete test-pattern records from SharePoint /Settings/.

The PROPOSAL pipeline (used by agencies, sales reps, presets) doesn't have
a delete-from-cloud mechanism today, so the rogue test runs from a
developer machine left behind a bunch of test-pattern files in:

  /Settings/agencies/
  /Settings/sales_reps/
  /Settings/presets/

Those files live on SharePoint and also in the dtm-shared-settings repo
at resources/config/. This script cleans up the SharePoint side directly
via Graph (using the same StorageProvider the app uses). The repo-side
cleanup is a manual ``git rm`` + commit + PR on dtm-shared-settings if
you want the repo to stop being the source for a bulk re-publish.

Usage:
    .venv/bin/python scripts/cleanup_sharepoint_test_data.py            # dry run
    .venv/bin/python scripts/cleanup_sharepoint_test_data.py --apply    # delete

Requires the same cloud_config.json + signed-in MSAL token the app uses.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Allow running directly from a repo checkout without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

# Bypass the pytest-only guard in shared_work_service / wiring. This script
# is operator tooling, not a test, so we want real cloud access.
os.environ.pop("PYTEST_CURRENT_TEST", None)


_REMOTE_FOLDERS = ("Settings/agencies", "Settings/sales_reps", "Settings/presets")


# Agencies created by tests show up under a small set of placeholder
# names — never real customers.
_TEST_AGENCY_NAMES = {
    "Test PD", "Test", "",
    "Alpha PD", "Beta SO", "Gamma Sheriff", "Delta County",
}


def _looks_like_test_agency(data: dict) -> bool:
    name = str(data.get("name", "")).strip()
    if "Test" in name:
        return True
    if name in _TEST_AGENCY_NAMES:
        return True
    contact = str(data.get("contact_name", "")).strip()
    return contact in {"Test User", "Test", ""} and not name


# Sales reps created by test fixtures use single-given-name placeholders.
_TEST_REP_FIRST_NAMES = {
    "Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi",
}


def _looks_like_test_rep(data: dict) -> bool:
    name = str(data.get("name", "")).strip()
    if "Test" in name:
        return True
    email = str(data.get("email", "")).strip()
    if email.endswith("@example.invalid"):
        return True
    # Pattern: "Carol" / "Bob Brown" / "Dave Davis" — single name or
    # first-name + surname-starting-with-same-letter that maps onto the
    # alphabet placeholder set.
    parts = name.split()
    if not parts:
        return True
    first = parts[0]
    if first in _TEST_REP_FIRST_NAMES and len(parts) <= 2:
        # Avoid eating a real "Alice Johnson" — but we don't have any
        # real reps with those first names today, so this is safe.
        return True
    return False


def _looks_like_test_preset(data: dict) -> bool:
    label = str(data.get("label", "")).strip()
    if "Test" in label:
        return True
    preset_id = str(data.get("preset_id", "")).strip()
    parts = data.get("parts") or []
    # Test-fixture preset IDs end in a 6-hex-character suffix (uuid4().hex[:6])
    # because save_preset auto-generates that when no preset_id is passed in.
    # Combined with an empty parts list, this is a near-certain test record.
    if not parts and re.search(r"_[0-9a-f]{6}$", preset_id):
        return True
    if not label and not parts:
        return True
    return False


_PREDICATES = {
    "Settings/agencies": _looks_like_test_agency,
    "Settings/sales_reps": _looks_like_test_rep,
    "Settings/presets": _looks_like_test_preset,
}


def _get_storage():
    """Construct the cloud storage adapter the app would use.

    Mirrors wiring.build_internal_team_bundle but stops at storage —
    no proposal gateway / notification setup needed here.
    """
    from dtm_buildsheet.app.adapters.cloud.config import load_cloud_config_from_env
    from dtm_buildsheet.app.adapters.cloud.msal_client import MsalClient
    from dtm_buildsheet.app.adapters.cloud.sharepoint_graph_provider import (
        SharePointGraphProvider,
    )

    config = load_cloud_config_from_env()
    msal = MsalClient(config)
    return SharePointGraphProvider(
        config,
        token_provider=lambda: msal.acquire_token(interactive_ok=True),
    )


def _survey(storage, folder: str, predicate):
    """Return [(path, parsed_json)] for files in *folder* that match *predicate*."""
    try:
        paths = storage.list_files(folder)
    except FileNotFoundError:
        print(f"  (folder missing: {folder})")
        return []
    matches = []
    for path in paths:
        if not path.endswith(".json") or path.endswith(".meta.json"):
            continue
        try:
            raw = storage.read_text(path)
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"  ?? unreadable: {path}  ({exc})")
            continue
        if predicate(data):
            matches.append((path, data))
    return matches


def _summarize(folder: str, matches):
    print(f"\n{folder}: {len(matches)} test-pattern file(s).")
    for path, data in matches[:5]:
        label = data.get("name") or data.get("label") or "(unnamed)"
        print(f"  - {path}  → {label!r}")
    if len(matches) > 5:
        print(f"  ... and {len(matches) - 5} more")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the records from SharePoint. Without this flag the script only surveys.",
    )
    args = parser.parse_args()

    try:
        storage = _get_storage()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not construct cloud storage: {exc}")
        print("Make sure cloud_config.json is present and you're signed in to M365.")
        return 1

    all_matches: list[tuple[str, list]] = []
    for folder in _REMOTE_FOLDERS:
        matches = _survey(storage, folder, _PREDICATES[folder])
        _summarize(folder, matches)
        all_matches.append((folder, matches))

    total = sum(len(m) for _, m in all_matches)
    if total == 0:
        print("\nNothing to clean up. SharePoint is already clean.")
        return 0
    if not args.apply:
        print("\nDry run — re-run with --apply to actually delete from SharePoint.")
        print("Note: this only cleans /Settings/ on SharePoint. The same files")
        print("still exist in dtm-shared-settings/resources/config/ — clean those")
        print("up with a separate `git rm` + commit + PR on the settings repo")
        print("if you want them gone permanently (a future bulk-publish run would")
        print("otherwise re-upload them).")
        return 0

    failures = 0
    deleted_count = 0
    for _folder, matches in all_matches:
        for path, _data in matches:
            for target in (path, path + ".meta.json"):
                try:
                    storage.delete(target)
                    deleted_count += 1
                except FileNotFoundError:
                    pass  # already gone
                except Exception as exc:  # noqa: BLE001
                    print(f"  ✗ {target}: {exc}")
                    failures += 1
    print(f"\nDeleted {deleted_count} file(s) from SharePoint; {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
