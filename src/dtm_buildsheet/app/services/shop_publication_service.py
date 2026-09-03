"""Publish finalized vehicle packages to the opt-in Shop Documents target.

The service owns only the exact PDF/reference item IDs persisted on an
``IndividualUnit``. It creates (but never enumerates or mutates inside)
``Completed Build Photos``. Production remains inert until the separate
``shop_publication_enabled`` configuration switch is explicitly enabled. The
retry sweep also catches finalized records created before production cutover,
provided their exact PDF is available on the current workstation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from ...domain.vehicle_naming import (
    project_year_folder_name,
    safe_vehicle_folder_name,
    vehicle_folder_name,
)
from ...inputs.project_entry import list_projects, load_project, save_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway
from .reference_package_service import resolve_reference_package


logger = logging.getLogger(__name__)
_publication_lock = threading.RLock()


class ShopPublicationGateway(Protocol):
    """Narrow item-ID based boundary used by publication and its tests."""

    def ensure_folder(self, remote_path: str) -> dict: ...
    def move_item(self, item_id: str, *, parent_id: str, new_name: str) -> dict: ...
    def upload_file(self, remote_path: str, data: bytes) -> dict: ...
    def delete_item(self, item_id: str) -> None: ...


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_segment(value: str, *, fallback: str) -> str:
    cleaned = safe_vehicle_folder_name(value)
    return cleaned if cleaned != "Unidentified Vehicle" else fallback


def _find_target(project, unit_id: str, individual_id: str):
    unit = next((item for item in project.build_units if item.unit_id == unit_id), None)
    if unit is None:
        raise ValueError("Build unit not found")
    individual = next(
        (item for item in unit.individuals if item.individual_id == individual_id),
        None,
    )
    if individual is None:
        raise ValueError("Individual unit not found")
    return unit, individual


def shop_publication_configured() -> bool:
    """Return whether this install has explicitly enabled the Shop target."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return False
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return False
    try:
        from ..adapters.cloud.config import load_cloud_config_from_env
        return load_cloud_config_from_env().shop_target_configured
    except Exception:
        return False


def _shop_config():
    from ..adapters.cloud.config import load_cloud_config_from_env
    config = load_cloud_config_from_env()
    if not config.shop_target_configured:
        raise RuntimeError("Shop publication is not configured")
    return config


