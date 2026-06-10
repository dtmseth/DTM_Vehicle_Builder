"""parts_db.json read service (Phase 3, revised schema).

Manufacturer-centric hierarchy: Category → Manufacturer → Product → PartNumber.
See docs/ROADMAP.md §Phase 3 and the quiet-vaulting-quail plan file for the
schema rationale.

Three-tier fallback for name-keyed lookups (the manifest editor's dropdowns
during the dual-read transition):

  1. parts_db.json  — the canonical answer once the migration has run
  2. legacy_workbook_index.json — transition layer mapping old workbook
     part-type strings to product_ids (populated by PR-2b migration)
  3. workbook_rules.json — last-resort fallback, gone in Phase 4

Lifecycle:
- Process-wide singleton via `get_parts_db_service(paths)`.
- Cache invalidated by `config_service.save_config_file("parts_db.json", ...)`
  (and the sibling `legacy_workbook_index.json` save).
"""

from __future__ import annotations

import logging
from typing import Optional

from ...config.store import load_config
from ...domain.parts_db_models import (
    Category,
    Color,
    Manufacturer,
    OptionAxis,
    PartNumber,
    PartType,
    Product,
    Zone,
)
from ...paths import AppPaths

logger = logging.getLogger(__name__)


def _empty_parts_db_doc() -> dict:
    return {
        "schema_version": 1,
        "metadata": {},
        "categories": {},
        "manufacturers": {},
        "products": {},
        "option_axes_catalog": {},
        "color_palette": {},
        "location_zones": {},
        "location_zone_map": {},
        "part_types": {},
        "naming_rules": {},
    }


def _empty_legacy_index_doc() -> dict:
    return {
        "schema_version": 1,
        "part_type_to_products": {},
        "model_string_to_product": {},
    }


# ── Legacy fallback readers ───────────────────────────────────────────────────


class LegacyWorkbookIndex:
    """Reader for legacy_workbook_index.json.

    Bridges the gap between today's workbook string-keyed lookups and the
    new product-id-keyed parts_db. The file lives at
    workspace/config/legacy_workbook_index.json and is populated by the
    PR-2b migration script. Until then, missing-file is treated as
    empty maps (everything falls through to LegacyFallbackReader).
    """

    def __init__(self, paths: AppPaths):
        self._paths = paths
        self._cache: dict | None = None

    def _load(self) -> dict:
        if self._cache is None:
            try:
                self._cache = load_config("legacy_workbook_index.json", self._paths)
            except FileNotFoundError:
                self._cache = _empty_legacy_index_doc()
            except Exception:
                logger.exception("Could not load legacy_workbook_index.json; using empty")
                self._cache = _empty_legacy_index_doc()
        return self._cache

    def reload(self) -> None:
        self._cache = None

    def product_ids_for_part_type(self, label: str) -> list[str]:
        return list(
            (self._load().get("part_type_to_products") or {}).get(label) or []
        )

    def product_id_for_model_string(self, model: str) -> str | None:
        return (self._load().get("model_string_to_product") or {}).get(model)


class LegacyFallbackReader:
    """Last-resort fallback: read raw workbook_rules.part_rules.

    Used only when parts_db.json and legacy_workbook_index.json both have
    nothing for a given query. Phase 4 deletes this class along with the
    workbook_rules domain fields it reads.
    """

    def __init__(self, paths: AppPaths):
        self._paths = paths

    def reload(self) -> None:
        pass  # no cache

    def _workbook_rule(self, legacy_name: str) -> dict:
        wb = load_config("workbook_rules.json", self._paths)
        rules = wb.get("part_rules") or {}
        if legacy_name in rules:
            return rules[legacy_name]
        target = legacy_name.strip().upper()
        for key, rule in rules.items():
            if key.strip().upper() == target:
                return rule
        return {}

    def manufacturers(self, legacy_name: str) -> list[str]:
        return list(self._workbook_rule(legacy_name).get("manufacturer") or [])

    def models(self, legacy_name: str) -> list[str]:
        return list(self._workbook_rule(legacy_name).get("models") or [])

    def locations(self, legacy_name: str) -> list[str]:
        return list(self._workbook_rule(legacy_name).get("locations") or [])


# ── Service ──────────────────────────────────────────────────────────────────


