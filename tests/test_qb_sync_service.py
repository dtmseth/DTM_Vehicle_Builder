"""Phase 2 (Slice A) tests for the QuickBooks parts-sync read path.

Hermetic: the QBO Data API client and the connection service are replaced
with in-process fakes, so these never touch the network or the keychain.

The load-bearing assertion is that a sync NEVER writes parts_db.json — it
only reads it (to flag already-linked items) and writes the git-ignored
items cache.
"""

from __future__ import annotations

import json

import pytest

from dtm_buildsheet.app.services import qb_sync_service as sync
from dtm_buildsheet.app.adapters.quickbooks.api_client import _normalize_item
from dtm_buildsheet.paths import AppPaths


_FAKE_ITEMS = [
    {"qb_item_id": "1", "name": "Whelen Liberty II", "sku": "WL-LIB2", "description": "",
     "unit_price": 1249.0, "type": "Inventory"},
    {"qb_item_id": "2", "name": "Setina PB400", "sku": "PB400", "description": "",
     "unit_price": 599.5, "type": "Inventory"},
    {"qb_item_id": "3", "name": "Labor", "sku": "", "description": "", "unit_price": 95.0,
     "type": "Service"},
]


class _FakeApiClient:
    def __init__(self, *, access_token, realm_id, environment="production"):
        self.access_token = access_token
        self.realm_id = realm_id
        self.environment = environment

    def fetch_active_items(self, *, page_size: int = 1000):
        return [dict(it) for it in _FAKE_ITEMS]


@pytest.fixture
def paths(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return AppPaths(workspace_dir=tmp_path, workspace_config_dir=config_dir)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setattr(sync, "QuickBooksApiClient", _FakeApiClient)
    monkeypatch.setattr(sync.quickbooks_service, "ensure_access_token", lambda paths: "ACCESS")
    monkeypatch.setattr(sync.quickbooks_service, "get_realm_id", lambda paths: "REALM1")
    monkeypatch.setattr(sync.quickbooks_service, "get_status", lambda paths: {"environment": "sandbox"})
    # set_last_sync writes the real config file; allow it (tmp workspace).


def _write_parts_db(paths, products: dict) -> str:
    db = {"schema_version": 2, "products": products}
    text = json.dumps(db, indent=2)
    (paths.workspace_config_dir / "parts_db.json").write_text(text, encoding="utf-8")
    return text


def test_sync_pulls_items_into_cache(paths):
    res = sync.sync_items(paths)
    assert res["ok"] is True
    assert res["item_count"] == 3
    cache = json.loads((paths.workspace_dir / "quickbooks_items_cache.json").read_text())
    assert cache["item_count"] == 3
    assert {i["qb_item_id"] for i in cache["items"]} == {"1", "2", "3"}


def test_sync_never_writes_parts_db(paths):
    before = _write_parts_db(paths, {"setina_pb400": {"model": "PB400"}})
    sync.sync_items(paths)
    after = (paths.workspace_config_dir / "parts_db.json").read_text()
    assert before == after  # byte-for-byte untouched


def test_sync_flags_linked_items(paths):
    # One product already carries qb_item_id "2" → that item is "linked".
    _write_parts_db(paths, {"setina_pb400": {"model": "PB400", "qb_item_id": "2"}})
    res = sync.sync_items(paths)
    assert res["linked"] == 1
    assert res["unlinked"] == 2
    cache = json.loads((paths.workspace_dir / "quickbooks_items_cache.json").read_text())
    linked = {i["qb_item_id"]: i["linked"] for i in cache["items"]}
    assert linked == {"1": False, "2": True, "3": False}


def test_sync_with_no_parts_db_treats_all_unlinked(paths):
    res = sync.sync_items(paths)
    assert res["linked"] == 0
    assert res["unlinked"] == 3


def test_get_cached_items_without_sync_is_empty(paths):
    res = sync.get_cached_items(paths)
    assert res["ok"] is True
    assert res["item_count"] == 0
    assert res["items"] == []
    assert res["last_sync_utc"] is None


def test_sync_not_connected_returns_error(paths, monkeypatch):
    from dtm_buildsheet.app.adapters.quickbooks.oauth_client import QuickBooksOAuthError

    def _boom(paths):
        raise QuickBooksOAuthError("not_connected")

    monkeypatch.setattr(sync.quickbooks_service, "ensure_access_token", _boom)
    res = sync.sync_items(paths)
    assert res["ok"] is False
    assert res["error"] == "not_connected"


def test_sync_no_realm_returns_error(paths, monkeypatch):
    monkeypatch.setattr(sync.quickbooks_service, "get_realm_id", lambda paths: "")
    res = sync.sync_items(paths)
    assert res["ok"] is False
    assert res["error"] == "no_realm_id"


# ── api_client normalization (pure, no network) ──────────────────────────────


def test_normalize_item_coerces_fields():
    raw = {"Id": 42, "Name": " Light Bar ", "Sku": " LB-1 ", "Description": "x",
           "UnitPrice": "1249.00", "Type": "Inventory", "Active": True}
    norm = _normalize_item(raw)
    assert norm == {
        "qb_item_id": "42",
        "name": "Light Bar",
        "sku": "LB-1",
        "description": "x",
        "unit_price": 1249.0,
        "type": "Inventory",
    }


def test_normalize_item_handles_missing_price():
    norm = _normalize_item({"Id": "7", "Name": "Svc"})
    assert norm["unit_price"] is None
    assert norm["sku"] == ""
