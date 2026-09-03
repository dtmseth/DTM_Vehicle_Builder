"""Progressively provision the flag-gated Company and Shop vehicle trees.

The lifecycle is intentionally additive and project-scoped:

* project save -> agency/year/reference/vehicle folders;
* known physical vehicle -> vehicle/photo folders, with stable placeholders
  for legacy records that do not yet have a unit number or VIN.

Standalone Agency Manager and QuickBooks Customer records never create folders.
Historical Build Photos agencies enter the lifecycle through ordinary sparse
projects created by the reviewed photo migration.

No source file is copied or deleted here. Stored Graph item IDs let flattening
and later renames move an already-created vehicle subtree without guessing by
path or disturbing the photos inside it.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

from ...domain.vehicle_naming import (
    project_year_folder_name,
    safe_vehicle_folder_name,
    vehicle_folder_name,
)
from ...inputs.project_entry import (
    list_projects,
    load_project,
    save_project_operational_state,
)
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway
from .agency_service import get_agency, load_agencies, save_agency_folder_state
from .shop_publication_service import ShopPublicationGateway


logger = logging.getLogger(__name__)
_provisioning_lock = threading.RLock()


@dataclass(frozen=True)
class ProvisioningTargets:
    company: bool
    shop: bool


def _safe_segment(value: str, fallback: str) -> str:
    cleaned = safe_vehicle_folder_name(value)
    return cleaned if cleaned != "Unidentified Vehicle" else fallback


def _enabled_config():
    from ..adapters.cloud.config import load_cloud_config_from_env
    return load_cloud_config_from_env()


def folder_provisioning_targets() -> ProvisioningTargets:
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return ProvisioningTargets(False, False)
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return ProvisioningTargets(False, False)
    try:
        config = _enabled_config()
        return ProvisioningTargets(
            config.company_provisioning_target_configured,
            config.shop_provisioning_target_configured,
        )
    except Exception:
        return ProvisioningTargets(False, False)


def mark_agency_folder_provisioning_pending(record) -> bool:
    """Mark enabled roots before the agency edit is durably saved.

    If the app closes before the daemon provisioner starts, the next sync can
    still see that the readable path needs to be reconciled.
    """
    targets = folder_provisioning_targets()
    changed = False
    for target, enabled in (("company", targets.company), ("shop", targets.shop)):
        if not enabled:
            continue
        status_field = f"{target}_folder_status"
        error_field = f"{target}_folder_error"
        changed = changed or getattr(record, status_field, "") != "pending"
        setattr(record, status_field, "pending")
        setattr(record, error_field, "")
    return changed


def mark_project_folder_provisioning_pending(project) -> bool:
    """Mark enabled project and vehicle targets before project persistence."""
    targets = folder_provisioning_targets()
    changed = False
    for target, enabled in (("company", targets.company), ("shop", targets.shop)):
        if not enabled:
            continue
        project_status = f"{target}_folder_status"
        project_error = f"{target}_folder_error"
        changed = changed or getattr(project, project_status, "") != "pending"
        setattr(project, project_status, "pending")
        setattr(project, project_error, "")
        for unit in project.build_units:
            for individual in unit.individuals:
                status = "pending"
                status_field = f"{target}_folder_status"
                error_field = f"{target}_folder_error"
                changed = changed or getattr(individual, status_field, "") != status
                setattr(individual, status_field, status)
                setattr(individual, error_field, "")
    return changed


def _company_gateway(config) -> GraphDriveGateway:
    return GraphDriveGateway.from_active_cloud(
        config,
        library_names=(
            config.company_library_name,
            config.company_library_internal_name,
            config.exports_library_name,
            config.exports_library_internal_name,
        ),
    )


def _shop_gateway(config) -> GraphDriveGateway:
    return GraphDriveGateway.from_active_cloud(
        config,
        library_names=(config.shop_library_name, config.shop_library_internal_name),
    )


def _ensure_or_move(
    gateway: ShopPublicationGateway,
    *,
    item_id: str,
    current_path: str,
    target_path: str,
    parent_path: str,
    target_name: str,
) -> dict:
    if item_id and current_path == target_path:
        return {"id": item_id, "name": target_name}
    if item_id:
        parent = gateway.ensure_folder(parent_path)
        return gateway.move_item(
            item_id,
            parent_id=str(parent.get("id") or ""),
            new_name=target_name,
        )
    return gateway.ensure_folder(target_path)


def _drive_item_locator(item: dict) -> tuple[str, str, str]:
    """Return ``(item_path, parent_id, parent_path)`` from Graph metadata."""
    name = str(item.get("name") or "").strip()
    parent = item.get("parentReference")
    if not name or "/" in name or "\\" in name or not isinstance(parent, dict):
        return "", "", ""
    raw_parent_path = str(parent.get("path") or "")
    if "/root:" in raw_parent_path:
        parent_path = raw_parent_path.split("/root:", 1)[1].strip("/")
    elif raw_parent_path.startswith("root:"):
        parent_path = raw_parent_path.split("root:", 1)[1].strip("/")
    else:
        return "", "", ""
    item_path = "/".join(filter(None, (parent_path, name)))
    return item_path, str(parent.get("id") or ""), parent_path


def _resolve_vehicle_item_locations(project, gateway, *, target: str) -> dict:
    """Recover current vehicle paths after out-of-band SharePoint moves."""
    get_item = getattr(gateway, "get_item", None)
    if not callable(get_item):
        return {}
    resolved: dict[tuple[str, str], tuple[str, str, str]] = {}
    for unit in project.build_units:
        for individual in unit.individuals:
            item_id = str(getattr(individual, f"{target}_vehicle_folder_id") or "")
            if not item_id:
                continue
            try:
                item = get_item(item_id)
            except Exception:
                logger.warning(
                    "Could not resolve current %s vehicle folder %s by item ID",
                    target,
                    individual.individual_id,
                    exc_info=True,
                )
                continue
            if not isinstance(item, dict):
                continue
            item_path, parent_id, parent_path = _drive_item_locator(item)
            if item_path and parent_id and parent_path:
                resolved[(unit.unit_id, individual.individual_id)] = (
                    item_path,
                    parent_id,
                    parent_path,
                )
    return resolved


def provision_agency_folders(
    agency_id: str,
    paths: AppPaths,
    *,
    company_gateway: ShopPublicationGateway | None = None,
    shop_gateway: ShopPublicationGateway | None = None,
    company_root: str | None = None,
    shop_root: str | None = None,
) -> dict:
    """Create or rename one agency's roots without touching their contents."""
    with _provisioning_lock:
        agency = get_agency(paths, agency_id)
        if agency is None:
            return {"ok": False, "error": "Agency not found"}
        config = None
        if company_gateway is None or shop_gateway is None:
            targets = folder_provisioning_targets()
            if targets.company or targets.shop:
                config = _enabled_config()
        else:
            targets = ProvisioningTargets(True, True)

        state: dict[str, str] = {}
        attempted = succeeded = 0
        if company_gateway is not None or targets.company:
            attempted += 1
            try:
                gateway = company_gateway or _company_gateway(config)
                configured = config.company_vehicle_root if config is not None else ""
                root = str(company_root or configured or "Vehicle Project Database").strip("/")
                name = _safe_segment(agency.name, "Unassigned Agency")
                target = f"{root}/{name}"
                item = _ensure_or_move(
                    gateway,
                    item_id=agency.company_folder_id,
                    current_path=agency.company_folder_path,
                    target_path=target,
                    parent_path=root,
                    target_name=name,
                )
                state.update({
                    "company_folder_id": str(item.get("id") or agency.company_folder_id),
                    "company_folder_path": target,
                    "company_folder_status": "provisioned",
                    "company_folder_error": "",
                })
                succeeded += 1
            except Exception:
                logger.exception("Company agency folder provisioning failed for %s", agency_id)
                state.update({
                    "company_folder_status": "error",
                    "company_folder_error": "Company folder provisioning will retry during cloud sync.",
                })

        if shop_gateway is not None or targets.shop:
            attempted += 1
            try:
                gateway = shop_gateway or _shop_gateway(config)
                configured = config.shop_build_photos_root if config is not None else ""
                root = str(shop_root or configured or "Shop Project Database").strip("/")
                name = _safe_segment(agency.name, "Unassigned Agency")
                target = f"{root}/{name}"
                item = _ensure_or_move(
                    gateway,
                    item_id=agency.shop_folder_id,
                    current_path=agency.shop_folder_path,
                    target_path=target,
                    parent_path=root,
                    target_name=name,
                )
                state.update({
                    "shop_folder_id": str(item.get("id") or agency.shop_folder_id),
                    "shop_folder_path": target,
                    "shop_folder_status": "provisioned",
                    "shop_folder_error": "",
                })
                succeeded += 1
            except Exception:
                logger.exception("Shop agency folder provisioning failed for %s", agency_id)
                state.update({
                    "shop_folder_status": "error",
                    "shop_folder_error": "Shop folder provisioning will retry during cloud sync.",
                })

        if state:
            save_agency_folder_state(paths, agency_id, state)
        return {
            "ok": attempted == succeeded,
            "enabled": bool(attempted),
            "attempted": attempted,
            "succeeded": succeeded,
            "failed": attempted - succeeded,
        }


