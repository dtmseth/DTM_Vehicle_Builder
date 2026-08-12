"""Customer sales-price rules layered over QuickBooks Item list prices.

QuickBooks ``Item.UnitPrice`` remains the immutable list-price source.  This
module applies DTM's reviewed manufacturer discounts only at estimate time,
so catalog reconciliation can keep refreshing list prices without baking one
customer's terms into ``parts_db.json``.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from ...paths import AppPaths
from .config_service import save_config_file
from .parts_db_service import get_parts_db_service


DEFAULT_RULE_NAME = "Default"
DEFAULT_MANUFACTURER_DISCOUNTS = {
    "gamber_johnson": 40.0,
    "havis": 20.0,
    "pac_tool": 5.0,
    "santa_cruz": 25.0,
    "setina": 20.0,
    "westin": 15.0,
    "whelen": 38.0,
}


def _money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _discount(value: object) -> float:
    try:
        discount = float(value)
    except (TypeError, ValueError):
        raise ValueError("Discounts must be numbers from 0 through 100") from None
    if not 0 <= discount <= 100:
        raise ValueError("Discounts must be numbers from 0 through 100")
    return discount


def _pricing_doc(paths: AppPaths) -> tuple[dict, dict]:
    doc = get_parts_db_service(paths).raw_doc()
    pricing = doc.get("customer_pricing") or {}
    rule = pricing.get("default_rule") or {}
    discounts = {
        manufacturer_id: _discount(value)
        for manufacturer_id, value in (rule.get("manufacturer_discounts") or {}).items()
    }
    if not discounts:
        discounts = dict(DEFAULT_MANUFACTURER_DISCOUNTS)
    return doc, {
        "name": str(rule.get("name") or DEFAULT_RULE_NAME).strip() or DEFAULT_RULE_NAME,
        "manufacturer_discounts": discounts,
    }


def get_default_rule(paths: AppPaths) -> dict:
    """Return the shared default rule and display labels for its manufacturers."""
    doc, rule = _pricing_doc(paths)
    manufacturers = doc.get("manufacturers") or {}
    rows = []
    for manufacturer_id, discount in rule["manufacturer_discounts"].items():
        label = str((manufacturers.get(manufacturer_id) or {}).get("label") or manufacturer_id)
        rows.append({
            "manufacturer_id": manufacturer_id,
            "manufacturer": label,
            "discount_percent": discount,
        })
    rows.sort(key=lambda row: row["manufacturer"].casefold())
    return {"ok": True, "rule_name": rule["name"], "discounts": rows}


def save_default_rule(paths: AppPaths, body: dict) -> dict:
    """Persist a reviewed shared default through the normal config mirror path."""
    doc, current = _pricing_doc(paths)
    incoming = body.get("manufacturer_discounts")
    if not isinstance(incoming, dict) or not incoming:
        return {"ok": False, "error": "At least one manufacturer discount is required"}
    known_manufacturers = doc.get("manufacturers") or {}
    try:
        discounts = {}
        for manufacturer_id, value in incoming.items():
            mid = str(manufacturer_id).strip()
            if mid not in known_manufacturers:
                raise ValueError(f"Unknown manufacturer: {mid}")
            discounts[mid] = _discount(value)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    name = str(body.get("rule_name") or current["name"] or DEFAULT_RULE_NAME).strip()
    doc["customer_pricing"] = {
        "default_rule": {
            "name": name or DEFAULT_RULE_NAME,
            "manufacturer_discounts": discounts,
        }
    }
    result = save_config_file("parts_db.json", doc, paths)
    if not result.get("ok"):
        return result
    get_parts_db_service(paths).invalidate()
    return {**get_default_rule(paths), **{k: v for k, v in result.items() if k != "ok"}}


def normalize_overrides(value: object) -> dict[str, float]:
    """Validate a sparse AgencyRecord manufacturer→discount override map."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError("Agency pricing overrides must be an object")
    return {str(key).strip(): _discount(discount) for key, discount in value.items() if str(key).strip()}


def effective_rule(paths: AppPaths, agency=None) -> dict:
    """Return default discounts overlaid by one agency's sparse exceptions."""
    _doc, default = _pricing_doc(paths)
    overrides = normalize_overrides(getattr(agency, "pricing_overrides", {}) if agency else {})
    effective = {**default["manufacturer_discounts"], **overrides}
    return {
        "rule_name": default["name"],
        "source": "customer_override" if overrides else "default",
        "manufacturer_discounts": effective,
        "overrides": overrides,
    }


def apply_customer_pricing(paths: AppPaths, lines: list[dict], agency=None) -> tuple[list[dict], dict]:
    """Apply the effective rule to resolved estimate lines and return a summary."""
    rule = effective_rule(paths, agency)
    priced_lines: list[dict] = []
    applied: dict[str, dict] = {}
    list_total = 0.0
    customer_total = 0.0
    for original in lines:
        line = deepcopy(original)
        list_unit_price = float(line.get("unit_price") or 0)
        quantity = int(line.get("qty") or 1)
        manufacturer_id = str(line.get("manufacturer_id") or "").strip()
        # Pending rows and one-off custom prices are not manufacturer list
        # prices, so never infer a catalog discount for them. Custom rows may
        # carry the generic MISC PART ItemRef solely so QBO can bill the amount.
        discount = (
            rule["manufacturer_discounts"].get(manufacturer_id, 0.0)
            if line.get("qb_item_id") else 0.0
        )
        customer_unit_price = _money(list_unit_price * (1 - discount / 100))
        list_amount = _money(list_unit_price * quantity)
        customer_amount = _money(customer_unit_price * quantity)
        line.update({
            "list_unit_price": list_unit_price,
            "list_amount": list_amount,
            "discount_percent": discount,
            "pricing_rule": rule["rule_name"],
            "unit_price": customer_unit_price,
            "amount": customer_amount,
        })
        priced_lines.append(line)
        list_total += list_amount
        customer_total += customer_amount
        if discount:
            applied[manufacturer_id] = {
                "manufacturer_id": manufacturer_id,
                "manufacturer": line.get("manufacturer") or manufacturer_id,
                "discount_percent": discount,
                "override": manufacturer_id in rule["overrides"],
            }

    list_total = _money(list_total)
    customer_total = _money(customer_total)
    return priced_lines, {
        "rule_name": rule["rule_name"],
        "source": rule["source"],
        "list_total": list_total,
        "customer_total": customer_total,
        "savings": _money(list_total - customer_total),
        "applied_discounts": sorted(applied.values(), key=lambda row: str(row["manufacturer"]).casefold()),
    }
