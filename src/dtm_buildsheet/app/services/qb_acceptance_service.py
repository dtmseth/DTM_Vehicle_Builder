"""Read linked QBO Estimates and share acceptance evidence with Operations.

No Estimate writes, no Builder build-content imports, and no observed-time
fallback for AcceptedDate. Manual acceptance is never overwritten by polling.
"""
from datetime import datetime, timezone
import logging
import os
import threading
import uuid

from ...domain.operations_models import ProjectState
from ...domain.estimate_status import estimate_send_evidence, merge_send_evidence
from ...domain.operations_policy import Capability, has_capability
from ..adapters import wiring
from .operations_access_service import describe_access_session, actor_from_access_session
from .operations_service import OperationsService
from . import quickbooks_service, qb_sync_service

logger = logging.getLogger(__name__)
_THREAD = None
_LOCK = threading.Lock()


def builder_estimate_links(paths):
    """Return current per-vehicle Builder Estimate candidates for Operations."""
    from ...inputs import project_entry

    links = {}
    for project in project_entry.list_projects(paths):
        for build in project.build_units:
            for unit in build.individuals:
                candidates = []
                seen = set()

                def add(estimate_id):
                    estimate_id = str(estimate_id or '').strip()
                    if estimate_id and estimate_id not in seen:
                        seen.add(estimate_id)
                        candidates.append({
                            'estimate_id': estimate_id,
                            'project_id': str(unit.qb_project_id or '').strip(),
                            'project_name': str(unit.qb_project_name or '').strip(),
                        })

                add(unit.qb_estimate_id)
                for reference in unit.quote_references:
                    if reference.state == 'current' and reference.match_status == 'linked':
                        add(reference.qb_estimate_id)
                if candidates:
                    links[unit.individual_id] = candidates
    return links


def refresh_linked_acceptance(reader, writer, client, actor, *, now=None,
                              still_authorized=None, builder_links=None):
    if not actor.user_id or not has_capability(actor.roles, Capability.OPERATIONS_QBO_OBSERVE):
        return {'checked': 0, 'updated': 0, 'skipped': 'role'}
    clock = now or datetime.now(timezone.utc)
    checked = updated = failed = 0
    estimates = {}
    for record in reader.list_vehicles():
        candidates = list((builder_links or {}).get(record.vehicle_id) or [])
        if not candidates and record.qbo_estimate_id:
            candidates = [{
                'estimate_id': record.qbo_estimate_id,
                'project_id': record.qbo_project_id,
                'project_name': record.qbo_project_name,
            }]
        if record.project_state != ProjectState.ACTIVE or not candidates:
            continue
        if still_authorized is not None and not still_authorized():
            break
        try:
            available = []
            for candidate in candidates:
                estimate_id = candidate['estimate_id']
                if estimate_id not in estimates:
                    estimates[estimate_id] = client.read_estimate(estimate_id)
                estimate = estimates[estimate_id]
                if estimate:
                    available.append((candidate, estimate))
            checked += 1
            if not available:
                failed += 1
                continue
            # Operations has one Estimate observation slot. When a build has
            # multiple current quotes, an accepted/closed candidate is the
            # strongest evidence that the build itself was accepted.
            candidate, estimate = next((item for item in available if
                str(item[1].get('TxnStatus') or '').strip().casefold() in {'accepted', 'closed'}),
                available[0])
            estimate_id = candidate['estimate_id']
            status = str(estimate.get('TxnStatus') or '').strip()
            accepted = str(estimate.get('AcceptedDate') or '').strip()
            # Reject malformed dates; missing dates remain missing.
            if accepted:
                from ...domain.calendar_planning import valid_day
                valid_day(accepted, 'QuickBooks Accepted Date', optional=False)
            modified = str((estimate.get('MetaData') or {}).get('LastUpdatedTime') or '')
            number = str(estimate.get('DocNumber') or record.qbo_estimate_number).strip()
            sending = estimate_send_evidence(estimate)
            sent_status, sent_at = merge_send_evidence(record, estimate_id,
                sending['qbo_estimate_sent_status'], sending['qbo_estimate_sent_at'])
            changes = (sent_status != record.qbo_estimate_sent_status or sent_at != record.qbo_estimate_sent_at
                       or status != record.qbo_estimate_status or accepted != record.qbo_estimate_accepted_at
                       or modified != record.qbo_estimate_last_modified_at
                       or estimate_id != record.qbo_estimate_id or number != record.qbo_estimate_number
                       or candidate['project_id'] != record.qbo_project_id
                       or candidate['project_name'] != record.qbo_project_name)
            try:
                last = datetime.fromisoformat(record.qbo_checked_at.replace('Z', '+00:00'))
                stale = (clock - last).total_seconds() >= 6 * 3600
            except (ValueError, TypeError):
                stale = True
            needs_acceptance = (status.casefold() in {'accepted', 'closed'} and
                (str(record.acceptance_status) == 'not_accepted' or
                 (record.acceptance_source == 'qbo' and record.accepted_at[:10] != accepted)))
            if not changes and not stale and not needs_acceptance:
                continue
            if still_authorized is not None and not still_authorized():
                break
            OperationsService(writer).observe_qbo_estimate(
                vehicle_id=record.vehicle_id, actor=actor, request_id='qbo-watch-'+str(uuid.uuid4()),
                source_client='builder_desktop', expected_revision=record.revision,
                qbo_project_id=candidate['project_id'], qbo_project_name=candidate['project_name'],
                qbo_estimate_id=estimate_id, qbo_estimate_number=number,
                qbo_estimate_status=status, qbo_estimate_accepted_at=accepted,
                qbo_estimate_last_modified_at=modified, **sending,
                qbo_diff_status=(
                    'unchanged' if estimate_id != record.qbo_estimate_id
                    else 'modified' if modified != record.qbo_estimate_last_modified_at
                    else record.qbo_diff_status
                ))
            updated += 1
        except Exception:
            # Stale revisions are retried by fresh reads next pass, never by
            # dropping the revision guard. Provider details stay out of logs.
            failed += 1
    return {'checked': checked, 'updated': updated, 'failed': failed}


