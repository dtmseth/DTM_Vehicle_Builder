from __future__ import annotations

import logging
import re as _re
from pathlib import Path

from ..config_loader import ConfigBundle
from ..config.loader import model_lookup_keys
from ..domain import BuildPlan, PartInput, PlannedPart, PlannedPlacement, RenderInstance, slot_roles
from ..domain.geometry import view_side_role
from ..domain.rules import RuleSeverity
from ..domain.supply import normalized_supply_fields
from ..naming import canonical_name
from ..rules.engine import run_rules
from .asset_resolver import resolve_asset_path, size_class_for_part
from .color_resolver import resolve_color_token, resolve_custom_head_color_token, resolve_profile
from .fixture_resolver import resolve_fixture_entry
from .layer_policy import enforced_render_layer
from .location_resolver import (
    apply_co_part_rules,
    custom_location_has_no_render_placement,
    custom_location_points,
    resolve_normal_location,
    resolved_location_key,
)
from .quantity_resolver import apply_quantity_rules, apply_quantity_rules_list

_log = logging.getLogger(__name__)


_SUPPRESS_QTY_MISMATCH_LOCATIONS: frozenset[str] = frozenset({
    "TOP OF PUSH BUMPER",
    "UNDER PUSH BUMPER",
    "TOP TUBE",
})

# Category → render_kind mapping for synthesized specs (parts not in
# the legacy catalog but resolvable by part_type).
_CATEGORY_RENDER_KIND: dict[str, str] = {
    "warning":      "light",
    "scene":        "light",
    "interior":     "light",
    "interior_bar": "bar",
    "roof_bar":     "bar",
    "spotlight":    "light",
}

# Tracer housing SKUs render as their fixed lamp-row shape (tracer_Nlamp:
# group_shapes, slot_count = lamp count). The legacy catalog remaps "<N>-LAMP
# TRACER" model strings, but picker-created parts resolve through a synthesized
# spec with no model_remaps, so map the parts_db housing SKUs here too.
_TRACER_RENDER_BY_SKU: dict[str, str] = {
    "TCRWX2": "tracer_2lamp",
    "TCRWX3": "tracer_3lamp",
    "TCRWX5": "tracer_5lamp",
    "TCRWX6": "tracer_6lamp",
}

# Bar part_types → their bar_assets key (the synthesized spec otherwise uses the
# part_type_id, which has no bar_assets entry → blank render).
_BAR_ASSET_KEY: dict[str, str] = {
    "roof_light_bar": "roof",
    "front_interior_light_bar": "interior-front",
    "rear_interior_light_bar": "interior-rear",
}

# Interior bars are shown only in their windshield-facing vehicle view.  The
# top view is reserved for exterior equipment and makes windshield bars look
# like they are mounted on the roof.
_INTERIOR_LIGHT_BAR_PART_TYPES = frozenset({
    "front_interior_light_bar",
    "rear_interior_light_bar",
})
_INTERIOR_LIGHT_BAR_ASSET_KEYS = frozenset({"interior-front", "interior-rear"})

# The parts_db uses readable physical type ids while the vehicle fixture map
# retains two legacy catalog ids.  Picker-created Inner Edges must use the
# fixture locations, but render as individual ION-size lights rather than the
# generic bar image.
_INNER_EDGE_FIXTURE_BY_TYPE: dict[str, str] = {
    "front_interior_light_bar": "interior_light_bar_front",
    "rear_interior_light_bar": "rear_interior_light_bar",
}

# Inner Edge modules use the same artwork as ION heads, but a normal ION is
# too wide when a full FST/RST row is rendered.  Keep the normal head height
# while narrowing the artwork so each module remains distinct and inside the
# windshield/vehicle bounds.
_INNER_EDGE_SIZE_PER_VIEW: dict[str, dict[str, float]] = {
    "front": {"w": 0.31, "h": 0.114},
    "rear": {"w": 0.31, "h": 0.114},
    "top": {"w": 0.17, "h": 0.045},
}

# Outer Edge is a fixed rear-pillar assembly, not six independently placed
# warning heads.  Its two three-head columns use the normal PILLARS anchors
# and mirror their inward angle around the vehicle centerline.
_OUTER_EDGE_PILLAR_PRODUCT_ID = "whelen_ion_rear_pillar"
_OUTER_EDGE_HEAD_COUNT = 6
_OUTER_EDGE_VERTICAL_SPACING = 0.045
_OUTER_EDGE_PILLAR_ROTATION = -55.0


_WARNING_BASE_NAMES = {
    "forward warning", "side warning", "rear warning", "front side warning",
    "mirror warning", "pit bar warning", "lower lift gate warning", "warning",
}
_NUMBERED_SIREN_SLOT_INDEX = {"SIREN SPEAKER 1": 0, "SIREN SPEAKER 2": 1}


def _concealed_mount(part, location_key: str) -> tuple[str, str]:
    """Return normalized hidden-mount metadata for a siren speaker."""
    if getattr(part, "part_type", "") != "siren_speaker":
        return "", ""
    key = canonical_name(location_key).strip().upper()
    if "BEHIND GRILL" in key or "BEHIND GRILLE" in key:
        return "behind_grille", "BEHIND GRILLE"
    if "BEHIND OEM BUMPER" in key:
        return "behind_oem_bumper", "BEHIND OEM BUMPER"
    return "", ""
