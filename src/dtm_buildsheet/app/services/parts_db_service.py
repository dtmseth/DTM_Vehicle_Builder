"""parts_db.json read service (schema v2 — tree + intersection rules).

Tree-based hierarchy: Type → Section → Zone → (Sub-zone) → Part Type.
Products are flat-keyed; each declares `fits_part_types` for filtering.
Compatibility checking is intersection-based: a (part_type, product,
placement) triple is valid iff each entity's optional whitelist is
either empty or contains the others.

Three-tier fallback for name-keyed legacy queries (excel_reader,
manifest_editor dropdowns):

  1. parts_db.json + legacy_workbook_index.json (current source of truth)
  2. workbook_rules.json (deepest fallback, gone in Phase 4)

Singleton lifecycle: `get_parts_db_service(paths)`. Cache invalidates via
`config_service.save_config_file("parts_db.json", ...)`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

from ...config.store import load_config
from ...domain.parts_db_models import (
    BuildAttribute,
    Color,
    Manufacturer,
    PartNumber,
    PartType,
    Placement,
    PlacementZone,
    PreferenceFilter,
    Product,
    Section,
    Service,
    SubZone,
    Tag,
    TreePosition,
    Type,
    Zone,
)
from ...paths import AppPaths

logger = logging.getLogger(__name__)


def _empty_parts_db_doc() -> dict:
    return {
        "schema_version": 2,
        "metadata": {},
        "types": {},
        "sections": {},
        "zones": {},
        "sub_zones": {},
        "build_attributes": {},
        "tags": {},
        "manufacturers": {},
        "products": {},
        "part_types": {},
        "placements": {},
        "placement_zones": {},
        "services": {},
        "preference_filters": {},
        "color_palette": {},
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
    """Reader for legacy_workbook_index.json (string-keyed transition map)."""

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

    def product_ids_for_part_type_label(self, label: str) -> list[str]:
        return list((self._load().get("part_type_to_products") or {}).get(label) or [])

    def product_id_for_model_string(self, model: str) -> str | None:
        return (self._load().get("model_string_to_product") or {}).get(model)


class LegacyFallbackReader:
    """Last-resort fallback: read raw workbook_rules.part_rules."""

    def __init__(self, paths: AppPaths):
        self._paths = paths

    def reload(self) -> None:
        pass

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

    # ── Top-level taxonomies ──────────────────────────────────────────────

    def list_types(self) -> list[Type]:
        return [_hyd_type(tid, spec) for tid, spec in (self._load().get("types") or {}).items()]

    def list_sections(self) -> list[Section]:
        return [Section(section_id=sid, label=spec.get("label", sid))
                for sid, spec in (self._load().get("sections") or {}).items()]

    def list_zones(self, section: str | None = None) -> list[Zone]:
        out: list[Zone] = []
        for zid, spec in (self._load().get("zones") or {}).items():
            if section and spec.get("section") != section:
                continue
            out.append(_hyd_zone(zid, spec))
        return out

    def list_sub_zones(self, zone: str | None = None) -> list[SubZone]:
        out: list[SubZone] = []
        for sid, spec in (self._load().get("sub_zones") or {}).items():
            if zone and spec.get("zone") != zone:
                continue
            out.append(SubZone(sub_zone_id=sid,
                               label=spec.get("label", sid),
                               zone=spec.get("zone", ""),
                               requires_attribute=spec.get("requires_attribute", "")))
        return out

    def list_build_attributes(self) -> list[BuildAttribute]:
        return [BuildAttribute(attribute_id=aid, label=spec.get("label", aid),
                               default_by_build_type=dict(spec.get("default_by_build_type") or {}))
                for aid, spec in (self._load().get("build_attributes") or {}).items()]

    def list_tags(self) -> list[Tag]:
        return [Tag(tag_id=tid, label=spec.get("label", tid))
                for tid, spec in (self._load().get("tags") or {}).items()]

    def list_manufacturers(self) -> list[Manufacturer]:
        return [_hyd_manufacturer(mid, spec)
                for mid, spec in (self._load().get("manufacturers") or {}).items()]

    def list_colors(self) -> list[Color]:
        return [_hyd_color(cid, spec)
                for cid, spec in (self._load().get("color_palette") or {}).items()]

    def list_services(self) -> list[Service]:
        return [Service(service_id=sid, label=spec.get("label", sid))
                for sid, spec in (self._load().get("services") or {}).items()]

    def list_preference_filters(self) -> list[PreferenceFilter]:
        return [PreferenceFilter(filter_id=fid,
                                 preference_field=spec.get("preference_field", ""),
                                 filter_scope_kind=spec.get("filter_scope_kind", ""),
                                 filter_scope_values=list(spec.get("filter_scope_values") or []),
                                 filter_action=spec.get("filter_action", ""))
                for fid, spec in (self._load().get("preference_filters") or {}).items()]

    # ── Part types ────────────────────────────────────────────────────────

    def list_part_types(self) -> list[PartType]:
        return [_hyd_part_type(pid, spec)
                for pid, spec in (self._load().get("part_types") or {}).items()]

    def list_part_types_at(self, type_id: str | None = None, section: str | None = None,
                            zone: str | None = None, sub_zone: str | None = None) -> list[PartType]:
        """Return part_types whose tree_positions match the given filters.

        Any combination of filters can be set or left None. When all are None,
        returns every part_type.
        """
        out: list[PartType] = []
        for pid, spec in (self._load().get("part_types") or {}).items():
            if type_id and spec.get("type_id") != type_id:
                continue
            if section is None and zone is None and sub_zone is None:
                out.append(_hyd_part_type(pid, spec))
                continue
            for pos in spec.get("tree_positions") or []:
                if section is not None and pos.get("section") != section:
                    continue
                if zone is not None and pos.get("zone") != zone:
                    continue
                if sub_zone is not None and pos.get("sub_zone", "") != sub_zone:
                    continue
                out.append(_hyd_part_type(pid, spec))
                break
        return out

    def list_part_types_with_tag(self, tag_id: str) -> list[PartType]:
        return [_hyd_part_type(pid, spec)
                for pid, spec in (self._load().get("part_types") or {}).items()
                if tag_id in (spec.get("tag_ids") or [])]

    def list_accessories_of(self, parent_part_type_id: str) -> list[PartType]:
        return [_hyd_part_type(pid, spec)
                for pid, spec in (self._load().get("part_types") or {}).items()
                if spec.get("accessory_of") == parent_part_type_id]

    def get_part_type(self, part_type_id: str) -> Optional[PartType]:
        spec = (self._load().get("part_types") or {}).get(part_type_id)
        if not spec:
            return None
        return _hyd_part_type(part_type_id, spec)

    # ── Products ──────────────────────────────────────────────────────────

    def list_products(self) -> list[Product]:
        return [_hyd_product(pid, spec)
                for pid, spec in (self._load().get("products") or {}).items()]

    def list_products_for_part_type(self, part_type_id: str) -> list[Product]:
        """Products whose fits_part_types includes the given part_type, intersected
        with the part_type's allowed_products whitelist (if any)."""
        doc = self._load()
        pt = (doc.get("part_types") or {}).get(part_type_id) or {}
        allowed = pt.get("allowed_products") or []
        out: list[Product] = []
        for pid, spec in (doc.get("products") or {}).items():
            if part_type_id not in (spec.get("fits_part_types") or []):
                continue
            if allowed and pid not in allowed:
                continue
            out.append(_hyd_product(pid, spec))
        return out

    def list_products_with_tag(self, tag_id: str) -> list[Product]:
        return [_hyd_product(pid, spec)
                for pid, spec in (self._load().get("products") or {}).items()
                if tag_id in (spec.get("tag_ids") or [])]

    def get_product(self, product_id: str) -> Optional[Product]:
        spec = (self._load().get("products") or {}).get(product_id)
        if not spec:
            return None
        return _hyd_product(product_id, spec)

    def list_part_numbers(self, product_id: str) -> list[PartNumber]:
        spec = (self._load().get("products") or {}).get(product_id) or {}
        return [_hyd_part_number(pn) for pn in (spec.get("part_numbers") or [])]

    # ── Placements ────────────────────────────────────────────────────────

    def get_placement(self, location_id: str) -> Placement:
        spec = (self._load().get("placements") or {}).get(location_id) or {}
        return Placement(location_id=location_id,
                          placement_zone=spec.get("placement_zone", ""),
                          allowed_products=list(spec.get("allowed_products") or []))

    def list_placement_zones(self) -> list[PlacementZone]:
        return [PlacementZone(placement_zone_id=zid, label=spec.get("label", zid))
                for zid, spec in (self._load().get("placement_zones") or {}).items()]

    # ── Compatibility validation (the single intersection rule) ──────────

    def validate_placement(self, part_type_id: str, product_id: str,
                            location_id: str) -> dict:
        """Apply the intersection rule. Returns {valid: bool, reason: str}."""
        doc = self._load()
        pt = (doc.get("part_types") or {}).get(part_type_id)
        product = (doc.get("products") or {}).get(product_id)
        placement = (doc.get("placements") or {}).get(location_id) or {}

        if pt is None:
            return {"valid": False, "reason": f"Unknown part_type: {part_type_id}"}
        if product is None:
            return {"valid": False, "reason": f"Unknown product: {product_id}"}

        pt_allowed_products = pt.get("allowed_products") or []
        pt_allowed_placements = pt.get("allowed_placements") or []
        product_fits = product.get("fits_part_types") or []
        placement_allowed_products = placement.get("allowed_products") or []

        if pt_allowed_products and product_id not in pt_allowed_products:
            return {"valid": False,
                    "reason": f"Product {product_id} not in part_type's allowed_products"}
        if pt_allowed_placements and location_id not in pt_allowed_placements:
            return {"valid": False,
                    "reason": f"Location {location_id} not in part_type's allowed_placements"}
        if product_fits and part_type_id not in product_fits:
            return {"valid": False,
                    "reason": f"Part type {part_type_id} not in product's fits_part_types"}
        if placement_allowed_products and product_id not in placement_allowed_products:
            return {"valid": False,
                    "reason": f"Product {product_id} not allowed at placement {location_id}"}

        return {"valid": True, "reason": ""}

    # ── Legacy compatibility shims (3-tier) ──────────────────────────────

    def products_for_legacy_part_type_label(self, label: str) -> list[Product]:
        product_ids = self._legacy_index.product_ids_for_part_type_label(label)
        doc = self._load()
        products_doc = doc.get("products") or {}
        return [_hyd_product(pid, products_doc[pid])
                for pid in product_ids if pid in products_doc]

    def product_for_legacy_model_string(self, model: str) -> Optional[Product]:
        pid = self._legacy_index.product_id_for_model_string(model)
        if not pid:
            return None
        spec = (self._load().get("products") or {}).get(pid)
        if not spec:
            return None
        return _hyd_product(pid, spec)

    def manufacturers_by_legacy_name(self, label: str) -> list[str]:
        products = self.products_for_legacy_part_type_label(label)
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
        products = self.products_for_legacy_part_type_label(label)
        if products:
            seen: list[str] = []
            for p in products:
                if p.model and p.model not in seen:
                    seen.append(p.model)
            if seen:
                return seen
        return self._fallback.models(label)

    def locations_by_legacy_name(self, label: str) -> list[str]:
        return self._fallback.locations(label)


