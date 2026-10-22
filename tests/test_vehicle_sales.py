from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from dtm_buildsheet.app.services.request_access_service import required_capabilities
from dtm_buildsheet.app.services.vehicle_sale_service import (
    delete_record,
    find_build_vehicle_matches,
    find_record_for_vehicle,
    list_records,
    print_record_pdf,
    record_for_vehicle,
    save_record,
)
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


def test_vehicle_sale_save_replaces_one_fillable_pdf_and_keeps_record(tmp_path):
    paths = _paths(tmp_path)
    created = save_record({
        "record_id": "57dc95b2-c6a2-4c71-81ab-ff303124f3c2",
        "record_year": "2026",
        "prepared_by": "Morgan Lee",
        "project_agency": "Lake County",
        "date_received": "2027-03-04",
        "purchased_from": "Lake County",
        "vehicle_year": "2019",
        "vehicle_make": "Chevrolet",
        "vehicle_model": "Tahoe",
        "vin": "1GNSKDEC0KR123456",
        "purchase_via": "account_credit",
        "quote_number": "Q-1042",
        "dvs_flagged_resale_date": "2027-03-08",
        "buyer_name": "Private buyer",
    }, paths, publish=False)

    pdf_path = Path(created["pdf_path"])
    assert pdf_path.parent == tmp_path / "output" / "Vehicle Buyback Sales" / "2027"
    assert pdf_path.is_file()
    assert len(list(pdf_path.parent.glob("*.pdf"))) == 1
    document = fitz.open(pdf_path)
    assert document.page_count == 1
    widgets = {widget.field_name: widget for widget in document[0].widgets()}
    assert len(widgets) == 26
    assert widgets["prepared_by"].field_value == "Morgan Lee"
    assert widgets["prepared_by"].text_fontsize == 10
    assert widgets["prepared_by"].border_width >= 1
    assert widgets["prepared_by"].border_color == [0.0, 0.0, 0.0]
    assert widgets["date_received"].field_value == "03/04/2027"
    assert widgets["quote_number"].field_value == "Q-1042"
    assert "INVOICE NUMBER" in " ".join(page.get_text() for page in document)
    assert "project_agency" not in widgets
    assert "vehicle_unit_number" in widgets
    assert "DTM Fleet Service" in " ".join(page.get_text() for page in document)
    assert max(widget.rect.y1 for widget in widgets.values()) < 710
    document.close()

    first_name = pdf_path.name
    updated = save_record({
        **created["record"],
        "buyer_name": "North Star Auto",
        "sale_amount": "12,500.00",
    }, paths, publish=False)
    assert Path(updated["pdf_path"]).name == first_name
    assert len(list(pdf_path.parent.glob("*.pdf"))) == 1
    stored = json.loads(
        (tmp_path / "vehicle_buyback_sales" / f"{created['record']['record_id']}.json")
        .read_text(encoding="utf-8")
    )
    assert stored["buyer_name"] == "North Star Auto"
    assert list_records(paths, sync_cloud=False)["records"][0]["sale_amount"] == "12,500.00"

    completed = type("Completed", (), {"returncode": 0, "stdout": "system default destination: Front Office\n", "stderr": ""})()
    with patch(
        "dtm_buildsheet.app.services.vehicle_sale_service.subprocess.run",
        side_effect=[completed, completed],
    ) as process, patch("dtm_buildsheet.app.services.vehicle_sale_service.sys.platform", "darwin"):
        print_result = print_record_pdf(created["record"]["record_id"], paths)
    assert print_result["ok"] is True
    assert print_result["printer_name"] == "Front Office"
    assert process.call_args_list[0].args[0] == ["lpstat", "-d"]
    spool_path = Path(print_result["spool_path"])
    assert process.call_args_list[1].args[0] == ["lp", str(spool_path)]
    assert spool_path != pdf_path
    printed = fitz.open(spool_path)
    assert printed.page_count == 1
    assert list(printed[0].widgets() or []) == []
    printed_text = printed[0].get_text()
    assert "Morgan Lee" in printed_text
    assert "Q-1042" in printed_text
    printed.close()
    editable_after_print = fitz.open(pdf_path)
    assert len(list(editable_after_print[0].widgets() or [])) == 26
    editable_after_print.close()

    with patch(
        "dtm_buildsheet.app.services.vehicle_sale_service._print_pdf_windows",
        return_value="Front Office",
    ) as windows_print, patch(
        "dtm_buildsheet.app.services.vehicle_sale_service.sys.platform", "win32",
    ):
        windows_result = print_record_pdf(created["record"]["record_id"], paths)
    assert windows_result["ok"] is True
    assert windows_result["printer_name"] == "Front Office"
    assert windows_result["message"] == "Sent to Front Office"
    windows_print.assert_called_once_with(Path(windows_result["spool_path"]))

    with pytest.raises(ValueError, match="DELETE RECORD"):
        delete_record(created["record"]["record_id"], "delete", paths, publish=False)
    assert pdf_path.is_file()
    deleted = delete_record(
        created["record"]["record_id"], "DELETE RECORD", paths, publish=False,
    )
    assert deleted["ok"] is True
    assert not pdf_path.exists()
    assert not (tmp_path / "vehicle_buyback_sales" / f"{created['record']['record_id']}.json").exists()


