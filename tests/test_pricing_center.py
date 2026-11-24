"""Focused Pricing Center workflow tests."""

from __future__ import annotations

import base64
import io
import shutil
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import fitz
from openpyxl import Workbook, load_workbook

from dtm_buildsheet.app.services import pricing_center_service as pricing
from dtm_buildsheet.paths import AppPaths


ROOT = Path(__file__).parents[1]
UI_ROOT = ROOT / "src" / "dtm_buildsheet" / "ui"


def _upload(name: str, content: bytes) -> dict:
    return {"filename": name, "content_base64": base64.b64encode(content).decode("ascii")}


def _workbook_bytes(headers: list[str], row: list[object]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.cell(1, 1, "Generation Date")
    sheet.cell(1, 3, "11/19/2026")
    for column, value in enumerate(headers, start=1):
        sheet.cell(3, column, value)
    for column, value in enumerate(row, start=1):
        sheet.cell(4, column, value)
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_vendor_retail_is_suggested_as_msrp_and_map_is_the_custom_vendor_price():
    mapping = pricing._suggest_mapping(["Part Number", "Retail", "Our Retail", "MAP"])

    assert mapping["sku"] == "Part Number"
    assert mapping["msrp"] == "Retail"
    assert mapping["agency_price"] == "MAP"
    assert "retail" not in mapping
    assert "map_price" not in mapping


def test_pdf_currency_parser_accepts_spaces_inserted_inside_numbers():
    assert pricing._money("$ 5 ,673") == pricing.Decimal("5673.00")  # noqa: SLF001
    assert pricing._money("$ 1 0,237") == pricing.Decimal("10237.00")  # noqa: SLF001


def test_builtin_vendor_templates_cover_every_supplied_format():
    expected = {
        "Stalker_Radar_Internal_Pricing_2026-11-16.xlsx": "stalker-internal-xlsx",
        "Troy Products NEW Master Price List - 30 Percent Discount.xlsx": "troy-master-xlsx",
        "STALKER Radar DTM Fleet Pricing 10-26-26.pdf": "stalker-dtm-pdf",
        "Whelen June 2026-Dec 2026.xlsx": "whelen-compare-xlsx",
        "Santa Cruz Jan 2026.xlsx": "santa-cruz-xlsx",
        "Tiger Tough Jan 2026.xlsx": "tigertough-seat-covers-xlsx",
        "Kussmaul Sept 2026.xlsx": "kussmaul-xlsx",
        "Truck Vault 2025.xlsx": "truckvault-xlsx",
        "REDARC Sept 25.xlsx": "redarc-xlsx",
        "SETINA OCT 2026.xlsx": "setina-xlsx",
        "NightRide Dealer Pricing and Terms 8-1-2026.pdf": "nightride-pdf",
        "Pac Tool Mounts 1-1-2026.pdf": "pac-pdf",
        "TigerTough Floor Liner Pricing 2026.xlsx": "tigertough-floor-liners-xlsx",
        "GAMBER-JOHNSON 65% July 25.xlsx": "gamber-program-xlsx",
        "Soundoff Signal 2026.xlsx": "soundoff-xlsx",
        "Patrol PC 2026.pdf": "patrol-pc-pdf",
        "Gamber Johnson July 2025.xlsx": "gamber-gold-xlsx",
        "AnyGlide Sept 2026.pdf": "anyglide-pdf",
        "Westin May 2026.xlsx": "westin-xlsx",
        "Havis-Master-MSRP_11-20-2026A.xlsx": "havis-master-msrp-xlsx",
        "Angel Armor Jan 2026.pdf": "angel-armor-pdf",
    }
    assert len(pricing._BUILTIN_VENDOR_TEMPLATES) == len(expected)  # noqa: SLF001
    for filename, template_id in expected.items():
        template = pricing._builtin_template(filename, "", Path(filename).suffix.lower())  # noqa: SLF001
        assert template and template["id"] == template_id


def test_file_parsing_fills_vendor_and_effective_date_before_column_confirmation(tmp_path: Path):
    inspected = pricing.inspect_price_list(paths=AppPaths(workspace_dir=tmp_path), payload={
        **_upload(
            "Troy Products NEW Master Price List - 30 Percent Discount.xlsx",
            _workbook_bytes(
                ["TROY PART #", "ITEM DESCRIPTION", "MSRP", "DISCOUNT %"],
                ["CC-TROY-1", "Console", 1000, 700],
            ),
        ),
        "vendor": "",
        "effective_date": "",
    })

    assert inspected["vendor"] == "Troy"
    assert inspected["vendor_auto_detected"] is True
    assert date.fromisoformat(inspected["effective_date"])
    assert inspected["template_id"] == "troy-master-xlsx"


def test_repeated_headers_are_removed_from_preview_and_normalized_parts(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    content = (
        "Part Number,Description,Cost,MSRP\n"
        "ABC-1,Warning light,100.00,150.00\n"
        "Part Number,Description,Cost,MSRP\n"
        "ABC-2,Siren,200.00,300.00\n"
    ).encode()
    inspected = pricing.inspect_price_list(paths, {
        **_upload("generic.csv", content), "vendor": "Example", "effective_date": "2026-11-01",
    })
    candidate = inspected["candidates"][0]
    assert all(row[0] != "Part Number" for row in candidate["rows"])
    confirmed = pricing.confirm_mapping(paths, {
        "session_id": inspected["session_id"], "candidate_id": candidate["id"],
        "vendor": "Example", "effective_date": "2026-11-01",
        "mapping": {"sku": "Part Number", "description": "Description", "cost": "Cost", "msrp": "MSRP"},
    })
    assert confirmed["rows_ready"] == 2
    session = pricing.PricingStore(paths).get("import_sessions", inspected["session_id"])
    normalized = pricing._json_read(session["normalized_path"])  # noqa: SLF001
    assert [row["sku"] for row in normalized] == ["ABC-1", "ABC-2"]


def test_parallel_startup_migrates_an_existing_rules_database_once(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    paths.workspace_pricing_dir.mkdir(parents=True)
    database_path = paths.workspace_pricing_dir / "pricing_center.sqlite3"
    with sqlite3.connect(database_path) as database:
        database.execute(
            "CREATE TABLE rules (id TEXT PRIMARY KEY,name TEXT NOT NULL,scope_type TEXT NOT NULL,"
            "scope_value TEXT NOT NULL,method TEXT NOT NULL,amount TEXT NOT NULL,source_field TEXT NOT NULL,"
            "enabled INTEGER NOT NULL,updated_at TEXT NOT NULL,group_name TEXT NOT NULL DEFAULT '')"
        )
        database.execute(
            "INSERT INTO rules VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("legacy", "Legacy", "brand", "Legacy", "markup_percent_cost", "10", "cost", 1, pricing._now(), ""),  # noqa: SLF001
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: pricing.summary(paths), range(4)))

    assert all(result["ok"] for result in results)
    store = pricing.PricingStore(paths)
    migrated = store.get("rules", "legacy")
    assert migrated["cost_enabled"] == 0
    assert migrated["cost_discount_enabled"] == 0
    whelen = store.get("rules", "brand-whelen")
    assert (whelen["method"], whelen["amount"]) == ("discount_percent_msrp", "36")
    assert (whelen["cost_method"], whelen["cost_amount"]) == ("discount_percent_msrp", "40")
    assert (whelen["cost_discount_enabled"], whelen["cost_discount_percent"]) == (1, "8")
    angel_armor = store.get("rules", "brand-angel-armor")
    assert (angel_armor["source_field"], angel_armor["cost_source_field"]) == ("agency_price", "cost")
    gamber = store.get("rules", "brand-gamber")
    assert (gamber["method"], gamber["source_field"]) == ("imported_value", "agency_price")
    assert (gamber["cost_method"], gamber["cost_source_field"]) == ("imported_value", "cost")
    lind = store.get("rules", "brand-lind")
    assert (lind["method"], lind["source_field"]) == ("imported_value", "agency_price")
    with store.connect() as database:
        assert database.execute(
            "SELECT 1 FROM reference_cache WHERE key=?", (pricing._VENDOR_GUIDE_RULE_VERSION,),  # noqa: SLF001
        ).fetchone()
    pricing._INITIALIZED_DATABASES.discard(database_path.resolve())  # noqa: SLF001
    restarted = pricing.PricingStore(paths)
    assert restarted.get("rules", "brand-angel-armor")["name"] == "Angel Armor Pro and Agency pricing"


def test_builtin_template_infers_vendor_date_and_still_requires_column_confirmation(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    content = _workbook_bytes(
        ["Item Number", "MSRP", "Reseller Price", "Starting Date"],
        ["S0321004-IW-BLK", 267, 189.57, "2026-01-01"],
    )
    inspected = pricing.inspect_price_list(paths=paths, payload={
        **_upload("Tiger Tough Jan 2026.xlsx", content), "vendor": "", "effective_date": "",
    })

    assert inspected["vendor"] == "TigerTough"
    assert inspected["vendor_auto_detected"] is True
    assert inspected["effective_date"] == "2026-01-01"
    assert inspected["preset_applied"] is True
    assert inspected["template_id"] == "tigertough-seat-covers-xlsx"
    assert inspected["candidates"][0]["suggested_mapping"] == {
        "sku": "Item Number", "cost": "Reseller Price", "msrp": "MSRP",
        "effective_date": "Starting Date",
    }
    pricing.confirm_mapping(paths, {
        "session_id": inspected["session_id"], "candidate_id": inspected["candidates"][0]["id"],
        "mapping": inspected["candidates"][0]["suggested_mapping"], "vendor": inspected["vendor"],
        "effective_date": inspected["effective_date"],
    })
    session = pricing.PricingStore(paths).get("import_sessions", inspected["session_id"])
    assert pricing._json_read(session["normalized_path"])[0]["brand"] == "TigerTough"  # noqa: SLF001


def test_anyglide_confirm_assignments_loads_pricing_preview(tmp_path: Path, monkeypatch):
    paths = AppPaths(workspace_dir=tmp_path)
    candidate = pricing._canonical_candidate(  # noqa: SLF001
        "AnyGlide catalog price tables", ["SKU", "Description", "Dealer", "MSRP"],
        [["6416-1", '16" Wide Single Box', "$ 1,365", "$ 1 ,706"]],
        "template:anyglide",
    )
    monkeypatch.setattr(
        pricing, "_custom_template_candidates", lambda _path, _parser: [candidate],
    )
    inspected = pricing.inspect_price_list(paths, {
        **_upload("AnyGlide Sept 2026.pdf", b"%PDF-1.4\nmock"),
        "vendor": "", "effective_date": "",
    })
    pricing.confirm_mapping(paths, {
        "session_id": inspected["session_id"],
        "candidate_id": inspected["candidates"][0]["id"],
        "mapping": inspected["candidates"][0]["suggested_mapping"],
        "vendor": inspected["vendor"], "effective_date": inspected["effective_date"],
    })
    headers = [
        "Name*", "SKU (optional)", "Vendor (optional)", "Cost (optional)",
        "Retail (optional)", "Brand (optional)", "Shopmonkey ID (optional)",
    ]
    pricing.upload_snapshot(paths, _upload(
        "shopmonkey.xlsx",
        _workbook_bytes(headers, ["AnyGlide box", "6416-1", "AnyGlide", 1300, 1600, "AnyGlide", "sm-any-1"]),
    ))

    preview = pricing.rule_preview(paths, {"session_id": inspected["session_id"]})

    assert preview["examples"][0]["sku"] == "6416-1"
    assert preview["examples"][0]["new_retail"] == "1706.00"
    assert pricing._reference_cache_exists(  # noqa: SLF001
        pricing.PricingStore(paths),
        f"{pricing._ANYGLIDE_PARSER_VERSION}:{inspected['session_id']}",  # noqa: SLF001
    )


def test_angel_armor_template_expands_panel_skus_from_application_rows(tmp_path: Path):
    source = tmp_path / "Angel Armor Jan 2026.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "FORD\nPIU/ EXPLORER MSRP AGENCY PRO DRIVER FRONT PASSENGER FRONT\n"
        "2011-2019 $2144.00 $904.00 $754.00 IIIA 01-00001 01-00002",
    )
    document.save(source)
    document.close()

    candidate = pricing._parse_angel_armor_pdf(source)[0]  # noqa: SLF001

    assert candidate["row_count"] == 2
    assert candidate["rows"][0] == [
        "01-00001", "FORD PIU/ EXPLORER 2011-2019 IIIA Panel", "754.00", "2144.00", "904.00",
    ]


def test_soundoff_template_combines_product_sheets(tmp_path: Path):
    source = tmp_path / "Soundoff Signal 2026.xlsx"
    workbook = Workbook()
    workbook.active.title = "Standard Items"
    workbook.create_sheet("Accessories")
    for index, sheet in enumerate(workbook.worksheets, start=1):
        sheet.append(["Price list"])
        for _ in range(4):
            sheet.append([])
        sheet.append(["", "PART NUMBER", "DESCRIPTION", "LIST PRICE", "WARRANTY"])
        sheet.append(["", f"PART-{index}", f"Product {index}", f"${index}25.00", "5 Years"])
    workbook.save(source)
    workbook.close()

    candidate = pricing._parse_soundoff_xlsx(source)[0]  # noqa: SLF001

    assert candidate["row_count"] == 2
    assert [row[0] for row in candidate["rows"]] == ["PART-1", "PART-2"]
    assert candidate["rows"][0][2:] == ["50.00", "125.00"]
    template = pricing._builtin_template(source.name, "", ".xlsx")  # noqa: SLF001
    assert pricing._template_mapping(template, candidate)["cost"] == "Calculated Cost (40% of MSRP)"  # noqa: SLF001


def test_truckvault_template_calculates_standard_buy_cost(tmp_path: Path):
    source = tmp_path / "Truck Vault 2025.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Make", "Model", "Stock Code", "Description", "Long Description", "MSRP"])
    sheet.append(["Ford", "F150", "TV-100", "F150 drawer", "", 1000])
    workbook.save(source)
    workbook.close()

    candidate = pricing._parse_truckvault_xlsx(source)[0]  # noqa: SLF001

    assert candidate["rows"] == [["TV-100", "F150 drawer", "720.00", "1000.00"]]
    template = pricing._builtin_template(source.name, "", ".xlsx")  # noqa: SLF001
    assert pricing._template_mapping(template, candidate)["cost"] == "Calculated Cost (72% of MSRP)"  # noqa: SLF001


