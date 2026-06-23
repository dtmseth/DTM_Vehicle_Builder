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


# ── linking (Slice B) ────────────────────────────────────────────────────────


class _FakePartsDbService:
    """Minimal stand-in for PartsDbService backing link/unlink."""

    def __init__(self, doc):
        self._doc = doc
        self.invalidated = False

    def raw_doc(self):
        return self._doc

    def invalidate(self):
        self.invalidated = True


@pytest.fixture
def _link_fakes(paths, monkeypatch):
    """Wire link/unlink to an in-memory parts_db + a capturing save."""
    doc = {"schema_version": 2, "products": {
        "setina_pb400": {"model": "PB400", "manufacturer_id": "setina"},
        "whelen_lib2": {"model": "Liberty II", "manufacturer_id": "whelen"},
    }}
    fake_svc = _FakePartsDbService(doc)
    saved = {}

    def _fake_save(filename, data, p):
        saved["filename"] = filename
        saved["data"] = data
        # Mirror the real pipeline: persisted doc becomes what the next
        # raw_doc() returns (production reloads from disk after invalidate()).
        fake_svc._doc = data
        # _linked_map reads parts_db.json straight off disk, so persist there too
        # (production's save_config_file writes the file).
        if filename == "parts_db.json":
            (paths.workspace_config_dir / filename).write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        return {"ok": True}

    import dtm_buildsheet.app.services.config_service as cfg
    import dtm_buildsheet.app.services.parts_db_service as pdb
    monkeypatch.setattr(cfg, "save_config_file", _fake_save)
    monkeypatch.setattr(pdb, "get_parts_db_service", lambda p: fake_svc)
    # Seed a cache so link_item can find the item's sku/price.
    sync.sync_items(paths)
    return {"doc": doc, "svc": fake_svc, "saved": saved}


def test_link_item_writes_qb_fields_via_save_pipeline(paths, _link_fakes):
    res = sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    assert res["ok"] is True
    # Saved through the config pipeline (not a raw write), full doc, right file.
    assert _link_fakes["saved"]["filename"] == "parts_db.json"
    product = _link_fakes["saved"]["data"]["products"]["whelen_lib2"]
    assert product["qb_item_id"] == "1"
    assert product["qb_sku"] == "WL-LIB2"
    assert product["qb_unit_price"] == 1249.0
    assert "qb_last_synced" in product
    assert _link_fakes["svc"].invalidated is True


