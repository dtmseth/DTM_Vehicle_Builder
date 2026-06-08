#!/usr/bin/env python3
"""One-shot: publish local agencies / sales_reps / presets to SharePoint.

Recovery tool for when the proposal-based save pipeline fell behind and
SharePoint is missing records that exist locally. Walks the dev workspace
for each per-record entity type and uploads any file that's missing on
SharePoint (or whose content differs) via the same direct write the new
save handlers now use.

Other devices see the result on their next 60s sync — local files they
already have stay (UUID match means same record), new ones get downloaded,
records SP didn't have at all flow through to everyone.

Usage:
    .venv/bin/python scripts/publish_local_settings_to_cloud.py        # dry run
    .venv/bin/python scripts/publish_local_settings_to_cloud.py --apply

Cloud config + signed-in MSAL token required.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

# Bypass the pytest-only guard in wiring + shared_work_service.
os.environ.pop("PYTEST_CURRENT_TEST", None)


def _get_storage():
    from dtm_buildsheet.app.adapters.cloud.config import load_cloud_config_from_env
    from dtm_buildsheet.app.adapters.cloud.msal_client import MsalClient
    from dtm_buildsheet.app.adapters.cloud.sharepoint_graph_provider import (
        SharePointGraphProvider,
    )
    config = load_cloud_config_from_env()
    msal = MsalClient(config)
    return SharePointGraphProvider(
        config, token_provider=lambda: msal.acquire_token(interactive_ok=True),
    )


def _local_files(directory: Path) -> dict[str, str]:
    """Return {filename: contents} for *.json (skipping dotfiles)."""
    out: dict[str, str] = {}
    if not directory.exists():
        return out
    for p in sorted(directory.glob("*.json")):
        if p.name.startswith("."):
            continue
        try:
            out[p.name] = p.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"  ?? could not read {p}: {exc}")
    return out


def _remote_contents(storage, folder: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        files = storage.list_files(folder)
    except Exception:  # noqa: BLE001
        return out
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if name.endswith(".meta.json"):
            continue
        try:
            out[name] = storage.read_text(f)
        except Exception as exc:  # noqa: BLE001
            print(f"  ?? remote read failed for {f}: {exc}")
    return out


def _diff(local: dict[str, str], remote: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (new_to_upload, changed_to_overwrite)."""
    new_files = [n for n in local if n not in remote]
    changed = [n for n in local if n in remote and local[n].strip() != remote[n].strip()]
    return new_files, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually upload (default is dry-run).")
    args = parser.parse_args()

    from dtm_buildsheet.paths import ensure_workspace
    paths = ensure_workspace()

    try:
        storage = _get_storage()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not construct cloud storage: {exc}")
        return 1

    targets = [
        ("agencies",   paths.workspace_dir / "agencies",   "Settings/agencies"),
        ("sales_reps", paths.workspace_dir / "sales_reps", "Settings/sales_reps"),
        ("presets",    paths.workspace_presets_dir,        "Settings/presets"),
    ]

    work: list[tuple[str, str, str]] = []  # (remote_path, filename, content)

    for label, local_dir, remote_folder in targets:
        local = _local_files(local_dir)
        remote = _remote_contents(storage, remote_folder)
        new, changed = _diff(local, remote)
        print(f"\n=== {label} ===")
        print(f"  local dir: {local_dir}")
        print(f"  remote folder: {remote_folder}")
        print(f"  local: {len(local)}    remote: {len(remote)}")
        print(f"  new to upload: {len(new)}")
        for n in new[:10]:
            print(f"     + {n}")
        if len(new) > 10:
            print(f"     ... +{len(new) - 10}")
        print(f"  changed (will overwrite): {len(changed)}")
        for n in changed[:10]:
            print(f"     ~ {n}")
        if len(changed) > 10:
            print(f"     ... +{len(changed) - 10}")
        for n in new + changed:
            work.append((f"{remote_folder}/{n}", n, local[n]))

    if not work:
        print("\nNothing to upload — local and remote are in sync.")
        return 0

    if not args.apply:
        print(f"\nDry run — re-run with --apply to upload {len(work)} file(s).")
        return 0

    failures = 0
    for remote_path, _name, content in work:
        try:
            storage.write_text(remote_path, content)
            print(f"  ✓ {remote_path}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {remote_path}: {exc}")
            failures += 1
    print(f"\nUploaded {len(work) - failures} file(s); {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
