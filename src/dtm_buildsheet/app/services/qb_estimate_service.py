"""Draft QuickBooks Estimates from a vehicle's chosen parts.

This is the "create estimate" half of the QuickBooks bridge. An **Estimate**
is a non-posting QBO document — it does NOT hit the books, which is exactly
what makes it the right object for a reviewable draft ("draft without sending").
Converting an accepted estimate into an Invoice is a separate, explicit step.

Flow per vehicle (one IndividualUnit):
  1. Resolve the build draft's parts to QuickBooks line items. Each part must
     map to a catalog product that is QB-linked (carries qb_item_id), active,
     and priced. Anything that doesn't is a *problem*.
  2. If there are ANY problems, refuse to create the document and report them
     (the owner chose "block until all linked"). Nothing is sent to QBO.
  3. Otherwise resolve the agency's top-level Customer and the true QBO
     Project bound to this vehicle, create the Estimate with ``ProjectRef``,
     and write the estimate link back onto the unit.

``validate_estimate`` runs steps 1–2 only and touches no network, so the UI can
show exactly what's blocking before the owner ever connects or commits.

Like the rest of the integration, no item names, prices, customer data, or QB
response bodies are logged.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ...domain.supply import supply_state
from ...paths import AppPaths
from ..adapters.quickbooks.api_client import QuickBooksApiError
from . import qb_sync_service
from .parts_db_service import get_parts_db_service

logger = logging.getLogger(__name__)


# ── part → QuickBooks line resolution ────────────────────────────────────────


def _qb_fields(spec: dict) -> dict:
    """Pull the QB-owned fields off a product or part_number spec."""
    return {
        "qb_item_id": str(spec.get("qb_item_id", "")).strip(),
        "qb_sku": str(spec.get("qb_sku", "")),
        "qb_sales_description": str(spec.get("qb_sales_description", "")).strip(),
        "qb_unit_price": spec.get("qb_unit_price"),
        "qb_inactive": bool(spec.get("qb_inactive")),
        "qb_pending": bool(spec.get("qb_pending")),
        "price_usd": spec.get("price_usd"),
    }


def _resolution_index(paths: AppPaths) -> tuple[dict, dict, dict]:
    """Build (by_part_number, by_model, prod_qb) lookups from parts_db.

    QB linkage is resolved **per part number** — each ``part_numbers[]`` entry
    can carry its own ``qb_item_id`` / ``qb_unit_price`` (the SKU's price), which
    is what an estimate must bill. A part_number entry that lacks its own QB
    fields falls back to the product-level fields (the legacy one-to-one link
    the Settings → QuickBooks "Link" button writes), so both models work.

    - by_part_number: norm part number → resolved entry {product_id + qb fields}
    - by_model:       norm model string → product_id (last-resort match)
    - prod_qb:        product_id → product-level qb fields (for the model path)
    """
    doc = get_parts_db_service(paths).raw_doc()
    products = doc.get("products") or {}
    by_part_number: dict[str, dict] = {}
    by_model: dict[str, str] = {}
    prod_qb: dict[str, dict] = {}
    manufacturer_specs = doc.get("manufacturers") or {}
    cached_items = {
        str(item.get("qb_item_id", "")).strip(): item
        for item in qb_sync_service._read_cache(paths).get("items", [])
        if str(item.get("qb_item_id", "")).strip()
    }
    cached_descriptions = {
        item_id: str(item.get("description", "")).strip()
        for item_id, item in cached_items.items()
    }
    for pid, spec in products.items():
        spec = spec or {}
        prod_fields = _qb_fields(spec)
        manufacturer_id = str(spec.get("manufacturer_id", "")).strip()
        manufacturer = str(
            (manufacturer_specs.get(manufacturer_id) or {}).get("label", manufacturer_id)
        ).strip() or "Unbranded"
        prod_fields["manufacturer"] = manufacturer
        prod_fields["manufacturer_id"] = manufacturer_id
        # ``friendly_name`` was used by the first QB importer. Keep it as a
        # compatibility fallback, but prefer the separate QB sales-description
        # field populated by reconciliation.
        cached_product = cached_items.get(prod_fields["qb_item_id"], {})
        cached_product_description = cached_descriptions.get(prod_fields["qb_item_id"], "")
        prod_fields["qb_sales_description"] = (
            cached_product_description
            or prod_fields["qb_sales_description"]
            or str(spec.get("friendly_name", "")).strip()
            or str(spec.get("description", "")).strip()
        )
        if cached_product.get("unit_price") is not None:
            prod_fields["qb_unit_price"] = cached_product["unit_price"]
        prod_qb[pid] = prod_fields
        model = str(spec.get("model", "")).strip().lower()
        if model:
            by_model.setdefault(model, pid)
        for pn in spec.get("part_numbers") or []:
            num = str((pn or {}).get("part_number", "")).strip().lower()
            if not num:
                continue
            pn_fields = _qb_fields(pn or {})
            cached_item = cached_items.get(
                pn_fields["qb_item_id"] or prod_fields["qb_item_id"], {}
            )
            cached_price = cached_item.get("unit_price")
            # part_number fields win; fall back to product-level where empty.
            entry = {
                "product_id": pid,
                "qb_item_id": pn_fields["qb_item_id"] or prod_fields["qb_item_id"],
                "qb_sku": pn_fields["qb_sku"] or prod_fields["qb_sku"],
                "qb_sales_description": (
                    cached_descriptions.get(
                        pn_fields["qb_item_id"] or prod_fields["qb_item_id"], ""
                    )
                    or pn_fields["qb_sales_description"]
                    or prod_fields["qb_sales_description"]
                ),
                "qb_unit_price": (
                    cached_price
                    if cached_price is not None
                    else (
                        pn_fields["qb_unit_price"]
                        if pn_fields["qb_unit_price"] is not None
                        else prod_fields["qb_unit_price"]
                    )
                ),
                "qb_inactive": (pn_fields["qb_inactive"] if "qb_inactive" in (pn or {})
                                else prod_fields["qb_inactive"]),
                "qb_pending": pn_fields["qb_pending"],
                "price_usd": pn_fields["price_usd"],
                "manufacturer": manufacturer,
                "manufacturer_id": manufacturer_id,
            }
            if not entry["qb_sales_description"] and entry["qb_item_id"]:
                entry["qb_sales_description"] = cached_descriptions.get(entry["qb_item_id"], "")
            by_part_number.setdefault(num, entry)
    return by_part_number, by_model, prod_qb


def _unbilled_keys(paths: AppPaths) -> set[str]:
    """Normalized part-number + model keys of products tagged ``unbilled``.

    Agency-supplied items (cameras, radios) that the shop installs but never
    bills — they need no QB item and must not appear on an estimate.
    """
    doc = get_parts_db_service(paths).raw_doc()
    tags = doc.get("tags") or {}
    uid = next((tid for tid, t in tags.items()
                if tid == "unbilled" or (t.get("label") or "").strip().lower() == "unbilled"), None)
    if not uid:
        return set()
    keys: set[str] = set()
    for spec in (doc.get("products") or {}).values():
        if uid not in ((spec or {}).get("tag_ids") or []):
            continue
        model = str((spec or {}).get("model", "")).strip().lower()
        if model:
            keys.add(model)
        for pn in (spec or {}).get("part_numbers") or []:
            num = str((pn or {}).get("part_number", "")).strip().lower()
            if num:
                keys.add(num)
    return keys


def _resolve_part_number(
    part_number: str,
    name: str,
    by_part_number: dict,
    by_model: dict,
    prod_qb: dict,
) -> tuple[dict | None, str]:
    """Resolve one concrete part number to a billable line, or return (None, reason).

    reason is one of: no_catalog_match, not_linked, qb_inactive, no_price.
    """
    pn = (part_number or "").strip().lower()
    entry = by_part_number.get(pn) if pn else None
    if entry is None:
        key = pn or (name or "").strip().lower()
        pid = by_model.get(key)
        if pid:
            entry = {"product_id": pid, **prod_qb[pid]}
    if entry is None:
        return None, "no_catalog_match"

    if not entry["qb_item_id"]:
        # Pending-QB part: usable + billable now (via price_usd), flagged so the
        # estimate tells the reviewer to create the item. See docs/PARTS_DB_AND_PICKER.md.
        if entry.get("qb_pending"):
            price = (entry["qb_unit_price"] if entry["qb_unit_price"] is not None
                     else entry.get("price_usd"))
            if price is None:
                return None, "no_price"
            return {
                "product_id": entry["product_id"],
                "qb_item_id": "",
                "qb_sku": entry["qb_sku"],
                "description": entry.get("qb_sales_description", ""),
                "manufacturer": entry.get("manufacturer", "Unbranded"),
                "manufacturer_id": entry.get("manufacturer_id", ""),
                "unit_price": float(price),
                "pending": True,
            }, ""
        return None, "not_linked"
    if entry["qb_inactive"]:
        return None, "qb_inactive"
    if entry["qb_unit_price"] is None:
        return None, "no_price"

    return {
        "product_id": entry["product_id"],
        "qb_item_id": entry["qb_item_id"],
        "qb_sku": entry["qb_sku"],
        "description": entry.get("qb_sales_description", ""),
        "manufacturer": entry.get("manufacturer", "Unbranded"),
        "manufacturer_id": entry.get("manufacturer_id", ""),
        "unit_price": float(entry["qb_unit_price"]),
        "pending": False,
    }, ""


def _resolve_part(draft_part, by_part_number, by_model, prod_qb) -> tuple[dict | None, str]:
    """Resolve one DraftPart using its display/model part number."""
    return _resolve_part_number(
        draft_part.part_number,
        draft_part.name,
        by_part_number,
        by_model,
        prod_qb,
    )


def _resolve_custom_part(draft_part) -> tuple[dict | None, str]:
    """Resolve a picker-created one-off part without touching inventory."""
    custom = (getattr(draft_part, "picker_config", {}) or {}).get("custom_part")
    if not isinstance(custom, dict):
        return None, "no_catalog_match"
    sku = str(custom.get("sku") or draft_part.part_number or "").strip()
    description = str(custom.get("description") or draft_part.name or "").strip()
    try:
        price = float(custom.get("unit_price"))
    except (TypeError, ValueError):
        return None, "no_price"
    if not sku or not description or not math.isfinite(price) or price < 0:
        return None, "no_price"
    return {
        "product_id": "custom_part",
        "qb_item_id": "",
        "qb_sku": sku,
        "description": description,
        "manufacturer": "Custom",
        "unit_price": price,
        "pending": False,
        "custom": True,
    }, ""


def _resolve_window_tint(draft_part) -> tuple[dict | None, str]:
    """Resolve the app-owned per-window tint service through MISC PART."""
    config = (getattr(draft_part, "picker_config", {}) or {}).get("window_tint")
    if not isinstance(config, dict):
        return None, "no_catalog_match"
    windows = [str(value).strip() for value in config.get("windows", []) if str(value).strip()]
    try:
        percentage = int(config.get("percentage"))
    except (TypeError, ValueError):
        return None, "no_price"
    if not windows or not 1 <= percentage <= 100:
        return None, "no_price"
    labels = {
        "windshield": "Windshield",
        "windshield_brow": "Windshield brow",
        "driver_front": "Driver front window",
        "passenger_front": "Passenger front window",
        "driver_rear": "Driver rear window",
        "passenger_rear": "Passenger rear window",
        "driver_quarter": "Driver quarter / cargo window",
        "passenger_quarter": "Passenger quarter / cargo window",
        "rear_window": "Rear window",
    }
    description = f"Window tint — {percentage}% — " + ", ".join(labels.get(value, value) for value in windows)
    return {
        "product_id": "window_tint",
        "qb_item_id": "",
        "qb_sku": "TINT",
        "description": description,
        "manufacturer": "DTM Service",
        "manufacturer_id": "",
        "unit_price": 65.0,
        "pending": False,
        "custom": True,
        "custom_kind": "window_tint",
        "window_count": len(windows),
    }, ""


def _attach_custom_parts_to_misc_item(paths: AppPaths, lines: list[dict]) -> list[dict]:
    """Bill one-off priced parts through the exact active ``MISC PART`` Item."""
    custom_lines = [line for line in lines if line.get("custom")]
    if not custom_lines:
        return []
    misc_item = qb_sync_service.find_cached_active_item_by_name(paths, "MISC PART")
    item_id = str((misc_item or {}).get("qb_item_id") or "").strip()
    if not item_id:
        return [{
            "name": line["name"],
            "part_number": line.get("part_number", ""),
            "reason": "custom_item_unavailable",
        } for line in custom_lines]
    for line in custom_lines:
        line["qb_item_id"] = item_id
        line["qb_item_name"] = str(misc_item.get("name") or "MISC PART")
        line["pending"] = False
    return []


def _component_quantity(component: dict) -> int:
    """Return a safe billable quantity for a concrete component SKU."""
    try:
        quantity = int(component.get("quantity") or 0)
    except (TypeError, ValueError):
        quantity = 0
    return quantity if quantity > 0 else 1


def _apply_quote_override(resolved: dict, picker_config: dict) -> dict:
    """Apply an explicitly authored quote price without changing QB catalog data."""
    if "quote_unit_price_override" not in picker_config:
        return resolved
    try:
        price = float(picker_config["quote_unit_price_override"])
    except (TypeError, ValueError):
        return resolved
    if not math.isfinite(price) or price < 0:
        return resolved
    out = dict(resolved)
    out["unit_price"] = price
    note = str(picker_config.get("quote_note") or "").strip()
    if note:
        description = str(out.get("description") or "").strip()
        out["description"] = f"{description} — {note}" if description else note
    return out


def resolve_build_lines(paths: AppPaths, draft) -> tuple[list[dict], list[dict]]:
    """Split a build draft into (billable_lines, problems).

    Only included parts are considered. A part with quantity <= 0 bills as 1
    (these are physical parts installed on the vehicle — at least one each).
    """
    by_part_number, by_model, prod_qb = _resolution_index(paths)
    unbilled = _unbilled_keys(paths)
    lines: list[dict] = []
    problems: list[dict] = []
    for dp in draft.parts:
        if not dp.include:
            continue
        # Customer-supplied hardware remains on the build manifest but is not
        # a purchase for this estimate, regardless of physical condition.
        if not supply_state(dp).is_billable:
            continue
        picker_config = getattr(dp, "picker_config", {}) or {}
        # Console kits include some physical rows (for example a cup holder or
        # OEM relocation plate). Keep those in the build manifest, but the kit
        # itself already covers their price in QuickBooks.
        if picker_config.get("console_kit_included"):
            continue
        # Guided radio/radar/camera parents are shop-install records. Their
        # separately nested cable-refresh children are the only system rows
        # that are billable through QB.
        if picker_config.get("system_type"):
            continue
        if isinstance(picker_config.get("window_tint"), dict):
            resolved, reason = _resolve_window_tint(dp)
            if reason:
                problems.append({
                    "name": dp.name,
                    "part_number": dp.part_number,
                    "reason": reason,
                })
                continue
            qty = int(resolved.pop("window_count"))
            lines.append({
                **resolved,
                "name": "Window Tint",
                "part_number": "TINT",
                "qty": qty,
                "amount": round(resolved["unit_price"] * qty, 2),
            })
            continue
        if isinstance(picker_config.get("custom_part"), dict):
            resolved, reason = _resolve_custom_part(dp)
            if reason:
                problems.append({
                    "name": dp.name,
                    "part_number": dp.part_number,
                    "reason": reason,
                })
                continue
            qty = dp.quantity if (dp.quantity and dp.quantity > 0) else 1
            lines.append({
                **resolved,
                "name": dp.name,
                "part_number": resolved["qb_sku"],
                "qty": qty,
                "amount": round(resolved["unit_price"] * qty, 2),
            })
            continue
        # Unbilled parts (agency-supplied cameras/radios etc., tagged "unbilled"):
        # tracked on the build but never quoted — skip with no line and no problem.
        if (str(dp.part_number or "").strip().lower() in unbilled
                or str(dp.name or "").strip().lower() in unbilled):
            continue

        # Picker-created rows use the product model as the parent display value
        # (for example PB450L), while the actual selected QB item lives in the
        # concrete component SKU (for example BK1001ITU20). Resolve and bill
        # those concrete SKUs instead of asking the QB catalog to link the
        # display/model string. A row can contain multiple component SKUs (such
        # as split-color light heads), so each one becomes its own estimate line.
        components = [
            component for component in (getattr(dp, "components", []) or [])
            if isinstance(component, dict) and str(component.get("part_number") or "").strip()
        ]
        if components:
            for component in components:
                component_part_number = str(component["part_number"]).strip()
                resolved, reason = _resolve_part_number(
                    component_part_number,
                    dp.name,
                    by_part_number,
                    by_model,
                    prod_qb,
                )
                if reason:
                    problems.append({
                        "name": dp.name,
                        "part_number": component_part_number,
                        "reason": reason,
                    })
                    continue
                qty = _component_quantity(component)
                lines.append({
                    **resolved,
                    "name": dp.name,
                    "part_number": component_part_number,
                    "qty": qty,
                    "amount": round(resolved["unit_price"] * qty, 2),
                })
            continue

        resolved, reason = _resolve_part(dp, by_part_number, by_model, prod_qb)
        if reason:
            problems.append({
                "name": dp.name,
                "part_number": dp.part_number,
                "reason": reason,
            })
            continue
        resolved = _apply_quote_override(resolved, picker_config)
        qty = dp.quantity if (dp.quantity and dp.quantity > 0) else 1
        lines.append({
            **resolved,
            "name": dp.name,
            "part_number": dp.part_number,
            "qty": qty,
            "amount": round(resolved["unit_price"] * qty, 2),
        })
    # A build may reference the same physical QB item more than once (for
    # example two identical printer cables or split manifest rows for the same
    # light). QBO estimates should show one SKU row with the combined quantity.
    consolidated: dict[tuple, dict] = {}
    for line in lines:
        key = (
            line.get("qb_item_id", ""),
            line.get("part_number", "") if line.get("pending") else line.get("qb_item_id", ""),
            line.get("description", ""),
            line.get("unit_price"),
            bool(line.get("pending")),
        )
        current = consolidated.get(key)
        if current is None:
            consolidated[key] = dict(line)
        else:
            current["qty"] += line["qty"]
            current["amount"] = round(current["amount"] + line["amount"], 2)

    lines = sorted(
        consolidated.values(),
        key=lambda line: (
            str(line.get("manufacturer", "Unbranded")).casefold(),
            str(line.get("description") or line.get("name", "")).casefold(),
            str(line.get("qb_sku") or line.get("part_number", "")).casefold(),
        ),
    )
    return lines, problems


def _pending_note(ln: dict) -> str:
    """Reviewer-facing note for a part that isn't a QB inventory item yet."""
    sku = (ln.get("part_number") or "").strip()
    if ln.get("custom"):
        return (f"⚠ CUSTOM PART — NOT IN QB INVENTORY: {sku or ln['name']} — "
                f"{ln['name']} — {ln['qty']} × ${ln['unit_price']:.2f} "
                f"(= ${ln['amount']:.2f})")
    return (f"⚠ NOT IN QB INVENTORY — create item {sku or ln['name']}: "
            f"{ln['name']} — {ln['qty']} × ${ln['unit_price']:.2f} "
            f"(= ${ln['amount']:.2f})")


def _build_estimate_payload(
    customer_ref: str,
    lines: list[dict],
    *,
    memo: str = "",
    project_ref: str = "",
) -> dict:
    """Assemble the QBO Estimate request body from resolved lines.

    Pending-QB parts (no qb_item_id) post as DescriptionOnly lines carrying a
    "create item" note — visible to the reviewer, no ItemRef required, no billed
    amount until the QB user creates the item. See docs/PARTS_DB_AND_PICKER.md.
    """
    qb_lines = []
    for ln in lines:
        if ln.get("pending"):
            qb_lines.append({
                "DetailType": "DescriptionOnly",
                "Description": _pending_note(ln),
            })
            continue
        qb_lines.append({
            "DetailType": "SalesItemLineDetail",
            "Amount": ln["amount"],
            # This is the QB item's Sales Description, not the manifest row
            # name. The latter is only our local fallback when QB has no
            # description available yet.
            "Description": (
                f"{ln.get('part_number') or ln.get('qb_sku')} — {ln.get('description') or ln['name']}"
                if ln.get("custom") else ln.get("description") or ln["name"]
            ),
            "SalesItemLineDetail": {
                "ItemRef": {"value": ln["qb_item_id"]},
                "Qty": ln["qty"],
                "UnitPrice": ln["unit_price"],
            },
        })
    payload: dict = {"CustomerRef": {"value": str(customer_ref)}, "Line": qb_lines}
    if project_ref:
        # ProjectRef is part of the normal Estimate REST payload. It ties the
        # document to a real QBO Project without creating a sub-customer.
        payload["ProjectRef"] = {"value": str(project_ref)}
    if memo:
        payload["CustomerMemo"] = {"value": memo}
    return payload


def _estimate_ref_value(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("value", "") or "").strip()
    return str(value or "").strip()


def _estimate_text_value(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("value", "") or "").strip()
    return str(value or "").strip()


def _estimate_number(value: object) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        number = round(float(value), 4)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _estimate_line_snapshot(line: object) -> dict:
    if not isinstance(line, dict):
        return {}
    detail_type = str(line.get("DetailType", "") or "")
    # QuickBooks may append calculated subtotal/tax rows. They are not
    # Builder-authored material and must not create a false external-edit
    # conflict after an otherwise unchanged create/update.
    if detail_type not in {"SalesItemLineDetail", "DescriptionOnly"}:
        return {}
    detail = line.get("SalesItemLineDetail") or {}
    return {
        "detail_type": detail_type,
        "item_id": _estimate_ref_value(detail.get("ItemRef")),
        "description": str(line.get("Description", "") or "").strip(),
        "quantity": _estimate_number(detail.get("Qty")),
        "unit_price": _estimate_number(detail.get("UnitPrice")),
        "amount": _estimate_number(line.get("Amount")),
    }


def _estimate_snapshot(estimate: object) -> dict:
    """Keep only material Estimate fields owned by Vehicle Builder."""
    if not isinstance(estimate, dict):
        return {}
    return {
        "doc_number": str(estimate.get("DocNumber", "") or "").strip(),
        "customer_id": _estimate_ref_value(estimate.get("CustomerRef")),
        "project_id": _estimate_ref_value(estimate.get("ProjectRef")),
        "customer_memo": _estimate_text_value(estimate.get("CustomerMemo")),
        "private_note": str(estimate.get("PrivateNote", "") or "").strip(),
        "lines": [
            snapshot for snapshot in (
                _estimate_line_snapshot(line) for line in (estimate.get("Line") or [])
            ) if snapshot
        ],
    }


def _estimate_line_label(line: dict) -> str:
    if not line:
        return "—"
    description = str(line.get("description", "") or "").strip()
    if line.get("detail_type") == "DescriptionOnly":
        return description or "Description-only line"
    item = f"Item {line.get('item_id')}" if line.get("item_id") else "Item line"
    facts = [item]
    if line.get("quantity") is not None:
        facts.append(f"qty {line['quantity']}")
    if line.get("unit_price") is not None:
        facts.append(f"unit ${float(line['unit_price']):.2f}")
    if line.get("amount") is not None:
        facts.append(f"total ${float(line['amount']):.2f}")
    if description:
        facts.append(description)
    return " · ".join(facts)


def _estimate_differences(baseline: dict, current: dict) -> list[dict]:
    differences: list[dict] = []
    labels = {
        "doc_number": "Estimate number",
        "customer_id": "Customer",
        "project_id": "QuickBooks Project",
        "customer_memo": "Customer memo",
        "private_note": "Private note",
    }
    for key, label in labels.items():
        if baseline.get(key, "") != current.get(key, ""):
            differences.append({
                "field": label,
                "before": str(baseline.get(key, "") or "—"),
                "after": str(current.get(key, "") or "—"),
            })
    old_lines = baseline.get("lines") if isinstance(baseline.get("lines"), list) else []
    new_lines = current.get("lines") if isinstance(current.get("lines"), list) else []
    for index in range(max(len(old_lines), len(new_lines))):
        before = old_lines[index] if index < len(old_lines) else {}
        after = new_lines[index] if index < len(new_lines) else {}
        if before != after:
            differences.append({
                "field": f"Line {index + 1}",
                "before": _estimate_line_label(before),
                "after": _estimate_line_label(after),
            })
    return differences[:50]


def _estimate_change_status(unit, current_estimate: dict | None) -> dict:
    estimate_id = str(getattr(unit, "qb_estimate_id", "") or "").strip()
    if not estimate_id:
        return {"status": "none", "modified": False, "differences": []}
    baseline = getattr(unit, "qb_estimate_snapshot", {}) or {}
    if current_estimate is None:
        return {
            "status": "missing", "modified": False, "differences": [],
            "message": "The linked estimate could not be found in QuickBooks.",
        }
    if not isinstance(baseline, dict) or not baseline:
        return {
            "status": "untracked", "modified": False, "differences": [],
            "message": "This estimate was linked before QuickBooks change tracking was enabled.",
        }
    current = _estimate_snapshot(current_estimate)
    differences = _estimate_differences(baseline, current)
    return {
        "status": "modified" if differences else "unchanged",
        "modified": bool(differences),
        "differences": differences,
        "snapshot_at": str(getattr(unit, "qb_estimate_snapshot_at", "") or ""),
    }


# ── load helper ───────────────────────────────────────────────────────────────


def _load_unit_draft(paths: AppPaths, project_id: str, individual_id: str):
    """Return (project, build_unit, unit, draft) or ({"error": ...},)-style dict.

    On success returns a 4-tuple; on failure returns a dict with ``error``.
    """
    from ...inputs import project_entry
    from .draft_service import load_draft_for_request

    try:
        project = project_entry.load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "unknown_project"}
    build_unit, unit = qb_sync_service._find_individual(project, individual_id)
    if unit is None:
        return {"ok": False, "error": "unknown_unit"}
    if not unit.draft_id:
        return {"ok": False, "error": "no_build"}
    try:
        draft = load_draft_for_request(unit.draft_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "no_build"}
    return project, build_unit, unit, draft


