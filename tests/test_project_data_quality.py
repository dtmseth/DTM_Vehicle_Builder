from __future__ import annotations

import json
from dataclasses import asdict
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
    handle_set_project_completion,
)
from dtm_buildsheet.app.services.sales_rep_service import (
    handle_merge_reps,
    handle_save_rep,
    reconcile_project_rep_links,
)
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


def test_agency_review_uses_official_styling_with_saint_paul_exception(paths):
    assert agency_service.review_agency_name_without_matches(
        "City of St Cloud",
    ) == "City of St. Cloud"
    assert agency_service.review_agency_name_without_matches(
        "Saint Joseph Police Department",
    ) == "St. Joseph Police Department"
    assert agency_service.review_agency_name_without_matches(
        "St. Paul Police Department",
    ) == "Saint Paul Police Department"
    official = agency_service.review_agency_name("St. Cloud Police Department", paths)
    assert official["suggested_name"] == "St. Cloud Police Department"
    assert not any("St." in warning or "Saint" in warning for warning in official["warnings"])
    uncommon_saint = agency_service.review_agency_name("Saint Example Police Department", paths)
    assert uncommon_saint["suggested_name"] == "Saint Example Police Department"
    assert uncommon_saint["requires_acknowledgement"] is True
    assert any("official source" in warning for warning in uncommon_saint["warnings"])


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


def test_builder_agency_merge_can_keep_same_year_projects_separate(paths):
    source = agency_service.handle_save_agency({"name": "ICE duplicate"}, paths)["agency"]
    target = agency_service.handle_save_agency({
        "name": "US Immigration & Customs Enforcement (ICE)",
        "abbreviation": "ICE",
        "customer_since": "2026",
    }, paths)["agency"]
    agency_service.set_qb_customer_id(paths, source["agency_id"], "443")
    agency_service.set_qb_customer_id(paths, target["agency_id"], "443")
    source_project = project_entry.new_project(
        customer=CustomerInfo(
            agency_id=source["agency_id"], agency=source["name"], build_year="2026",
        ),
        build_units=[BuildUnit(unit_id="source-group", individuals=[
            IndividualUnit(individual_id="source-vehicle", vin="1FT7W2BA5TEC31935"),
        ])],
    )
    target_project = project_entry.new_project(
        customer=CustomerInfo(
            agency_id=target["agency_id"], agency=target["name"], build_year="2026",
        ),
        build_units=[BuildUnit(unit_id="target-group", individuals=[
            IndividualUnit(individual_id="target-vehicle", vin="1FM5K8AB6SGC43753"),
        ])],
    )
    project_entry.save_project(source_project, paths)
    project_entry.save_project(target_project, paths)

    result = agency_service.handle_merge_agencies({
        "source_agency_id": source["agency_id"],
        "target_agency_id": target["agency_id"],
        "keep_projects_separate": True,
    }, paths)

    assert result["ok"] is True
    assert result["updated_project_ids"] == [source_project.project_id]
    assert result["kept_project_ids_separate"] == [source_project.project_id]
    saved_projects = {
        project.project_id: project for project in project_entry.list_projects(paths)
    }
    assert set(saved_projects) == {source_project.project_id, target_project.project_id}
    assert saved_projects[source_project.project_id].customer.agency_id == target["agency_id"]
    assert saved_projects[target_project.project_id].customer.agency_id == target["agency_id"]
    assert saved_projects[source_project.project_id].build_units[0].individuals[0].individual_id == (
        "source-vehicle"
    )
    assert agency_service.get_agency(paths, source["agency_id"]) is None


def test_project_form_requires_real_agency_and_sales_rep_selection(paths):
    rejected = handle_save_project({
        "require_selected_identities": True,
        "customer": {"agency": "Typed Agency", "sales_rep": "Typed Rep", "build_year": "2026"},
    }, paths)
    assert rejected["error_code"] == "agency_selection_required"

    agency = agency_service.handle_save_agency({"name": "Example Police Department"}, paths)["agency"]
    rep = handle_save_rep({"name": "Alex Rep", "phone": "555-0100", "email": "alex@example.com"}, paths)["rep"]
    typed_existing_rep = handle_save_project({
        "require_selected_identities": True,
        "customer": {
            "agency": agency["name"], "agency_id": agency["agency_id"],
            "sales_rep": "Alex Rep", "build_year": "2026",
        },
    }, paths)
    assert typed_existing_rep["error_code"] == "sales_rep_selection_required"
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