def test_vehicle_card_creation_prefills_existing_vehicle_and_keeps_optional_link(tmp_path):
    paths = _paths(tmp_path)
    project = ProjectRecord(
        project_id="lake-2027",
        created_at="2027-01-01T00:00:00+00:00",
        updated_at="2027-01-01T00:00:00+00:00",
        customer=CustomerInfo(agency="Lake County Sheriff", quote_number="Q-88"),
        build_units=[BuildUnit(
            unit_id="group-1",
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                unit_number="101",
                year="2027",
                make="Chevrolet",
                model="Tahoe PPV",
                color="White",
                vin="1GNSKDEC0PR765432",
                existing_year="2018",
                existing_make="Ford",
                existing_model="Police Interceptor Utility",
                existing_color="Black",
                existing_unit_number="77",
                existing_vin="1FM5K8AR0JGA12345",
            )],
        )],
    )
    save_project(project, paths)

    record = record_for_vehicle("lake-2027", "group-1", "vehicle-1", paths)

    assert record["project_id"] == "lake-2027"
    assert record["individual_id"] == "vehicle-1"
    assert record["project_agency"] == "Lake County Sheriff"
    assert record["vehicle_unit_number"] == "77"
    assert record["vehicle_year"] == "2018"
    assert record["vehicle_make"] == "Ford"
    assert record["vehicle_model"] == "Police Interceptor Utility"
    assert record["vehicle_color"] == "Black"
    assert record["vin"] == "1FM5K8AR0JGA12345"
    assert record["quote_number"] == "Q-88"

    save_record({
        **record,
        "vehicle_year": "",
        "vehicle_make": "",
        "vehicle_model": "",
        "vehicle_color": "",
        "vin": "",
        "vehicle_unit_number": "",
    }, paths, publish=False)
    refreshed = record_for_vehicle("lake-2027", "group-1", "vehicle-1", paths)
    assert refreshed["vehicle_year"] == "2018"
    assert refreshed["vehicle_make"] == "Ford"
    assert refreshed["vehicle_model"] == "Police Interceptor Utility"
    assert refreshed["vehicle_color"] == "Black"
    assert refreshed["vin"] == "1FM5K8AR0JGA12345"
    assert refreshed["vehicle_unit_number"] == "77"
    matches = find_build_vehicle_matches(
        vin="1gnskdec0pr-765432",
        agency="Lake County Sheriff",
        unit_number="101",
        exclude_project_id="",
        paths=paths,
    )["matches"]
    assert len(matches) == 1
    assert matches[0]["match_reasons"] == ["Exact VIN", "Agency + unit number"]
    assert matches[0]["vehicle_model"] == "Tahoe PPV"
    assert matches[0]["vehicle_color"] == "White"
    assert find_build_vehicle_matches(
        vin="1GNSKDEC0PR765432",
        agency="Lake County Sheriff",
        unit_number="101",
        exclude_project_id="lake-2027",
        paths=paths,
    )["matches"] == []
    assert find_record_for_vehicle(
        "lake-2027", "vehicle-1", paths, sync_cloud=False,
    )["record_id"] == record["record_id"]
    assert find_record_for_vehicle(
        "lake-2027", "missing-vehicle", paths, sync_cloud=False,
    ) is None


