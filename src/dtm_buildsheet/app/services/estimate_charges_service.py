from __future__ import annotations

import math

from ...paths import AppPaths
from . import qb_sync_service
from .config_service import load_config_file


CONFIG_FILENAME = "estimate_charges.json"
LEGACY_MANAGED_PRODUCT_IDS = {"qb_unassigned_install_supplies"}


def load_settings(paths: AppPaths) -> dict:
    """Load shared estimate-charge settings.

    A missing file is treated as a legacy workspace with this feature disabled.
    Packaged/current workspaces always receive the bundled configuration file.
    """
    try:
        return {"enabled": True, **load_config_file(CONFIG_FILENAME, paths)}
    except FileNotFoundError:
        return {
            "enabled": False,
            "schema_version": 1,
            "card_fee_percent": 0,
            "service_items": {},
            "presets": {},
        }


def _money(value: object, fallback: float = 0) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return fallback
    return round(amount, 2) if math.isfinite(amount) and amount >= 0 else fallback


def _preset_id(settings: dict, build_type: str, requested: str = "") -> str:
    presets = settings.get("presets") or {}
    if requested in presets:
        return requested
    build_label = str(build_type or "").strip().casefold()
    for preset_id, preset in presets.items():
        aliases = [preset_id, *((preset or {}).get("aliases") or [])]
        if any(str(alias).strip().casefold() in build_label for alias in aliases if str(alias).strip()):
            return preset_id
    return "custom" if "custom" in presets else next(iter(presets), "")


def _service_line(item: dict, *, charge_type: str, amount: float, description: str) -> dict:
    item_name = str(item.get("name") or "").strip()
    return {
        "product_id": f"estimate_charge_{charge_type}",
        "qb_item_id": str(item.get("qb_item_id") or "").strip(),
        "qb_item_name": item_name,
        "qb_sku": str(item.get("sku") or "").strip(),
        "description": description,
        "manufacturer": "DTM",
        "manufacturer_id": "",
        "unit_price": amount,
        "pending": False,
        "discountable": False,
        "estimate_charge_type": charge_type,
        "name": item_name,
        "part_number": item_name,
        "qty": 1,
        "amount": amount,
    }


def exclude_legacy_managed_lines(paths: AppPaths, lines: list[dict]) -> list[dict]:
    """Keep an older manually selected supplies row from billing twice.

    The draft row remains on the shop manifest; Additional charges owns its
    estimate amount once this config is enabled.
    """
    if not load_settings(paths).get("enabled"):
        return lines
    return [
        line for line in lines
        if str(line.get("product_id") or "") not in LEGACY_MANAGED_PRODUCT_IDS
    ]


def calculate_additional_charges(
    paths: AppPaths,
    *,
    build_type: str,
    material_lines: list[dict],
    overrides: dict | None = None,
) -> dict:
    """Resolve presets and produce ready-to-post QBO service lines."""
    settings = load_settings(paths)
    materials_total = round(sum(_money(line.get("amount")) for line in material_lines), 2)
    if not settings.get("enabled"):
        return {
            "enabled": False,
            "preset_id": "",
            "presets": {},
            "card_fee_percent": 0,
            "materials_total": materials_total,
            "labor_amount": 0,
            "install_supplies_amount": 0,
            "delivery_amount": 0,
            "card_fee_amount": 0,
            "additional_total": 0,
            "estimate_total": materials_total,
            "lines": [],
            "problems": [],
        }

    values = overrides if isinstance(overrides, dict) else {}
    presets = settings.get("presets") or {}
    preset_id = _preset_id(settings, build_type, str(values.get("preset_id") or ""))
    preset = presets.get(preset_id) or {}
    labor_amount = _money(values.get("labor_amount"), _money(preset.get("labor_amount")))
    supplies_amount = _money(
        values.get("install_supplies_amount"),
        _money(preset.get("install_supplies_amount")),
    )
    delivery_amount = _money(values.get("delivery_amount"), 0)
    fee_percent = _money(settings.get("card_fee_percent"), 4)
    fee_base = round(materials_total + labor_amount + supplies_amount + delivery_amount, 2)
    fee_amount = round(fee_base * fee_percent / 100, 2)

    problems: list[dict] = []
    if labor_amount <= 0:
        problems.append({
            "name": "Installation labor",
            "part_number": str((settings.get("service_items") or {}).get("labor") or ""),
            "reason": "labor_amount_required",
        })
    if supplies_amount <= 0:
        problems.append({
            "name": "Install supplies",
            "part_number": str((settings.get("service_items") or {}).get("install_supplies") or ""),
            "reason": "install_supplies_amount_required",
        })

    item_names = settings.get("service_items") or {}
    needed_types = ["labor", "install_supplies", "card_fee"]
    if delivery_amount > 0:
        needed_types.append("delivery")
    items: dict[str, dict] = {}
    for charge_type in needed_types:
        item_name = str(item_names.get(charge_type) or "").strip()
        item = qb_sync_service.find_cached_active_item_by_name(paths, item_name) if item_name else None
        if not str((item or {}).get("qb_item_id") or "").strip():
            problems.append({
                "name": item_name or charge_type.replace("_", " ").title(),
                "part_number": item_name,
                "reason": "additional_charge_item_missing",
                "charge_type": charge_type,
            })
        else:
            items[charge_type] = item

    label = str(preset.get("label") or preset_id.title() or "Custom")
    lines: list[dict] = []
    if labor_amount > 0 and "labor" in items:
        lines.append(_service_line(
            items["labor"], charge_type="labor", amount=labor_amount,
            description=f"DTM installation labor — {label} build",
        ))
    if supplies_amount > 0 and "install_supplies" in items:
        lines.append(_service_line(
            items["install_supplies"], charge_type="install_supplies", amount=supplies_amount,
            description=f"DTM install supplies — {label} build",
        ))
    if delivery_amount > 0 and "delivery" in items:
        lines.append(_service_line(
            items["delivery"], charge_type="delivery", amount=delivery_amount,
            description="Delivery / travel fee",
        ))
    if fee_amount > 0 and "card_fee" in items:
        lines.append(_service_line(
            items["card_fee"], charge_type="card_fee", amount=fee_amount,
            description=f"{fee_percent:g}% credit card processing fee",
        ))

    additional_total = round(labor_amount + supplies_amount + delivery_amount + fee_amount, 2)
    return {
        "enabled": True,
        "preset_id": preset_id,
        "preset_label": label,
        "presets": presets,
        "service_items": item_names,
        "card_fee_percent": fee_percent,
        "materials_total": materials_total,
        "labor_amount": labor_amount,
        "install_supplies_amount": supplies_amount,
        "delivery_amount": delivery_amount,
        "card_fee_amount": fee_amount,
        "additional_total": additional_total,
        "estimate_total": round(materials_total + additional_total, 2),
        "lines": lines,
        "problems": problems,
    }