def _reviewed_project_body(agency: dict, rep: dict, *, unit_id: str, vehicle_id: str,
                           vin: str, quote: str) -> dict:
    return {
        "require_selected_identities": True,
        "customer": {
            "agency": agency["name"],
            "agency_id": agency["agency_id"],
            "sales_rep": rep["name"],
            "sales_rep_id": rep["rep_id"],
            "build_year": "2026",
            "quote_number": quote,
        },
        "build_units": [{
            "unit_id": unit_id,
            "vehicle_model": "PIU",
            "build_type": "Patrol",
            "quantity": 1,
            "individuals": [{"individual_id": vehicle_id, "vin": vin}],
        }],
    }


def test_same_agency_year_creation_compares_then_allows_separate_editable_projects(paths):
    agency = agency_service.handle_save_agency({"name": "Example Police Department"}, paths)["agency"]
    rep = handle_save_rep({
        "name": "Alex Rep", "phone": "555-0100", "email": "alex@example.com",
    }, paths)["rep"]
    first_body = _reviewed_project_body(
        agency, rep, unit_id="group-1", vehicle_id="vehicle-1",
        vin="1FM5K8AB1SGA00001", quote="Q-100",
    )
    first = handle_save_project(first_body, paths)
    second_body = _reviewed_project_body(
        agency, rep, unit_id="group-2", vehicle_id="vehicle-2",
        vin="1FM5K8AB1SGA00002", quote="Q-200",
    )

    warning = handle_save_project(second_body, paths)

    assert warning["error_code"] == "project_exists_for_agency_year"
    assert warning["existing_project"]["vehicle_count"] == 1
    assert warning["proposed_project"]["vehicles"][0]["vin"] == "1FM5K8AB1SGA00002"
    assert warning["duplicate_vins"] == []

    second = handle_save_project({**second_body, "conflict_resolution": "separate"}, paths)
    assert second["ok"] is True and second["resolution"] == "separate"
    assert second["project_id"] != first["project_id"]

    saved_second = project_entry.load_project(second["project_id"], paths)
    edited = handle_save_project({
        **asdict(saved_second),
        "expected_updated_at": saved_second.updated_at,
        "expected_record_revision": saved_second.record_revision,
    }, paths)
    assert edited["ok"] is True

    assert handle_set_project_completion(
        first["project_id"], {"completed": True}, paths,
    )["ok"] is True
    completion_warning = handle_set_project_completion(
        second["project_id"], {"completed": True}, paths,
    )
    assert completion_warning["error_code"] == "completed_project_exists_for_agency_year"
    completed_separately = handle_set_project_completion(
        second["project_id"], {"completed": True, "conflict_resolution": "separate"}, paths,
    )
    assert completed_separately["ok"] is True
    assert completed_separately["resolution"] == "separate"


def test_same_agency_year_creation_can_merge_distinct_units_and_blocks_duplicate_vin(paths):
    agency = agency_service.handle_save_agency({"name": "Example Police Department"}, paths)["agency"]
    rep = handle_save_rep({
        "name": "Alex Rep", "phone": "555-0100", "email": "alex@example.com",
    }, paths)["rep"]
    first_body = _reviewed_project_body(
        agency, rep, unit_id="group-1", vehicle_id="vehicle-1",
        vin="1FM5K8AB1SGA00001", quote="Q-100",
    )
    first = handle_save_project(first_body, paths)
    duplicate_body = _reviewed_project_body(
        agency, rep, unit_id="group-duplicate", vehicle_id="vehicle-duplicate",
        vin="1FM5K8AB1SGA00001", quote="Q-DUP",
    )
    duplicate_warning = handle_save_project(duplicate_body, paths)
    assert duplicate_warning["duplicate_vins"] == ["1FM5K8AB1SGA00001"]
    duplicate_merge = handle_save_project({
        **duplicate_body, "conflict_resolution": "merge",
    }, paths)
    assert duplicate_merge["error_code"] == "project_merge_vehicle_conflict"

    distinct_body = _reviewed_project_body(
        agency, rep, unit_id="group-2", vehicle_id="vehicle-2",
        vin="1FM5K8AB1SGA00002", quote="Q-200",
    )
    merged = handle_save_project({**distinct_body, "conflict_resolution": "merge"}, paths)

    assert merged["ok"] is True and merged["resolution"] == "merge"
    assert merged["project_id"] == first["project_id"]
    projects = project_entry.list_projects(paths)
    assert len(projects) == 1
    assert {unit.unit_id for unit in projects[0].build_units} == {"group-1", "group-2"}
    assert projects[0].quote_numbers == ["Q-100", "Q-200"]


