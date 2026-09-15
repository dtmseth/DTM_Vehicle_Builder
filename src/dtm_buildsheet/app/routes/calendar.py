"""Capability-gated Calendar routes; planning and persistence live in the service."""
from __future__ import annotations

import logging
import uuid
from dataclasses import replace

from ..adapters import wiring
from ..adapters.calendar_store import CalendarConflictError
from ..adapters.interfaces import OperationsConflictError
from ..services.calendar_service import CalendarService
from ..services.calendar_workspace import workspace
from ..services.operations_access_service import actor_from_access_session, describe_access_session
from ..services.operations_service import OperationsAuthorizationError
from ...domain.operations_policy import Capability, has_capability
from .http import send_json

logger = logging.getLogger(__name__)


def route_calendar(handler, method, path, body, paths):
    routes = {"/api/calendar": "view", "/api/calendar/preview": "preview",
              "/api/calendar/save": "save", "/api/calendar/settings": "save_settings",
              "/api/calendar/apply-date": "apply_dates",
              "/api/calendar/save-background": "save_background",
              "/api/calendar/save-status": "save_status", "/api/calendar/retry-sync": "retry_sync",
              "/api/calendar/sync-review": "sync_review", "/api/calendar/resolve-sync": "resolve_sync"}
    if path not in routes or (method == "GET") != (path in {"/api/calendar", "/api/calendar/save-status"}):
        return False
    try:
        bundle = wiring.get_active_bundle()
        cloud = wiring._cloud_flag_enabled()
        session = describe_access_session(bundle=bundle, cloud_enabled=cloud)
        actor = actor_from_access_session(session)
        if actor is None:
            send_json(handler, {"ok": False, "error": "Sign in to open Calendar"}, status=401)
            return True
        if cloud and bundle.operations_writer is not None:
            bundle = replace(bundle, operations_writer=bundle.operations_writer.for_background())
        def authorize(expected, capability):
            current = actor_from_access_session(describe_access_session(cloud_enabled=cloud))
            return current is not None and current.user_id == expected.user_id and has_capability(current.roles, capability)
        service = CalendarService(paths, bundle, cloud=cloud, authorize=authorize)
        service._require(actor, Capability.OPERATIONS_VIEW)
        local = workspace(service, actor)
        if path == '/api/calendar/save-status':
            payload = local.status()
        elif path == '/api/calendar/retry-sync':
            payload = local.retry()
        elif path == '/api/calendar/sync-review':
            payload = local.review_sync()
        elif path == '/api/calendar/resolve-sync':
            payload = local.resolve_sync(body)
        elif path in ('/api/calendar/save-background', '/api/calendar/save', '/api/calendar/settings'):
            payload = local.commit({**body, 'request_id': body.get('request_id') or str(uuid.uuid4())})
        elif path == '/api/calendar/apply-date':
            payload = service.apply_dates(actor, body)  # Legacy audited one-vehicle endpoint.
        else:
            payload = local.view() if method == 'GET' else local.preview(body)
        send_json(handler, payload)
    except OperationsAuthorizationError as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, status=403)
    except (CalendarConflictError, OperationsConflictError) as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, status=409)
    except ValueError as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, status=400)
    except Exception:
        logger.error("Calendar request failed", exc_info=False)
        send_json(handler, {"ok": False, "error": "Calendar could not connect. Refresh to check the saved state before trying again."}, status=503)
    return True
