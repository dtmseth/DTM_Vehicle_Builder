"""Capability-gated routes for the Operations workspace and creation pilot."""
from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ...domain.operations_models import (
    FinalFinishStatus,
    OperationsWorkstream,
    schedule_bucket,
)
from ...domain.operations_policy import Capability
from ...inputs.project_entry import list_projects, load_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.interfaces import (
    OperationsAlreadyExistsError,
    OperationsConflictError,
    OperationsRepositoryError,
)
from ..services.operations_access_service import (
    actor_from_access_session,
    describe_access_session,
)
from ..services.operations_read_service import OperationsReadService
from ..services.operations_projection_service import (
    OperationsProjectSyncService,
    OperationsProjectionPilotService,
    OperationsProjectionPreviewService,
)
from ..services.project_service import handle_set_project_lifecycle
from ..services.operations_service import (
    OperationsAuthorizationError,
    OperationsNotFoundError,
    OperationsService,
    OperationsServiceError,
    OperationsValidationError,
)
from .http import send_json

logger = logging.getLogger(__name__)


def _attach_calendar_team_history(payload: dict, paths: AppPaths, bundle) -> None:
    """Expose durable Calendar team assignments alongside Operations history."""
    try:
        from ..adapters.calendar_store import CalendarStore
        document, _ = CalendarStore(
            paths, cloud_storage=bundle.storage if wiring._cloud_flag_enabled() else None  # noqa: SLF001
        ).read()
        teams = {team['id']: team['name'] for team in document.get('settings', {}).get('teams', [])}
        jobs = document.get('jobs', {})
    except Exception:  # Calendar history should never hide Operations records.
        logger.warning("Calendar team history was unavailable", exc_info=True)
        return
    for vehicle in payload.get('vehicles', []):
        last = jobs.get(vehicle['vehicle_id'], {}).get('last_plan', {})
        team_ids = last.get('team_ids') or ([last['team_id']] if last.get('team_id') else [])
        vehicle['build_team_ids'] = team_ids
        vehicle['build_team_names'] = [teams.get(team_id, team_id) for team_id in team_ids]


_STATUS_RESPONSE_ATTR = {
    OperationsWorkstream.ACCEPTANCE: "acceptance_status",
    OperationsWorkstream.AVAILABILITY: "vehicle_availability_status",
    OperationsWorkstream.PARTS: "parts_status",
    OperationsWorkstream.SHOP: "shop_status",
    OperationsWorkstream.TRAY: "tray_status",
    OperationsWorkstream.PROGRAMMING_QC: "programming_qc_status",
    OperationsWorkstream.FINAL_FINISH: "final_finish_status",
}


def _required_revision(body: dict) -> int:
    raw = body.get("expected_revision")
    if isinstance(raw, bool) or raw in (None, ""):
        raise OperationsValidationError("expected_revision is required")
    try:
        revision = int(raw)
    except (TypeError, ValueError) as exc:
        raise OperationsValidationError("expected_revision must be a non-negative integer") from exc
    if revision < 0:
        raise OperationsValidationError("expected_revision must be a non-negative integer")
    return revision


def _plain_status(record, workstream: OperationsWorkstream) -> str:
    value = getattr(record, _STATUS_RESPONSE_ATTR[workstream])
    return value.value if hasattr(value, "value") else str(value or "")


