from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from dtm_buildsheet.app.adapters.memory_operations_repository import InMemoryOperationsRepository
from dtm_buildsheet.app.adapters.quickbooks.api_client import _disambiguate_customer_names
from dtm_buildsheet.app.services import (
    agency_service,
    qb_customer_migration_service,
    qb_estimate_service,
    qb_sync_service,
)
from dtm_buildsheet.app.services.operations_read_service import OperationsReadService
from dtm_buildsheet.app.services.project_service import (
    handle_list_projects,
    handle_save_individual_notes,
    handle_save_project,
)
from dtm_buildsheet.app.services.sales_rep_service import handle_save_rep
from dtm_buildsheet.domain.operations_models import OperationsActor, VehicleOperations
from dtm_buildsheet.domain.operations_policy import AppRole
from dtm_buildsheet.domain.project_codec import project_from_dict
from dtm_buildsheet.domain.project_models import BuildUnit, CustomerInfo, IndividualUnit
from dtm_buildsheet.inputs import project_entry
from dtm_buildsheet.inputs.project_drafts import load_draft, new_draft, save_draft
from dtm_buildsheet.paths import AppPaths


@pytest.fixture
def paths(tmp_path):
    for name in ("config", "projects", "drafts", "agencies", "sales_reps", "output"):
        (tmp_path / name).mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_config_dir=tmp_path / "config",
        workspace_projects_dir=tmp_path / "projects",
        workspace_drafts_dir=tmp_path / "drafts",
        workspace_output_dir=tmp_path / "output",
    )


@pytest.fixture(autouse=True)
def no_cloud(monkeypatch):
    from dtm_buildsheet.app.services import shared_work_service

    monkeypatch.setattr(shared_work_service, "save_setting_to_cloud_in_background", lambda *a, **k: None)
    monkeypatch.setattr(shared_work_service, "save_settings_to_cloud_batch_in_background", lambda *a, **k: None)
    monkeypatch.setattr(shared_work_service, "mirror_project_to_cloud_in_background", lambda *a, **k: None)
    monkeypatch.setattr(shared_work_service, "delete_setting_from_cloud", lambda *a, **k: True)
    monkeypatch.setattr(qb_sync_service, "push_agency_after_save", lambda *a, **k: {"ok": True})


def test_codec_round_trips_laptop_and_project_estimate():
    project = project_from_dict({
        "project_id": "p1",
        "created_at": "now",
        "updated_at": "now",
        "preferences": {"laptop_make": "Panasonic", "laptop_model": "Toughbook 55"},
        "project_quote_references": [{
            "reference_id": "r1", "quote_number": "26-100", "qb_estimate_id": "100",
            "match_status": "linked",
        }],
    })
    assert (project.preferences.laptop_make, project.preferences.laptop_model) == (
        "Panasonic", "Toughbook 55",
    )
    assert project.project_quote_references[0].qb_estimate_id == "100"


def test_agency_review_suggests_standard_and_detects_canonical_duplicate(paths):
    created = agency_service.handle_save_agency({
        "name": "Hubbard County Sheriff's Office", "naming_override": True,
    }, paths)
    assert created["ok"]
    review = agency_service.review_agency_name("Hubbard County Sheriff", paths)
    assert review["suggested_name"] == "Hubbard County Sheriff's Office"
    assert review["requires_acknowledgement"]
    assert "Hubbard County Sheriff's Office" in review["possible_matches"] or any(
        "already matches" in warning for warning in review["warnings"]
    )


def test_agency_review_treats_bare_county_as_sheriffs_office(paths):
    review = agency_service.review_agency_name("Fergus County", paths)

    assert review["requires_acknowledgement"] is True
    assert review["suggested_name"] == "Fergus County Sheriff's Office"
    assert any("normally means" in warning for warning in review["warnings"])


def test_qbo_customers_with_same_company_use_unique_display_names():
    customers = [
        {"qb_customer_id": "38", "name": "Minnesota State Patrol", "display_name": "Minnesota State Patrol 2600"},
        {"qb_customer_id": "39", "name": "Minnesota State Patrol", "display_name": "Minnesota State Patrol 2400"},
        {"qb_customer_id": "88", "name": "Minnesota State Patrol", "display_name": "Minnesota State Patrol 4700"},
    ]

    assert [item["name"] for item in _disambiguate_customer_names(customers)] == [
        "Minnesota State Patrol 2600",
        "Minnesota State Patrol 2400",
        "Minnesota State Patrol 4700",
    ]


