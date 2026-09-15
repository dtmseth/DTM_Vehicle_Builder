"""Reviewable, additive reference-folder backfill using shared record/item IDs.

This deliberately does not invoke general provisioning: it must not rename
folders, create ancestors, mirror project records, or touch Shop packages.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ...domain.project_codec import project_from_dict
from .vehicle_folder_provisioning_service import _drive_item_locator


FOLDER_NAME = "Build Reference Photos"


def _etag(item):
    return str(item.get("eTag") or item.get("@odata.etag") or "")


def _folder_path(item):
    if not item or not isinstance(item.get("folder"), dict):
        raise ValueError("A registered parent is missing or is not a folder")
    path, _, _ = _drive_item_locator(item)
    if not path:
        raise ValueError("A registered parent has no portable location")
    return path


def plan_reference_folders(records_gateway, company_gateway, *, root: str, progress=None,
                           exclude_project_ids=()) -> dict:
    plan = {
        "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "records_drive_id": records_gateway.drive_id,
        "company_drive_id": company_gateway.drive_id, "root": root.strip("/"),
        "projects": [], "targets": [], "blockers": [], "excluded_projects": [],
    }
    owners = {}
    for item in records_gateway.list_children("Projects"):
        name = str(item.get("name") or "")
        if not name.endswith(".json") or isinstance(item.get("folder"), dict):
            continue
        if name[:-5] in exclude_project_ids:
            plan["excluded_projects"].append(name[:-5])
            continue
        ident = str(item.get("id") or "")
        try:
            if not ident or not _etag(item):
                raise ValueError("Shared project identity/revision is unavailable")
            project = project_from_dict(json.loads(records_gateway.download_item(ident)))
            if not project.project_id or name != f"{project.project_id}.json":
                raise ValueError("Shared project filename/identity mismatch")
            after = records_gateway.get_item(ident)
            if not after or _etag(after) != _etag(item):
                raise ValueError("Shared project changed during planning")
            plan["projects"].append({"project_id": project.project_id, "item_id": ident, "etag": _etag(item)})
            for unit in project.build_units:
                for vehicle in unit.individuals:
                    parent_id = vehicle.company_vehicle_folder_id
                    if not parent_id:
                        raise ValueError(f"Vehicle {vehicle.individual_id} has no registered Company folder ID")
                    if parent_id in owners:
                        raise ValueError("Multiple vehicles reference the same Company folder ID")
                    owners[parent_id] = vehicle.individual_id
                    parent_path = _folder_path(company_gateway.get_item(parent_id))
                    if not parent_path.startswith(plan["root"] + "/"):
                        raise ValueError("Registered vehicle folder is outside the reviewed Company root")
                    path = f"{parent_path}/{FOLDER_NAME}"
                    child = company_gateway.get_item_by_path(path)
                    if child and (not isinstance(child.get("folder"), dict)
                                  or str((child.get("parentReference") or {}).get("id") or "") != parent_id):
                        raise ValueError("A conflicting file/folder blocks the reference folder")
                    plan["targets"].append({
                        "project_id": project.project_id, "unit_id": unit.unit_id,
                        "individual_id": vehicle.individual_id,
                        "parent_id": parent_id, "parent_path": parent_path,
                        "folder_name": FOLDER_NAME, "path": path,
                        "existing_id": str((child or {}).get("id") or ""),
                        "action": "keep" if child else "create",
                    })
        except Exception as exc:
            plan["blockers"].append({"project_item_id": ident, "error": str(exc)})
        if progress:
            progress(len(plan["projects"]), len(plan["targets"]))
    return plan


def apply_reference_folders(plan, records_gateway, company_gateway, *, checkpoint=None) -> dict:
    """Stop on stale identity/revision; retries retain already-created folders."""
    if (plan.get("version") != 1 or plan.get("blockers")
            or plan.get("company_drive_id") != company_gateway.drive_id
            or plan.get("records_drive_id") != records_gateway.drive_id):
        raise ValueError("The backfill plan is blocked or belongs to different libraries")
    report = {"created": 0, "verified": 0, "targets": [], "ok": False}
    projects = {p["project_id"]: p for p in plan["projects"]}
    try:
        # Check every source before the first mutation, and again per target.
        for project in projects.values():
            current = records_gateway.get_item(project["item_id"])
            if not current or _etag(current) != project["etag"]:
                raise ValueError("A shared project changed; generate a fresh plan")
        for target in plan["targets"]:
            project = projects[target["project_id"]]
            current = records_gateway.get_item(project["item_id"])
            if not current or _etag(current) != project["etag"]:
                raise ValueError("A shared project changed; generate a fresh plan")
            if target["folder_name"] != FOLDER_NAME:
                raise ValueError("The plan contains an unexpected folder name")
            parent_path = _folder_path(company_gateway.get_item(target["parent_id"]))
            if (parent_path != target["parent_path"]
                    or not parent_path.startswith(plan["root"] + "/")
                    or target["path"] != f"{parent_path}/{FOLDER_NAME}"):
                raise ValueError("A vehicle folder moved; generate a fresh plan")
            existing = company_gateway.get_item_by_path(target["path"])
            if target["existing_id"] and str((existing or {}).get("id") or "") != target["existing_id"]:
                raise ValueError("An existing reference folder changed; generate a fresh plan")
            if existing:
                child = existing
            else:
                child = company_gateway.ensure_child_folder(target["parent_id"], FOLDER_NAME)
                report["created"] += 1
            child_id = str(child.get("id") or "")
            verified = company_gateway.get_item(child_id) if child_id else None
            if (not verified or not isinstance(verified.get("folder"), dict)
                    or str((verified.get("parentReference") or {}).get("id") or "") != target["parent_id"]
                    or verified.get("name") != FOLDER_NAME):
                raise ValueError("Reference folder read-back did not match the registered parent")
            report["verified"] += 1
            report["targets"].append({**target, "folder_id": child_id})
            if checkpoint:
                checkpoint(report)
        report["ok"] = True
    except Exception as exc:
        report["error"] = str(exc)
    if checkpoint:
        checkpoint(report)
    return report