def test_vehicle_sale_workspace_is_staff_admin_only_and_vehicle_cards_use_focused_actions():
    assert required_capabilities("GET", "/api/vehicle-sales") == frozenset({Capability.PROJECTS_EDIT})
    assert required_capabilities("POST", "/api/vehicle-sales/save") == frozenset({Capability.PROJECTS_EDIT})

    root = Path(__file__).parents[1] / "src" / "dtm_buildsheet" / "ui"
    html = (root / "index.html").read_text(encoding="utf-8")
    tabs = (root / "js" / "tabs.js").read_text(encoding="utf-8")
    sales = (root / "js" / "vehicle_sales.js").read_text(encoding="utf-8")
    builds = (root / "js" / "projects" / "detail_builds.js").read_text(encoding="utf-8")
    individual_modal = (root / "js" / "projects" / "individual_modal.js").read_text(encoding="utf-8")
    styles = (root / "styles.css").read_text(encoding="utf-8")

    assert 'data-tab="vehicle-sales"' in html
    assert "DVS Date flagged held for resale" in html
    assert "Invoice number" in html
    assert 'data-sale-field="quote_number"' in html
    assert "An invoice number is required" in html
    assert "Open SharePoint folder" in html
    assert 'id="vehicle-sales-print-pdf"' in html
    assert "vehicle-sales-more-menu" in html
    assert 'tab === "vehicle-sales"' in tabs
    assert 'appHasCapability("projects.edit")' in tabs
    assert 'window.PT_openVehicleSale' in sales
    assert 'api("/api/vehicle-sales/print-pdf"' in sales
    assert 'api("/api/vehicle-sales/delete"' in sales
    assert "_vehicleSaleOpenDeleteModal" in sales
    assert 'addEventListener("click", _vehicleSaleOpenDeleteModal)' in sales
    assert "window.prompt" not in sales
    assert 'id="vehicle-sales-delete-confirmation"' not in html
    assert "PERMANENTLY DELETES THIS RECORD AND PDF" in html
    assert 'confirmation: "DELETE RECORD"' in sales
    assert "Saved · SharePoint syncing" in sales
    assert 'years.setAttribute("aria-busy", "true")' in sales
    assert "if (!_vehicleSaleActive)" in sales
    assert "scrollbar-gutter:stable" in styles
    assert "#vehicle-sales-years{min-height:280px}" in styles
    assert "_ptFocusedBuildActionsMarkup" in builds
    assert "Vehicle details &amp; records" in builds
    assert "Unit info, quotes, notes, and buyback / sale" in builds
    assert "proj-vehicle-details-button" in builds
    assert 'onclick="PT_openVehicleSale' not in builds
    assert "_ptExistingVehicleMarkup" not in builds
    assert "proj-existing-vehicle" not in builds
    assert 'id="ind-edit-vehicle-selector"' in html
    assert "Change unit group vehicle" in html
    assert 'id="ind-edit-existing-build-type"' not in html
    assert 'id="ind-edit-existing-color"' in html
    assert 'data-sale-field="vehicle_unit_number"' in html
    assert 'data-sale-field="existing_vehicle_link"' not in html
    assert 'data-sale-field="project_agency"' not in html
    assert 'data-sale-field="record_year"' not in html
    assert 'id="vehicle-sales-record-year"' not in html
    assert 'id="vehicle-sales-purchased-from"' in html
    assert "_ptWireAgencySearch(" in sales
    assert 'via === "account_credit" && !invoiceNumber' in sales
    assert "other.disabled" not in sales
    assert "`Invoice ${record.quote_number}`" in individual_modal
    assert "Record &amp; optional project link" not in html
    assert "<span>01</span> Record details" in html
    assert 'id="vehicle-sales-match-assistant"' in html
    assert 'api("/api/vehicle-sales/matches"' in sales
    assert "Use this vehicle" in sales
    assert 'id="ind-edit-make"' not in html
    assert 'api("/api/vehicle-sales/lookup"' in individual_modal
    assert "PT_openIndModalVehicleSale" in individual_modal
    assert "PT_selectIndModalVehicle" in individual_modal
    assert ".vehicle-details-selector-option" in styles
    assert ">Create or update PDF</button>" in builds
    assert ">Add completed photos or files</button>" in builds
    assert ">Import estimate parts</button>" in builds

