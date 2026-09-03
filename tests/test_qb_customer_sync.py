"""Phase 3 (first cut) tests: QuickBooks Customers → VB Agencies down-sync.

Covers the agency-service upsert/preview matching and the qb_sync_service
orchestration. Hermetic — no network, no cloud, no real keychain.
"""

from __future__ import annotations

import pytest

from dtm_buildsheet.app.services import agency_service as agc
from dtm_buildsheet.app.services import qb_sync_service as sync
from dtm_buildsheet.app.adapters.quickbooks.api_client import _normalize_customer
from dtm_buildsheet.paths import AppPaths


@pytest.fixture
def paths(tmp_path):
    return AppPaths(workspace_dir=tmp_path)


@pytest.fixture(autouse=True)
def _no_cloud(monkeypatch):
    # Belt-and-suspenders: the batch mirror is a no-op outside cloud mode, but
    # make absolutely sure tests never touch it.
    import dtm_buildsheet.app.services.shared_work_service as sw
    monkeypatch.setattr(sw, "save_settings_to_cloud_batch_in_background", lambda items: None)
    agc._invalidate_cache  # noqa: B018 — ensure symbol exists


def _cust(qid, name, **kw):
    return {"qb_customer_id": str(qid), "name": name, "contact_name": kw.get("contact_name", ""),
            "contact_email": kw.get("contact_email", ""), "contact_phone": kw.get("contact_phone", ""),
            "is_sub": kw.get("is_sub", False)}


# ── normalization ────────────────────────────────────────────────────────────


def test_normalize_customer_prefers_company_name_and_flags_sub():
    raw = {"Id": 9, "DisplayName": "Disp", "CompanyName": "Acme PD",
           "ParentRef": {"value": "3"}, "Job": True}
    n = _normalize_customer(raw)
    assert n["name"] == "Acme PD"
    assert n["is_sub"] is True


def test_normalize_customer_falls_back_to_display_name():
    n = _normalize_customer({"Id": 1, "DisplayName": "Solo"})
    assert n["name"] == "Solo"
    assert n["is_sub"] is False


def test_normalize_customer_keeps_contact_and_address_profile():
    n = _normalize_customer({
        "Id": 1,
        "DisplayName": "Alpha PD",
        "Mobile": {"FreeFormNumber": "555-0111"},
        "Fax": {"FreeFormNumber": "555-0112"},
        "WebAddr": {"URI": "https://alpha.example"},
        "Notes": "Purchasing uses PO numbers",
        "Taxable": False,
        "BillAddr": {"Line1": "1 Main", "City": "Alpha", "CountrySubDivisionCode": "MN", "PostalCode": "55001"},
        "ShipAddr": {"Line1": "2 Depot", "Country": "US"},
    })
    assert n["mobile_phone"] == "555-0111"
    assert n["fax"] == "555-0112"
    assert n["website"] == "https://alpha.example"
    assert n["notes"] == "Purchasing uses PO numbers"
    assert n["taxable"] is False
    assert n["bill_address_line1"] == "1 Main"
    assert n["bill_city"] == "Alpha"
    assert n["bill_state"] == "MN"
    assert n["ship_address_line1"] == "2 Depot"
    assert n["ship_country"] == "US"


# ── upsert: create / link / fill ─────────────────────────────────────────────


def test_import_creates_new_agencies(paths):
    res = agc.upsert_agencies_from_qb([_cust(1, "Alpha PD"), _cust(2, "Beta SO")], paths)
    assert res == {"ok": True, "created": 2, "updated": 0, "total": 2}
    names = {a.name: a for a in agc.load_agencies(paths)}
    assert names["Alpha PD"].qb_customer_id == "1"
    assert names["Beta SO"].qb_customer_id == "2"


def test_import_does_not_schedule_vehicle_folders(paths, monkeypatch):
    import dtm_buildsheet.app.services.vehicle_folder_provisioning_service as folders

    monkeypatch.setattr(
        folders,
        "folder_provisioning_targets",
        lambda: folders.ProvisioningTargets(True, True),
    )
    monkeypatch.setattr(
        folders,
        "schedule_agency_folder_provisioning_batch",
        lambda *_args, **_kwargs: pytest.fail(
            "QBO Customer imports must not create vehicle-project folders"
        ),
    )

    result = agc.upsert_agencies_from_qb([_cust(1, "Standalone QBO Customer")], paths)

    assert result["created"] == 1
    stored = agc.load_agencies(paths)[0]
    assert stored.company_folder_status == "not_provisioned"
    assert stored.shop_folder_status == "not_provisioned"


