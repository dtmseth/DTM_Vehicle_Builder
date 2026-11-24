from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from dtm_buildsheet.app.services import temporary_tag_service, vehicle_sale_service
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


def _save_project_vehicle(paths: AppPaths) -> None:
    save_project(ProjectRecord(
        project_id="lake-2027",
        created_at="2027-01-01T00:00:00+00:00",
        updated_at="2027-01-01T00:00:00+00:00",
        customer=CustomerInfo(agency="Lake County Sheriff", quote_number="Q-1042"),
        build_units=[BuildUnit(
            unit_id="group-1",
            vehicle_model="Tahoe PPV",
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                unit_number="204",
                year="2027",
                make="Chevrolet",
                model="Tahoe PPV",
                color="White",
                vin="1GNSKDEC0PR765432",
            )],
        )],
    ), paths)


def test_temporary_tag_batch_prefills_saves_flattens_and_prints(tmp_path):
    paths = _paths(tmp_path)
    _save_project_vehicle(paths)
    vehicle_sale_service.save_record({
        "record_year": "2027",
        "purchased_from": "Lake County Sheriff",
        "date_received": "2027-03-04",
        "vehicle_year": "2027",
        "vehicle_make": "Chevrolet",
        "vehicle_model": "Tahoe PPV",
        "vehicle_unit_number": "204",
        "vin": "1GNSKDEC0PR765432",
        "quote_number": "Q-1042",
    }, paths, publish=False)

    candidates = temporary_tag_service.list_vehicle_candidates(paths)["records"]
    matching = [item for item in candidates if item["vin"] == "1GNSKDEC0PR765432"]
    assert len(matching) == 1
    assert matching[0]["agency"] == "Lake County Sheriff"
    assert matching[0]["date_received"] == "03/04/27"
    assert matching[0]["quote_number"] == "Q-1042"

    batch = temporary_tag_service.new_batch()
    batch["name"] = "March yard arrivals"
    batch["items"] = [
        {**matching[0], "item_id": "02445725-4c02-4e20-879f-1333d51b6492"},
        {
            "item_id": "73ef1a58-5867-49dd-ad15-e9e79efe610b",
            "source_type": "manual",
            "source_label": "Manual entry",
            "agency": "Pine County",
            "vin": "ABCD",
            "quote_number": "Q-2044",
            "date_received": "2027-03-05",
            "vehicle_summary": "Manual yard vehicle",
        },
    ]
    result = temporary_tag_service.save_batch(batch, paths)
    assert result["validation"]["complete"] is True
    assert Path(result["record"]["pdf_path"]).is_file()
    stored_path = tmp_path / "temporary_vehicle_tags" / f"{batch['batch_id']}.json"
    assert json.loads(stored_path.read_text(encoding="utf-8"))["name"] == "March yard arrivals"
    assert temporary_tag_service.list_batches(paths)["records"][0]["batch_id"] == batch["batch_id"]

    document = fitz.open(result["record"]["pdf_path"])
    assert document.page_count == 2
    assert document[0].rect == fitz.Rect(0, 0, 792, 612)
    assert all(list(page.widgets() or []) == [] for page in document)
    drawings = document[0].get_drawings()
    for hidden_guide in (
        fitz.Rect(126.72, 28.8, 161.28, 43.2),
        fitz.Rect(630.72, 28.8, 665.28, 43.2),
        fitz.Rect(126.72, 388.8, 161.28, 403.2),
        fitz.Rect(630.72, 388.8, 665.28, 403.2),
        fitz.Rect(12.96, 432.0, 779.04, 432.0),
    ):
        assert any(
            drawing["fill"] == (1.0, 1.0, 1.0)
            and drawing["rect"].contains(hidden_guide)
            for drawing in drawings
        )
    first_text = document[0].get_text()
    second_text = document[1].get_text()
    assert first_text.count("Lake") == 2
    assert first_text.count("Sheriff") == 2
    assert first_text.count("5432") == 2
    assert first_text.count("Q-1042") == 2
    assert first_text.count("03/04/27") == 2
    assert second_text.count("Pine") == 2
    assert second_text.count("County") == 2
    assert second_text.count("ABCD") == 2
    document.close()

    completed = type(
        "Completed", (),
        {"returncode": 0, "stdout": "system default destination: Yard Printer\n", "stderr": ""},
    )()
    with patch(
        "dtm_buildsheet.app.services.temporary_tag_service.subprocess.run",
        side_effect=[completed, completed],
    ) as process, patch(
        "dtm_buildsheet.app.services.temporary_tag_service.sys.platform", "darwin",
    ):
        printed = temporary_tag_service.print_batch_pdf(batch["batch_id"], paths)
    assert printed["ok"] is True
    assert printed["printer_name"] == "Yard Printer"
    assert "2 tag sheet(s)" in printed["message"]
    assert process.call_args_list[1].args[0] == [
        "lp",
        "-o", "media=Letter",
        "-o", "orientation-requested=4",
        "-o", "fit-to-page",
        result["record"]["pdf_path"],
    ]