def _load_individual(paths: AppPaths, project_id: str, individual_id: str):
    """Return ``(project, build_unit, unit)`` without requiring a build draft."""
    from ...inputs import project_entry

    try:
        project = project_entry.load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "unknown_project"}
    build_unit, unit = qb_sync_service._find_individual(project, individual_id)
    if unit is None:
        return {"ok": False, "error": "unknown_unit"}
    return project, build_unit, unit


def _ensure_project_tax_status(client, qb_project_id: str, agency) -> dict:
    """Keep a QBO Project's taxable flag aligned with its agency Customer."""
    if agency is None or not qb_project_id or agency.taxable is None:
        return {"ok": True, "changed": False}
    try:
        current = client.read_customer(qb_project_id)
        if current is None or current.get("Taxable") == bool(agency.taxable):
            return {"ok": True, "changed": False}
        client.update_customer(
            qb_project_id,
            str(current.get("SyncToken", "0")),
            {"taxable": bool(agency.taxable)},
        )
        return {"ok": True, "changed": True}
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks Project tax sync failed: %s", exc)
        return {"ok": False, "error": "project_tax_sync_failed"}


# ── public API ────────────────────────────────────────────────────────────────


def validate_estimate(paths: AppPaths, *, project_id: str, individual_id: str) -> dict:
    """Dry run: resolve the build and report whether an estimate can be created.

    Refreshes the read-only QB Item catalog first. ``can_create`` is True only
    when there are billable lines and zero problems.
    """
    loaded = _load_unit_draft(paths, project_id, individual_id)
    if isinstance(loaded, dict):
        return loaded
    project, build_unit, unit, draft = loaded

    refresh = qb_sync_service.refresh_estimate_catalog(paths)
    if not refresh.get("ok"):
        return refresh

    lines, problems = resolve_build_lines(paths, draft)
    from .estimate_charges_service import exclude_legacy_managed_lines
    lines = exclude_legacy_managed_lines(paths, lines)
    problems.extend(_attach_custom_parts_to_misc_item(paths, lines))
    from . import agency_service, customer_pricing_service
    agency = agency_service.get_agency(paths, (project.customer.agency_id or "").strip())
    lines, pricing = customer_pricing_service.apply_customer_pricing(paths, lines, agency)
    materials_total = round(sum(ln["amount"] for ln in lines), 2)
    from .estimate_charges_service import calculate_additional_charges
    additional_charges = calculate_additional_charges(
        paths,
        build_type=build_unit.build_type,
        material_lines=lines,
    )
    problems.extend(additional_charges["problems"])
    total = additional_charges["estimate_total"]
    pending = [{"name": ln["name"], "part_number": ln.get("part_number", ""),
                "amount": ln["amount"]} for ln in lines if ln.get("pending")]
    customer = None
    customer_linked = False
    if agency is not None:
        customer = {
            "name": agency.name,
            "contact_name": agency.contact_name,
            "contact_email": agency.contact_email,
            "contact_phone": agency.contact_phone,
        }
        customer_linked = bool(agency.qb_customer_id)
    from .exports_upload_service import portable_export_filename
    estimate_change = {"status": "none", "modified": False, "differences": []}
    if str(unit.qb_estimate_id or "").strip():
        client, client_error = qb_sync_service._build_client(paths)
        if client_error:
            estimate_change = {
                "status": "check_failed", "modified": False, "differences": [],
                "message": "QuickBooks changes could not be checked.",
            }
        else:
            try:
                current_estimate = client.read_estimate(str(unit.qb_estimate_id).strip())
                estimate_change = _estimate_change_status(unit, current_estimate)
            except QuickBooksApiError:
                estimate_change = {
                    "status": "check_failed", "modified": False, "differences": [],
                    "message": "QuickBooks changes could not be checked.",
                }
    return {
        "ok": True,
        "can_create": not problems and bool(lines),
        "material_line_count": len(lines),
        "line_count": len(lines) + len(additional_charges["lines"]),
        "total": total,
        "materials_total": materials_total,
        "additional_charges": additional_charges,
        "pricing": pricing,
        "pricing_refreshed_at": refresh.get("last_sync_utc"),
        "problems": problems,
        # Billable but not yet a QB inventory item — created as a flagged note.
        "pending": pending,
        "pending_count": len(pending),
        "customer": customer,
        "customer_linked": customer_linked,
        "existing_estimate_id": str(unit.qb_estimate_id or "").strip(),
        "estimate_change": estimate_change,
        "pdf_available": bool(str(unit.pdf_path or "").strip()),
        "pdf_name": portable_export_filename(str(unit.pdf_path))
        if str(unit.pdf_path or "").strip() else "",
        "project": _project_binding_summary(paths, project, build_unit, unit),
    }


