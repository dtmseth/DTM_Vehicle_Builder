"""Canonical records for physical used vehicles across Builder workflows.

The opaque ``used_vehicle_id`` is internal. Users identify a vehicle by VIN;
project ``existing_*`` fields, buyback records, and strip records are
compatibility projections that all point to this one record.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...inputs.project_entry import list_projects, load_project, save_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway


logger = logging.getLogger(__name__)

LOCAL_RECORD_FOLDER = "used_vehicles"
SHAREPOINT_ROOT = "Used Vehicles"
SHAREPOINT_DATA_FOLDER = f"{SHAREPOINT_ROOT}/Record Data"

PURCHASE_STATUSES = {"unknown", "purchased_by_dtm", "returned_to_owner"}
TRANSFER_STATUSES = {"unknown", "not_linked", "linked"}
STRIP_REQUIREMENTS = {"undetermined", "required", "not_required"}
STRIP_STATUSES = {"not_started", "in_progress", "documented", "not_required"}

_DETAIL_FIELDS = (
    "agency_name", "vehicle_year", "vehicle_make", "vehicle_model", "vehicle_color",
    "unit_number", "vin",
)
_VEHICLE_DETAIL_FIELDS = tuple(field for field in _DETAIL_FIELDS if field != "agency_name")
_save_lock = threading.RLock()
_publish_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_vin(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _full_vin(value: Any) -> str:
    value = normalized_vin(value)
    return value if len(value) == 17 else ""


def _safe_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", raw):
        raise ValueError("Used vehicle ID is invalid")
    return raw


def _record_dir(paths: AppPaths) -> Path:
    target = paths.workspace_dir / LOCAL_RECORD_FOLDER
    target.mkdir(parents=True, exist_ok=True)
    return target


def _record_path(paths: AppPaths, used_vehicle_id: str) -> Path:
    return _record_dir(paths) / f"{_safe_id(used_vehicle_id)}.json"


def _normalize(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = dict(existing or {})
    used_vehicle_id = _safe_id(
        payload.get("used_vehicle_id") or current.get("used_vehicle_id") or str(uuid.uuid4())
    )
    record: dict[str, Any] = {
        "schema_version": 1,
        "used_vehicle_id": used_vehicle_id,
        "created_at": str(current.get("created_at") or payload.get("created_at") or _now()),
        "updated_at": _now(),
    }
    for field in _DETAIL_FIELDS:
        record[field] = str(payload.get(field, current.get(field, "")) or "").strip()[:4000]
    record["vin"] = normalized_vin(record["vin"])

    purchase = str(payload.get("purchase_status", current.get("purchase_status", "unknown")) or "unknown")
    transfer = str(payload.get("equipment_transfer_status", current.get("equipment_transfer_status", "unknown")) or "unknown")
    if transfer == "strip_only":  # Pre-release compatibility for early local records.
        transfer = "not_linked"
    strip_requirement = str(payload.get("strip_requirement", current.get("strip_requirement", "undetermined")) or "undetermined")
    strip_status = str(payload.get("strip_status", current.get("strip_status", "not_started")) or "not_started")
    record["purchase_status"] = purchase if purchase in PURCHASE_STATUSES else "unknown"
    record["equipment_transfer_status"] = transfer if transfer in TRANSFER_STATUSES else "unknown"
    record["strip_requirement"] = strip_requirement if strip_requirement in STRIP_REQUIREMENTS else "undetermined"
    record["strip_status"] = strip_status if strip_status in STRIP_STATUSES else "not_started"
    record["strip_not_required_reason"] = str(
        payload.get("strip_not_required_reason", current.get("strip_not_required_reason", "")) or ""
    ).strip()[:1000]
    record["origin_project_id"] = str(payload.get("origin_project_id", current.get("origin_project_id", "")) or "").strip()
    record["origin_unit_id"] = str(payload.get("origin_unit_id", current.get("origin_unit_id", "")) or "").strip()
    record["origin_individual_id"] = str(payload.get("origin_individual_id", current.get("origin_individual_id", "")) or "").strip()
    return record


def _write(paths: AppPaths, record: dict[str, Any]) -> None:
    target = _record_path(paths, record["used_vehicle_id"])
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def _load_local(paths: AppPaths) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(_record_dir(paths).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                records.append(payload)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read used vehicle record %s", path.name)
    return records


def get_record(used_vehicle_id: str, paths: AppPaths) -> dict[str, Any]:
    try:
        payload = json.loads(_record_path(paths, used_vehicle_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        raise FileNotFoundError("Used vehicle record not found") from None
    if not isinstance(payload, dict):
        raise FileNotFoundError("Used vehicle record not found")
    return payload


def find_by_vin(vin: Any, paths: AppPaths) -> dict[str, Any] | None:
    vin_key = _full_vin(vin)
    if not vin_key:
        return None
    return next((record for record in _load_local(paths) if _full_vin(record.get("vin")) == vin_key), None)


def ensure_record(
    values: dict[str, Any], paths: AppPaths, *, publish: bool = True,
) -> dict[str, Any]:
    """Create or update one canonical vehicle, deduplicating only exact full VINs."""
    with _save_lock:
        requested_id = str(values.get("used_vehicle_id") or "").strip()
        existing = None
        if requested_id:
            try:
                existing = get_record(requested_id, paths)
            except FileNotFoundError:
                existing = None
        vin_match = find_by_vin(values.get("vin"), paths)
        if vin_match is not None:
            existing = vin_match
        merged = dict(existing or {})
        for field, value in values.items():
            if field in _DETAIL_FIELDS and str(value or "").strip():
                merged[field] = value
            elif field in {
                "purchase_status", "equipment_transfer_status", "strip_requirement",
                "strip_status", "strip_not_required_reason", "origin_project_id",
                "origin_unit_id", "origin_individual_id",
            } and value is not None:
                merged[field] = value
        if existing is not None:
            merged["used_vehicle_id"] = existing["used_vehicle_id"]
        elif requested_id:
            merged["used_vehicle_id"] = requested_id
        record = _normalize(merged, existing=existing)
        _write(paths, record)
    if publish and _cloud_gateway() is not None:
        threading.Thread(
            target=_publish_record,
            args=(record,),
            name=f"used-vehicle-{record['used_vehicle_id'][-6:]}",
            daemon=True,
        ).start()
    return record


def ensure_for_project_vehicle(project, unit, individual, paths: AppPaths) -> dict[str, Any] | None:
    """Resolve a project's existing-vehicle projection to the canonical registry."""
    values = {
        "used_vehicle_id": individual.source_used_vehicle_id,
        "agency_name": project.customer.agency,
        "vehicle_year": individual.existing_year,
        "vehicle_make": individual.existing_make,
        "vehicle_model": individual.existing_model,
        "vehicle_color": individual.existing_color,
        "unit_number": individual.existing_unit_number,
        "vin": individual.existing_vin,
        "equipment_transfer_status": "linked",
        "strip_requirement": "required",
    }
    if not individual.source_used_vehicle_id and not any(
        str(values[field] or "").strip() for field in _VEHICLE_DETAIL_FIELDS
    ):
        return None
    record = ensure_record(values, paths)
    individual.source_used_vehicle_id = record["used_vehicle_id"]
    individual.existing_year = record["vehicle_year"]
    individual.existing_make = record["vehicle_make"]
    individual.existing_model = record["vehicle_model"]
    individual.existing_color = record["vehicle_color"]
    individual.existing_unit_number = record["unit_number"]
    individual.existing_vin = record["vin"]
    return record