_SETINA_PB450L_PREFIX_COUNTS: dict[str, int] = {
    # Setina PB450L lighted bumper SKU families. The friendly names in
    # parts_db are authoritative where available; these keep legacy imports
    # and future compatible SKUs rendering without extra draft rows.
    "BK2017": 2,
    "BK2166": 2,
    "BK2124": 2,
    "BK2019": 4,
    "BK2168": 4,
    "BK0802": 4,
    "BK1001": 6,
    "BK2338": 6,
    "BK0282": 6,
}


def _find_part_type_by_name(name: str, svc) -> tuple[object | None, str]:
    """Match a part name like 'Forward Warning 3' to its part_type.

    Returns (part_type, base_name_without_number).  part_type is None
    when no match is found.  The service must provide list_part_types().
    """
    base = _re.sub(r"\s+\d+$", "", name).strip()
    if not base:
        return None, name
    for pt in svc.list_part_types():
        if (pt.label or "").strip().lower() == base.lower():
            return pt, base
    # Fallback: try matching against the label with the trailing pattern
    # stripped (some labels carry `{n}`).
    for pt in svc.list_part_types():
        label = (pt.label or "").strip()
        label_base = _re.sub(r"\s+\{n\}$", "", label).strip()
        if label_base.lower() == base.lower():
            return pt, base
    # Picker-created lines carry a line_id, so they resolve through parts_db
    # instead of the legacy catalog. Some part types intentionally author a
    # legacy/workbook display name that differs from the picker label
    # (Preemption → Opticom); allow those names to resolve to the part_type too.
    for pt in svc.list_part_types():
        pattern = (getattr(pt, "workbook_label_pattern", "") or "").strip()
        if "{" in pattern:
            pattern = _re.sub(r"\s+\{n\}$", "", pattern).strip()
        if pattern and pattern.lower() == base.lower():
            return pt, base
    # Warning lights collapsed to one home: every zone/legacy warning name
    # (Forward/Side/Rear/Front Side/Mirror/Pit Bar/Lower Lift Gate Warning)
    # resolves to `warning_light`; the name itself carries the friendly zone.
    if base.lower() in _WARNING_BASE_NAMES:
        for pt in svc.list_part_types():
            if pt.part_type_id == "warning_light":
                return pt, base
    return None, name


def _synthesize_spec(pt, location_key: str) -> dict:
    """Build a render spec from a part_type for the planner.

    The spec is a dict with the keys the planner's existing code paths
    expect: part_id, display_name, category, render_kind, default_views,
    asset_key, is_fixture, render_quantity_policy, etc.

    render_kind is derived from the part_type's *category*, not from the
    legacy catalog.  default_views is set to an empty list here — the
    planner will resolve views from the location's coordinates instead.
    """
    cat = (pt.category or "").lower()
    render_kind = _CATEGORY_RENDER_KIND.get(cat, "equipment")
    # Bars draw from bar_assets keyed by asset_key, which differs from the
    # part_type_id (e.g. roof_light_bar → "roof"); without this the synthesized
    # spec resolves no bar asset and the bar renders blank.
    render = dict(getattr(pt, "render", {}) or {})
    asset_key = render.get("asset_key") or _BAR_ASSET_KEY.get(pt.part_type_id, pt.part_type_id)
    return {
        "part_id":                  pt.part_type_id,
        "display_name":             pt.label,
        "category":                 pt.category or cat,
        "render_kind":              render_kind,
        # Most picker-built parts resolve their views from a chosen location.
        # Physical fixtures instead own their coordinates in vehicle_layouts;
        # preserve that distinction when the part type provides it.
        "default_views":            list(render.get("default_views") or []),
        "asset_key":                asset_key,
        "is_fixture":               bool(render.get("is_fixture", False)),
        "render_quantity_policy":   render.get("render_quantity_policy", "location_slots"),
        "default_color_profile":    render.get("default_color_profile", ""),
        # A parts-db-owned profile is the canonical size source. Product/SKU
        # assignments are resolved below and override this part-type default.
        "size_rule_id":             render.get("size_rule_id", ""),
        "accessory_of":             getattr(pt, "accessory_of", None),
        "group_shapes":             False,
        # Empty containers for code paths that iterate these unconditionally.
        "model_remaps":             {},
        "co_part_rules":            list(render.get("co_part_rules") or []),
        "location_asset_rules":     {},
        "size_per_view":            dict(render.get("size_per_view") or {}),
        "quantity_rules":           list(render.get("quantity_rules") or []),
        "images":                   dict(render.get("images") or {}),
        "_parts_db_render":          True,
    }


def _part_number_candidates(part: PartInput) -> list[str]:
    candidates: list[str] = []
    if part.part_number:
        candidates.append(part.part_number)
    for component in getattr(part, "components", []) or []:
        if isinstance(component, dict) and component.get("part_number"):
            candidates.append(str(component["part_number"]))
    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        sku = candidate.strip().upper()
        if sku and sku not in seen:
            seen.add(sku)
            out.append(sku)
    return out


