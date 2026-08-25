"""Phase 3 Slice 3 + Estimates tests: per-vehicle jobs and draft estimates.

Covers part→QB-item resolution, the block-until-all-linked validation, the
sub-customer/job bridge, estimate creation + write-back, and batch creation.
Hermetic — no network, no cloud, no real keychain.
"""

from __future__ import annotations

import json

import pytest

from dtm_buildsheet.app.adapters.quickbooks.api_client import QuickBooksApiError
from dtm_buildsheet.app.services import agency_service as agc
from dtm_buildsheet.app.services import parts_db_service
from dtm_buildsheet.app.services import qb_estimate_service as est
from dtm_buildsheet.app.services import qb_sync_service as sync
from dtm_buildsheet.domain.project_models import BuildUnit, CustomerInfo, IndividualUnit
from dtm_buildsheet.inputs import project_entry
from dtm_buildsheet.inputs.project_drafts import DraftPart, new_draft, save_draft
from dtm_buildsheet.paths import AppPaths


@pytest.fixture
def paths(tmp_path):
    for sub in ("config", "projects", "drafts", "agencies", "output"):
        (tmp_path / sub).mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_config_dir=tmp_path / "config",
        workspace_projects_dir=tmp_path / "projects",
        workspace_drafts_dir=tmp_path / "drafts",
        workspace_output_dir=tmp_path / "output",
    )


@pytest.fixture(autouse=True)
def _no_cloud(monkeypatch):
    import dtm_buildsheet.app.services.shared_work_service as sw
    for name in (
        "save_setting_to_cloud_in_background",
        "save_settings_to_cloud_batch_in_background",
        "mirror_project_to_cloud_in_background",
        "mirror_draft_to_cloud_in_background",
    ):
        monkeypatch.setattr(sw, name, lambda *a, **k: None)
    parts_db_service.reset_for_testing()
    monkeypatch.setattr(sync, "refresh_estimate_catalog",
                        lambda paths: {"ok": True, "last_sync_utc": "2026-08-12T00:00:00Z"})


class FakeClient:
    """Captures all QB write calls; returns canned ids."""

    def __init__(self):
        self.created_customers = []
        self.updated_customers = []
        self.created_jobs = []
        self.created_estimates = []
        self.updated_estimates = []
        self.estimate_attachments = []
        self.uploaded_attachments = []
        self.name_lookups = []
        self.next_doc_number = "1001"
        self.estimate_to_read = None

    def read_customer(self, customer_id):
        return None

    def find_customer_type_by_name(self, name):
        return "retail-type-id" if name == "Retail" else ""

    def find_top_level_customer_by_display_name(self, name):
        # The estimate flow must reuse the agency Customer and never create a
        # vehicle sub-customer.
        return {"qb_customer_id": "CUST9", "name": "Lakeville PD", "is_sub": False}

    def create_customer(self, fields):
        self.created_customers.append(fields)
        return {"qb_customer_id": "CUST1", "sync_token": "0"}

    def update_customer(self, customer_id, sync_token, fields):
        self.updated_customers.append((customer_id, sync_token, fields))
        return {"qb_customer_id": customer_id, "sync_token": "1"}

    def find_customer_by_display_name(self, name):
        self.name_lookups.append(name)
        return ""

    def create_job(self, parent_id, display_name):
        self.created_jobs.append((parent_id, display_name))
        return {"qb_customer_id": "JOB1", "sync_token": "0"}

    def create_estimate(self, payload):
        self.created_estimates.append(payload)
        return {"qb_estimate_id": "EST1", "doc_number": "1001"}

    def next_estimate_doc_number(self):
        return self.next_doc_number

    def read_estimate(self, estimate_id):
        return self.estimate_to_read or {"Id": estimate_id, "SyncToken": "7", "DocNumber": "1001"}

    def update_estimate(self, estimate_id, sync_token, payload):
        self.updated_estimates.append((estimate_id, sync_token, payload))
        return {"qb_estimate_id": estimate_id, "doc_number": "1001"}

    def fetch_estimate_attachments(self, estimate_id):
        return self.estimate_attachments

    def upload_estimate_attachment(self, estimate_id, pdf_path):
        self.uploaded_attachments.append((estimate_id, pdf_path))
        return {"attachment_id": "ATT1", "file_name": "build.pdf"}


def test_window_tint_quotes_65_per_selected_window_through_misc(paths, monkeypatch):
    _write_parts_db(paths, {})
    draft = new_draft(parts=[DraftPart(
        name="Window Tint", part_number="TINT", quantity=3,
        picker_config={"window_tint": {
            "windows": ["windshield_brow", "driver_front", "passenger_front"],
            "percentage": 20,
            "unit_price": 65,
        }},
    )])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert problems == []
    assert lines[0]["qty"] == 3
    assert lines[0]["unit_price"] == 65.0
    assert lines[0]["amount"] == 195.0
    assert "20%" in lines[0]["description"]
    monkeypatch.setattr(sync, "find_cached_active_item_by_name", lambda *_: {
        "qb_item_id": "MISC1", "name": "MISC PART",
    })
    assert est._attach_custom_parts_to_misc_item(paths, lines) == []
    assert lines[0]["qb_item_id"] == "MISC1"


def test_gamber_specialty_faceplates_are_zero_oem_is_omitted_and_extra_is_billed(paths):
    _write_parts_db(paths, {
        "core": _linked_product("Core plate", "7160-0339", "Q1", 75),
        "radio": _linked_product("Motorola plate", "7160-0321", "Q2", 80),
        "oem": _linked_product("OEM plate", "15250", "Q3", 60),
        "extra": _linked_product("Extra plate", "EXTRA-1", "Q4", 45),
    })
    no_charge = {"quote_unit_price_override": 0, "quote_note": "Included specialty faceplate — no charge"}
    draft = new_draft(parts=[
        DraftPart(name="Core faceplate", part_number="7160-0339", picker_config=no_charge),
        DraftPart(name="Motorola faceplate", part_number="7160-0321", picker_config=no_charge),
        DraftPart(name="OEM relocation plate", part_number="15250", picker_config={"console_kit_included": True}),
        DraftPart(name="Extra specialty faceplate", part_number="EXTRA-1"),
    ])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert problems == []
    by_part = {line["part_number"]: line for line in lines}
    assert by_part["7160-0339"]["amount"] == 0
    assert by_part["7160-0321"]["amount"] == 0
    assert "15250" not in by_part
    assert by_part["EXTRA-1"]["amount"] == 45


