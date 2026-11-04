"""Hermetic tests for the Shopmonkey read/write integration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from dtm_buildsheet.app.adapters.shopmonkey import api_client
from dtm_buildsheet.app.services import shopmonkey_service as service
from dtm_buildsheet.app.services.request_access_service import required_capabilities
from dtm_buildsheet.domain.agency_models import AgencyRecord
from dtm_buildsheet.domain.operations_policy import Capability
from dtm_buildsheet.paths import AppPaths
from tools.configure_shopmonkey_pricing import build_config as build_vendor_guide_config
from tools.shopmonkey_retail_pricing_pilot import discounted_cents, should_auto_price


class _Response:
    def __init__(self, payload, *, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {"x-request-id": "sm-request-1"}

    def json(self):
        return self._payload


def test_api_client_uses_bearer_token_and_paginates_customer_search(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        skip = kwargs["json"]["skip"]
        if skip == 0:
            return _Response({"success": True, "data": [{"id": "one"}, {"id": "two"}], "meta": {"hasMore": True}})
        return _Response({"success": True, "data": [{"id": "three"}], "meta": {"hasMore": False}})

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    client = api_client.ShopmonkeyApiClient(api_key="secret-token")

    rows = client.search_customers(page_size=2)

    assert [row["id"] for row in rows] == ["one", "two", "three"]
    assert calls[0][0:2] == ("POST", "https://api.shopmonkey.cloud/v3/customer/search")
    assert calls[0][2]["headers"]["Authorization"] == "Bearer secret-token"
    assert calls[1][2]["json"]["skip"] == 2


def test_api_client_lists_labels_and_brands_with_bounded_pagination(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        path = url.rsplit("/", 1)[-1]
        skip = kwargs["params"]["skip"]
        if skip == 0:
            return _Response({
                "success": True,
                "data": [{"id": f"{path}-1"}, {"id": f"{path}-deleted", "deleted": True}],
                "meta": {"hasMore": True},
            })
        return _Response({
            "success": True,
            "data": [{"id": f"{path}-2"}],
            "meta": {"hasMore": False},
        })

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    client = api_client.ShopmonkeyApiClient(api_key="secret-token")

    assert [row["id"] for row in client.list_labels()] == ["label-1", "label-2"]
    assert [row["id"] for row in client.list_brands()] == ["brand-1", "brand-2"]
    assert calls[0][0:2] == ("GET", "https://api.shopmonkey.cloud/v3/label")
    assert calls[2][0:2] == ("GET", "https://api.shopmonkey.cloud/v3/brand")


def test_api_client_error_does_not_surface_provider_body(monkeypatch):
    monkeypatch.setattr(
        api_client.requests,
        "request",
        lambda *args, **kwargs: _Response(
            {"success": False, "message": "Private customer data"},
            status=401,
        ),
    )
    client = api_client.ShopmonkeyApiClient(api_key="bad-token")

    with pytest.raises(api_client.ShopmonkeyApiError) as exc_info:
        client.check_status()

    assert str(exc_info.value) == "http_401"
    assert "Private customer" not in str(exc_info.value)
    assert exc_info.value.request_id == "sm-request-1"


def test_retail_pricing_pilot_applies_whelen_discount_and_preserves_manual_prices():
    assert discounted_cents(20600, Decimal("36")) == 13184
    assert should_auto_price(current_cents=20600, msrp_cents=20600, target_cents=13184)
    assert should_auto_price(
        current_cents=17057,
        msrp_cents=20600,
        target_cents=13184,
        pricing_matrix_id="default-matrix",
    )
    assert not should_auto_price(current_cents=15000, msrp_cents=20600, target_cents=13184)
    assert not should_auto_price(current_cents=13184, msrp_cents=20600, target_cents=13184)


class _MemoryStore:
    def __init__(self):
        self.data = {}

    def load(self):
        return dict(self.data)

    def save(self, value):
        self.data = dict(value)

    def clear(self):
        self.data = {}


class _FakeClient:
    customers = []
    vehicles = []
    inventory_parts = []
    inventory_tires = []
    inventory_categories = []
    labels = []
    brands = []
    checked_keys = []
    created_categories = []
    created_parts = []

    def __init__(self, *, api_key):
        self.api_key = api_key

    def check_status(self):
        self.checked_keys.append(self.api_key)

    def search_customers(self):
        return list(self.customers)

    def fetch_customer_vehicles(self, customer_id):
        assert customer_id == "customer-1"
        return list(self.vehicles)

    def search_inventory_parts(self, *, category_id=""):
        rows = list(self.inventory_parts)
        if category_id:
            rows = [row for row in rows if row.get("categoryId") == category_id]
        return rows

    def search_inventory_tires(self):
        return list(self.inventory_tires)

    def list_inventory_categories(self):
        return list(self.inventory_categories)

    def list_labels(self):
        return list(self.labels)

    def list_brands(self):
        return list(self.brands)

    def create_inventory_category(self, name, *, parent_id=""):
        row = {"id": f"category-{len(self.created_categories) + 1}", "name": name}
        self.created_categories.append(row)
        self.inventory_categories.append(row)
        return dict(row)

    def create_inventory_part(self, *, name, category_id=""):
        row = {
            "id": f"part-{len(self.created_parts) + 1}",
            "name": name,
            "categoryId": category_id,
        }
        self.created_parts.append(row)
        self.inventory_parts.append(row)
        return dict(row)


@pytest.fixture
def store(monkeypatch):
    value = _MemoryStore()
    monkeypatch.setattr(service, "_store", lambda: value)
    monkeypatch.setattr(service, "ShopmonkeyApiClient", _FakeClient)
    _FakeClient.customers = []
    _FakeClient.vehicles = []
    _FakeClient.inventory_parts = []
    _FakeClient.inventory_tires = []
    _FakeClient.inventory_categories = []
    _FakeClient.labels = []
    _FakeClient.brands = []
    _FakeClient.checked_keys = []
    _FakeClient.created_categories = []
    _FakeClient.created_parts = []
    return value


def test_connect_validates_then_stores_key_without_returning_it(store):
    result = service.connect("  shopmonkey-secret  ")

    assert result["ok"] is True
    assert _FakeClient.checked_keys == ["shopmonkey-secret"]
    assert store.data["api_key"] == "shopmonkey-secret"
    assert "shopmonkey-secret" not in str(result)
    assert service.disconnect()["connected"] is False
    assert store.data == {}


def test_hosted_pricing_save_is_hmac_signed_without_sending_api_key(monkeypatch, store):
    store.data = {"api_key": "shopmonkey-secret"}
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        body = kwargs["data"]
        headers = kwargs["headers"]
        digest = hashlib.sha256(body).hexdigest()
        message = (
            f"{headers['X-DTM-Timestamp']}.{headers['X-DTM-Nonce']}.PUT.{digest}"
            .encode("utf-8")
        )
        expected = base64.b64encode(
            hmac.new(b"shopmonkey-secret", message, hashlib.sha256).digest()
        ).decode("ascii")
        assert hmac.compare_digest(headers["X-DTM-Signature"], expected)
        return 200, {
            "ok": True,
            "config": {"revision": "new-revision", "mode": "test"},
        }

    monkeypatch.setattr(service, "request_json_document", fake_request)
    result = service.save_pricing_settings(
        {"mode": "test", "customer_types": [], "rules": []}, "old-revision"
    )

    assert result["ok"] is True
    assert result["config"]["revision"] == "new-revision"
    assert captured["method"] == "PUT"
    assert "shopmonkey-secret" not in json.dumps(captured["headers"])
    assert b"shopmonkey-secret" not in captured["data"]


def test_pricing_references_only_return_real_customer_labels_and_part_brands(store):
    store.data = {"api_key": "shopmonkey-secret"}
    _FakeClient.labels = [
        {"id": "retail-label", "name": "$ Retail $", "entity": "Customer", "color": "green"},
        {"id": "retail-label-copy", "name": "$ RETAIL $", "entity": "Customer"},
        {"id": "order-label", "name": "Rush", "entity": "Order"},
    ]
    _FakeClient.brands = [
        {"id": "whelen-brand", "name": "Whelen", "entity": "Part"},
        {"id": "tire-brand", "name": "Whelen Tires", "entity": "Tire"},
    ]

    result = service.pricing_reference_data()

    assert result == {
        "ok": True,
        "customer_labels": [{"id": "retail-label", "name": "$ Retail $", "color": "green"}],
        "brands": [{"id": "whelen-brand", "name": "Whelen"}],
    }


def test_vendor_guide_config_covers_every_available_brand_in_test_mode():
    brand_names = [
        "Angel Armor", "AnyGlide", "Apparel/Displays/Lit", "Brute", "Fey",
        "Gamber Johnson", "Kussmaul", "NightRide", "PAC Tool Mounts", "Patrol PC",
        "REDARC", "Santa Cruz Gunlocks", "Setina", "SoundOff Signal", "Superwinch",
        "SW Military", "TigerTough", "TruckVault", "Westin", "Westin Public Safety",
        "Whelen",
    ]
    references = {
        "customer_labels": [
            {"id": "label-retail", "name": "$ Retail $"},
            {"id": "label-wholesale", "name": "$ Wholesale $"},
        ],
        "brands": [
            {"id": f"brand-{index}", "name": name}
            for index, name in enumerate(brand_names)
        ],
    }

    config, pending = build_vendor_guide_config({}, references)
    rules = {(row["brand"], row["customer_type_id"]): row for row in config["rules"]}

    assert config["mode"] == "test"
    assert config["preserve_custom_prices"] is True
    assert len(rules) == 63
    assert sum(row["enabled"] for row in rules.values()) == 22
    assert config["customer_types"][2]["match_untagged"] is True
    assert rules[("Gamber Johnson", "retail")]["percent"] == 40
    assert rules[("Gamber Johnson", "wholesale")]["percent"] == 40
    assert rules[("Gamber Johnson", "default")]["percent"] == 40
    assert rules[("Whelen", "retail")]["percent"] == 36
    assert rules[("Whelen", "wholesale")]["percent"] == 43
    assert rules[("Setina", "wholesale")]["percent"] == 30
    assert rules[("Westin", "retail")]["basis"] == "cost"
    assert rules[("Westin", "retail")]["operation"] == "markup"
    assert rules[("Westin", "retail")]["percent"] == 25
    assert rules[("Westin", "wholesale")]["enabled"] is False
    assert rules[("Kussmaul", "retail")]["enabled"] is True
    assert rules[("Kussmaul", "wholesale")]["enabled"] is False
    assert rules[("Kussmaul", "default")]["enabled"] is False
    assert rules[("Angel Armor", "retail")]["enabled"] is False
    assert any("GAMBER JOHNSON CRADLE/DOCK" in row for row in pending)
    assert any("Westin" in row and "conflicts" in row for row in pending)
    assert len(pending) == 5


def test_pricing_save_canonicalizes_live_shopmonkey_reference_names(monkeypatch, store):
    store.data = {"api_key": "shopmonkey-secret"}
    _FakeClient.labels = [
        {"id": "retail-label", "name": "$ Retail $", "entity": "Customer"},
    ]
    _FakeClient.brands = [
        {"id": "whelen-brand", "name": "Whelen", "entity": "Part"},
    ]
    captured = {}

    def fake_management(method, payload=None):
        captured.update(payload)
        return 200, {"ok": True, "config": payload["config"]}

    monkeypatch.setattr(service, "_pricing_management_request", fake_management)
    result = service.save_pricing_settings({
        "customer_types": [{
            "id": "retail", "name": "Retail", "label_id": "retail-label", "label": "typo",
        }],
        "rules": [{
            "id": "whelen-retail", "brand_id": "whelen-brand", "brand": "typo",
            "customer_type_id": "retail", "basis": "retail", "operation": "discount",
            "percent": 36,
        }],
    }, "revision")

    assert result["ok"] is True
    assert captured["config"]["schema_version"] == 2
    assert captured["config"]["customer_types"][0]["label"] == "$ Retail $"
    assert captured["config"]["rules"][0]["brand"] == "Whelen"


def test_cleanup_report_flags_duplicates_missing_fields_and_tax_mismatch(tmp_path, monkeypatch, store):
    store.data = {"api_key": "key"}
    _FakeClient.customers = [
        {
            "id": "customer-1",
            "companyName": "Springfield Police Department",
            "customerType": "Fleet",
            "emails": [{"email": "fleet@example.com", "primary": True}],
            "phoneNumbers": [{"number": "555-111-2222", "primary": True}],
            "address1": "1 Main St",
            "city": "Springfield",
            "state": "IL",
            "postalCode": "62701",
            "country": "US",
            "taxExempt": False,
            "vehicleCount": 2,
        },
        {
            "id": "customer-2",
            "companyName": "Springfield Police Department",
            "customerType": "Fleet",
            "emails": [],
            "phoneNumbers": [],
            "taxExempt": True,
        },
    ]
    agency = AgencyRecord(
        agency_id="agency-1",
        name="Springfield Police Department",
        taxable=False,
    )
    monkeypatch.setattr(service.agency_service, "load_agencies", lambda paths: [agency])

    result = service.cleanup_report(AppPaths(workspace_dir=tmp_path))

    assert result["ok"] is True
    assert result["summary"] == {
        "total": 2,
        "fleets": 2,
        "customers": 0,
        "records_with_issues": 2,
        "duplicate_groups": 1,
        "tax_mismatches": 1,
        "missing_all_contact": 1,
    }
    first = next(row for row in result["customers"] if row["shopmonkey_customer_id"] == "customer-1")
    assert "Tax status differs from DTM agency" in first["issues"]
    assert first["dtm_agency"]["agency_id"] == "agency-1"
    second = next(row for row in result["customers"] if row["shopmonkey_customer_id"] == "customer-2")
    assert "Missing email" in second["issues"]
    assert "Missing phone" in second["issues"]


def test_customer_vehicle_review_flags_identity_owner_and_photo_gaps(store):
    store.data = {"api_key": "key"}
    _FakeClient.vehicles = [{
        "id": "vehicle-1",
        "year": 2025,
        "make": "Ford",
        "model": "Interceptor",
        "unit": "",
        "vin": "",
        "ownerCount": 0,
        "customPhoto": False,
    }]

    result = service.customer_vehicles("customer-1")

    assert result["summary"] == {"total": 1, "with_issues": 1, "missing_photos": 1}
    assert result["vehicles"][0]["issues"] == [
        "Missing unit number",
        "Missing VIN",
        "No customer owner link",
        "No custom photo",
    ]


def test_inventory_client_searches_parts_tires_and_categories_with_pagination(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        paging = kwargs.get("json") or kwargs.get("params") or {}
        skip = paging["skip"]
        if skip == 0:
            return _Response({"success": True, "data": [{"id": "one"}], "meta": {"hasMore": True}})
        return _Response({"success": True, "data": [{"id": "two"}], "meta": {"hasMore": False}})

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    client = api_client.ShopmonkeyApiClient(api_key="secret-token")

    assert [row["id"] for row in client._search_inventory(
        "/inventory_part/search", operation="test", page_size=1
    )] == ["one", "two"]
    assert [row["id"] for row in client.list_inventory_categories(page_size=1)] == ["one", "two"]
    assert calls[0][0:2] == ("POST", "https://api.shopmonkey.cloud/v3/inventory_part/search")
    assert calls[2][0:2] == ("GET", "https://api.shopmonkey.cloud/v3/inventory_category")


def test_inventory_client_soft_deletes_parts_and_tires_with_reason(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response({"success": True, "data": {"deleted": True}})

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    client = api_client.ShopmonkeyApiClient(api_key="secret-token")

    client.soft_delete_inventory_part("part/id", reason="Catalog rebuild")
    client.soft_delete_inventory_tire("tire/id", reason="Catalog rebuild")

    assert [(method, url) for method, url, _ in calls] == [
        ("PATCH", "https://api.shopmonkey.cloud/v3/inventory_part/part%2Fid/delete"),
        ("PATCH", "https://api.shopmonkey.cloud/v3/inventory_tire/tire%2Fid/delete"),
    ]
    assert calls[0][2]["json"] == {"reason": "Catalog rebuild"}
    assert calls[1][2]["json"] == {"reason": "Catalog rebuild"}
    assert calls[0][2]["headers"]["Authorization"] == "Bearer secret-token"


def test_inventory_client_creates_minimal_category_and_part(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        body = kwargs.get("json") or {}
        return _Response({"success": True, "data": {"id": "created-id", **body}})

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    client = api_client.ShopmonkeyApiClient(api_key="secret-token")

    client.create_inventory_category("Estimate Line Breaks (Page, Heading, etc.)")
    client.create_inventory_part(name="---Front Configuration---", category_id="category-1")

    assert calls[0][0:2] == ("POST", "https://api.shopmonkey.cloud/v3/inventory_category")
    assert calls[0][2]["json"] == {"name": "Estimate Line Breaks (Page, Heading, etc.)"}
    assert calls[1][0:2] == ("POST", "https://api.shopmonkey.cloud/v3/inventory_part")
    assert calls[1][2]["json"] == {
        "name": "---Front Configuration---",
        "categoryId": "category-1",
    }


def test_inventory_part_search_can_be_scoped_to_one_category(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response({"success": True, "data": [], "meta": {"hasMore": False}})

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    client = api_client.ShopmonkeyApiClient(api_key="secret-token")

    assert client.search_inventory_parts(category_id="category-1") == []
    assert calls[0][2]["json"] == {
        "limit": 100,
        "skip": 0,
        "where": {"categoryId": "category-1"},
    }


def test_estimate_line_break_setup_is_minimal_and_idempotent(store):
    store.data = {"api_key": "key"}

    first = service.ensure_estimate_line_breaks()
    second = service.ensure_estimate_line_breaks()

    assert first["ok"] is True
    assert first["category"] == {
        "id": "category-1",
        "name": "Estimate Line Breaks (Page, Heading, etc.)",
        "created": True,
    }
    assert len(first["created"]) == 7
    assert first["existing"] == []
    assert first["total"] == 7
    assert second["category"]["created"] is False
    assert second["created"] == []
    assert len(second["existing"]) == 7
    assert len(_FakeClient.created_categories) == 1
    assert len(_FakeClient.created_parts) == 7
    assert all(set(row) == {"id", "name", "categoryId"} for row in _FakeClient.created_parts)
    assert _FakeClient.created_parts[0]["name"] == (
        "-----------------------------------Front Configuration-----------------------------------"
    )


def test_inventory_snapshot_is_recoverable_and_excludes_customer_data(tmp_path, store):
    store.data = {"api_key": "key"}
    _FakeClient.inventory_categories = [{"id": "cat-1", "name": "Lighting", "deleted": False}]
    _FakeClient.inventory_parts = [{
        "id": "part-1",
        "name": "Warning light",
        "sku": "WL-1",
        "number": "WL-1",
        "categoryId": "cat-1",
        "quantity": 2,
        "wholesaleCostCents": 1000,
        "retailCostCents": 1500,
        "photo": True,
        "brand": {"id": "brand-1", "name": "Example"},
    }]
    _FakeClient.inventory_tires = [{
        "id": "tire-1",
        "name": "All season",
        "sku": "T-1",
        "quantity": 4,
        "retailCostCents": 20000,
        "photo": False,
    }]

    result = service.create_inventory_snapshot(AppPaths(workspace_dir=tmp_path))

    assert result["ok"] is True
    assert result["summary"] == {
        "parts": 1,
        "tires": 1,
        "categories": 1,
        "total_items": 2,
        "quantity": 6.0,
        "retail_value_cents": 83000,
        "missing_sku": 0,
        "missing_part_number": 1,
        "missing_price": 0,
        "missing_photo": 1,
        "missing_brand": 1,
        "missing_category": 1,
        "negative_quantity": 0,
        "zero_quantity": 0,
        "duplicate_name_groups": 0,
    }
    assert result["reset_preview"] == {
        "soft_delete_parts": 1,
        "soft_delete_tires": 1,
        "soft_delete_categories": 1,
        "enabled": False,
        "blocked_reason": "Stage and approve replacement price lists before enabling deletion.",
    }
    snapshot_path = tmp_path / "shopmonkey_inventory_snapshots" / result["snapshot_file"].split("/")[-1]
    document = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert document["inventory_parts"][0]["sku"] == "WL-1"
    assert document["inventory_tires"][0]["sku"] == "T-1"
    assert document["scope"]["customers"] is False
    assert "customers" not in document
    assert len(document["sha256"]) == 64


def test_shopmonkey_credentials_are_admin_only_but_cleanup_is_general_settings():
    assert required_capabilities("POST", "/api/shopmonkey/connect") == frozenset({
        Capability.SETTINGS_ADVANCED_MANAGE,
    })
    assert required_capabilities("GET", "/api/shopmonkey/cleanup") == frozenset({
        Capability.SETTINGS_GENERAL_MANAGE,
    })
    assert required_capabilities("POST", "/api/shopmonkey/inventory/snapshot") == frozenset({
        Capability.SETTINGS_ADVANCED_MANAGE,
    })
    assert required_capabilities(
        "POST", "/api/shopmonkey/inventory/estimate-line-breaks"
    ) == frozenset({Capability.SETTINGS_ADVANCED_MANAGE})
    assert required_capabilities(
        "POST", "/api/shopmonkey/pricing/save"
    ) == frozenset({Capability.SETTINGS_ADVANCED_MANAGE})
    assert required_capabilities("GET", "/api/shopmonkey/pricing") == frozenset({
        Capability.SETTINGS_GENERAL_MANAGE,
    })
    assert required_capabilities(
        "GET", "/api/shopmonkey/pricing/references"
    ) == frozenset({Capability.SETTINGS_GENERAL_MANAGE})
