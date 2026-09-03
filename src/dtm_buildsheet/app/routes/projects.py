from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services.export_service import handle_export_all_pdf
from ..services.project_service import (
    handle_create_draft,
    handle_create_individual_draft,
    handle_delete_project,
    handle_delete_project_with_options,
    handle_get_project,
    handle_list_projects,
    handle_save_project,
    handle_set_project_completion,
)
from ..services.finalization_service import (
    handle_finalization_check,
    handle_finalize_build,
    handle_reopen_build,
)
from ..services.reference_photo_service import (
    handle_delete_reference,
    handle_effective_references,
    handle_import_gallery_references,
    handle_list_references,
    handle_remove_gallery_references,
    handle_save_reference,
)
from ..services.reference_library_service import handle_discover_references
from ..services.photo_gallery_service import handle_photo_gallery
from ..services.shop_publication_service import handle_republish_vehicle_package
from ..services.vehicle_naming_migration_service import build_vehicle_naming_migration_report
from .http import send_json


def route_projects(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    """Return True if the request was handled."""

    if path.startswith("/api/project/") and "/finalization/" in path:
        inner, action = path[len("/api/project/"):].rsplit("/finalization/", 1)
        individual_id = ""
        if "/individual/" in inner:
            unit_part, individual_id = inner.rsplit("/individual/", 1)
        else:
            unit_part = inner
        parts = unit_part.split("/unit/", 1)
        if len(parts) == 2:
            project_id, unit_id = parts
            valid = all(value and "/" not in value for value in (project_id, unit_id))
            valid = valid and (not individual_id or "/" not in individual_id)
            if valid and method == "GET" and action == "check":
                send_json(handler, handle_finalization_check(project_id, unit_id, individual_id, paths))
                return True
            if valid and method == "POST" and action == "finalize":
                send_json(handler, handle_finalize_build(project_id, unit_id, individual_id, body, paths))
                return True
            if valid and method == "POST" and action == "reopen":
                send_json(handler, handle_reopen_build(project_id, unit_id, individual_id, body, paths))
                return True

    if method == "POST" and path.startswith("/api/project/") and path.endswith(
        "/shop-publication/republish"
    ):
        inner = path[len("/api/project/"):-len("/shop-publication/republish")]
        if "/individual/" in inner:
            unit_part, individual_id = inner.rsplit("/individual/", 1)
            parts = unit_part.split("/unit/", 1)
            if len(parts) == 2:
                project_id, unit_id = parts
                if all(
                    value and "/" not in value
                    for value in (project_id, unit_id, individual_id)
                ):
                    send_json(handler, handle_republish_vehicle_package(
                        project_id, unit_id, individual_id, paths,
                    ))
                    return True

    if path.startswith("/api/project/") and "/references" in path:
        tail = path[len("/api/project/"):]
        project_id, separator, action = tail.partition("/references")
        if project_id and "/" not in project_id and separator:
            if method == "GET" and action == "":
                send_json(handler, handle_list_references(project_id, paths))
                return True
            if method in {"GET", "POST"} and action == "/discover":
                send_json(handler, handle_discover_references(
                    project_id,
                    paths,
                    agency=str(body.get("agency") or "") if method == "POST" else "",
                ))
                return True
            if method == "POST" and action == "/import-gallery":
                send_json(handler, handle_import_gallery_references(project_id, body, paths))
                return True
            if method == "POST" and action == "/remove-gallery":
                send_json(handler, handle_remove_gallery_references(project_id, body, paths))
                return True
            if method == "POST" and action == "/save":
                send_json(handler, handle_save_reference(project_id, body, paths))
                return True
            if method == "POST" and action == "/effective":
                send_json(handler, handle_effective_references(project_id, body, paths))
                return True
            if method == "POST" and action.startswith("/") and action.endswith("/delete"):
                reference_id = action[1:-len("/delete")]
                if reference_id and "/" not in reference_id:
                    send_json(handler, handle_delete_reference(project_id, reference_id, paths))
                    return True
    if method == "POST" and path.startswith("/api/project/") and path.endswith("/photo-gallery"):
        project_id = path[len("/api/project/"):-len("/photo-gallery")]
        if project_id and "/" not in project_id:
            send_json(handler, handle_photo_gallery(project_id, body, paths))
            return True
    if method == "GET" and path == "/api/projects/naming-migration-report":
        send_json(handler, build_vehicle_naming_migration_report(paths))
        return True

    # GET /api/projects
    if method == "GET" and path == "/api/projects":
        send_json(handler, handle_list_projects(paths))
        return True

    # GET /api/project/{project_id}
    if method == "GET" and path.startswith("/api/project/"):
        tail = path[len("/api/project/"):]
        if tail and "/" not in tail:
            send_json(handler, handle_get_project(tail, paths))
            return True

    # POST /api/project/save
    if method == "POST" and path == "/api/project/save":
        send_json(handler, handle_save_project(body, paths))
        return True

    # POST /api/project/{project_id}/completion
    if method == "POST" and path.startswith("/api/project/") and path.endswith("/completion"):
        project_id = path[len("/api/project/"):-len("/completion")]
        if project_id and "/" not in project_id:
            send_json(handler, handle_set_project_completion(project_id, body, paths))
            return True

    # DELETE /api/project/{project_id}
    if method == "DELETE" and path.startswith("/api/project/"):
        project_id = path[len("/api/project/"):]
        if project_id and "/" not in project_id:
            send_json(handler, handle_delete_project(project_id, paths))
            return True

    # POST /api/project/{project_id}/delete
    if method == "POST" and path.startswith("/api/project/") and path.endswith("/delete"):
        project_id = path[len("/api/project/"):-len("/delete")]
        if project_id and "/" not in project_id:
            send_json(handler, handle_delete_project_with_options(project_id, body, paths))
            return True

    # POST /api/project/{project_id}/unit/{unit_id}/create-draft
    if method == "POST" and path.startswith("/api/project/") and path.endswith("/create-draft"):
        inner = path[len("/api/project/"):-len("/create-draft")]
        # Individual: .../unit/{unit_id}/individual/{individual_id}
        if "/individual/" in inner:
            unit_part, individual_id = inner.rsplit("/individual/", 1)
            unit_parts = unit_part.split("/unit/", 1)
            if len(unit_parts) == 2:
                project_id, unit_id = unit_parts
                if all(s and "/" not in s for s in (project_id, unit_id, individual_id)):
                    send_json(handler, handle_create_individual_draft(
                        project_id, unit_id, individual_id, paths))
                    return True
        else:
            parts = inner.split("/unit/", 1)
            if len(parts) == 2:
                project_id, unit_id = parts
                if project_id and unit_id and "/" not in project_id and "/" not in unit_id:
                    send_json(handler, handle_create_draft(project_id, unit_id, paths))
                    return True

    # POST /api/project/{project_id}/export-all-pdf
    if method == "POST" and path.startswith("/api/project/") and path.endswith("/export-all-pdf"):
        project_id = path[len("/api/project/"):-len("/export-all-pdf")]
        if project_id and "/" not in project_id:
            send_json(handler, handle_export_all_pdf(project_id, paths))
            return True

    return False
