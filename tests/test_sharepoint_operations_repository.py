from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest
import requests

from dtm_buildsheet.app.adapters import (
    OperationsAlreadyExistsError,
    OperationsConflictError,
    OperationsRepositoryError,
)
from dtm_buildsheet.app.adapters.cloud.operations_list_codec import (
    operations_event_from_fields,
    operations_event_to_fields,
    record_snapshot_from_json,
    vehicle_operations_from_fields,
    vehicle_operations_to_fields,
)
from dtm_buildsheet.app.adapters.cloud.sharepoint_operations_repository import (
    SharePointOperationsRepository,
)
from dtm_buildsheet.app.adapters.memory_operations_repository import (
    InMemoryOperationsRepository,
)
from dtm_buildsheet.app.services.operations_service import OperationsService
from dtm_buildsheet.domain.operations_models import (
    OperationsActor,
    OperationsEvent,
    OperationsEventType,
    OperationsSource,
    OperationsWorkstream,
    ProjectState,
    VehicleAvailabilityStatus,
    VehicleOperations,
)
from dtm_buildsheet.domain.operations_policy import AppRole


NOW = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)


class _Response:
    def __init__(self, payload=None, status_code: int = 200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code

    def json(self):
        return deepcopy(self._payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _GraphSession:
    """Stateful in-memory Graph double; it never opens a network connection."""

    def __init__(self):
        self.rows = {"operations-id": [], "events-id": []}
        self._next_id = 1
        self.calls: list[tuple[str, str]] = []
        self.fail_event_post_before_write_once = False
        self.fail_event_post_after_write_once = False
        self.fail_current_create_after_write_once = False
        self.fail_current_patch_before_write_once = False
        self.fail_current_patch_after_write_once = False
        self.fail_event_patch_before_write_once = False
        self.fail_event_patch_after_write_once = False
        self.force_concurrent_current_patch_once = False

    def get(self, url, *, headers, timeout, params=None):
        list_id = self._list_id(url)
        self.calls.append(("get", list_id))
        rows = list(self.rows[list_id])
        expression = str((params or {}).get("$filter") or "")
        if expression:
            match = re.fullmatch(r"fields/([A-Za-z0-9_]+) eq '(.*)'", expression)
            assert match, expression
            field_name, wanted = match.groups()
            wanted = wanted.replace("''", "'")
            rows = [
                row for row in rows
                if str(row["fields"].get(field_name) or "") == wanted
            ]
        top = int((params or {}).get("$top", 999))
        return _Response({"value": deepcopy(rows[:top])})

    def post(self, url, *, headers, timeout, json):
        list_id = self._list_id(url)
        self.calls.append(("post", list_id))
        fields = deepcopy(json["fields"])
        if list_id == "events-id" and self.fail_event_post_before_write_once:
            self.fail_event_post_before_write_once = False
            raise requests.ConnectionError("simulated failure before event creation")
        unique_fields = (
            ("BuilderVehicleId",)
            if list_id == "operations-id"
            else ("EventId", "RequestId")
        )
        if any(
            str(row["fields"].get(field_name) or "")
            == str(fields.get(field_name) or "")
            for row in self.rows[list_id]
            for field_name in unique_fields
        ):
            return _Response(status_code=409)
        item = {
            "id": str(self._next_id),
            "eTag": '"1"',
            "fields": fields,
        }
        self._next_id += 1
        self.rows[list_id].append(item)
        if list_id == "events-id" and self.fail_event_post_after_write_once:
            self.fail_event_post_after_write_once = False
            raise requests.ConnectionError("simulated uncertain event creation")
        if list_id == "operations-id" and self.fail_current_create_after_write_once:
            self.fail_current_create_after_write_once = False
            raise requests.ConnectionError("simulated uncertain current creation")
        return _Response(item, status_code=201)

    def patch(self, url, *, headers, timeout, json):
        list_id = self._list_id(url)
        self.calls.append(("patch", list_id))
        item_id = url.split("/items/", 1)[1].split("/", 1)[0]
        item = next(row for row in self.rows[list_id] if row["id"] == item_id)
        if list_id == "operations-id" and self.fail_current_patch_before_write_once:
            self.fail_current_patch_before_write_once = False
            raise requests.ConnectionError("simulated token-bearing URL must not escape")
        if list_id == "operations-id" and self.force_concurrent_current_patch_once:
            self.force_concurrent_current_patch_once = False
            item["fields"]["Revision"] = int(item["fields"].get("Revision", 0)) + 1
            item["fields"]["LastEventId"] = "other-client-event"
            self._bump(item)
        if headers.get("If-Match") != item["eTag"]:
            return _Response(status_code=412)
        if list_id == "events-id" and self.fail_event_patch_before_write_once:
            self.fail_event_patch_before_write_once = False
            raise requests.ConnectionError("simulated failure before event update")
        item["fields"].update(deepcopy(json))
        self._bump(item)
        if list_id == "operations-id" and self.fail_current_patch_after_write_once:
            self.fail_current_patch_after_write_once = False
            raise requests.ConnectionError("simulated uncertain response")
        if list_id == "events-id" and self.fail_event_patch_after_write_once:
            self.fail_event_patch_after_write_once = False
            raise requests.ConnectionError("simulated uncertain response")
        return _Response(item)

    def delete(self, url, *, headers, timeout):
        del timeout
        list_id = self._list_id(url)
        self.calls.append(("delete", list_id))
        item_id = url.split("/items/", 1)[1].split("/", 1)[0]
        item = next(row for row in self.rows[list_id] if row["id"] == item_id)
        if headers.get("If-Match") != item["eTag"]:
            return _Response(status_code=412)
        self.rows[list_id].remove(item)
        return _Response(status_code=204)

    @staticmethod
    def _list_id(url: str) -> str:
        return url.split("/lists/", 1)[1].split("/", 1)[0]

    @staticmethod
    def _bump(item: dict) -> None:
        version = int(item["eTag"].strip('"')) + 1
        item["eTag"] = f'"{version}"'


def _actor(*roles: AppRole) -> OperationsActor:
    return OperationsActor(
        user_id="entra-1",
        display_name="Test User",
        roles=frozenset(role.value for role in roles),
    )


def _sharepoint_repository(session: _GraphSession) -> SharePointOperationsRepository:
    return SharePointOperationsRepository(
        token_provider=lambda: "TOKEN",
        site_id="tenant.sharepoint.com,site-id,web-id",
        operations_list_id="operations-id",
        events_list_id="events-id",
        session=session,
    )


def _service(repository):
    counter = iter(range(100))
    return OperationsService(
        repository,
        clock=lambda: NOW,
        event_id_factory=lambda: f"event-{next(counter)}",
    )


def _create(service: OperationsService, request_id: str = "create-1"):
    return service.create_vehicle(
        vehicle_id="vehicle-1",
        project_id="project-1",
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id=request_id,
        source_client=OperationsSource.BUILDER_DESKTOP,
        title="Unit 21",
        agency_name="Example PD",
        build_year="2027",
        vehicle_label="2027 Example PD PIU - Unit 21",
    )


@pytest.fixture(params=["memory", "sharepoint"])
def repository(request):
    if request.param == "memory":
        return InMemoryOperationsRepository()
    return _sharepoint_repository(_GraphSession())


class TestRepositoryContract:
    def test_create_get_find_and_list_round_trip(self, repository):
        service = _service(repository)
        created = _create(service)

        assert repository.get_vehicle("vehicle-1") == created.record
        assert repository.list_vehicles() == [created.record]
        assert repository.find_event_by_request_id("create-1") == created.event
        assert repository.list_events("vehicle-1") == [created.event]
        assert repository.list_events("another-vehicle") == []

    def test_duplicate_request_is_one_event(self, repository):
        service = _service(repository)
        _create(service)
        first = service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="shop-start",
            source_client="builder_desktop",
        )
        duplicate = service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="shop-start",
            source_client="builder_desktop",
        )

        assert first.record.revision == 1
        assert duplicate.duplicate is True
        assert duplicate.event == first.event
        assert len(repository.list_events("vehicle-1")) == 2

    def test_stale_revision_and_duplicate_vehicle_are_rejected(self, repository):
        service = _service(repository)
        _create(service)
        service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="shop-start",
            source_client="builder_desktop",
            expected_revision=0,
        )
        with pytest.raises(OperationsConflictError, match="Expected revision 0"):
            service.change_status(
                vehicle_id="vehicle-1",
                workstream="tray",
                new_status="ready",
                actor=_actor(AppRole.SHOP_EDITOR),
                request_id="stale",
                source_client="builder_desktop",
                expected_revision=0,
            )
        with pytest.raises(OperationsAlreadyExistsError):
            service.create_vehicle(
                vehicle_id="vehicle-1",
                project_id="another-project",
                actor=_actor(AppRole.BUILDER_EDITOR),
                request_id="another-create",
                source_client="builder_desktop",
            )

    def test_delete_project_removes_only_its_records_and_history(self, repository):
        service = _service(repository)
        _create(service)
        service.create_vehicle(
            vehicle_id="vehicle-2",
            project_id="project-2",
            actor=_actor(AppRole.BUILDER_EDITOR),
            request_id="create-2",
            source_client=OperationsSource.BUILDER_DESKTOP,
        )
        service.change_status(
            vehicle_id="vehicle-1",
            workstream="parts",
            new_status="ordered",
            actor=_actor(AppRole.PARTS_EDITOR),
            request_id="parts-1",
            source_client=OperationsSource.BUILDER_DESKTOP,
        )

        assert repository.delete_project("project-1") == (1, 2)
        assert repository.get_vehicle("vehicle-1") is None
        assert repository.list_events("vehicle-1") == []
        assert repository.get_vehicle("vehicle-2") is not None
        assert len(repository.list_events("vehicle-2")) == 1