# ── Hydration helpers ────────────────────────────────────────────────────────


def _hyd_type(tid: str, spec: dict) -> Type:
    return Type(type_id=tid, label=spec.get("label", tid),
                requires_attribute=spec.get("requires_attribute", ""))


def _hyd_zone(zid: str, spec: dict) -> Zone:
    return Zone(zone_id=zid, label=spec.get("label", zid),
                section=spec.get("section", ""),
                requires_attribute=spec.get("requires_attribute", ""))


def _hyd_manufacturer(mid: str, spec: dict) -> Manufacturer:
    return Manufacturer(manufacturer_id=mid, label=spec.get("label", mid),
                         website=spec.get("website", ""))


def _hyd_part_number(spec: dict) -> PartNumber:
    return PartNumber(part_number=spec.get("part_number", ""),
                       friendly_name=spec.get("friendly_name", ""),
                       options=dict(spec.get("options") or {}),
                       qty_on_hand=spec.get("qty_on_hand"),
                       price_usd=spec.get("price_usd"),
                       color=spec.get("color", ""),
                       secondary_color=spec.get("secondary_color", ""),
                       tertiary_color=spec.get("tertiary_color", ""),
                       lens_type=spec.get("lens_type", ""),
                       qb_item_id=str(spec.get("qb_item_id", "")),
                       qb_sku=str(spec.get("qb_sku", "")),
                       qb_unit_price=spec.get("qb_unit_price"),
                       qb_inactive=bool(spec.get("qb_inactive", False)),
                       qb_pending=bool(spec.get("qb_pending", False)),
                       vehicle_tags=list(spec.get("vehicle_tags") or []))