def _package_fingerprint(pdf_path: Path, folder_path: str, package) -> str:
    digest = hashlib.sha256()
    digest.update(folder_path.encode("utf-8"))
    with pdf_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    reference_manifest = [
        {
            "reference_id": entry.asset.reference_id,
            "source_item_id": entry.asset.source_item_id,
            "source_etag": entry.asset.source_etag,
            "published_file_name": entry.published_file_name,
            "note": entry.assignment.note,
            "origin": entry.origin,
        }
        for entry in package.entries
    ]
    digest.update(json.dumps(reference_manifest, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _shop_paths(project, unit, individual, *, root: str) -> dict[str, str]:
    ordinal = next(
        (index for index, item in enumerate(unit.individuals, start=1)
         if item.individual_id == individual.individual_id),
        1,
    )
    folder_name = vehicle_folder_name(project, unit, individual, ordinal=ordinal)
    segments = [
        str(root or "Shop Project Database").strip().strip("/"),
        _safe_segment(project.customer.agency, fallback="Unassigned Agency"),
        _safe_segment(project_year_folder_name(project), fallback="Unassigned Year"),
        folder_name,
    ]
    vehicle_path = "/".join(segment for segment in segments if segment)
    return {
        "year": "/".join(segments[:3]),
        "folder_name": folder_name,
        "vehicle": vehicle_path,
        "parent": vehicle_path.rsplit("/", 1)[0],
        "references": f"{vehicle_path}/Build Reference Photos",
        "completed": f"{vehicle_path}/Completed Build Photos",
        "pdf": f"{vehicle_path}/{folder_name}.pdf",
    }


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (FileNotFoundError, ValueError)):
        return str(exc)
    return "Shop publication could not be completed. It will retry during cloud sync."


def publish_vehicle_package(
    project_id: str,
    unit_id: str,
    individual_id: str,
    paths: AppPaths,
    *,
    gateway: ShopPublicationGateway | None = None,
    shop_root: str | None = None,
) -> dict:
    """Publish one finalized PDF/photo package, replacing only owned items."""
    with _publication_lock:
        project = load_project(project_id, paths)
        unit, individual = _find_target(project, unit_id, individual_id)
        if individual.status != "finalized":
            return {"ok": False, "error": "Only finalized vehicles can be published"}
        pdf_path = Path(str(individual.pdf_path or ""))
        if not pdf_path.is_absolute():
            pdf_path = paths.workspace_dir / pdf_path
        if not pdf_path.is_file():
            error = "The finalized PDF is not available on this workstation."
            individual.shop_publication_status = "error"
            individual.shop_publication_error = error
            save_project(project, paths)
            return {"ok": False, "error": error}

        try:
            if gateway is None:
                config = _shop_config()
                gateway = GraphDriveGateway.from_active_cloud(
                    config,
                    library_names=(config.shop_library_name, config.shop_library_internal_name),
                )
                root = config.shop_build_photos_root
            else:
                root = shop_root or "Shop Project Database"
            remote = _shop_paths(project, unit, individual, root=root)
            package = resolve_reference_package(
                project, unit_id=unit_id, individual_id=individual_id, paths=paths,
            )
            if package.errors:
                raise ValueError("One or more assigned build reference photos are unavailable.")
            fingerprint = _package_fingerprint(pdf_path, remote["vehicle"], package)
            if (
                individual.shop_publication_status == "published"
                and individual.shop_publication_fingerprint == fingerprint
                and individual.shop_pdf_item_id
                and individual.shop_vehicle_folder_path == remote["vehicle"]
                and project.shop_year_folder_path == remote["year"]
            ):
                return {
                    "ok": True,
                    "unchanged": True,
                    "folder_path": remote["vehicle"],
                    "published_at": individual.shop_published_at,
                }

            individual.shop_publication_status = "publishing"
            individual.shop_publication_error = ""
            save_project(project, paths)

            year_folder = gateway.ensure_folder(remote["year"])
            parent = (
                year_folder
                if remote["parent"] == remote["year"]
                else gateway.ensure_folder(remote["parent"])
            )
            if individual.shop_vehicle_folder_id:
                folder = gateway.move_item(
                    individual.shop_vehicle_folder_id,
                    parent_id=str(parent.get("id") or ""),
                    new_name=remote["folder_name"],
                )
            else:
                folder = gateway.ensure_folder(remote["vehicle"])
            gateway.ensure_folder(remote["references"])
            # This is the only operation involving Completed Build Photos.
            # Never list or delete its children.
            gateway.ensure_folder(remote["completed"])
            pdf_item = gateway.upload_file(remote["pdf"], pdf_path.read_bytes())
            published_refs = []
            for entry in package.entries:
                ref_path = f"{remote['references']}/{entry.published_file_name}"
                item = gateway.upload_file(ref_path, entry.local_path.read_bytes())
                published_refs.append({
                    "reference_id": entry.asset.reference_id,
                    "item_id": str(item.get("id") or ""),
                    "file_name": entry.published_file_name,
                    "path": ref_path,
                    "source_etag": entry.asset.source_etag,
                })

            new_ids = {str(item.get("item_id") or "") for item in published_refs}
            for old in individual.shop_reference_items:
                old_id = str(old.get("item_id") or "") if isinstance(old, dict) else ""
                if old_id and old_id not in new_ids:
                    gateway.delete_item(old_id)
            old_pdf_id = str(individual.shop_pdf_item_id or "")
            new_pdf_id = str(pdf_item.get("id") or "")
            if old_pdf_id and old_pdf_id != new_pdf_id:
                gateway.delete_item(old_pdf_id)

            individual.shop_vehicle_folder_id = str(folder.get("id") or "")
            individual.shop_vehicle_folder_name = remote["folder_name"]
            individual.shop_vehicle_folder_path = remote["vehicle"]
            individual.shop_folder_status = "provisioned"
            individual.shop_folder_error = ""
            individual.shop_pdf_item_id = new_pdf_id
            individual.shop_pdf_path = remote["pdf"]
            individual.shop_reference_items = published_refs
            individual.shop_publication_fingerprint = fingerprint
            individual.shop_published_at = _utcnow()
            individual.shop_publication_status = "published"
            individual.shop_publication_error = ""
            project.shop_year_folder_id = str(year_folder.get("id") or "")
            project.shop_year_folder_path = remote["year"]
            project.shop_folder_status = "provisioned"
            project.shop_folder_error = ""
            save_project(project, paths)
            return {
                "ok": True,
                "unchanged": False,
                "folder_path": remote["vehicle"],
                "pdf_item_id": new_pdf_id,
                "reference_count": len(published_refs),
                "published_at": individual.shop_published_at,
            }
        except Exception as exc:
            logger.exception("Shop package publication failed for project %s", project_id)
            # Reload so an earlier status save cannot overwrite concurrent
            # project changes while recording the retryable failure.
            current = load_project(project_id, paths)
            _, current_individual = _find_target(current, unit_id, individual_id)
            current_individual.shop_publication_status = "error"
            current_individual.shop_publication_error = _safe_error(exc)
            save_project(current, paths)
            return {"ok": False, "error": current_individual.shop_publication_error}


def handle_republish_vehicle_package(
    project_id: str, unit_id: str, individual_id: str, paths: AppPaths,
) -> dict:
    """Replace an existing app-owned Shop package after an explicit user choice."""
    try:
        project = load_project(project_id, paths)
        _, individual = _find_target(project, unit_id, individual_id)
        if individual.status != "finalized":
            return {"ok": False, "error": "Only finalized vehicles can update the Shop PDF"}
        if not str(individual.shop_pdf_item_id or "").strip():
            return {"ok": False, "error": "This vehicle does not have an existing Shop PDF to replace"}
    except FileNotFoundError:
        return {"ok": False, "error": "Project not found"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return publish_vehicle_package(project_id, unit_id, individual_id, paths)


def withdraw_vehicle_package(
    project_id: str,
    unit_id: str,
    individual_id: str,
    paths: AppPaths,
    *,
    gateway: ShopPublicationGateway | None = None,
) -> dict:
    """Delete only stored app-owned item IDs; preserve all folders/photos."""
    with _publication_lock:
        project = load_project(project_id, paths)
        _, individual = _find_target(project, unit_id, individual_id)
        owned_ids = [str(individual.shop_pdf_item_id or "")]
        owned_ids.extend(
            str(item.get("item_id") or "")
            for item in individual.shop_reference_items
            if isinstance(item, dict)
        )
        owned_ids = list(dict.fromkeys(item_id for item_id in owned_ids if item_id))
        if not owned_ids:
            individual.shop_publication_status = "not_published"
            individual.shop_publication_error = ""
            save_project(project, paths)
            return {"ok": True, "deleted": 0}
        try:
            if gateway is None:
                config = _shop_config()
                gateway = GraphDriveGateway.from_active_cloud(
                    config,
                    library_names=(config.shop_library_name, config.shop_library_internal_name),
                )
            individual.shop_publication_status = "withdrawing"
            individual.shop_publication_error = ""
            save_project(project, paths)
            for item_id in owned_ids:
                gateway.delete_item(item_id)
            current = load_project(project_id, paths)
            _, current_individual = _find_target(current, unit_id, individual_id)
            current_individual.shop_pdf_item_id = ""
            current_individual.shop_pdf_path = ""
            current_individual.shop_reference_items = []
            current_individual.shop_publication_fingerprint = ""
            current_individual.shop_published_at = ""
            current_individual.shop_publication_status = "not_published"
            current_individual.shop_publication_error = ""
            save_project(current, paths)
            return {"ok": True, "deleted": len(owned_ids)}
        except Exception as exc:
            logger.exception("Shop package withdrawal failed for project %s", project_id)
            current = load_project(project_id, paths)
            _, current_individual = _find_target(current, unit_id, individual_id)
            current_individual.shop_publication_status = "withdrawal_error"
            current_individual.shop_publication_error = _safe_error(exc)
            save_project(current, paths)
            return {"ok": False, "error": current_individual.shop_publication_error}


def schedule_vehicle_publication(
    project_id: str, unit_id: str, individual_id: str, paths: AppPaths,
) -> bool:
    if not individual_id or not shop_publication_configured():
        return False
    threading.Thread(
        target=publish_vehicle_package,
        args=(project_id, unit_id, individual_id, paths),
        name="shop-package-publish",
        daemon=True,
    ).start()
    return True


def schedule_vehicle_withdrawal(
    project_id: str, unit_id: str, individual_id: str, paths: AppPaths,
) -> bool:
    if not individual_id or not shop_publication_configured():
        return False
    threading.Thread(
        target=withdraw_vehicle_package,
        args=(project_id, unit_id, individual_id, paths),
        name="shop-package-withdraw",
        daemon=True,
    ).start()
    return True


def retry_pending_shop_publications(paths: AppPaths) -> dict:
    """Retry durable publish/withdraw states during an ordinary cloud sync."""
    if not shop_publication_configured():
        return {"enabled": False, "attempted": 0, "succeeded": 0, "failed": 0}
    attempted = succeeded = failed = 0
    for project in list_projects(paths):
        for unit in project.build_units:
            for individual in unit.individuals:
                status = str(individual.shop_publication_status or "")
                pdf_path = Path(str(individual.pdf_path or ""))
                if not pdf_path.is_absolute():
                    pdf_path = paths.workspace_dir / pdf_path
                catch_up = status in {"", "not_published"} and pdf_path.is_file()
                if (
                    individual.status == "finalized"
                    and (status in {"pending", "publishing", "error"} or catch_up)
                ):
                    attempted += 1
                    result = publish_vehicle_package(
                        project.project_id, unit.unit_id, individual.individual_id, paths,
                    )
                elif individual.status != "finalized" and status in {
                    "withdrawal_pending", "withdrawing", "withdrawal_error",
                }:
                    attempted += 1
                    result = withdraw_vehicle_package(
                        project.project_id, unit.unit_id, individual.individual_id, paths,
                    )
                else:
                    continue
                if result.get("ok"):
                    succeeded += 1
                else:
                    failed += 1
    return {"enabled": True, "attempted": attempted, "succeeded": succeeded, "failed": failed}
