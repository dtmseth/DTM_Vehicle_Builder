"""Build the hosted Shopmonkey pricing matrix from audited QBO and guide rules.

The command is dry-run by default. Pass ``--apply`` to write the generated
configuration through the Builder's authenticated hosted-settings boundary.
It never reads or prints the Shopmonkey API key.
"""

from __future__ import annotations

import argparse
import json
import re

import requests

from dtm_buildsheet.app.services import shopmonkey_service


# QBO customer scope and product groups were audited in the live company on
# 2026-11-03. Each tuple is (Retail, Wholesale, Default/untagged). A missing rule stays disabled;
# Standard Sell is not copied into Wholesale unless QBO explicitly applies the
# rule to that customer type or All Customers. Guide-only Standard Sell rules
# extend Retail for brands that have no QBO price rule.
_AUDITED_RULES = {
    "Gamber Johnson": (("retail", "discount", 40), ("retail", "discount", 40), ("retail", "discount", 40)),
    "Havis": (("retail", "discount", 20), ("retail", "discount", 20), ("retail", "discount", 20)),
    "Kussmaul": (("retail", "discount", 10), None, None),
    "NightRide": (("cost", "markup", 25), None, None),
    "PAC Tool Mounts": (("retail", "discount", 5), None, None),
    "Patrol PC": (("retail", "discount", 26), None, None),
    "REDARC": (("retail", "discount", 10), None, None),
    "Santa Cruz Gunlocks": (("retail", "discount", 25), None, None),
    "Setina": (("retail", "discount", 20), ("retail", "discount", 30), None),
    "SoundOff Signal": (("retail", "discount", 45), None, None),
    "TigerTough": (("retail", "discount", 10), None, None),
    "TruckVault": (("retail", "discount", 10), None, None),
    "Whelen": (("retail", "discount", 36), ("retail", "discount", 43), None),
}

_WESTIN_FAMILY = {
    "Brute",
    "Fey",
    "Superwinch",
    "SW Military",
    "Westin",
    "Westin Public Safety",
}

_PENDING_GUIDE_FORMULA = {
    "Angel Armor": "Guide uses price-sheet Agency Pricing",
    "AnyGlide": "No formula in vendor guide",
    "Apparel/Displays/Lit": "Imported grouping; no manufacturer formula in vendor guide",
}

_LOCAL_BUILDER_URL = "http://127.0.0.1:7655"


