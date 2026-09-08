"""Microsoft Graph repository for current operations state and event history.

SharePoint cannot atomically mutate two lists. This adapter therefore writes a
pending event containing the complete intended record, conditionally applies
that snapshot to the current row, and finally marks the event applied. Any
retry can resume the same request without inventing a second event.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import requests

from ....domain.operations_models import OperationsEvent, OperationsEventType, VehicleOperations
from ..interfaces import (
    OperationsAlreadyExistsError,
    OperationsConflictError,
    OperationsRepository,
    OperationsRepositoryError,
)
from .config import GRAPH_ENDPOINT, CloudConfig
from .operations_list_codec import (
    operations_event_from_fields,
    operations_event_to_fields,
    record_snapshot_from_json,
    record_snapshot_to_json,
    vehicle_operations_from_fields,
    vehicle_operations_to_fields,
)


TokenProvider = Callable[[], str]
_PENDING = "pending"
_APPLIED = "applied"
_CONFLICT = "conflict"


class SharePointOperationsRepository(OperationsRepository):
    """Operations persistence using two GUID-addressed SharePoint lists."""

    def __init__(
        self,
        *,
        token_provider: TokenProvider,
        site_id: str,
        operations_list_id: str,
        events_list_id: str,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        for value, label in (
            (site_id, "site_id"),
            (operations_list_id, "operations_list_id"),
            (events_list_id, "events_list_id"),
        ):
            if not str(value or "").strip():
                raise ValueError(f"{label} is required")
        if not callable(token_provider):
            raise ValueError("token_provider is required")
        self._token_provider = token_provider
        self._site_id = str(site_id).strip()
        self._operations_list_id = str(operations_list_id).strip()
        self._events_list_id = str(events_list_id).strip()
        self._session = session or requests.Session()
        self._timeout = max(1.0, min(float(timeout_seconds), 120.0))

    @classmethod
    def from_config(
        cls,
        config: CloudConfig,
        token_provider: TokenProvider,
        **kwargs,
    ) -> SharePointOperationsRepository:
        return cls(
            token_provider=token_provider,
            site_id=config.sharepoint_site_id,
            operations_list_id=config.operations_list_id,
            events_list_id=config.operations_events_list_id,
            **kwargs,
        )

    def get_vehicle(self, vehicle_id: str) -> VehicleOperations | None:
        vehicle_id = self._required(vehicle_id, "vehicle_id")
        self._reconcile_pending_for_vehicle(vehicle_id)
        item = self._find_vehicle_item(vehicle_id)
        return self._record_from_item(item) if item is not None else None

    def list_vehicles(self) -> list[VehicleOperations]:
        """Read every current projection without triggering repair writes."""

        records = [
            self._record_from_item(item)
            for item in self._query_items(self._operations_list_id)
        ]
        return sorted(
            records,
            key=lambda item: (
                str(item.agency_name).casefold(),
                str(item.vehicle_label or item.title).casefold(),
                item.vehicle_id,
            ),
        )

    def create_vehicle(
        self,
        record: VehicleOperations,
        event: OperationsEvent,
    ) -> VehicleOperations:
        self._validate_pair(record, event)
        if record.revision != 0 or event.record_revision != 0:
            raise OperationsConflictError("A new operations record must start at revision 0")
        existing = self._find_vehicle_item(record.vehicle_id)
        if existing is not None:
            raise OperationsAlreadyExistsError(
                f"Operations already exist for vehicle {record.vehicle_id}"
            )
        event_item = self._ensure_pending_event(record, event)
        return self._reconcile_event_item(event_item, intended=record)

    def commit_transition(
        self,
        record: VehicleOperations,
        event: OperationsEvent,
        *,
        expected_revision: int,
    ) -> VehicleOperations:
        self._validate_pair(record, event)
        if record.revision != expected_revision + 1:
            raise OperationsConflictError("Committed record revision must advance exactly once")
        if event.record_revision != record.revision:
            raise OperationsConflictError("Event revision does not match current record")
        current_item = self._find_vehicle_item(record.vehicle_id)
        if current_item is None:
            raise OperationsConflictError(
                f"Operations no longer exist for vehicle {record.vehicle_id}"
            )
        current = self._record_from_item(current_item)
        if current.revision != expected_revision:
            raise OperationsConflictError(
                f"Expected revision {expected_revision}; found {current.revision}"
            )
        event_item = self._ensure_pending_event(record, event)
        return self._reconcile_event_item(event_item, intended=record)

    def find_event_by_request_id(self, request_id: str) -> OperationsEvent | None:
        request_id = self._required(request_id, "request_id")
        item = self._find_event_item(request_id)
        if item is None:
            return None
        status = self._commit_status(item)
        if status == _CONFLICT:
            raise OperationsConflictError("Request ID belongs to a conflicted operation")
        if status == _PENDING:
            self._reconcile_event_item(item)
            item = self._find_event_item(request_id)
            if item is None or self._commit_status(item) != _APPLIED:
                raise OperationsRepositoryError("Pending operation could not be reconciled")
        return self._event_from_item(item)

    def list_events(self, vehicle_id: str) -> list[OperationsEvent]:
        """Read applied history without invoking pending-event reconciliation."""

        vehicle_id = self._required(vehicle_id, "vehicle_id")
        items = self._query_items(
            self._events_list_id,
            filter_expression=(
                f"fields/BuilderVehicleId eq '{self._odata_string(vehicle_id)}'"
            ),
        )
        events = [
            self._event_from_item(item)
            for item in items
            if self._commit_status(item) in {"", _APPLIED}
        ]
        return sorted(events, key=lambda event: (event.occurred_at, event.event_id))

    def delete_project(self, project_id: str) -> tuple[int, int]:
        """Delete one project's Operations rows and their complete event history."""

        project_id = self._required(project_id, "project_id")
        expression = (
            f"fields/BuilderProjectId eq '{self._odata_string(project_id)}'"
        )
        events = self._query_items(
            self._events_list_id,
            filter_expression=expression,
        )
        records = self._query_items(
            self._operations_list_id,
            filter_expression=expression,
        )
        # Remove history first so a partial failure leaves the visible current
        # rows in place and a retry can safely finish the same exact cascade.
        for item in events:
            self._delete_item(self._events_list_id, item, "operations event deletion")
        for item in records:
            self._delete_item(self._operations_list_id, item, "operations record deletion")
        return len(records), len(events)

    def _reconcile_pending_for_vehicle(self, vehicle_id: str) -> None:
        pending = self._query_items(
            self._events_list_id,
            filter_expression="fields/CommitStatus eq 'pending'",
        )
        relevant = [
            item for item in pending
            if str(self._fields(item).get("BuilderVehicleId") or "") == vehicle_id
        ]
        relevant.sort(key=lambda item: (
            self._integer(self._fields(item).get("RecordRevision")),
            str(self._fields(item).get("OccurredAtUtc") or ""),
            str(self._fields(item).get("EventId") or ""),
        ))
        for item in relevant:
            try:
                self._reconcile_event_item(item)
            except (OperationsAlreadyExistsError, OperationsConflictError):
                # The pending row has been durably marked conflict. It is an
                # attempted mutation, not part of the accepted event history.
                continue

    def _reconcile_event_item(
        self,
        event_item: dict,
        *,
        intended: VehicleOperations | None = None,
    ) -> VehicleOperations:
        fields = self._fields(event_item)
        event = operations_event_from_fields(fields)
        status = str(fields.get("CommitStatus") or _APPLIED)
        if status == _CONFLICT:
            raise OperationsConflictError("Operation was previously rejected by concurrency checks")
        try:
            snapshot = record_snapshot_from_json(fields.get("RecordSnapshotJson"))
        except ValueError as exc:
            raise OperationsRepositoryError(str(exc)) from None
        self._validate_pair(snapshot, event)
        if (
            intended is not None
            and record_snapshot_to_json(snapshot) != record_snapshot_to_json(intended)
        ):
            self._mark_conflict_best_effort(event_item)
            raise OperationsConflictError("Request ID was reused with different operations data")
        if event.record_revision != snapshot.revision:
            self._mark_conflict_best_effort(event_item)
            raise OperationsConflictError("Event snapshot revision does not match its event")

        current_item = self._find_vehicle_item(event.vehicle_id)
        is_create = event.event_type == OperationsEventType.RECORD_CREATED
        if current_item is not None:
            current = self._record_from_item(current_item)
            if (
                current.revision == snapshot.revision
                and current.last_event_id == event.event_id
            ):
                self._mark_event(event_item, _APPLIED)
                return current
            if is_create:
                self._mark_conflict_best_effort(event_item)
                raise OperationsAlreadyExistsError(
                    f"Operations already exist for vehicle {event.vehicle_id}"
                )
            if current.revision != snapshot.revision - 1:
                self._mark_conflict_best_effort(event_item)
                raise OperationsConflictError(
                    f"Expected revision {snapshot.revision - 1}; found {current.revision}"
                )
            try:
                self._apply_current_snapshot(current_item, snapshot, event_item)
            except OperationsRepositoryError:
                if not self._snapshot_is_current(snapshot):
                    raise
        elif is_create:
            try:
                self._create_current_snapshot(snapshot, event_item)
            except OperationsRepositoryError:
                if not self._snapshot_is_current(snapshot):
                    raise
        else:
            self._mark_conflict_best_effort(event_item)
            raise OperationsConflictError(
                f"Operations no longer exist for vehicle {event.vehicle_id}"
            )

        self._mark_event(event_item, _APPLIED)
        saved = self._find_vehicle_item(event.vehicle_id)
        if saved is None:
            raise OperationsRepositoryError("Applied operations record could not be reloaded")
        return self._record_from_item(saved)

    def _apply_current_snapshot(
        self,
        current_item: dict,
        snapshot: VehicleOperations,
        event_item: dict,
    ) -> None:
        etag = self._etag(current_item)
        response = self._send(
            "patch",
            self._fields_url(self._operations_list_id, self._item_id(current_item)),
            operation="current-record update",
            headers={"If-Match": etag},
            json=vehicle_operations_to_fields(snapshot),
        )
        if response.status_code == 412:
            refreshed = self._find_vehicle_item(snapshot.vehicle_id)
            if refreshed is not None:
                current = self._record_from_item(refreshed)
                if (
                    current.revision == snapshot.revision
                    and current.last_event_id == snapshot.last_event_id
                ):
                    return
            self._mark_conflict_best_effort(event_item)
            found_revision = self._record_from_item(refreshed).revision if refreshed else "missing"
            raise OperationsConflictError(
                f"Expected revision {snapshot.revision - 1}; found {found_revision}"
            )
        self._raise_for_status(response, operation="current-record update")

    def _create_current_snapshot(
        self,
        snapshot: VehicleOperations,
        event_item: dict,
    ) -> None:
        response = self._send(
            "post",
            self._items_url(self._operations_list_id),
            operation="current-record creation",
            json={"fields": vehicle_operations_to_fields(snapshot)},
        )
        if response.status_code in {400, 409}:
            existing = self._find_vehicle_item(snapshot.vehicle_id)
            if existing is not None:
                current = self._record_from_item(existing)
                if (
                    current.revision == snapshot.revision
                    and current.last_event_id == snapshot.last_event_id
                ):
                    return
                self._mark_conflict_best_effort(event_item)
                raise OperationsAlreadyExistsError(
                    f"Operations already exist for vehicle {snapshot.vehicle_id}"
                )
        self._raise_for_status(response, operation="current-record creation")

    def _ensure_pending_event(
        self,
        record: VehicleOperations,
        event: OperationsEvent,
    ) -> dict:
        existing = self._find_event_item(event.request_id)
        if existing is not None:
            self._validate_existing_event(existing, record, event)
            return existing
        try:
            response = self._send(
                "post",
                self._items_url(self._events_list_id),
                operation="pending-event creation",
                json={"fields": operations_event_to_fields(event, record)},
            )
        except OperationsRepositoryError:
            existing = self._find_event_item(event.request_id)
            if existing is None:
                raise
            self._validate_existing_event(existing, record, event)
            return existing
        if response.status_code not in {200, 201}:
            if response.status_code in {400, 409}:
                existing = self._find_event_item(event.request_id)
                if existing is not None:
                    self._validate_existing_event(existing, record, event)
                    return existing
            self._raise_for_status(response, operation="pending-event creation")
        created = self._find_event_item(event.request_id)
        if created is None:
            raise OperationsRepositoryError("Created operations event could not be reloaded")
        self._validate_existing_event(created, record, event)
        return created

    def _validate_existing_event(
        self,
        item: dict,
        record: VehicleOperations,
        event: OperationsEvent,
    ) -> None:
        found = self._event_from_item(item)
        try:
            stored_snapshot = record_snapshot_to_json(
                record_snapshot_from_json(self._fields(item).get("RecordSnapshotJson"))
            )
        except ValueError as exc:
            raise OperationsRepositoryError(str(exc)) from None
        if (
            found.event_id != event.event_id
            or found.vehicle_id != event.vehicle_id
            or found.project_id != event.project_id
            or stored_snapshot != record_snapshot_to_json(record)
        ):
            raise OperationsConflictError("Request ID was reused for another operation")

    def _mark_event(self, event_item: dict, status: str) -> None:
        current_status = self._commit_status(event_item)
        if current_status == status:
            return
        request_id = str(self._fields(event_item).get("RequestId") or "")
        try:
            response = self._send(
                "patch",
                self._fields_url(self._events_list_id, self._item_id(event_item)),
                operation=f"event {status}",
                headers={"If-Match": self._etag(event_item)},
                json={"CommitStatus": status},
            )
        except OperationsRepositoryError:
            refreshed = self._find_event_item(request_id)
            if refreshed is not None and self._commit_status(refreshed) == status:
                return
            raise
        if response.status_code == 412:
            refreshed = self._find_event_item(request_id)
            if refreshed is not None and self._commit_status(refreshed) == status:
                return
        self._raise_for_status(response, operation=f"event {status}")

    def _mark_conflict_best_effort(self, event_item: dict) -> None:
        try:
            self._mark_event(event_item, _CONFLICT)
        except OperationsRepositoryError:
            pass

    def _find_vehicle_item(self, vehicle_id: str) -> dict | None:
        items = self._query_items(
            self._operations_list_id,
            filter_expression=(
                f"fields/BuilderVehicleId eq '{self._odata_string(vehicle_id)}'"
            ),
            top=2,
        )
        if len(items) > 1:
            raise OperationsRepositoryError("Duplicate operations rows exist for one vehicle")
        return items[0] if items else None

    def _find_event_item(self, request_id: str) -> dict | None:
        items = self._query_items(
            self._events_list_id,
            filter_expression=f"fields/RequestId eq '{self._odata_string(request_id)}'",
            top=2,
        )
        if len(items) > 1:
            raise OperationsRepositoryError("Duplicate operations events share one request ID")
        return items[0] if items else None

    def _snapshot_is_current(self, snapshot: VehicleOperations) -> bool:
        item = self._find_vehicle_item(snapshot.vehicle_id)
        if item is None:
            return False
        current = self._record_from_item(item)
        return (
            current.revision == snapshot.revision
            and current.last_event_id == snapshot.last_event_id
        )

    def _query_items(
        self,
        list_id: str,
        *,
        filter_expression: str = "",
        top: int = 999,
    ) -> list[dict]:
        rows: list[dict] = []
        url = self._items_url(list_id)
        params: dict[str, str] | None = {
            "$expand": "fields",
            "$top": str(max(1, min(int(top), 999))),
        }
        if filter_expression:
            params["$filter"] = filter_expression
        while url:
            response = self._send(
                "get", url, operation="operations query", params=params,
            )
            self._raise_for_status(response, operation="operations query")
            payload = self._response_json(response, operation="operations query")
            value = payload.get("value", [])
            if not isinstance(value, list):
                raise OperationsRepositoryError("SharePoint operations query was not a collection")
            rows.extend(item for item in value if isinstance(item, dict))
            url = str(payload.get("@odata.nextLink") or "")
            params = None
        return rows

    def _send(self, method: str, url: str, *, operation: str, headers=None, **kwargs):
        if (
            os.environ.get("PYTEST_CURRENT_TEST")
            and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS")
            and isinstance(self._session, requests.Session)
        ):
            raise OperationsRepositoryError(
                "SharePoint operations access is disabled in the test environment"
            )
        try:
            token = str(self._token_provider() or "").strip()
            if not token:
                raise OperationsRepositoryError("SharePoint authentication is unavailable")
            return getattr(self._session, method)(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    **(headers or {}),
                },
                timeout=self._timeout,
                **kwargs,
            )
        except OperationsRepositoryError:
            raise
        except requests.RequestException as exc:
            raise OperationsRepositoryError(
                f"SharePoint {operation} request failed ({type(exc).__name__})"
            ) from None
        except Exception as exc:
            raise OperationsRepositoryError(
                f"SharePoint authentication failed ({type(exc).__name__})"
            ) from None

    def _delete_item(self, list_id: str, item: dict, operation: str) -> None:
        response = self._send(
            "delete",
            self._item_url(list_id, self._item_id(item)),
            operation=operation,
            headers={"If-Match": self._etag(item)},
        )
        self._raise_for_status(response, operation=operation)

    @staticmethod
    def _raise_for_status(response, *, operation: str) -> None:
        try:
            response.raise_for_status()
        except requests.RequestException:
            status = getattr(response, "status_code", None)
            detail = f"HTTP {status}" if status else "HTTP request failed"
            raise OperationsRepositoryError(
                f"SharePoint {operation} failed ({detail})"
            ) from None

    @staticmethod
    def _response_json(response, *, operation: str) -> dict:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise OperationsRepositoryError(
                f"SharePoint {operation} returned invalid JSON"
            ) from None
        if not isinstance(payload, dict):
            raise OperationsRepositoryError(
                f"SharePoint {operation} returned an invalid object"
            )
        return payload

    @staticmethod
    def _fields(item: dict) -> dict:
        fields = item.get("fields")
        if not isinstance(fields, dict):
            raise OperationsRepositoryError("SharePoint list item has no fields")
        return fields

    @staticmethod
    def _item_id(item: dict) -> str:
        value = str(item.get("id") or "").strip()
        if not value:
            raise OperationsRepositoryError("SharePoint list item has no durable ID")
        return value

    @staticmethod
    def _etag(item: dict) -> str:
        value = str(item.get("eTag") or item.get("@odata.etag") or "").strip()
        if not value:
            raise OperationsRepositoryError("SharePoint list item has no concurrency tag")
        return value

    @classmethod
    def _record_from_item(cls, item: dict) -> VehicleOperations:
        try:
            return vehicle_operations_from_fields(cls._fields(item))
        except ValueError as exc:
            raise OperationsRepositoryError(str(exc)) from None

    @classmethod
    def _event_from_item(cls, item: dict) -> OperationsEvent:
        try:
            return operations_event_from_fields(cls._fields(item))
        except ValueError as exc:
            raise OperationsRepositoryError(str(exc)) from None

    @classmethod
    def _commit_status(cls, item: dict) -> str:
        return str(cls._fields(item).get("CommitStatus") or "")

    @staticmethod
    def _validate_pair(record: VehicleOperations, event: OperationsEvent) -> None:
        if record.vehicle_id != event.vehicle_id or record.project_id != event.project_id:
            raise OperationsConflictError("Operations record and event identity do not match")
        if record.last_event_id != event.event_id:
            raise OperationsConflictError("Operations record does not reference its event")

    @staticmethod
    def _integer(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _required(value: Any, label: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError(f"{label} is required")
        return cleaned

    @staticmethod
    def _odata_string(value: str) -> str:
        return str(value).replace("'", "''")

    def _items_url(self, list_id: str) -> str:
        return (
            f"{GRAPH_ENDPOINT}/sites/{quote(self._site_id, safe='')}/lists/"
            f"{quote(list_id, safe='')}/items"
        )

    def _fields_url(self, list_id: str, item_id: str) -> str:
        return f"{self._items_url(list_id)}/{quote(item_id, safe='')}/fields"

    def _item_url(self, list_id: str, item_id: str) -> str:
        return f"{self._items_url(list_id)}/{quote(item_id, safe='')}"
