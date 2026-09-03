#!/usr/bin/env python3
"""Execute the reviewed legacy Build Photos migration in safe phases.

The tool is intentionally production-specific.  Every destructive target is
re-derived from the reviewed aliases, checked under the exact configured root,
and required to be empty immediately before deletion.  The legacy source tree
is read and copied but never moved, renamed, or deleted.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from dtm_buildsheet.app.adapters.cloud.config import load_cloud_config_from_env
from dtm_buildsheet.app.adapters.cloud.graph_drive_gateway import GraphDriveGateway
from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.services import agency_service
from dtm_buildsheet.app.services.legacy_build_photos_migration_service import (
    LEGACY_PHOTO_GROUPS,
    create_completed_projects,
    desired_agency_names,
    ensure_joint_agency,
    resolve_agencies,
)
from dtm_buildsheet.app.services.shared_work_service import (
    mirror_project_to_cloud,
    save_setting_to_cloud,
)
from dtm_buildsheet.app.services.vehicle_folder_provisioning_service import (
    _company_gateway,
    _shop_gateway,
    provision_project_folders,
)
from dtm_buildsheet.inputs.project_entry import list_projects, load_project
from dtm_buildsheet.paths import AppPaths


EXPECTED_UNWANTED_ROOTS_PER_DATABASE = 184
EXPECTED_SOURCE_FILE_COUNT = 1043
EXPECTED_GROUP_COUNT = 46
EXPECTED_HISTORICAL_PROJECT_COUNT = 35


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_report(report: dict, phase: str) -> Path:
    destination = Path(f"/private/tmp/dtm-build-photos-{phase}-{_stamp()}.json")
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return destination


def _backup_local(paths: AppPaths, phase: str) -> Path:
    destination = Path(f"/private/tmp/dtm-build-photos-backup-{phase}-{_stamp()}")
    destination.mkdir(parents=True, exist_ok=False)
    for source in (paths.workspace_dir / "agencies", paths.workspace_projects_dir):
        if source.exists():
            shutil.copytree(source, destination / source.name)
    return destination


def _gateways():
    config = load_cloud_config_from_env()
    return config, _company_gateway(config), _shop_gateway(config)


def _roots(config) -> tuple[str, str]:
    return (
        config.company_vehicle_root.strip("/") or "Vehicle Project Database",
        config.shop_build_photos_root.strip("/") or "Shop Project Database",
    )


def _root_audit(gateway: GraphDriveGateway, root: str, wanted: set[str]) -> dict:
    root_item = gateway.get_item_by_path(root)
    if root_item is None or not isinstance(root_item.get("folder"), dict):
        raise RuntimeError(f"Configured root is missing or is not a folder: {root}")
    rows = gateway.list_children(root)
    names = [str(row.get("name") or "") for row in rows]
    if len(names) != len({name.casefold() for name in names}):
        raise RuntimeError(f"Duplicate case-insensitive agency roots exist below {root}")
    nonfolders = [name for name, row in zip(names, rows) if not isinstance(row.get("folder"), dict)]
    if nonfolders:
        raise RuntimeError(f"Non-folder items block root cleanup below {root}: {nonfolders}")
    wanted_folded = {name.casefold() for name in wanted}
    retained = [row for row in rows if str(row.get("name") or "").casefold() in wanted_folded]
    unwanted = [row for row in rows if str(row.get("name") or "").casefold() not in wanted_folded]
    return {
        "root": root,
        "root_id": str(root_item.get("id") or ""),
        "total": len(rows),
        "retained": retained,
        "unwanted": unwanted,
    }


def _slim_item(item: dict) -> dict:
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "child_count": int((item.get("folder") or {}).get("childCount") or 0),
        "parent_id": str((item.get("parentReference") or {}).get("id") or ""),
    }


def audit(paths: AppPaths) -> dict:
    config, company, shop = _gateways()
    company_root, shop_root = _roots(config)
    wanted = desired_agency_names(paths)
    company_audit = _root_audit(company, company_root, wanted)
    shop_audit = _root_audit(shop, shop_root, wanted)
    source_files, source_folders = _tree_manifest(shop, "Build Photos")
    return {
        "phase": "audit",
        "at": _now(),
        "wanted_agencies": sorted(wanted, key=str.casefold),
        "company": {
            **{key: company_audit[key] for key in ("root", "root_id", "total")},
            "retained": [_slim_item(item) for item in company_audit["retained"]],
            "unwanted": [_slim_item(item) for item in company_audit["unwanted"]],
        },
        "shop": {
            **{key: shop_audit[key] for key in ("root", "root_id", "total")},
            "retained": [_slim_item(item) for item in shop_audit["retained"]],
            "unwanted": [_slim_item(item) for item in shop_audit["unwanted"]],
        },
        "source_file_count": len(source_files),
        "source_folder_count": len(source_folders),
        "source_total_bytes": sum(source_files.values()),
    }


def _delete_exact_empty_roots(
    gateway: GraphDriveGateway,
    root_audit: dict,
    *,
    expected: int,
    progress,
) -> list[dict]:
    unwanted = root_audit["unwanted"]
    if len(unwanted) != expected:
        raise RuntimeError(
            f"Cleanup expected {expected} unwanted roots below {root_audit['root']}; "
            f"fresh audit found {len(unwanted)}"
        )
    deleted: list[dict] = []
    for index, item in enumerate(unwanted, start=1):
        current_name = str(item.get("name") or "")
        current_id = str(item.get("id") or "")
        if not current_name or not current_id:
            raise RuntimeError("An unwanted root is missing its durable name or item ID")
        if str((item.get("parentReference") or {}).get("id") or "") != root_audit["root_id"]:
            raise RuntimeError(f"Parent identity changed for {current_name}")
        if int((item.get("folder") or {}).get("childCount") or 0) != 0:
            raise RuntimeError(f"Refusing to delete non-empty root: {current_name}")
        exact_path = f"{root_audit['root']}/{current_name}"
        children = gateway.list_children(exact_path)
        if children:
            raise RuntimeError(f"Refusing to delete root with live children: {current_name}")
        refreshed = gateway.get_item_by_path(exact_path)
        if refreshed is None:
            raise RuntimeError(f"Root disappeared before reviewed deletion: {current_name}")
        if str(refreshed.get("id") or "") != current_id:
            raise RuntimeError(f"Root identity changed before deletion: {current_name}")
        if int((refreshed.get("folder") or {}).get("childCount") or 0) != 0:
            raise RuntimeError(f"Root became non-empty before deletion: {current_name}")
        gateway.delete_item(current_id)
        deleted.append(_slim_item(refreshed))
        progress(index, len(unwanted), current_name)
    return deleted


def _clear_deleted_folder_state(
    paths: AppPaths,
    company_ids: set[str],
    shop_ids: set[str],
) -> dict:
    changed: list[str] = []
    matched_company: set[str] = set()
    matched_shop: set[str] = set()
    records = agency_service._records(paths)  # noqa: SLF001
    for agency in records.values():
        touched = False
        if agency.company_folder_id in company_ids:
            matched_company.add(agency.company_folder_id)
            agency.company_folder_id = ""
            agency.company_folder_path = ""
            agency.company_folder_status = "not_provisioned"
            agency.company_folder_error = ""
            touched = True
        if agency.shop_folder_id in shop_ids:
            matched_shop.add(agency.shop_folder_id)
            agency.shop_folder_id = ""
            agency.shop_folder_path = ""
            agency.shop_folder_status = "not_provisioned"
            agency.shop_folder_error = ""
            touched = True
        if not touched:
            continue
        agency_service._write_record(agency, paths)  # noqa: SLF001
        payload = json.dumps(asdict(agency), indent=2) + "\n"
        if not save_setting_to_cloud(f"agencies/{agency.agency_id}.json", payload):
            raise RuntimeError(f"Could not mirror cleared folder state for {agency.name}")
        changed.append(agency.agency_id)
    if matched_company != company_ids or matched_shop != shop_ids:
        raise RuntimeError(
            "Deleted roots did not map one-to-one to standalone agency folder state "
            f"(company {len(matched_company)}/{len(company_ids)}, "
            f"shop {len(matched_shop)}/{len(shop_ids)})"
        )
    return {"agency_ids": changed, "count": len(changed)}


def _save_setting_with_retry(target: str, payload: str, *, attempts: int = 5) -> None:
    for attempt in range(1, attempts + 1):
        if save_setting_to_cloud(target, payload):
            return
        if attempt < attempts:
            time.sleep(min(8, 2 ** (attempt - 1)))
    raise RuntimeError(f"Could not mirror cleared folder state after {attempts} attempts: {target}")


def reconcile_state(paths: AppPaths) -> dict:
    """Resume folder-state cleanup after the exact roots are already gone."""
    backup = _backup_local(paths, "state")
    config, company, shop = _gateways()
    company_root, shop_root = _roots(config)
    wanted = desired_agency_names(paths)
    company_audit = _root_audit(company, company_root, wanted)
    shop_audit = _root_audit(shop, shop_root, wanted)
    if company_audit["unwanted"] or shop_audit["unwanted"]:
        raise RuntimeError("State-only reconciliation requires the reviewed unwanted roots to be gone")

    wanted_folded = {name.casefold() for name in wanted}
    records = agency_service._records(paths)  # noqa: SLF001
    outside_scope = [
        agency for agency in records.values()
        if agency.name.strip().casefold() not in wanted_folded
    ]
    if len(outside_scope) != EXPECTED_UNWANTED_ROOTS_PER_DATABASE:
        raise RuntimeError(
            f"Expected {EXPECTED_UNWANTED_ROOTS_PER_DATABASE} standalone records; "
            f"found {len(outside_scope)}"
        )
    mirrored = []
    for index, agency in enumerate(sorted(outside_scope, key=lambda item: item.name.casefold()), start=1):
        agency.company_folder_id = ""
        agency.company_folder_path = ""
        agency.company_folder_status = "not_provisioned"
        agency.company_folder_error = ""
        agency.shop_folder_id = ""
        agency.shop_folder_path = ""
        agency.shop_folder_status = "not_provisioned"
        agency.shop_folder_error = ""
        agency_service._write_record(agency, paths)  # noqa: SLF001
        payload = json.dumps(asdict(agency), indent=2) + "\n"
        _save_setting_with_retry(f"agencies/{agency.agency_id}.json", payload)
        mirrored.append(agency.agency_id)
        print(f"state {index}/{len(outside_scope)}: {agency.name}", flush=True)
    return {
        "phase": "state",
        "at": _now(),
        "backup": str(backup),
        "mirrored_agency_ids": mirrored,
        "mirrored_count": len(mirrored),
        "company_remaining": company_audit["total"],
        "shop_remaining": shop_audit["total"],
    }


def cleanup(paths: AppPaths) -> dict:
    backup = _backup_local(paths, "cleanup")
    config, company, shop = _gateways()
    company_root, shop_root = _roots(config)
    wanted = desired_agency_names(paths)
    company_audit = _root_audit(company, company_root, wanted)
    shop_audit = _root_audit(shop, shop_root, wanted)

    def company_progress(index, total, name):
        print(f"cleanup company {index}/{total}: {name}", flush=True)

    def shop_progress(index, total, name):
        print(f"cleanup shop {index}/{total}: {name}", flush=True)

    deleted_company = _delete_exact_empty_roots(
        company, company_audit,
        expected=EXPECTED_UNWANTED_ROOTS_PER_DATABASE,
        progress=company_progress,
    )
    deleted_shop = _delete_exact_empty_roots(
        shop, shop_audit,
        expected=EXPECTED_UNWANTED_ROOTS_PER_DATABASE,
        progress=shop_progress,
    )
    state = _clear_deleted_folder_state(
        paths,
        {item["id"] for item in deleted_company},
        {item["id"] for item in deleted_shop},
    )
    final_company = _root_audit(company, company_root, wanted)
    final_shop = _root_audit(shop, shop_root, wanted)
    if final_company["unwanted"] or final_shop["unwanted"]:
        raise RuntimeError("Unwanted roots remain after cleanup")
    return {
        "phase": "cleanup",
        "at": _now(),
        "backup": str(backup),
        "deleted_company": deleted_company,
        "deleted_shop": deleted_shop,
        "cleared_state": state,
        "company_remaining": final_company["total"],
        "shop_remaining": final_shop["total"],
    }


def projects(paths: AppPaths) -> dict:
    backup = _backup_local(paths, "projects")
    agency, agency_created = ensure_joint_agency(paths, mirror_to_cloud=True)
    result = create_completed_projects(paths, mirror_to_cloud=True)
    if result["project_count"] != EXPECTED_HISTORICAL_PROJECT_COUNT:
        raise RuntimeError("Historical project count changed from the reviewed plan")
    if result["group_count"] != EXPECTED_GROUP_COUNT:
        raise RuntimeError("Historical source-group count changed from the reviewed plan")
    return {
        "phase": "projects",
        "at": _now(),
        "backup": str(backup),
        "joint_agency_id": agency.agency_id,
        "joint_agency_created": agency_created,
        **result,
    }


def provision(paths: AppPaths) -> dict:
    config, company, shop = _gateways()
    company_root, shop_root = _roots(config)
    plan = create_completed_projects(paths, mirror_to_cloud=False)
    project_ids = sorted({target["project_id"] for target in plan["targets"].values()})
    results = []
    for index, project_id in enumerate(project_ids, start=1):
        print(f"provision {index}/{len(project_ids)}: {project_id}", flush=True)
        result = provision_project_folders(
            project_id,
            paths,
            company_gateway=company,
            shop_gateway=shop,
            company_root=company_root,
            shop_root=shop_root,
        )
        if not result.get("ok"):
            raise RuntimeError(f"Folder provisioning failed for {project_id}: {result}")
        local_path = paths.workspace_projects_dir / project_id / "project.json"
        if not mirror_project_to_cloud(project_id, local_path):
            raise RuntimeError(f"Provisioned project {project_id} could not be mirrored")
        results.append({"project_id": project_id, **result})

    for agency in resolve_agencies(paths).values():
        payload = json.dumps(asdict(agency_service.get_agency(paths, agency.agency_id)), indent=2) + "\n"
        if not save_setting_to_cloud(f"agencies/{agency.agency_id}.json", payload):
            raise RuntimeError(f"Provisioned agency state could not be mirrored: {agency.name}")
    return {
        "phase": "provision",
        "at": _now(),
        "projects": results,
        "project_count": len(results),
    }


def _tree_manifest(gateway: GraphDriveGateway, root: str) -> tuple[dict[str, int], set[str]]:
    files: dict[str, int] = {}
    folders: set[str] = set()
    stack = [root.strip("/")]
    while stack:
        current = stack.pop()
        for item in gateway.list_children(current):
            name = str(item.get("name") or "")
            if not name or "/" in name or "\\" in name:
                raise RuntimeError(f"Unsafe SharePoint item name below {root!r}")
            child = f"{current}/{name}"
            relative = str(PurePosixPath(child).relative_to(PurePosixPath(root)))
            if isinstance(item.get("folder"), dict):
                folders.add(relative)
                stack.append(child)
            else:
                files[relative] = int(item.get("size") or 0)
    return files, folders


def _wait_until_missing(gateway: GraphDriveGateway, path: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gateway.get_item_by_path(path) is None:
            return
        time.sleep(0.5)
    raise RuntimeError(f"Deleted empty destination did not disappear: {path}")


def copy_photos(paths: AppPaths) -> dict:
    _config, _company, shop = _gateways()
    plan = create_completed_projects(paths, mirror_to_cloud=False)
    results = []
    total_source_files = 0
    total_destination_files = 0
    total_source_bytes = 0
    total_destination_bytes = 0

    for index, group in enumerate(LEGACY_PHOTO_GROUPS, start=1):
        target = plan["targets"][group.source_path]
        project = load_project(target["project_id"], paths)
        unit = next(item for item in project.build_units if item.unit_id == target["unit_id"])
        individual = next(
            item for item in unit.individuals
            if item.individual_id == target["individual_id"]
        )
        if not individual.shop_vehicle_folder_id or not individual.shop_vehicle_folder_path:
            raise RuntimeError(f"Shop destination is not provisioned for {group.source_path}")
        destination = f"{individual.shop_vehicle_folder_path}/Completed Build Photos"
        source_item = shop.get_item_by_path(group.source_path)
        if source_item is None or not isinstance(source_item.get("folder"), dict):
            raise RuntimeError(f"Legacy source group is missing: {group.source_path}")
        source_files, source_folders = _tree_manifest(shop, group.source_path)
        if not source_files:
            raise RuntimeError(f"Legacy source group is unexpectedly empty: {group.source_path}")

        existing = shop.get_item_by_path(destination)
        copied = False
        if existing is not None:
            destination_files, destination_folders = _tree_manifest(shop, destination)
            if destination_files or destination_folders:
                if destination_files != source_files or destination_folders != source_folders:
                    raise RuntimeError(f"Destination collision or incomplete copy: {destination}")
            else:
                if str((existing.get("parentReference") or {}).get("id") or "") != individual.shop_vehicle_folder_id:
                    raise RuntimeError(f"Empty destination has the wrong parent: {destination}")
                if int((existing.get("folder") or {}).get("childCount") or 0) != 0:
                    raise RuntimeError(f"Empty destination child count changed: {destination}")
                shop.delete_item(str(existing.get("id") or ""))
                _wait_until_missing(shop, destination)
                existing = None
        if existing is None:
            shop.copy_item(
                str(source_item.get("id") or ""),
                parent_id=individual.shop_vehicle_folder_id,
                new_name="Completed Build Photos",
                destination_path=destination,
            )
            copied = True

        destination_files, destination_folders = _tree_manifest(shop, destination)
        if destination_files != source_files or destination_folders != source_folders:
            raise RuntimeError(f"Copied tree verification failed: {destination}")
        source_bytes = sum(source_files.values())
        destination_bytes = sum(destination_files.values())
        total_source_files += len(source_files)
        total_destination_files += len(destination_files)
        total_source_bytes += source_bytes
        total_destination_bytes += destination_bytes
        results.append({
            "source_path": group.source_path,
            "destination_path": destination,
            "source_item_id": str(source_item.get("id") or ""),
            "destination_item_id": str((shop.get_item_by_path(destination) or {}).get("id") or ""),
            "copied": copied,
            "file_count": len(source_files),
            "total_bytes": source_bytes,
        })
        print(
            f"copy {index}/{len(LEGACY_PHOTO_GROUPS)}: "
            f"{len(source_files)} files {'copied' if copied else 'verified'} - {group.source_path}",
            flush=True,
        )

    if total_source_files != EXPECTED_SOURCE_FILE_COUNT:
        raise RuntimeError(
            f"Legacy source count changed: {total_source_files} != {EXPECTED_SOURCE_FILE_COUNT}"
        )
    if total_destination_files != EXPECTED_SOURCE_FILE_COUNT:
        raise RuntimeError("Completed Build Photos total does not match the source")
    if total_source_bytes != total_destination_bytes:
        raise RuntimeError("Completed Build Photos byte total does not match the source")
    return {
        "phase": "copy",
        "at": _now(),
        "groups": results,
        "group_count": len(results),
        "source_file_count": total_source_files,
        "destination_file_count": total_destination_files,
        "source_total_bytes": total_source_bytes,
        "destination_total_bytes": total_destination_bytes,
    }


def verify(paths: AppPaths) -> dict:
    config, company, shop = _gateways()
    company_root, shop_root = _roots(config)
    wanted = desired_agency_names(paths)
    company_audit = _root_audit(company, company_root, wanted)
    shop_audit = _root_audit(shop, shop_root, wanted)
    source_files, source_folders = _tree_manifest(shop, "Build Photos")
    plan = create_completed_projects(paths, mirror_to_cloud=False)
    project_ids = {target["project_id"] for target in plan["targets"].values()}
    completed = [load_project(project_id, paths) for project_id in project_ids]
    if any(project.project_status != "completed" for project in completed):
        raise RuntimeError("A migrated historical project is not completed")
    if len(source_files) != EXPECTED_SOURCE_FILE_COUNT:
        raise RuntimeError("The untouched legacy source file count changed")
    if company_audit["unwanted"] or shop_audit["unwanted"]:
        raise RuntimeError("Database roots contain agencies outside the approved scope")
    if {str(item.get("name") or "") for item in company_audit["retained"]} != wanted:
        raise RuntimeError("Company database roots do not match the approved agency set")
    if {str(item.get("name") or "") for item in shop_audit["retained"]} != wanted:
        raise RuntimeError("Shop database roots do not match the approved agency set")

    destination_file_count = 0
    destination_total_bytes = 0
    for group in LEGACY_PHOTO_GROUPS:
        target = plan["targets"][group.source_path]
        project = load_project(target["project_id"], paths)
        unit = next(item for item in project.build_units if item.unit_id == target["unit_id"])
        individual = next(
            item for item in unit.individuals
            if item.individual_id == target["individual_id"]
        )
        source_group_files, source_group_folders = _tree_manifest(shop, group.source_path)
        destination = f"{individual.shop_vehicle_folder_path}/Completed Build Photos"
        destination_files, destination_folders = _tree_manifest(shop, destination)
        if destination_files != source_group_files or destination_folders != source_group_folders:
            raise RuntimeError(f"Final destination verification failed: {destination}")
        destination_file_count += len(destination_files)
        destination_total_bytes += sum(destination_files.values())
    if destination_file_count != EXPECTED_SOURCE_FILE_COUNT:
        raise RuntimeError("Final destination file total changed")
    if destination_total_bytes != sum(source_files.values()):
        raise RuntimeError("Final destination byte total changed")

    storage = wiring.get_active_bundle().storage
    remote_project_count = 0
    for project_id in sorted(project_ids):
        local_payload = json.loads(
            (paths.workspace_projects_dir / project_id / "project.json").read_text("utf-8")
        )
        remote_payload = json.loads(storage.read_text(f"Projects/{project_id}.json"))
        if remote_payload != local_payload:
            raise RuntimeError(f"Remote project mirror differs from local state: {project_id}")
        remote_project_count += 1

    wanted_folded = {name.casefold() for name in wanted}
    remote_cleared_agencies = 0
    remote_joint_agency = False
    for agency in agency_service.load_agencies(paths):
        remote = json.loads(storage.read_text(f"Settings/agencies/{agency.agency_id}.json"))
        if agency.name == "Benton-Stearns Negotiator Van":
            if remote.get("abbreviation") != "BSNV":
                raise RuntimeError("Remote BSNV agency record is incomplete")
            remote_joint_agency = True
        if agency.name.casefold() in wanted_folded:
            continue
        for field in (
            "company_folder_id", "company_folder_path", "company_folder_error",
            "shop_folder_id", "shop_folder_path", "shop_folder_error",
        ):
            if remote.get(field):
                raise RuntimeError(f"Remote standalone agency still has {field}: {agency.name}")
        if remote.get("company_folder_status") != "not_provisioned":
            raise RuntimeError(f"Remote Company state was not cleared: {agency.name}")
        if remote.get("shop_folder_status") != "not_provisioned":
            raise RuntimeError(f"Remote Shop state was not cleared: {agency.name}")
        remote_cleared_agencies += 1
    if remote_cleared_agencies != EXPECTED_UNWANTED_ROOTS_PER_DATABASE:
        raise RuntimeError("Remote standalone-agency verification count changed")
    if not remote_joint_agency:
        raise RuntimeError("The remote BSNV agency record is missing")
    return {
        "phase": "verify",
        "at": _now(),
        "agency_root_count": len(wanted),
        "company_root_count": company_audit["total"],
        "shop_root_count": shop_audit["total"],
        "historical_project_count": len(completed),
        "historical_build_group_count": sum(len(project.build_units) for project in completed),
        "legacy_source_file_count": len(source_files),
        "legacy_source_folder_count": len(source_folders),
        "legacy_source_total_bytes": sum(source_files.values()),
        "destination_file_count": destination_file_count,
        "destination_total_bytes": destination_total_bytes,
        "remote_project_count": remote_project_count,
        "remote_cleared_agency_count": remote_cleared_agencies,
        "remote_joint_agency": remote_joint_agency,
    }


_PHASES = {
    "audit": audit,
    "cleanup": cleanup,
    "state": reconcile_state,
    "projects": projects,
    "provision": provision,
    "copy": copy_photos,
    "verify": verify,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=tuple(_PHASES))
    args = parser.parse_args(argv)
    paths = AppPaths()
    report = _PHASES[args.phase](paths)
    report_path = _write_report(report, args.phase)
    summary = {
        key: value for key, value in report.items()
        if key not in {"deleted_company", "deleted_shop", "groups", "targets", "projects"}
    }
    summary["report"] = str(report_path)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