def _use_fake(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(sync, "_build_client", lambda p: (fake, None))
    return fake


# ── fixtures: parts_db, agency, project + draft ───────────────────────────────


def _write_parts_db(paths, products):
    db = {"schema_version": 2, "products": products}
    (paths.workspace_config_dir / "parts_db.json").write_text(json.dumps(db, indent=2), "utf-8")
    parts_db_service.reset_for_testing()


def _write_estimate_charges(paths, *, labor=2000, supplies=450):
    presets = {
        preset_id: {
            "label": label,
            "aliases": [preset_id] if preset_id != "custom" else [],
            "labor_amount": labor,
            "install_supplies_amount": supplies,
        }
        for preset_id, label in (
            ("patrol", "Patrol"), ("undercover", "Undercover"),
            ("admin", "Admin"), ("custom", "Custom"),
        )
    }
    (paths.workspace_config_dir / "estimate_charges.json").write_text(json.dumps({
        "schema_version": 1,
        "card_fee_percent": 4,
        "service_items": {
            "labor": "LABOR INSTALL",
            "install_supplies": "INSTALL SUPPLIES",
            "card_fee": "Convenience Fee",
            "delivery": "TRAVEL",
        },
        "presets": presets,
    }), "utf-8")


def _linked_product(model, part_number, item_id, price, **extra):
    return {
        "manufacturer_id": "mfg",
        "model": model,
        "part_numbers": [{"part_number": part_number}],
        "qb_item_id": item_id,
        "qb_sku": part_number,
        "qb_unit_price": price,
        **extra,
    }


def _make_agency(paths, *, qb_customer_id=""):
    agc.handle_save_agency({
        "name": "Lakeville PD",
        "contact_name": "Patrol Contact",
        "contact_phone": "555-0100",
        "contact_email": "patrol@example.test",
        "bill_address_line1": "123 Main Street",
        "bill_city": "Lakeville",
        "bill_state": "MN",
        "bill_postal_code": "55044",
    }, paths)
    aid = agc.load_agencies(paths)[0].agency_id
    if qb_customer_id:
        agc.set_qb_customer_id(paths, aid, qb_customer_id)
    return aid


def _make_project(paths, agency_id, draft_parts, *, quote="26-043"):
    draft = new_draft(vehicle_info={"VehicleType": "TAHOE"}, parts=list(draft_parts))
    save_draft(draft, paths.workspace_drafts_dir)
    unit = IndividualUnit(
        individual_id="ind1",
        unit_number="12",
        year="2026",
        model="Tahoe",
        draft_id=draft.draft_id,
        qb_project_id="447322633",
        qb_project_name="Unit 12 | Build 2026",
    )
    bu = BuildUnit(unit_id="bu1", vehicle_model="Tahoe", build_type="Patrol", individuals=[unit])
    project = project_entry.new_project(
        customer=CustomerInfo(agency_id=agency_id, build_year="2026", quote_number=quote),
        build_units=[bu],
    )
    project_entry.save_project(project, paths)
    return project.project_id


# ── resolution ────────────────────────────────────────────────────────────────


def test_resolve_links_priced_active_part(paths):
    _write_parts_db(paths, {"p1": _linked_product("Liberty II", "WL-LIB2", "847", 1249.0)})
    draft = new_draft(parts=[DraftPart(name="Liberty", part_number="WL-LIB2", quantity=2)])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert problems == []
    assert lines[0]["qb_item_id"] == "847"
    assert lines[0]["qty"] == 2 and lines[0]["amount"] == 2498.0


def test_resolve_uses_builder_sku_with_production_id_price_and_description(paths):
    _write_parts_db(paths, {
        "p1": {
            "manufacturer_id": "mfg",
            "model": "K5011",
            "part_numbers": [{
                "part_number": "K5011",
                "qb_item_id": "production-847",
                "qb_sku": "",
                "qb_sales_description": "Sandbox description",
                "qb_unit_price": 100.0,
            }],
        },
    })
    sync._write_cache(paths, {
        "items": [{
            "qb_item_id": "production-847",
            "name": "K5011-B",
            "sku": "",
            "description": "Production description\nwith formatting",
            "unit_price": 124.5,
            "type": "NonInventory",
        }],
    })
    draft = new_draft(parts=[DraftPart(name="Axe hanger", part_number="K5011", quantity=2)])

    lines, problems = est.resolve_build_lines(paths, draft)

    assert problems == []
    assert lines == [{
        "product_id": "p1",
        "qb_item_id": "production-847",
        "qb_sku": "",
        "description": "Production description\nwith formatting",
        "manufacturer": "mfg",
        "manufacturer_id": "mfg",
        "unit_price": 124.5,
        "pending": False,
        "name": "Axe hanger",
        "part_number": "K5011",
        "qty": 2,
        "amount": 249.0,
    }]
    payload = est._build_estimate_payload("customer-1", lines)
    assert payload["Line"][0]["SalesItemLineDetail"]["ItemRef"] == {
        "value": "production-847",
    }
    assert payload["Line"][0]["Description"] == "Production description\nwith formatting"


def test_resolve_uses_concrete_component_skus_for_picker_parent(paths):
    # Picker rows show the product model on the parent (PB450L), but store the
    # vehicle-specific SKU selected by the user in components (BK1001ITU20).
    _write_parts_db(paths, {"bumper": {
        "manufacturer_id": "m", "model": "PB450L",
        "part_numbers": [
            {"part_number": "BK1001ITU20", "qb_item_id": "295", "qb_unit_price": 1459.0},
            {"part_number": "BK2019ITU20", "qb_item_id": "302", "qb_unit_price": 1179.0},
        ],
    }})
    draft = new_draft(parts=[DraftPart(
        name="Push Bumper",
        part_number="PB450L",
        quantity=1,
        components=[
            {"part_number": "BK1001ITU20", "quantity": 1},
            {"part_number": "BK2019ITU20", "quantity": 2},
        ],
    )])

    lines, problems = est.resolve_build_lines(paths, draft)

    assert problems == []
    assert [(line["part_number"], line["qb_item_id"], line["qty"], line["amount"])
            for line in lines] == [
        ("BK1001ITU20", "295", 1, 1459.0),
        ("BK2019ITU20", "302", 2, 2358.0),
    ]


def test_resolve_reports_component_sku_when_component_is_unlinked(paths):
    _write_parts_db(paths, {"bumper": {
        "manufacturer_id": "m", "model": "PB450L",
        "part_numbers": [{"part_number": "BK1001ITU20"}],
    }})
    draft = new_draft(parts=[DraftPart(
        name="Push Bumper",
        part_number="PB450L",
        components=[{"part_number": "BK1001ITU20", "quantity": 1}],
    )])

    lines, problems = est.resolve_build_lines(paths, draft)

    assert lines == []
    assert problems == [{
        "name": "Push Bumper",
        "part_number": "BK1001ITU20",
        "reason": "not_linked",
    }]


def test_resolve_flags_unlinked_inactive_unpriced_unmatched(paths):
    _write_parts_db(paths, {
        "linked": _linked_product("A", "AA", "1", 10.0),
        "unlinked": {"manufacturer_id": "m", "model": "B", "part_numbers": [{"part_number": "BB"}]},
        "inactive": _linked_product("C", "CC", "3", 30.0, qb_inactive=True),
        "nopriced": {"manufacturer_id": "m", "model": "D",
                     "part_numbers": [{"part_number": "DD"}], "qb_item_id": "4"},
    })
    draft = new_draft(parts=[
        DraftPart(name="a", part_number="AA"),
        DraftPart(name="b", part_number="BB"),
        DraftPart(name="c", part_number="CC"),
        DraftPart(name="d", part_number="DD"),
        DraftPart(name="z", part_number="ZZ"),  # no catalog match
    ])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert len(lines) == 1 and lines[0]["qb_item_id"] == "1"
    reasons = {p["part_number"]: p["reason"] for p in problems}
    assert reasons == {"BB": "not_linked", "CC": "qb_inactive",
                       "DD": "no_price", "ZZ": "no_catalog_match"}


def test_resolve_prices_per_part_number(paths):
    # One product, two SKUs each with its own QB id + price (the catalog reality).
    _write_parts_db(paths, {"p1": {
        "manufacturer_id": "m", "model": "WIDGET",
        "part_numbers": [
            {"part_number": "SKU-A", "qb_item_id": "100", "qb_unit_price": 10.0},
            {"part_number": "SKU-B", "qb_item_id": "200", "qb_unit_price": 25.0},
        ],
    }})
    draft = new_draft(parts=[DraftPart(name="a", part_number="SKU-A", quantity=2),
                             DraftPart(name="b", part_number="SKU-B")])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert problems == []
    by_id = {ln["qb_item_id"]: ln for ln in lines}
    assert by_id["100"]["unit_price"] == 10.0 and by_id["100"]["amount"] == 20.0
    assert by_id["200"]["unit_price"] == 25.0 and by_id["200"]["amount"] == 25.0


def test_resolve_uses_qb_sales_descriptions_and_groups_sorted_brand_lines(paths):
    _write_parts_db(paths, {
        "alpha": {
            "manufacturer_id": "alpha", "model": "Alpha part",
            "part_numbers": [{"part_number": "A-1", "qb_item_id": "10",
                               "qb_unit_price": 12.0,
                               "qb_sales_description": "ALPHA QB SALES DESCRIPTION"}],
        },
        "beta": {
            "manufacturer_id": "beta", "model": "Beta part",
            "part_numbers": [{"part_number": "B-1", "qb_item_id": "20",
                               "qb_unit_price": 8.0,
                               "qb_sales_description": "BETA QB SALES DESCRIPTION"}],
        },
    })
    db = json.loads((paths.workspace_config_dir / "parts_db.json").read_text())
    db["manufacturers"] = {"alpha": {"label": "Alpha"}, "beta": {"label": "Beta"}}
    (paths.workspace_config_dir / "parts_db.json").write_text(json.dumps(db), "utf-8")
    parts_db_service.reset_for_testing()
    draft = new_draft(parts=[
        DraftPart(name="manifest beta", part_number="B-1"),
        DraftPart(name="manifest alpha 1", part_number="A-1", quantity=2),
        DraftPart(name="manifest alpha 2", part_number="A-1", quantity=1),
    ])

    lines, problems = est.resolve_build_lines(paths, draft)

    assert problems == []
    assert [line["manufacturer"] for line in lines] == ["Alpha", "Beta"]
    assert lines[0]["description"] == "ALPHA QB SALES DESCRIPTION"
    assert lines[0]["qty"] == 3 and lines[0]["amount"] == 36.0
    payload = est._build_estimate_payload("CUST1", lines)
    assert payload["Line"][0]["Description"] == "ALPHA QB SALES DESCRIPTION"


def test_resolve_prefers_last_synced_qb_cache_price(paths):
    _write_parts_db(paths, {
        "p1": _linked_product("Widget", "W-1", "10", 10.0,
                               qb_sales_description="Stale description"),
    })
    (paths.workspace_dir / "quickbooks_items_cache.json").write_text(json.dumps({
        "last_sync_utc": "2026-07-22T00:00:00Z",
        "items": [{"qb_item_id": "10", "description": "CURRENT QB DESCRIPTION",
                   "unit_price": 12.5, "sku": "W-1"}],
    }), "utf-8")
    draft = new_draft(parts=[DraftPart(name="widget", part_number="W-1")])

    lines, problems = est.resolve_build_lines(paths, draft)

    assert problems == []
    assert lines[0]["unit_price"] == 12.5
    assert lines[0]["description"] == "CURRENT QB DESCRIPTION"


def test_resolve_skips_excluded_and_defaults_qty(paths):
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 5.0)})
    draft = new_draft(parts=[
        DraftPart(name="a", part_number="AA", quantity=0),      # qty 0 → bills 1
        DraftPart(name="x", part_number="AA", include=False),   # excluded → skipped
    ])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert len(lines) == 1 and lines[0]["qty"] == 1 and lines[0]["amount"] == 5.0


