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
    inactive_items: list[dict] = []

    def __init__(self, *, access_token, realm_id, environment="production"):
        assert access_token == "ACCESS"
        assert realm_id == "PRODUCTION-REALM"
        assert environment == "production"

    def fetch_active_items(self):
        return [dict(item) for item in self.items]

    def fetch_inactive_items(self):
        return [dict(item) for item in self.inactive_items]


@pytest.fixture
def paths(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return AppPaths(workspace_dir=tmp_path, workspace_config_dir=config_dir)


@pytest.fixture(autouse=True)
def _preview_connection(monkeypatch):
    _FakeApiClient.items = []
    _FakeApiClient.inactive_items = []
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


def test_create_baseline_snapshot_uses_current_catalog_and_selects_it(paths):
    parts = {
        "products": {
            "linked": {"part_numbers": [{"part_number": "A-1", "qb_item_id": "sandbox-1"}]},
            "pending": {"part_numbers": [{"part_number": "B-2", "qb_pending": True}]},
        }
    }
    source = paths.workspace_config_dir / "parts_db.json"
    source.write_text(json.dumps(parts), encoding="utf-8")
    (paths.workspace_dir / "quickbooks_config.json").write_text(
        json.dumps({"environment": "sandbox", "client_id": "NON-SECRET-ID"}), encoding="utf-8"
    )
    (paths.workspace_dir / "quickbooks_items_cache.json").write_text(
        json.dumps({"items": [{"qb_item_id": "1", "name": "A-1"}], "last_sync_utc": "now"}),
        encoding="utf-8",
    )
    (paths.workspace_dir / "quickbooks_production_preview_config.json").write_text(
        json.dumps({"client_id": "DO-NOT-COPY"}), encoding="utf-8"
    )
    stale_report = paths.workspace_dir / "quickbooks_production_mapping_report.json"
    stale_plan = paths.workspace_dir / "quickbooks_production_mapping_plan.json"
    stale_report.write_text('{"snapshot": "old"}', encoding="utf-8")
    stale_plan.write_text('{"snapshot": "old"}', encoding="utf-8")

    result = preview.create_baseline_snapshot(paths, "After Cleanup #1")

    assert result["ok"] is True
    assert result["snapshot_name"].endswith("-after-cleanup-1")
    directory = paths.workspace_dir / "quickbooks_migration_snapshots" / result["snapshot_name"]
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["catalog"] == {
        "products": 2,
        "part_numbers": 2,
        "linked_part_numbers": 1,
        "pending_part_numbers": 1,
    }
    assert manifest["sandbox_items_cache"]["items"] == 1
    assert json.loads((directory / "parts_db.json").read_text()) == parts
    assert not (directory / "quickbooks_production_preview_config.json").exists()
    assert not stale_report.exists()
    assert not stale_plan.exists()
    assert preview.get_status(paths)["selected_snapshot"]["name"] == result["snapshot_name"]


def test_create_baseline_snapshot_rejects_invalid_catalog(paths):
    (paths.workspace_config_dir / "parts_db.json").write_text('{"not_products": true}', encoding="utf-8")

    assert preview.create_baseline_snapshot(paths) == {"ok": False, "error": "invalid_parts_db"}


def test_historical_plan_handles_production_format_differences(paths):
    _create_snapshot(
        paths,
        products={
            "raw_one": {"part_numbers": [{"part_number": "SC-931-1", "qb_item_id": "s1"}]},
            "raw_two": {"part_numbers": [{"part_number": "SC-9311", "qb_item_id": "s2"}]},
            "shared_one": {"part_numbers": [{"part_number": "TCRLBKT", "qb_item_id": "s3"}]},
            "shared_two": {"part_numbers": [{"part_number": "TCRLBKT", "qb_item_id": "s3"}]},
            "renamed": {"part_numbers": [{"part_number": "K5011", "qb_item_id": "s4"}]},
            "bad_name": {"part_numbers": [{"part_number": "c", "qb_item_id": "s5"}]},
            "inactive": {"part_numbers": [{"part_number": "OLD-1", "qb_item_id": "s6"}]},
        },
        sandbox_items=[
            {"qb_item_id": "s1", "name": "SC-931-1", "description": "ONE", "unit_price": 1, "type": "NonInventory"},
            {"qb_item_id": "s2", "name": "SC-9311", "description": "TWO", "unit_price": 2, "type": "NonInventory"},
            {"qb_item_id": "s3", "name": "TCRLBKT", "description": "BRACKET", "unit_price": 3, "type": "NonInventory"},
            {"qb_item_id": "s4", "name": "K5011", "description": "AXE HANGER", "unit_price": 4, "type": "NonInventory"},
            {"qb_item_id": "s5", "name": "c", "description": "REAL PRODUCT", "unit_price": 5, "type": "NonInventory"},
            {"qb_item_id": "s6", "name": "OLD-1", "description": "OLD PRODUCT", "unit_price": 6, "type": "NonInventory"},
        ],
    )
    _FakeApiClient.items = [
        {"qb_item_id": "p1", "name": "SC-931-1", "sku": "", "description": "ONE", "unit_price": 1, "type": "NonInventory"},
        {"qb_item_id": "p2", "name": "SC-9311", "sku": "", "description": "TWO", "unit_price": 2, "type": "NonInventory"},
        {"qb_item_id": "p3", "name": "TCRLBKT", "sku": "", "description": "BRACKET", "unit_price": 3, "type": "NonInventory"},
        {"qb_item_id": "p4", "name": "K5011-B", "sku": "", "description": "AXE HANGER - BLACK STRAPS", "unit_price": 4.5, "type": "NonInventory"},
        {"qb_item_id": "p5", "name": "REAL-5", "sku": "", "description": "REAL\nPRODUCT", "unit_price": 5, "type": "NonInventory"},
    ]
    _FakeApiClient.inactive_items = [
        {"qb_item_id": "p6", "name": "OLD-1 (deleted)", "sku": "", "description": "OLD PRODUCT", "unit_price": 7, "type": "NonInventory"},
    ]

    assert preview.pull_production_catalog(paths)["ok"] is True
    report = preview.set_mapping_field(paths, "name")["report"]
    summary = report["historical_link_summary"]
    assert summary == {
        "previously_linked_rows": 7,
        "matched_rows": 7,
        "unmatched_rows": 0,
        "unique_sandbox_items": 6,
        "unique_production_items": 6,
        "shared_link_rows": 1,
        "active_matches": 6,
        "inactive_matches": 1,
        "blank_sku_matches": 7,
        "type_change_count": 0,
        "match_basis": {
            "exact_name": 4,
            "historical_deleted_name": 1,
            "name_variant_description_prefix": 1,
            "exact_description": 1,
        },
    }
    plan = json.loads((paths.workspace_dir / "quickbooks_production_historical_link_plan.json").read_text())
    assert plan["application_status"] == "locked_not_applied"
    assert plan["activation_requirements"]["sandbox_background_polling_must_be_stopped"] is True
    assert all(row["confidence"] == "high" for row in plan["matches"])
    inactive = next(row for row in plan["matches"] if row["builder"]["part_number"] == "OLD-1")
    assert inactive["planned_qb_fields"]["qb_inactive"] is True
    renamed = next(row for row in plan["matches"] if row["builder"]["part_number"] == "K5011")
    assert renamed["planned_qb_fields"]["qb_item_id"] == "p4"


def test_apply_historical_plan_replaces_only_qb_owned_fields():
    document = {
        "products": {
            "p1": {
                "model": "Owner model",
                "tag_ids": ["keep-me"],
                "part_numbers": [{
                    "part_number": "K5011",
                    "color": "black",
                    "qb_item_id": "sandbox-1",
                    "qb_sku": "K5011",
                    "qb_unit_price": 100,
                }],
            },
        },
    }
    plan = {
        "application_status": "locked_not_applied",
        "summary": {"previously_linked_rows": 1, "matched_rows": 1, "unmatched_rows": 0},
        "matches": [{
            "confidence": "high",
            "builder": {
                "product_id": "p1",
                "part_number": "K5011",
                "baseline_qb_item_id": "sandbox-1",
            },
            "planned_qb_fields": {
                "qb_item_id": "production-1",
                "qb_sku": "",
                "qb_sales_description": "Production description",
                "qb_unit_price": 124.5,
                "qb_inactive": False,
            },
        }],
    }

    updated, stats = preview._apply_historical_plan_to_document(
        document, plan, applied_utc="2026-08-11T17:00:00Z"
    )

    assert stats == {"updated_rows": 1, "inactive_rows": 0}
    assert document["products"]["p1"]["part_numbers"][0]["qb_item_id"] == "sandbox-1"
    product = updated["products"]["p1"]
    assert product["model"] == "Owner model"
    assert product["tag_ids"] == ["keep-me"]
    assert product["part_numbers"][0] == {
        "part_number": "K5011",
        "color": "black",
        "qb_item_id": "production-1",
        "qb_sku": "",
        "qb_sales_description": "Production description",
        "qb_unit_price": 124.5,
        "qb_inactive": False,
        "qb_last_synced": "2026-08-11T17:00:00Z",
    }


def test_apply_historical_plan_refuses_changed_baseline_row():
    document = {
        "products": {
            "p1": {"part_numbers": [{"part_number": "K5011", "qb_item_id": "changed"}]},
        },
    }
    plan = {
        "application_status": "locked_not_applied",
        "summary": {"previously_linked_rows": 1, "matched_rows": 1, "unmatched_rows": 0},
        "matches": [{
            "confidence": "high",
            "builder": {
                "product_id": "p1",
                "part_number": "K5011",
                "baseline_qb_item_id": "sandbox-1",
            },
            "planned_qb_fields": {"qb_item_id": "production-1"},
        }],
    }

    with pytest.raises(ValueError, match="activation_baseline_row_changed"):
        preview._apply_historical_plan_to_document(
            document, plan, applied_utc="2026-08-11T17:00:00Z"
        )