def _local_builder_request(method: str, path: str, payload: dict | None = None) -> dict:
    response = requests.request(
        method,
        f"{_LOCAL_BUILDER_URL}{path}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    document = response.json()
    return document if isinstance(document, dict) else {"ok": False, "error": "invalid_response"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _rule(
    *, brand: dict, customer_type_id: str, basis: str, operation: str,
    percent: float, enabled: bool = True,
) -> dict:
    return {
        "id": f"{_slug(brand['name'])}-{customer_type_id}",
        "brand_id": brand["id"],
        "brand": brand["name"],
        "customer_type_id": customer_type_id,
        "basis": basis,
        "operation": operation,
        "percent": percent,
        "enabled": enabled,
    }


def build_config(current: dict, references: dict) -> tuple[dict, list[str]]:
    labels = {row["name"]: row for row in references["customer_labels"]}
    brands = {row["name"]: row for row in references["brands"]}
    missing = [name for name in ("$ Retail $", "$ Wholesale $") if name not in labels]
    if missing:
        raise RuntimeError(f"Missing Shopmonkey Customer labels: {', '.join(missing)}")

    rules: list[dict] = []
    pending: list[str] = []
    for name in sorted(brands, key=str.casefold):
        brand = brands[name]
        if name in _WESTIN_FAMILY:
            retail = ("cost", "markup", 25)
            wholesale = untagged = None
        elif name in _AUDITED_RULES:
            retail, wholesale, untagged = _AUDITED_RULES[name]
        else:
            retail = wholesale = untagged = None
            pending.append(f"{name}: {_PENDING_GUIDE_FORMULA.get(name, 'No reviewed rule')}")
        retail = retail or ("retail", "discount", 0)
        wholesale = wholesale or ("retail", "discount", 0)
        untagged = untagged or ("retail", "discount", 0)
        rules.append(_rule(
            brand=brand, customer_type_id="retail", basis=retail[0],
            operation=retail[1], percent=retail[2], enabled=retail[2] > 0,
        ))
        rules.append(_rule(
            brand=brand, customer_type_id="wholesale", basis=wholesale[0],
            operation=wholesale[1], percent=wholesale[2], enabled=wholesale[2] > 0,
        ))
        rules.append(_rule(
            brand=brand, customer_type_id="default", basis=untagged[0],
            operation=untagged[1], percent=untagged[2], enabled=untagged[2] > 0,
        ))

    if "Gamber Johnson" in brands:
        pending.append(
            "Gamber Johnson Retail: QBO's 30% rule is limited to the "
            "GAMBER JOHNSON CRADLE/DOCK product group; the brand-wide matrix "
            "uses QBO's 40% All Customers rule until product-level matching is added."
        )
    if any(name in brands for name in _WESTIN_FAMILY):
        pending.append(
            "Westin: QBO Retail uses cost +25%; the vendor guide's 15% off list "
            "Standard Sell rule conflicts and is not loaded automatically."
        )

    config = {
        "schema_version": 2,
        "revision": str(current.get("revision") or ""),
        "updated_at": str(current.get("updated_at") or ""),
        "enabled": True,
        "mode": "test",
        "test_order_id": str(current.get("test_order_id") or ""),
        "max_line_age_seconds": int(current.get("max_line_age_seconds") or 600),
        "preserve_custom_prices": True,
        "customer_types": [
            {
                "id": "retail", "name": "Retail", "label_id": labels["$ Retail $"]["id"],
                "label": "$ Retail $", "enabled": True,
            },
            {
                "id": "wholesale", "name": "Wholesale",
                "label_id": labels["$ Wholesale $"]["id"],
                "label": "$ Wholesale $", "enabled": True,
            },
            {
                "id": "default", "name": "Default / untagged",
                "label_id": "", "label": "", "match_untagged": True,
                "enabled": True,
            },
        ],
        "rules": rules,
    }
    return config, pending


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the generated test-mode config")
    parser.add_argument(
        "--local-builder", action="store_true",
        help="use the already-running Builder on localhost (the API key remains in that process)",
    )
    args = parser.parse_args()

    if args.local_builder:
        hosted = _local_builder_request("GET", "/api/shopmonkey/pricing")
        references = _local_builder_request("GET", "/api/shopmonkey/pricing/references")
    else:
        hosted = shopmonkey_service.get_pricing_settings()
        references = shopmonkey_service.pricing_reference_data()
    if not hosted.get("ok") or not references.get("ok"):
        print(json.dumps({
            "ok": False,
            "hosted_error": hosted.get("error", ""),
            "reference_error": references.get("error", ""),
        }))
        return 1
    config, pending = build_config(hosted["config"], references)
    enabled = sum(1 for row in config["rules"] if row["enabled"])
    summary = {
        "ok": True,
        "applied": False,
        "persisted": bool(hosted.get("persisted")),
        "revision_present": bool(hosted.get("config", {}).get("revision")),
        "mode": config["mode"],
        "brands": len(references["brands"]),
        "rules": len(config["rules"]),
        "enabled_rules": enabled,
        "disabled_rules": len(config["rules"]) - enabled,
        "pending": pending,
    }
    if args.apply:
        payload = {"config": config, "expected_revision": hosted["config"].get("revision", "")}
        result = (
            _local_builder_request("POST", "/api/shopmonkey/pricing/save", payload)
            if args.local_builder
            else shopmonkey_service.save_pricing_settings(
                config, hosted["config"].get("revision", "")
            )
        )
        summary["applied"] = bool(result.get("ok"))
        summary["save_error"] = str(result.get("error") or "")
        if result.get("config"):
            summary["revision_saved"] = bool(result["config"].get("revision"))
        print(json.dumps(summary, indent=2))
        return 0 if result.get("ok") else 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
