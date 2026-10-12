"""Read-only planning for importing an existing QBO Estimate into a build.

The Estimate is a bill of materials seed, not a build definition.  This module
therefore classifies lines and returns catalog/build hints without mutating the
project, draft, parts database, or QuickBooks.  The UI uses the result to drive
the ordinary picker and the existing guided-system workflows.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from ...domain.supply import supply_state
from ...inputs import project_entry
from ...paths import AppPaths
from ..adapters.quickbooks.api_client import QuickBooksApiError
from . import config_service, estimate_charges_service, qb_sync_service
from .draft_service import load_draft_for_request
from .parts_db_service import get_parts_db_service


_GUIDED_FAMILIES = {
    "radio_comms": "radio",
    "radar": "radar",
    "camera_system": "camera",
    "console_system": "console",
}
_PENDING_MARKERS = ("not in qb inventory", "custom part — not in qb inventory")
_TRACER_MODEL = re.compile(r"\b\d+\s*-?\s*lamp\b", re.IGNORECASE)
_FIXTURE_PART_ALIASES = {"front_interior_light_bar": "interior_light_bar_front"}
# These parts have one useful build-sheet home, even though the broader Parts
# DB vocabulary retains historical location choices for old builds. Estimate
# import can therefore place them without interrupting the reviewer.
_IMPORT_FIXED_LOCATIONS = {
    "k9_kennel": "PRISONER AREA",
    "equipment_tray": "CARGO AREA",
}
_GUIDED_PRIMARY_PART_TYPES = {
    "radio": "radio_head",
    "radar": "radar_display_unit",
    "camera": "camera_dvr",
    "console": "console",
}
_GUIDED_COMPONENT_PART_TYPES = {
    "radio": {
        "radio_head", "radio_brick", "radio_antenna_top", "radio_speaker",
        "radio_cable", "radio_mic_clip", "radio_antenna_cable",
    },
    "radar": {
        "radar_display_unit", "radar_counting_unit", "front_radar_antenna_mount",
        "rear_radar_antenna_mount", "radar_cable",
    },
    "camera": {
        "camera_dvr", "camera_antenna", "front_camera", "rear_camera",
        "rear_seat_camera", "body_camera_dock", "wireless_mic_charger",
    },
    "console": {
        "console", "special_face_plate", "arm_rest", "motion_attachment",
        "pedestal_mount", "docking_station", "radio_mic_clip", "printer",
        "printer_power", "printer_usb",
    },
}
_NON_PART_ITEM_NAMES = re.compile(
    r"^(?:(?:labor|labour|configuration|configeration|programming)(?: .*)?|"
    r"installation labor|install labor|installation|install|shop supplies|install supplies|"
    r"delivery|travel|convenience fee|credit card fee)$",
    re.IGNORECASE,
)


def _text(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or value.get("name") or "").strip()
    return str(value or "").strip()


def _ref_name(value: object) -> str:
    """Prefer a QBO reference's human label when one is available."""
    if isinstance(value, dict):
        return str(value.get("name") or value.get("value") or "").strip()
    return str(value or "").strip()


def _number(value: object) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        result = round(float(value), 4)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return int(result) if result.is_integer() else result