def test_sharepoint_vehicle_list_is_strictly_read_only():
    session = _GraphSession()
    repository = _sharepoint_repository(session)
    created = _create(_service(repository))
    session.calls.clear()

    assert repository.list_vehicles() == [created.record]
    assert session.calls == [("get", "operations-id")]


def test_sharepoint_event_list_is_strictly_read_only():
    session = _GraphSession()
    repository = _sharepoint_repository(session)
    created = _create(_service(repository))
    session.calls.clear()

    assert repository.list_events("vehicle-1") == [created.event]
    assert session.calls == [("get", "events-id")]


class TestSharePointFieldCodec:
    def test_current_and_event_fields_round_trip(self):
        record = VehicleOperations(
            vehicle_id="vehicle-1",
            project_id="project-1",
            title="Unit 21",
            revision=3,
            vin="1FTFW1E50NFA12345",
            project_state=ProjectState.INACTIVE,
            vehicle_availability_status=VehicleAvailabilityStatus.AT_DTM,
            vehicle_availability_status_changed_at="2026-09-04T14:00:00+00:00",
            created_at="2026-09-01T14:00:00+00:00",
            created_by_id="entra-1",
            created_by_name="Creator",
            updated_at="2026-09-04T14:00:00+00:00",
            last_event_id="event-3",
        )
        event = OperationsEvent(
            event_id="event-3",
            request_id="request-3",
            vehicle_id="vehicle-1",
            project_id="project-1",
            workstream=OperationsWorkstream.AVAILABILITY,
            event_type=OperationsEventType.AVAILABILITY_CHANGED,
            previous_value="ready_for_pickup",
            new_value="at_dtm",
            occurred_at="2026-09-04T14:00:00+00:00",
            actor_id="entra-1",
            actor_display_name="Test User",
            source_client=OperationsSource.BUILDER_DESKTOP,
            record_revision=3,
        )

        current_fields = vehicle_operations_to_fields(record)
        event_fields = operations_event_to_fields(event, record)

        assert current_fields["VehicleAvailabilityStatusChanged"] == (
            "2026-09-04T14:00:00+00:00"
        )
        assert current_fields["DeliveryMethod"] is None
        assert vehicle_operations_from_fields(current_fields) == record
        assert operations_event_from_fields(event_fields) == event
        assert event_fields["CommitStatus"] == "pending"
        assert "1FTFW1E50NFA12345" in event_fields["RecordSnapshotJson"]

    def test_phone_flow_sharepoint_field_snapshot_normalizes_to_domain_record(self):
        record = VehicleOperations(
            vehicle_id="vehicle-1",
            project_id="project-1",
            revision=4,
            shop_status="complete",
            updated_at="2026-09-09T15:00:00+00:00",
            last_event_id="request-4",
            source_client=OperationsSource.POWER_APPS_MOBILE,
        )
        fields = vehicle_operations_to_fields(record)
        fields["ID"] = 42
        fields["@odata.etag"] = '"4"'

        decoded = record_snapshot_from_json(json.dumps(fields))

        assert decoded == replace(record, title="vehicle-1")

    def test_graph_date_only_timestamps_are_normalized_for_browser_inputs(self):
        record = VehicleOperations(vehicle_id="vehicle-1", project_id="project-1")
        current_fields = vehicle_operations_to_fields(record)
        current_fields["ScheduledWeekOf"] = "2026-09-07T07:00:00Z"
        current_fields["MustDeliverOverrideDate"] = "2026-11-06T08:00:00Z"
        event = OperationsEvent(
            event_id="event-1",
            request_id="request-1",
            vehicle_id="vehicle-1",
            project_id="project-1",
            workstream=OperationsWorkstream.SCHEDULE,
            event_type=OperationsEventType.SCHEDULE_CHANGED,
            previous_value="",
            new_value="",
            occurred_at="2026-09-04T14:00:00+00:00",
            actor_id="entra-1",
            actor_display_name="Test User",
            source_client=OperationsSource.BUILDER_DESKTOP,
        )
        event_fields = operations_event_to_fields(event, record)
        event_fields["EffectiveDate"] = "2026-09-07T07:00:00Z"

        decoded_record = vehicle_operations_from_fields(current_fields)
        decoded_event = operations_event_from_fields(event_fields)

        assert decoded_record.scheduled_week_of == "2026-09-07"
        assert decoded_record.must_deliver_override_date == "2026-11-06"
        assert decoded_event.effective_date == "2026-09-07"


