from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.adapters.memory_operations_repository import (
    InMemoryOperationsRepository,
)
from dtm_buildsheet.app.adapters.wiring import build_local_bundle, set_active_bundle
from dtm_buildsheet.app.routes.projects import route_projects
from dtm_buildsheet.domain.project_models import (
    BuildUnit,
    CustomerInfo,
    IndividualUnit,
    ProjectRecord,
)
from dtm_buildsheet.paths import AppPaths
from tests.contract.harness import call_route


@pytest.fixture(autouse=True)
def _reset_bundle():
    yield
    wiring._active_bundle = None  # noqa: SLF001


def _paths(tmp_path) -> AppPaths:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=projects_dir,
        workspace_drafts_dir=tmp_path / "drafts",
        workspace_output_dir=tmp_path / "output",
    )


def _project() -> ProjectRecord:
    return ProjectRecord(
        project_id="project-1",
        created_at="2026-09-08T12:00:00+00:00",
        updated_at="2026-09-08T12:00:00+00:00",
        customer=CustomerInfo(
            agency="Example PD",
            agency_abbreviation="EPD",
            build_year="2027",
        ),
        build_units=[BuildUnit(
            unit_id="group-1",
            vehicle_model="PIU",
            build_type="Patrol",
            quantity=1,
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                unit_number="21",
                vin="1FTFW1E50NFA12345",
            )],
        )],
    )


def test_project_routes_sync_lifecycle_and_cascade_delete(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    repository = InMemoryOperationsRepository()
    set_active_bundle(replace(
        build_local_bundle(),
        operations=repository,
        operations_writer=repository,
    ))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: False)

    status, payload, handled = call_route(
        route_projects,
        "POST",
        "/api/project/save",
        asdict(_project()),
        paths,
    )
    assert (status, handled) == (200, True)
    assert payload["operations_sync"]["created"] == 1
    assert repository.get_vehicle("vehicle-1").project_id == "project-1"

    status, payload, handled = call_route(
        route_projects,
        "POST",
        "/api/project/project-1/lifecycle",
        {"status": "inactive", "reason": "Waiting on customer"},
        paths,
    )
    assert (status, handled) == (200, True)
    assert payload["operations_sync"]["updated"] == 1
    assert repository.get_vehicle("vehicle-1").project_state.value == "inactive"

    status, payload, handled = call_route(
        route_projects,
        "POST",
        "/api/project/project-1/delete",
        {"delete_files": False},
        paths,
    )
    assert (status, handled) == (200, True)
    assert payload["ok"] is True
    assert payload["operations_sync"]["records_deleted"] == 1
    assert payload["operations_sync"]["events_deleted"] == 2
    assert repository.get_vehicle("vehicle-1") is None
    assert not (paths.workspace_projects_dir / "project-1" / "project.json").exists()


def test_project_completion_merge_rebinds_operations_and_preserves_vehicle_history(
    monkeypatch, tmp_path,
):
    paths = _paths(tmp_path)
    repository = InMemoryOperationsRepository()
    set_active_bundle(replace(
        build_local_bundle(),
        operations=repository,
        operations_writer=repository,
    ))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: False)

    completed = _project()
    status, payload, handled = call_route(
        route_projects, "POST", "/api/project/save", asdict(completed), paths,
    )
    assert (status, handled, payload["ok"]) == (200, True, True)
    status, payload, handled = call_route(
        route_projects,
        "POST",
        "/api/project/project-1/completion",
        {"completed": True},
        paths,
    )
    assert (status, handled, payload["ok"]) == (200, True, True)

    active = _project()
    active.project_id = "project-2"
    active.build_units[0].unit_id = "group-2"
    active.build_units[0].individuals[0].individual_id = "vehicle-2"
    active.build_units[0].individuals[0].unit_number = "22"
    status, payload, handled = call_route(
        route_projects, "POST", "/api/project/save", asdict(active), paths,
    )
    assert (status, handled, payload["ok"]) == (200, True, True)
    assert repository.get_vehicle("vehicle-2").project_id == "project-2"

    status, conflict, handled = call_route(
        route_projects,
        "POST",
        "/api/project/project-2/completion",
        {"completed": True},
        paths,
    )
    assert (status, handled) == (200, True)
    assert conflict["error_code"] == "completed_project_exists_for_agency_year"

    status, merged, handled = call_route(
        route_projects,
        "POST",
        "/api/project/project-2/completion",
        {"completed": True, "conflict_resolution": "merge"},
        paths,
    )

    assert (status, handled, merged["ok"]) == (200, True, True)
    assert merged["operations_sync"]["synchronized"]["updated"] == 1
    assert repository.get_vehicle("vehicle-2").project_id == "project-1"
    assert repository.get_vehicle("vehicle-2").project_state.value == "completed"
    assert len(repository.list_events("vehicle-2")) == 2


def test_project_completion_overwrite_removes_old_operations_and_keeps_replacement(
    monkeypatch, tmp_path,
):
    paths = _paths(tmp_path)
    repository = InMemoryOperationsRepository()
    set_active_bundle(replace(
        build_local_bundle(),
        operations=repository,
        operations_writer=repository,
    ))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: False)

    completed = _project()
    status, payload, handled = call_route(
        route_projects, "POST", "/api/project/save", asdict(completed), paths,
    )
    assert (status, handled, payload["ok"]) == (200, True, True)
    status, payload, handled = call_route(
        route_projects,
        "POST",
        "/api/project/project-1/completion",
        {"completed": True},
        paths,
    )
    assert (status, handled, payload["ok"]) == (200, True, True)
    assert len(repository.list_events("vehicle-1")) == 2

    active = _project()
    active.project_id = "project-2"
    active.build_units[0].unit_id = "group-2"
    active.build_units[0].individuals[0].individual_id = "vehicle-2"
    active.build_units[0].individuals[0].unit_number = "22"
    status, payload, handled = call_route(
        route_projects, "POST", "/api/project/save", asdict(active), paths,
    )
    assert (status, handled, payload["ok"]) == (200, True, True)

    status, overwritten, handled = call_route(
        route_projects,
        "POST",
        "/api/project/project-2/completion",
        {
            "completed": True,
            "conflict_resolution": "overwrite",
            "overwrite_confirmation": "OVERWRITE",
        },
        paths,
    )

    assert (status, handled, overwritten["ok"]) == (200, True, True)
    removed = overwritten["operations_sync"]["removed_completed_project"]
    assert removed == {"ok": True, "records_deleted": 1, "events_deleted": 2}
    assert repository.get_vehicle("vehicle-1") is None
    assert repository.list_events("vehicle-1") == []
    replacement = repository.get_vehicle("vehicle-2")
    assert replacement.project_id == "project-1"
    assert replacement.project_state.value == "completed"
    assert len(repository.list_events("vehicle-2")) == 2