def _project_identity_labels(unit) -> list[str]:
    """Return the sole, owner-approved vehicle identifier for a QBO Project."""
    unit_number = (unit.unit_number or unit.existing_unit_number or "").strip()
    return [f"Unit {unit_number}"] if unit_number else []


def _automatic_build_label(project, build_unit, unit) -> str:
    """Return a deterministic display label without replacing vehicle identity.

    The individual_id remains the durable association for drafts, files, and
    estimates.  This label is only the owner-approved name used when a unit
    number is not known yet.
    """
    build_type = str(getattr(build_unit, "build_type", "") or "Build").strip() or "Build"
    ordinal = 0
    target_id = str(getattr(unit, "individual_id", "") or "")
    for candidate_build in project.build_units:
        if str(candidate_build.build_type or "Build").strip() != build_type:
            continue
        for candidate in candidate_build.individuals:
            ordinal += 1
            if str(candidate.individual_id) == target_id:
                return f"{build_type} #{ordinal}"
    return f"{build_type} #1"


def _estimate_project_name(project, build_unit, unit, *, use_auto_name: bool = False) -> str:
    """Return the canonical, self-identifying name for one real QBO Project.

    QBO already displays the parent agency Customer, so repeating it in every
    Project title is redundant. The operational order is unit number first,
    then build year. Vehicle specification, VIN, and quote number are
    deliberately excluded to keep the QBO Project list clean.
    """
    labels = _project_identity_labels(unit)
    has_stored_binding = bool(
        str(getattr(unit, "qb_project_id", "") or "").strip()
        and str(getattr(unit, "qb_project_name", "") or "").strip()
    )
    if not labels and (use_auto_name or has_stored_binding):
        labels = [_automatic_build_label(project, build_unit, unit)]
    parts = list(labels)
    build_year = (project.customer.build_year or "").strip()
    if build_year:
        parts.append(f"Build {build_year}")
    return " | ".join(p for p in parts if p)


