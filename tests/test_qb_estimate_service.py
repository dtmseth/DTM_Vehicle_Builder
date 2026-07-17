"""Phase 3 Slice 3 + Estimates tests: per-vehicle jobs and draft estimates.

Covers part→QB-item resolution, the block-until-all-linked validation, the
sub-customer/job bridge, estimate creation + write-back, and batch creation.
Hermetic — no network, no cloud, no real keychain.
"""

from __future__ import annotations

import json

import pytest

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
    for sub in ("config", "projects", "drafts", "agencies"):
        (tmp_path / sub).mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_config_dir=tmp_path / "config",
        workspace_projects_dir=tmp_path / "projects",
        workspace_drafts_dir=tmp_path / "drafts",
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


class FakeClient:
    """Captures all QB write calls; returns canned ids."""

    def __init__(self):
        self.created_customers = []
        self.created_jobs = []
        self.created_estimates = []
        self.name_lookups = []

    def read_customer(self, customer_id):
        return None

    def create_customer(self, fields):
        self.created_customers.append(fields)
        return {"qb_customer_id": "CUST1", "sync_token": "0"}

    def find_customer_by_display_name(self, name):
        self.name_lookups.append(name)
        return ""

    def create_job(self, parent_id, display_name):
        self.created_jobs.append((parent_id, display_name))
        return {"qb_customer_id": "JOB1", "sync_token": "0"}

    def create_estimate(self, payload):
        self.created_estimates.append(payload)
        return {"qb_estimate_id": "EST1", "doc_number": "1001"}


def _use_fake(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(sync, "_build_client", lambda p: (fake, None))
    return fake


# ── fixtures: parts_db, agency, project + draft ───────────────────────────────


def _write_parts_db(paths, products):
    db = {"schema_version": 2, "products": products}
    (paths.workspace_config_dir / "parts_db.json").write_text(json.dumps(db, indent=2), "utf-8")
    parts_db_service.reset_for_testing()


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
    agc.handle_save_agency({"name": "Lakeville PD"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id
    if qb_customer_id:
        agc.set_qb_customer_id(paths, aid, qb_customer_id)
    return aid


def _make_project(paths, agency_id, draft_parts, *, quote="26-043"):
    draft = new_draft(vehicle_info={"VehicleType": "TAHOE"}, parts=list(draft_parts))
    save_draft(draft, paths.workspace_drafts_dir)
    unit = IndividualUnit(individual_id="ind1", unit_number="12", year="2026",
                          model="Tahoe", draft_id=draft.draft_id)
    bu = BuildUnit(unit_id="bu1", vehicle_model="Tahoe", individuals=[unit])
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


def test_resolve_skips_excluded_and_defaults_qty(paths):
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 5.0)})
    draft = new_draft(parts=[
        DraftPart(name="a", part_number="AA", quantity=0),      # qty 0 → bills 1
        DraftPart(name="x", part_number="AA", include=False),   # excluded → skipped
    ])
    lines, problems = est.resolve_build_lines(paths, draft)
    assert len(lines) == 1 and lines[0]["qty"] == 1 and lines[0]["amount"] == 5.0


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


def test_create_estimate_creates_job_and_estimate(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 250.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA", quantity=2)])

    res = est.create_estimate(paths, project_id=pid, individual_id="ind1", memo="Build 26-043")
    assert res["ok"] and res["qb_estimate_id"] == "EST1"
    assert res["line_count"] == 1 and res["total"] == 500.0
    # Job was created and the estimate is attached to it.
    assert fake.created_jobs and fake.created_estimates
    payload = fake.created_estimates[0]
    assert payload["CustomerRef"]["value"] == "JOB1"
    assert payload["Line"][0]["SalesItemLineDetail"]["ItemRef"]["value"] == "1"
    assert payload["Line"][0]["Amount"] == 500.0
    assert payload["CustomerMemo"]["value"] == "Build 26-043"
    # Both ids written back onto the unit.
    unit = project_entry.load_project(pid, paths).build_units[0].individuals[0]
    assert unit.qb_job_id == "JOB1" and unit.qb_estimate_id == "EST1"


def test_create_estimate_reuses_existing_job(paths, monkeypatch):
    fake = _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 10.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    pid = _make_project(paths, aid, [DraftPart(name="a", part_number="AA")])
    # Pre-set the job id so create shouldn't make a new one.
    proj = project_entry.load_project(pid, paths)
    proj.build_units[0].individuals[0].qb_job_id = "JOB_PRESET"
    project_entry.save_project(proj, paths)

    res = est.create_estimate(paths, project_id=pid, individual_id="ind1")
    assert res["ok"]
    assert fake.created_jobs == []  # reused JOB_PRESET
    assert fake.created_estimates[0]["CustomerRef"]["value"] == "JOB_PRESET"


def test_create_estimates_batch_mixed(paths, monkeypatch):
    _use_fake(monkeypatch)
    _write_parts_db(paths, {"p1": _linked_product("A", "AA", "1", 100.0)})
    aid = _make_agency(paths, qb_customer_id="CUST9")
    # Two units: one billable, one with an unmatched part.
    d_ok = new_draft(parts=[DraftPart(name="a", part_number="AA")])
    d_bad = new_draft(parts=[DraftPart(name="z", part_number="ZZ")])
    save_draft(d_ok, paths.workspace_drafts_dir)
    save_draft(d_bad, paths.workspace_drafts_dir)
    units = [
        IndividualUnit(individual_id="ok", unit_number="1", model="Tahoe", draft_id=d_ok.draft_id),
        IndividualUnit(individual_id="bad", unit_number="2", model="Tahoe", draft_id=d_bad.draft_id),
    ]
    project = project_entry.new_project(
        customer=CustomerInfo(agency_id=aid, build_year="2026", quote_number="Q1"),
        build_units=[BuildUnit(unit_id="bu1", vehicle_model="Tahoe", individuals=units)],
    )
    project_entry.save_project(project, paths)

    res = est.create_estimates_batch(paths, project_id=project.project_id)
    assert res["created"] == 1 and res["blocked"] == 1
    by_id = {r["individual_id"]: r for r in res["results"]}
    assert by_id["ok"]["ok"] is True
    assert by_id["bad"]["ok"] is False and by_id["bad"]["error"] == "validation_failed"
