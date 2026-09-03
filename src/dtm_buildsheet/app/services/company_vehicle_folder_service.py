"""Company Files vehicle folders and PDF publication.

The explicit cutover flag keeps this path independently controllable from
folder provisioning. Production uses the per-vehicle ``Vehicle Project
Database`` tree; the legacy agency/year PDF tree is no longer dual-written.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

from ...domain.vehicle_naming import (
    project_year_folder_name,
    safe_vehicle_folder_name,
    vehicle_folder_name,
)
from ...inputs.project_entry import list_projects, load_project, save_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway
from .shop_publication_service import ShopPublicationGateway


logger = logging.getLogger(__name__)
_company_lock = threading.RLock()


def _safe_segment(value: str, fallback: str) -> str:
    cleaned = safe_vehicle_folder_name(value)
    return cleaned if cleaned != "Unidentified Vehicle" else fallback


def company_vehicle_folders_configured() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return False
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return False
    try:
        from ..adapters.cloud.config import load_cloud_config_from_env
        return load_cloud_config_from_env().company_target_configured
    except Exception:
        return False


def _config():
    from ..adapters.cloud.config import load_cloud_config_from_env
    config = load_cloud_config_from_env()
    if not config.company_target_configured:
        raise RuntimeError("Company vehicle folders are not configured")
    return config


def _target(project, unit_id: str, individual_id: str):
    unit = next((item for item in project.build_units if item.unit_id == unit_id), None)
    if unit is None:
        raise ValueError("Build unit not found")
    individual = next(
        (item for item in unit.individuals if item.individual_id == individual_id), None,
    )
    if individual is None:
        raise ValueError("Individual unit not found")
    return unit, individual


def _paths(project, unit, individual, *, root: str) -> dict[str, str]:
    ordinal = next(
        (index for index, item in enumerate(unit.individuals, start=1)
         if item.individual_id == individual.individual_id), 1,
    )
    vehicle = vehicle_folder_name(project, unit, individual, ordinal=ordinal)
    year_root = "/".join((
        str(root or "Vehicle Project Database").strip().strip("/"),
        _safe_segment(project.customer.agency, "Unassigned Agency"),
        _safe_segment(project_year_folder_name(project), "Unassigned Year"),
    ))
    vehicle_path = "/".join((
        year_root,
        vehicle,
    ))
    return {
        "year": year_root,
        "references": f"{year_root}/Reference Photos & Videos",
        "folder_name": vehicle,
        "parent": vehicle_path.rsplit("/", 1)[0],
        "vehicle": vehicle_path,
        "pdf": f"{vehicle_path}/{vehicle}.pdf",
    }


def publish_company_vehicle_pdf(
    project_id: str,
    unit_id: str,
    individual_id: str,
    paths: AppPaths,
    *,
    gateway: ShopPublicationGateway | None = None,
    company_root: str | None = None,
) -> dict:
    with _company_lock:
        project = load_project(project_id, paths)
        unit, individual = _target(project, unit_id, individual_id)
        pdf_path = Path(str(individual.pdf_path or ""))
        if not pdf_path.is_absolute():
            pdf_path = paths.workspace_dir / pdf_path
        if not pdf_path.is_file():
            individual.company_publication_status = "error"
            individual.company_publication_error = "The current PDF is unavailable on this workstation."
            save_project(project, paths)
            return {"ok": False, "error": individual.company_publication_error}
        try:
            if gateway is None:
                config = _config()
                gateway = GraphDriveGateway.from_active_cloud(
                    config,
                    library_names=(
                        config.company_library_name,
                        config.company_library_internal_name,
                        config.exports_library_name,
                        config.exports_library_internal_name,
                    ),
                )
                root = config.company_vehicle_root
            else:
                root = company_root or "Vehicle Project Database"
            remote = _paths(project, unit, individual, root=root)
            digest = hashlib.sha256()
            digest.update(remote["pdf"].encode("utf-8"))
            pdf_bytes = pdf_path.read_bytes()
            digest.update(pdf_bytes)
            fingerprint = digest.hexdigest()
            if (
                individual.company_publication_status == "published"
                and individual.company_publication_fingerprint == fingerprint
                and individual.company_pdf_item_id
                and individual.company_vehicle_folder_path == remote["vehicle"]
                and project.company_year_folder_path == remote["year"]
            ):
                return {"ok": True, "unchanged": True, "path": remote["pdf"]}

            individual.company_publication_status = "publishing"
            individual.company_publication_error = ""
            save_project(project, paths)
            year_folder = gateway.ensure_folder(remote["year"])
            gateway.ensure_folder(remote["references"])
            parent = (
                year_folder
                if remote["parent"] == remote["year"]
                else gateway.ensure_folder(remote["parent"])
            )
            if individual.company_vehicle_folder_id:
                folder = gateway.move_item(
                    individual.company_vehicle_folder_id,
                    parent_id=str(parent.get("id") or ""),
                    new_name=remote["folder_name"],
                )
            else:
                folder = gateway.ensure_folder(remote["vehicle"])
            pdf_item = gateway.upload_file(remote["pdf"], pdf_bytes)
            old_id = str(individual.company_pdf_item_id or "")
            new_id = str(pdf_item.get("id") or "")
            if old_id and old_id != new_id:
                gateway.delete_item(old_id)
            individual.company_vehicle_folder_id = str(folder.get("id") or "")
            individual.company_vehicle_folder_name = remote["folder_name"]
            individual.company_vehicle_folder_path = remote["vehicle"]
            individual.company_folder_status = "provisioned"
            individual.company_folder_error = ""
            individual.company_pdf_item_id = new_id
            individual.company_pdf_path = remote["pdf"]
            individual.company_publication_fingerprint = fingerprint
            individual.company_publication_status = "published"
            individual.company_publication_error = ""
            project.company_year_folder_id = str(year_folder.get("id") or "")
            project.company_year_folder_path = remote["year"]
            project.company_folder_status = "provisioned"
            project.company_folder_error = ""
            save_project(project, paths)
            return {"ok": True, "unchanged": False, "path": remote["pdf"], "pdf_item_id": new_id}
        except Exception:
            logger.exception("Company vehicle PDF publication failed for project %s", project_id)
            current = load_project(project_id, paths)
            _, current_individual = _target(current, unit_id, individual_id)
            current_individual.company_publication_status = "error"
            current_individual.company_publication_error = (
                "Company vehicle PDF publication could not be completed. It will retry during cloud sync."
            )
            save_project(current, paths)
            return {"ok": False, "error": current_individual.company_publication_error}


def schedule_company_vehicle_pdf(
    project_id: str, unit_id: str, individual_id: str, paths: AppPaths,
) -> bool:
    if not individual_id or not company_vehicle_folders_configured():
        return False
    threading.Thread(
        target=publish_company_vehicle_pdf,
        args=(project_id, unit_id, individual_id, paths),
        name="company-vehicle-pdf",
        daemon=True,
    ).start()
    return True


def retry_pending_company_vehicle_pdfs(paths: AppPaths) -> dict:
    if not company_vehicle_folders_configured():
        return {"enabled": False, "attempted": 0, "succeeded": 0, "failed": 0}
    attempted = succeeded = failed = 0
    for project in list_projects(paths):
        for unit in project.build_units:
            for individual in unit.individuals:
                status = str(individual.company_publication_status or "not_published")
                pdf_path = Path(str(individual.pdf_path or ""))
                if not pdf_path.is_absolute():
                    pdf_path = paths.workspace_dir / pdf_path
                catch_up = status == "not_published" and pdf_path.is_file()
                if status not in {"pending", "publishing", "error"} and not catch_up:
                    continue
                attempted += 1
                result = publish_company_vehicle_pdf(
                    project.project_id, unit.unit_id, individual.individual_id, paths,
                )
                if result.get("ok"):
                    succeeded += 1
                else:
                    failed += 1
    return {"enabled": True, "attempted": attempted, "succeeded": succeeded, "failed": failed}