def reconcile_project(project, paths: AppPaths) -> bool:
    changed = False
    for unit in project.build_units:
        for individual in unit.individuals:
            before = (
                individual.source_used_vehicle_id, individual.existing_year,
                individual.existing_make, individual.existing_model,
                individual.existing_color, individual.existing_unit_number,
                individual.existing_vin,
            )
            ensure_for_project_vehicle(project, unit, individual, paths)
            after = (
                individual.source_used_vehicle_id, individual.existing_year,
                individual.existing_make, individual.existing_model,
                individual.existing_color, individual.existing_unit_number,
                individual.existing_vin,
            )
            changed = changed or before != after
    return changed


def migrate_legacy_projects(paths: AppPaths) -> dict[str, int]:
    """Backfill canonical links for every stored project with existing-vehicle data."""
    migrated_projects = 0
    migrated_vehicles = 0
    for project in list_projects(paths):
        candidates = [
            individual
            for unit in project.build_units
            for individual in unit.individuals
            if not individual.source_used_vehicle_id and any(
                str(value or "").strip() for value in (
                    individual.existing_year,
                    individual.existing_make,
                    individual.existing_model,
                    individual.existing_color,
                    individual.existing_unit_number,
                    individual.existing_vin,
                )
            )
        ]
        if not candidates:
            continue
        try:
            if reconcile_project(project, paths):
                save_project(project, paths)
                migrated_projects += 1
                migrated_vehicles += len(candidates)
        except Exception:
            # A user edit or cloud refresh can win the startup race. The next
            # ordinary project save performs the same reconciliation safely.
            logger.warning("Could not migrate used vehicles for project %s", project.project_id)
    return {"projects": migrated_projects, "vehicles": migrated_vehicles}