class TestSharePointRecovery:
    def test_event_create_failure_before_write_leaves_current_untouched(self):
        session = _GraphSession()
        repository = _sharepoint_repository(session)
        service = _service(repository)
        _create(service)
        session.fail_event_post_before_write_once = True

        with pytest.raises(OperationsRepositoryError, match="ConnectionError"):
            service.change_status(
                vehicle_id="vehicle-1",
                workstream="shop",
                new_status="in_progress",
                actor=_actor(AppRole.SHOP_EDITOR),
                request_id="try-again",
                source_client="builder_desktop",
            )

        assert repository.get_vehicle("vehicle-1").revision == 0
        retried = service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="try-again",
            source_client="builder_desktop",
        )
        assert retried.record.revision == 1
        assert len(repository.list_events("vehicle-1")) == 2

    @pytest.mark.parametrize(
        "failure_flag",
        ["fail_event_post_after_write_once", "fail_current_create_after_write_once"],
    )
    def test_uncertain_create_is_verified_without_duplicate(self, failure_flag):
        session = _GraphSession()
        repository = _sharepoint_repository(session)
        service = _service(repository)
        setattr(session, failure_flag, True)

        created = _create(service)

        assert created.record.revision == 0
        assert len(session.rows["operations-id"]) == 1
        assert len(session.rows["events-id"]) == 1
        assert session.rows["events-id"][0]["fields"]["CommitStatus"] == "applied"

    def test_pending_event_resumes_after_failure_before_current_patch(self):
        session = _GraphSession()
        repository = _sharepoint_repository(session)
        service = _service(repository)
        _create(service)
        session.fail_current_patch_before_write_once = True

        with pytest.raises(OperationsRepositoryError, match="ConnectionError"):
            service.change_status(
                vehicle_id="vehicle-1",
                workstream="shop",
                new_status="in_progress",
                actor=_actor(AppRole.SHOP_EDITOR),
                request_id="recover-me",
                source_client="builder_desktop",
            )

        recovered = service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="recover-me",
            source_client="builder_desktop",
        )

        assert recovered.duplicate is True
        assert recovered.record.shop_status == "in_progress"
        assert len(repository.list_events("vehicle-1")) == 2

    def test_vehicle_read_repairs_an_abandoned_pending_event(self):
        session = _GraphSession()
        repository = _sharepoint_repository(session)
        service = _service(repository)
        _create(service)
        session.fail_current_patch_before_write_once = True
        with pytest.raises(OperationsRepositoryError):
            service.change_status(
                vehicle_id="vehicle-1",
                workstream="shop",
                new_status="in_progress",
                actor=_actor(AppRole.SHOP_EDITOR),
                request_id="abandoned",
                source_client="builder_desktop",
            )

        repaired = repository.get_vehicle("vehicle-1")

        assert repaired.shop_status == "in_progress"
        assert session.rows["events-id"][-1]["fields"]["CommitStatus"] == "applied"

    @pytest.mark.parametrize(
        "failure_flag",
        [
            "fail_current_patch_after_write_once",
            "fail_event_patch_after_write_once",
        ],
    )
    def test_uncertain_success_is_verified_without_duplicate(self, failure_flag):
        session = _GraphSession()
        repository = _sharepoint_repository(session)
        service = _service(repository)
        _create(service)
        setattr(session, failure_flag, True)

        result = service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="uncertain",
            source_client="builder_desktop",
        )

        assert result.record.revision == 1
        assert len(repository.list_events("vehicle-1")) == 2
        assert session.rows["events-id"][-1]["fields"]["CommitStatus"] == "applied"

    def test_retry_finishes_event_marker_after_pre_write_failure(self):
        session = _GraphSession()
        repository = _sharepoint_repository(session)
        service = _service(repository)
        _create(service)
        session.fail_event_patch_before_write_once = True

        with pytest.raises(OperationsRepositoryError, match="ConnectionError"):
            service.change_status(
                vehicle_id="vehicle-1",
                workstream="shop",
                new_status="in_progress",
                actor=_actor(AppRole.SHOP_EDITOR),
                request_id="finish-marker",
                source_client="builder_desktop",
            )

        retried = service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="finish-marker",
            source_client="builder_desktop",
        )
        assert retried.duplicate is True
        assert session.rows["events-id"][-1]["fields"]["CommitStatus"] == "applied"

    def test_etag_race_rejects_stale_write_and_hides_conflicted_event(self):
        session = _GraphSession()
        repository = _sharepoint_repository(session)
        service = _service(repository)
        _create(service)
        session.force_concurrent_current_patch_once = True

        with pytest.raises(OperationsConflictError, match="Expected revision 0; found 1"):
            service.change_status(
                vehicle_id="vehicle-1",
                workstream="shop",
                new_status="in_progress",
                actor=_actor(AppRole.SHOP_EDITOR),
                request_id="lost-race",
                source_client="builder_desktop",
                expected_revision=0,
            )

        assert session.rows["events-id"][-1]["fields"]["CommitStatus"] == "conflict"
        assert [event.request_id for event in repository.list_events("vehicle-1")] == [
            "create-1"
        ]

    def test_request_reuse_with_different_payload_is_rejected(self):
        session = _GraphSession()
        repository = _sharepoint_repository(session)
        service = _service(repository)
        created = _create(service)
        changed_record = replace(created.record, agency_name="Different Agency")

        with pytest.raises(OperationsConflictError, match="reused"):
            repository._ensure_pending_event(changed_record, created.event)

    def test_network_error_never_exposes_response_url(self):
        session = _GraphSession()
        session.get = lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.ConnectionError("https://example.invalid/?token=do-not-leak")
        )
        repository = _sharepoint_repository(session)

        with pytest.raises(OperationsRepositoryError) as raised:
            repository.get_vehicle("vehicle-1")

        assert "do-not-leak" not in str(raised.value)
        assert raised.value.__cause__ is None