def test_reviewed_state_patrol_posts_are_not_filtered_as_duplicates(paths):
    (paths.workspace_dir / "quickbooks_customer_migration_state.json").write_text(json.dumps({
        "status": "complete",
        "ignored_duplicate_customer_ids": ["38", "88", "407"],
    }))

    assert qb_customer_migration_service.ignored_production_customer_ids(paths) == {"407"}


def test_builder_agency_merge_rebinds_projects_without_losing_them(paths):
    source = agency_service.handle_save_agency({"name": "Hubbard County Sheriff"}, paths)["agency"]
    target = agency_service.handle_save_agency({
        "name": "Hubbard County Sheriff's Office", "naming_override": True,
    }, paths)["agency"]
    agency_service.set_qb_customer_id(paths, target["agency_id"], "survivor-qb-id")
    project = project_entry.new_project(
        customer=CustomerInfo(
            agency_id=source["agency_id"], agency=source["name"], build_year="2026",
        ),
        build_units=[BuildUnit(unit_id="g1", individuals=[IndividualUnit(individual_id="v1")])],
    )
    project_entry.save_project(project, paths)

    merged = agency_service.handle_merge_agencies({
        "source_agency_id": source["agency_id"],
        "target_agency_id": target["agency_id"],
    }, paths)

    assert merged["ok"]
    saved = project_entry.load_project(project.project_id, paths)
    assert saved.customer.agency_id == target["agency_id"]
    assert saved.customer.agency == "Hubbard County Sheriff's Office"
    assert agency_service.get_agency(paths, source["agency_id"]) is None


def test_project_form_requires_real_agency_and_sales_rep_selection(paths):
    rejected = handle_save_project({
        "require_selected_identities": True,
        "customer": {"agency": "Typed Agency", "sales_rep": "Typed Rep", "build_year": "2026"},
    }, paths)
    assert rejected["error_code"] == "agency_selection_required"

    agency = agency_service.handle_save_agency({"name": "Example Police Department"}, paths)["agency"]
    rep = handle_save_rep({"name": "Alex Rep", "phone": "555-0100", "email": "alex@example.com"}, paths)["rep"]
    saved = handle_save_project({
        "require_selected_identities": True,
        "customer": {
            "agency": "forged label", "agency_id": agency["agency_id"],
            "sales_rep": "forged label", "sales_rep_id": rep["rep_id"],
            "build_year": "2026",
        },
    }, paths)
    assert saved["ok"]
    project = project_entry.load_project(saved["project_id"], paths)
    assert project.customer.agency == "Example Police Department"
    assert project.customer.sales_rep == "Alex Rep"
    duplicate = handle_save_rep({
        "name": " alex rep ", "phone": "555-0199", "email": "other@example.com",
    }, paths)
    assert duplicate["error_code"] == "sales_rep_already_exists"


def test_unit_notes_update_project_and_draft_without_losing_paragraphs(paths):
    draft = new_draft(notes={"INSTALLATION NOTES": ["Old first", "Old second"]})
    save_draft(draft, paths.workspace_drafts_dir)
    project = project_entry.new_project(build_units=[BuildUnit(unit_id="g1", individuals=[
        IndividualUnit(individual_id="v1", draft_id=draft.draft_id),
    ])])
    project_entry.save_project(project, paths)

    notes = "First paragraph\n\nSecond paragraph\nwith another line"
    result = handle_save_individual_notes(
        project.project_id, "g1", "v1", {
            "notes": notes,
            "delivery_requirements": "Call before delivery\nBring both keys",
        }, paths,
    )

    assert result["ok"]
    assert project_entry.load_project(project.project_id, paths).build_units[0].individuals[0].notes == notes
    saved_draft = load_draft(draft.draft_id, paths.workspace_drafts_dir)
    assert saved_draft.notes["INSTALLATION NOTES"] == [notes]
    assert saved_draft.notes["DELIVERY REQUIREMENTS"] == [
        "Call before delivery\nBring both keys",
    ]


