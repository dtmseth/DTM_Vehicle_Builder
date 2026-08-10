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


def test_create_estimate_uses_standard_legacy_custom_fields_request(monkeypatch):
    captured = {}

    def fake_post(entity, payload, *, query_params=None):
        captured["query_params"] = query_params
        return {"Estimate": {"Id": "1", "DocNumber": "10"}}

    client = api_client.QuickBooksApiClient(access_token="token", realm_id="realm")
    monkeypatch.setattr(client, "_post", fake_post)

    assert client.create_estimate({}) == {"qb_estimate_id": "1", "doc_number": "10"}
    assert captured["query_params"] is None