def _transfer_links(paths: AppPaths) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for project in list_projects(paths):
        for unit in project.build_units:
            for individual in unit.individuals:
                key = str(individual.source_used_vehicle_id or "").strip()
                if not key:
                    continue
                result.setdefault(key, []).append({
                    "project_id": project.project_id,
                    "project_agency": project.customer.agency,
                    "project_year": project.customer.build_year,
                    "unit_id": unit.unit_id,
                    "individual_id": individual.individual_id,
                    "build_type": unit.build_type,
                    "build_unit_number": individual.unit_number,
                    "build_vin": individual.vin,
                })
    return result


def list_records(paths: AppPaths, *, sync_cloud: bool = True) -> dict[str, Any]:
    if sync_cloud:
        _sync_from_cloud(paths)
    links = _transfer_links(paths)
    records = []
    for stored in _load_local(paths):
        record = dict(stored)
        record["transfer_links"] = links.get(record["used_vehicle_id"], [])
        records.append(record)
    records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {"ok": True, "records": records}


def suggest_records(
    *, agency_name: str, vin: str, unit_number: str, paths: AppPaths,
) -> dict[str, Any]:
    agency_key = re.sub(r"[^a-z0-9]", "", str(agency_name or "").casefold())
    unit_key = re.sub(r"[^a-z0-9]", "", str(unit_number or "").casefold())
    vin_key = _full_vin(vin)
    suggestions = []
    for record in list_records(paths)["records"]:
        reasons: list[str] = []
        confidence = "candidate"
        if vin_key and _full_vin(record.get("vin")) == vin_key:
            reasons.append("Exact VIN")
            confidence = "exact"
        record_agency = re.sub(r"[^a-z0-9]", "", str(record.get("agency_name") or "").casefold())
        if agency_key and record_agency == agency_key:
            reasons.append("Same agency")
        record_unit = re.sub(r"[^a-z0-9]", "", str(record.get("unit_number") or "").casefold())
        if agency_key and record_agency == agency_key and unit_key and record_unit == unit_key:
            reasons.append("Same unit number")
        if not reasons or (confidence != "exact" and "Same agency" not in reasons):
            continue
        suggestions.append({**record, "match_reasons": reasons, "match_confidence": confidence})
    suggestions.sort(
        key=lambda item: (item["match_confidence"] == "exact", len(item["match_reasons"]), item["updated_at"]),
        reverse=True,
    )
    return {"ok": True, "records": suggestions}


def link_to_build(
    used_vehicle_id: str, project_id: str, unit_id: str, individual_id: str,
    paths: AppPaths,
) -> dict[str, Any]:
    record = get_record(used_vehicle_id, paths)
    project = load_project(project_id, paths)
    unit = next((item for item in project.build_units if item.unit_id == unit_id), None)
    individual = next(
        (item for item in (unit.individuals if unit else []) if item.individual_id == individual_id),
        None,
    )
    if unit is None or individual is None:
        raise ValueError("The selected new-build vehicle could not be found")
    _unlink_from_builds(record["used_vehicle_id"], paths, except_target=(project_id, unit_id, individual_id))
    project = load_project(project_id, paths)
    unit = next(item for item in project.build_units if item.unit_id == unit_id)
    individual = next(item for item in unit.individuals if item.individual_id == individual_id)
    individual.source_used_vehicle_id = record["used_vehicle_id"]
    individual.existing_year = record["vehicle_year"]
    individual.existing_make = record["vehicle_make"]
    individual.existing_model = record["vehicle_model"]
    individual.existing_color = record["vehicle_color"]
    individual.existing_unit_number = record["unit_number"]
    individual.existing_vin = record["vin"]
    save_project(project, paths)
    record = ensure_record({
        **record,
        "equipment_transfer_status": "linked",
        "strip_requirement": "required",
    }, paths)
    return {"ok": True, "record": record, "project": asdict(project)}


def _unlink_from_builds(
    used_vehicle_id: str,
    paths: AppPaths,
    *,
    except_target: tuple[str, str, str] | None = None,
) -> None:
    """Clear compatibility projections when an explicit relationship is removed or moved."""
    for project in list_projects(paths):
        changed = False
        for unit in project.build_units:
            for individual in unit.individuals:
                target = (project.project_id, unit.unit_id, individual.individual_id)
                if target == except_target or individual.source_used_vehicle_id != used_vehicle_id:
                    continue
                individual.source_used_vehicle_id = ""
                individual.existing_year = ""
                individual.existing_make = ""
                individual.existing_model = ""
                individual.existing_color = ""
                individual.existing_unit_number = ""
                individual.existing_vin = ""
                changed = True
        if changed:
            save_project(project, paths)