def test_project_list_recovers_paragraphs_from_legacy_draft_rows(paths):
    draft = new_draft(notes={"INSTALLATION NOTES": ["First paragraph", "Second paragraph"]})
    save_draft(draft, paths.workspace_drafts_dir)
    project = project_entry.new_project(build_units=[BuildUnit(unit_id="g1", individuals=[
        IndividualUnit(individual_id="v1", draft_id=draft.draft_id),
    ])])
    project_entry.save_project(project, paths)

    listed = handle_list_projects(paths)

    assert listed["projects"][0]["build_units"][0]["individuals"][0]["notes"] == (
        "First paragraph\n\nSecond paragraph"
    )


def test_inactive_qb_agency_is_removed_unless_a_project_uses_it(paths):
    unused = agency_service.handle_save_agency({"name": "Unused Test Agency"}, paths)["agency"]
    used = agency_service.handle_save_agency({"name": "Historical Test Agency"}, paths)["agency"]
    agency_service.set_qb_customer_id(paths, unused["agency_id"], "inactive-unused")
    agency_service.set_qb_customer_id(paths, used["agency_id"], "inactive-used")
    project = project_entry.new_project(customer=CustomerInfo(
        agency_id=used["agency_id"], agency=used["name"], build_year="2025",
    ))
    project_entry.save_project(project, paths)

    result = agency_service.reconcile_inactive_qb_agencies([
        {"qb_customer_id": "inactive-unused"},
        {"qb_customer_id": "inactive-used"},
    ], paths)

    assert [item["agency_id"] for item in result["removed"]] == [unused["agency_id"]]
    assert [item["agency_id"] for item in result["retained_for_projects"]] == [used["agency_id"]]
    assert agency_service.get_agency(paths, unused["agency_id"]) is None
    assert agency_service.get_agency(paths, used["agency_id"]) is not None


def test_project_estimate_binding_is_verified_and_propagates_to_all_units(paths, monkeypatch):
    project = project_entry.new_project(
        customer=CustomerInfo(build_year="2026"),
        build_units=[BuildUnit(unit_id="g1", individuals=[
            IndividualUnit(individual_id="v1"), IndividualUnit(individual_id="v2"),
        ])],
    )
    project_entry.save_project(project, paths)

    class Client:
        def read_estimate(self, estimate_id):
            return {
                "Id": estimate_id, "DocNumber": "26-500", "TxnStatus": "Accepted",
                "TxnDate": "2026-09-18", "CustomerRef": {"name": "Example Police Department"},
            }

    monkeypatch.setattr(qb_sync_service, "_build_client", lambda _paths: (Client(), None))
    result = qb_estimate_service.bind_project_estimate(
        paths, project_id=project.project_id, qb_estimate_id="500",
    )
    assert result["ok"]
    saved = project_entry.load_project(project.project_id, paths)
    assert saved.project_quote_references[0].quote_number == "26-500"

    from dtm_buildsheet.app.services.qb_acceptance_service import builder_estimate_links
    links = builder_estimate_links(paths)
    assert links["v1"][0]["estimate_id"] == "500"
    assert links["v2"][0]["estimate_id"] == "500"


def test_operations_read_filters_removed_vehicle_and_normalizes_legacy_parts_state():
    repository = InMemoryOperationsRepository()
    repository._records["current"] = VehicleOperations(  # noqa: SLF001
        vehicle_id="current", project_id="p1", parts_status="partially_received",
    )
    repository._records["removed"] = VehicleOperations(  # noqa: SLF001
        vehicle_id="removed", project_id="p1",
    )
    project = SimpleNamespace(
        project_id="p1",
        project_type="build",
        service_details={},
        build_units=[SimpleNamespace(individuals=[SimpleNamespace(individual_id="current")])],
    )
    actor = OperationsActor(
        user_id="user", display_name="User", roles=frozenset({AppRole.APP_ADMIN.value}),
    )
    payload = OperationsReadService(repository).list_vehicle_summaries(actor, projects=[project])
    assert [row["vehicle_id"] for row in payload["vehicles"]] == ["current"]
    assert payload["vehicles"][0]["parts_status"] == "ordered"
