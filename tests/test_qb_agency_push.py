"""Phase 3, Slice 2 tests: VB Agencies → QuickBooks Customers up-sync.

Covers the api_client payload mapping, the qb_sync_service push (create /
update / recreate / not-connected), the qb_customer_id write-back, and the
auto-trigger from handle_save_agency. Hermetic — no network, no cloud, no
real keychain.
"""

from __future__ import annotations

import pytest

from dtm_buildsheet.app.adapters.quickbooks.api_client import (
    QuickBooksApiError,
    _build_customer_payload,
    _customer_result,
)
from dtm_buildsheet.app.services import agency_service as agc
from dtm_buildsheet.app.services import qb_sync_service as sync
from dtm_buildsheet.paths import AppPaths


@pytest.fixture
def paths(tmp_path):
    return AppPaths(workspace_dir=tmp_path)


@pytest.fixture(autouse=True)
def _no_cloud(monkeypatch):
    import dtm_buildsheet.app.services.shared_work_service as sw
    monkeypatch.setattr(sw, "save_setting_to_cloud_in_background", lambda *a, **k: None)
    monkeypatch.setattr(sw, "save_settings_to_cloud_batch_in_background", lambda items: None)


class _FakeClient:
    """Records create/update/read calls; returns canned ids."""

    def __init__(self, *, existing=None, new_id="500"):
        self.existing = existing  # raw customer dict returned by read_customer
        self.new_id = new_id
        self.created = []
        self.updated = []
        self.reads = []

    def read_customer(self, customer_id):
        self.reads.append(customer_id)
        return self.existing

    def create_customer(self, fields):
        self.created.append(fields)
        return {"qb_customer_id": self.new_id, "sync_token": "0"}

    def update_customer(self, customer_id, sync_token, fields):
        self.updated.append((customer_id, sync_token, fields))
        return {"qb_customer_id": customer_id, "sync_token": "1"}


# ── payload mapping ──────────────────────────────────────────────────────────


def test_build_customer_payload_maps_only_present_fields():
    p = _build_customer_payload(
        {"name": "Alpha PD", "contact_email": "a@pd.gov",
         "contact_phone": "555", "contact_name": "Jane Doe"}
    )
    assert p["DisplayName"] == "Alpha PD"
    assert p["CompanyName"] == "Alpha PD"
    assert p["PrimaryEmailAddr"] == {"Address": "a@pd.gov"}
    assert p["PrimaryPhone"] == {"FreeFormNumber": "555"}
    assert p["GivenName"] == "Jane" and p["FamilyName"] == "Doe"


def test_build_customer_payload_omits_empty_and_single_name():
    p = _build_customer_payload({"name": "Solo", "contact_name": "Cher"})
    assert p == {"DisplayName": "Solo", "CompanyName": "Solo", "GivenName": "Cher"}


def test_build_customer_payload_maps_full_customer_profile():
    p = _build_customer_payload({
        "contact_title": "Fleet Manager",
        "mobile_phone": "555-0111",
        "fax": "555-0112",
        "website": "https://alpha.example",
        "notes": "Use PO number",
        "taxable": False,
        "bill_address_line1": "1 Main",
        "bill_city": "Alpha",
        "bill_state": "MN",
        "bill_postal_code": "55001",
        "ship_address_line1": "2 Depot",
    })
    assert p["Title"] == "Fleet Manager"
    assert p["Mobile"] == {"FreeFormNumber": "555-0111"}
    assert p["Fax"] == {"FreeFormNumber": "555-0112"}
    assert p["WebAddr"] == {"URI": "https://alpha.example"}
    assert p["Notes"] == "Use PO number"
    assert p["Taxable"] is False
    assert p["BillAddr"] == {
        "Line1": "1 Main", "City": "Alpha", "CountrySubDivisionCode": "MN", "PostalCode": "55001",
    }
    assert p["ShipAddr"] == {"Line1": "2 Depot"}


def test_customer_result_extracts_id_and_token():
    r = _customer_result({"Customer": {"Id": 42, "SyncToken": 3}})
    assert r == {"qb_customer_id": "42", "sync_token": "3"}


# ── push: create / update / recreate ─────────────────────────────────────────


