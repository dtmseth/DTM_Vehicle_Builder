#!/usr/bin/env python3
"""Create an immutable, local QuickBooks production-mapping baseline.

The production-catalog transition must start from a recoverable record of the
Builder catalog that existed before any production OAuth connection or mapping
approval.  This tool copies only non-secret catalog data: ``parts_db.json`` and
an optional normalized QuickBooks item cache.  It deliberately never reads or
copies ``quickbooks_config.json`` or the OS-keychain credential blob.

The snapshot lives beside the installed application's workspace by default,
outside the repository and SharePoint mirror.  It is a recovery aid, not an
input to routine synchronization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _catalog_counts(document: dict) -> dict[str, int]:
    products = document.get("products") or {}
    if not isinstance(products, dict):
        raise ValueError("parts_db.json has no products object")
    part_numbers = [
        part_number
        for product in products.values()
        if isinstance(product, dict)
        for part_number in (product.get("part_numbers") or [])
        if isinstance(part_number, dict)
    ]
    return {
        "products": len(products),
        "part_numbers": len(part_numbers),
        "linked_part_numbers": sum(bool(str(item.get("qb_item_id") or "").strip()) for item in part_numbers),
        "pending_part_numbers": sum(item.get("qb_pending") is True for item in part_numbers),
    }


def _safe_label(raw: str) -> str:
    label = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if not label:
        raise ValueError("snapshot label must contain a letter or number")
    return label[:48]


def _record_file(source: Path, destination: Path) -> dict[str, object]:
    shutil.copy2(source, destination)
    os.chmod(destination, 0o444)
    return {
        "file": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
    }


def create_snapshot(
    *,
    parts_db: Path,
    items_cache: Path | None,
    output_root: Path,
    label: str,
) -> Path:
    parts_db = parts_db.expanduser().resolve()
    if not parts_db.is_file():
        raise ValueError(f"parts database not found: {parts_db}")
    parts_document = _load_json(parts_db)

    cache_document: dict | None = None
    if items_cache is not None:
        items_cache = items_cache.expanduser().resolve()
        if not items_cache.is_file():
            raise ValueError(f"QuickBooks item cache not found: {items_cache}")
        cache_document = _load_json(items_cache)
        if not isinstance(cache_document.get("items") or [], list):
            raise ValueError("QuickBooks item cache has no items list")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = output_root.expanduser().resolve() / f"{timestamp}-{_safe_label(label)}"
    if snapshot_dir.exists():
        raise ValueError(f"snapshot directory already exists: {snapshot_dir}")

    snapshot_dir.mkdir(parents=True)
    try:
        files = {"parts_db": _record_file(parts_db, snapshot_dir / "parts_db.json")}
        if items_cache is not None and cache_document is not None:
            files["sandbox_items_cache"] = _record_file(
                items_cache, snapshot_dir / "sandbox_quickbooks_items_cache.json"
            )

        manifest = {
            "schema_version": 1,
            "snapshot_type": "quickbooks_production_mapping_baseline",
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "label": _safe_label(label),
            "catalog": _catalog_counts(parts_document),
            "sandbox_items_cache": (
                {
                    "items": len(cache_document.get("items") or []),
                    "last_sync_utc": cache_document.get("last_sync_utc"),
                }
                if cache_document is not None
                else None
            ),
            "files": files,
            "safety": {
                "contains_credentials": False,
                "contains_oauth_tokens": False,
                "restore_rule": "Never restore automatically. Owner review is required before any catalog rollback.",
                "production_sync": "disabled until a production mapping is reviewed and approved",
            },
        }
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o444)
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise

    return snapshot_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts-db", required=True, type=Path, help="Current installed parts_db.json")
    parser.add_argument(
        "--items-cache",
        type=Path,
        help="Optional current sandbox quickbooks_items_cache.json (non-secret)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path.home() / "Library" / "Application Support" / "DTM Vehicle Builder" / "quickbooks_migration_snapshots",
        help="Local-only folder in which to store immutable snapshot directories",
    )
    parser.add_argument("--label", default="pre-production-mapping", help="Human-readable snapshot label")
    args = parser.parse_args()

    try:
        path = create_snapshot(
            parts_db=args.parts_db,
            items_cache=args.items_cache,
            output_root=args.output_root,
            label=args.label,
        )
    except ValueError as exc:
        print(f"Snapshot not created: {exc}", file=sys.stderr)
        return 2

    print(f"Created QuickBooks migration snapshot: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