def _project_customer_name(paths: AppPaths, project) -> str:
    """Find the agency label for a project before its QBO Customer is resolved."""
    from . import agency_service

    agency_id = (project.customer.agency_id or "").strip()
    agency = agency_service.get_agency(paths, agency_id) if agency_id else None
    return (agency.name if agency is not None else "").strip()


def _project_binding_summary(paths: AppPaths, project, build_unit, unit) -> dict:
    """Describe the local link to the real QBO Project for the estimate UI."""
    labels = _project_identity_labels(unit)
    stored_name = str(getattr(unit, "qb_project_name", "") or "").strip()
    stored_id = str(getattr(unit, "qb_project_id", "") or "").strip()
    auto_label = _automatic_build_label(project, build_unit, unit)
    return {
        "qb_project_id": stored_id,
        "customer_name": _project_customer_name(paths, project),
        "project_name": _estimate_project_name(project, build_unit, unit),
        "identity_ready": bool(labels or (stored_id and stored_name)),
        "identity_labels": labels or ([auto_label] if stored_id and stored_name else []),
        "auto_label": auto_label,
        "auto_project_name": _estimate_project_name(
            project, build_unit, unit, use_auto_name=True,
        ),
        "ready": bool(stored_id),
    }


def preview_project_binding(paths: AppPaths, *, project_id: str, individual_id: str) -> dict:
    """Return QBO Project setup details without requiring a build draft.

    Project linking is a vehicle-level step, so it can happen as soon as an
    individual unit exists. Estimate validation remains separate because it
    needs the configured build's billable parts.
    """
    loaded = _load_individual(paths, project_id, individual_id)
    if isinstance(loaded, dict):
        return loaded
    project, build_unit, unit = loaded
    return {
        "ok": True,
        "project": _project_binding_summary(paths, project, build_unit, unit),
    }


