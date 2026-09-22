from dataclasses import replace
from datetime import date

from dtm_buildsheet.app.adapters.memory_operations_repository import (
    InMemoryOperationsRepository,
)
from dtm_buildsheet.app.adapters.wiring import build_local_bundle
from dtm_buildsheet.app.services.calendar_service import CalendarService
from dtm_buildsheet.app.services.calendar_workspace import CalendarWorkspace
from dtm_buildsheet.app.services.operations_read_service import OperationsReadService
from dtm_buildsheet.domain.operations_models import (
    AcceptanceStatus,
    OperationsActor,
    VehicleOperations,
)
from dtm_buildsheet.domain.project_models import (
    BuildUnit,
    CustomerInfo,
    IndividualUnit,
    ProjectRecord,
)
from dtm_buildsheet.domain.operations_policy import AppRole
from dtm_buildsheet.inputs.project_entry import load_project, save_project
from dtm_buildsheet.paths import AppPaths


ACTOR = OperationsActor(
    user_id="owner",
    display_name="Owner",
    roles=frozenset({AppRole.APP_ADMIN.value}),
)


def _paths(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    return replace(
        AppPaths(),
        workspace_dir=tmp_path,
        workspace_projects_dir=projects,
        workspace_drafts_dir=tmp_path / "drafts",
        workspace_output_dir=tmp_path / "output",
    )


def _project(agency_name="Old County Sheriff"):
    return ProjectRecord(
        project_id="project-1",
        created_at="2026-09-01T12:00:00+00:00",
        updated_at="2026-09-01T12:00:00+00:00",
        customer=CustomerInfo(
            agency=agency_name,
            agency_id="agency-1",
            agency_abbreviation="OCSO",
            build_year="2027",
        ),
        build_units=[BuildUnit(
            unit_id="build-1",
            vehicle_model="PIU",
            build_type="Patrol",
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                unit_number="21",
                vin="1FM5K8AC0SGB12345",
            )],
        )],
    )


def _stale_operations_record():
    return VehicleOperations(
        vehicle_id="vehicle-1",
        project_id="project-1",
        title="2027 OCSO PIU - Patrol - Unit 21 - VIN B12345",
        agency_id="agency-1",
        agency_name="Old County Sheriff",
        build_year="2027",
        unit_number="21",
        vin="1FM5K8AC0SGB12345",
        acceptance_status=AcceptanceStatus.ACCEPTED,
        accepted_at="2026-09-01T12:00:00Z",
    )


def test_operations_reads_agency_name_from_current_builder_project(tmp_path):
    paths = _paths(tmp_path)
    project = _project("Old County Sheriff's Office")
    save_project(project, paths)
    repository = InMemoryOperationsRepository()
    repository._records["vehicle-1"] = _stale_operations_record()  # noqa: SLF001

    payload = OperationsReadService(repository).list_vehicle_summaries(
        ACTOR, projects=[load_project("project-1", paths)],
    )

    assert payload["vehicles"][0]["agency_name"] == "Old County Sheriff's Office"
    assert repository.get_vehicle("vehicle-1").agency_name == "Old County Sheriff"


def test_calendar_cached_rows_use_current_builder_agency_name(tmp_path):
    paths = _paths(tmp_path)
    project = _project()
    save_project(project, paths)
    repository = InMemoryOperationsRepository()
    repository._records["vehicle-1"] = _stale_operations_record()  # noqa: SLF001
    bundle = replace(
        build_local_bundle(),
        operations=repository,
        operations_writer=repository,
    )
    service = CalendarService(paths, bundle, clock=lambda: date(2026, 9, 21))
    workspace = CalendarWorkspace(service, ACTOR, tmp_path / "calendar-cache.json")

    project.customer.agency = "Old County Sheriff's Office"
    save_project(project, paths)
    payload = workspace._payload()  # noqa: SLF001 - exercise stale cache read path
    rows = payload["plan"]["queue"] + payload["plan"]["needs_review"]

    assert next(row for row in rows if row["id"] == "vehicle-1")["agency_name"] == (
        "Old County Sheriff's Office"
    )
    assert workspace.state["records"][0]["agency_name"] == "Old County Sheriff"

    body = {
        "revision": payload["revision"],
        "source_revision": payload["source_revision"],
        "edit": {
            "id": "vehicle-1",
            "team_id": "team-david",
            "start_date": "2026-09-21",
        },
        "reason": "Regression test",
    }
    preview = workspace.preview(body)
    workspace.kick = lambda **_kwargs: None
    workspace.commit({
        **body,
        "preview_token": preview["preview_token"],
        "request_id": "calendar-save-1",
    })

    assert workspace.state["pending"][0]["sources"][0]["agency_name"] == (
        "Old County Sheriff's Office"
    )
