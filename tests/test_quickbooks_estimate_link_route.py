from __future__ import annotations

from dataclasses import replace

import pytest

from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.adapters.memory_operations_repository import (
    InMemoryOperationsRepository,
)
from dtm_buildsheet.app.adapters.wiring import build_local_bundle, set_active_bundle
from dtm_buildsheet.app.routes.quickbooks import route_quickbooks
from dtm_buildsheet.app.services import qb_estimate_service
from dtm_buildsheet.app.services.operations_service import OperationsService
from dtm_buildsheet.domain.operations_models import OperationsActor
from dtm_buildsheet.domain.operations_policy import AppRole
from dtm_buildsheet.paths import AppPaths
from tests.contract.harness import call_route


@pytest.fixture(autouse=True)
def _reset_bundle():
    yield
    wiring._active_bundle = None  # noqa: SLF001


def test_connect_existing_estimate_writes_safe_shared_observation(monkeypatch, tmp_path):
    repository = InMemoryOperationsRepository()
    set_active_bundle(replace(
        build_local_bundle(),
        operations=repository,
        operations_writer=repository,
    ))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: False)
    actor = OperationsActor(
        user_id="seed",
        display_name="Seed User",
        roles=frozenset({AppRole.APP_ADMIN.value}),
    )
    OperationsService(repository).create_vehicle(
        vehicle_id="vehicle-1",
        project_id="project-1",
        actor=actor,
        request_id="seed-vehicle",
        source_client="builder_desktop",
    )
    monkeypatch.setattr(qb_estimate_service, "bind_estimate", lambda *args, **kwargs: {
        "ok": True,
        "linked": True,
        "qb_estimate_id": "98765",
        "estimate_number": "2041",
        "estimate_status": "Accepted",
        "observation": {
            "qbo_project_id": "447322633",
            "qbo_project_name": "2026 Tahoe | Patrol | Unit 21",
            "qbo_estimate_id": "98765",
            "qbo_estimate_number": "2041",
            "qbo_estimate_status": "Accepted",
            "qbo_estimate_accepted_at": "2026-09-08T18:00:00Z",
            "qbo_estimate_last_modified_at": "2026-09-08T18:15:00Z",
            "qbo_diff_status": "unchanged",
        },
    })

    status, payload, handled = call_route(
        route_quickbooks,
        "POST",
        "/api/quickbooks/estimates/bind",
        {
            "project_id": "project-1",
            "individual_id": "vehicle-1",
            "qb_estimate_id": "98765",
        },
        AppPaths(workspace_dir=tmp_path),
    )

    assert (status, handled, payload["ok"]) == (200, True, True)
    assert payload["operations_sync"]["ok"] is True
    shared = repository.get_vehicle("vehicle-1")
    assert shared.qbo_estimate_id == "98765"
    assert shared.qbo_estimate_number == "2041"
    assert shared.qbo_estimate_status == "Accepted"
    assert shared.acceptance_status.value == "accepted"
    assert shared.acceptance_source == "qbo"
    assert len(repository.list_events("vehicle-1")) == 2