def test_resolve_skips_used_and_reused_parts(paths):
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 5.0)})
    draft = new_draft(parts=[
        DraftPart(name="new", part_number="AA", new_or_used="New"),
        DraftPart(name="used", part_number="AA", new_or_used="Used"),
        DraftPart(name="reused", part_number="AA", new_or_used="Reused"),
    ])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert problems == []
    assert [line["name"] for line in lines] == ["new"]


def test_resolve_skips_both_customer_supplied_conditions(paths):
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 5.0)})
    draft = new_draft(parts=[
        DraftPart(name="dtm", part_number="AA", supply_type="new"),
        DraftPart(
            name="customer-new", part_number="AA", supply_type="customer_supplied",
            customer_condition="new", customer_source="Agency stock",
        ),
        DraftPart(
            name="customer-used", part_number="AA", supply_type="customer_supplied",
            customer_condition="used", customer_source="Retired unit",
        ),
    ])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert problems == []
    assert [line["name"] for line in lines] == ["dtm"]


def test_resolve_skips_console_parts_included_with_kit(paths):
    _write_parts_db(paths, {
        "kit": _linked_product("Console kit", "KIT", "1", 500.0),
        "cup": _linked_product("Cup holder", "CUP", "2", 25.0),
    })
    draft = new_draft(parts=[
        DraftPart(name="Center Console", part_number="KIT"),
        DraftPart(name="Cup Holder Faceplate", part_number="CUP", picker_config={"console_kit_included": True}),
    ])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert problems == []
    assert [line["part_number"] for line in lines] == ["KIT"]


