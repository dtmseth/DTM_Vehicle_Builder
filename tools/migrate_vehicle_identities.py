#!/usr/bin/env python3
"""Conservatively add VehicleIdentity to unambiguous legacy project units.

The migration never edits legacy ``vehicle_model`` or individual vehicle
fields. Ambiguous, mixed-year, or sync-conflicted projects are reported and
left byte-for-byte untouched. Run without ``--apply`` for a dry run.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dtm_buildsheet.app.services.shared_work_service import (
    _clear_project_conflict,
    _cloud_storage,
    mirror_project_to_cloud,
)
from dtm_buildsheet.inputs.project_entry import _archive_current_project
from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.storage.local import LocalStorageProvider


GENERIC_MODELS = {"", "vehicle", "model pending", "misc"}
CUSTOM_MAKES = {"atv", "fire apparatus", "generic"}
MAKE_EQUIVALENTS = {
    "chevy": "chevrolet",
    "chevrolet": "chevrolet",
    "ram": "ram",
}


def _fold(value: object) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _make_key(value: object) -> str:
    folded = _fold(value)
    return MAKE_EQUIVALENTS.get(folded, folded)


def _model_key(value: object) -> str:
    return "".join(character for character in _fold(value) if character.isalnum())


def _unique(values: list[object]) -> list[str]:
    result: dict[str, str] = {}
    for raw in values:
        value = " ".join(str(raw or "").strip().split())
        if value:
            result.setdefault(_fold(value), value)
    return list(result.values())


def _load_layouts(paths: AppPaths) -> dict[str, dict]:
    path = paths.workspace_config_dir / "vehicle_layouts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {_fold(key): value for key, value in (data.get("vehicles") or {}).items()}


def _layout_identity(unit: dict, layouts: dict[str, dict]) -> tuple[str, str] | None:
    layout = layouts.get(_fold(unit.get("vehicle_model")))
    if not isinstance(layout, dict):
        return None
    make = " ".join(str(layout.get("make") or "").strip().split())
    model = " ".join(str(layout.get("model") or "").strip().split())
    if not make or _fold(model) in GENERIC_MODELS:
        return None
    return make, model


def _identity_for(unit: dict, layouts: dict[str, dict]) -> tuple[dict | None, str]:
    current = unit.get("vehicle_identity")
    if isinstance(current, dict) and _fold(current.get("source")) != "legacy":
        return None, "already migrated"

    individuals = [item for item in unit.get("individuals", []) if isinstance(item, dict)]
    years = _unique([item.get("year") for item in individuals])
    makes = _unique([item.get("make") for item in individuals])
    models = _unique([item.get("model") for item in individuals])
    if len(years) != 1:
        return None, "mixed or missing model year"
    if len(makes) > 1 or len(models) > 1:
        return None, "mixed make or model within unit group"

    layout_identity = _layout_identity(unit, layouts)
    individual_make = makes[0] if makes else ""
    individual_model = models[0] if models else ""
    legacy_model = str(unit.get("vehicle_model") or "").strip()

    if layout_identity:
        make, model = layout_identity
        if individual_make and _make_key(individual_make) != _make_key(make):
            return None, f"make conflict: {individual_make!r} vs layout {make!r}"
        if individual_model and _fold(individual_model) not in GENERIC_MODELS:
            aliases = {_model_key(model), _model_key(legacy_model)}
            if _model_key(individual_model) not in aliases:
                return None, f"model conflict: {individual_model!r} vs layout {model!r}"
    else:
        custom_individual = _fold(individual_make) in CUSTOM_MAKES
        if not individual_make or not individual_model or (
            _fold(individual_model) in GENERIC_MODELS and not custom_individual
        ):
            return None, "make/model cannot be established without guessing"
        legacy_matches = _model_key(legacy_model) in {
            _model_key(individual_model),
            _model_key(f"{individual_make} {individual_model}"),
        }
        if legacy_model and not legacy_matches:
            return None, f"layout/model conflict: {legacy_model!r} vs {individual_model!r}"
        make, model = individual_make, individual_model

    make = {"chevy": "Chevrolet", "ram": "Ram", "ford": "Ford", "dodge": "Dodge"}.get(
        _fold(make), make,
    )
    custom = _fold(make) in CUSTOM_MAKES or "side by side" in _fold(model)
    specialty = custom or _fold(make) == "harley-davidson"
    category = "atv_utv" if "side by side" in _fold(model) else ("other" if specialty else "automobile")
    package = str((current or {}).get("package") or "").strip()
    identity = {
        "source": "custom" if custom else "catalog",
        "model_year": years[0],
        "make": make,
        "model": model,
        "package": package,
        "category": category,
        "catalog_source": "" if custom else "Legacy project data",
        "catalog_make_id": "",
        "catalog_model_id": "",
        "layout_id": legacy_model,
        "display_name": " ".join(value for value in (years[0], make, model, package) if value),
    }
    return identity, ""


def _without_allowed_changes(data: dict) -> dict:
    result = copy.deepcopy(data)
    for key in ("record_revision", "record_parent_revision", "record_ancestor_revisions"):
        result.pop(key, None)
    for unit in result.get("build_units", []):
        if isinstance(unit, dict):
            unit.pop("vehicle_identity", None)
    return result


def _write_atomic(path: Path, data: dict) -> None:
    serialized = json.dumps(data, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".vehicle-identity-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(*, apply: bool) -> dict:
    paths = AppPaths()
    layouts = _load_layouts(paths)
    report = {
        "mode": "apply" if apply else "dry-run",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "projects_scanned": 0,
        "projects_changed": 0,
        "units_migrated": 0,
        "cloud_uploads": 0,
        "skipped": [],
        "changed": [],
    }
    cloud_storage = _cloud_storage() if apply else None
    real_cloud = cloud_storage is not None and not isinstance(cloud_storage, LocalStorageProvider)
    report["cloud_available"] = real_cloud
    for path in sorted(paths.workspace_projects_dir.glob("*/project.json")):
        report["projects_scanned"] += 1
        project_dir = path.parent
        if (project_dir / ".sync_conflict.json").exists():
            report["skipped"].append({
                "project_id": project_dir.name, "unit_id": "", "reason": "unresolved cloud sync conflict",
            })
            continue
        original_bytes = path.read_bytes()
        original_hash = hashlib.sha256(original_bytes).hexdigest()
        original = json.loads(original_bytes.decode("utf-8"))
        updated = copy.deepcopy(original)
        project_changes = []
        for unit in updated.get("build_units", []):
            if not isinstance(unit, dict):
                continue
            identity, reason = _identity_for(unit, layouts)
            if identity is None:
                if reason != "already migrated":
                    report["skipped"].append({
                        "project_id": str(original.get("project_id") or project_dir.name),
                        "unit_id": str(unit.get("unit_id") or ""),
                        "vehicle_model": str(unit.get("vehicle_model") or ""),
                        "reason": reason,
                    })
                continue
            unit["vehicle_identity"] = identity
            project_changes.append({"unit_id": str(unit.get("unit_id") or ""), "identity": identity})

        if not project_changes:
            continue
        old_revision = str(original.get("record_revision") or "")
        ancestors = [old_revision, *(original.get("record_ancestor_revisions") or [])]
        updated["record_parent_revision"] = old_revision
        updated["record_ancestor_revisions"] = list(dict.fromkeys(value for value in ancestors if value))[:64]
        updated["record_revision"] = str(uuid.uuid4())
        if _without_allowed_changes(original) != _without_allowed_changes(updated):
            raise RuntimeError(f"Unexpected field change detected for {path}")

        report["changed"].append({
            "project_id": str(original.get("project_id") or project_dir.name),
            "agency": str((original.get("customer") or {}).get("agency") or ""),
            "units": project_changes,
        })
        report["projects_changed"] += 1
        report["units_migrated"] += len(project_changes)
        if not apply:
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != original_hash:
            raise RuntimeError(f"Project changed during migration: {path}")
        _archive_current_project(path, original_bytes)
        _write_atomic(path, updated)
        if real_cloud and mirror_project_to_cloud(project_dir.name, path):
            report["cloud_uploads"] += 1
    return report


def reconcile_cloud(applied_report_path: Path) -> dict:
    """Merge only the audited identity additions onto an unchanged cloud record."""
    paths = AppPaths()
    applied = json.loads(applied_report_path.read_text(encoding="utf-8"))
    storage = _cloud_storage()
    if storage is None or isinstance(storage, LocalStorageProvider):
        raise RuntimeError("A real SharePoint adapter is required")
    read_versioned = getattr(storage, "read_versioned_text", None)
    write_versioned = getattr(storage, "write_versioned_text", None)
    if not callable(read_versioned) or not callable(write_versioned):
        raise RuntimeError("SharePoint versioned I/O is unavailable")

    result = {"attempted": 0, "uploaded": 0, "skipped": []}
    for change in applied.get("changed", []):
        project_id = str(change.get("project_id") or "")
        path = paths.workspace_projects_dir / project_id / "project.json"
        result["attempted"] += 1
        local_bytes = path.read_bytes()
        local = json.loads(local_bytes.decode("utf-8"))
        try:
            remote_text, remote_etag = read_versioned(f"Projects/{project_id}.json")
            remote = json.loads(remote_text)
        except Exception as exc:
            result["skipped"].append({"project_id": project_id, "reason": f"cloud read failed: {type(exc).__name__}"})
            continue
        if not isinstance(remote, dict) or _without_allowed_changes(local) != _without_allowed_changes(remote):
            result["skipped"].append({"project_id": project_id, "reason": "cloud has other project changes"})
            continue

        local_units = {
            str(unit.get("unit_id") or ""): unit
            for unit in local.get("build_units", []) if isinstance(unit, dict)
        }
        remote_units = {
            str(unit.get("unit_id") or ""): unit
            for unit in remote.get("build_units", []) if isinstance(unit, dict)
        }
        safe = True
        for unit_change in change.get("units", []):
            unit_id = str(unit_change.get("unit_id") or "")
            target_identity = unit_change.get("identity")
            local_identity = (local_units.get(unit_id) or {}).get("vehicle_identity")
            remote_identity = (remote_units.get(unit_id) or {}).get("vehicle_identity")
            if local_identity != target_identity or remote_identity not in (None, target_identity):
                safe = False
                break
        if not safe:
            result["skipped"].append({"project_id": project_id, "reason": "vehicle identity changed independently"})
            continue

        merged = copy.deepcopy(remote)
        merged_units = {
            str(unit.get("unit_id") or ""): unit
            for unit in merged.get("build_units", []) if isinstance(unit, dict)
        }
        for unit_change in change.get("units", []):
            merged_units[str(unit_change["unit_id"])]["vehicle_identity"] = copy.deepcopy(unit_change["identity"])
        remote_revision = str(remote.get("record_revision") or "")
        ancestors = [remote_revision, *(remote.get("record_ancestor_revisions") or [])]
        merged["record_parent_revision"] = remote_revision
        merged["record_ancestor_revisions"] = list(dict.fromkeys(value for value in ancestors if value))[:64]
        merged["record_revision"] = str(uuid.uuid4())
        if _without_allowed_changes(remote) != _without_allowed_changes(merged):
            raise RuntimeError(f"Unexpected cloud merge change for {project_id}")
        serialized = json.dumps(merged, indent=2) + "\n"
        try:
            write_versioned(f"Projects/{project_id}.json", serialized, remote_etag)
        except Exception as exc:
            result["skipped"].append({"project_id": project_id, "reason": f"conditional cloud write failed: {type(exc).__name__}"})
            continue
        _archive_current_project(path, local_bytes)
        _write_atomic(path, merged)
        _clear_project_conflict(path)
        result["uploaded"] += 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write and upload safe migrations")
    parser.add_argument("--reconcile-cloud", type=Path, help="safely merge an applied report onto SharePoint")
    parser.add_argument("--report", type=Path, default=Path("/tmp/dtm_vehicle_identity_migration.json"))
    args = parser.parse_args()
    report = reconcile_cloud(args.reconcile_cloud) if args.reconcile_cloud else run(apply=args.apply)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.reconcile_cloud:
        print(json.dumps({
            "attempted": report["attempted"], "uploaded": report["uploaded"],
            "skipped": len(report["skipped"]), "report": str(args.report),
        }, sort_keys=True))
        return
    print(json.dumps({
        "mode": report["mode"],
        "projects_scanned": report["projects_scanned"],
        "projects_changed": report["projects_changed"],
        "units_migrated": report["units_migrated"],
        "cloud_uploads": report["cloud_uploads"],
        "units_or_projects_skipped": len(report["skipped"]),
        "report": str(args.report),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
