from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dtm_buildsheet.app.adapters import OperationsConflictError
from dtm_buildsheet.app.adapters.memory_operations_repository import (
    InMemoryOperationsRepository,
)
from dtm_buildsheet.app.services.operations_service import (
    OperationsAuthorizationError,
    OperationsService,
    OperationsValidationError,
)
from dtm_buildsheet.domain.operations_codec import (
    operations_event_from_dict,
    operations_event_to_dict,
    vehicle_operations_from_dict,
    vehicle_operations_to_dict,
)
from dtm_buildsheet.domain.operations_models import (
    AcceptanceSource,
    AcceptanceStatus,
    OperationsActor,
    OperationsSource,
    OperationsWorkstream,
    PartsStatus,
    ProjectAcceptanceTag,
    ScheduleBucket,
    VehicleAvailabilityStatus,
    VehicleOperations,
    calculate_commitment_dates,
    is_ready_to_build,
    project_acceptance_tag,
    qbo_observation_is_stale,
    schedule_bucket,
)
from dtm_buildsheet.domain.operations_policy import (
    ALL_CAPABILITIES,
    AppRole,
    Capability,
    capabilities_for_roles,
    has_capability,
)


NOW = datetime(2026, 9, 3, 15, 30, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()


def _actor(*roles: AppRole, user_id: str = "entra-1") -> OperationsActor:
    return OperationsActor(
        user_id=user_id,
        display_name="Test User",
        roles=frozenset(role.value for role in roles),
    )


def _service():
    repository = InMemoryOperationsRepository()
    counter = iter(range(100))
    service = OperationsService(
        repository,
        clock=lambda: NOW,
        event_id_factory=lambda: f"event-{next(counter)}",
    )
    created = service.create_vehicle(
        vehicle_id="vehicle-1",
        project_id="project-1",
        actor=_actor(AppRole.BUILDER_EDITOR),
        request_id="create-1",
        source_client=OperationsSource.BUILDER_DESKTOP,
        title="Unit 21",
    )
    return service, repository, created.record


class TestOperationsPolicy:
    def test_unknown_roles_are_denied(self):
        assert capabilities_for_roles(["MadeUpRole"]) == frozenset()
        assert has_capability(["MadeUpRole"], Capability.OPERATIONS_VIEW) is False

    def test_multiple_roles_union_capabilities(self):
        capabilities = capabilities_for_roles([
            AppRole.PARTS_EDITOR,
            AppRole.PROGRAMMING_QC_EDITOR,
        ])
        assert Capability.OPERATIONS_PARTS_UPDATE in capabilities
        assert Capability.OPERATIONS_PROGRAMMING_QC_UPDATE in capabilities
        assert Capability.OPERATIONS_SHOP_UPDATE not in capabilities

    def test_admin_has_every_known_capability(self):
        assert capabilities_for_roles([AppRole.APP_ADMIN]) == ALL_CAPABILITIES


class TestOperationsCodec:
    def test_current_record_round_trips_enums_as_stable_values(self):
        original = VehicleOperations(
            vehicle_id="v1",
            project_id="p1",
            build_finalized=True,
            vin="1FTFW1E50NFA12345",
            vehicle_availability_status=VehicleAvailabilityStatus.READY_FOR_PICKUP,
        )
        payload = vehicle_operations_to_dict(original)

        assert payload["project_state"] == "active"
        assert payload["tray_status"] == "not_ready"
        assert payload["build_finalized"] is True
        assert payload["vin"] == "1FTFW1E50NFA12345"
        assert vehicle_operations_from_dict(payload) == original

    def test_unknown_current_values_fall_back_safely(self):
        record = vehicle_operations_from_dict({
            "vehicle_id": "v1",
            "project_id": "p1",
            "project_state": "lost",
            "parts_status": "palletized",
            "shop_status": "blocked",
            "tray_status": "paused",
        })

        assert record.project_state.value == "active"
        assert record.parts_status == ""
        assert record.shop_status == ""
        assert record.tray_status.value == "not_ready"

    def test_sixty_day_commitment_uses_later_business_date(self):
        assert calculate_commitment_dates(
            "2026-09-01",
            "2026-09-07T15:30:00+00:00",
        ) == ("2026-09-07", "2026-11-06")
        assert calculate_commitment_dates("", "2026-09-07T15:30:00+00:00") == ("", "")

    def test_schedule_bucket_is_derived_from_acceptance_and_week(self):
        record = VehicleOperations(vehicle_id="v1", project_id="p1")
        assert schedule_bucket(record) == ScheduleBucket.PROSPECTIVE
        record.acceptance_status = AcceptanceStatus.ACCEPTED
        assert schedule_bucket(record) == ScheduleBucket.UNSCHEDULED
        record.scheduled_week_of = "2026-10-12"
        assert schedule_bucket(record) == ScheduleBucket.SCHEDULED

    def test_ready_to_build_is_derived_with_override(self):
        record = VehicleOperations(
            vehicle_id="v1",
            project_id="p1",
            build_finalized=True,
            parts_status=PartsStatus.PARTS_READY.value,
            vehicle_availability_status=VehicleAvailabilityStatus.AT_DTM,
        )
        assert is_ready_to_build(record) is True
        record.parts_status = "received"
        assert is_ready_to_build(record) is False
        record.ready_to_build_override = True
        assert is_ready_to_build(record) is True

    def test_qbo_observation_warns_at_twenty_four_hours(self):
        assert qbo_observation_is_stale(
            "2026-09-02T15:30:01Z",
            as_of=NOW,
        ) is False
        assert qbo_observation_is_stale(
            "2026-09-02T15:30:00Z",
            as_of=NOW,
        ) is True
        assert qbo_observation_is_stale("", as_of=NOW) is True

    def test_event_round_trip(self):
        service, repository, _ = _service()
        result = service.change_status(
            vehicle_id="vehicle-1",
            workstream=OperationsWorkstream.SHOP,
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="shop-start",
            source_client="builder_desktop",
        )
        payload = operations_event_to_dict(result.event)

        assert payload["workstream"] == "shop"
        assert operations_event_from_dict(payload) == result.event
        assert len(repository.list_events("vehicle-1")) == 2


class TestOperationsTransitions:
    def test_create_records_initial_statuses_and_audit(self):
        _, repository, record = _service()

        assert record.revision == 0
        assert record.shop_status == ""
        assert record.tray_status.value == "not_ready"
        assert record.programming_qc_status.value == "not_ready"
        assert record.created_at == NOW_ISO
        events = repository.list_events("vehicle-1")
        assert len(events) == 1
        assert events[0].event_type.value == "record_created"

    def test_shop_start_and_complete_stamp_dates(self):
        service, repository, _ = _service()
        started = service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="shop-start",
            source_client="builder_desktop",
            expected_revision=0,
        )
        completed = service.change_status(
            vehicle_id="vehicle-1",
            workstream="shop",
            new_status="complete",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="shop-complete",
            source_client="builder_desktop",
            expected_revision=1,
        )

        assert started.record.shop_started_at == NOW_ISO
        assert completed.record.shop_completed_at == NOW_ISO
        assert completed.record.revision == 2
        assert [event.new_value for event in repository.list_events("vehicle-1")] == [
            "created", "in_progress", "complete",
        ]

    def test_workstreams_overlap_without_cross_stream_dependency(self):
        service, _, _ = _service()
        tray = service.change_status(
            vehicle_id="vehicle-1",
            workstream="tray",
            new_status="ready",
            actor=_actor(AppRole.SHOP_EDITOR),
            request_id="tray-ready",
            source_client="builder_desktop",
        )
        programming = service.change_status(
            vehicle_id="vehicle-1",
            workstream="programming_qc",
            new_status="ready",
            actor=_actor(AppRole.PROGRAMMING_QC_EDITOR),
            request_id="programming-ready",
            source_client="builder_desktop",
        )

        assert tray.record.shop_status == ""
        assert programming.record.shop_status == ""
        assert programming.record.programming_qc_ready_at == NOW_ISO

    def test_parts_ordered_is_a_dated_normal_milestone(self):
        service, _, _ = _service()
        ordered = service.change_status(
            vehicle_id="vehicle-1",
            workstream="parts",
            new_status="ordered",
            actor=_actor(AppRole.PARTS_EDITOR),
            request_id="parts-ordered",
            source_client="builder_desktop",
        )
        partial = service.change_status(
            vehicle_id="vehicle-1",
            workstream="parts",
            new_status="partially_received",
            actor=_actor(AppRole.PARTS_EDITOR),
            request_id="parts-partial",
            source_client="builder_desktop",
            expected_revision=ordered.record.revision,
        )

        assert ordered.record.parts_status == "ordered"
        assert ordered.record.parts_ordered_at == NOW_ISO
        assert partial.record.parts_ordered_at == NOW_ISO
        assert partial.record.parts_partially_received_at == NOW_ISO

    def test_parts_can_receive_one_complete_shipment_without_partial_state(self):
        service, _, _ = _service()
        result = service.change_status(
            vehicle_id="vehicle-1",
            workstream="parts",
            new_status="received",
            actor=_actor(AppRole.PARTS_EDITOR),
            request_id="parts-received",
            source_client="builder_desktop",
        )

        assert result.record.parts_status == "received"
        assert result.record.parts_received_at == NOW_ISO
        assert result.record.parts_partially_received_at == ""

    def test_parts_ready_implies_received_when_earlier_step_was_skipped(self):
        service, _, _ = _service()
        result = service.change_status(
            vehicle_id="vehicle-1",
            workstream="parts",
            new_status="parts_ready",
            actor=_actor(AppRole.APP_ADMIN),
            request_id="parts-ready-direct",
            source_client="builder_desktop",
            correction_reason="Imported current state",
        )

        assert result.record.parts_ready_at == NOW_ISO
        assert result.record.parts_received_at == NOW_ISO

    def test_vehicle_availability_can_be_backdated_and_drives_delivery_date(self):
        service, repository, _ = _service()
        available = service.change_vehicle_availability(
            vehicle_id="vehicle-1",
            new_status="ready_for_pickup",
            effective_date="2026-08-31",
            actor=_actor(AppRole.BUILDER_EDITOR),
            request_id="vehicle-available",
            source_client="builder_desktop",
        )
        received = service.change_status(
            vehicle_id="vehicle-1",
            workstream="parts",
            new_status="received",
            actor=_actor(AppRole.PARTS_EDITOR),
            request_id="parts-received",
            source_client="builder_desktop",
        )

        assert available.record.vehicle_available_date == "2026-08-31"
        assert repository.list_events("vehicle-1")[1].effective_date == "2026-08-31"
        assert received.record.commitment_start_date == "2026-09-03"
        assert received.record.must_deliver_by_date == "2026-11-02"

    def test_delivered_availability_requires_audited_correction_to_reopen(self):
        """Legacy availability=delivered records remain correctable and readable."""
        service, repository, _ = _service()
        legacy = repository.get_vehicle("vehicle-1")
        legacy.vehicle_availability_status = VehicleAvailabilityStatus.DELIVERED
        legacy.delivered_date = "2026-09-02"
        repository._records["vehicle-1"] = legacy  # noqa: SLF001 - legacy fixture

        with pytest.raises(OperationsAuthorizationError, match="operations.correct"):
            service.change_vehicle_availability(
                vehicle_id="vehicle-1", new_status="at_dtm",
                actor=_actor(AppRole.BUILDER_EDITOR), request_id="reopen-denied",
                source_client="builder_desktop", correction_reason="Wrong vehicle",
            )

        reopened = service.change_vehicle_availability(
            vehicle_id="vehicle-1", new_status="at_dtm",
            actor=_actor(AppRole.OPERATIONS_MANAGER), request_id="reopen",
            source_client="builder_desktop", correction_reason="Wrong vehicle",
        )
        assert reopened.record.delivered_date == ""

    def test_new_delivery_cannot_be_written_to_vehicle_availability(self):
        service, _, _ = _service()

        with pytest.raises(OperationsValidationError, match="Final Finish"):
            service.change_vehicle_availability(
                vehicle_id="vehicle-1", new_status="delivered",
                actor=_actor(AppRole.OPERATIONS_MANAGER), request_id="wrong-stream-delivery",
                source_client="builder_desktop",
            )

    def test_final_finish_delivery_stamps_date_and_requires_correction_to_reopen(self):
        service, _, _ = _service()
        ready_to_clean = service.change_status(
            vehicle_id="vehicle-1", workstream="final_finish",
            new_status="ready_for_wash_clean_photos",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="finish-clean",
            source_client="builder_desktop",
        )
        ready_to_deliver = service.change_status(
            vehicle_id="vehicle-1", workstream="final_finish",
            new_status="ready_for_delivery",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="finish-ready",
            source_client="builder_desktop",
            expected_revision=ready_to_clean.record.revision,
        )
        delivered = service.change_status(
            vehicle_id="vehicle-1", workstream="final_finish",
            new_status="delivered",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="finish-delivered",
            source_client="builder_desktop",
            expected_revision=ready_to_deliver.record.revision,
        )

        assert delivered.record.final_finish_status.value == "delivered"
        assert delivered.record.delivered_date == "2026-09-03"

        with pytest.raises(OperationsAuthorizationError, match="operations.correct"):
            service.change_status(
                vehicle_id="vehicle-1", workstream="final_finish",
                new_status="ready_for_delivery",
                actor=_actor(AppRole.SHOP_EDITOR), request_id="finish-reopen-denied",
                source_client="builder_desktop",
                expected_revision=delivered.record.revision,
                correction_reason="Delivery was recorded on the wrong unit",
            )

        reopened = service.change_status(
            vehicle_id="vehicle-1", workstream="final_finish",
            new_status="ready_for_delivery",
            actor=_actor(AppRole.OPERATIONS_MANAGER), request_id="finish-reopen",
            source_client="builder_desktop",
            expected_revision=delivered.record.revision,
            correction_reason="Delivery was recorded on the wrong unit",
        )
        assert reopened.record.delivered_date == ""

    def test_availability_effective_date_correction_preserves_status(self):
        service, repository, _ = _service()
        service.change_vehicle_availability(
            vehicle_id="vehicle-1", new_status="ready_for_pickup",
            effective_date="2026-09-01", actor=_actor(AppRole.BUILDER_EDITOR),
            request_id="available", source_client="builder_desktop",
        )
        corrected = service.change_vehicle_availability(
            vehicle_id="vehicle-1", new_status="ready_for_pickup",
            effective_date="2026-08-31", actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="correct-date", source_client="builder_desktop",
            correction_reason="Dealer confirmed the earlier date",
        )

        assert corrected.record.vehicle_availability_status.value == "ready_for_pickup"
        assert corrected.record.vehicle_available_date == "2026-08-31"
        assert repository.list_events("vehicle-1")[-1].previous_value == "2026-09-01"

    def test_invalid_forward_skip_requires_correction_permission_and_reason(self):
        service, _, _ = _service()

        with pytest.raises(OperationsAuthorizationError, match="operations.correct"):
            service.change_status(
                vehicle_id="vehicle-1",
                workstream="shop",
                new_status="complete",
                actor=_actor(AppRole.SHOP_EDITOR),
                request_id="bad-skip",
                source_client="builder_desktop",
                correction_reason="Imported already-complete work",
            )

        with pytest.raises(OperationsValidationError, match="reason"):
            service.change_status(
                vehicle_id="vehicle-1",
                workstream="shop",
                new_status="complete",
                actor=_actor(AppRole.OPERATIONS_MANAGER),
                request_id="missing-reason",
                source_client="builder_desktop",
            )

    def test_authorized_regression_clears_current_cycle_date_but_keeps_history(self):
        service, repository, _ = _service()
        service.change_status(
            vehicle_id="vehicle-1", workstream="tray", new_status="ready",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="tray-ready",
            source_client="builder_desktop",
        )
        service.change_status(
            vehicle_id="vehicle-1", workstream="tray", new_status="complete",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="tray-complete",
            source_client="builder_desktop",
        )
        corrected = service.change_status(
            vehicle_id="vehicle-1", workstream="tray", new_status="ready",
            actor=_actor(AppRole.OPERATIONS_MANAGER), request_id="tray-correction",
            source_client="builder_desktop", correction_reason="Completed by mistake",
        )

        assert corrected.record.tray_status.value == "ready"
        assert corrected.record.tray_completed_at == ""
        events = repository.list_events("vehicle-1")
        assert events[-2].new_value == "complete"
        assert events[-1].reason == "Completed by mistake"

    def test_duplicate_request_is_idempotent(self):
        service, repository, _ = _service()
        first = service.change_status(
            vehicle_id="vehicle-1", workstream="shop", new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="same-request",
            source_client="builder_desktop",
        )
        duplicate = service.change_status(
            vehicle_id="vehicle-1", workstream="shop", new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="same-request",
            source_client="builder_desktop",
        )

        assert first.duplicate is False
        assert duplicate.duplicate is True
        assert duplicate.event.event_id == first.event.event_id
        assert len(repository.list_events("vehicle-1")) == 2

    def test_stale_expected_revision_is_rejected(self):
        service, _, _ = _service()
        service.change_status(
            vehicle_id="vehicle-1", workstream="shop", new_status="in_progress",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="shop-start",
            source_client="builder_desktop", expected_revision=0,
        )

        with pytest.raises(OperationsConflictError, match="Expected revision 0"):
            service.change_status(
                vehicle_id="vehicle-1", workstream="tray", new_status="ready",
                actor=_actor(AppRole.SHOP_EDITOR), request_id="stale",
                source_client="builder_desktop", expected_revision=0,
            )

    def test_wrong_role_cannot_change_parts(self):
        service, _, _ = _service()
        with pytest.raises(OperationsAuthorizationError, match="parts.update"):
            service.change_status(
                vehicle_id="vehicle-1", workstream="parts", new_status="received",
                actor=_actor(AppRole.SHOP_EDITOR), request_id="wrong-role",
                source_client="builder_desktop",
            )

    def test_same_status_is_noop_without_event(self):
        service, repository, _ = _service()
        result = service.change_status(
            vehicle_id="vehicle-1", workstream="tray", new_status="not_ready",
            actor=_actor(AppRole.SHOP_EDITOR), request_id="same-state",
            source_client="builder_desktop",
        )

        assert result.unchanged is True
        assert result.event is None
        assert len(repository.list_events("vehicle-1")) == 1