def test_patrol_pc_parser_keeps_included_zero_price_options():
    parsed = pricing._patrol_pc_table_row([  # noqa: SLF001
        "CELL-NO", "No embedded cellular modem.", "Included", "Included", "Included",
    ])

    assert parsed == ["CELL-NO", "No embedded cellular modem.", "0.00", "0.00", "0.00"]
    priced = ["CELL-NO", "No embedded cellular modem.", "25.00", "40.00", "30.00"]
    assert pricing._dedupe_patrol_pc_rows([parsed, priced]) == [priced]  # noqa: SLF001


def test_stalker_internal_parser_falls_back_when_manufacturer_sku_is_blank(tmp_path: Path):
    source = tmp_path / "Stalker_Radar_Internal_Pricing_2026-11-16.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Pricing"
    sheet.append([])
    sheet.append([
        "Internal SKU", "Manufacturer Part #", "Product", "List Price", "Our Cost",
    ])
    sheet.append(["STALKER-25547382", "", "Power Supply Kit", 50.50, 47.97])
    sheet.append(["015-0012-01", "015-0012-01", "Tripod", 440.75, 418.71])
    workbook.save(source)
    workbook.close()

    candidate = pricing._parse_stalker_internal_xlsx(source)[0]  # noqa: SLF001

    assert candidate["rows"][0][:4] == ["STALKER-25547382", "Power Supply Kit", "47.97", "50.5"]
    assert candidate["rows"][1][0] == "015-0012-01"