class PartsDbService:
    def __init__(self, paths: AppPaths):
        self._paths = paths
        self._cache: dict | None = None
        self._legacy_index = LegacyWorkbookIndex(paths)
        self._fallback = LegacyFallbackReader(paths)

    # ── Loading ────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._cache is None:
            try:
                self._cache = load_config("parts_db.json", self._paths)
            except FileNotFoundError:
                self._cache = _empty_parts_db_doc()
            except Exception:
                logger.exception("Could not load parts_db.json; using empty")
                self._cache = _empty_parts_db_doc()
        return self._cache

    def invalidate(self) -> None:
        self._cache = None
        self._legacy_index.reload()
        self._fallback.reload()

    def raw_doc(self) -> dict:
        return self._load()

    def raw_legacy_index(self) -> dict:
        return self._legacy_index._load()

    # ── Primary typed queries ──────────────────────────────────────────────

    def list_categories(self) -> list[Category]:
        return [
            _hydrate_category(cid, spec)
            for cid, spec in (self._load().get("categories") or {}).items()
        ]

    def list_manufacturers_in_category(self, category_id: str) -> list[Manufacturer]:
        doc = self._load()
        mfgs_doc = doc.get("manufacturers") or {}
        seen: list[str] = []
        for product in (doc.get("products") or {}).values():
            if product.get("category_id") != category_id:
                continue
            mfg_id = product.get("manufacturer_id", "")
            if mfg_id and mfg_id not in seen:
                seen.append(mfg_id)
        return [
            _hydrate_manufacturer(mid, mfgs_doc[mid])
            for mid in seen
            if mid in mfgs_doc
        ]

    def list_products(self) -> list[Product]:
        doc = self._load()
        return [
            _hydrate_product(pid, spec)
            for pid, spec in (doc.get("products") or {}).items()
        ]

    def list_products_by_category(self, category_id: str) -> list[Product]:
        doc = self._load()
        return [
            _hydrate_product(pid, spec)
            for pid, spec in (doc.get("products") or {}).items()
            if spec.get("category_id") == category_id
        ]

    def list_products_by_manufacturer(self, manufacturer_id: str) -> list[Product]:
        doc = self._load()
        return [
            _hydrate_product(pid, spec)
            for pid, spec in (doc.get("products") or {}).items()
            if spec.get("manufacturer_id") == manufacturer_id
        ]

    def get_product(self, product_id: str) -> Optional[Product]:
        spec = (self._load().get("products") or {}).get(product_id)
        if not spec:
            return None
        return _hydrate_product(product_id, spec)

    def list_part_numbers(self, product_id: str) -> list[PartNumber]:
        spec = (self._load().get("products") or {}).get(product_id) or {}
        return [_hydrate_part_number(pn) for pn in (spec.get("part_numbers") or [])]

    def list_option_axes(self, product_id: str) -> dict[str, OptionAxis]:
        spec = (self._load().get("products") or {}).get(product_id) or {}
        return {
            name: _hydrate_option_axis(name, axis)
            for name, axis in (spec.get("option_axes") or {}).items()
        }

    # ── Compatibility queries ──────────────────────────────────────────────

    def zones_for_category(self, category_id: str) -> list[str]:
        cat = (self._load().get("categories") or {}).get(category_id) or {}
        return list(cat.get("applies_to_zones") or [])

    def products_compatible_with_zone(self, zone_id: str) -> list[Product]:
        doc = self._load()
        compatible_cats = {
            cid
            for cid, spec in (doc.get("categories") or {}).items()
            if zone_id in (spec.get("applies_to_zones") or [])
        }
        return [
            _hydrate_product(pid, spec)
            for pid, spec in (doc.get("products") or {}).items()
            if spec.get("category_id") in compatible_cats
        ]

    def brackets_for_product(self, product_id: str) -> list[Product]:
        doc = self._load()
        out: list[Product] = []
        for pid, spec in (doc.get("products") or {}).items():
            if spec.get("category_id") != "brackets":
                continue
            if product_id in (spec.get("compatible_with_products") or []):
                out.append(_hydrate_product(pid, spec))
        return out

    def list_colors(self) -> list[Color]:
        return [
            _hydrate_color(cid, spec)
            for cid, spec in (self._load().get("color_palette") or {}).items()
        ]

    # ── Compat shims (three-tier fallback) ────────────────────────────────

    def products_for_legacy_part_type(self, label: str) -> list[Product]:
        product_ids = self._legacy_index.product_ids_for_part_type(label)
        doc = self._load()
        products_doc = doc.get("products") or {}
        return [
            _hydrate_product(pid, products_doc[pid])
            for pid in product_ids
            if pid in products_doc
        ]

    def product_for_legacy_model_string(self, model: str) -> Optional[Product]:
        pid = self._legacy_index.product_id_for_model_string(model)
        if not pid:
            return None
        spec = (self._load().get("products") or {}).get(pid)
        if not spec:
            return None
        return _hydrate_product(pid, spec)

    def manufacturers_by_legacy_name(self, label: str) -> list[str]:
        """Used by manifest_editor's manufacturer dropdown for a workbook part-type.

        Tier 1: parts_db via legacy_workbook_index.
        Tier 2: workbook_rules.part_rules.
        """
        products = self.products_for_legacy_part_type(label)
        if products:
            doc = self._load()
            mfgs = doc.get("manufacturers") or {}
            seen: list[str] = []
            for p in products:
                if p.manufacturer_id and p.manufacturer_id in mfgs:
                    lbl = mfgs[p.manufacturer_id].get("label", p.manufacturer_id)
                    if lbl not in seen:
                        seen.append(lbl)
            if seen:
                return seen
        return self._fallback.manufacturers(label)

    def models_by_legacy_name(self, label: str) -> list[str]:
        products = self.products_for_legacy_part_type(label)
        if products:
            seen: list[str] = []
            for p in products:
                if p.model and p.model not in seen:
                    seen.append(p.model)
            if seen:
                return seen
        return self._fallback.models(label)

    def locations_by_legacy_name(self, label: str) -> list[str]:
        """Locations aren't on products in the new schema — they're a vehicle
        geometry concern. For the legacy compat shim, return the union of
        location keys whose zone is in any compatible category's applies_to_zones.

        If the parts_db has no products for this label, fall back to the
        raw workbook_rules.part_rules[label].locations list.
        """
        doc = self._load()
        products = self.products_for_legacy_part_type(label)
        if products:
            categories = doc.get("categories") or {}
            location_zone_map = doc.get("location_zone_map") or {}
            allowed_zones: set[str] = set()
            for p in products:
                allowed_zones.update(
                    (categories.get(p.category_id) or {}).get("applies_to_zones") or []
                )
            if allowed_zones:
                return [
                    loc_id
                    for loc_id, zone in location_zone_map.items()
                    if zone in allowed_zones
                ]
        return self._fallback.locations(label)