def _project_paths(
    project,
    *,
    company_root: str,
    shop_root: str,
    agency_name: str = "",
) -> dict[str, str]:
    agency = _safe_segment(agency_name or project.customer.agency, "Unassigned Agency")
    year = _safe_segment(project_year_folder_name(project), "Unassigned Year")
    company_agency = "/".join((company_root.strip("/"), agency))
    shop_agency = "/".join((shop_root.strip("/"), agency))
    return {
        "year_name": year,
        "company_agency": company_agency,
        "company_year": f"{company_agency}/{year}",
        "shop_agency": shop_agency,
        "shop_year": f"{shop_agency}/{year}",
    }


def _rewrite_project_root_prefix(project, *, target: str, old_root: str, new_root: str) -> None:
    """Keep descendant locators valid after their agency root moves by ID.

    If an agency root is renamed first (notably when restoring the ampersand
    in ICE), the same subtree is immediately reachable under the new root.
    Rewriting in-memory locators keeps the durable vehicle and publication
    paths aligned until each vehicle is reconciled by item ID.
    """
    old = str(old_root or "").rstrip("/")
    new = str(new_root or "").rstrip("/")
    if not old or not new or old == new:
        return

    def moved(value: str) -> str:
        current = str(value or "")
        if current == old:
            return new
        prefix = old + "/"
        return new + current[len(old):] if current.startswith(prefix) else current

    year_field = f"{target}_year_folder_path"
    setattr(project, year_field, moved(getattr(project, year_field)))
    for unit in project.build_units:
        group_field = f"{target}_group_folder_path"
        setattr(unit, group_field, moved(getattr(unit, group_field)))
        for individual in unit.individuals:
            vehicle_field = f"{target}_vehicle_folder_path"
            pdf_field = f"{target}_pdf_path"
            setattr(individual, vehicle_field, moved(getattr(individual, vehicle_field)))
            setattr(individual, pdf_field, moved(getattr(individual, pdf_field)))