def test_troy_parser_combines_master_and_vehicle_specific_sheets(tmp_path: Path):
    source = tmp_path / "Troy Products NEW Master Price List - 30 Percent Discount.xlsx"
    workbook = Workbook()
    master = workbook.active
    master.title = "MASTER PRICE LIST"
    master.append(["TROY PART #", "ITEM DESCRIPTION", "MSRP", "DISCOUNT %"])
    master.append(["MASTER-1", "Master item", 100, 70])
    vehicle = workbook.create_sheet("2018-24 FORD EXPEDITION")
    vehicle.append(["TROY PART #", "ITEM DESCRIPTION", "MSRP", "DISCOUNT %"])
    vehicle.append(["CP-GB484012-T-PBK", "Vehicle-specific box", 3400, 2380])
    workbook.save(source)
    workbook.close()

    candidate = pricing._parse_troy_all_sheets_xlsx(source)[0]  # noqa: SLF001

    assert candidate["row_count"] == 2
    assert {row[0] for row in candidate["rows"]} == {"MASTER-1", "CP-GB484012-T-PBK"}


def test_gamber_template_imports_gold_cost_and_sell_for_the_whole_list(tmp_path: Path):
    source = tmp_path / "Gamber Johnson July 2025.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "2025 Gold - 7-1-25 II"
    sheet.append([
        "Code", "Product Category", "Item Number", "Product Description",
        "7/1/25 List Price", "Sell", "Gold",
    ])
    sheet.append(["", "MOUNTS", "7160-1000", "Gamber mount", 200, 140, 100])
    sheet.append(["", "POWER", "LPS-100", "LIND power supply", 300, 210, 165])
    firesale = workbook.create_sheet("Firesale")
    firesale.append(["Item Number", "Firesale Price"])
    firesale.append(["OLD-1", 20])
    workbook.save(source)
    workbook.close()

    inspected = pricing.inspect_price_list(AppPaths(workspace_dir=tmp_path / "workspace"), {
        **_upload(source.name, source.read_bytes()), "vendor": "", "effective_date": "",
    })
    candidate = inspected["candidates"][0]

    assert candidate["row_count"] == 2
    assert candidate["headers"] == [
        "Item Number", "Product Description", "Gold", "List Price", "Sell",
    ]
    assert candidate["suggested_mapping"] == {
        "sku": "Item Number", "description": "Product Description", "cost": "Gold",
        "msrp": "List Price", "agency_price": "Sell",
    }
    confirmed = pricing.confirm_mapping(AppPaths(workspace_dir=tmp_path / "workspace"), {
        "session_id": inspected["session_id"], "candidate_id": candidate["id"],
        "mapping": candidate["suggested_mapping"], "vendor": inspected["vendor"],
        "effective_date": inspected["effective_date"],
    })
    assert confirmed["rows_ready"] == 2
    store = pricing.PricingStore(AppPaths(workspace_dir=tmp_path / "workspace"))
    session = store.get("import_sessions", inspected["session_id"])
    normalized = pricing._json_read(session["normalized_path"])  # noqa: SLF001
    assert normalized[1]["description"] == "LIND power supply"
    assert (normalized[1]["cost"], normalized[1]["msrp"], normalized[1]["agency_price"]) == (
        "165.00", "300.00", "210.00",
    )


def test_havis_template_reads_msrp_and_effective_date_from_header(tmp_path: Path):
    source = tmp_path / "Havis-Master-MSRP_11-20-2026A.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "20261120"
    sheet.append([])
    sheet.append([
        "Catalog No.", "Product Title", "Status", "Replacement Product(s)",
        "Last Change Date", "MSRP Effective 11/20/2026",
    ])
    sheet.append(["C-HDM-100", "Heavy-duty mount", "PRICE CHANGE", "", "1/1/2026", 500])
    sheet.append(["C-HDM-100", "Heavy-duty mount", "ACTIVE", "", "8/25/2025", 500])
    sheet.append(["C-HDM-200", "Light-duty mount", "ACTIVE", "", "8/25/2025", 250])
    definitions = workbook.create_sheet("Status Definitions")
    definitions.append(["Status", "Definition"])
    definitions.append(["ACTIVE", "Current product"])
    workbook.save(source)
    workbook.close()

    candidate = pricing._parse_havis_master_xlsx(source)[0]  # noqa: SLF001
    template = pricing._builtin_template(source.name, "", ".xlsx")  # noqa: SLF001

    assert candidate["row_count"] == 2
    assert candidate["rows"][0] == ["C-HDM-100", "Heavy-duty mount", "500.00", "2026-11-20"]
    assert pricing._template_mapping(template, candidate) == {  # noqa: SLF001
        "sku": "Catalog No.",
        "description": "Product Title",
        "msrp": "MSRP",
        "effective_date": "Effective Date",
    }


