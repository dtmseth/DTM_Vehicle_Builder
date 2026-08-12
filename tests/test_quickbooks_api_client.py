"""HTTP error handling tests for the QBO API client."""

from __future__ import annotations

import pytest

from dtm_buildsheet.app.adapters.quickbooks import api_client


class _Response:
    status_code = 400
    headers = {"intuit_tid": "trace-123"}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_post_surfaces_safe_qbo_fault_summary_without_detail(monkeypatch):
    response = _Response({
        "Fault": {
            "Error": [{
                "code": "6000",
                "Message": "Business Validation Error",
                "Detail": "Sensitive customer and item information",
            }],
        },
    })
    monkeypatch.setattr(api_client.requests, "post", lambda *args, **kwargs: response)
    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")

    with pytest.raises(api_client.QuickBooksApiError) as exc_info:
        client._post("estimate", {"private": "payload"})

    message = str(exc_info.value)
    assert message == "http_400 qb_6000: Business Validation Error intuit_tid=trace-123"
    assert "Sensitive customer" not in message


def test_post_keeps_status_and_trace_when_fault_cannot_be_parsed(monkeypatch):
    class _UnparseableResponse(_Response):
        def json(self):
            raise ValueError("not JSON")

    monkeypatch.setattr(
        api_client.requests, "post", lambda *args, **kwargs: _UnparseableResponse({})
    )
    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")

    with pytest.raises(api_client.QuickBooksApiError) as exc_info:
        client._post("estimate", {})

    assert str(exc_info.value) == "http_400 intuit_tid=trace-123"


def test_post_uses_current_minor_version(monkeypatch):
    captured = {}

    class _SuccessResponse(_Response):
        status_code = 200

        def json(self):
            return {"Estimate": {"Id": "1"}}

    def fake_post(url, **kwargs):
        captured["params"] = kwargs["params"]
        return _SuccessResponse({})

    monkeypatch.setattr(api_client.requests, "post", fake_post)
    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")

    assert client._post("estimate", {}) == {"Estimate": {"Id": "1"}}
    assert captured["params"]["minorversion"] == "75"


def test_transport_failure_never_exposes_request_url(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("https://quickbooks.example/path?access_token=do-not-log")

    monkeypatch.setattr(api_client.requests, "get", _boom)
    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")

    with pytest.raises(api_client.QuickBooksApiError) as exc_info:
        client.query("SELECT Id FROM Item")

    assert str(exc_info.value) == "request_failed"


def test_fetch_preferences_normalizes_enabled_sales_custom_fields(monkeypatch):
    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")
    monkeypatch.setattr(client, "query", lambda statement: {
        "Preferences": {
            "SalesFormsPrefs": {
                # QBO sends the flags and field labels in separate nested
                # CustomField wrapper objects, not in one flat array.
                "CustomField": [
                    {"CustomField": [
                        {"Name": "SalesFormsPrefs.UseSalesCustom1", "BooleanValue": True},
                        {"Name": "SalesFormsPrefs.UseSalesCustom2", "BooleanValue": False},
                        {"Name": "SalesFormsPrefs.UseSalesCustom3", "BooleanValue": True},
                    ]},
                    {"CustomField": [
                        {"Name": "SalesFormsPrefs.SalesCustomName1", "StringValue": "Unit Number"},
                        {"Name": "SalesFormsPrefs.SalesCustomName2", "StringValue": "Sales ID"},
                        {"Name": "SalesFormsPrefs.SalesCustomName3", "StringValue": "Vehicle Year, Make, Model"},
                    ]},
                ],
            },
        },
    })

    assert client.fetch_preferences()["sales_custom_fields"] == [
        {"definition_id": "1", "name": "Unit Number"},
        {"definition_id": "3", "name": "Vehicle Year, Make, Model"},
    ]


def test_find_customer_type_by_name_returns_unique_active_exact_match(monkeypatch):
    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")
    monkeypatch.setattr(client, "query", lambda statement: {
        "CustomerType": [{"Id": "retail-id", "Name": "Retail", "Active": True}],
    })

    assert client.find_customer_type_by_name("Retail") == "retail-id"


def test_create_estimate_uses_standard_legacy_custom_fields_request(monkeypatch):
    captured = {}

    def fake_post(entity, payload, *, query_params=None):
        captured["query_params"] = query_params
        return {"Estimate": {"Id": "1", "DocNumber": "10"}}

    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")
    monkeypatch.setattr(client, "_post", fake_post)

    assert client.create_estimate({}) == {"qb_estimate_id": "1", "doc_number": "10"}
    assert captured["query_params"] is None


def test_fetch_inactive_items_paginates_and_preserves_active_flag(monkeypatch):
    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")
    statements = []

    def fake_query(statement):
        statements.append(statement)
        if "STARTPOSITION 1" in statement:
            return {"Item": [{
                "Id": "old-1",
                "Name": "OLD-1 (deleted)",
                "Sku": "",
                "Description": "Historical part",
                "UnitPrice": 12.5,
                "Type": "NonInventory",
                "Active": False,
            }]}
        return {"Item": []}

    monkeypatch.setattr(client, "query", fake_query)

    assert client.fetch_inactive_items(page_size=1) == [{
        "qb_item_id": "old-1",
        "name": "OLD-1 (deleted)",
        "sku": "",
        "description": "Historical part",
        "unit_price": 12.5,
        "type": "NonInventory",
        "active": False,
    }]
    assert len(statements) == 2
    assert all("WHERE Active = false" in statement for statement in statements)