def _provision_project_target(
    project,
    *,
    gateway: ShopPublicationGateway,
    target: str,
    root: str,
    agency_name: str = "",
) -> tuple[dict, dict[str, dict], dict[tuple[str, str], dict]]:
    paths = _project_paths(
        project,
        company_root=root if target == "company" else "Vehicle Project Database",
        shop_root=root if target == "shop" else "Shop Project Database",
        agency_name=agency_name,
    )
    agency_path = paths[f"{target}_agency"]
    year_path = paths[f"{target}_year"]
    year_id = getattr(project, f"{target}_year_folder_id")
    current_year_path = getattr(project, f"{target}_year_folder_path")
    gateway.ensure_folder(agency_path)

    # Paths are hints; durable item IDs are authoritative. A vehicle may have
    # been moved manually after an app edit, so recover its live location
    # before moving it directly beneath the project year.
    resolved_vehicles = _resolve_vehicle_item_locations(
        project, gateway, target=target,
    )

    year = _ensure_or_move(
        gateway,
        item_id=year_id,
        current_path=current_year_path,
        target_path=year_path,
        parent_path=agency_path,
        target_name=paths["year_name"],
    )
    if target == "company":
        gateway.ensure_folder(f"{year_path}/Reference Photos & Videos")

    group_states: dict[str, dict] = {}
    vehicle_states: dict[tuple[str, str], dict] = {}
    for unit in project.build_units:
        group_states[unit.unit_id] = {
            # Retain these codec fields for backward compatibility, but the
            # filesystem no longer has a unit-group layer.
            f"{target}_group_folder_id": "",
            f"{target}_group_folder_path": "",
        }
        for ordinal, individual in enumerate(unit.individuals, start=1):
            key = (unit.unit_id, individual.individual_id)
            folder_name = vehicle_folder_name(project, unit, individual, ordinal=ordinal)
            vehicle_path = f"{year_path}/{folder_name}"
            resolved_vehicle = resolved_vehicles.get(key)
            current_vehicle_path = (
                resolved_vehicle[0]
                if resolved_vehicle
                else getattr(individual, f"{target}_vehicle_folder_path")
            )
            item = _ensure_or_move(
                gateway,
                item_id=getattr(individual, f"{target}_vehicle_folder_id"),
                current_path=current_vehicle_path,
                target_path=vehicle_path,
                parent_path=year_path,
                target_name=folder_name,
            )
            if target == "shop":
                gateway.ensure_folder(f"{vehicle_path}/Build Reference Photos")
                gateway.ensure_folder(f"{vehicle_path}/Completed Build Photos")
            state = {
                f"{target}_vehicle_folder_id": str(item.get("id") or ""),
                f"{target}_vehicle_folder_name": folder_name,
                f"{target}_vehicle_folder_path": vehicle_path,
                f"{target}_folder_status": "provisioned",
                f"{target}_folder_error": "",
            }
            pdf_path_field = f"{target}_pdf_path"
            if str(getattr(individual, pdf_path_field, "") or ""):
                state[pdf_path_field] = f"{vehicle_path}/{folder_name}.pdf"
            if target == "shop" and individual.shop_reference_items:
                state["shop_reference_items"] = [
                    {
                        **entry,
                        "path": (
                            f"{vehicle_path}/Build Reference Photos/"
                            f"{str(entry.get('file_name') or '').strip()}"
                        ),
                    }
                    if isinstance(entry, dict) and str(entry.get("file_name") or "").strip()
                    else entry
                    for entry in individual.shop_reference_items
                ]
            vehicle_states[key] = state
    return {
        f"{target}_year_folder_id": str(year.get("id") or year_id),
        f"{target}_year_folder_path": year_path,
        f"{target}_folder_status": "provisioned",
        f"{target}_folder_error": "",
    }, group_states, vehicle_states