def _change_status(writer, actor, body: dict, paths=None):
    try:
        workstream = OperationsWorkstream(str(body.get("workstream") or ""))
    except ValueError as exc:
        raise OperationsValidationError("Invalid status workstream") from exc
    if workstream not in _STATUS_RESPONSE_ATTR:
        raise OperationsValidationError(f"{workstream.value} is not an editable status")

    if paths is not None and workstream.value in {'parts', 'tray', 'programming_qc'}:
        from ...domain.project_types import with_project_work, applicable_workstreams
        record = writer.get_vehicle(str(body.get('vehicle_id') or ''))
        if record is not None:
            try:
                project = load_project(record.project_id, paths)
            except FileNotFoundError:
                project = None
            if workstream.value not in applicable_workstreams(with_project_work(record, project)):
                raise OperationsValidationError('This workstream is not applicable to this service project')
    service = OperationsService(writer)
    common = {
        "vehicle_id": body.get("vehicle_id", ""),
        "new_status": body.get("new_status", ""),
        "actor": actor,
        "request_id": body.get("request_id", ""),
        "source_client": "builder_desktop",
        "expected_revision": _required_revision(body),
        "correction_reason": body.get("correction_reason", ""),
    }
    if workstream == OperationsWorkstream.ACCEPTANCE:
        result = service.change_acceptance(
            **common,
            acceptance_source="manual",
        )
    elif workstream == OperationsWorkstream.AVAILABILITY:
        result = service.change_vehicle_availability(
            **common,
            effective_date=body.get("effective_date", ""),
        )
    else:
        result = service.change_status(**common, workstream=workstream)
    return workstream, result


def _change_schedule(writer, actor, body: dict):
    fields = {
        field: body[field]
        for field in (
            "scheduled_week_of",
            "planned_start_date",
            "target_finish_date",
            "must_deliver_override_date",
        )
        if field in body
    }
    return OperationsService(writer).change_schedule(
        vehicle_id=body.get("vehicle_id", ""),
        **fields,
        actor=actor,
        request_id=body.get("request_id", ""),
        source_client="builder_desktop",
        expected_revision=_required_revision(body),
    )


def _auto_complete_delivered_project(paths, writer, actor, record) -> dict:
    """Complete an active Builder project once every real vehicle's final finish is delivered."""

    try:
        project = load_project(record.project_id, paths)
    except (FileNotFoundError, ValueError):
        return {}
    if project.project_status != "active":
        return {}
    vehicle_ids = {
        individual.individual_id
        for build_unit in project.build_units
        for individual in build_unit.individuals
        if individual.individual_id
    }
    if not vehicle_ids:
        return {}
    records = {
        item.vehicle_id: item
        for item in writer.list_vehicles()
        if item.project_id == project.project_id
    }
    records[record.vehicle_id] = record
    if set(records).intersection(vehicle_ids) != vehicle_ids:
        return {}
    if any(
        records[vehicle_id].final_finish_status
        != FinalFinishStatus.DELIVERED
        for vehicle_id in vehicle_ids
    ):
        return {}

    completion = handle_set_project_lifecycle(
        project.project_id,
        {
            "status": "completed",
            "actor": actor.display_name,
            "reason": "All project vehicles were marked delivered in Operations",
        },
        paths,
    )
    if not completion.get("ok"):
        return {"project_auto_completion_error": completion.get("error")}
    completed_project = load_project(project.project_id, paths)
    OperationsProjectSyncService(writer).sync_lifecycle(
        completed_project,
        actor,
        reason="All project vehicles were marked delivered in Operations",
    )
    return {"project_auto_completed": True}