def test_import_links_existing_by_name_without_clobbering(paths):
    # Pre-existing agency entered by the user, no QB link, with a phone already.
    agc.handle_save_agency({"name": "Alpha PD", "contact_phone": "111"}, paths)
    res = agc.upsert_agencies_from_qb(
        [_cust(1, "Alpha PD", contact_phone="999", contact_email="a@pd.gov")], paths
    )
    assert res["created"] == 0 and res["updated"] == 1
    a = agc.load_agencies(paths)[0]
    assert a.qb_customer_id == "1"          # linked
    assert a.contact_phone == "111"          # user's value preserved
    assert a.contact_email == "a@pd.gov"     # empty field filled from QB


def test_new_local_agency_defaults_to_not_taxable(paths):
    saved = agc.handle_save_agency({"name": "Default Non-Taxable PD"}, paths)
    agency = agc.get_agency(paths, saved["agency"]["agency_id"])
    assert agency.taxable is False


def test_import_fills_missing_extended_profile_without_erasing_existing(paths):
    saved = agc.handle_save_agency({
        "name": "Alpha PD",
        "mobile_phone": "local-mobile",
        "bill_address_line1": "Local Street",
    }, paths)
    res = agc.upsert_agencies_from_qb([{
        **_cust(1, "Alpha PD", contact_phone="999"),
        "mobile_phone": "qb-mobile",
        "website": "https://alpha.example",
        "bill_address_line1": "QB Street",
        "bill_city": "Alpha",
        "bill_state": "MN",
        "bill_postal_code": "55001",
        "taxable": False,
    }], paths)
    assert res["updated"] == 1
    a = agc.get_agency(paths, saved["agency"]["agency_id"])
    assert a.mobile_phone == "local-mobile"
    assert a.bill_address_line1 == "Local Street"
    assert a.website == "https://alpha.example"
    assert a.bill_city == "Alpha"
    assert a.taxable is False


def test_import_matches_by_qb_id_over_name(paths):
    agc.upsert_agencies_from_qb([_cust(1, "Alpha PD")], paths)
    # The customer was renamed in QB but keeps the same Id → still one agency.
    res = agc.upsert_agencies_from_qb([_cust(1, "Alpha Police Department")], paths)
    assert res["created"] == 0 and res["updated"] == 1
    assert len(agc.load_agencies(paths)) == 1


def test_import_is_idempotent(paths):
    custs = [_cust(1, "Alpha PD"), _cust(2, "Beta SO")]
    agc.upsert_agencies_from_qb(custs, paths)
    res = agc.upsert_agencies_from_qb(custs, paths)
    assert res["created"] == 0 and res["updated"] == 2
    assert len(agc.load_agencies(paths)) == 2


def test_import_skips_nameless_customers(paths):
    res = agc.upsert_agencies_from_qb([_cust(1, "")], paths)
    assert res["created"] == 0
    assert agc.load_agencies(paths) == []


def test_qb_customer_id_survives_reload(paths):
    agc.upsert_agencies_from_qb([_cust(7, "Gamma PD")], paths)
    agc._invalidate_cache(paths)  # force re-read from disk
    a = agc.load_agencies(paths)[0]
    assert a.qb_customer_id == "7"


def test_qb_customer_id_preserved_through_user_edit(paths):
    agc.upsert_agencies_from_qb([_cust(7, "Gamma PD")], paths)
    aid = agc.load_agencies(paths)[0].agency_id
    # User edits the agency through the normal save path (no qb field in body).
    agc.handle_save_agency({"agency_id": aid, "name": "Gamma PD", "contact_name": "Sam"}, paths)
    a = agc.load_agencies(paths)[0]
    assert a.qb_customer_id == "7"
    assert a.contact_name == "Sam"


# ── preview (dry run) ────────────────────────────────────────────────────────


def test_preview_counts_without_writing(paths):
    agc.handle_save_agency({"name": "Alpha PD"}, paths)
    pre = agc.preview_qb_customer_import(
        [_cust(1, "Alpha PD"), _cust(2, "Beta SO")], paths
    )
    assert pre == {"ok": True, "total": 2, "would_create": 1, "would_update": 1}
    # Nothing was written — still just the one user-created agency.
    assert len(agc.load_agencies(paths)) == 1


# ── orchestration ────────────────────────────────────────────────────────────


def test_import_customers_not_connected(paths, monkeypatch):
    from dtm_buildsheet.app.adapters.quickbooks.oauth_client import QuickBooksOAuthError

    def _boom(p):
        raise QuickBooksOAuthError("not_connected")

    monkeypatch.setattr(sync.quickbooks_service, "ensure_access_token", _boom)
    res = sync.import_customers(paths)
    assert res["ok"] is False and res["error"] == "not_connected"


def test_import_customers_delegates_to_agency_service(paths, monkeypatch):
    class _FakeClient:
        def fetch_active_customers(self, **kw):
            return [_cust(1, "Alpha PD"), _cust(2, "Beta SO")]

    monkeypatch.setattr(sync, "_build_client", lambda p: (_FakeClient(), None))
    res = sync.import_customers(paths)
    assert res["created"] == 2
    assert {a.name for a in agc.load_agencies(paths)} == {"Alpha PD", "Beta SO"}