def _normalize_qb_project_id(value: str) -> str:
    """Accept a numeric Project ID or the project URL copied from QBO's UI."""
    raw = str(value or "").strip()
    if re.fullmatch(r"[0-9]+", raw):
        return raw
    try:
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
    except ValueError:
        return ""
    for key in ("projectId", "project_id", "projectRef"):
        candidate = (query.get(key) or [""])[0].strip()
        if re.fullmatch(r"[0-9]+", candidate):
            return candidate
    # Current QBO project detail pages use ``?id=<project id>``. Restrict this
    # generic parameter to an actual Project URL, so a Customer URL cannot be
    # accidentally saved as a ProjectRef.
    if "project" in parsed.path.lower():
        candidate = (query.get("id") or [""])[0].strip()
        if re.fullmatch(r"[0-9]+", candidate):
            return candidate
    return ""


def bind_project(
    paths: AppPaths, *, project_id: str, individual_id: str, qb_project_id: str,
    accept_auto_name: bool = False,
) -> dict:
    """Store the ID of a real QBO Project created manually in QuickBooks.

    This is a local-only link. The free Accounting API cannot create or list
    Projects, but it can attach an Estimate to this known Project through
    ``ProjectRef``. It accepts a numeric ID or a QBO project URL containing a
    project ID, while rejecting customer names and unrelated values.
    """
    loaded = _load_individual(paths, project_id, individual_id)
    if isinstance(loaded, dict):
        return loaded
    project, build_unit, unit = loaded
    raw_id = _normalize_qb_project_id(qb_project_id)
    if not raw_id:
        return {"ok": False, "error": "invalid_project_id"}
    binding = _project_binding_summary(paths, project, build_unit, unit)
    if not binding["identity_ready"]:
        if not accept_auto_name:
            return {"ok": False, "error": "project_identity_required", "project": binding}
        binding["project_name"] = binding["auto_project_name"]

    unit.qb_project_id = raw_id
    unit.qb_project_name = binding["project_name"]
    from ...inputs import project_entry
    project_entry.save_project(project, paths)
    return {
        "ok": True,
        "qb_project_id": raw_id,
        "project_name": unit.qb_project_name,
    }