def route_operations(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    body: dict,
    paths: AppPaths,
) -> bool:
    get_paths = {
        "/api/operations/session",
        "/api/operations/vehicles",
        "/api/operations/history",
        "/api/operations/projection-preview",
    }
    pilot_path = "/api/operations/projection-pilot"
    status_path = "/api/operations/status"
    schedule_path = "/api/operations/schedule"
    is_pilot = method == "POST" and path == pilot_path
    is_status_update = method == "POST" and path == status_path
    is_schedule_update = method == "POST" and path == schedule_path
    is_acceptance_date = method == "POST" and path == "/api/operations/acceptance-date"
    is_history = method == "GET" and path == "/api/operations/history"
    if not (
        (method == "GET" and path in get_paths)
        or is_pilot
        or is_status_update
        or is_schedule_update
        or is_acceptance_date
    ):
        return False

    try:
        bundle = wiring.get_active_bundle()
        session = describe_access_session(
            bundle=bundle,
            cloud_enabled=wiring._cloud_flag_enabled(),  # noqa: SLF001
        )
    except Exception:
        logger.exception("Operations session resolution failed")
        send_json(handler, {
            "ok": False,
            "error": "Operations access could not be checked",
        }, status=503)
        return True

    if path == "/api/operations/session":
        send_json(handler, session)
        return True

    if not session.get("authenticated"):
        send_json(handler, {
            "ok": False,
            "error": "Sign in with Microsoft 365 to view Operations",
        }, status=401)
        return True
    if Capability.OPERATIONS_VIEW.value not in session.get("capabilities", ()):
        send_json(handler, {
            "ok": False,
            "error": "Your account has not been assigned Operations access",
        }, status=403)
        return True
    if bundle.operations is None:
        send_json(handler, {
            "ok": False,
            "error": "The Operations data connection is not configured",
        }, status=503)
        return True

    actor = actor_from_access_session(session)
    if actor is None:
        send_json(handler, {
            "ok": False,
            "error": "A verified Microsoft 365 identity is required",
        }, status=401)
        return True
    try:
        if is_pilot or is_status_update or is_schedule_update or is_acceptance_date:
            if bundle.operations_writer is None:
                send_json(handler, {
                    "ok": False,
                    "error": "The Operations write connection is not configured",
                }, status=503)
                return True
            if is_acceptance_date:
                result = OperationsService(bundle.operations_writer).change_acceptance_date(
                    vehicle_id=body.get('vehicle_id', ''), accepted_date=body.get('accepted_date', ''),
                    acceptance_source=body.get('acceptance_source', 'manual'), actor=actor,
                    request_id=body.get('request_id', ''), source_client='builder_desktop',
                    expected_revision=_required_revision(body))
                send_json(handler, {'ok': True, 'accepted_at': result.record.accepted_at,
                                    'acceptance_source': result.record.acceptance_source,
                                    'revision': result.record.revision})
            elif is_pilot:
                result = OperationsProjectionPilotService(
                    bundle.operations_writer
                ).create_one(
                    list_projects(paths),
                    actor,
                    vehicle_id=body.get("vehicle_id", ""),
                    confirmation=body.get("confirmation", ""),
                    request_id=body.get("request_id", ""),
                )
                send_json(handler, {
                    "ok": True,
                    "created": not result.duplicate,
                    "duplicate": result.duplicate,
                    "vehicle_id": result.record.vehicle_id,
                    "vehicle_label": result.record.vehicle_label,
                    "project_state": result.record.project_state.value,
                    "revision": result.record.revision,
                })
            elif is_status_update:
                workstream, result = _change_status(
                    bundle.operations_writer,
                    actor,
                    body,
                    paths,
                )
                payload = {
                    "ok": True,
                    "vehicle_id": result.record.vehicle_id,
                    "workstream": workstream.value,
                    "status": _plain_status(result.record, workstream),
                    "revision": result.record.revision,
                    "changed": not result.unchanged and not result.duplicate,
                    "unchanged": result.unchanged,
                    "duplicate": result.duplicate,
                }
                if (
                    workstream == OperationsWorkstream.FINAL_FINISH
                    and result.record.final_finish_status
                    == FinalFinishStatus.DELIVERED
                ):
                    try:
                        payload.update(_auto_complete_delivered_project(
                            paths,
                            bundle.operations_writer,
                            actor,
                            result.record,
                        ))
                    except (OperationsRepositoryError, OperationsServiceError):
                        logger.exception("Automatic project completion failed")
                        payload["project_auto_completion_error"] = (
                            "The delivery status was saved, but the project could not "
                            "be moved to Completed"
                        )
                send_json(handler, payload)
            else:
                result = _change_schedule(bundle.operations_writer, actor, body)
                send_json(handler, {
                    "ok": True,
                    "vehicle_id": result.record.vehicle_id,
                    "scheduled_week_of": result.record.scheduled_week_of,
                    "planned_start_date": result.record.planned_start_date,
                    "target_finish_date": result.record.target_finish_date,
                    "must_deliver_override_date": result.record.must_deliver_override_date,
                    "must_deliver_by_date": result.record.must_deliver_by_date,
                    "schedule_bucket": schedule_bucket(result.record).value,
                    "revision": result.record.revision,
                    "changed": not result.unchanged and not result.duplicate,
                    "unchanged": result.unchanged,
                    "duplicate": result.duplicate,
                })
            return True
        if is_history:
            query = parse_qs(urlparse(handler.path).query)
            payload = OperationsReadService(bundle.operations).list_vehicle_history(
                (query.get("vehicle_id") or [""])[0],
                actor,
            )
        elif path == "/api/operations/projection-preview":
            if Capability.PROJECTS_EDIT.value not in session.get("capabilities", ()):
                raise OperationsAuthorizationError(
                    f"Missing capability: {Capability.PROJECTS_EDIT.value}"
                )
            payload = OperationsProjectionPreviewService(bundle.operations).preview(
                list_projects(paths),
                actor,
            )
            payload["writes_enabled"] = bundle.operations_writer is not None
            payload["write_mode"] = (
                "single_vehicle_create_pilot"
                if bundle.operations_writer is not None
                else "disabled"
            )
        else:
            # Builder lifecycle is authoritative for visibility. A previously
            # projected Operations row may still say active if an older client
            # marked its project inactive without updating that projection.
            # Filter it at the API boundary so every Operations client agrees.
            inactive_project_ids = frozenset(
                project.project_id
                for project in list_projects(paths)
                if project.project_status == "inactive"
            )
            payload = OperationsReadService(bundle.operations).list_vehicle_summaries(
                actor,
                hidden_project_ids=inactive_project_ids,
                projects=list_projects(paths),
            )
            _attach_calendar_team_history(payload, paths, bundle)
        send_json(handler, payload)
    except OperationsAuthorizationError:
        send_json(handler, {
            "ok": False,
            "error": (
                "Your role cannot add Builder vehicles"
                if is_pilot
                else "Your role cannot update the Operations schedule"
                if is_schedule_update
                else "Your role cannot update that Operations status"
                if is_status_update
                else "Your role cannot preview Builder vehicle projection"
                if path == "/api/operations/projection-preview"
                else "Your account has not been assigned Operations access"
            ),
        }, status=403)
    except OperationsNotFoundError as exc:
        send_json(handler, {"ok": False, "error": str(exc)}, status=404)
    except OperationsConflictError:
        send_json(handler, {
            "ok": False,
            "error": (
                "This vehicle changed on another device; refresh before continuing"
                if is_status_update or is_schedule_update or is_acceptance_date
                else "That vehicle already has an Operations record; refresh before continuing"
            ),
        }, status=409)
    except OperationsAlreadyExistsError:
        send_json(handler, {
            "ok": False,
            "error": "That vehicle already has an Operations record; refresh before continuing",
        }, status=409)
    except OperationsRepositoryError:
        logger.exception("Operations list query failed")
        send_json(handler, {
            "ok": False,
            "error": (
                "The Operations update could not be saved"
                if is_status_update or is_schedule_update or is_acceptance_date
                else "The Operations record could not be created"
                if is_pilot
                else "Operations history is temporarily unavailable"
                if is_history
                else "Operations data is temporarily unavailable"
            ),
        }, status=503)
    except OperationsValidationError as exc:
        logger.warning("Operations request rejected: %s", exc)
        send_json(handler, {
            "ok": False,
            "error": (
                str(exc)
                if is_pilot or is_status_update or is_schedule_update or is_history or is_acceptance_date
                else "Builder vehicles could not be safely mapped to Operations"
            ),
        }, status=(
            400
            if is_pilot or is_status_update or is_schedule_update or is_history or is_acceptance_date
            else 409
        ))
    return True
