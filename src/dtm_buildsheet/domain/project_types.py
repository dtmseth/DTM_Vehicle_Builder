"""Project work categories; independent of vehicle type and lifecycle."""
from copy import deepcopy
from dataclasses import replace
import math

PROJECT_TYPES = {'build': 'Build', 'service': 'Service', 'offsite': 'Off-Site Service'}


def project_type(value):
    value = str(value or 'build').strip().lower()
    if value not in PROJECT_TYPES:
        raise ValueError('Choose Build, Service, or Off-Site Service')
    return value


def service_details(value):
    if not isinstance(value, dict):
        raise ValueError('Service details must be an object')
    result = {}
    for key in ('location', 'contact'):
        text = value.get(key, '')
        if not isinstance(text, str) or len(text) > 500:
            raise ValueError(f'Service {key} must be text of at most 500 characters')
        result[key] = text.strip()
    for key, default in (('requires_parts', True), ('requires_strip', False), ('requires_tray', False),
                         ('requires_programming_qc', False), ('requires_finishing', False), ('render_vehicle', False)):
        result[key] = value.get(key, default)
        if not isinstance(result[key], bool):
            raise ValueError(f'{key} must be true or false')
    travel = value.get('travel_hours', 0)
    if isinstance(travel, bool):
        raise ValueError('Travel allowance must be a number')
    try:
        travel = float(travel)
    except (TypeError, ValueError):
        raise ValueError('Travel allowance must be a number') from None
    if not math.isfinite(travel) or not 0 <= travel <= 100:
        raise ValueError('Travel allowance must be between 0 and 100 labor hours')
    result['travel_hours'] = travel
    return result


def with_project_work(record, project):
    """Attach current Builder metadata without rewriting Operations statuses."""
    if project is None:
        return record
    return replace(record, project_type=project.project_type, service_details=deepcopy(project.service_details))


def applicable_workstreams(record):
    streams = {'parts', 'shop', 'tray', 'programming_qc', 'final_finish'}
    if record.project_type != 'build':
        for stream in ('parts', 'tray', 'programming_qc'):
            if not record.service_details.get('requires_' + stream, stream == 'parts'):
                streams.discard(stream)
    return streams


def physical_readiness(record):
    parts = record.parts_status in ('received', 'parts_ready') or 'parts' not in applicable_workstreams(record)
    vehicle = record.vehicle_availability_status == 'at_dtm' or (
        record.project_type == 'offsite' and record.vehicle_availability_status == 'ready_for_pickup')
    return parts, vehicle