# ── Hydration helpers ────────────────────────────────────────────────────────


def _hydrate_category(cid: str, spec: dict) -> Category:
    return Category(
        category_id=cid,
        label=spec.get("label", cid),
        applies_to_zones=list(spec.get("applies_to_zones") or []),
    )


def _hydrate_manufacturer(mid: str, spec: dict) -> Manufacturer:
    return Manufacturer(
        manufacturer_id=mid,
        label=spec.get("label", mid),
        website=spec.get("website", ""),
    )


def _hydrate_option_axis(name: str, spec: dict) -> OptionAxis:
    return OptionAxis(
        name=name,
        type=spec.get("type", ""),
        axis_id=spec.get("axis_id", ""),
        allowed=list(spec.get("allowed") or []),
        min=spec.get("min"),
        max=spec.get("max"),
    )


def _hydrate_part_number(spec: dict) -> PartNumber:
    return PartNumber(
        part_number=spec.get("part_number", ""),
        friendly_name=spec.get("friendly_name", ""),
        options=dict(spec.get("options") or {}),
        qty_on_hand=spec.get("qty_on_hand"),
        price_usd=spec.get("price_usd"),
    )


def _hydrate_product(pid: str, spec: dict) -> Product:
    return Product(
        product_id=pid,
        manufacturer_id=spec.get("manufacturer_id", ""),
        category_id=spec.get("category_id", ""),
        model=spec.get("model", ""),
        description=spec.get("description", ""),
        images=dict(spec.get("images") or {}),
        option_axes={
            name: _hydrate_option_axis(name, axis)
            for name, axis in (spec.get("option_axes") or {}).items()
        },
        part_numbers=[_hydrate_part_number(pn) for pn in (spec.get("part_numbers") or [])],
        compatible_with_products=list(spec.get("compatible_with_products") or []),
    )


def _hydrate_color(cid: str, spec: dict) -> Color:
    return Color(
        color_id=cid,
        label=spec.get("label", cid),
        hex=spec.get("hex", ""),
        naming_token=spec.get("naming_token", ""),
    )


# ── Singleton ────────────────────────────────────────────────────────────────


_instance: PartsDbService | None = None


def get_parts_db_service(paths: AppPaths) -> PartsDbService:
    global _instance
    if _instance is None or _instance._paths is not paths:
        _instance = PartsDbService(paths)
    return _instance


def reset_for_testing() -> None:
    global _instance
    _instance = None
