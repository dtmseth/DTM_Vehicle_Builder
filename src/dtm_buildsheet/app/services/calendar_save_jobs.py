"""Legacy save-job compatibility; Calendar routes use calendar_workspace instead.

One background Calendar save per workspace, with durable local progress.

The worker owns the reviewed request after the browser returns. An app restart
marks unfinished work interrupted; recovery always needs a fresh review.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import threading
import uuid

from ...domain.operations_policy import Capability
from ...storage.local import LocalStorageProvider
from ..adapters.calendar_store import CalendarConflictError

_LOCK = threading.RLock()
_THREADS = {}
_RUNNING = {'saving', 'syncing'}


def _path(service):
    name = 'cloud-save-status.json' if service.cloud else 'local-save-status.json'
    return service.paths.workspace_dir / 'calendar' / name


def _write(path, status):
    LocalStorageProvider().write_text(str(path), json.dumps(status))


def status(service, actor):
    service._require(actor, Capability.OPERATIONS_VIEW)
    path = _path(service)
    with _LOCK:
        result = json.loads(path.read_text()) if path.exists() else {'state': 'idle'}
        if result['state'] in _RUNNING and not _THREADS.get(str(path), None):
            result.update(state='interrupted', message='Save interrupted. Refresh Calendar and review the remaining changes.')
            _write(path, result)
        return {'ok': True, 'save': result}


def start(service, actor, body):
    service._require(actor, Capability.OPERATIONS_SCHEDULE_UPDATE)
    if not isinstance(body, dict) or not body.get('preview_token'):
        raise ValueError('Review the schedule before saving')
    request_id = body.get('request_id')
    if not isinstance(request_id, str) or not request_id or len(request_id) > 100:
        raise ValueError('A save request ID is required')
    path = _path(service)
    with _LOCK:
        current = status(service, actor)['save']
        if current.get('request_id') == request_id and current.get('actor_id') == actor.user_id:
            return {'ok': True, 'save': current}
        if current['state'] in _RUNNING:
            raise CalendarConflictError('A schedule save is already running. You can keep using the app.')
        progress = {'id': str(uuid.uuid4()), 'request_id': request_id, 'actor_id': actor.user_id,
                    'state': 'saving', 'completed': 0, 'total': 0,
                    'started_at': datetime.now(timezone.utc).isoformat(),
                    'message': 'Saving schedule… You can keep using the app.'}
        _write(path, progress)
        thread = threading.Thread(target=_run, args=(service, actor, deepcopy(body), path, progress),
                                  daemon=True, name='calendar-save')
        _THREADS[str(path)] = thread
        thread.start()
        return {'ok': True, 'save': deepcopy(progress)}


def _run(service, actor, body, path, progress):
    def update(**values):
        with _LOCK:
            progress.update(values)
            _write(path, progress)
    try:
        saved = service.save(actor, body)
        jobs = service.date_changes(saved['plan']['jobs'], saved['plan']['released'])
        update(state='syncing', total=len(jobs), message='Schedule saved. Updating Operations dates…')
        service.publish_dates(actor, saved, progress['id'],
                              on_progress=lambda count: update(completed=count))
        update(state='complete', message='Schedule saved. Operations dates are up to date.')
    except CalendarConflictError as exc:
        update(state='failed', message=str(exc) + ' Refresh Calendar and review the remaining changes.')
    except Exception:
        # Provider exceptions can contain customer data or credentials. Never
        # persist their raw text in a progress record or expose it to the UI.
        update(state='failed', message='Save stopped. Check your connection, then refresh Calendar and review the remaining changes.')
    finally:
        with _LOCK:
            _THREADS.pop(str(path), None)