def _setina_lighted_bumper_count(part: PartInput, svc) -> tuple[int, str]:
    manufacturer = (part.manufacturer or "").strip().lower()
    part_numbers = _part_number_candidates(part)
    if not part_numbers:
        return 0, ""
    if manufacturer and "setina" not in manufacturer:
        return 0, ""

    try:
        product = svc.get_product("setina_pb450l")
        for pn in getattr(product, "part_numbers", []) or []:
            matched_sku = (pn.part_number or "").strip().upper()
            if matched_sku not in part_numbers:
                continue
            text = f"{getattr(product, 'model', '')} {pn.friendly_name or ''}".upper()
            match = _re.search(r"\bPB450L([246])\b", text)
            if match:
                return int(match.group(1)), matched_sku
            match = _re.search(r"\b([246])\s+(?:TOTAL\s+)?LIGHTS?\b", text)
            if match:
                return int(match.group(1)), matched_sku
    except Exception:
        pass

    for part_number in part_numbers:
        for prefix, count in _SETINA_PB450L_PREFIX_COUNTS.items():
            if part_number.startswith(prefix):
                return count, part_number
    return 0, ""


def _lighted_bumper_virtual_parts(part: PartInput, svc) -> list[PartInput]:
    light_count, source_sku = _setina_lighted_bumper_count(part, svc)
    if light_count not in {2, 4, 6}:
        return []

    base_line_id = part.line_id or part.part_number or "push_bumper"
    source_sku = source_sku or part.part_number
    virtual = [
        PartInput(
            name="Forward Warning",
            include=True,
            manufacturer="Whelen",
            part_number=f"{source_sku}:included-top-tube",
            location="TOP TUBE",
            raw_color="Red/Blue/White",
            quantity=4 if light_count == 6 else light_count,
            lens="clear",
            notes="Included with Setina PB450L lighted push bumper",
            line_id=f"{base_line_id}:included-top-tube",
        )
    ]
    if light_count == 6:
        virtual.append(
            PartInput(
                name="Forward Warning",
                include=True,
                manufacturer="Whelen",
                part_number=f"{source_sku}:included-side-push-bumper",
                location="SIDE OF PUSH BUMPER",
                raw_color="Red/Blue/White",
                quantity=2,
                lens="clear",
                notes="Included with Setina PB450L lighted push bumper",
                line_id=f"{base_line_id}:included-side-push-bumper",
            )
        )
    return virtual


def _parts_db_render_for_part(
    part_number: str, svc, candidates: list[str] | None = None
) -> dict:
    candidates = candidates or [part_number]
    candidates = [
        str(candidate).strip().upper()
        for candidate in candidates
        if str(candidate).strip()
    ]
    if not candidates:
        return {}
    try:
        products = (svc.raw_doc().get("products") or {}).values()
    except Exception:
        return {}

    def render_for(product: dict, sku: dict | None = None) -> dict:
        render = dict(product.get("render") or {})
        # Keep the optional override on the concrete SKU, without requiring
        # every SKU to carry duplicated render dimensions.
        if sku and sku.get("size_rule_id"):
            render["size_rule_id"] = sku["size_rule_id"]
        return render

    # A concrete SKU is the strongest product identity. This also makes a
    # SKU-level size assignment win over its parent model as documented.
    for product in products:
        for pn in product.get("part_numbers") or []:
            if str(pn.get("part_number", "")).strip().upper() in candidates:
                return render_for(product, pn)

    # Older workbook rows can carry a product model instead of an orderable
    # SKU. Resolve those through the product's stable model identity and any
    # curated aliases; this is identity translation, not a size text rule.
    def normalized_identity(value: object) -> str:
        return _re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())

    wanted = {normalized_identity(candidate) for candidate in candidates}
    wanted.discard("")
    if not wanted:
        return {}
    for product in products:
        identities = [product.get("model", ""), *(product.get("model_aliases") or [])]
        if wanted.intersection(normalized_identity(identity) for identity in identities):
            return render_for(product)
    return {}


def _inner_edge_render_config(part: PartInput) -> dict:
    """Return a sanitized Inner Edge render directive saved by the picker."""
    raw = getattr(part, "picker_config", {}) or {}
    config = raw.get("inner_edge") if isinstance(raw, dict) else None
    if not isinstance(config, dict):
        return {}
    product_id = str(config.get("product_id", "")).strip()
    lamp_count = config.get("lamp_count")
    try:
        lamp_count = int(lamp_count)
    except (TypeError, ValueError):
        lamp_count = 0
    if product_id not in {"whelen_fst", "whelen_rst"} or lamp_count < 1:
        return {}
    coverage = str(config.get("coverage", "both")).strip().lower()
    if coverage not in {"both", "driver", "passenger"}:
        coverage = "both"
    return {"product_id": product_id, "lamp_count": lamp_count, "coverage": coverage}


def _outer_edge_render_config(part: PartInput) -> dict:
    """Return the fixed six-head rear-pillar directive saved by the picker."""
    raw = getattr(part, "picker_config", {}) or {}
    config = raw.get("outer_edge_pillar") if isinstance(raw, dict) else None
    if not isinstance(config, dict):
        return {}
    if str(config.get("product_id", "")).strip() != _OUTER_EDGE_PILLAR_PRODUCT_ID:
        return {}
    try:
        head_count = int(config.get("head_count", 0))
    except (TypeError, ValueError):
        return {}
    if head_count != _OUTER_EDGE_HEAD_COUNT:
        return {}
    return {"head_count": head_count}


