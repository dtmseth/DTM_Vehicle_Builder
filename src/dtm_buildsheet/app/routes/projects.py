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
)
from ..services.finalization_service import (
    handle_finalization_check,
    handle_finalize_build,
    handle_reopen_build,
)
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
