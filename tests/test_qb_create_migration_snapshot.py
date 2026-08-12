from __future__ import annotations

import json

from tools.qb_create_migration_snapshot import create_snapshot


def test_snapshot_copies_only_non_secret_catalog_inputs(tmp_path):
    parts_db = tmp_path / "config" / "parts_db.json"
    parts_db.parent.mkdir()
    parts_db.write_text(
        json.dumps(
            {
                "products": {
                    "light": {
                        "part_numbers": [
                            {"part_number": "A-1", "qb_item_id": "42"},
                            {"part_number": "PENDING", "qb_pending": True},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    cache = tmp_path / "quickbooks_items_cache.json"
    cache.write_text(
        json.dumps({"last_sync_utc": "2026-08-10T00:00:00Z", "items": [{"qb_item_id": "42"}]}),
        encoding="utf-8",
    )
    # This is deliberately present beside the source data. The snapshot API
    # has no parameter that would let it copy metadata or OAuth credentials.
    (tmp_path / "quickbooks_config.json").write_text('{"client_id":"not-a-secret"}', encoding="utf-8")

    snapshot = create_snapshot(
        parts_db=parts_db,
        items_cache=cache,
        output_root=tmp_path / "snapshots",
        label="Pre Production Mapping",
    )

    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["snapshot_type"] == "quickbooks_production_mapping_baseline"
    assert manifest["catalog"] == {
        "products": 1,
        "part_numbers": 2,
        "linked_part_numbers": 1,
        "pending_part_numbers": 1,
    }
    assert manifest["sandbox_items_cache"] == {"items": 1, "last_sync_utc": "2026-08-10T00:00:00Z"}
    assert (snapshot / "parts_db.json").is_file()
    assert (snapshot / "sandbox_quickbooks_items_cache.json").is_file()
    assert not (snapshot / "quickbooks_config.json").exists()
    assert manifest["safety"]["contains_credentials"] is False