def _accessory_parent_render_groups(parts: list[PartInput]) -> dict[str, dict]:
    """Return visual grouping declared by accessory child rows.

    The relationship stays on the accessory line because that is the billable
    SKU that determines the physical housing.  THSG2 is retained as a fallback
    for drafts saved before the picker began snapshotting accessory metadata.
    """
    groups: dict[str, dict] = {}
    for child in parts:
        if not child.include or not child.parent_line_id:
            continue
        config = getattr(child, "picker_config", {}) or {}
        rule = config.get("accessory_quantity") if isinstance(config, dict) else None
        if not isinstance(rule, dict):
            rule = {}
        style = str(rule.get("render_parent_group") or "").strip()
        if not style and str(child.part_number or "").strip().upper() == "THSG2":
            style = "dual_shroud"
            rule = {**rule, "parent_units_per_item": 2}
        if style != "dual_shroud":
            continue
        groups[child.parent_line_id] = {
            "style": style,
            "size": max(2, int(rule.get("parent_units_per_item") or 2)),
        }
    return groups


def _views_for_location(location_key: str, view_map: dict[str, dict]) -> list[str]:
    """Return the view names where *location_key* has coordinates.

    view_map is {view_name_lower: view_config}.  Only views where
    location_key exists in view_config["locations"] are returned.
    """
    views: list[str] = []
    for view_name, vcfg in sorted(view_map.items()):
        locations = vcfg.get("locations") or {}
        if location_key in locations:
            views.append(view_name)
    return views


def _renderable_system_components(part: PartInput) -> list[PartInput]:
    """Return system sub-components that need their own physical artwork.

    Guided systems intentionally keep most of their setup as an expandable
    component list on one purchase line.  A roof antenna is different: it is
    visible on the build drawing, so synthesize a planning-only part from the
    saved component.  This also repairs already-saved guided radio builds
    without rewriting their drafts.
    """
    rendered: list[PartInput] = []
    for component in getattr(part, "components", []) or []:
        if not isinstance(component, dict) or component.get("part_type") != "radio_antenna_top":
            continue
        detail = str(component.get("detail", "") or "")
        is_whip = "whip" in detail.casefold()
        supply = normalized_supply_fields({
            **component,
            "new_or_used": component.get("new_or_used", part.new_or_used),
            "source": component.get("source", part.source),
            "supply_type": component.get("supply_type", part.supply_type),
            "customer_condition": component.get("customer_condition", part.customer_condition),
            "customer_source": component.get("customer_source", part.customer_source),
        })
        rendered.append(PartInput(
            name="Radio Antenna",
            include=True,
            new_or_used=supply["new_or_used"],
            source=supply["source"],
            supply_type=supply["supply_type"],
            customer_condition=supply["customer_condition"],
            customer_source=supply["customer_source"],
            manufacturer="Laird" if is_whip else "",
            part_number="QWB800" if is_whip else "",
            location=str(component.get("location", "") or ""),
            quantity=max(1, int(component.get("quantity", 1) or 1)),
            notes=detail,
            line_id=part.line_id,
            part_type="radio_antenna_top",
        ))
    return rendered