def run_connected_refresh(paths):
    if not wiring._cloud_flag_enabled() or not quickbooks_service.get_status(paths).get('connected'):
        return {'updated': 0, 'skipped': 'not_connected'}
    bundle = wiring.get_active_bundle()
    actor = actor_from_access_session(describe_access_session(bundle=bundle, cloud_enabled=True))
    if actor is None or bundle.operations is None or bundle.operations_writer is None:
        return {'updated': 0, 'skipped': 'operations_unavailable'}
    if not has_capability(actor.roles, Capability.OPERATIONS_QBO_OBSERVE):
        return {'updated': 0, 'skipped': 'role'}
    client, error = qb_sync_service._build_client(paths)
    if error:
        return {'updated': 0, 'skipped': 'not_connected'}
    def authorized():
        current = actor_from_access_session(describe_access_session(bundle=bundle, cloud_enabled=True))
        return current is not None and current.user_id == actor.user_id and has_capability(current.roles, Capability.OPERATIONS_QBO_OBSERVE)
    return refresh_linked_acceptance(
        bundle.operations,
        bundle.operations_writer.for_background(),
        client,
        actor,
        still_authorized=authorized,
        builder_links=builder_estimate_links(paths),
    )


def start_background_refresh(paths, *, startup_ready=None, on_data_change=None, interval_seconds=300):
    global _THREAD
    if os.environ.get('PYTEST_CURRENT_TEST') or not wiring._cloud_flag_enabled():
        return
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        def run():
            if startup_ready is not None:
                startup_ready.wait()
            while True:
                try:
                    result = run_connected_refresh(paths)
                    if result.get('updated') and on_data_change is not None:
                        on_data_change()
                except Exception:
                    logger.warning('Linked Estimate acceptance refresh failed')
                threading.Event().wait(max(60, interval_seconds))
        _THREAD = threading.Thread(target=run, name='qbo-acceptance-watch', daemon=True)
        _THREAD.start()
