"""Production QuickBooks catalog comparison tests.

These tests use a temporary snapshot plus fake Intuit reads.  They never use a
real keychain, never contact QuickBooks, and assert that the comparison has no
path to change the Builder catalog.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from dtm_buildsheet.app.services import qb_production_preview_service as preview
from dtm_buildsheet.paths import AppPaths


class _FakeApiClient:
    items: list[dict] = []

    def __init__(self, *, access_token, realm_id, environment="production"):
        assert access_token == "ACCESS"
        assert realm_id == "PRODUCTION-REALM"
        assert environment == "production"

    def fetch_active_items(self):
        return [dict(item) for item in self.items]


@pytest.fixture
def paths(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return AppPaths(workspace_dir=tmp_path, workspace_config_dir=config_dir)


@pytest.fixture(autouse=True)
def _preview_connection(monkeypatch):
    monkeypatch.setattr(preview, "QuickBooksApiClient", _FakeApiClient)
    monkeypatch.setattr(
        preview.quickbooks_service,
        "get_status",
        lambda paths, *, profile: {"environment": "production", "connected": True},
    )
    monkeypatch.setattr(
        preview.quickbooks_service,
        "ensure_access_token",
        lambda paths, *, profile: "ACCESS",
    )
    monkeypatch.setattr(
        preview.quickbooks_service,
        "get_realm_id",
        lambda paths, *, profile: "PRODUCTION-REALM",
    )


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_snapshot(paths, *, products, sandbox_items):
    directory = paths.workspace_dir / "quickbooks_migration_snapshots" / "baseline"
    directory.mkdir(parents=True)
    parts_path = directory / "parts_db.json"
    parts_path.write_text(json.dumps({"products": products, "manufacturers": {}}), encoding="utf-8")
    cache_path = directory / "sandbox_quickbooks_items_cache.json"
    cache_path.write_text(json.dumps({"items": sandbox_items}), encoding="utf-8")
    manifest = {
        "snapshot_type": "quickbooks_production_mapping_baseline",
        "created_utc": "2026-08-10T00:00:00Z",
        "catalog": {"products": len(products)},
        "sandbox_items_cache": {"items": len(sandbox_items)},
        "files": {
            "parts_db": {"file": "parts_db.json", "sha256": _sha(parts_path)},
            "sandbox_items_cache": {
                "file": "sandbox_quickbooks_items_cache.json",
                "sha256": _sha(cache_path),
            },
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert preview.select_snapshot(paths, "baseline")["ok"] is True


def test_preview_compares_columns_without_touching_catalog(paths):
    original_catalog = {"products": {"live": {"part_numbers": [{"part_number": "DO-NOT-TOUCH"}]}}}
    source = paths.workspace_config_dir / "parts_db.json"
    source.write_text(json.dumps(original_catalog), encoding="utf-8")

    _create_snapshot(
        paths,
        products={
            "whelen": {"model": "Warning", "part_numbers": [{"part_number": "WL-ONE"}]},
            "setina": {"model": "Bumper", "part_numbers": [{"part_number": "SET-2"}]},
        },
        sandbox_items=[{"qb_item_id": "ignored", "name": "TRAILER-1", "sku": ""}],
    )
    _FakeApiClient.items = [
        {"qb_item_id": "1", "name": "WL-ONE", "sku": "inventory-1", "description": "", "unit_price": 1, "type": "Inventory"},
        {"qb_item_id": "2", "name": "TRAILER-1", "sku": "inventory-2", "description": "", "unit_price": 1, "type": "Inventory"},
    ]

    pulled = preview.pull_production_catalog(paths)
    assert pulled["ok"] is True
    assert pulled["production_sync_enabled"] is False
    report = preview.set_mapping_field(paths, "name")["report"]

    assert report["field_analysis"]["name"]["catalog_exact"] == 1
    assert report["field_analysis"]["name"]["catalog_missing"] == 1
    assert report["field_analysis"]["name"]["intentionally_excluded"] == 1
    assert report["field_analysis"]["sku"]["catalog_exact"] == 0
    assert source.read_text(encoding="utf-8") == json.dumps(original_catalog)
    assert not (paths.workspace_dir / "quickbooks_items_cache.json").exists()


def test_plan_prepares_all_exact_matches_and_never_applies_them(paths):
    _create_snapshot(
        paths,
        products={
            "one": {"model": "One", "part_numbers": [{"part_number": "A-1"}]},
            "two": {"model": "Two", "part_numbers": [{"part_number": "B-2"}]},
        },
        sandbox_items=[{"qb_item_id": "ignored", "name": "SHOP-SUPPLY", "sku": ""}],
    )
    _FakeApiClient.items = [
        {"qb_item_id": "1", "name": "A-1", "sku": "", "description": "", "unit_price": 1, "type": "Inventory"},
        {"qb_item_id": "2", "name": "B-2", "sku": "", "description": "", "unit_price": 1, "type": "Inventory"},
        {"qb_item_id": "3", "name": "SHOP-SUPPLY", "sku": "", "description": "", "unit_price": 1, "type": "Inventory"},
    ]

    assert preview.pull_production_catalog(paths)["ok"] is True
    selected = preview.set_mapping_field(paths, "name")["report"]
    assert selected["selected_blocker_count"] == 0

    prepared = preview.prepare_auto_mapping_plan(paths)
    assert prepared == {
        "ok": True,
        "preview_only": True,
        "production_sync_enabled": False,
        "exact_match_count": 2,
        "unresolved_exception_count": 0,
        "application_status": "prepared_not_applied",
    }
    plan = json.loads((paths.workspace_dir / "quickbooks_production_mapping_plan.json").read_text())
    assert plan["application_status"] == "prepared_not_applied"
    assert {row["production_item_id"] for row in plan["exact_matches"]} == {"1", "2"}


def test_preview_requires_snapshot_and_https_redirect(paths):
    assert preview.pull_production_catalog(paths)["error"] == "snapshot_required"
    _create_snapshot(paths, products={}, sandbox_items=[])
    result = preview.save_connection(
        paths,
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://localhost:7655/api/quickbooks/callback",
    )
    assert result == {"ok": False, "error": "production_redirect_must_be_https"}
    local_https = preview.save_connection(
        paths,
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="https://localhost/api/quickbooks/callback",
    )
    assert local_https == {"ok": False, "error": "production_redirect_must_be_https"}


def test_plan_keeps_exceptions_out_of_the_automatic_matches(paths):
    _create_snapshot(
        paths,
        products={
            "exact": {"model": "Exact", "part_numbers": [{"part_number": "A-1", "qb_item_id": "sandbox-1"}]},
            "missing": {"model": "Missing", "part_numbers": [{"part_number": "B-2"}]},
        },
        sandbox_items=[],
    )
    _FakeApiClient.items = [
        {"qb_item_id": "production-1", "name": "A-1", "sku": "", "description": "", "unit_price": 1, "type": "Inventory"},
    ]

    assert preview.pull_production_catalog(paths)["ok"] is True
    assert preview.set_mapping_field(paths, "name")["report"]["selected_blocker_count"] == 1
    prepared = preview.prepare_auto_mapping_plan(paths)
    assert prepared["exact_match_count"] == 1
    assert prepared["unresolved_exception_count"] == 1
    plan = json.loads((paths.workspace_dir / "quickbooks_production_mapping_plan.json").read_text())
    assert plan["exact_matches"][0]["builder"]["baseline_qb_item_id"] == "sandbox-1"
    assert plan["exact_matches"][0]["production_item_id"] == "production-1"


def test_snapshot_with_changed_exclusion_cache_is_not_usable(paths):
    _create_snapshot(paths, products={}, sandbox_items=[])
    cache = paths.workspace_dir / "quickbooks_migration_snapshots" / "baseline" / "sandbox_quickbooks_items_cache.json"
    cache.write_text('{"items":[{"name":"altered"}]}', encoding="utf-8")

    assert preview.list_snapshots(paths)["snapshots"] == []
    assert preview.select_snapshot(paths, "baseline") == {"ok": False, "error": "snapshot_not_found_or_invalid"}
