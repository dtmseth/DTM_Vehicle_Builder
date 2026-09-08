"""Thread-safe in-memory operations repository for tests and local development."""
from __future__ import annotations

import threading
from copy import deepcopy

from .interfaces import (
    OperationsAlreadyExistsError,
    OperationsConflictError,
    OperationsRepository,
)
from ...domain.operations_models import OperationsEvent, VehicleOperations


class InMemoryOperationsRepository(OperationsRepository):
    def __init__(self) -> None:
        self._records: dict[str, VehicleOperations] = {}
        self._events: list[OperationsEvent] = []
        self._events_by_request: dict[str, OperationsEvent] = {}
        self._lock = threading.RLock()

    def get_vehicle(self, vehicle_id: str) -> VehicleOperations | None:
        with self._lock:
            record = self._records.get(str(vehicle_id))
            return deepcopy(record) if record is not None else None

    def list_vehicles(self) -> list[VehicleOperations]:
        with self._lock:
            return [
                deepcopy(record)
                for record in sorted(
                    self._records.values(),
                    key=lambda item: (
                        str(item.agency_name).casefold(),
                        str(item.vehicle_label or item.title).casefold(),
                        item.vehicle_id,
                    ),
                )
            ]

    def create_vehicle(
        self,
        record: VehicleOperations,
        event: OperationsEvent,
    ) -> VehicleOperations:
        with self._lock:
            if record.vehicle_id in self._records:
                raise OperationsAlreadyExistsError(
                    f"Operations already exist for vehicle {record.vehicle_id}"
                )
            if event.request_id in self._events_by_request:
                raise OperationsAlreadyExistsError(
                    f"Request {event.request_id} was already committed"
                )
            self._records[record.vehicle_id] = deepcopy(record)
            self._events.append(deepcopy(event))
            self._events_by_request[event.request_id] = deepcopy(event)
            return deepcopy(record)

    def commit_transition(
        self,
        record: VehicleOperations,
        event: OperationsEvent,
        *,
        expected_revision: int,
    ) -> VehicleOperations:
        with self._lock:
            current = self._records.get(record.vehicle_id)
            if current is None:
                raise OperationsConflictError(
                    f"Operations no longer exist for vehicle {record.vehicle_id}"
                )
            if event.request_id in self._events_by_request:
                return deepcopy(current)
            if current.revision != expected_revision:
                raise OperationsConflictError(
                    f"Expected revision {expected_revision}; found {current.revision}"
                )
            if record.revision != expected_revision + 1:
                raise OperationsConflictError("Committed record revision must advance exactly once")
            if event.record_revision != record.revision:
                raise OperationsConflictError("Event revision does not match current record")
            self._records[record.vehicle_id] = deepcopy(record)
            self._events.append(deepcopy(event))
            self._events_by_request[event.request_id] = deepcopy(event)
            return deepcopy(record)

    def find_event_by_request_id(self, request_id: str) -> OperationsEvent | None:
        with self._lock:
            event = self._events_by_request.get(str(request_id))
            return deepcopy(event) if event is not None else None

    def list_events(self, vehicle_id: str) -> list[OperationsEvent]:
        with self._lock:
            return [
                deepcopy(event)
                for event in self._events
                if event.vehicle_id == str(vehicle_id)
            ]

    def delete_project(self, project_id: str) -> tuple[int, int]:
        with self._lock:
            wanted = str(project_id)
            vehicle_ids = {
                vehicle_id
                for vehicle_id, record in self._records.items()
                if record.project_id == wanted
            }
            event_request_ids = {
                event.request_id
                for event in self._events
                if event.project_id == wanted
            }
            event_count = len(event_request_ids)
            for vehicle_id in vehicle_ids:
                self._records.pop(vehicle_id, None)
            self._events = [
                event for event in self._events
                if event.project_id != wanted
            ]
            for request_id in event_request_ids:
                self._events_by_request.pop(request_id, None)
            return len(vehicle_ids), event_count