def test_push_creates_customer_and_writes_back_id(paths, monkeypatch):
    agc.handle_save_agency({"name": "Alpha PD", "contact_email": "a@pd.gov"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id

    fake = _FakeClient(new_id="900")
    monkeypatch.setattr(sync, "_build_client", lambda p: (fake, None))

    res = sync.push_agency(paths, aid)
    assert res == {"ok": True, "qb_customer_id": "900", "action": "created"}
    assert len(fake.created) == 1 and fake.created[0]["name"] == "Alpha PD"
    # Id written back onto the agency record.
    assert agc.get_agency(paths, aid).qb_customer_id == "900"


def test_push_updates_when_already_linked(paths, monkeypatch):
    agc.handle_save_agency({"name": "Beta SO"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id
    agc.set_qb_customer_id(paths, aid, "77")

    fake = _FakeClient(existing={"Id": "77", "SyncToken": "5"})
    monkeypatch.setattr(sync, "_build_client", lambda p: (fake, None))

    res = sync.push_agency(paths, aid)
    assert res == {"ok": True, "qb_customer_id": "77", "action": "updated"}
    assert fake.reads == ["77"]
    assert fake.updated and fake.updated[0][0] == "77" and fake.updated[0][1] == "5"
    assert fake.created == []


def test_push_recreates_when_linked_customer_gone(paths, monkeypatch):
    agc.handle_save_agency({"name": "Gamma PD"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id
    agc.set_qb_customer_id(paths, aid, "88")

    fake = _FakeClient(existing=None, new_id="123")  # read returns None
    monkeypatch.setattr(sync, "_build_client", lambda p: (fake, None))

    res = sync.push_agency(paths, aid)
    assert res["action"] == "created" and res["qb_customer_id"] == "123"
    assert fake.created and not fake.updated
    assert agc.get_agency(paths, aid).qb_customer_id == "123"


def test_push_unknown_agency(paths, monkeypatch):
    monkeypatch.setattr(sync, "_build_client", lambda p: (_FakeClient(), None))
    assert sync.push_agency(paths, "nope")["error"] == "unknown_agency"


def test_push_not_connected(paths, monkeypatch):
    from dtm_buildsheet.app.adapters.quickbooks.oauth_client import QuickBooksOAuthError

    def _boom(p):
        raise QuickBooksOAuthError("not_connected")

    monkeypatch.setattr(sync.quickbooks_service, "ensure_access_token", _boom)
    agc.handle_save_agency({"name": "Delta PD"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id
    res = sync.push_agency(paths, aid)
    assert res["ok"] is False and res["error"] == "not_connected"


def test_push_surfaces_api_error(paths, monkeypatch):
    agc.handle_save_agency({"name": "Eps PD"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id

    class _Boom(_FakeClient):
        def create_customer(self, fields):
            raise QuickBooksApiError("http_400 intuit_tid=abc")

    monkeypatch.setattr(sync, "_build_client", lambda p: (_Boom(), None))
    res = sync.push_agency(paths, aid)
    assert res["ok"] is False and "http_400" in res["error"]
    assert agc.get_agency(paths, aid).qb_customer_id == ""  # nothing written back


# ── auto-trigger + re-entrancy ───────────────────────────────────────────────


def test_save_agency_triggers_background_push(paths, monkeypatch):
    calls = []
    monkeypatch.setattr(
        sync, "push_agency_in_background", lambda p, aid: calls.append(aid)
    )
    agc.handle_save_agency({"name": "Zeta PD"}, paths)
    assert len(calls) == 1


def test_background_push_noops_under_pytest(paths, monkeypatch):
    # PYTEST_CURRENT_TEST is set, so the background entry must not build a client.
    called = []
    monkeypatch.setattr(sync, "_build_client", lambda p: called.append(1) or (None, {"ok": False}))
    sync.push_agency_in_background(paths, "anything")
    assert called == []


def test_set_qb_customer_id_does_not_loop(paths, monkeypatch):
    # Writing the id back must not itself fire another push.
    agc.handle_save_agency({"name": "Eta PD"}, paths)
    aid = agc.load_agencies(paths)[0].agency_id
    calls = []
    monkeypatch.setattr(sync, "push_agency_in_background", lambda p, a: calls.append(a))
    agc.set_qb_customer_id(paths, aid, "55")
    assert calls == []  # set_qb_customer_id bypasses handle_save_agency
    assert agc.get_agency(paths, aid).qb_customer_id == "55"