def build_plan(project, config: ConfigBundle) -> BuildPlan:
    manifest = config.asset_manifest
    layouts = config.vehicle_layouts.get("vehicles", {})
    vehicle_type = project.info.get("VehicleType", "PIU")
    vehicle = layouts.get(vehicle_type, {})
    view_map = {k.lower(): v for k, v in vehicle.get("views", {}).items()}
    fixtures_map = vehicle.get("fixtures", {})

    # Lazy-load parts_db_service only when a catalog miss occurs.
    _parts_db_svc: object | None = None

    def _get_svc():
        nonlocal _parts_db_svc
        if _parts_db_svc is None:
            from ..app.services.parts_db_service import get_parts_db_service
            _parts_db_svc = get_parts_db_service(config.paths)
        return _parts_db_svc

    # Pre-pass: collect names of all included parts for co_part_rules
    present_part_names: set[str] = set()
    for part in project.parts:
        if part.include:
            present_part_names.add(part.name.strip())
            present_part_names.add(canonical_name(part.name).strip().upper())
            if part.part_number:
                present_part_names.add(part.part_number.strip())
                present_part_names.add(canonical_name(part.part_number).strip().upper())

    planned_parts: list[PlannedPart] = []
    warnings: list[str] = []
    accessory_render_groups = _accessory_parent_render_groups(project.parts)

    # Run the rule engine; fold results into the top-level warnings list
    rule_result = run_rules(project, config.build_rules)
    for msg in rule_result.messages:
        prefix = "[ERROR]" if msg.severity == RuleSeverity.ERROR else "[RULE]"
        warnings.append(f"{prefix} {msg.message}")

    parts_to_plan: list[PartInput] = []
    for part in project.parts:
        parts_to_plan.append(part)
        if part.include:
            parts_to_plan.extend(_lighted_bumper_virtual_parts(part, _get_svc()))
            parts_to_plan.extend(_renderable_system_components(part))

    for part in parts_to_plan:
        if not part.include:
            continue

        # One-off custom parts are billable manifest lines, deliberately not
        # inventory/catalog products. They belong in generated documentation
        # but have no vehicle artwork or placement requirement.
        custom = (getattr(part, "picker_config", {}) or {}).get("custom_part")
        if isinstance(custom, dict):
            planned_parts.append(
                PlannedPart(
                    part_id="custom_part",
                    part_name=part.name,
                    category="custom",
                    render_kind="none",
                    on_diagram=False,
                    raw=part,
                )
            )
            continue

        spec = config.parts_by_name.get(part.name.upper())
        # ── category-level resolution ──────────────────────────────────
        # When a part matches the legacy catalog, use that spec ONLY for
        # legacy Excel imports (no line_id).  Picker-created parts with a
        # line_id always resolve through the part_type so rendering
        # parameters (quantity_rules, color_profile, asset_key) are not
        # contaminated by catalog entries designed for specific locations.
        if spec is not None and part.line_id:
            spec = None

        if spec is None:
            svc = _get_svc()
            # A picker line carries its exact parts_db type. Prefer that over
            # guessing from its display name: nested build parts deliberately
            # use descriptive manifest names such as "Center Console · Face
            # Plate 1 · …", which have no legacy workbook equivalent.
            part_type_id = str(getattr(part, "part_type", "") or "").strip()
            pt = svc.get_part_type(part_type_id) if part_type_id else None
            base_name = part.name
            if pt is None:
                pt, base_name = _find_part_type_by_name(part.name, svc)
            if pt is not None:
                spec = _synthesize_spec(pt, part.location)
            else:
                planned_parts.append(
                    PlannedPart(
                        part_id="unmapped",
                        part_name=part.name,
                        category="unknown",
                        render_kind="none",
                        on_diagram=False,
                        raw=part,
                        warnings=[f"No part catalog entry for '{part.name}'"],
                    )
                )
                warnings.append(f"Unmapped part: {part.name}")
                continue

        # Model-based remap: switch spec when the part number matches a model_remaps entry
        if part.part_number and spec.get("model_remaps"):
            model_key = canonical_name(part.part_number).strip().upper()
            remapped_id = spec["model_remaps"].get(model_key)
            if remapped_id and remapped_id in config.parts_by_id:
                spec = config.parts_by_id[remapped_id]

        # Tracer housings always render as their lamp-row shape, even when the
        # line was picker-created (synthesized spec carries no model_remaps).
        if part.part_number:
            tracer_id = _TRACER_RENDER_BY_SKU.get((part.part_number or "").strip().upper())
            if tracer_id and tracer_id in config.parts_by_id:
                spec = config.parts_by_id[tracer_id]

        inner_edge = _inner_edge_render_config(part)
        if inner_edge:
            fixture_id = _INNER_EDGE_FIXTURE_BY_TYPE.get(part.part_type)
            if fixture_id:
                # The housing remains a one-unit QB line, while its lamp count
                # drives render slots below. Rendering as `light` deliberately
                # bypasses the existing full-width interior-bar bitmap.
                spec = {
                    **spec,
                    "part_id": fixture_id,
                    "render_kind": "light",
                    "asset_key": "",
                    "is_fixture": True,
                    "default_views": (
                        ["front", "top"] if inner_edge["product_id"] == "whelen_fst" else ["rear", "top"]
                    ),
                    "render_quantity_policy": "single_per_line",
                    "group_shapes": False,
                    "images": {},
                }

        outer_edge = _outer_edge_render_config(part)
        if outer_edge:
            # The one billable housing line renders the six included IONs as
            # two rear-pillar stacks.  The separately saved ION child lines
            # remain manifest/estimate detail and intentionally do not render.
            spec = {
                **spec,
                "part_id": "outer_edge_pillar",
                "render_kind": "light",
                "asset_key": "",
                "is_fixture": False,
                "default_views": ["rear"],
                "render_quantity_policy": "single_per_line",
                "group_shapes": False,
                "images": {},
            }

        accessory_parents = spec.get("accessory_of")
        planned = PlannedPart(
            part_id=spec["part_id"],
            part_name=part.name,
            category=spec["category"],
            render_kind=spec["render_kind"],
            on_diagram=False,
            raw=part,
            accessory_of=(
                accessory_parents[0]
                if isinstance(accessory_parents, list) and accessory_parents
                else accessory_parents
                if isinstance(accessory_parents, str)
                else None
            ),
        )

        if spec["render_kind"] == "none":
            planned_parts.append(planned)
            continue

        # A custom shop reference is allowed to be manifest-only.  It carries
        # no vehicle anchor unless the picker user explicitly chose a dot or
        # free point, so it must not become a render warning.
        if custom_location_has_no_render_placement(part):
            planned_parts.append(planned)
            continue

        # Determine which views to render in: default_views from the catalog
        # spec, OR resolved from the location's coordinates when the spec
        # was synthesised (category-level parts).
        free_points = custom_location_points(part)
        catalog_views = spec.get("default_views", [])
        if free_points:
            render_views = list(free_points)
        elif catalog_views:
            render_views = catalog_views[:]
        else:
            # Synthesised spec — resolve views from location coordinates.
            location_key = resolved_location_key(part, spec)
            if location_key:
                render_views = _views_for_location(location_key, view_map)
                if not render_views:
                    planned.warnings.append(
                        f"No views found for location '{location_key}' in vehicle '{vehicle_type}'"
                    )
                    planned_parts.append(planned)
                    continue
            else:
                planned.warnings.append(f"No location supplied for '{part.name}' — cannot resolve views")
                planned_parts.append(planned)
                continue

        # Apply the same no-top-view rule to picker-created (parts_db) lines
        # and legacy spreadsheet lines resolved from part_catalog.json.
        if (
            part.part_type in _INTERIOR_LIGHT_BAR_PART_TYPES
            or spec.get("part_id") in _INTERIOR_LIGHT_BAR_PART_TYPES
            or spec.get("asset_key") in _INTERIOR_LIGHT_BAR_ASSET_KEYS
        ):
            render_views = [view for view in render_views if view.lower() != "top"]

        if not render_views:
            planned.warnings.append(f"No views configured for '{part.name}'")
            planned_parts.append(planned)
            continue

        profile_id, raw_color_token = resolve_profile(part, spec, manifest)
        product_render = _parts_db_render_for_part(
            part.part_number,
            _get_svc(),
            candidates=_part_number_candidates(part),
        )
        explicit_size_rule = (
            product_render.get("size_rule_id")
            or spec.get("size_rule_id")
            or ""
        )
        size_class = size_class_for_part(
            part.part_number,
            manifest,
            explicit_size_class=str(explicit_size_rule),
        )
        lib_entry = next(
            (
                config.parts_lib_by_model[key]
                for key in model_lookup_keys(part.part_number)
                if key in config.parts_lib_by_model
            ),
            {},
        )
        lib_size_per_view: dict = lib_entry.get("size_per_view", {})
        lib_images: dict = lib_entry.get("images", {})
        catalog_size_per_view: dict = spec.get("size_per_view", {})
        product_size_per_view: dict = product_render.get("size_per_view", {})
        merged_size_per_view = {**lib_size_per_view, **catalog_size_per_view, **product_size_per_view}
        spec_images: dict = spec.get("images", {})
        product_images: dict = product_render.get("images", {})
        merged_images = {**lib_images, **spec_images, **product_images}
        accessory_render_group = accessory_render_groups.get(part.line_id, {})

        is_fixture = bool(spec.get("is_fixture"))
        co_overrides = apply_co_part_rules(spec, present_part_names)

        if co_overrides.get("skip"):
            continue
        # Some combined fixture artwork includes a separately listed sibling
        # component.  Keep that component on the manifest while deliberately
        # omitting its redundant vehicle drawing.
        if co_overrides.get("suppress_render"):
            planned_parts.append(planned)
            continue

        effective_asset_key = co_overrides.get(
            "asset_key", spec.get("asset_key") or spec.get("part_id", "")
        )

        render_targets = (
            [(view, point, index + 1)
             for view in render_views
             for index, point in enumerate(free_points.get(view.lower(), []))]
            if free_points else [(view, None, 0) for view in render_views]
        )
        for view, custom_point, custom_point_index in render_targets:
            view_config = view_map.get(view.lower(), {})

            if custom_point is not None:
                location = {
                    "x": custom_point["x"], "y": custom_point["y"],
                    "units": view_config.get("coord_space", "relative_image"),
                    "orientation": "h", "slot_count": 1, "pattern": "single",
                }
                location_key = f"CUSTOM:{view.upper()}:{custom_point_index}"
            elif is_fixture:
                location, location_key = resolve_fixture_entry(
                    spec, view, fixtures_map, view_config
                )
                if location is None:
                    planned.warnings.append(
                        f"{view}: no fixture coords for '{part.name}' in vehicle '{vehicle_type}'"
                    )
                    continue
            else:
                location, location_key = resolve_normal_location(
                    part, spec, view, view_config
                )
                if location is None:
                    if location_key:
                        planned.warnings.append(f"{view}: location '{location_key}' not found")
                    else:
                        planned.warnings.append(f"{view}: no location supplied for {part.name}")
                    continue

            # Library entries (per-product) may override the part_type's policy.
            # A spec like "front_scene" defaults to location_slots, but a Pioneer
            # placed in that row is a single-head fixture-style product and
            # should render as one centered icon, not a mirror pair.
            quantity_policy = (
                lib_entry.get("render_quantity_policy")
                or spec.get("render_quantity_policy", "location_slots")
            )
            slot_count = int(location.get("slot_count", 1))

            if quantity_policy == "single_per_line":
                # A single billable fixture line normally renders once.  Some
                # artwork, such as front wing wraps, is a physical left/right
                # pair and declares its visual instance count per view.
                slot_count = int(location.get("render_slot_count", 1))
            elif quantity_policy == "quantity_as_slots":
                slot_count = max(1, part.quantity or 1)

            if inner_edge:
                slot_count = inner_edge["lamp_count"]

            qty_overrides = apply_quantity_rules(spec, part.quantity)
            if not qty_overrides:
                loc_rules = location.get("quantity_rules")
                if loc_rules:
                    qty_overrides = apply_quantity_rules_list(loc_rules, part.quantity)
            numbered_siren_slot = _NUMBERED_SIREN_SLOT_INDEX.get(part.name.strip().upper())
            if (
                numbered_siren_slot is not None
                and spec.get("_parts_db_render")
                and "SIREN SPEAKER 1" in present_part_names
                and "SIREN SPEAKER 2" in present_part_names
                and (part.quantity or 1) == 1
            ):
                qty_overrides = {
                    "slot_count": 2,
                    "slot_indices": [numbered_siren_slot],
                    "pattern": "mirror",
                }
            if qty_overrides.get("slot_count"):
                slot_count = int(qty_overrides["slot_count"])
            if outer_edge:
                slot_count = outer_edge["head_count"]
            slot_indices: list[int] | None = qty_overrides.get("slot_indices")

            # A normal single-per-line product is one centered icon even at a
            # mirror location (for example a Pioneer on top of a bumper).
            # Front Wing Wraps are one billable fixture but deliberately draw
            # two physical halves, so retain their authored mirror pattern.
            is_wing_wrap_pair = (
                spec.get("part_id") == "wing_wraps"
                and int(location.get("render_slot_count", 1)) > 1
            )
            default_pattern = (
                "single"
                if quantity_policy == "single_per_line"
                and not is_wing_wrap_pair
                else location.get("pattern", "single")
            )
            effective_pattern = co_overrides.get(
                "pattern", qty_overrides.get("pattern", default_pattern)
            )
            # A one-head Pioneer at a mirrored mount (such as the top of a
            # push bumper) occupies the center. Multi-head Pioneer selections
            # still use the location's authored pattern and head count.
            if (
                product_render.get("center_single_at_mirror_location")
                and quantity_policy == "quantity_as_slots"
                and max(1, part.quantity or 1) == 1
                and location.get("pattern") == "mirror"
            ):
                effective_pattern = "single"
            # Scene heads are selected as an explicit count in the picker.  A
            # single-coordinate scene location is an anchor, not a one-head
            # cap: one stays at that anchor while two or more need a visible
            # row.  Preserve authored mirror/horizontal/vertical patterns,
            # and only supply the natural horizontal fallback for a legacy
            # single-dot location.
            if (
                spec.get("_parts_db_render")
                and spec.get("category") == "scene"
                and quantity_policy == "quantity_as_slots"
                and slot_count > 1
                and effective_pattern == "single"
            ):
                effective_pattern = "horizontal"
            if inner_edge:
                if inner_edge["product_id"] == "whelen_rst":
                    effective_pattern = "inner_edge_rear"
                else:
                    effective_pattern = {
                        "driver": "inner_edge_front_driver",
                        "passenger": "inner_edge_front_passenger",
                    }.get(inner_edge["coverage"], "inner_edge_front")
            if outer_edge:
                effective_pattern = "outer_edge_pillars"
            forced_side = co_overrides.get("side", "")
            if forced_side:
                slot_count = 1

            compound_group_size = 1
            compound_group_count = 0
            compound_group_style = ""
            compound_item_spacing = 1.0
            placement_unit_count = slot_count
            if (
                accessory_render_group.get("style") == "dual_shroud"
                and spec.get("render_kind") == "light"
                and custom_point is None
            ):
                compound_group_size = max(2, int(accessory_render_group.get("size") or 2))
                requested_groups = max(
                    1,
                    (max(1, part.quantity or 1) + compound_group_size - 1)
                    // compound_group_size,
                )
                # A side profile has one visible cargo-window position even
                # though the order contains matching driver/passenger shrouds.
                # Front/rear mirror locations expose both group positions.
                compound_group_count = min(requested_groups, max(1, slot_count))
                placement_unit_count = compound_group_count
                compound_group_style = "dual_shroud"
                compound_item_spacing = 1.05

            loc_asset_rules = spec.get("location_asset_rules", {})
            if not is_fixture and location_key in loc_asset_rules:
                effective_asset_key = loc_asset_rules[location_key]

            placement_roles = slot_roles(
                effective_pattern,
                placement_unit_count,
                view_config,
                forced_side,
                uniform_color=bool(spec.get("group_shapes", False)),
            )
            roles = (
                [role for role in placement_roles for _ in range(compound_group_size)]
                if compound_group_style
                else placement_roles
            )
            slot_count = len(roles)

            custom_head_index = None
            if custom_point is not None:
                raw_index = custom_point.get("head_index", custom_point_index - 1)
                custom_head_index = raw_index if isinstance(raw_index, int) else custom_point_index - 1
                x = float(custom_point["x"])
                point_count = len(free_points.get(view.lower(), []))
                if "head_index" in custom_point and point_count > 1:
                    midpoint = (point_count - 1) / 2
                    if custom_head_index < midpoint:
                        roles = [view_side_role(view_config, "negative_x")]
                    elif custom_head_index > midpoint:
                        roles = [view_side_role(view_config, "positive_x")]
                    else:
                        roles = [view_config.get("default_slot_role", "center")]
                elif x < 0.49:
                    roles = [view_side_role(view_config, "negative_x")]
                elif x > 0.51:
                    roles = [view_side_role(view_config, "positive_x")]
                else:
                    roles = [view_config.get("default_slot_role", "center")]

            position_slot_count: int | None = None
            if slot_indices:
                position_slot_count = slot_count
                roles = [roles[i] for i in slot_indices if i < len(roles)]
                slot_count = len(roles)

            original_location_pattern = location.get("pattern", "single")
            anchor_x = (
                0.5
                if original_location_pattern == "mirror"
                and not forced_side
                and (placement_unit_count == 1 or location.get("render_slot_count"))
                else location["x"]
            )
            anchor_y = (
                0.5
                if original_location_pattern == "vertical_mirror"
                and placement_unit_count == 1
                and not forced_side
                else location["y"]
            )

            effective_size_override = (
                dict(_INNER_EDGE_SIZE_PER_VIEW[view])
                if inner_edge and view in _INNER_EDGE_SIZE_PER_VIEW
                else merged_size_per_view.get(view) or None
            )

            mount_visibility, callout_label = _concealed_mount(part, location_key)
            placement = PlannedPlacement(
                part_id=spec["part_id"],
                part_name=part.name,
                view=view,
                location_key=location_key,
                render_kind=spec["render_kind"],
                asset_key=effective_asset_key,
                size_class=size_class,
                color_profile=profile_id,
                quantity_policy=quantity_policy,
                ordered_quantity=part.quantity,
                location_slot_count=int(location.get("slot_count", 1)),
                anchor={
                    "x": anchor_x,
                    "y": anchor_y,
                    "units": location.get("units", view_config.get("coord_space", "relative_image")),
                },
                pattern=effective_pattern,
                # Inner Edge uses narrowed ION artwork with a small gap between
                # heads. FST's special geometry supplies its own center gap;
                # RST stays connected without overlapping the vehicle.
                h_spacing=(1.05 if inner_edge else location.get("h_spacing") or None),
                v_spacing=(
                    _OUTER_EDGE_VERTICAL_SPACING
                    if outer_edge else location.get("v_spacing") or None
                ),
                h_spacing_units=("icon_width" if inner_edge else location.get("h_spacing_units", "relative_image")),
                size_override=effective_size_override,
                rotation=(
                    _OUTER_EDGE_PILLAR_ROTATION if outer_edge else (
                        float(location.get("rotation", 0))
                        + float((effective_size_override or {}).get("rotation", 0))
                    ) % 360
                ),
                flip_h=bool(location.get("flip_h", False)),
                flip_v=bool(location.get("flip_v", False)),
                flip_mirrored_h=bool(location.get("flip_mirrored_h", False)),
                behind_vehicle=bool(location.get("behind_vehicle", False)),
                mount_visibility=mount_visibility,
                callout_label=callout_label,
                layer=enforced_render_layer(
                    spec["part_id"], int(location.get("layer", 0))
                ),
                group_shapes=(
                    quantity_policy == "quantity_as_slots"
                    or bool(compound_group_style)
                    or bool(spec.get("group_shapes", False))
                ),
                is_fixture=is_fixture,
                slot_indices=slot_indices or None,
                position_slot_count=position_slot_count,
                compound_group_size=compound_group_size,
                compound_group_count=compound_group_count,
                compound_group_style=compound_group_style,
                compound_item_spacing=compound_item_spacing,
                line_id=part.line_id,
            )

            if quantity_policy == "location_slots":
                placement_quantity = (
                    max(1, (part.quantity + compound_group_size - 1) // compound_group_size)
                    if compound_group_style and part.quantity
                    else part.quantity
                )
                if custom_point is None and placement_quantity and placement_quantity != placement.location_slot_count and not slot_indices:
                    is_side_light = view == "side" and spec["render_kind"] in ("light", "bar")
                    if not is_side_light and location_key not in _SUPPRESS_QTY_MISMATCH_LOCATIONS:
                        placement.warnings.append(
                            f"[{part.name}] @ '{location_key}' ({view}): "
                            f"workbook qty {part.quantity} ≠ location slot count {placement.location_slot_count}"
                        )
            elif quantity_policy == "single_per_line" and part.quantity > 1:
                placement.warnings.append(
                    f"[{part.name}] @ '{location_key}' ({view}): "
                    f"qty {part.quantity} recorded but this part renders once per line item"
                )

            orientation = location.get("orientation", "h")
            for index, slot_role in enumerate(roles, start=1):
                color_token = resolve_color_token(
                    profile_id, raw_color_token, slot_role, part, manifest
                )
                if custom_head_index is not None:
                    color_token = resolve_custom_head_color_token(part, custom_head_index) or color_token
                elif compound_group_style:
                    color_token = resolve_custom_head_color_token(part, index - 1) or color_token
                asset_path = resolve_asset_path(
                    render_kind=spec["render_kind"],
                    asset_key=effective_asset_key,
                    view=view,
                    orientation=orientation,
                    color_token=color_token,
                    asset_manifest=manifest,
                    fallback_images=merged_images,
                )
                if spec.get("_parts_db_render") and merged_images.get(view):
                    asset_path = merged_images[view]
                instance = RenderInstance(
                    slot_index=index,
                    slot_role=slot_role,
                    orientation=orientation,
                    color_token=color_token,
                    asset_path=asset_path,
                )
                if asset_path:
                    asset_file = config.paths.workspace_assets_dir / Path(asset_path)
                    if not asset_file.exists():
                        instance.warnings.append(f"Missing asset ({view}): {asset_path}")
                elif spec["render_kind"] == "equipment":
                    instance.warnings.append(f"No equipment asset configured for '{part.name}' ({view})")
                elif spec["render_kind"] == "bar":
                    instance.warnings.append(f"No bar asset configured for '{part.name}' ({view})")
                elif spec["render_kind"] != "none":
                    instance.warnings.append(f"No asset resolved for '{part.name}' ({view})")
                placement.instances.append(instance)

            planned.placements.append(placement)

        planned.on_diagram = bool(planned.placements)
        planned_parts.append(planned)

    return BuildPlan(
        version="7.0",
        project=project.info,
        planned_parts=planned_parts,
        warnings=warnings,
        notes=project.notes,
    )
