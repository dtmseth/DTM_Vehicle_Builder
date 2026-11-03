from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import fitz

from dtm_buildsheet.app.services import strip_documentation_service, vehicle_sale_service
from dtm_buildsheet.app.services.request_access_service import required_capabilities
from dtm_buildsheet.domain.operations_policy import Capability
from dtm_buildsheet.domain.project_models import BuildUnit, CustomerInfo, IndividualUnit, ProjectRecord
from dtm_buildsheet.inputs.project_entry import save_project
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


def _project() -> ProjectRecord:
    return ProjectRecord(
        project_id="lake-2027",
        created_at="2027-01-01T00:00:00+00:00",
        updated_at="2027-01-01T00:00:00+00:00",
        customer=CustomerInfo(agency="Lake County Sheriff"),
        build_units=[BuildUnit(
            unit_id="group-1",
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                existing_year="2018",
                existing_make="Ford",
                existing_model="Police Interceptor Utility",
                existing_color="Black",
                existing_unit_number="77",
                existing_vin="1FM5K8AR0JGA12345",
            )],
        )],
    )


def test_strip_record_keeps_internal_identity_hidden_and_exposes_vin_at_two_entry_points(tmp_path):
    paths = _paths(tmp_path)
    save_project(_project(), paths)

    from_project = strip_documentation_service.record_from_project(
        "lake-2027", "group-1", "vehicle-1", paths,
    )
    assert from_project["agency_name"] == "Lake County Sheriff"
    assert from_project["vin"] == "1FM5K8AR0JGA12345"
    assert from_project["sharepoint_folder_path"].startswith(
        "Strip Documentation/Lake County Sheriff/2018/"
    )

    sale = vehicle_sale_service.save_record({
        "record_year": "2027",
        "purchased_from": "Lake County Sheriff",
        "vehicle_year": "2018",
        "vehicle_make": "Ford",
        "vehicle_model": "Police Interceptor Utility",
        "vehicle_color": "Black",
        "vehicle_unit_number": "77",
        "vin": "1FM5K8AR0JGA12345",
        "project_id": "lake-2027",
        "unit_id": "group-1",
        "individual_id": "vehicle-1",
    }, paths, publish=False)["record"]
    from_sale = strip_documentation_service.record_from_sale(sale["record_id"], paths)
    assert from_sale["record_id"] == from_project["record_id"]
    assert from_sale["used_vehicle_id"] == from_project["used_vehicle_id"]
    assert from_sale["vehicle_sale_record_id"] == sale["record_id"]
    assert from_sale["disposition"] == "purchased_by_dtm"
    assert from_sale["workflow_stage"] == "intake"
    assert from_sale["form_status"] == "intake_complete"

    technician_record = strip_documentation_service.save_technician_record({
        "record_id": from_sale["record_id"],
        "agency_name": "This shop-supplied change must be ignored",
    }, paths, publish=False)["record"]
    assert technician_record["workflow_stage"] == "technician"
    assert technician_record["agency_name"] == "Lake County Sheriff"

    updated = strip_documentation_service.save_technician_record({
        **technician_record,
        "strip_date": "2027-03-11",
        "photo_proof_captured": True,
        "technician_signature": "Morgan Lee",
        "technician_signed_date": "2027-03-11",
        "reviewer_signature": "Casey Park",
        "reviewer_signed_date": "2027-03-11",
        "checklist": {
            item_id: {"status": "removed", "note": ""}
            for item_id, _label in strip_documentation_service.CHECKLIST_ITEMS
        },
    }, paths, publish=False)["record"]
    assert updated["form_status"] == "form_ready"
    assert updated["performed_by"] == "Morgan Lee"
    assert updated["reviewed_by"] == "Casey Park"

    stored = json.loads(
        (tmp_path / "strip_documentation" / f"{updated['record_id']}.json").read_text(encoding="utf-8")
    )
    assert stored["used_vehicle_id"] == updated["used_vehicle_id"]
    pdf_path = Path(updated["pdf_path"])
    assert pdf_path.is_file()
    document = fitz.open(pdf_path)
    assert document.page_count == 1
    assert document.metadata["title"] == "DTM Vehicle Strip Documentation"
    widgets = {
        widget.field_name: widget
        for page in document
        for widget in (page.widgets() or [])
    }
    assert widgets["agency_name"].field_value == "Lake County Sheriff"
    assert widgets["emergency_lights_removed"].field_value == "Yes"
    assert widgets["photo_proof_captured"].field_value == "Yes"
    assert "plate_number" not in widgets
    assert "plate_type" not in widgets
    assert "technician_signature" not in widgets
    assert "reviewer_signature" not in widgets
    assert "photo_vin_before" not in widgets
    assert max(widget.rect.y1 for widget in widgets.values()) < 760
    all_text = " ".join(page.get_text() for page in document)
    assert "not the state certificate of compliance" in all_text
    assert "IS DTM BUYING THIS VEHICLE?" in all_text
    assert "1FM5K8AR0JGA12345" in all_text
    assert "USED VEHICLE ID" not in all_text
    assert "SHAREPOINT" not in all_text
    assert "WORK ORDER" not in all_text
    assert "LOCATION" not in all_text
    assert "PHOTO DOCUMENTATION PLAN" not in all_text
    assert "Morgan Lee" in all_text
    assert "Casey Park" in all_text
    assert any("Caveat" in str(font) for font in document[0].get_fonts(full=True))
    document.close()

    assert len(strip_documentation_service.PHOTO_ANGLES) == 12
    checklist_labels = {label for _item_id, label in strip_documentation_service.CHECKLIST_ITEMS}
    assert "Spotlights" in checklist_labels
    assert "Antennas" in checklist_labels
    assert strip_documentation_service.SHAREPOINT_VEHICLE_SUBFOLDERS == (
        "Before Photos", "After Photos", "Documents",
    )
    assert required_capabilities(
        "POST", "/api/strip-documentation/save-intake",
    ) == frozenset({Capability.PROJECTS_EDIT})
    assert required_capabilities(
        "POST", "/api/strip-documentation/save-technician",
    ) == frozenset({Capability.COMPLETED_MEDIA_UPLOAD})

    ui_root = Path(__file__).parents[1] / "src" / "dtm_buildsheet" / "ui"
    html = (ui_root / "index.html").read_text(encoding="utf-8")
    project_js = (ui_root / "js" / "projects" / "individual_modal.js").read_text(encoding="utf-8")
    sale_js = (ui_root / "js" / "vehicle_sales.js").read_text(encoding="utf-8")
    strip_js = (ui_root / "js" / "strip_documentation.js").read_text(encoding="utf-8")
    assert 'id="vehicle-sales-strip-documentation"' in html
    assert 'id="ind-edit-strip-documentation"' in html
    assert "strip-documentation-used-vehicle-id" not in html
    assert 'data-strip-field="work_order_number"' not in html
    assert 'data-strip-field="strip_location"' not in html
    assert 'data-strip-field="plate_number"' not in html
    assert 'data-strip-field="plate_type"' not in html
    assert "strip-documentation-open-folder" not in html
    assert 'data-strip-field="technician_signature"' in html
    assert 'data-strip-field="reviewer_signature"' in html
    assert 'data-strip-field="performed_by"' not in html
    assert 'data-strip-field="reviewed_by"' not in html
    assert 'id="strip-documentation-technician-section"' in html
    assert 'id="strip-documentation-sales-tab"' in html
    assert 'id="strip-documentation-technician-tab"' in html
    assert "Technician Strip Documentation" in html
    assert "Technician removal documentation" not in html
    assert "Each person types their full name once" in html
    assert "Is DTM buying this vehicle?" in html
    assert "Yes - DTM buyback" in html
    assert "No - returning to agency" in html
    assert "Vehicle destination" not in html
    assert "/api/strip-documentation/save-intake" in strip_js
    assert "/api/strip-documentation/save-technician" in strip_js
    assert "DTMStripDocumentation?.fromProject" in project_js
    assert "DTMStripDocumentation?.fromSale" in sale_js