def provision_project_folders(
    project_id: str,
    paths: AppPaths,
    *,
    company_gateway: ShopPublicationGateway | None = None,
    shop_gateway: ShopPublicationGateway | None = None,
    company_root: str | None = None,
    shop_root: str | None = None,
) -> dict:
    """Provision all currently knowable folders for one project snapshot."""
    with _provisioning_lock:
        try:
            project = load_project(project_id, paths)
        except FileNotFoundError:
            return {"ok": False, "error": "Project not found"}
        config = None
        if company_gateway is None or shop_gateway is None:
            targets = folder_provisioning_targets()
            if targets.company or targets.shop:
                config = _enabled_config()
        else:
            targets = ProvisioningTargets(True, True)

        # Rename/move the agency roots first so creating a year cannot fork a
        # second path while an agency-name change is still being reconciled.
        current_agency = None
        prior_agency_paths: dict[str, str] = {}
        if project.customer.agency_id:
            current_agency = get_agency(paths, project.customer.agency_id)
            if current_agency is not None:
                prior_agency_paths = {
                    "company": current_agency.company_folder_path,
                    "shop": current_agency.shop_folder_path,
                }
            provision_agency_folders(
                project.customer.agency_id,
                paths,
                company_gateway=company_gateway,
                shop_gateway=shop_gateway,
                company_root=company_root,
                shop_root=shop_root,
            )
            current_agency = get_agency(paths, project.customer.agency_id)
            if current_agency is not None:
                for target in ("company", "shop"):
                    _rewrite_project_root_prefix(
                        project,
                        target=target,
                        old_root=prior_agency_paths.get(target, ""),
                        new_root=getattr(current_agency, f"{target}_folder_path"),
                    )

        project_state: dict = {}
        group_state: dict[str, dict] = {}
        vehicle_state: dict[tuple[str, str], dict] = {}
        attempted = succeeded = 0
        for target, injected, enabled, root in (
            ("company", company_gateway, targets.company, company_root),
            ("shop", shop_gateway, targets.shop, shop_root),
        ):
            if injected is None and not enabled:
                continue
            attempted += 1
            try:
                gateway = injected or (_company_gateway(config) if target == "company" else _shop_gateway(config))
                configured_root = root or (
                    (
                        config.company_vehicle_root
                        if target == "company"
                        else config.shop_build_photos_root
                    )
                    if config is not None else
                    ("Vehicle Project Database" if target == "company" else "Shop Project Database")
                )
                state, groups, vehicles = _provision_project_target(
                    project,
                    gateway=gateway,
                    target=target,
                    root=configured_root,
                    agency_name=current_agency.name if current_agency is not None else "",
                )
                project_state.update(state)
                for key, values in groups.items():
                    group_state.setdefault(key, {}).update(values)
                for key, values in vehicles.items():
                    vehicle_state.setdefault(key, {}).update(values)
                succeeded += 1
            except Exception:
                logger.exception("%s project folder provisioning failed for %s", target, project_id)
                project_state.update({
                    f"{target}_folder_status": "error",
                    f"{target}_folder_error": (
                        f"{target.title()} folder provisioning will retry during cloud sync."
                    ),
                })

        if project_state or vehicle_state:
            try:
                latest = load_project(project_id, paths)
            except FileNotFoundError:
                return {"ok": False, "error": "Project was removed during folder provisioning"}
            for field, value in project_state.items():
                setattr(latest, field, value)
            for unit in latest.build_units:
                for field, value in group_state.get(unit.unit_id, {}).items():
                    setattr(unit, field, value)
                for individual in unit.individuals:
                    for field, value in vehicle_state.get(
                        (unit.unit_id, individual.individual_id), {},
                    ).items():
                        setattr(individual, field, value)
            save_project_operational_state(latest, paths)

        return {
            "ok": attempted == succeeded,
            "enabled": bool(attempted),
            "attempted": attempted,
            "succeeded": succeeded,
            "failed": attempted - succeeded,
        }