# ── pending-QB parts (docs/PARTS_DB_AND_PICKER.md) ───────────────────────────────


def _pending_product(model, part_number, price, **extra):
    return {"manufacturer_id": "m", "model": model,
            "part_numbers": [{"part_number": part_number, "qb_pending": True,
                              "price_usd": price, **extra}]}


def test_resolve_pending_part_bills_with_price_and_flag(paths):
    # No qb_item_id, but qb_pending + price_usd → billable line flagged pending.
    _write_parts_db(paths, {"trio": _pending_product("Trio WCX", "TCRWXPJC", 116.0)})
    draft = new_draft(parts=[DraftPart(name="Trio head", part_number="TCRWXPJC", quantity=3)])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert problems == []
    assert len(lines) == 1
    ln = lines[0]
    assert ln["pending"] is True and ln["qb_item_id"] == ""
    assert ln["unit_price"] == 116.0 and ln["amount"] == 348.0


def test_pending_part_posts_as_description_only_line(paths):
    lines = [
        {"name": "Liberty", "part_number": "WL", "qb_item_id": "1", "qb_sku": "WL",
         "unit_price": 10.0, "qty": 1, "amount": 10.0, "pending": False},
        {"name": "Trio head", "part_number": "TCRWXPJC", "qb_item_id": "", "qb_sku": "",
         "unit_price": 116.0, "qty": 2, "amount": 232.0, "pending": True},
    ]
    payload = est._build_estimate_payload("CUST1", lines)
    qb_lines = payload["Line"]
    assert qb_lines[0]["DetailType"] == "SalesItemLineDetail"
    assert qb_lines[1]["DetailType"] == "DescriptionOnly"
    assert "ItemRef" not in qb_lines[1].get("SalesItemLineDetail", {})
    assert "TCRWXPJC" in qb_lines[1]["Description"]
    assert "NOT IN QB INVENTORY" in qb_lines[1]["Description"]


def test_custom_part_bills_with_entered_price_through_misc_item(paths, monkeypatch):
    draft = new_draft(parts=[DraftPart(
        name="Vendor supplied cable kit", part_number="VND-042", quantity=2,
        picker_config={"custom_part": {
            "sku": "VND-042", "description": "Vendor supplied cable kit", "unit_price": 42.5,
        }},
    )])

    lines, problems = est.resolve_build_lines(paths, draft)

    assert problems == []
    assert len(lines) == 1
    line = lines[0]
    assert line["product_id"] == "custom_part"
    assert line["qb_item_id"] == "" and line["qb_sku"] == "VND-042"
    assert line["description"] == "Vendor supplied cable kit"
    assert line["manufacturer"] == "Custom"
    assert line["unit_price"] == 42.5 and line["amount"] == 85.0
    assert line["qty"] == 2 and line["pending"] is False and line["custom"] is True
    monkeypatch.setattr(sync, "find_cached_active_item_by_name",
                        lambda paths, name: {"qb_item_id": "557", "name": "MISC PART"})
    assert est._attach_custom_parts_to_misc_item(paths, lines) == []
    payload = est._build_estimate_payload("CUST1", lines)
    note = payload["Line"][0]
    assert note["DetailType"] == "SalesItemLineDetail"
    assert note["Amount"] == 85.0
    assert note["SalesItemLineDetail"] == {
        "ItemRef": {"value": "557"}, "Qty": 2, "UnitPrice": 42.5,
    }
    assert "VND-042" in note["Description"]
    assert "Vendor supplied cable kit" in note["Description"]


def test_custom_part_blocks_if_misc_item_is_unavailable(paths, monkeypatch):
    lines = [{"custom": True, "name": "One-off", "part_number": "CUSTOM-1"}]
    monkeypatch.setattr(sync, "find_cached_active_item_by_name", lambda paths, name: None)
    assert est._attach_custom_parts_to_misc_item(paths, lines) == [{
        "name": "One-off", "part_number": "CUSTOM-1", "reason": "custom_item_unavailable",
    }]


def test_validate_blocks_when_current_prices_cannot_refresh(paths, monkeypatch):
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 100.0)})
    aid = _make_agency(paths)
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    monkeypatch.setattr(sync, "refresh_estimate_catalog",
                        lambda paths: {"ok": False, "error": "pricing_refresh_failed"})
    assert est.validate_estimate(paths, project_id=pid, individual_id="ind1") == {
        "ok": False, "error": "pricing_refresh_failed",
    }


def test_project_tax_status_is_aligned_to_non_taxable_agency():
    class Client:
        def __init__(self):
            self.updated = []

        def read_customer(self, customer_id):
            return {"Id": customer_id, "SyncToken": "4", "Taxable": True}

        def update_customer(self, customer_id, sync_token, fields):
            self.updated.append((customer_id, sync_token, fields))

    client = Client()
    agency = type("Agency", (), {"taxable": False})()
    assert est._ensure_project_tax_status(client, "434", agency) == {"ok": True, "changed": True}
    assert client.updated == [("434", "4", {"taxable": False})]


def test_validate_reports_pending_but_can_create(paths):
    _write_parts_db(paths, {
        "linked": _linked_product("A", "AA", "1", 10.0),
        "trio": _pending_product("Trio", "BB", 116.0),
    })
    aid = _make_agency(paths, qb_customer_id="CUST1")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA"),
                                     DraftPart(name="t", part_number="BB")])
    res = est.validate_estimate(paths, project_id=pid, individual_id="ind1")
    assert res["can_create"] is True            # pending is not a blocker
    assert res["pending_count"] == 1
    assert res["pending"][0]["part_number"] == "BB"
    assert res["total"] == 126.0