class TestAcceptance:
    def test_acceptance_stamps_source_and_is_summarized(self):
        service, _, _ = _service()
        result = service.change_acceptance(
            vehicle_id="vehicle-1",
            new_status=AcceptanceStatus.ACCEPTED,
            acceptance_source=AcceptanceSource.QBO,
            actor=_actor(AppRole.BUILDER_EDITOR),
            request_id="accepted",
            source_client="builder_desktop",
        )

        assert result.record.accepted_at == NOW_ISO
        assert result.record.acceptance_source == "qbo"
        assert project_acceptance_tag([AcceptanceStatus.ACCEPTED]) == ProjectAcceptanceTag.ACCEPTED
        assert project_acceptance_tag([
            AcceptanceStatus.ACCEPTED,
            AcceptanceStatus.NOT_ACCEPTED,
        ]) == ProjectAcceptanceTag.PARTIALLY_ACCEPTED
        assert project_acceptance_tag([]) == ProjectAcceptanceTag.NOT_ACCEPTED

    def test_reversing_acceptance_is_an_audited_correction(self):
        service, repository, _ = _service()
        service.change_acceptance(
            vehicle_id="vehicle-1", new_status="accepted", acceptance_source="manual",
            actor=_actor(AppRole.BUILDER_EDITOR), request_id="accept",
            source_client="builder_desktop",
        )

        with pytest.raises(OperationsAuthorizationError, match="operations.correct"):
            service.change_acceptance(
                vehicle_id="vehicle-1", new_status="not_accepted",
                acceptance_source="manual", actor=_actor(AppRole.BUILDER_EDITOR),
                request_id="reverse-denied", source_client="builder_desktop",
                correction_reason="Customer rescinded acceptance",
            )

        corrected = service.change_acceptance(
            vehicle_id="vehicle-1", new_status="not_accepted",
            acceptance_source="manual", actor=_actor(AppRole.APP_ADMIN),
            request_id="reverse", source_client="builder_desktop",
            correction_reason="Acceptance was attached to the wrong unit",
        )
        assert corrected.record.accepted_at == ""
        assert repository.list_events("vehicle-1")[-1].reason