def test_existing_project_identity_move_can_stay_separate_but_cannot_merge(paths):
    first_agency = agency_service.handle_save_agency({"name": "First Police Department"}, paths)["agency"]
    second_agency = agency_service.handle_save_agency({"name": "Second Police Department"}, paths)["agency"]
    rep = handle_save_rep({
        "name": "Alex Rep", "phone": "555-0100", "email": "alex@example.com",
    }, paths)["rep"]
    first = handle_save_project(_reviewed_project_body(
        first_agency, rep, unit_id="group-1", vehicle_id="vehicle-1",
        vin="1FM5K8AB1SGA00001", quote="Q-100",
    ), paths)
    second = handle_save_project(_reviewed_project_body(
        second_agency, rep, unit_id="group-2", vehicle_id="vehicle-2",
        vin="1FM5K8AB1SGA00002", quote="Q-200",
    ), paths)
    saved_second = project_entry.load_project(second["project_id"], paths)
    edit_body = {
        **asdict(saved_second),
        "expected_updated_at": saved_second.updated_at,
        "expected_record_revision": saved_second.record_revision,
        "customer": {
            **asdict(saved_second.customer),
            "agency": first_agency["name"],
            "agency_id": first_agency["agency_id"],
        },
    }

    warning = handle_save_project(edit_body, paths)
    assert warning["error_code"] == "project_exists_for_agency_year"
    assert warning["merge_allowed"] is False

    rejected_merge = handle_save_project({
        **edit_body, "conflict_resolution": "merge",
    }, paths)
    assert rejected_merge["error_code"] == "existing_project_merge_not_supported"
    assert project_entry.load_project(second["project_id"], paths).customer.agency_id == second_agency["agency_id"]

    kept_separate = handle_save_project({
        **edit_body, "conflict_resolution": "separate",
    }, paths)
    assert kept_separate["ok"] is True
    assert kept_separate["resolution"] == "separate"
    projects = {project.project_id: project for project in project_entry.list_projects(paths)}
    assert set(projects) == {first["project_id"], second["project_id"]}
    assert projects[second["project_id"]].customer.agency_id == first_agency["agency_id"]


def test_deleted_duplicate_rep_link_is_repaired_by_exact_name(paths):
    agency = agency_service.handle_save_agency({"name": "Example Police Department"}, paths)["agency"]
    current = handle_save_rep({
        "name": "Dan Orth", "phone": "555-0100", "email": "dan@example.com",
    }, paths)["rep"]
    project = project_entry.new_project(customer=CustomerInfo(
        agency_id=agency["agency_id"],
        agency=agency["name"],
        build_year="2027",
        sales_rep_id="deleted-duplicate-id",
        sales_rep="  DAN   ORTH ",
    ))
    project_entry.save_project(project, paths)

    result = reconcile_project_rep_links(paths)

    assert result["ok"] is True
    assert len(result["repaired"]) == 1
    saved = project_entry.load_project(project.project_id, paths)
    assert saved.customer.sales_rep_id == current["rep_id"]
    assert saved.customer.sales_rep == "Dan Orth"


def test_identical_duplicate_rep_merge_rebinds_projects(paths):
    target = handle_save_rep({
        "name": "Dan Orth", "phone": "555-0100", "email": "dan@example.com",
    }, paths)["rep"]
    source = {**target, "rep_id": "duplicate-dan"}
    (paths.workspace_dir / "sales_reps" / "duplicate-dan.json").write_text(
        json.dumps(source), encoding="utf-8",
    )
    from dtm_buildsheet.app.services import sales_rep_service
    sales_rep_service.warmup_cache(paths, force=True)
    project = project_entry.new_project(customer=CustomerInfo(
        build_year="2027", sales_rep_id=source["rep_id"], sales_rep=source["name"],
    ))
    project_entry.save_project(project, paths)

    result = handle_merge_reps({
        "source_rep_id": source["rep_id"],
        "target_rep_id": target["rep_id"],
    }, paths)

    assert result["ok"] is True
    assert result["updated_project_ids"] == [project.project_id]
    saved = project_entry.load_project(project.project_id, paths)
    assert saved.customer.sales_rep_id == target["rep_id"]
    assert not (paths.workspace_dir / "sales_reps" / "duplicate-dan.json").exists()


