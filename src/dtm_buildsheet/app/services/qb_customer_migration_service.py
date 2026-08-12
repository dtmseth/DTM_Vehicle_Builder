"""Guarded sandbox-to-production QuickBooks Customer link migration.

Customer IDs are company-local. After the Item catalog was promoted from the
sandbox company to production, the agency records still carried sandbox
Customer IDs. This module deliberately ignores those IDs and prepares a
name-lineage plan against active production Customers. It is separate from the
normal ID-first customer sync, which becomes correct again only after migration.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ...domain.agency_models import CUSTOMER_PROFILE_FIELDS
from ...paths import AppPaths
from . import agency_service, quickbooks_service

_STATE_FILENAME = "quickbooks_customer_migration_state.json"
_PLAN_FILENAME = "quickbooks_production_customer_migration_plan.json"
_SNAPSHOTS_DIRNAME = "quickbooks_customer_migration_snapshots"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _STATE_FILENAME


def _plan_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _PLAN_FILENAME


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def customer_writes_blocked(paths: AppPaths) -> bool:
    """True while stale sandbox Customer IDs may still exist locally."""
    state = _read_json(_state_path(paths))
    return bool(state) and state.get("status") != "complete"


def ignored_production_customer_ids(paths: AppPaths) -> set[str]:
    """Return owner-rejected duplicate production Customers for future pulls."""
    state = _read_json(_state_path(paths))
    if state.get("status") != "complete":
        return set()
    return {
        str(customer_id) for customer_id in (state.get("ignored_duplicate_customer_ids") or [])
        if str(customer_id).strip()
    }


def _build_name_plan(agencies: list, customers: list[dict]) -> dict:
    """Build a pure unique-name migration plan, ignoring every stored QB ID."""
    by_name: dict[str, list[dict]] = defaultdict(list)
    for customer in customers:
        key = agency_service._normalize(str(customer.get("name") or ""))
        if key:
            by_name[key].append(customer)

    safe_matches: list[dict] = []
    ambiguous: list[dict] = []
    local_only: list[dict] = []
    matched_customer_ids: set[str] = set()
    for agency in agencies:
        key = agency_service._normalize(agency.name)
        candidates = by_name.get(key, [])
        local = {
            "agency_id": agency.agency_id,
            "name": agency.name,
            "baseline_qb_customer_id": agency.qb_customer_id,
        }
        if len(candidates) == 1:
            customer = candidates[0]
            customer_id = str(customer.get("qb_customer_id") or "")
            matched_customer_ids.add(customer_id)
            safe_matches.append({
                "agency": local,
                "production_customer": {
                    field: customer.get(field) for field in CUSTOMER_PROFILE_FIELDS
                } | {"qb_customer_id": customer_id},
                "match_basis": "unique_normalized_name",
                "confidence": "high",
            })
        elif candidates:
            ambiguous.append({
                "agency": local,
                "production_candidates": [
                    {
                        field: customer.get(field) for field in CUSTOMER_PROFILE_FIELDS
                    } | {"qb_customer_id": str(customer.get("qb_customer_id") or "")}
                    for customer in candidates
                ],
            })
        else:
            local_only.append({"agency": local})

    production_only = [
        {
            field: customer.get(field) for field in CUSTOMER_PROFILE_FIELDS
        } | {"qb_customer_id": str(customer.get("qb_customer_id") or "")}
        for customer in customers
        if str(customer.get("qb_customer_id") or "") not in matched_customer_ids
        and not any(
            str(candidate.get("qb_customer_id") or "") == str(customer.get("qb_customer_id") or "")
            for row in ambiguous for candidate in row["production_candidates"]
        )
    ]
    return {
        "safe_matches": safe_matches,
        "ambiguous": ambiguous,
        "local_only": local_only,
        "production_only": production_only,
        "summary": {
            "local_agencies": len(agencies),
            "production_customers": len(customers),
            "safe_unique_name_matches": len(safe_matches),
            "ambiguous_local_agencies": len(ambiguous),
            "local_without_name_match": len(local_only),
            "production_without_local_name_match": len(production_only),
        },
    }


def _snapshot_agencies(paths: AppPaths) -> tuple[str, dict[str, str]]:
    source_dir = agency_service._agencies_dir(paths)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_name = f"{timestamp}-pre-production-customer-migration"
    destination = paths.workspace_dir / _SNAPSHOTS_DIRNAME / snapshot_name
    destination.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for source in sorted(source_dir.glob("*.json")):
        target = destination / source.name
        shutil.copy2(source, target)
        os.chmod(target, 0o444)
        hashes[source.name] = _sha256(target)
    manifest = {
        "schema_version": 1,
        "created_utc": _now(),
        "snapshot_type": "quickbooks_production_customer_migration_baseline",
        "agency_count": len(hashes),
        "agency_sha256": hashes,
        "contains_credentials": False,
    }
    manifest_path = destination / "manifest.json"
    _write_json(manifest_path, manifest)
    os.chmod(manifest_path, 0o444)
    return snapshot_name, hashes


def prepare(paths: AppPaths) -> dict:
    """Fetch active production Customers and persist a read-only migration plan."""
    status = quickbooks_service.get_status(paths)
    if status.get("environment") != "production" or not status.get("connected"):
        return {"ok": False, "error": "standard_production_connection_required"}
    _write_json(_state_path(paths), {
        "schema_version": 1,
        "status": "required",
        "customer_writes_blocked": True,
        "updated_utc": _now(),
    })

    from . import qb_sync_service
    client, error = qb_sync_service._build_client(paths)
    if error:
        return error
    try:
        customers = client.fetch_active_customers()
    except Exception:  # noqa: BLE001 — API layer already keeps response data out of logs
        return {"ok": False, "error": "production_customer_pull_failed"}

    agencies = agency_service.load_agencies(paths)
    snapshot_name, hashes = _snapshot_agencies(paths)
    plan = _build_name_plan(agencies, customers)
    plan.update({
        "schema_version": 1,
        "created_utc": _now(),
        "snapshot_name": snapshot_name,
        "agency_sha256": hashes,
        "application_status": "prepared_not_applied",
        "match_rule": "Ignore sandbox Customer IDs; auto-match only one unique normalized production name.",
    })
    _write_json(_plan_path(paths), plan)
    return {"ok": True, "application_status": plan["application_status"], **plan["summary"]}


def apply_safe_matches(paths: AppPaths, *, owner_approved: bool = False) -> dict:
    """Apply unique-name relinks and clear stale IDs from every exception row."""
    if not owner_approved:
        return {"ok": False, "error": "owner_approval_required"}
    plan = _read_json(_plan_path(paths))
    if plan.get("application_status") != "prepared_not_applied":
        return {"ok": False, "error": "prepared_plan_required"}

    agency_dir = agency_service._agencies_dir(paths)
    hashes = plan.get("agency_sha256") or {}
    for filename, expected in hashes.items():
        path = agency_dir / filename
        if not path.is_file() or _sha256(path) != expected:
            return {"ok": False, "error": f"agency_changed_since_plan:{filename}"}

    original_bytes = {path: path.read_bytes() for path in agency_dir.glob("*.json")}
    agency_service._invalidate_cache(paths)
    records = {record.agency_id: record for record in agency_service.load_agencies(paths)}
    applied_utc = _now()
    filled_fields = 0
    relinked = 0
    cleared_stale_ids = 0
    try:
        for match in plan.get("safe_matches") or []:
            local = match["agency"]
            record = records.get(local["agency_id"])
            if record is None or record.qb_customer_id != local["baseline_qb_customer_id"]:
                raise ValueError("agency_link_changed_since_plan")
            customer = match["production_customer"]
            record.qb_customer_id = str(customer["qb_customer_id"])
            filled_fields += len(agency_service.merge_missing_customer_profile(record, customer))
            record.updated_at = applied_utc
            agency_service._write_record(record, paths)
            relinked += 1

        for exception in [*(plan.get("ambiguous") or []), *(plan.get("local_only") or [])]:
            local = exception["agency"]
            record = records.get(local["agency_id"])
            if record is None or record.qb_customer_id != local["baseline_qb_customer_id"]:
                raise ValueError("agency_exception_changed_since_plan")
            if record.qb_customer_id:
                record.qb_customer_id = ""
                record.updated_at = applied_utc
                agency_service._write_record(record, paths)
                cleared_stale_ids += 1
    except Exception as exc:  # noqa: BLE001 — restore the full per-record baseline
        for path, content in original_bytes.items():
            path.write_bytes(content)
        agency_service._invalidate_cache(paths)
        return {"ok": False, "error": f"customer_migration_rolled_back:{type(exc).__name__}"}

    agency_service._invalidate_cache(paths)
    applied = dict(plan)
    applied["application_status"] = "safe_matches_applied_exceptions_pending"
    applied["applied_utc"] = applied_utc
    applied["application"] = {
        "relinked": relinked,
        "filled_blank_profile_fields": filled_fields,
        "cleared_stale_exception_ids": cleared_stale_ids,
    }
    _write_json(_plan_path(paths), applied)
    _write_json(_state_path(paths), {
        "schema_version": 1,
        "status": "exceptions_pending",
        "customer_writes_blocked": True,
        "updated_utc": applied_utc,
        "summary": plan.get("summary") or {},
    })
    return {"ok": True, "application_status": applied["application_status"], **applied["application"]}


def finalize_reviewed_exceptions(
    paths: AppPaths,
    *,
    links_by_agency_name: dict[str, str],
    delete_agency_names: list[str],
    import_customer_ids: list[str],
    ignored_duplicate_customer_ids: list[str],
    owner_approved: bool = False,
) -> dict:
    """Apply explicit exception decisions and mark Customer links production-ready."""
    if not owner_approved:
        return {"ok": False, "error": "owner_approval_required"}
    plan = _read_json(_plan_path(paths))
    if plan.get("application_status") != "safe_matches_applied_exceptions_pending":
        return {"ok": False, "error": "safe_match_application_required"}

    customer_by_id: dict[str, dict] = {}
    for match in plan.get("safe_matches") or []:
        customer = match.get("production_customer") or {}
        customer_by_id[str(customer.get("qb_customer_id") or "")] = customer
    for row in plan.get("ambiguous") or []:
        for customer in row.get("production_candidates") or []:
            customer_by_id[str(customer.get("qb_customer_id") or "")] = customer
    for customer in plan.get("production_only") or []:
        customer_by_id[str(customer.get("qb_customer_id") or "")] = customer

    agency_dir = agency_service._agencies_dir(paths)
    agency_service._invalidate_cache(paths)
    records = {record.agency_id: record for record in agency_service.load_agencies(paths)}
    by_name: dict[str, list] = defaultdict(list)
    for record in records.values():
        by_name[record.name].append(record)

    try:
        for name, customer_id in links_by_agency_name.items():
            if len(by_name.get(name, [])) != 1 or customer_id not in customer_by_id:
                raise ValueError(f"reviewed_link_unresolvable:{name}")
        for name in delete_agency_names:
            if len(by_name.get(name, [])) != 1:
                raise ValueError(f"reviewed_delete_unresolvable:{name}")
        if any(customer_id not in customer_by_id for customer_id in import_customer_ids):
            raise ValueError("reviewed_import_unresolvable")
        if set(import_customer_ids).intersection(ignored_duplicate_customer_ids):
            raise ValueError("customer_cannot_be_imported_and_ignored")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    original_bytes = {path: path.read_bytes() for path in agency_dir.glob("*.json")}
    created_paths: list[Path] = []
    applied_utc = _now()
    linked = imported = deleted = filled_fields = 0
    deleted_records: list[dict] = []
    try:
        for name, customer_id in links_by_agency_name.items():
            record = by_name[name][0]
            if record.qb_customer_id:
                raise ValueError(f"reviewed_agency_already_linked:{name}")
            customer = customer_by_id[customer_id]
            record.qb_customer_id = customer_id
            filled_fields += len(agency_service.merge_missing_customer_profile(record, customer))
            record.updated_at = applied_utc
            agency_service._write_record(record, paths)
            linked += 1

        for name in delete_agency_names:
            record = by_name[name][0]
            deleted_records.append({"agency_id": record.agency_id, "name": record.name})
            agency_service._delete_record_file(record.agency_id, paths)
            deleted += 1

        existing_ids = {
            str(record.qb_customer_id or "") for record in records.values()
            if record.name not in delete_agency_names and str(record.qb_customer_id or "")
        }
        existing_names = {
            agency_service._normalize(record.name) for record in records.values()
            if record.name not in delete_agency_names
        }
        for customer_id in import_customer_ids:
            customer = customer_by_id[customer_id]
            name = str(customer.get("name") or "").strip()
            if not name or customer_id in existing_ids or agency_service._normalize(name) in existing_names:
                raise ValueError(f"reviewed_import_conflict:{customer_id}")
            fields = {
                field: agency_service._clean_agency_field(field, customer.get(field))
                for field in CUSTOMER_PROFILE_FIELDS
                if field != "name" and customer.get(field) is not None
            }
            record = agency_service.AgencyRecord(
                agency_id=str(uuid.uuid4()),
                name=name,
                qb_customer_id=customer_id,
                created_at=applied_utc,
                updated_at=applied_utc,
                **fields,
            )
            agency_service._write_record(record, paths)
            created_paths.append(agency_service._record_path(record.agency_id, paths))
            existing_ids.add(customer_id)
            existing_names.add(agency_service._normalize(name))
            imported += 1
    except Exception as exc:  # noqa: BLE001 — restore all agency files atomically
        for path in agency_dir.glob("*.json"):
            if path not in original_bytes:
                path.unlink(missing_ok=True)
        for path, content in original_bytes.items():
            path.write_bytes(content)
        agency_service._invalidate_cache(paths)
        return {"ok": False, "error": f"customer_exception_finalize_rolled_back:{type(exc).__name__}"}

    agency_service._invalidate_cache(paths)
    complete = dict(plan)
    complete["application_status"] = "applied"
    complete["completed_utc"] = applied_utc
    complete["reviewed_exceptions"] = {
        "links_by_agency_name": links_by_agency_name,
        "deleted_agencies": deleted_records,
        "imported_customer_ids": import_customer_ids,
        "ignored_duplicate_customer_ids": ignored_duplicate_customer_ids,
    }
    _write_json(_plan_path(paths), complete)
    _write_json(_state_path(paths), {
        "schema_version": 1,
        "status": "complete",
        "customer_writes_blocked": False,
        "updated_utc": applied_utc,
        "ignored_duplicate_customer_ids": ignored_duplicate_customer_ids,
    })
    return {
        "ok": True,
        "application_status": "applied",
        "linked_reviewed_exceptions": linked,
        "filled_blank_profile_fields": filled_fields,
        "imported_agencies": imported,
        "deleted_agencies": deleted,
        "deleted_records": deleted_records,
    }