def create_estimate(
    paths: AppPaths,
    *,
    project_id: str,
    individual_id: str,
    memo: str = "",
    customer_confirmed: bool = False,
    customer_fields: dict | None = None,
    existing_action: str = "",
    attach_pdf: bool = False,
    pricing_mode: str = "retail",
    custom_pricing: dict | None = None,
    additional_charges: dict | None = None,
    overwrite_qb_changes: bool = False,
) -> dict:
    """Create a QBO Estimate for one vehicle. Blocks if any part is unbillable.

    Uses the agency's top-level QB Customer and the individual vehicle's true
    QBO Project. It never creates a per-vehicle sub-customer.
    """
    loaded = _load_unit_draft(paths, project_id, individual_id)
    if isinstance(loaded, dict):
        return loaded
    project, _build_unit, unit, draft = loaded

    existing_action = str(existing_action or "").strip()
    existing_estimate_id = str(unit.qb_estimate_id or "").strip()
    if existing_estimate_id and existing_action not in {"update", "create_new"}:
        return {
            "ok": False,
            "error": "duplicate_estimate_confirmation_required",
            "existing_estimate_id": existing_estimate_id,
        }
    if existing_action == "update" and not existing_estimate_id:
        return {"ok": False, "error": "existing_estimate_not_found"}

    pdf_path = Path(unit.pdf_path) if str(unit.pdf_path or "").strip() else None
    if attach_pdf:
        from .export_service import _allowed_roots, _check_allowed
        if pdf_path is not None and not pdf_path.is_file():
            from .exports_upload_service import download_export
            hydrated = download_export(
                paths,
                source_path=str(unit.pdf_path),
                agency=str(project.customer.agency or ""),
                year=str(project.customer.build_year or ""),
            )
            if hydrated.get("ok"):
                pdf_path = Path(hydrated["path"])
            else:
                return {
                    "ok": False,
                    "error": "build_pdf_shared_unavailable",
                    "detail": hydrated.get("error", "shared_export_download_failed"),
                }
        if pdf_path is not None and _check_allowed(pdf_path, _allowed_roots(paths)):
            return {"ok": False, "error": "build_pdf_outside_output"}
        if pdf_path is None or not pdf_path.is_file():
            return {"ok": False, "error": "build_pdf_missing"}
        if pdf_path.suffix.lower() != ".pdf":
            return {"ok": False, "error": "build_pdf_invalid"}
        try:
            with pdf_path.open("rb") as stream:
                signature = stream.read(5)
            if pdf_path.stat().st_size > 100 * 1024 * 1024 or signature != b"%PDF-":
                return {"ok": False, "error": "build_pdf_invalid"}
        except OSError:
            return {"ok": False, "error": "build_pdf_missing"}

    refresh = qb_sync_service.refresh_estimate_catalog(paths)
    if not refresh.get("ok"):
        return refresh

    lines, problems = resolve_build_lines(paths, draft)
    from .estimate_charges_service import exclude_legacy_managed_lines
    lines = exclude_legacy_managed_lines(paths, lines)
    problems.extend(_attach_custom_parts_to_misc_item(paths, lines))
    from . import agency_service, customer_pricing_service
    agency = agency_service.get_agency(paths, (project.customer.agency_id or "").strip())
    try:
        lines, pricing = customer_pricing_service.apply_customer_pricing(
            paths,
            lines,
            agency,
            pricing_mode=pricing_mode,
            custom_discounts=custom_pricing,
        )
    except ValueError as exc:
        return {"ok": False, "error": "invalid_pricing", "detail": str(exc)}
    from .estimate_charges_service import calculate_additional_charges
    charge_result = calculate_additional_charges(
        paths,
        build_type=_build_unit.build_type,
        material_lines=lines,
        overrides=additional_charges,
    )
    problems.extend(charge_result["problems"])
    if problems:
        return {"ok": False, "error": "validation_failed",
                "problems": problems, "line_count": len(lines)}
    if not lines:
        return {"ok": False, "error": "no_billable_parts"}
    lines.extend(charge_result["lines"])

    binding = _project_binding_summary(paths, project, _build_unit, unit)
    if not binding["identity_ready"]:
        return {"ok": False, "error": "project_identity_required", "project": binding}
    if not binding["ready"]:
        return {"ok": False, "error": "project_not_linked", "project": binding}

    client, err = qb_sync_service._build_client(paths)
    if err:
        return err

    tax_sync = _ensure_project_tax_status(client, unit.qb_project_id, agency)
    if not tax_sync.get("ok"):
        return tax_sync

    customer_result = qb_sync_service.ensure_top_level_customer(
        paths,
        project,
        client=client,
        confirmed=customer_confirmed,
        fields=customer_fields,
    )
    if not customer_result.get("ok"):
        return customer_result
    project_name = _estimate_project_name(project, _build_unit, unit)
    memo_parts = [project_name]
    vehicle_description = " ".join(
        value for value in (unit.year, unit.make, unit.model) if str(value or "").strip()
    )
    if vehicle_description:
        memo_parts.append(f"Vehicle: {vehicle_description}")
    if memo.strip():
        memo_parts.append(memo.strip())
    payload = _build_estimate_payload(
        customer_result["qb_customer_id"],
        lines,
        memo=" — ".join(memo_parts),
        project_ref=unit.qb_project_id,
    )
    # QBO does not expose the Estimate form's Discounts and fees → Bank
    # transfer switch through the Accounting API. Do not confuse it with the
    # Invoice-only AllowOnlineACHPayment field or send an invented Estimate
    # field that Intuit may silently ignore.
    payload["PrivateNote"] = f"DTM vehicle project: {project_name}"
    current_estimate = None
    try:
        if existing_action == "update":
            current_estimate = client.read_estimate(existing_estimate_id)
            if current_estimate is None:
                return {
                    "ok": False,
                    "error": "existing_estimate_not_found",
                    "existing_estimate_id": existing_estimate_id,
                }
            estimate_change = _estimate_change_status(unit, current_estimate)
            change_status = str(estimate_change.get("status") or "untracked")
            if change_status != "unchanged" and not overwrite_qb_changes:
                return {
                    "ok": False,
                    "error": (
                        "existing_estimate_modified"
                        if change_status == "modified"
                        else "existing_estimate_change_unverified"
                    ),
                    "existing_estimate_id": existing_estimate_id,
                    "estimate_change": estimate_change,
                }
            result = client.update_estimate(
                existing_estimate_id,
                current_estimate.get("SyncToken", "0"),
                payload,
            )
            estimate_action = "updated"
        else:
            next_doc_number = client.next_estimate_doc_number()
            if next_doc_number:
                payload["DocNumber"] = next_doc_number
            result = client.create_estimate(payload)
            estimate_action = "created"
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks estimate write failed: %s", exc)
        # Do not leave a locally stored, rejected project reference looking
        # usable. Keep it intact for auditability, but give the UI the binding
        # context it needs to send the user straight back to Project setup.
        if "qb_9341: Invalid ProjectRef" in str(exc):
            return {
                "ok": False,
                "error": "invalid_qb_project_ref",
                "project": {**binding, "project_ref_invalid": True},
            }
        return {
            "ok": False,
            "error": "quickbooks_rejected_estimate",
            "detail": str(exc),
        }

    estimate_id = result.get("qb_estimate_id", "")
    unit.qb_estimate_id = estimate_id
    unit.qb_project_name = project_name
    snapshot_source = result.get("_estimate")
    if not isinstance(snapshot_source, dict) or not snapshot_source:
        snapshot_source = {**(current_estimate or {}), **payload}
        snapshot_source["DocNumber"] = (
            result.get("doc_number") or snapshot_source.get("DocNumber", "")
        )
    unit.qb_estimate_snapshot = _estimate_snapshot(snapshot_source)
    unit.qb_estimate_snapshot_at = datetime.now(timezone.utc).isoformat()
    from ...inputs import project_entry
    project_entry.save_project(project, paths)
    attachment = None
    if attach_pdf and pdf_path is not None:
        try:
            existing_attachments = client.fetch_estimate_attachments(estimate_id)
            pdf_size = pdf_path.stat().st_size
            duplicate = next((row for row in existing_attachments if
                row.get("file_name") == pdf_path.name and row.get("size") == pdf_size), None)
            if duplicate:
                attachment = {
                    "ok": True,
                    "skipped": "already_attached",
                    "attachment_id": duplicate.get("id", ""),
                    "file_name": pdf_path.name,
                }
            else:
                uploaded = client.upload_estimate_attachment(estimate_id, str(pdf_path))
                attachment = {"ok": True, **uploaded}
        except (OSError, QuickBooksApiError) as exc:
            logger.warning("QuickBooks build PDF attachment failed: %s", exc)
            attachment = {"ok": False, "error": str(exc)}
    total = round(sum(ln["amount"] for ln in lines), 2)
    pending_count = sum(1 for ln in lines if ln.get("pending"))
    logger.info("QB estimate %s: %d lines (%d pending)", estimate_action, len(lines), pending_count)
    return {
        "ok": True,
        "action": estimate_action,
        "qb_estimate_id": estimate_id,
        "doc_number": result.get("doc_number", ""),
        "line_count": len(lines),
        "pending_count": pending_count,
        "total": total,
        "materials_total": charge_result["materials_total"],
        "additional_charges": {
            key: value for key, value in charge_result.items()
            if key not in {"lines", "problems"}
        },
        "pricing": pricing,
        "pricing_refreshed_at": refresh.get("last_sync_utc"),
        "qb_project_id": unit.qb_project_id,
        "project_name": project_name,
        "attachment": attachment,
    }


def create_estimates_batch(
    paths: AppPaths, *, project_id: str, individual_ids: list[str] | None = None, memo: str = "",
    attach_pdf: bool = False,
) -> dict:
    """Create estimates for several vehicles. Each is validated independently.

    Per the "block until all linked" rule, a vehicle with unbillable parts is
    skipped (reported under its result), not silently partial-billed; clean
    vehicles still go through. Returns per-unit results plus created/blocked
    counts.
    """
    from ...inputs import project_entry

    try:
        project = project_entry.load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "unknown_project"}

    wanted = set(individual_ids) if individual_ids else None
    targets = [
        ind.individual_id
        for bu in project.build_units
        for ind in bu.individuals
        if wanted is None or ind.individual_id in wanted
    ]

    results = []
    created = 0
    for ind_id in targets:
        res = create_estimate(
            paths,
            project_id=project_id,
            individual_id=ind_id,
            memo=memo,
            attach_pdf=attach_pdf,
        )
        if res.get("ok"):
            created += 1
        results.append({"individual_id": ind_id, **res})

    return {
        "ok": True,
        "created": created,
        "blocked": len(results) - created,
        "results": results,
    }