def update_relationships(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    record = get_record(str(payload.get("used_vehicle_id") or ""), paths)
    updates = {"used_vehicle_id": record["used_vehicle_id"]}
    for field in (
        "purchase_status", "equipment_transfer_status", "strip_requirement",
        "strip_status", "strip_not_required_reason",
    ):
        if field in payload:
            updates[field] = payload[field]
    requested_transfer = updates.get("equipment_transfer_status")
    if requested_transfer == "strip_only":
        requested_transfer = "not_linked"
        updates["equipment_transfer_status"] = requested_transfer
    existing_links = _transfer_links(paths).get(record["used_vehicle_id"], [])
    if requested_transfer == "unknown" and existing_links:
        updates["equipment_transfer_status"] = "linked"
    effective_transfer = updates.get(
        "equipment_transfer_status", record.get("equipment_transfer_status", "unknown"),
    )
    effective_strip_requirement = updates.get(
        "strip_requirement", record.get("strip_requirement", "undetermined"),
    )
    if effective_transfer == "linked" and effective_strip_requirement == "not_required":
        raise ValueError("A vehicle supplying equipment to a new build requires strip documentation")
    if updates.get("strip_requirement") == "not_required":
        updates["strip_status"] = "not_required"
    elif (
        "strip_requirement" in updates
        and record.get("strip_status") == "not_required"
        and "strip_status" not in updates
    ):
        updates["strip_status"] = "not_started"
    if "strip_requirement" in updates and updates["strip_requirement"] != "not_required":
        updates["strip_not_required_reason"] = ""
    if updates.get("equipment_transfer_status") == "not_linked":
        _unlink_from_builds(record["used_vehicle_id"], paths)
    return {"ok": True, "record": ensure_record(updates, paths)}


def build_suggestions(agency_name: str, paths: AppPaths) -> dict[str, Any]:
    agency_key = re.sub(r"[^a-z0-9]", "", str(agency_name or "").casefold())
    rows = []
    for project in list_projects(paths):
        project_agency_key = re.sub(r"[^a-z0-9]", "", project.customer.agency.casefold())
        if agency_key and project_agency_key != agency_key:
            continue
        for unit in project.build_units:
            for individual in unit.individuals:
                rows.append({
                    "project_id": project.project_id,
                    "project_agency": project.customer.agency,
                    "project_year": project.customer.build_year,
                    "unit_id": unit.unit_id,
                    "individual_id": individual.individual_id,
                    "build_type": unit.build_type,
                    "unit_number": individual.unit_number,
                    "vin": individual.vin,
                    "source_used_vehicle_id": individual.source_used_vehicle_id,
                })
    return {"ok": True, "builds": rows}


def _cloud_gateway() -> GraphDriveGateway | None:
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return None
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return None
    try:
        from ..adapters.cloud.config import load_cloud_config_from_env

        config = load_cloud_config_from_env()
        return GraphDriveGateway.from_active_cloud(config, library_names=(
            config.company_library_name,
            config.company_library_internal_name,
            config.exports_library_name,
            config.exports_library_internal_name,
        ))
    except Exception:
        logger.warning("Used vehicle SharePoint library is unavailable")
        return None


def _sync_from_cloud(paths: AppPaths) -> None:
    gateway = _cloud_gateway()
    if gateway is None:
        return
    try:
        children = gateway.list_children(SHAREPOINT_DATA_FOLDER)
    except FileNotFoundError:
        return
    except Exception:
        logger.warning("Could not list shared used vehicle records")
        return
    for item in children:
        name = str(item.get("name") or "")
        item_id = str(item.get("id") or "")
        if not name.casefold().endswith(".json") or not item_id:
            continue
        try:
            remote = json.loads(gateway.download_item(item_id).decode("utf-8"))
            if not isinstance(remote, dict):
                continue
            record_id = _safe_id(remote.get("used_vehicle_id"))
            local_path = _record_path(paths, record_id)
            local = json.loads(local_path.read_text(encoding="utf-8")) if local_path.exists() else {}
            if str(local.get("updated_at") or "") >= str(remote.get("updated_at") or ""):
                continue
            normalized = _normalize(remote, existing=remote)
            normalized["updated_at"] = str(remote.get("updated_at") or normalized["updated_at"])
            normalized["created_at"] = str(remote.get("created_at") or normalized["created_at"])
            _write(paths, normalized)
        except Exception:
            logger.warning("Could not hydrate shared used vehicle record %s", name)


def _publish_record(record: dict[str, Any]) -> None:
    with _publish_lock:
        gateway = _cloud_gateway()
        if gateway is None:
            return
        try:
            gateway.ensure_folder(SHAREPOINT_DATA_FOLDER)
            payload = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
            gateway.upload_file(
                f"{SHAREPOINT_DATA_FOLDER}/{record['used_vehicle_id']}.json", payload,
            )
        except Exception:
            logger.exception("Could not publish used vehicle %s", record.get("used_vehicle_id"))
