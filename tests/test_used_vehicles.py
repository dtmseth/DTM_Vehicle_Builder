from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dtm_buildsheet.app.services import (
    strip_documentation_service,
    used_vehicle_service,
    vehicle_sale_service,
)
from dtm_buildsheet.app.services.request_access_service import required_capabilities
from dtm_buildsheet.domain.operations_policy import Capability
from dtm_buildsheet.domain.project_models import BuildUnit, CustomerInfo, IndividualUnit, ProjectRecord
from dtm_buildsheet.inputs.project_entry import load_project, save_project
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path: Path) -> AppPaths:
    root = Path(__file__).parents[1]
    return replace(
        AppPaths(),
        workspace_dir=tmp_path,
        workspace_output_dir=tmp_path / "output",
        workspace_projects_dir=tmp_path / "projects",
        resources_dir=root / "src" / "dtm_buildsheet" / "resources",
    )


def _project(project_id: str, individual: IndividualUnit) -> ProjectRecord:
    return ProjectRecord(
        project_id=project_id,
        created_at="2027-01-01T00:00:00+00:00",
        updated_at="2027-01-01T00:00:00+00:00",
        customer=CustomerInfo(agency="Hector Police Department", build_year="2027"),
        build_units=[BuildUnit(unit_id=f"{project_id}-group", build_type="Patrol", individuals=[individual])],
    )


def test_used_vehicle_is_canonical_across_project_buyback_and_strip(tmp_path):
    paths = _paths(tmp_path)
    blank_sale = vehicle_sale_service.new_record(paths)["record"]
    assert blank_sale["used_vehicle_id"] == ""
    assert used_vehicle_service.list_records(paths, sync_cloud=False)["records"] == []

    donor_vin = "1FM5K8AR0JGA12345"
    project = _project("hector-build", IndividualUnit(
        individual_id="new-build-1",
        unit_number="201",
        vin="1GNSKLED8RR123456",
        existing_year="2018",
        existing_make="Ford",
        existing_model="Police Interceptor Utility",
        existing_color="Black",
        existing_unit_number="77",
        existing_vin=donor_vin,
    ))
    save_project(project, paths)
    assert used_vehicle_service.migrate_legacy_projects(paths) == {"projects": 1, "vehicles": 1}
    project = load_project("hector-build", paths)
    donor = used_vehicle_service.get_record(
        project.build_units[0].individuals[0].source_used_vehicle_id, paths,
    )
    assert donor["vin"] == donor_vin
    assert donor["equipment_transfer_status"] == "linked"
    assert donor["strip_requirement"] == "required"
    sale = vehicle_sale_service.save_record({
        "purchased_from": "Hector Police Department",
        "vehicle_year": "2018",
        "vehicle_make": "Ford",
        "vehicle_model": "Police Interceptor Utility",
        "vehicle_color": "Black",
        "vehicle_unit_number": "77",
        "vin": donor_vin,
    }, paths, publish=False)["record"]
    assert sale["used_vehicle_id"] == donor["used_vehicle_id"]
    donor = used_vehicle_service.get_record(donor["used_vehicle_id"], paths)
    assert donor["purchase_status"] == "purchased_by_dtm"

    linked_sale = vehicle_sale_service.find_record_for_vehicle(
        "hector-build", "new-build-1", paths, sync_cloud=False,
    )
    assert linked_sale and linked_sale["record_id"] == sale["record_id"]

    no_transfer = used_vehicle_service.update_relationships({
        "used_vehicle_id": donor["used_vehicle_id"],
        "equipment_transfer_status": "not_linked",
    }, paths)["record"]
    assert no_transfer["equipment_transfer_status"] == "not_linked"
    original = load_project("hector-build", paths).build_units[0].individuals[0]
    assert original.source_used_vehicle_id == ""

    not_required = used_vehicle_service.update_relationships({
        "used_vehicle_id": donor["used_vehicle_id"],
        "strip_requirement": "not_required",
        "strip_not_required_reason": "Authorized recipient",
    }, paths)["record"]
    assert not_required["purchase_status"] == "purchased_by_dtm"
    assert not_required["strip_status"] == "not_required"

    required_again = used_vehicle_service.update_relationships({
        "used_vehicle_id": donor["used_vehicle_id"],
        "strip_requirement": "required",
    }, paths)["record"]
    assert required_again["strip_status"] == "not_started"
    assert required_again["strip_not_required_reason"] == ""

    strip = strip_documentation_service.record_from_sale(sale["record_id"], paths)
    assert strip["used_vehicle_id"] == donor["used_vehicle_id"]
    donor = used_vehicle_service.get_record(donor["used_vehicle_id"], paths)
    assert donor["strip_requirement"] == "required"
    assert donor["strip_status"] == "in_progress"

    second = _project("hector-second", IndividualUnit(
        individual_id="new-build-2",
        unit_number="202",
        vin="1GNSKLED8RR654321",
    ))
    save_project(second, paths)
    linked = used_vehicle_service.link_to_build(
        donor["used_vehicle_id"], "hector-second", "hector-second-group", "new-build-2", paths,
    )
    assert linked["ok"]
    stored_second = load_project("hector-second", paths)
    source = stored_second.build_units[0].individuals[0]
    assert source.source_used_vehicle_id == donor["used_vehicle_id"]
    assert source.existing_vin == donor_vin
    with pytest.raises(ValueError, match="requires strip documentation"):
        used_vehicle_service.update_relationships({
            "used_vehicle_id": donor["used_vehicle_id"],
            "strip_requirement": "not_required",
        }, paths)
    used_vehicle_service.update_relationships({
        "used_vehicle_id": donor["used_vehicle_id"],
        "equipment_transfer_status": "not_linked",
    }, paths)
    unlinked = load_project("hector-second", paths).build_units[0].individuals[0]
    assert unlinked.source_used_vehicle_id == ""
    assert unlinked.existing_vin == ""

    exact = used_vehicle_service.suggest_records(
        agency_name="Hector Police Department", vin=donor_vin,
        unit_number="77", paths=paths,
    )["records"]
    assert exact[0]["used_vehicle_id"] == donor["used_vehicle_id"]
    assert exact[0]["match_confidence"] == "exact"
    assert "Exact VIN" in exact[0]["match_reasons"]

    unrelated = used_vehicle_service.suggest_records(
        agency_name="Unrelated Agency", vin="", unit_number="", paths=paths,
    )["records"]
    assert unrelated == []

    assert required_capabilities("GET", "/api/used-vehicles") == frozenset({Capability.PROJECTS_VIEW})
    assert required_capabilities(
        "POST", "/api/used-vehicles/link-build",
    ) == frozenset({Capability.PROJECTS_EDIT})

    ui_root = Path(__file__).parents[1] / "src" / "dtm_buildsheet" / "ui"
    html = (ui_root / "index.html").read_text(encoding="utf-8")
    project_js = (ui_root / "js" / "projects" / "individual_modal.js").read_text(encoding="utf-8")
    sales_js = (ui_root / "js" / "vehicle_sales.js").read_text(encoding="utf-8")
    assert 'id="ind-edit-used-vehicle"' in html
    assert 'id="vehicle-sales-strip-requirement"' in html
    assert 'id="vehicle-sales-transfer-build"' in html
    assert "/api/used-vehicles/suggest" in project_js
    assert "/api/used-vehicles/link-build" in sales_js