def test_temporary_tag_missing_data_requires_explicit_output_confirmation(tmp_path):
    paths = _paths(tmp_path)
    batch = temporary_tag_service.new_batch()
    batch["items"] = [{
        "item_id": "02445725-4c02-4e20-879f-1333d51b6492",
        "source_type": "manual",
        "source_label": "Manual entry",
        "agency": "",
        "vin": "12",
        "quote_number": "",
        "date_received": "",
    }]
    saved = temporary_tag_service.save_batch(batch, paths)
    warning = saved["validation"]["item_warnings"][0]
    assert warning["missing_fields"] == [
        "Agency", "Quote number", "Date received", "VIN (at least four characters)",
    ]
    with pytest.raises(ValueError, match="confirm before continuing"):
        temporary_tag_service.open_batch_pdf(batch["batch_id"], paths)


def test_temporary_tag_agency_uses_largest_readable_wrapped_layout():
    large_rect = fitz.Rect(21.6, 95.04, 385.92, 208.8)
    lines, size = temporary_tag_service._largest_text_layout(  # noqa: SLF001
        "United States Immigration and Customs Enforcement",
        large_rect,
        max_lines=2,
    )
    assert len(lines) == 2
    assert " ".join(lines) == "United States Immigration and Customs Enforcement"
    assert size > 25

    short_lines, short_size = temporary_tag_service._largest_text_layout(  # noqa: SLF001
        "FBI", large_rect, max_lines=2,
    )
    assert short_lines == ["FBI"]
    assert short_size > 70


def test_temporary_tag_vin_and_date_scale_without_wrapping():
    vin_rect = fitz.Rect(406.08, 95.04, 770.4, 208.8)
    vin_size = temporary_tag_service._single_line_fitted_size(  # noqa: SLF001
        "5432", vin_rect, preferred_size=96,
    )
    assert 90 < vin_size <= 96

    date_rect = fitz.Rect(406.08, 246.96, 770.4, 360.72)
    date_size = temporary_tag_service._single_line_fitted_size(  # noqa: SLF001
        "11/10/26", date_rect, preferred_size=78,
    )
    assert 60 < date_size <= 86


def test_temporary_tags_have_a_dedicated_forms_workspace_and_operational_access():
    assert required_capabilities(
        "GET", "/api/temporary-tags/candidates",
    ) == frozenset({Capability.PROJECTS_VIEW, Capability.OPERATIONS_VIEW})
    assert required_capabilities(
        "POST", "/api/temporary-tags/print-pdf",
    ) == frozenset({Capability.PROJECTS_VIEW, Capability.OPERATIONS_VIEW})

    ui_root = Path(__file__).parents[1] / "src" / "dtm_buildsheet" / "ui"
    html = (ui_root / "index.html").read_text(encoding="utf-8")
    tabs = (ui_root / "js" / "tabs.js").read_text(encoding="utf-8")
    tags = (ui_root / "js" / "temporary_tags.js").read_text(encoding="utf-8")
    styles = (ui_root / "styles.css").read_text(encoding="utf-8")
    assert 'data-tab="forms"' in html
    assert 'id="tab-forms"' in html
    assert 'id="temporary-tags-print"' in html
    assert "Some tags are missing data" in html
    assert 'tab === "forms"' in tabs
    assert "initTemporaryTagsTab" in tabs
    assert 'api("/api/temporary-tags/candidates"' in tags
    assert 'api("/api/temporary-tags/save"' in tags
    assert '"print-pdf"' in tags
    assert "allow_incomplete" in tags
    assert "Manual tag" in html
    assert 'placeholder="MM/DD/YY"' in tags
    assert 'maxlength="8"' in tags
    assert 'type="date"' not in tags
    assert "_temporaryTagFormatDate" in tags
    assert '<textarea data-temporary-tag-field="agency"' in tags
    assert "_temporaryTagsResizeAgencyField" in tags
    assert ".temporary-tags-picker,.temporary-tags-editor{min-width:0" in styles
    assert "background:var(--surface);color:var(--text)" in styles
    assert ".temporary-tags-item{width:100%;max-width:100%;min-width:0;overflow:hidden" in styles
    assert "grid-template-columns:minmax(0,1.3fr) minmax(0,1fr)" in styles
    assert "@media(max-width:1250px){.temporary-tags-item-grid{grid-template-columns:repeat(2,minmax(0,1fr))}" in styles
    assert ".temporary-tags-item-grid :is(input,textarea){box-sizing:border-box;min-height:34px" in styles
    assert ".temporary-tags-item-grid textarea{max-height:92px;resize:none;overflow:hidden}" in styles