def test_cross_device_rep_and_qbo_import_ids_are_deterministic(tmp_path):
    roots = [tmp_path / "device-a", tmp_path / "device-b"]
    device_paths = []
    for root in roots:
        for name in ("config", "projects", "drafts", "agencies", "sales_reps", "output"):
            (root / name).mkdir(parents=True, exist_ok=True)
        device_paths.append(AppPaths(
            workspace_dir=root,
            workspace_config_dir=root / "config",
            workspace_projects_dir=root / "projects",
            workspace_drafts_dir=root / "drafts",
            workspace_output_dir=root / "output",
        ))

    rep_ids = [
        handle_save_rep({
            "name": "  Don   Starry ", "phone": "555", "email": "don@example.com",
        }, device)["rep"]["rep_id"]
        for device in device_paths
    ]
    agency_ids = []
    for device in device_paths:
        imported = agency_service.upsert_agencies_from_qb([{
            "qb_customer_id": "customer-42",
            "name": "Example Police Department",
        }], device)
        assert imported["created"] == 1
        agency_ids.append(agency_service.load_agencies(device)[0].agency_id)

    assert rep_ids[0] == rep_ids[1]
    assert agency_ids[0] == agency_ids[1]


def test_stale_project_agency_link_is_repaired_by_canonical_name(paths):
    agency = agency_service.handle_save_agency({
        "name": "Rice County Sheriff's Office", "naming_override": True,
    }, paths)["agency"]
    project = project_entry.new_project(customer=CustomerInfo(
        agency_id="deleted-duplicate-id",
        agency="Rice County Sheriff",
        build_year="2027",
    ))
    project_entry.save_project(project, paths)

    result = agency_service.reconcile_project_agency_links(paths)

    assert result["ok"] is True
    assert len(result["repaired"]) == 1
    saved = project_entry.load_project(project.project_id, paths)
    assert saved.customer.agency_id == agency["agency_id"]
    assert saved.customer.agency == "Rice County Sheriff's Office"


def test_project_save_repairs_stale_agency_id_but_not_unselected_text(paths):
    agency = agency_service.handle_save_agency({
        "name": "Rice County Sheriff's Office", "naming_override": True,
    }, paths)["agency"]
    repaired = handle_save_project({
        "require_selected_identities": False,
        "customer": {
            "agency_id": "deleted-duplicate-id",
            "agency": "Rice County Sheriff",
            "build_year": "2027",
        },
    }, paths)
    assert repaired["ok"] is True
    saved = project_entry.load_project(repaired["project_id"], paths)
    assert saved.customer.agency_id == agency["agency_id"]

    rejected = handle_save_project({
        "require_selected_identities": True,
        "customer": {
            "agency": "Rice County Sheriff's Office",
            "build_year": "2028",
        },
    }, paths)
    assert rejected["error_code"] == "agency_selection_required"


def test_project_save_repairs_deleted_duplicate_rep_link(paths):
    agency = agency_service.handle_save_agency({"name": "Example Police Department"}, paths)["agency"]
    current = handle_save_rep({
        "name": "Don Starry", "phone": "555-0101", "email": "don@example.com",
    }, paths)["rep"]

    saved = handle_save_project({
        "require_selected_identities": True,
        "customer": {
            "agency_id": agency["agency_id"],
            "agency": agency["name"],
            "build_year": "2027",
            "sales_rep_id": "deleted-duplicate-id",
            "sales_rep": "Don Starry",
        },
    }, paths)

    assert saved["ok"] is True
    project = project_entry.load_project(saved["project_id"], paths)
    assert project.customer.sales_rep_id == current["rep_id"]
    assert project.customer.sales_rep == "Don Starry"


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