def _catalog_indexes(doc: dict, paths: AppPaths) -> dict:
    products = doc.get("products") or {}
    manufacturers = doc.get("manufacturers") or {}
    part_types = doc.get("part_types") or {}
    families = doc.get("families") or {}
    try:
        catalog_parts = (config_service.load_config_file("part_catalog.json", paths).get("parts") or [])
    except (FileNotFoundError, ValueError):
        catalog_parts = []
    fixture_catalog = {
        str(part.get("part_id") or ""): part
        for part in catalog_parts
        if isinstance(part, dict) and part.get("is_fixture")
    }

    family_by_part_type: dict[str, list[str]] = defaultdict(list)
    for family_id, family in families.items():
        for part_type_id in (family or {}).get("members") or []:
            family_by_part_type[str(part_type_id)].append(str(family_id))

    by_qb_item_id: dict[str, list[dict]] = defaultdict(list)
    by_sku: dict[str, dict] = {}
    for product_id, product in products.items():
        if not isinstance(product, dict):
            continue
        manufacturer_id = str(product.get("manufacturer_id") or "").strip()
        manufacturer = str(
            (manufacturers.get(manufacturer_id) or {}).get("label") or manufacturer_id
        ).strip()
        fits = [str(value) for value in (product.get("fits_part_types") or []) if str(value)]
        family_ids = list(dict.fromkeys(
            family_id for part_type_id in fits
            for family_id in family_by_part_type.get(part_type_id, [])
        ))
        guided_kinds = list(dict.fromkeys(
            _GUIDED_FAMILIES[family_id]
            for family_id in family_ids if family_id in _GUIDED_FAMILIES
        ))
        model = str(product.get("model") or "").strip()
        if _TRACER_MODEL.search(model):
            guided_kinds.append("tracer")
        if str(product_id) in {"whelen_fst", "whelen_rst"}:
            guided_kinds.append("inner edge")
        if str(product_id) == "whelen_ion_rear_pillar":
            guided_kinds.append("outer edge")
        if (
            "roof_light_bar" in fits
            and not re.search(r"\b(mini|micro)\b|responder\s*lp", model, re.IGNORECASE)
        ):
            guided_kinds.append("lightbar")
        guided_kinds = list(dict.fromkeys(guided_kinds))
        primary_part_type_id = str(
            product.get("picker_primary_part_type")
            or product.get("global_search_part_type")
            or (fits[0] if fits else "")
        )
        primary_part_type = part_types.get(primary_part_type_id) or {}
        fixture_part_type_id = next((
            part_type_id for part_type_id in [primary_part_type_id, *fits]
            if _FIXTURE_PART_ALIASES.get(part_type_id, part_type_id) in fixture_catalog
            or bool(((part_types.get(part_type_id) or {}).get("render") or {}).get("is_fixture"))
        ), "")
        fixture_catalog_part = fixture_catalog.get(
            _FIXTURE_PART_ALIASES.get(fixture_part_type_id, fixture_part_type_id), {}
        )
        fixture_label = str(
            fixture_catalog_part.get("display_name")
            or (part_types.get(fixture_part_type_id) or {}).get("label")
            or ""
        ).strip()
        for sku in product.get("part_numbers") or []:
            if not isinstance(sku, dict):
                continue
            part_number = str(sku.get("part_number") or "").strip()
            accessory_category = str(product.get("accessory_category") or "").strip()
            if not accessory_category:
                accessory_category = next((
                    str((part_types.get(part_type_id) or {}).get("accessory_category") or "").strip()
                    for part_type_id in fits
                    if str((part_types.get(part_type_id) or {}).get("accessory_category") or "").strip()
                ), "")
            match = {
                "product_id": str(product_id),
                "model": model,
                "description": str(product.get("description") or "").strip(),
                "manufacturer_id": manufacturer_id,
                "manufacturer": manufacturer,
                "part_number": part_number,
                "friendly_name": str(sku.get("friendly_name") or "").strip(),
                "color": str(sku.get("color") or "").strip(),
                "secondary_color": str(sku.get("secondary_color") or "").strip(),
                "tertiary_color": str(sku.get("tertiary_color") or "").strip(),
                "lens_type": str(sku.get("lens_type") or "").strip(),
                "part_type_ids": fits,
                "primary_part_type_id": primary_part_type_id,
                "primary_part_type_label": str(
                    primary_part_type.get("label") or primary_part_type_id
                ).strip(),
                "family_ids": family_ids,
                "guided_kinds": guided_kinds,
                "accessory_category": accessory_category,
                "accessory_of_products": [
                    str(value) for value in (product.get("accessory_of_products") or [])
                    if str(value)
                ],
                "is_fixture": bool(fixture_part_type_id),
                "default_location": str(
                    fixture_catalog_part.get("default_location_key") or fixture_label
                ).strip(),
                "fixture_label": fixture_label,
                "fixture_name_pattern": str(
                    (part_types.get(fixture_part_type_id) or {}).get("workbook_label_pattern")
                    or fixture_label
                ).strip(),
                "fixture_base_label": str(
                    (part_types.get(fixture_part_type_id) or {}).get("label") or fixture_label
                ).strip(),
                "has_configured_accessories": bool(product.get("accessories")),
                "picker_location_allocation": bool(product.get("picker_location_allocation")),
                "fixed_location": str(
                    product.get("fixed_location")
                    or _IMPORT_FIXED_LOCATIONS.get(primary_part_type_id, "")
                ).strip(),
            }
            qb_item_id = str(sku.get("qb_item_id") or product.get("qb_item_id") or "").strip()
            if qb_item_id:
                by_qb_item_id[qb_item_id].append(match)
            if part_number:
                by_sku.setdefault(part_number.casefold(), match)

    return {
        "products": products,
        "part_types": part_types,
        "by_qb_item_id": by_qb_item_id,
        "by_sku": by_sku,
    }