def test_full_import_rule_reconcile_and_export_preserves_shopmonkey_row(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    csv_content = (
        "Part Number,Product Description,Dealer Cost,MSRP,Brand Name\n"
        "ABC-1,Warning light,100.00,160.00,Whelen\n"
    ).encode()
    inspected = pricing.inspect_price_list(paths, {
        **_upload("whelen.csv", csv_content),
        "vendor": "Whelen", "effective_date": "2026-11-01", "include_notes": True,
    })
    candidate = inspected["candidates"][0]
    confirmed = pricing.confirm_mapping(paths, {
        "session_id": inspected["session_id"], "candidate_id": candidate["id"],
        "vendor": "Whelen", "effective_date": "2026-11-01", "include_notes": True,
        "mapping": {
            "sku": "Part Number", "description": "Product Description",
            "cost": "Dealer Cost", "msrp": "MSRP", "brand": "Brand Name",
        },
    })
    assert confirmed["rows_ready"] == 1

    saved_rule = pricing.save_rule(paths, {
        "name": "Whelen standard", "scope_type": "brand", "scope_value": "Whelen",
        "method": "markup_percent_cost", "amount": "25", "enabled": True,
    })
    headers = [
        "Name*", "Note (optional)", "URL (optional)", "SKU (optional)",
        "Part # (optional)", "Vendor (optional)", "Cost (optional)",
        "Retail (optional)", "Brand (optional)", "Shopmonkey ID (optional)",
    ]
    existing = [
        "Warning light", "Install in grille", "https://example.invalid/abc", "ABC-1",
        "ABC-1", "Whelen", 90.0, 110.0, "Whelen", "sm-abc-1",
    ]
    snapshot = pricing.upload_snapshot(paths, _upload("shopmonkey.xlsx", _workbook_bytes(headers, existing)))
    assert snapshot["row_count"] == 1

    # Preserve the raw PDF-style value but simulate a previously normalized
    # blank so rule preview proves it can repair saved imports in place.
    store = pricing.PricingStore(paths)
    session = store.get("import_sessions", inspected["session_id"])
    normalized = pricing._json_read(session["normalized_path"])  # noqa: SLF001
    normalized[0]["msrp"] = ""
    pricing._json_write(Path(session["normalized_path"]), normalized)  # noqa: SLF001
    matrices = pricing._json_read(session["matrix_path"])  # noqa: SLF001
    matrices[0]["rows"][0][3] = "$ 1 60.00"
    pricing._json_write(Path(session["matrix_path"]), matrices)  # noqa: SLF001

    automatic = pricing.rule_preview(paths, {"session_id": inspected["session_id"]})
    assert automatic["choice"] == "auto"
    assert automatic["examples"][0]["current_cost"] == "90.00"
    assert automatic["examples"][0]["new_cost"] == "100.00"
    assert automatic["examples"][0]["new_retail"] == "125.00"
    assert automatic["examples"][0]["cost_source_value"] == "100.00"
    assert automatic["examples"][0]["cost_adjustment"] == "Use vendor-list cost"
    assert automatic["examples"][0]["retail_source_value"] == "100.00"
    assert automatic["examples"][0]["retail_adjustment"] == "25% markup"
    assert automatic["applied_rules"][0]["id"] == saved_rule["rule_id"]
    assert automatic["applied_rules"][0]["method"] == "markup_percent_cost"
    assert pricing._json_read(session["normalized_path"])[0]["msrp"] == "160.00"  # noqa: SLF001
    searched = pricing.rule_preview(paths, {
        "session_id": inspected["session_id"], "search": "warning light",
    })
    assert searched["example_total"] == 1
    assert searched["examples"][0]["sku"] == "ABC-1"
    no_match = pricing.rule_preview(paths, {
        "session_id": inspected["session_id"], "search": "does-not-exist",
    })
    assert no_match["example_total"] == 0
    assert no_match["examples"] == []
    removed = pricing.rule_preview(paths, {"session_id": inspected["session_id"], "choice": "none"})
    assert removed["examples"][0]["new_retail"] == ""
    selected = pricing.rule_preview(paths, {
        "session_id": inspected["session_id"], "choice": saved_rule["rule_id"],
    })
    assert selected["choice"] == saved_rule["rule_id"]
    assert selected["examples"][0]["rule_name"] == "Whelen standard"
    assert pricing._calculation_adjustment(  # noqa: SLF001
        "discount_percent_msrp", "40", "msrp", cost_discount="8",
    ) == "40% off, then 8% off"

    run = pricing.reconcile(paths, {
        "session_id": inspected["session_id"], "snapshot_id": snapshot["snapshot_id"],
    })
    assert run["counts"]["updated"] == 1
    review = pricing.get_review(paths, {"run_id": run["run_id"], "status": "updated"})
    assert review["selected_count"] == 1
    assert review["rows"][0]["new_retail"] == "125.00"
    without_notes = pricing.update_review_settings(paths, {"run_id": run["run_id"], "include_notes": False})
    assert without_notes["include_notes"] is False
    assert "MSRP:" not in pricing.get_review(paths, {"run_id": run["run_id"]})["rows"][0]["new_note"]
    pricing.update_review_settings(paths, {"run_id": run["run_id"], "include_notes": True})

    resumed = pricing.resume_import(paths, {"session_id": inspected["session_id"]})
    assert resumed["run_id"] == run["run_id"]
    assert resumed["session"]["status"] == "mapped"
    assert pricing.finalize_review(paths, {"run_id": run["run_id"]})["status"] == "ready"
    listed = next(item for item in pricing.summary(paths)["sessions"] if item["id"] == inspected["session_id"])
    assert listed["can_export"] is True
    assert listed["continue_import"] is False
    assert len(listed["applied_rule_ids"]) == 1
    applied = pricing.PricingStore(paths).get("rules", listed["applied_rule_ids"][0])
    assert applied["name"] == "Whelen standard"
    combined = pricing.create_bulk_export(paths, {"mode": "changed"})
    assert combined["row_count"] == 1
    assert combined["download_url"].startswith("/api/pricing/download/")
    combined_all = pricing.create_bulk_export(paths, {"mode": "all"})
    assert combined_all["exported_list_count"] == 1
    assert pricing.PricingStore(paths).get("runs", run["run_id"])["status"] == "exported"
    assert pricing.mark_all_imported(paths, {})["imported_count"] == 1
    assert pricing.PricingStore(paths).get("runs", run["run_id"])["status"] == "imported"

    exported = pricing.create_export(paths, {"run_id": run["run_id"]})
    repeated_export = pricing.create_export(paths, {"run_id": run["run_id"]})
    assert repeated_export["row_count"] == exported["row_count"]
    content, mime, filename = pricing.get_artifact(paths, exported["artifact_id"])
    assert filename.endswith(".xlsx")
    assert "spreadsheetml" in mime
    workbook = load_workbook(io.BytesIO(content), data_only=True)
    sheet = workbook.active
    assert [sheet.cell(1, column).value for column in range(1, len(headers) + 1)] == headers
    values = [sheet.cell(2, column).value for column in range(1, len(headers) + 1)]
    workbook.close()
    result = dict(zip(headers, values, strict=True))
    assert result["URL (optional)"] == "https://example.invalid/abc"
    assert result["Cost (optional)"] == 100
    assert result["Retail (optional)"] == 125
    assert "Install in grille" in result["Note (optional)"]
    assert "MSRP: $160.00" in result["Note (optional)"]
    assert "Price list effective: 2026-11-01" in result["Note (optional)"]
    assert pricing.mark_imported(paths, {"run_id": run["run_id"]})["status"] == "imported"
    verification = pricing.upload_snapshot(paths, _upload("shopmonkey-after-import.xlsx", content))
    assert verification["verified_runs"] == 0


def test_inventory_coverage_lists_shopmonkey_parts_missing_from_price_lists(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    inspected = pricing.inspect_price_list(paths, {
        **_upload(
            "example.csv",
            b"Part Number,Description,Cost,MSRP\nMATCH-1,Matched light,10,20\nMISS-2,Missing siren,30,50\n",
        ),
        "vendor": "Example", "effective_date": "2026-11-24",
    })
    candidate = inspected["candidates"][0]
    pricing.confirm_mapping(paths, {
        "session_id": inspected["session_id"], "candidate_id": candidate["id"],
        "vendor": "Example", "effective_date": "2026-11-24",
        "mapping": {
            "sku": "Part Number", "description": "Description", "cost": "Cost", "msrp": "MSRP",
        },
    })
    headers = [
        "Name*", "SKU (optional)", "Vendor (optional)", "Cost (optional)",
        "Retail (optional)", "Brand (optional)", "Shopmonkey ID (optional)",
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.cell(1, 1, "Generation Date")
    sheet.cell(1, 3, "11/24/2026")
    for column, value in enumerate(headers, start=1):
        sheet.cell(3, column, value)
    inventory_rows = [
        ["Matched light", "MATCH-1", "Example", 10, 20, "Example", "sm-1"],
        ["Forgotten Shopmonkey part", "SM-ONLY", "Other Vendor", 40, 70, "Other Brand", "sm-2"],
    ]
    for row_index, row in enumerate(inventory_rows, start=4):
        for column, value in enumerate(row, start=1):
            sheet.cell(row_index, column, value)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    pricing.upload_snapshot(paths, _upload(
        "shopmonkey.xlsx", stream.getvalue(),
    ))

    coverage = pricing.inventory_coverage(paths, {"page": 1, "page_size": 20})
    assert coverage["stats"] == {
        "price_list_count": 1, "total_parts": 2, "unique_parts": 2,
        "shopmonkey_parts": 2, "matched_parts": 1, "unmatched_parts": 1,
    }
    assert coverage["rows"][0]["sku"] == "SM-ONLY"
    assert coverage["rows"][0]["description"] == "Forgotten Shopmonkey part"
    assert coverage["rows"][0]["shopmonkey_id"] == "sm-2"
    assert coverage["rows"][0]["reason"] == "Not found in imported price lists"
    assert coverage["brands"] == [{"name": "Other Brand", "value": "Other Brand", "count": 1}]
    assert pricing.inventory_coverage(paths, {"brand": "Example"})["total"] == 0
    assert pricing.inventory_coverage(paths, {"brand": "Other Brand"})["rows"][0]["sku"] == "SM-ONLY"
    summary = pricing.summary(paths)
    assert summary["price_list_stats"] == {
        "price_list_count": 1, "total_parts": 2, "unique_parts": 2,
    }
    assert summary["sessions"][0]["part_count"] == 2


def test_missing_vendor_description_retains_shopmonkey_name_and_old_matches_are_actionable(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    inspected = pricing.inspect_price_list(paths, {
        **_upload(
            "Tiger Tough Jan 2026.xlsx",
            _workbook_bytes(
                ["Item Number", "Reseller Price", "MSRP", "Starting Date"],
                ["TT-1", 90.00, 150.00, "2026-01-01"],
            ),
        ),
        "vendor": "TigerTough", "effective_date": "2026-01-01",
    })
    candidate = inspected["candidates"][0]
    pricing.confirm_mapping(paths, {
        "session_id": inspected["session_id"], "candidate_id": candidate["id"],
        "vendor": "TigerTough", "effective_date": "2026-01-01",
        "mapping": {"sku": "Item Number", "cost": "Reseller Price", "msrp": "MSRP"},
    })
    headers = [
        "Name*", "Note (optional)", "SKU (optional)", "Vendor (optional)",
        "Cost (optional)", "Retail (optional)", "Brand (optional)",
        "Shopmonkey ID (optional)",
    ]
    existing = ["TigerTough seat cover", "Existing note", "TT-1", "TigerTough", 85, 140, "TigerTough", "sm-tt-1"]
    snapshot_content = _workbook_bytes(headers, existing)
    snapshot = pricing.upload_snapshot(paths, _upload("shopmonkey.xlsx", snapshot_content))
    run = pricing.reconcile(paths, {
        "session_id": inspected["session_id"], "snapshot_id": snapshot["snapshot_id"],
    })
    review = pricing.get_review(paths, {"run_id": run["run_id"]})
    assert review["rows"][0]["description"] == "TigerTough seat cover"
    assert review["rows"][0]["description_source"] == "shopmonkey"
    pricing.finalize_review(paths, {"run_id": run["run_id"]})

    artifact = pricing.create_export(paths, {"run_id": run["run_id"]})
    content, _mime, _filename = pricing.get_artifact(paths, artifact["artifact_id"])
    workbook = load_workbook(io.BytesIO(content), data_only=True)
    assert workbook.active.cell(1, 1).value == "Name*"
    assert workbook.active.cell(2, 1).value == "TigerTough seat cover"
    workbook.close()

    pricing.upload_snapshot(paths, _upload("shopmonkey-newer.xlsx", snapshot_content))
    listed = next(item for item in pricing.summary(paths)["sessions"] if item["id"] == inspected["session_id"])
    assert listed["needs_rematch"] is True
    assert listed["can_export"] is False
    assert pricing.resume_import(paths, {"session_id": inspected["session_id"]})["needs_rematch"] is True
    with pytest.raises(pricing.PricingCenterError, match="Continue import"):
        pricing.create_bulk_export(paths, {"mode": "changed"})


def test_saved_unfinished_price_list_can_resume_and_delete(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    inspected = pricing.inspect_price_list(paths, {
        **_upload("unfinished.csv", b"Part Number,Cost\nABC-1,10.00\n"),
        "vendor": "Example Vendor", "effective_date": "2026-11-20",
    })
    stored = pricing.PricingStore(paths).get("import_sessions", inspected["session_id"])
    source_path = Path(stored["source_path"])

    resumed = pricing.resume_import(paths, {"session_id": inspected["session_id"]})
    assert resumed["session"]["status"] == "inspected"
    assert resumed["candidates"][0]["rows"][0][0] == "ABC-1"
    listed = next(item for item in pricing.summary(paths)["sessions"] if item["id"] == inspected["session_id"])
    assert listed["can_export"] is False
    assert listed["continue_import"] is True

    assert pricing.delete_import(paths, {"session_id": inspected["session_id"]})["deleted"] is True
    assert pricing.PricingStore(paths).get("import_sessions", inspected["session_id"]) is None
    assert not source_path.exists()


def test_shopmonkey_export_is_reusable_for_twenty_four_hours():
    now = datetime.now(timezone.utc)

    assert pricing._snapshot_is_stale({"created_at": (now - timedelta(hours=23)).isoformat()}) is False  # noqa: SLF001
    assert pricing._snapshot_is_stale({"created_at": (now - timedelta(hours=25)).isoformat()}) is True  # noqa: SLF001


def test_pac_catalog_aliases_match_existing_shopmonkey_parts(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    inspected = pricing.inspect_price_list(paths, {
        **_upload(
            "pac.csv",
            b"Part Number,Description,Cost,MSRP,Brand\n1004,HANDLELOK,34.50,45.95,PAC\n",
        ),
        "vendor": "PAC", "effective_date": "2026-01-01",
    })
    candidate = inspected["candidates"][0]
    pricing.confirm_mapping(paths, {
        "session_id": inspected["session_id"], "candidate_id": candidate["id"],
        "vendor": "PAC", "effective_date": "2026-01-01",
        "mapping": {
            "sku": "Part Number", "description": "Description", "cost": "Cost",
            "msrp": "MSRP", "brand": "Brand",
        },
    })
    pricing.save_rule(paths, {
        "name": "PAC standard", "scope_type": "brand", "scope_value": "PAC",
        "method": "markup_percent_cost", "amount": "26.67", "enabled": True,
    })
    headers = [
        "Name*", "Note (optional)", "SKU (optional)", "Vendor (optional)",
        "Cost (optional)", "Retail (optional)", "Brand (optional)",
        "Shopmonkey ID (optional)",
    ]
    existing = ["HANDLELOK", "", "1004", "PAC TOOLS", 30, 40, "PAC Tool Mounts", "pac-1004"]
    snapshot = pricing.upload_snapshot(paths, _upload("shopmonkey.xlsx", _workbook_bytes(headers, existing)))

    run = pricing.reconcile(paths, {
        "session_id": inspected["session_id"], "snapshot_id": snapshot["snapshot_id"],
    })
    review = pricing.get_review(paths, {"run_id": run["run_id"], "status": "updated"})

    assert run["counts"]["updated"] == 1
    assert run["counts"]["possible_new"] == 0
    assert review["rows"][0]["shopmonkey_id"] == "pac-1004"
    assert review["rows"][0]["reason"] == "Brand + SKU"


def test_sku_exception_has_priority_and_supports_flat_pricing(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    pricing.save_rule(paths, {
        "name": "Brand rule", "scope_type": "brand", "scope_value": "REDARC",
        "method": "markup_percent_cost", "amount": "41.43", "enabled": True,
    })
    pricing.save_rule(paths, {
        "name": "Battery exception", "scope_type": "sku", "scope_value": "LBAT12150-SB",
        "group_name": "REDARC", "method": "flat_markup_cost", "amount": "50", "enabled": True,
    })
    rules = pricing.PricingStore(paths).list_rows("rules")
    pac_exceptions = [rule for rule in rules if rule["id"].startswith("sku-pac-")]
    assert len(pac_exceptions) == 30
    assert {rule["group_name"] for rule in pac_exceptions} == {"PAC"}
    assert all(rule["method"] != "unchanged" for rule in rules)
    assert next(rule for rule in rules if rule["id"] == "sku-setina-ck1266")["amount"] == "0"
    chosen = pricing._select_rule(rules, {  # noqa: SLF001 - focused precedence check
        "sku": "LBAT12150-SB", "brand": "REDARC", "vendor": "REDARC",
    }, "session")
    assert chosen["scope_type"] == "sku"
    assert pricing.calculate_retail(chosen, {"cost": "100.00"}, None) == pricing.Decimal("150.00")
    assert pricing.calculate_retail({
        "method": "markup_percent_source", "amount": "10", "source_field": "agency_price",
    }, {"agency_price": "100.00"}, None) == pricing.Decimal("110.00")


def test_optional_cost_rule_runs_before_retail_and_sku_exceptions_do_not_replace_it(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    parent = pricing.save_rule(paths, {
        "name": "Example pricing", "scope_type": "brand", "scope_value": "Example",
        "method": "markup_percent_cost", "amount": "25", "source_field": "cost", "enabled": True,
        "cost_enabled": True, "cost_method": "discount_percent_msrp", "cost_amount": "20",
        "cost_source_field": "msrp", "cost_discount_enabled": True, "cost_discount_percent": "10",
    })
    pricing.save_rule(paths, {
        "name": "Example retail exception", "scope_type": "sku", "scope_value": "EX-1",
        "group_name": "Example", "method": "fixed_retail", "amount": "99", "source_field": "retail",
        "enabled": True, "cost_enabled": True, "cost_method": "fixed_retail", "cost_amount": "1",
    })
    rules = pricing.PricingStore(paths).list_rows("rules")
    parent_rule = next(rule for rule in rules if rule["id"] == parent["rule_id"])
    exception = next(rule for rule in rules if rule["scope_type"] == "sku" and rule["scope_value"] == "EX-1")

    calculated_cost = pricing.calculate_cost(parent_rule, {"cost": "60", "msrp": "100"}, None)
    calculated_retail = pricing.calculate_retail(parent_rule, {"cost": calculated_cost, "msrp": "100"}, None)
    selected_cost_rule = pricing._select_cost_rule(rules, {  # noqa: SLF001
        "sku": "EX-1", "brand": "Example", "vendor": "",
    }, "session")

    assert calculated_cost == pricing.Decimal("72.00")
    assert calculated_retail == pricing.Decimal("90.00")
    assert selected_cost_rule["id"] == parent["rule_id"]
    assert exception["cost_enabled"] == 0


def test_scope_options_merge_live_names_with_snapshot_part_counts(tmp_path: Path, monkeypatch):
    paths = AppPaths(workspace_dir=tmp_path)
    headers = [
        "Name*", "Note (optional)", "SKU (optional)", "Vendor (optional)",
        "Cost (optional)", "Retail (optional)", "Brand (optional)",
        "Shopmonkey ID (optional)",
    ]
    row = ["Light", "", "ABC-1", "Acme Supply", 100, 125, "Whelen", "part-1"]
    pricing.upload_snapshot(paths, _upload("shopmonkey.xlsx", _workbook_bytes(headers, row)))

    class FakeClient:
        def list_brands(self):
            return [
                {"id": "brand-whelen", "name": "Whelen", "entity": "Part"},
                {"id": "brand-tire", "name": "Tire Brand", "entity": "Tire"},
            ]

        def list_vendors(self):
            return [{"id": "vendor-acme", "name": "Acme Supply"}]

    monkeypatch.setattr(pricing.shopmonkey_service, "_client", lambda: FakeClient())
    options = pricing.scope_options(paths, refresh=True)

    assert next(row for row in options["brands"] if row["name"] == "Whelen") == {
        "id": "brand-whelen", "name": "Whelen", "part_count": 1,
    }
    assert next(row for row in options["vendors"] if row["name"] == "Acme Supply") == {
        "id": "vendor-acme", "name": "Acme Supply", "part_count": 1,
    }
    assert all(row["name"] != "Tire Brand" for row in options["brands"])


def test_bulk_review_selection_applies_to_every_filtered_part(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    store = pricing.PricingStore(paths)
    review_path = store.root / "reviews" / "bulk.json"
    rows = [
        {"id": "a", "status": "updated", "sku": "A-1", "description": "Alpha light", "included": True, "approved_new": False},
        {"id": "b", "status": "updated", "sku": "B-1", "description": "Bravo light", "included": True, "approved_new": False},
        {"id": "c", "status": "possible_new", "sku": "C-1", "description": "Charlie light", "included": False, "approved_new": False},
    ]
    pricing._json_write(review_path, rows)  # noqa: SLF001
    with store.connect() as database:
        database.execute(
            "INSERT INTO runs (id,session_id,snapshot_id,review_path,artifact_id,artifact_path,status,created_at,missing_count) VALUES (?,?,?,?,?,?,?,?,?)",
            ("bulk-run", "session", "snapshot", str(review_path), "", "", "review", pricing._now(), 0),  # noqa: SLF001
        )

    cleared = pricing.bulk_update_review_rows(paths, {
        "run_id": "bulk-run", "status": "updated", "search": "alpha", "selected": False,
    })
    assert cleared["updated_count"] == 1
    updated_view = pricing.get_review(paths, {
        "run_id": "bulk-run", "status": "updated", "search": "alpha", "page_size": 20,
    })
    assert (updated_view["selectable_total"], updated_view["selected_total"]) == (1, 0)
    stored = pricing._json_read(review_path)  # noqa: SLF001
    assert next(row for row in stored if row["id"] == "b")["included"] is True

    approved = pricing.bulk_update_review_rows(paths, {
        "run_id": "bulk-run", "status": "possible_new", "selected": True,
    })
    assert approved["updated_count"] == 1
    possible_new = next(row for row in pricing._json_read(review_path) if row["id"] == "c")  # noqa: SLF001
    assert possible_new["approved_new"] is True
    assert possible_new["included"] is True


def test_ambiguous_shopmonkey_match_can_be_skipped_and_restored(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    store = pricing.PricingStore(paths)
    review_path = store.root / "reviews" / "ambiguous.json"
    rows = [{
        "id": "ambiguous", "status": "needs_review", "reason": "2 possible Shopmonkey matches",
        "sku": "PAC-1", "description": "Mount", "included": False, "approved_new": False,
        "inventory_index": -1, "candidate_matches": [{"inventory_index": 0}, {"inventory_index": 1}],
    }]
    pricing._json_write(review_path, rows)  # noqa: SLF001
    with store.connect() as database:
        database.execute(
            "INSERT INTO runs (id,session_id,snapshot_id,review_path,artifact_id,artifact_path,status,created_at,missing_count) VALUES (?,?,?,?,?,?,?,?,?)",
            ("ambiguous-run", "session", "snapshot", str(review_path), "", "", "review", pricing._now(), 0),  # noqa: SLF001
        )

    pricing.update_review_row(paths, {"run_id": "ambiguous-run", "row_id": "ambiguous", "skipped": True})
    skipped = pricing._json_read(review_path)[0]  # noqa: SLF001
    assert (skipped["status"], skipped["included"], skipped["reason"]) == ("skipped", False, "Skipped by user")
    assert pricing.finalize_review(paths, {"run_id": "ambiguous-run"})["status"] == "ready"

    pricing.update_review_row(paths, {"run_id": "ambiguous-run", "row_id": "ambiguous", "skipped": False})
    restored = pricing._json_read(review_path)[0]  # noqa: SLF001
    assert (restored["status"], restored["reason"]) == ("needs_review", "2 possible Shopmonkey matches")


def test_api_plan_enforces_five_minute_limit(tmp_path: Path):
    paths = AppPaths(workspace_dir=tmp_path)
    store = pricing.PricingStore(paths)
    review_path = store.root / "reviews" / "run.json"
    rows = [{
        "id": str(index), "included": True, "inventory_index": index,
        "status": "updated", "approved_new": False,
    } for index in range(pricing.API_MAX_PARTS + 1)]
    pricing._json_write(review_path, rows)  # noqa: SLF001
    now = pricing._now()  # noqa: SLF001
    with store.connect() as database:
        database.execute(
            "INSERT INTO runs (id,session_id,snapshot_id,review_path,artifact_id,artifact_path,status,created_at,missing_count) VALUES (?,?,?,?,?,?,?,?,?)",
            ("run", "session", "snapshot", str(review_path), "", "", "review", now, 0),
        )
    plan = pricing.api_plan(paths, {"run_id": "run"})
    assert plan["allowed"] is False
    assert plan["max_parts"] == pricing.API_MAX_PARTS
    assert "five-minute" in plan["reason"]


def test_pricing_ui_has_real_vendor_list_navigation_and_no_preview_fixtures():
    script = (UI_ROOT / "js" / "pricing_center.js").read_text(encoding="utf-8")
    styles = (UI_ROOT / "styles.css").read_text(encoding="utf-8")
    theme = (UI_ROOT / "theme.css").read_text(encoding="utf-8")
    tabs = (UI_ROOT / "js" / "tabs.js").read_text(encoding="utf-8")
    server = (ROOT / "src" / "dtm_buildsheet" / "app" / "server.py").read_text(encoding="utf-8")

    assert "Vendor Price Lists" in script
    assert "Price List Converter" in script
    assert 'src="/ui/images/shopmonkey-export-parts-arrow.png"' in script
    assert (UI_ROOT / "images" / "shopmonkey-export-parts-arrow.png").is_file()
    assert "Importing Shopmonkey parts…" in script
    assert 'class="pricing-spinner pricing-baseline-upload-spinner"' in script
    assert "API limit" not in script
    assert "One export can be reused for 24 hours" in script
    assert "Import, review, and export every vendor price list" in script
    assert "Available pricing rules" not in script
    assert "Example calculations" in script
    assert "Change rule" in script
    assert 'data-pricing-action="change-import-rule"' in script
    assert 'data-pricing-form="change-import-rule"' in script
    assert 'id="pricing-import-rule-choice"' not in script
    assert "Shopmonkey parts import" in script
    assert "Confirm both price terms below" in script
    assert 'data-pricing-action="edit-import-rule"' in script
    assert "pricing-rule-modal-backdrop" in script
    assert "cost_source_value" in script
    assert "retail_source_value" in script
    assert "cost_adjustment" in script
    assert "retail_adjustment" in script
    assert 'id="pricing-rule-example-search"' in script
    assert "Search SKU or description" in script
    assert 'payload.search = state.ruleExampleSearch' in script
    assert "Using preset" in script
    assert "Custom price column" in script
    assert "Save and export" in script
    assert "Save and exit" in script
    assert "Confirm Shopmonkey import" in script
    assert "Small API update" not in script
    assert 'page_size: 20' in script
    assert 'data-pricing-action="start-import"' in script
    assert 'data-pricing-action="continue-import"' in script
    assert 'data-pricing-action="bulk-export"' in script
    assert "Preparing bulk export" in script
    assert 'class="pricing-spinner pricing-spinner-small"' in script
    assert "Mark all as imported" in script
    assert "/api/pricing/export/mark-all-imported" in script
    assert "Price-list coverage" in script
    assert "/api/pricing/inventory/coverage" in script
    assert "Shopmonkey parts" in script
    assert "Covered by price lists" in script
    assert "Not in price lists" in script
    assert 'id="pricing-coverage-brand"' in script
    assert "All brands" in script
    assert "Needs rematching" in script
    assert "Existing Shopmonkey description retained" in script
    assert 'data-pricing-action="download-artifact"' in script
    assert "save_pricing_export" in script
    assert 'data-pricing-action="delete-import"' in script
    assert "Export all parts" in script
    assert "Export changed parts" in script
    assert "SKU exceptions" in script
    assert "pricing-rule-group" in script
    assert "Vendor or brand group" in script
    assert "pricing-rule-pill" in script
    assert '<details class="pricing-rule-menu">' in script
    assert '<details class="pricing-edit-exceptions">' in script
    assert '<span class="pricing-rule-pill ' in script
    assert '<h4 class="pricing-rule-name">' in script
    assert "Current our retail" in script
    assert 'class="pricing-part-identity"' in script
    assert "Search SKU, description, brand, vendor, or ID" in script
    assert "Select all" in script
    assert "Select none" in script
    assert "Bulk actions…" in script
    assert 'id="pricing-review-bulk-action"' in script
    assert "/api/pricing/review/bulk" in script
    assert "Skip this part" in script
    assert "Restore to review" in script
    assert "Repeated headers and rows without a SKU plus a numeric price are excluded" in script
    assert 'data-pricing-card-rule-id=' in script
    assert 'data-pricing-scope-search' in script
    assert "Calculate from" in script
    assert "Custom column on vendor list" in script
    assert "Vendor-list cost" in script
    assert "Our Retail (sell)" in script
    assert "Additional discount" in script
    assert "data-pricing-cost-enabled" in script
    assert 'class="pricing-unit-toggle"' in script
    assert "Part counts use the current Shopmonkey inventory baseline" in script
    assert 'call("/api/pricing/scope-options/refresh")' in script
    assert "def list_vendors" in (ROOT / "src" / "dtm_buildsheet" / "app" / "adapters" / "shopmonkey" / "api_client.py").read_text(encoding="utf-8")
    assert ".pricing-rule-group>header>div.pricing-rule-card-summary{display:grid" in styles
    assert ".pricing-rule-menu.pricing-list-menu>div{position:fixed" in styles
    assert "function positionListMenu(summary)" in script
    assert 'html[data-theme="dark"] .pricing-rule-pill-discount' in theme
    assert 'data-pricing-action="edit-rule"' in script
    assert "No placeholder rows are shown" in script
    assert 'action === "open-review"' in script
    assert 'action === "open-final-review"' in script
    assert "SAMPLE_REVIEW" not in script
    assert "UI preview" not in script
    assert 'appHasCapability("pricing.view")' in tabs
    assert "pricing_routes.route_pricing" in server
    assert "def save_pricing_export" in server


def test_export_package_splits_every_ten_thousand_rows():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for isolated Pricing Center function checks")
    source = UI_ROOT / "js" / "pricing_center.js"
    program = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const window={};
vm.runInNewContext(source,{window,console});
const pricing=window.PricingCenterPreview;
assert.equal(pricing.EXPORT_ROW_LIMIT,10000);
assert.deepEqual(Array.from(pricing.splitExportRows(10001), part=>part.rows),[10000,1]);
const pack=pricing.buildExportPackage(20001,'2026-11-19');
assert.equal(pack.isSplit,true);
assert.equal(pack.name,'shopmonkey-pricing-import-2026-11-19.zip');
assert.deepEqual(Array.from(pack.files, file=>file.rows),[10000,10000,1]);
const now=Date.parse('2026-11-20T18:00:00Z');
assert.equal(pricing.snapshotFreshness({created_at:'2026-11-20T07:00:00Z'},now),'current');
assert.equal(pricing.snapshotFreshness({created_at:'2026-11-20T05:00:00Z'},now),'aging');
assert.equal(pricing.snapshotFreshness({created_at:'2026-11-18T17:00:00Z'},now),'stale');
"""
    result = subprocess.run([node, "-e", program, str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