# ── validate (offline, no network) ────────────────────────────────────────────


def test_validate_can_create_when_clean(paths):
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 100.0)})
    aid = _make_agency(paths)
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA", quantity=3)])
    res = est.validate_estimate(paths, project_id=pid, individual_id="ind1")
    assert res["can_create"] is True
    assert res["line_count"] == 1 and res["total"] == 300.0 and res["problems"] == []


def test_validate_applies_default_whelen_discount_from_qb_list_price(paths):
    product = _linked_product("A", "AA", "1", 100.0)
    product["manufacturer_id"] = "whelen"
    _write_parts_db(paths, {"p1": product})
    aid = _make_agency(paths)
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA", quantity=2)])

    res = est.validate_estimate(paths, project_id=pid, individual_id="ind1")

    assert res["total"] == 124.0
    assert res["pricing"]["rule_name"] == "Retail"
    assert res["pricing"]["source"] == "retail"
    assert res["pricing"]["list_total"] == 200.0
    assert res["pricing"]["customer_total"] == 124.0
    assert res["pricing"]["savings"] == 76.0
    assert res["pricing"]["applied_discounts"] == [{
        "manufacturer_id": "whelen",
        "manufacturer": "whelen",
        "discount_percent": 38.0,
        "override": False,
    }]


def test_validate_defaults_to_retail_despite_saved_custom_agency_pricing(paths):
    product = _linked_product("A", "AA", "1", 100.0)
    product["manufacturer_id"] = "whelen"
    _write_parts_db(paths, {"p1": product})
    aid = _make_agency(paths)
    agc.handle_save_agency({
        "agency_id": aid,
        "name": "Lakeville PD",
        "pricing_overrides": {"whelen": 10},
    }, paths)
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA", quantity=2)])

    res = est.validate_estimate(paths, project_id=pid, individual_id="ind1")

    assert res["total"] == 124.0
    assert res["pricing"]["source"] == "retail"
    whelen = next(row for row in res["pricing"]["editable_discounts"]
                   if row["manufacturer_id"] == "whelen")
    assert whelen["custom_discount_percent"] == 10.0


def test_validate_blocks_with_problems(paths):
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 100.0)})
    aid = _make_agency(paths)
    pid = _make_project(paths, aid, [DraftPart(name="z", part_number="ZZ")])
    res = est.validate_estimate(paths, project_id=pid, individual_id="ind1")
    assert res["can_create"] is False
    assert res["problems"][0]["reason"] == "no_catalog_match"


# ── job bridge ────────────────────────────────────────────────────────────────


def test_push_vehicle_job_creates_under_existing_customer(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [])
    res = sync.push_vehicle_job(paths, pid, "ind1")
    assert res["ok"] and res["qb_job_id"] == "JOB1" and res["action"] == "created"
    assert fake.created_jobs[0][0] == "CUST9"
    assert "2026 Tahoe" in fake.created_jobs[0][1] and "Unit 12" in fake.created_jobs[0][1]
    # Written back onto the unit.
    proj = project_entry.load_project(pid, paths)
    assert proj.build_units[0].individuals[0].qb_job_id == "JOB1"


def test_push_vehicle_job_pushes_agency_first(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    fake.find_top_level_customer_by_display_name = lambda name: None
    aid = _make_agency(paths)  # no qb_customer_id yet
    pid = _make_project(paths, aid, [])
    res = sync.push_vehicle_job(paths, pid, "ind1")
    assert res["ok"]
    assert fake.created_customers  # agency was created in QBO first
    assert fake.created_jobs[0][0] == "CUST1"  # job parented to the new customer
    assert agc.get_agency(paths, aid).qb_customer_id == "CUST1"


def test_push_vehicle_job_reuses_existing_by_name(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    monkeypatch.setattr(fake, "find_customer_by_display_name", lambda name: "JOB_EXISTING")
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [])
    res = sync.push_vehicle_job(paths, pid, "ind1")
    assert res["qb_job_id"] == "JOB_EXISTING" and res["action"] == "linked"
    assert fake.created_jobs == []  # no duplicate created


def test_push_vehicle_job_no_agency(paths, monkeypatch):
    _use_fake(monkeypatch)
    pid = _make_project(paths, "", [])  # project has no agency_id
    res = sync.push_vehicle_job(paths, pid, "ind1")
    assert res["ok"] is False and res["error"] == "no_agency"


# ── create estimate ───────────────────────────────────────────────────────────


def test_create_estimate_blocks_on_problems(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 100.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="z", part_number="ZZ")])
    res = est.create_estimate(paths, project_id=pid, individual_id="ind1")
    assert res["ok"] is False and res["error"] == "validation_failed"
    assert fake.created_estimates == []  # nothing sent to QBO


def test_create_estimate_uses_top_level_customer_and_estimate(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 250.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA", quantity=2)])

    res = est.create_estimate(paths, project_id=pid, individual_id="ind1", memo="Build 26-043")
    assert res["ok"] and res["qb_estimate_id"] == "EST1"
    assert res["line_count"] == 1 and res["total"] == 500.0
    # New estimates do not create a vehicle sub-customer.
    assert fake.created_jobs == [] and fake.created_estimates
    payload = fake.created_estimates[0]
    assert payload["DocNumber"] == "1001"
    assert payload["CustomerRef"]["value"] == "CUST9"
    assert payload["ProjectRef"]["value"] == "447322633"
    assert payload["Line"][0]["SalesItemLineDetail"]["ItemRef"]["value"] == "1"
    assert payload["Line"][0]["Amount"] == 500.0
    assert "Unit 12 | Build 2026" in payload["CustomerMemo"]["value"]
    assert "Lakeville PD" not in payload["CustomerMemo"]["value"]
    assert "Vehicle: 2026 Tahoe" in payload["CustomerMemo"]["value"]
    assert "Build 26-043" in payload["CustomerMemo"]["value"]
    assert "DTM vehicle project" in payload["PrivateNote"]
    # The estimate id and stable vehicle/project name are written back onto the unit.
    unit = project_entry.load_project(pid, paths).build_units[0].individuals[0]
    assert unit.qb_job_id == "" and unit.qb_estimate_id == "EST1"
    assert unit.qb_project_id == "447322633"
    assert unit.qb_project_name


def test_create_estimate_appends_configured_service_lines_and_four_percent_fee(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 500.0)})
    _write_estimate_charges(paths)
    item_ids = {
        "LABOR INSTALL": "7", "INSTALL SUPPLIES": "6",
        "Convenience Fee": "1073", "TRAVEL": "791",
    }
    monkeypatch.setattr(sync, "find_cached_active_item_by_name", lambda _paths, name: {
        "qb_item_id": item_ids[name], "name": name, "sku": "",
    })
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])

    result = est.create_estimate(
        paths,
        project_id=pid,
        individual_id="ind1",
        additional_charges={
            "preset_id": "patrol", "labor_amount": 2000,
            "install_supplies_amount": 450, "delivery_amount": 100,
        },
    )

    assert result["ok"] is True
    assert result["materials_total"] == 500
    assert result["additional_charges"]["card_fee_amount"] == 122
    assert result["total"] == 3172
    assert result["line_count"] == 5
    payload_lines = fake.created_estimates[0]["Line"]
    assert [line["SalesItemLineDetail"]["ItemRef"]["value"] for line in payload_lines] == [
        "1", "7", "6", "791", "1073",
    ]
    assert payload_lines[-1]["Amount"] == 122
    assert payload_lines[-1]["Description"] == "4% credit card processing fee"