def _line_values(raw: dict, index: int) -> dict:
    detail_type = str(raw.get("DetailType") or "").strip()
    detail = raw.get("SalesItemLineDetail") if isinstance(
        raw.get("SalesItemLineDetail"), dict
    ) else {}
    item_ref = detail.get("ItemRef") if isinstance(detail.get("ItemRef"), dict) else {}
    item_id = str(item_ref.get("value") or "").strip()
    item_name = str(item_ref.get("name") or "").strip()
    return {
        "source_index": index,
        "line_id": str(raw.get("Id") or index + 1),
        "detail_type": detail_type,
        "item_id": item_id,
        "item_name": item_name,
        "description": str(raw.get("Description") or "").strip(),
        "quantity": _number(detail.get("Qty")),
        "unit_price": _number(detail.get("UnitPrice")),
        "amount": _number(raw.get("Amount")),
    }


def _looks_like_non_part_charge(row: dict) -> bool:
    """Recognize common service lines even when QBO settings or spelling drift."""
    name = re.sub(r"[^a-z0-9]+", " ", str(row.get("item_name") or "").casefold()).strip()
    return bool(name and _NON_PART_ITEM_NAMES.fullmatch(name))


def _existing_draft_parent_rows(paths: AppPaths, draft_id: str, indexes: dict) -> list[dict]:
    if not draft_id:
        return []
    try:
        draft = load_draft_for_request(draft_id, paths)
    except (FileNotFoundError, ValueError):
        return []
    out = []
    for part in draft.parts:
        if part.parent_line_id:
            continue
        product_ids: list[str] = []
        match = indexes["by_sku"].get(str(part.part_number or "").strip().casefold())
        if match:
            product_ids.append(match["product_id"])
        for component in part.components or []:
            if not isinstance(component, dict):
                continue
            match = indexes["by_sku"].get(
                str(component.get("part_number") or "").strip().casefold()
            )
            if match:
                product_ids.append(match["product_id"])
        out.append({
            "line_id": str(part.line_id or ""),
            "name": str(part.name or part.part_number or "Manifest part"),
            "location": str(part.location or ""),
            "part_number": str(part.part_number or ""),
            "product_ids": list(dict.fromkeys(product_ids)),
        })
    return out


def _existing_import_line_ids(paths: AppPaths, draft_id: str, estimate_id: str) -> set[str]:
    if not draft_id:
        return set()
    try:
        draft = load_draft_for_request(draft_id, paths)
    except (FileNotFoundError, ValueError):
        return set()
    out: set[str] = set()
    records = list(draft.parts)
    for part in draft.parts:
        records.extend(component for component in (part.components or []) if isinstance(component, dict))
    for record in records:
        picker = record.get("picker_config") if isinstance(record, dict) else getattr(record, "picker_config", {})
        source = (picker or {}).get("qb_import") if isinstance(picker, dict) else None
        if not isinstance(source, dict):
            continue
        if str(source.get("estimate_id") or "") != estimate_id:
            continue
        line_id = str(source.get("line_id") or "").strip()
        if line_id:
            out.add(line_id)
        out.update(
            str(value).strip() for value in (source.get("related_line_ids") or [])
            if str(value).strip()
        )
    return out