def _hyd_product(pid: str, spec: dict) -> Product:
    return Product(product_id=pid,
                    manufacturer_id=spec.get("manufacturer_id", ""),
                    model=spec.get("model", ""),
                    fits_part_types=list(spec.get("fits_part_types") or []),
                    tag_ids=list(spec.get("tag_ids") or []),
                    description=spec.get("description", ""),
                    images=dict(spec.get("images") or {}),
                    part_numbers=[_hyd_part_number(pn) for pn in (spec.get("part_numbers") or [])])


def _hyd_part_type(pid: str, spec: dict) -> PartType:
    tree_positions = [
        TreePosition(section=p.get("section", ""),
                     zone=p.get("zone", ""),
                     sub_zone=p.get("sub_zone", ""))
        for p in (spec.get("tree_positions") or [])
    ]
    return PartType(
        part_type_id=pid,
        label=spec.get("label", pid),
        type_id=spec.get("type_id", ""),
        category=spec.get("category", ""),
        tree_positions=tree_positions,
        tag_ids=list(spec.get("tag_ids") or []),
        max_count=spec.get("max_count"),
        accessory_of=spec.get("accessory_of", ""),
        accessories=list(spec.get("accessories") or []),
        allowed_products=list(spec.get("allowed_products") or []),
        allowed_placements=list(spec.get("allowed_placements") or []),
        workbook_label_pattern=spec.get("workbook_label_pattern", "{label}"),
        sequence_scope=spec.get("sequence_scope", "global"),
        render=dict(spec.get("render") or {}),
    )


def _hyd_color(cid: str, spec: dict) -> Color:
    return Color(color_id=cid, label=spec.get("label", cid),
                  hex=spec.get("hex", ""),
                  naming_token=spec.get("naming_token", ""))


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