def test_existing_estimate_requires_explicit_update_or_create_new(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    project = project_entry.load_project(pid, paths)
    project.build_units[0].individuals[0].qb_estimate_id = "EST-OLD"
    project_entry.save_project(project, paths)

    blocked = est.create_estimate(paths, project_id=pid, individual_id="ind1")

    assert blocked == {
        "ok": False,
        "error": "duplicate_estimate_confirmation_required",
        "existing_estimate_id": "EST-OLD",
    }
    assert fake.created_estimates == [] and fake.updated_estimates == []


def test_existing_estimate_can_be_updated_in_place(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    project = project_entry.load_project(pid, paths)
    project.build_units[0].individuals[0].qb_estimate_id = "EST-OLD"
    project_entry.save_project(project, paths)

    result = est.create_estimate(
        paths, project_id=pid, individual_id="ind1", existing_action="update",
        overwrite_qb_changes=True,
    )

    assert result["ok"] is True and result["action"] == "updated"
    assert result["qb_estimate_id"] == "EST-OLD"
    assert fake.created_estimates == []
    assert fake.updated_estimates[0][0:2] == ("EST-OLD", "7")


def test_untracked_existing_estimate_requires_explicit_overwrite(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    project = project_entry.load_project(pid, paths)
    project.build_units[0].individuals[0].qb_estimate_id = "EST-OLD"
    project_entry.save_project(project, paths)

    blocked = est.create_estimate(
        paths, project_id=pid, individual_id="ind1", existing_action="update",
    )

    assert blocked["error"] == "existing_estimate_change_unverified"
    assert blocked["estimate_change"]["status"] == "untracked"
    assert fake.updated_estimates == []


def test_existing_estimate_can_create_deliberate_new_version(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    project = project_entry.load_project(pid, paths)
    project.build_units[0].individuals[0].qb_estimate_id = "EST-OLD"
    project_entry.save_project(project, paths)

    result = est.create_estimate(
        paths, project_id=pid, individual_id="ind1", existing_action="create_new",
    )

    assert result["ok"] is True and result["action"] == "created"
    assert result["qb_estimate_id"] == "EST1"
    assert fake.created_estimates and fake.updated_estimates == []


def test_modified_qb_estimate_blocks_until_user_overwrites_or_creates_new(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])

    created = est.create_estimate(paths, project_id=pid, individual_id="ind1")
    assert created["ok"]
    project = project_entry.load_project(pid, paths)
    tracked = project.build_units[0].individuals[0]
    assert tracked.qb_estimate_snapshot["lines"][0]["unit_price"] == 10
    assert tracked.qb_estimate_snapshot_at

    current = json.loads(json.dumps(fake.created_estimates[0]))
    current.update({"Id": "EST1", "SyncToken": "8", "DocNumber": "1001"})
    current["Line"][0]["SalesItemLineDetail"]["UnitPrice"] = 12
    current["Line"][0]["Amount"] = 12
    current["Line"].append({
        "DetailType": "SubTotalLineDetail", "Amount": 12,
        "SubTotalLineDetail": {},
    })
    fake.estimate_to_read = current

    validation = est.validate_estimate(paths, project_id=pid, individual_id="ind1")
    assert validation["estimate_change"]["status"] == "modified"
    assert validation["estimate_change"]["modified"] is True
    assert validation["estimate_change"]["differences"][0]["field"] == "Line 1"
    assert len(validation["estimate_change"]["differences"]) == 1

    blocked = est.create_estimate(
        paths, project_id=pid, individual_id="ind1", existing_action="update",
    )
    assert blocked["error"] == "existing_estimate_modified"
    assert blocked["estimate_change"]["differences"]
    assert fake.updated_estimates == []

    overwritten = est.create_estimate(
        paths, project_id=pid, individual_id="ind1", existing_action="update",
        overwrite_qb_changes=True,
    )
    assert overwritten["ok"] and overwritten["action"] == "updated"
    assert fake.updated_estimates


def test_build_pdf_is_attached_after_estimate_creation(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF-1.7\nvalid test pdf")
    project = project_entry.load_project(pid, paths)
    project.build_units[0].individuals[0].pdf_path = str(pdf)
    project_entry.save_project(project, paths)

    result = est.create_estimate(
        paths, project_id=pid, individual_id="ind1", attach_pdf=True,
    )

    assert result["ok"] is True
    assert result["attachment"] == {
        "ok": True, "attachment_id": "ATT1", "file_name": "build.pdf",
    }
    assert fake.uploaded_attachments == [("EST1", str(pdf))]


def test_foreign_build_pdf_is_downloaded_before_estimate_attachment(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    project = project_entry.load_project(pid, paths)
    project.build_units[0].individuals[0].pdf_path = r"C:\other\build.pdf"
    project_entry.save_project(project, paths)
    local_pdf = paths.workspace_output_dir / "build.pdf"
    local_pdf.write_bytes(b"%PDF-1.7\nshared test pdf")
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.exports_upload_service.download_export",
        lambda *args, **kwargs: {"ok": True, "path": str(local_pdf), "downloaded": True},
    )

    result = est.create_estimate(
        paths, project_id=pid, individual_id="ind1", attach_pdf=True,
    )

    assert result["ok"] is True
    assert fake.uploaded_attachments == [("EST1", str(local_pdf))]


def test_attachment_failure_does_not_retry_or_fail_created_estimate(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    fake.upload_estimate_attachment = lambda estimate_id, pdf_path: (_ for _ in ()).throw(
        QuickBooksApiError("attachment_upload_failed")
    )
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF-1.7\nvalid test pdf")
    project = project_entry.load_project(pid, paths)
    project.build_units[0].individuals[0].pdf_path = str(pdf)
    project_entry.save_project(project, paths)

    result = est.create_estimate(
        paths, project_id=pid, individual_id="ind1", attach_pdf=True,
    )

    assert result["ok"] is True and result["qb_estimate_id"] == "EST1"
    assert result["attachment"] == {
        "ok": False, "error": "attachment_upload_failed",
    }
    assert len(fake.created_estimates) == 1


def test_create_estimate_sends_discounted_unit_price_without_invoice_only_ach_field(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    product = _linked_product("A", "AA", "1", 100.0)
    product["manufacturer_id"] = "whelen"
    _write_parts_db(paths, {"p1": product})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA", quantity=2)])

    res = est.create_estimate(paths, project_id=pid, individual_id="ind1")

    assert res["ok"] is True and res["total"] == 124.0
    payload = fake.created_estimates[0]
    assert payload["Line"][0]["SalesItemLineDetail"]["UnitPrice"] == 62.0
    assert payload["Line"][0]["Amount"] == 124.0
    assert "AllowOnlineACHPayment" not in payload


def test_create_estimate_can_use_temporary_custom_pricing(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    product = _linked_product("A", "AA", "1", 100.0)
    product["manufacturer_id"] = "whelen"
    _write_parts_db(paths, {"p1": product})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA", quantity=2)])

    res = est.create_estimate(
        paths,
        project_id=pid,
        individual_id="ind1",
        pricing_mode="custom",
        custom_pricing={"whelen": 10},
    )

    assert res["ok"] is True
    assert res["total"] == 180.0
    assert res["pricing"]["source"] == "custom"
    assert fake.created_estimates[0]["Line"][0]["SalesItemLineDetail"]["UnitPrice"] == 90.0


def test_create_estimate_does_not_write_custom_fields_with_accounting_only_access(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])

    assert est.create_estimate(paths, project_id=pid, individual_id="ind1")["ok"] is True
    assert "CustomField" not in fake.created_estimates[0]


def test_create_estimate_ignores_legacy_job_id(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    # A legacy job id remains intact for history, but is not used for new work.
    proj = project_entry.load_project(pid, paths)
    proj.build_units[0].individuals[0].qb_job_id = "JOB_PRESET"
    project_entry.save_project(proj, paths)

    res = est.create_estimate(paths, project_id=pid, individual_id="ind1")
    assert res["ok"]
    assert fake.created_jobs == []
    assert fake.created_estimates[0]["CustomerRef"]["value"] == "CUST9"


def test_create_estimate_requires_real_project_link(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    project = project_entry.load_project(pid, paths)
    unit = project.build_units[0].individuals[0]
    unit.qb_project_id = ""
    unit.qb_project_name = ""
    project_entry.save_project(project, paths)

    result = est.create_estimate(paths, project_id=pid, individual_id="ind1")

    assert result["ok"] is False and result["error"] == "project_not_linked"
    assert result["project"]["project_name"] == "Unit 12 | Build 2026"
    assert fake.created_estimates == []


def test_create_estimate_returns_project_setup_when_qbo_rejects_project_ref(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])

    def reject_project_ref(payload):
        fake.created_estimates.append(payload)
        raise QuickBooksApiError("http_400 qb_9341: Invalid ProjectRef intuit_tid=trace-123")

    fake.create_estimate = reject_project_ref
    result = est.create_estimate(paths, project_id=pid, individual_id="ind1")

    assert result["ok"] is False and result["error"] == "invalid_qb_project_ref"
    assert result["project"]["project_ref_invalid"] is True
    assert result["project"]["qb_project_id"] == "447322633"


def test_bind_project_persists_true_project_id_and_stable_name(paths):
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [])
    project = project_entry.load_project(pid, paths)
    unit = project.build_units[0].individuals[0]
    unit.qb_project_id = ""
    unit.qb_project_name = ""
    project_entry.save_project(project, paths)

    result = est.bind_project(paths, project_id=pid, individual_id="ind1", qb_project_id="447322633")

    assert result == {
        "ok": True,
        "qb_project_id": "447322633",
        "project_name": "Unit 12 | Build 2026",
    }
    saved = project_entry.load_project(pid, paths).build_units[0].individuals[0]
    assert saved.qb_project_id == "447322633"
    assert saved.qb_project_name == result["project_name"]

    project = project_entry.load_project(pid, paths)
    project.build_units[0].individuals[0].qb_project_id = ""
    project_entry.save_project(project, paths)
    from_url = est.bind_project(
        paths,
        project_id=pid,
        individual_id="ind1",
        qb_project_id="https://qbo.intuit.com/app/project?projectId=447322634",
    )
    assert from_url["ok"] is True and from_url["qb_project_id"] == "447322634"

    current_url = est.bind_project(
        paths,
        project_id=pid,
        individual_id="ind1",
        qb_project_id="https://sandbox.qbo.intuit.com/app/projects/projectdetails?id=70995",
    )
    assert current_url["ok"] is True and current_url["qb_project_id"] == "70995"


def test_project_can_be_previewed_and_linked_before_unit_is_configured(paths):
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [])
    project = project_entry.load_project(pid, paths)
    unit = project.build_units[0].individuals[0]
    unit.draft_id = None
    unit.qb_project_id = ""
    unit.qb_project_name = ""
    project_entry.save_project(project, paths)

    preview = est.preview_project_binding(paths, project_id=pid, individual_id="ind1")

    assert preview["ok"] is True
    assert preview["project"]["ready"] is False
    assert preview["project"]["project_name"] == "Unit 12 | Build 2026"
    linked = est.bind_project(
        paths,
        project_id=pid,
        individual_id="ind1",
        qb_project_id="447322633",
    )
    assert linked["ok"] is True
    saved = project_entry.load_project(pid, paths).build_units[0].individuals[0]
    assert saved.draft_id is None
    assert saved.qb_project_id == "447322633"


def test_project_preview_does_not_resurface_legacy_agency_prefixed_name(paths):
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [])
    project = project_entry.load_project(pid, paths)
    unit = project.build_units[0].individuals[0]
    unit.qb_project_id = "447322633"
    unit.qb_project_name = "Lakeville PD | Build 2026 | Unit 12"
    project_entry.save_project(project, paths)

    preview = est.preview_project_binding(paths, project_id=pid, individual_id="ind1")

    assert preview["ok"] is True
    assert preview["project"]["ready"] is True
    assert preview["project"]["project_name"] == "Unit 12 | Build 2026"


def test_bind_project_offers_stable_automatic_name_when_unit_number_is_missing(paths):
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [])
    assert est.bind_project(paths, project_id=pid, individual_id="ind1", qb_project_id="not-an-id") == {
        "ok": False, "error": "invalid_project_id",
    }

    project = project_entry.load_project(pid, paths)
    unit = project.build_units[0].individuals[0]
    unit.unit_number = ""
    unit.qb_project_id = ""
    unit.qb_project_name = ""
    unit.vin = "VIN123456"
    project_entry.save_project(project, paths)
    result = est.bind_project(paths, project_id=pid, individual_id="ind1", qb_project_id="123")
    assert result["ok"] is False and result["error"] == "project_identity_required"
    assert result["project"]["auto_label"] == "Patrol #1"

    accepted = est.bind_project(
        paths,
        project_id=pid,
        individual_id="ind1",
        qb_project_id="123",
        accept_auto_name=True,
    )
    assert accepted == {
        "ok": True,
        "qb_project_id": "123",
        "project_name": "Patrol #1 | Build 2026",
    }

    project = project_entry.load_project(pid, paths)
    unit = project.build_units[0].individuals[0]
    unit.unit_number = "77"
    project_entry.save_project(project, paths)
    saved = project_entry.load_project(pid, paths).build_units[0].individuals[0]
    assert saved.qb_project_id == "123"
    assert saved.qb_project_name == "Patrol #1 | Build 2026"


def test_create_estimate_requires_customer_confirmation_then_creates_top_level_customer(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    fake.find_top_level_customer_by_display_name = lambda name: None
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths)
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])

    blocked = est.create_estimate(paths, project_id=pid, individual_id="ind1")
    assert blocked["ok"] is False and blocked["error"] == "customer_required"
    assert fake.created_customers == [] and fake.created_estimates == []

    created = est.create_estimate(
        paths,
        project_id=pid,
        individual_id="ind1",
        customer_confirmed=True,
        customer_fields={
            "name": "Lakeville Police Department",
            "contact_name": "Patrol Contact",
            "contact_phone": "555-0100",
            "contact_email": "patrol@example.test",
            "bill_address_line1": "123 Main Street",
            "bill_city": "Lakeville",
            "bill_state": "MN",
            "bill_postal_code": "55044",
        },
    )
    assert created["ok"] is True
    assert fake.created_customers[0]["name"] == "Lakeville Police Department"
    assert fake.created_customers[0]["customer_type_id"] == "retail-type-id"
    assert fake.created_estimates[0]["CustomerRef"]["value"] == "CUST1"
    saved = project_entry.load_project(pid, paths)
    assert saved.customer.agency == "Lakeville Police Department"
    assert saved.customer.contact == "Patrol Contact"


def test_create_estimate_blocks_incomplete_confirmed_customer(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    fake.find_top_level_customer_by_display_name = lambda name: None
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    agc.handle_save_agency({"name": "Lakeville PD"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])

    result = est.create_estimate(
        paths,
        project_id=pid,
        individual_id="ind1",
        customer_confirmed=True,
        customer_fields={"name": "Lakeville PD", "contact_name": "Patrol Contact"},
    )

    assert result["ok"] is False and result["error"] == "customer_incomplete"
    assert "Billing address" in result["missing_fields"]
    assert fake.created_customers == [] and fake.created_estimates == []


def test_confirmed_profile_updates_linked_customer_before_estimate(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    agc.handle_save_agency({"name": "Lakeville PD"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id
    agc.set_qb_customer_id(paths, aid, "CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])

    result = est.create_estimate(
        paths,
        project_id=pid,
        individual_id="ind1",
        customer_confirmed=True,
        customer_fields={
            "name": "Lakeville PD",
            "contact_name": "Patrol Contact",
            "contact_phone": "555-0100",
            "contact_email": "patrol@example.test",
            "bill_address_line1": "123 Main Street",
            "bill_city": "Lakeville",
            "bill_state": "MN",
            "bill_postal_code": "55044",
        },
    )

    assert result["ok"] is True
    assert fake.updated_customers[0][0] == "CUST9"
    assert fake.updated_customers[0][2]["bill_address_line1"] == "123 Main Street"
    assert fake.updated_customers[0][2]["customer_type_id"] == "retail-type-id"
    assert fake.created_estimates


def test_create_estimates_batch_mixed(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 100.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    # Two units: one billable, one with an unmatched part.
    d_ok = new_draft(parts=[DraftPart(name="a", part_number="AA")])
    d_bad = new_draft(parts=[DraftPart(name="z", part_number="ZZ")])
    save_draft(d_ok, paths.workspace_drafts_dir)
    save_draft(d_bad, paths.workspace_drafts_dir)
    ok_pdf = paths.workspace_output_dir / "patrol-1.pdf"
    bad_pdf = paths.workspace_output_dir / "patrol-2.pdf"
    ok_pdf.write_bytes(b"%PDF-1.7\nvalid batch pdf")
    bad_pdf.write_bytes(b"%PDF-1.7\nvalid batch pdf")
    units = [
        IndividualUnit(individual_id="ok", unit_number="1", model="Tahoe", draft_id=d_ok.draft_id,
                       qb_project_id="447322633", pdf_path=str(ok_pdf)),
        IndividualUnit(individual_id="bad", unit_number="2", model="Tahoe", draft_id=d_bad.draft_id,
                       qb_project_id="447322634", pdf_path=str(bad_pdf)),
    ]
    project = project_entry.new_project(
        customer=CustomerInfo(agency_id=aid, build_year="2026", quote_number="Q1"),
        build_units=[BuildUnit(unit_id="bu1", vehicle_model="Tahoe", individuals=units)],
    )
    project_entry.save_project(project, paths)

    res = est.create_estimates_batch(paths, project_id=project.project_id, attach_pdf=True)
    assert res["created"] == 1 and res["blocked"] == 1
    by_id = {r["individual_id"]: r for r in res["results"]}
    assert by_id["ok"]["ok"] is True
    assert by_id["bad"]["ok"] is False and by_id["bad"]["error"] == "validation_failed"
    assert fake.uploaded_attachments == [("EST1", str(ok_pdf))]
