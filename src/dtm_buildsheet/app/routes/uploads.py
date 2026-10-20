from __future__ import annotations

import re
from http.server import BaseHTTPRequestHandler

from ...paths import AppPaths
from ..services.upload_service import (
    acknowledge_completed_uploads,
    cancel_upload,
    create_upload_job,
    list_upload_jobs,
    retry_upload,
    stage_upload_content,
    upload_job_destination,
)
from .http import send_json


_CONTENT_ROUTE = re.compile(
    r"^/api/uploads/(project|completed)/([a-f0-9]{32})/content$"
)
_ACTION_ROUTE = re.compile(
    r"^/api/uploads/(project|completed)/([a-f0-9]{32})/(retry|cancel)$"
)


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    expected = str(getattr(handler, "upload_token", "") or "")
    supplied = str(handler.headers.get("X-DTM-Upload-Token") or "")
    if expected and supplied == expected:
        return True
    send_json(handler, {"ok": False, "error": "Upload request authorization failed"}, 403)
    return False


def route_uploads(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    if method == "GET" and path == "/api/uploads/status":
        send_json(handler, list_upload_jobs(paths))
        return True
    if not path.startswith("/api/uploads/"):
        return False
    if not _authorized(handler):
        return True
    if method == "POST" and path == "/api/uploads/acknowledge":
        send_json(handler, acknowledge_completed_uploads(paths))
        return True
    if method == "POST" and path in {
        "/api/uploads/project/create",
        "/api/uploads/completed/create",
    }:
        destination = "project" if "/project/" in path else "completed"
        try:
            job = create_upload_job(paths, body, destination_kind=destination)
        except (FileNotFoundError, ValueError) as exc:
            send_json(handler, {"ok": False, "error": str(exc)}, 400)
        else:
            send_json(handler, {"ok": True, "job": job})
        return True
    match = _ACTION_ROUTE.fullmatch(path)
    if method == "POST" and match is not None:
        destination, job_id, action = match.groups()
        try:
            if upload_job_destination(paths, job_id) != destination:
                raise ValueError("Upload destination does not match this action")
            job = retry_upload(paths, job_id) if action == "retry" else cancel_upload(paths, job_id)
        except (FileNotFoundError, ValueError) as exc:
            send_json(handler, {"ok": False, "error": str(exc)}, 400)
        else:
            send_json(handler, {"ok": True, "job": job})
        return True
    return False


def route_upload_content(
    handler: BaseHTTPRequestHandler,
    path: str,
    paths: AppPaths,
) -> bool:
    match = _CONTENT_ROUTE.fullmatch(path)
    if match is None:
        return False
    if not _authorized(handler):
        return True
    destination, job_id = match.groups()
    try:
        if upload_job_destination(paths, job_id) != destination:
            raise ValueError("Upload destination does not match this job")
        content_length = int(handler.headers.get("Content-Length") or 0)
        if content_length <= 0:
            raise ValueError("Upload content length is required")
        job = stage_upload_content(paths, job_id, handler.rfile, content_length)
    except (FileNotFoundError, ValueError, OSError) as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, 400)
    else:
        send_json(handler, {"ok": True, "job": job})
    return True