def _draft_comparison_rows(
    paths: AppPaths, draft_id: str, indexes: dict,
) -> tuple[dict[str, int], dict[str, int], list[dict]]:
    """Return billable-style SKU totals and removable manifest rows.

    Picker parents frequently carry a display/model part number while their
    concrete orderable SKUs live in ``components``.  Match the Estimate the
    same way the outbound Estimate resolver does: components win when present.
    """
    if not draft_id:
        return {}, {}, []
    try:
        draft = load_draft_for_request(draft_id, paths)
    except (FileNotFoundError, ValueError):
        return {}, {}, []

    billable_totals: dict[str, int] = defaultdict(int)
    physical_totals: dict[str, int] = defaultdict(int)
    rows = []
    for part in draft.parts:
        components = [
            component for component in (part.components or [])
            if isinstance(component, dict) and str(component.get("part_number") or "").strip()
        ]
        sku_quantities: dict[str, int] = defaultdict(int)
        if components:
            for component in components:
                sku = str(component.get("part_number") or "").strip()
                try:
                    quantity = int(component.get("quantity") or 0)
                except (TypeError, ValueError):
                    quantity = 0
                sku_quantities[sku] += quantity if quantity > 0 else 1
        else:
            sku = str(part.part_number or "").strip()
            if sku:
                sku_quantities[sku] += part.quantity if part.quantity > 0 else 1
        for sku, quantity in sku_quantities.items():
            physical_totals[sku.casefold()] += quantity
            if supply_state(part).is_billable:
                billable_totals[sku.casefold()] += quantity

        product_ids = []
        part_type_ids = set([str(part.part_type or "").strip()])
        for sku in sku_quantities:
            match = indexes["by_sku"].get(sku.casefold())
            if not match:
                continue
            product_ids.append(match["product_id"])
            part_type_ids.update(match.get("part_type_ids") or [])
        part_type_ids.discard("")
        import_source = (part.picker_config or {}).get("qb_import")
        rows.append({
            "line_id": str(part.line_id or ""),
            "name": str(part.name or part.part_number or "Manifest part"),
            "location": str(part.location or ""),
            "part_number": str(part.part_number or ""),
            "quantity": part.quantity if part.quantity > 0 else 1,
            "skus": [
                {"part_number": sku, "quantity": quantity}
                for sku, quantity in sku_quantities.items()
            ],
            "product_ids": list(dict.fromkeys(product_ids)),
            "part_type_ids": sorted(part_type_ids),
            "parent_line_id": str(part.parent_line_id or ""),
            "is_billable": supply_state(part).is_billable,
            "supply_label": supply_state(part).label,
            "import_estimate_id": str((import_source or {}).get("estimate_id") or "")
            if isinstance(import_source, dict) else "",
        })
    return dict(billable_totals), dict(physical_totals), rows


def _accessory_parent_candidates(
    child: dict,
    *,
    available_product_ids: set[str],
    manifest_parent_rows: list[dict],
    indexes: dict,
) -> list[dict]:
    products = indexes["products"]
    part_types = indexes["part_types"]
    child_product_id = child["product_id"]
    scores: dict[str, tuple[int, str]] = {}

    for parent_id in child.get("accessory_of_products") or []:
        if parent_id in available_product_ids:
            scores[parent_id] = (300, "Exact product accessory relationship")

    for parent_id in available_product_ids:
        parent = products.get(parent_id) or {}
        for relationship in parent.get("accessories") or []:
            if str((relationship or {}).get("product_id") or "") == child_product_id:
                scores[parent_id] = max(
                    scores.get(parent_id, (0, "")),
                    (290, "Parent product explicitly includes this accessory"),
                )

    parent_type_ids = {
        str((part_types.get(part_type_id) or {}).get("accessory_of") or "")
        for part_type_id in child.get("part_type_ids") or []
    }
    parent_type_ids.discard("")
    if parent_type_ids:
        for parent_id in available_product_ids:
            parent = products.get(parent_id) or {}
            if parent_type_ids.intersection(parent.get("fits_part_types") or []):
                scores[parent_id] = max(
                    scores.get(parent_id, (0, "")),
                    (200, "Compatible part-type accessory relationship"),
                )

    result = []
    for product_id, (score, reason) in sorted(
        scores.items(), key=lambda item: (-item[1][0], item[0])
    ):
        product = products.get(product_id) or {}
        result.append({
            "product_id": product_id,
            "model": str(product.get("model") or product_id),
            "score": score,
            "reason": reason,
            "manifest_options": [
                row for row in manifest_parent_rows
                if product_id in row.get("product_ids", [])
            ],
        })
    return result