def schedule_agency_folder_provisioning(agency_id: str, paths: AppPaths) -> bool:
    targets = folder_provisioning_targets()
    if not (targets.company or targets.shop):
        return False
    threading.Thread(
        target=provision_agency_folders,
        args=(agency_id, paths),
        name="agency-folder-provision",
        daemon=True,
    ).start()
    return True


def schedule_project_folder_provisioning(project_id: str, paths: AppPaths) -> bool:
    targets = folder_provisioning_targets()
    if not (targets.company or targets.shop):
        return False
    threading.Thread(
        target=provision_project_folders,
        args=(project_id, paths),
        name="project-folder-provision",
        daemon=True,
    ).start()
    return True


def schedule_agency_folder_provisioning_batch(agency_ids: list[str], paths: AppPaths) -> bool:
    targets = folder_provisioning_targets()
    ids = list(dict.fromkeys(value for value in agency_ids if value))
    if not ids or not (targets.company or targets.shop):
        return False

    def run() -> None:
        for agency_id in ids:
            provision_agency_folders(agency_id, paths)

    threading.Thread(target=run, name="agency-folder-provision-batch", daemon=True).start()
    return True


def retry_folder_provisioning(paths: AppPaths) -> dict:
    """Idempotently retry pending/error lifecycle provisioning during sync."""
    targets = folder_provisioning_targets()
    if not (targets.company or targets.shop):
        return {"enabled": False, "agencies": 0, "projects": 0, "failed": 0}
    agencies = projects = failed = 0
    saved_projects = list_projects(paths)
    project_agency_ids = {
        project.customer.agency_id
        for project in saved_projects
        if project.customer.agency_id
    }
    for agency in load_agencies(paths):
        # Agency Manager includes every imported QBO Customer. Only agencies
        # with an actual Vehicle Builder project belong in the vehicle trees.
        if agency.agency_id not in project_agency_ids:
            continue
        statuses = []
        if targets.company:
            statuses.append(agency.company_folder_status)
        if targets.shop:
            statuses.append(agency.shop_folder_status)
        if statuses and all(status == "provisioned" for status in statuses):
            continue
        agencies += 1
        if not provision_agency_folders(agency.agency_id, paths).get("ok"):
            failed += 1
    for project in saved_projects:
        statuses = []
        if targets.company:
            statuses.append(project.company_folder_status)
        if targets.shop:
            statuses.append(project.shop_folder_status)
        vehicle_pending = any(
            (
                targets.company and individual.company_folder_status in {
                    "not_provisioned", "pending", "error",
                }
            ) or (
                targets.shop and individual.shop_folder_status in {
                    "not_provisioned", "pending", "error",
                }
            )
            for unit in project.build_units for individual in unit.individuals
        )
        if statuses and all(status == "provisioned" for status in statuses) and not vehicle_pending:
            continue
        projects += 1
        if not provision_project_folders(project.project_id, paths).get("ok"):
            failed += 1
    return {"enabled": True, "agencies": agencies, "projects": projects, "failed": failed}
