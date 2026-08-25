from __future__ import annotations

import json

from dtm_buildsheet.app.services import estimate_charges_service as charges
from dtm_buildsheet.app.services import qb_sync_service
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    return AppPaths(workspace_dir=tmp_path, workspace_config_dir=config)


def _write_settings(paths, *, labor=2000, supplies=450):
    (paths.workspace_config_dir / "estimate_charges.json").write_text(json.dumps({
        "schema_version": 1,
        "card_fee_percent": 4,
        "service_items": {
            "labor": "LABOR INSTALL",
            "install_supplies": "INSTALL SUPPLIES",
            "card_fee": "Convenience Fee",
            "delivery": "TRAVEL",
        },
        "presets": {
            "patrol": {
                "label": "Patrol", "aliases": ["patrol"],
                "labor_amount": labor, "install_supplies_amount": supplies,
            },
            "undercover": {
                "label": "Undercover", "aliases": ["undercover"],
                "labor_amount": 0, "install_supplies_amount": supplies,
            },
            "admin": {
                "label": "Admin", "aliases": ["admin"],
                "labor_amount": 0, "install_supplies_amount": supplies,
            },
            "custom": {
                "label": "Custom", "aliases": [],
                "labor_amount": 0, "install_supplies_amount": supplies,
            },
        },
    }), "utf-8")


def test_additional_charges_use_presets_and_compute_four_percent_without_fee_on_fee(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_settings(paths)
    item_ids = {
        "LABOR INSTALL": "7",
        "INSTALL SUPPLIES": "6",
        "Convenience Fee": "1073",
        "TRAVEL": "791",
    }
    monkeypatch.setattr(qb_sync_service, "find_cached_active_item_by_name", lambda _paths, name: {
        "qb_item_id": item_ids[name], "name": name, "sku": "",
    })

    result = charges.calculate_additional_charges(
        paths,
        build_type="Patrol SUV",
        material_lines=[{"amount": 1000}],
        overrides={"delivery_amount": 100},
    )

    assert result["problems"] == []
    assert result["preset_id"] == "patrol"
    assert result["card_fee_amount"] == 142
    assert result["additional_total"] == 2692
    assert result["estimate_total"] == 3692
    assert [line["estimate_charge_type"] for line in result["lines"]] == [
        "labor", "install_supplies", "delivery", "card_fee",
    ]
    assert [line["qb_item_id"] for line in result["lines"]] == ["7", "6", "791", "1073"]
    assert result["lines"][-1]["description"] == "4% credit card processing fee"


def test_additional_charges_require_amounts_and_exact_active_qb_items(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_settings(paths, labor=0, supplies=0)
    monkeypatch.setattr(qb_sync_service, "find_cached_active_item_by_name", lambda *_: None)

    result = charges.calculate_additional_charges(
        paths, build_type="Admin", material_lines=[{"amount": 500}],
    )

    reasons = [problem["reason"] for problem in result["problems"]]
    assert "labor_amount_required" in reasons
    assert "install_supplies_amount_required" in reasons
    assert reasons.count("additional_charge_item_missing") == 3
    assert result["lines"] == []


def test_missing_config_keeps_legacy_test_workspaces_compatible(tmp_path):
    paths = _paths(tmp_path)
    result = charges.calculate_additional_charges(
        paths, build_type="Patrol", material_lines=[{"amount": 75}],
    )
    assert result["enabled"] is False
    assert result["estimate_total"] == 75
    assert result["problems"] == []


def test_additional_charges_replace_legacy_manually_selected_supplies_line(tmp_path):
    paths = _paths(tmp_path)
    _write_settings(paths)
    lines = [
        {"product_id": "physical_part", "amount": 100},
        {"product_id": "qb_unassigned_install_supplies", "amount": 450},
    ]
    assert charges.exclude_legacy_managed_lines(paths, lines) == [lines[0]]