def _memo_sku_suggestions(memo: str, indexes: dict, quoted_item_ids: set[str]) -> list[dict]:
    if not memo.strip():
        return []
    suggestions = []
    folded = memo.casefold()
    for sku, match in sorted(indexes["by_sku"].items(), key=lambda item: -len(item[0])):
        if len(sku) < 3:
            continue
        start = 0
        found = False
        while True:
            start = folded.find(sku, start)
            if start < 0:
                break
            before = folded[start - 1] if start else " "
            after_pos = start + len(sku)
            after = folded[after_pos] if after_pos < len(folded) else " "
            if not before.isalnum() and not after.isalnum():
                found = True
                break
            start += len(sku)
        if not found:
            continue
        qb_ids = {
            item_id for item_id, matches in indexes["by_qb_item_id"].items()
            if any(candidate["product_id"] == match["product_id"]
                   and candidate["part_number"] == match["part_number"] for candidate in matches)
        }
        suggestions.append({
            **match,
            "also_quoted": bool(qb_ids.intersection(quoted_item_ids)),
        })
    return suggestions[:25]


def preview_estimate_import(
    paths: AppPaths,
    *,
    project_id: str,
    individual_id: str,
) -> dict:
    """Return a read-only, fully classified import plan for a linked Estimate."""
    try:
        project = project_entry.load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "unknown_project"}
    unit = next((
        individual
        for build in project.build_units
        for individual in build.individuals
        if individual.individual_id == individual_id
    ), None)
    if unit is None:
        return {"ok": False, "error": "unknown_individual"}
    estimate_id = str(unit.qb_estimate_id or "").strip()
    if not estimate_id:
        return {"ok": False, "error": "estimate_not_connected"}

    client, error = qb_sync_service._build_client(paths)
    if error:
        return error
    try:
        estimate = client.read_estimate(estimate_id)
    except QuickBooksApiError:
        return {"ok": False, "error": "estimate_lookup_failed"}
    if not estimate:
        return {"ok": False, "error": "existing_estimate_not_found"}

    doc = get_parts_db_service(paths).raw_doc()
    indexes = _catalog_indexes(doc, paths)
    charge_names = {
        str(value).strip().casefold()
        for value in (estimate_charges_service.load_settings(paths).get("service_items") or {}).values()
        if str(value).strip()
    }
    rows = [_line_values(raw, index) for index, raw in enumerate(estimate.get("Line") or [])
            if isinstance(raw, dict)]
    cached_items = qb_sync_service.get_cached_items(paths).get("items") or []
    cached_by_id = {
        str(item.get("qb_item_id") or "").strip(): item
        for item in cached_items if str(item.get("qb_item_id") or "").strip()
    }
    for row in rows:
        if not row["item_name"] and row["item_id"] in cached_by_id:
            row["item_name"] = str(cached_by_id[row["item_id"]].get("name") or "").strip()
    charge_item_ids = {
        item_id for item_id, item in cached_by_id.items()
        if str(item.get("name") or "").strip().casefold() in charge_names
    }
    quoted_product_ids: set[str] = set()
    quoted_item_ids = {row["item_id"] for row in rows if row["item_id"]}
    for row in rows:
        for match in indexes["by_qb_item_id"].get(row["item_id"], []):
            quoted_product_ids.add(match["product_id"])
    manifest_parent_rows = _existing_draft_parent_rows(
        paths, str(unit.draft_id or ""), indexes,
    )
    existing_product_ids = {
        product_id
        for row in manifest_parent_rows
        for product_id in row.get("product_ids", [])
    }
    imported_line_ids = _existing_import_line_ids(
        paths, str(unit.draft_id or ""), estimate_id,
    )
    draft_sku_totals, draft_physical_sku_totals, manifest_rows = _draft_comparison_rows(
        paths, str(unit.draft_id or ""), indexes,
    )
    available_product_ids = quoted_product_ids | existing_product_ids

    classified = []
    for row in rows:
        detail_type = row["detail_type"]
        description_folded = row["description"].casefold()
        if detail_type == "DescriptionOnly":
            classification = "pending_part" if any(
                marker in description_folded for marker in _PENDING_MARKERS
            ) else "section_header"
            classified.append({**row, "classification": classification, "ignored": classification == "section_header"})
            continue
        if detail_type != "SalesItemLineDetail":
            classified.append({**row, "classification": "calculated_or_unsupported", "ignored": True})
            continue
        if (
            row["item_name"].casefold() in charge_names
            or row["item_id"] in charge_item_ids
            or _looks_like_non_part_charge(row)
        ):
            classified.append({**row, "classification": "additional_charge", "ignored": True})
            continue
        matches = indexes["by_qb_item_id"].get(row["item_id"], [])
        if row["item_name"].casefold() == "misc part":
            classified.append({**row, "classification": "custom", "ignored": False})
            continue
        if not matches:
            classified.append({**row, "classification": "unknown_item", "ignored": False})
            continue

        candidates = []
        for match in matches:
            parent_candidates = _accessory_parent_candidates(
                match,
                available_product_ids=available_product_ids - {match["product_id"]},
                manifest_parent_rows=manifest_parent_rows,
                indexes=indexes,
            )
            is_accessory = bool(
                match.get("accessory_of_products")
                or match.get("accessory_category")
                or parent_candidates
                or any((indexes["part_types"].get(part_type_id) or {}).get("accessory_of")
                       for part_type_id in match.get("part_type_ids") or [])
            )
            candidates.append({
                **match,
                "is_accessory": is_accessory,
                "accessory_parent_candidates": parent_candidates,
            })
        guided_kinds = list(dict.fromkeys(
            kind for candidate in candidates for kind in candidate.get("guided_kinds") or []
        ))
        classification = "guided_system" if guided_kinds else (
            "accessory" if any(candidate["is_accessory"] for candidate in candidates)
            else "catalog_part"
        )
        classified.append({
            **row,
            "classification": classification,
            "ignored": False,
            "guided_kinds": guided_kinds,
            "catalog_matches": candidates,
            "ambiguous_match": len(candidates) > 1,
        })

    # One guided setup owns all quoted components in that system.  Mark the
    # primary line as the setup entry point and keep the remaining Estimate
    # lines visible but non-actionable so the user does not configure the same
    # hardware twice.
    for kind, primary_part_type in _GUIDED_PRIMARY_PART_TYPES.items():
        related = [
            row for row in classified
            if not row.get("ignored")
            and not row.get("covered_by_guided_line_id")
            and len(row.get("catalog_matches") or []) == 1
            and _GUIDED_COMPONENT_PART_TYPES[kind].intersection(
                (row.get("catalog_matches") or [{}])[0].get("part_type_ids") or []
            )
        ]
        primary = next((
            row for row in related
            if primary_part_type in row["catalog_matches"][0].get("part_type_ids", [])
        ), None)
        if not primary:
            continue
        primary["guided_estimate_components"] = [
            {
                "line_id": row["line_id"],
                "item_id": row["item_id"],
                "quantity": row["quantity"],
                "description": row["description"],
                "catalog_match": row["catalog_matches"][0],
            }
            for row in related
        ]
        for row in related:
            if row is primary:
                continue
            row["covered_by_guided_line_id"] = primary["line_id"]
            row["covered_by_guided_kind"] = kind

    memo = _text(estimate.get("CustomerMemo"))
    private_note = str(estimate.get("PrivateNote") or "").strip()
    combined_memo = "\n".join(value for value in (memo, private_note) if value)
    counts: dict[str, int] = defaultdict(int)
    for row in classified:
        row["already_imported"] = row["line_id"] in imported_line_ids
        counts[row["classification"]] += 1

    quoted_sku_totals: dict[str, int] = defaultdict(int)
    for row in classified:
        matches = row.get("catalog_matches") or []
        if row.get("ignored") or len(matches) != 1:
            continue
        match = matches[0]
        sku = str(match.get("part_number") or "").strip()
        quantity = row.get("quantity")
        if sku and isinstance(quantity, (int, float)) and quantity > 0:
            quoted_sku_totals[sku.casefold()] += int(quantity)

    quoted_skus = set(quoted_sku_totals)
    build_only_parts = []
    for row in manifest_rows:
        if (
            row["line_id"]
            and not row["parent_line_id"]
            and row["import_estimate_id"] != estimate_id
            and not any(str(sku["part_number"]).casefold() in quoted_skus for sku in row["skus"])
        ):
            build_only_parts.append({
                key: value for key, value in row.items() if key != "import_estimate_id"
            })
    build_only_by_type: dict[str, list[dict]] = defaultdict(list)
    for row in build_only_parts:
        for part_type_id in row.get("part_type_ids") or []:
            build_only_by_type[part_type_id].append(row)

    comparison_counts: dict[str, int] = defaultdict(int)
    for row in classified:
        matches = row.get("catalog_matches") or []
        comparison = {"status": "not_comparable"}
        if not row.get("ignored") and len(matches) == 1:
            match = matches[0]
            sku = str(match.get("part_number") or "").strip()
            estimate_quantity = quoted_sku_totals.get(sku.casefold(), 0)
            current_quantity = draft_sku_totals.get(sku.casefold(), 0)
            physical_quantity = draft_physical_sku_totals.get(sku.casefold(), 0)
            if current_quantity and current_quantity == estimate_quantity:
                status = "matched"
            elif current_quantity:
                status = "quantity_changed"
            elif physical_quantity:
                status = "supply_changed"
            else:
                status = "new"
            different_from = []
            if status == "new":
                seen = set()
                for part_type_id in match.get("part_type_ids") or []:
                    for candidate in build_only_by_type.get(part_type_id, []):
                        if candidate["line_id"] not in seen:
                            seen.add(candidate["line_id"])
                            different_from.append(candidate)
            comparison = {
                "status": status,
                "current_quantity": current_quantity,
                "physical_quantity": physical_quantity,
                "estimate_quantity": estimate_quantity,
                "matching_manifest_line_ids": [
                    manifest["line_id"] for manifest in manifest_rows
                    if any(
                        str(item["part_number"]).casefold() == sku.casefold()
                        for item in manifest.get("skus") or []
                    )
                ],
                "different_from": different_from,
            }
        row["comparison"] = comparison
        comparison_counts[comparison["status"]] += 1
    return {
        "ok": True,
        "estimate": {
            "id": estimate_id,
            "number": str(estimate.get("DocNumber") or "").strip(),
            "customer": _ref_name(estimate.get("CustomerRef")),
            "project_id": _text(estimate.get("ProjectRef")),
            "date": str(estimate.get("TxnDate") or "").strip(),
            "status": str(estimate.get("TxnStatus") or "").strip(),
            "last_modified": str((estimate.get("MetaData") or {}).get("LastUpdatedTime") or "")
            if isinstance(estimate.get("MetaData"), dict) else "",
            "customer_memo": memo,
            "private_note": private_note,
        },
        "draft_id": str(unit.draft_id or ""),
        "lines": classified,
        "counts": dict(counts),
        "manifest_parent_options": manifest_parent_rows,
        "manifest_accessory_rows": [
            {key: value for key, value in row.items() if key != "import_estimate_id"}
            for row in manifest_rows
            if row.get("parent_line_id")
        ],
        "build_is_blank": not bool(manifest_rows),
        "build_only_parts": build_only_parts,
        "comparison_counts": dict(comparison_counts),
        "memo_reuse_suggestions": _memo_sku_suggestions(combined_memo, indexes, quoted_item_ids),
        "can_start": bool(unit.draft_id) and any(
            not row.get("ignored") and not row.get("already_imported") for row in classified
        ),
    }