def test_link_item_rejects_double_linked_item(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    # Same QB item to a second product → rejected (one-to-one).
    res = sync.link_item(paths, qb_item_id="1", product_id="setina_pb400")
    assert res["ok"] is False
    assert res["error"] == "item_already_linked"


def test_link_item_rejects_product_with_other_link(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    res = sync.link_item(paths, qb_item_id="2", product_id="whelen_lib2")
    assert res["ok"] is False
    assert res["error"] == "product_already_linked"


def test_link_item_unknown_product(paths, _link_fakes):
    res = sync.link_item(paths, qb_item_id="1", product_id="nope")
    assert res["ok"] is False
    assert res["error"] == "unknown_product"


def test_unlink_item_removes_qb_fields(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    res = sync.unlink_item(paths, qb_item_id="1")
    assert res["ok"] is True
    assert res["product_id"] == "whelen_lib2"
    product = _link_fakes["saved"]["data"]["products"]["whelen_lib2"]
    assert "qb_item_id" not in product
    assert "qb_sku" not in product


def test_link_then_cache_reflects_link(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    cached = sync.get_cached_items(paths)
    by_id = {i["qb_item_id"]: i for i in cached["items"]}
    assert by_id["1"]["linked"] is True
    assert by_id["1"]["linked_product_id"] == "whelen_lib2"


# ── reconciliation (Slice C) ─────────────────────────────────────────────────


def test_reconcile_updates_linked_part_price_and_sku(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    # The linked product now carries qb_unit_price 1249.0 (from link). Simulate
    # QBO raising the price by rewriting the cache, then reconcile.
    cache = sync._read_cache(paths)
    for it in cache["items"]:
        if it["qb_item_id"] == "1":
            it["unit_price"] = 1399.0
            it["sku"] = "WL-LIB2-NEW"
    sync._write_cache(paths, cache)

    res = sync.reconcile_linked_parts(paths)
    assert res["ok"] is True
    assert res["updated"] == 1
    product = _link_fakes["saved"]["data"]["products"]["whelen_lib2"]
    assert product["qb_unit_price"] == 1399.0
    assert product["qb_sku"] == "WL-LIB2-NEW"


def test_reconcile_flags_missing_item_inactive(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    # Item "1" disappears from the active pull.
    cache = sync._read_cache(paths)
    cache["items"] = [it for it in cache["items"] if it["qb_item_id"] != "1"]
    sync._write_cache(paths, cache)

    res = sync.reconcile_linked_parts(paths)
    assert res["flagged_inactive"] == 1
    product = _link_fakes["saved"]["data"]["products"]["whelen_lib2"]
    assert product["qb_inactive"] is True


def test_reconcile_reactivates_returning_item(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    # Flag inactive first.
    cache = sync._read_cache(paths)
    saved_items = list(cache["items"])
    cache["items"] = [it for it in cache["items"] if it["qb_item_id"] != "1"]
    sync._write_cache(paths, cache)
    sync.reconcile_linked_parts(paths)
    assert _link_fakes["saved"]["data"]["products"]["whelen_lib2"]["qb_inactive"] is True
    # Item returns to the active set.
    cache["items"] = saved_items
    sync._write_cache(paths, cache)
    res = sync.reconcile_linked_parts(paths)
    assert res["reactivated"] == 1
    assert _link_fakes["saved"]["data"]["products"]["whelen_lib2"]["qb_inactive"] is False


def test_reconcile_links_pending_part_when_sku_appears(paths, _link_fakes):
    # A product carries a pre-added pending-QB part (no qb_item_id yet).
    prod = _link_fakes["svc"].raw_doc()["products"]["whelen_lib2"]
    prod["part_numbers"] = [{
        "part_number": "TCRWXPJC", "qb_pending": True, "price_usd": 116.0,
        "qb_item_id": "", "color": "red", "secondary_color": "blue", "tertiary_color": "white",
    }]

    # Not in QBO yet → nothing reconciled.
    res = sync.reconcile_linked_parts(paths)
    assert res["reconciled_pending"] == 0

    # The QB user creates the item; it appears in the next pull.
    cache = sync._read_cache(paths)
    cache["items"].append({"qb_item_id": "99", "name": "TCRWXPJC", "sku": "TCRWXPJC",
                           "description": "", "unit_price": 116.0, "type": "Inventory"})
    sync._write_cache(paths, cache)

    res = sync.reconcile_linked_parts(paths)
    assert res["reconciled_pending"] == 1
    pn = _link_fakes["saved"]["data"]["products"]["whelen_lib2"]["part_numbers"][0]
    assert pn["qb_item_id"] == "99"
    assert pn["qb_pending"] is False
    assert pn["qb_unit_price"] == 116.0
    assert pn["qb_sku"] == "TCRWXPJC"


def test_reconcile_never_touches_unlinked_parts(paths, _link_fakes):
    # No links at all → reconcile writes nothing.
    res = sync.reconcile_linked_parts(paths)
    assert res["updated"] == 0
    assert res["flagged_inactive"] == 0
    assert "filename" not in _link_fakes["saved"]  # save_config_file never called


def test_reconcile_skips_when_never_synced(paths, monkeypatch):
    # Empty cache (no last_sync_utc) must not flag everything inactive.
    res = sync.reconcile_linked_parts(paths)
    assert res.get("skipped") == "no_sync"


def test_reconcile_idempotent_no_double_write(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    # First reconcile applies price/sku from the cached item.
    sync.reconcile_linked_parts(paths)
    _link_fakes["saved"].clear()
    # Second reconcile with no further change → no save.
    res = sync.reconcile_linked_parts(paths)
    assert res["updated"] == 0
    assert "filename" not in _link_fakes["saved"]


def test_run_full_sync_pulls_then_reconciles(paths, _link_fakes):
    sync.link_item(paths, qb_item_id="1", product_id="whelen_lib2")
    res = sync.run_full_sync(paths)
    assert res["ok"] is True
    assert res["item_count"] == 3
    assert "reconciled" in res
    assert res["reconciled"]["ok"] is True
