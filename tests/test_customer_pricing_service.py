from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from dtm_buildsheet.app.services import customer_pricing_service as pricing
from dtm_buildsheet.app.services import parts_db_service
from dtm_buildsheet.paths import AppPaths


@pytest.fixture
def paths(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "parts_db.json").write_text(json.dumps({
        "schema_version": 2,
        "manufacturers": {
            "havis": {"label": "Havis"},
            "whelen": {"label": "Whelen"},
        },
        "products": {},
    }), "utf-8")
    parts_db_service.reset_for_testing()
    yield AppPaths(workspace_dir=tmp_path, workspace_config_dir=config)
    parts_db_service.reset_for_testing()


def test_default_rule_prices_linked_items_and_leaves_pending_lines_alone(paths):
    lines = [
        {"name": "Light", "manufacturer": "Whelen", "manufacturer_id": "whelen",
         "qb_item_id": "1", "unit_price": 10.05, "qty": 2},
        {"name": "Pending", "manufacturer": "Whelen", "manufacturer_id": "whelen",
         "qb_item_id": "", "unit_price": 50, "qty": 1, "pending": True},
    ]

    priced, summary = pricing.apply_customer_pricing(paths, lines)

    assert priced[0]["list_unit_price"] == 10.05
    assert priced[0]["unit_price"] == 6.23
    assert priced[0]["amount"] == 12.46
    assert priced[1]["unit_price"] == 50.0
    assert summary["list_total"] == 70.1
    assert summary["customer_total"] == 62.46
    assert summary["savings"] == 7.64


def test_agency_override_changes_only_named_manufacturer(paths):
    agency = SimpleNamespace(pricing_overrides={"whelen": 10})
    lines = [
        {"name": "Light", "manufacturer": "Whelen", "manufacturer_id": "whelen",
         "qb_item_id": "1", "unit_price": 100, "qty": 1},
        {"name": "Console", "manufacturer": "Havis", "manufacturer_id": "havis",
         "qb_item_id": "2", "unit_price": 100, "qty": 1},
    ]

    priced, summary = pricing.apply_customer_pricing(
        paths, lines, agency, pricing_mode="custom"
    )

    assert [line["unit_price"] for line in priced] == [90.0, 80.0]
    assert summary["source"] == "custom"
    assert {row["manufacturer_id"]: row["override"] for row in summary["applied_discounts"]} == {
        "havis": False,
        "whelen": True,
    }


def test_retail_mode_ignores_saved_agency_custom_defaults(paths):
    agency = SimpleNamespace(pricing_overrides={"whelen": 10})
    lines = [{"name": "Light", "manufacturer": "Whelen", "manufacturer_id": "whelen",
              "qb_item_id": "1", "unit_price": 100, "qty": 1}]

    priced, summary = pricing.apply_customer_pricing(paths, lines, agency)

    assert priced[0]["unit_price"] == 62.0
    assert summary["source"] == "retail"
    whelen = next(row for row in summary["editable_discounts"] if row["manufacturer_id"] == "whelen")
    assert whelen["custom_discount_percent"] == 10.0


def test_save_default_rule_uses_validated_parts_db_path(paths, monkeypatch):
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.shared_work_service.save_setting_to_cloud_in_background",
        lambda *args, **kwargs: None,
    )
    result = pricing.save_default_rule(paths, {
        "rule_name": "Retail",
        "manufacturer_discounts": {"havis": 25, "whelen": 35},
    })

    assert result["ok"] is True
    saved = json.loads((paths.workspace_config_dir / "parts_db.json").read_text("utf-8"))
    assert saved["customer_pricing"]["default_rule"]["manufacturer_discounts"] == {
        "havis": 25.0,
        "whelen": 35.0,
    }
    assert pricing.get_default_rule(paths)["discounts"] == [
        {"manufacturer_id": "havis", "manufacturer": "Havis", "discount_percent": 25.0},
        {"manufacturer_id": "whelen", "manufacturer": "Whelen", "discount_percent": 35.0},
    ]


def test_save_default_rule_rejects_unknown_manufacturer(paths):
    result = pricing.save_default_rule(paths, {
        "rule_name": "Default",
        "manufacturer_discounts": {"missing": 10},
    })
    assert result == {"ok": False, "error": "Unknown manufacturer: missing"}
