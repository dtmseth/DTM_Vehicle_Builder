from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ..services.draft_service import (
    handle_add_custom_part_to_draft,
    handle_add_part_to_draft,
    handle_delete_draft,
    handle_generate_from_draft,
    handle_get_draft,
    handle_list_drafts,
    handle_list_custom_parts,
    handle_remove_part_from_draft,
    handle_replace_console_setup_parts,
    handle_save_draft,
    handle_save_override,
    handle_save_overrides_batch,
    handle_update_part_in_draft,
    handle_update_custom_part_in_draft,
)
from ...paths import AppPaths
from .http import send_json


def route_drafts(handler: BaseHTTPRequestHandler, method: str, path: str, body: dict, paths: AppPaths) -> bool:
    """Return True if the request was handled."""

    # GET /api/draft/list
    if method == "GET" and path == "/api/draft/list":
        send_json(handler, handle_list_drafts(paths))
        return True

    # GET /api/draft/custom-parts
    if method == "GET" and path == "/api/draft/custom-parts":
        send_json(handler, handle_list_custom_parts(paths))
        return True

    # POST /api/draft/save
    if method == "POST" and path == "/api/draft/save":
        send_json(handler, handle_save_draft(body, paths))
        return True

    # POST /api/draft/generate
    if method == "POST" and path == "/api/draft/generate":
        send_json(handler, handle_generate_from_draft(body, paths))
        return True

    # POST /api/draft/{id}/part/{line_id}/update
    if method == "POST" and path.startswith("/api/draft/") and "/custom-part/" in path and path.endswith("/update"):
        rest = path[len("/api/draft/"):-len("/update")]
        if "/custom-part/" in rest:
            draft_id, line_id = rest.split("/custom-part/", 1)
            if draft_id and line_id and "/" not in draft_id and "/" not in line_id:
                send_json(handler, handle_update_custom_part_in_draft(draft_id, line_id, body, paths))
                return True

    # POST /api/draft/{id}/part/{line_id}/update
    if method == "POST" and path.startswith("/api/draft/") and "/part/" in path and path.endswith("/update"):
        rest = path[len("/api/draft/"):-len("/update")]
        if "/part/" in rest:
            draft_id, line_id = rest.split("/part/", 1)
            if draft_id and line_id and "/" not in draft_id and "/" not in line_id:
                send_json(handler, handle_update_part_in_draft(draft_id, line_id, body, paths))
                return True

    # POST /api/draft/{id}/part/{line_id}/delete
    if method == "POST" and path.startswith("/api/draft/") and "/part/" in path and path.endswith("/delete"):
        rest = path[len("/api/draft/"):-len("/delete")]
        if "/part/" in rest:
            draft_id, line_id = rest.split("/part/", 1)
            if draft_id and line_id and "/" not in draft_id and "/" not in line_id:
                send_json(handler, handle_remove_part_from_draft(draft_id, line_id, paths))
                return True

    # POST /api/draft/{id}/console-setup
    if method == "POST" and path.startswith("/api/draft/") and path.endswith("/console-setup"):
        draft_id = path[len("/api/draft/"):-len("/console-setup")]
        parent_line_id = body.get("parent_line_id", "")
        if draft_id and "/" not in draft_id:
            send_json(handler, handle_replace_console_setup_parts(draft_id, parent_line_id, body, paths))
            return True

    # POST /api/draft/{id}/custom-part
    if method == "POST" and path.startswith("/api/draft/") and path.endswith("/custom-part"):
        draft_id = path[len("/api/draft/"):-len("/custom-part")]
        if draft_id and "/" not in draft_id:
            send_json(handler, handle_add_custom_part_to_draft(draft_id, body, paths))
            return True

    # POST /api/draft/{id}/part
    if method == "POST" and path.startswith("/api/draft/") and path.endswith("/part"):
        inner = path[len("/api/draft/"):-len("/part")]
        if inner and "/" not in inner:
            send_json(handler, handle_add_part_to_draft(inner, body, paths))
            return True

    # POST /api/draft/{id}/overrides/batch
    if method == "POST" and path.startswith("/api/draft/") and path.endswith("/overrides/batch"):
        inner = path[len("/api/draft/"):-len("/overrides/batch")]
        if inner and "/" not in inner:
            send_json(handler, handle_save_overrides_batch(inner, body, paths))
            return True

    # POST /api/draft/{id}/override
    if method == "POST" and path.startswith("/api/draft/") and path.endswith("/override"):
        inner = path[len("/api/draft/"):-len("/override")]
        if inner and "/" not in inner:
            send_json(handler, handle_save_override(inner, body, paths))
            return True

    # GET /api/draft/{id}
    if method == "GET" and path.startswith("/api/draft/"):
        draft_id = path[len("/api/draft/"):]
        if draft_id and "/" not in draft_id:
            send_json(handler, handle_get_draft(draft_id, paths))
            return True

    # DELETE /api/draft/{id}
    if method == "DELETE" and path.startswith("/api/draft/"):
        draft_id = path[len("/api/draft/"):]
        if draft_id and "/" not in draft_id:
            send_json(handler, handle_delete_draft(draft_id, paths))
            return True

    return False