class TestScheduling:
    @staticmethod
    def _accepted_service():
        service, repository, _ = _service()
        accepted = service.change_acceptance(
            vehicle_id="vehicle-1",
            new_status="accepted",
            acceptance_source="manual",
            actor=_actor(AppRole.BUILDER_EDITOR),
            request_id="accept-for-schedule",
            source_client="builder_desktop",
            expected_revision=0,
        )
        return service, repository, accepted.record

    def test_schedule_sets_dates_timestamp_bucket_and_history(self):
        service, repository, accepted = self._accepted_service()

        result = service.change_schedule(
            vehicle_id="vehicle-1",
            scheduled_week_of="2026-09-07",
            planned_start_date="2026-09-08",
            target_finish_date="2026-09-18",
            actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="schedule-1",
            source_client="builder_desktop",
            expected_revision=accepted.revision,
        )

        assert result.record.scheduled_week_of == "2026-09-07"
        assert result.record.planned_start_date == "2026-09-08"
        assert result.record.target_finish_date == "2026-09-18"
        assert result.record.schedule_changed_at == NOW_ISO
        assert schedule_bucket(result.record) == ScheduleBucket.SCHEDULED
        assert result.event.workstream == OperationsWorkstream.SCHEDULE
        assert '"scheduled_week_of":"2026-09-07"' in result.event.new_value
        assert len(repository.list_events("vehicle-1")) == 3

    def test_clearing_schedule_returns_vehicle_to_unscheduled(self):
        service, _, accepted = self._accepted_service()
        scheduled = service.change_schedule(
            vehicle_id="vehicle-1",
            scheduled_week_of="2026-09-07",
            planned_start_date="",
            target_finish_date="",
            actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="schedule-first",
            source_client="builder_desktop",
            expected_revision=accepted.revision,
        )

        cleared = service.change_schedule(
            vehicle_id="vehicle-1",
            scheduled_week_of="",
            planned_start_date="",
            target_finish_date="",
            actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="schedule-clear",
            source_client="builder_desktop",
            expected_revision=scheduled.record.revision,
        )

        assert cleared.record.scheduled_week_of == ""
        assert schedule_bucket(cleared.record) == ScheduleBucket.UNSCHEDULED

    def test_schedule_is_a_partial_edit_and_does_not_require_acceptance(self):
        service, _, record = _service()
        first = service.change_schedule(
            vehicle_id="vehicle-1",
            planned_start_date="2026-09-08",
            actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="planned-only",
            source_client="builder_desktop",
            expected_revision=record.revision,
        )
        second = service.change_schedule(
            vehicle_id="vehicle-1",
            target_finish_date="2026-09-01",
            actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="finish-only",
            source_client="builder_desktop",
            expected_revision=first.record.revision,
        )

        assert second.record.planned_start_date == "2026-09-08"
        assert second.record.target_finish_date == "2026-09-01"
        assert second.record.scheduled_week_of == ""
        assert schedule_bucket(second.record) == ScheduleBucket.PROSPECTIVE

    def test_schedule_rejects_only_malformed_dates_and_requires_capability(self):
        service, _, record = _service()
        with pytest.raises(OperationsValidationError, match="At least one"):
            service.change_schedule(
                vehicle_id="vehicle-1",
                actor=_actor(AppRole.OPERATIONS_MANAGER),
                request_id="no-fields",
                source_client="builder_desktop",
                expected_revision=record.revision,
            )
        with pytest.raises(OperationsValidationError, match="ISO date"):
            service.change_schedule(
                vehicle_id="vehicle-1",
                planned_start_date="September 8",
                actor=_actor(AppRole.OPERATIONS_MANAGER),
                request_id="bad-date",
                source_client="builder_desktop",
                expected_revision=record.revision,
            )
        with pytest.raises(OperationsAuthorizationError, match="schedule.update"):
            service.change_schedule(
                vehicle_id="vehicle-1",
                scheduled_week_of="2026-09-07",
                planned_start_date="",
                target_finish_date="",
                actor=_actor(AppRole.SHOP_EDITOR),
                request_id="wrong-role",
                source_client="builder_desktop",
                expected_revision=record.revision,
            )

    def test_manual_must_deliver_date_overrides_and_can_return_to_automatic(self):
        service, _, record = _service()
        available = service.change_vehicle_availability(
            vehicle_id="vehicle-1",
            new_status="at_dtm",
            effective_date="2026-09-01",
            actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="at-dtm",
            source_client="builder_desktop",
            expected_revision=record.revision,
        )
        ready = service.change_status(
            vehicle_id="vehicle-1",
            workstream="parts",
            new_status="parts_ready",
            actor=_actor(AppRole.APP_ADMIN),
            request_id="parts-ready",
            source_client="builder_desktop",
            correction_reason="Imported current state",
            expected_revision=available.record.revision,
        )
        automatic = ready.record.must_deliver_by_date
        overridden = service.change_schedule(
            vehicle_id="vehicle-1",
            must_deliver_override_date="2026-12-15",
            actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="manual-deadline",
            source_client="builder_desktop",
            expected_revision=ready.record.revision,
        )
        restored = service.change_schedule(
            vehicle_id="vehicle-1",
            must_deliver_override_date="",
            actor=_actor(AppRole.OPERATIONS_MANAGER),
            request_id="automatic-deadline",
            source_client="builder_desktop",
            expected_revision=overridden.record.revision,
        )

        assert overridden.record.must_deliver_override_date == "2026-12-15"
        assert overridden.record.must_deliver_by_date == "2026-12-15"
        assert restored.record.must_deliver_override_date == ""
        assert restored.record.must_deliver_by_date == automatic
