"""parts_db.json read service (Phase 3).

Stands up the canonical parts database with a **dual-read** fallback so the
existing workbook_rules / parts_library / vehicle_layouts plumbing keeps
working while consumers migrate (Phase 4).

Lookups try `parts_db.json` first; when the file is missing, a part is
missing, or a requested field is empty, the service delegates to
`LegacyFallbackReader` which mirrors today's `workbook_rules.part_rules[name]`
access pattern.

Lifecycle:
- One singleton per process, accessible via `get_parts_db_service(paths)`.
- Cache is populated on first query and invalidated by
  `config_service.save_config_file("parts_db.json", ...)`.

See docs/ROADMAP.md §Phase 3 and §7 for schema and design notes.
"""

from __future__ import annotations

import logging
from typing import Optional

from ...config.store import load_config
from ...domain.parts_db_models import (
    BracketRequirement,
    Color,
    Location,
    Manufacturer,
    Model,
    Part,
)
from ...paths import AppPaths

logger = logging.getLogger(__name__)


def _empty_doc() -> dict:
    """Shape returned when parts_db.json is absent — every consumer sees the
    same empty document instead of branching on file existence."""
    return {
        "schema_version": 1,
        "metadata": {},
        "part_categories": {},
        "location_zones": {},
        "locations": {},
        "build_sections": {},
        "manufacturers": {},
        "color_palette": {},
        "parts": {},
        "naming_rules": {},
    }


# ── Legacy fallback reader ────────────────────────────────────────────────────


class LegacyFallbackReader:
    """Mirrors today's workbook_rules / parts_library / vehicle_layouts access.

    Compat-shim queries on `PartsDbService` delegate here when parts_db.json
    can't answer (file missing, part missing, field empty). Phase 4 deletes
    these callers and this reader along with them.
    """

    def __init__(self, paths: AppPaths):
        self._paths = paths
        # The cache is lazy and per-call: we re-read workbook_rules on every
        # query because it's small (~3K lines, cheap json.loads) and we want
        # any in-app edits to be reflected immediately without an
        # invalidation callback. Phase 4 deletes this reader, so the
        # per-call cost is short-lived.

    def reload(self) -> None:
        pass  # nothing cached; here so PartsDbService.invalidate stays uniform

    def _workbook_rule(self, legacy_name: str) -> dict:
        wb = load_config("workbook_rules.json", self._paths)
        rules = wb.get("part_rules", {}) or {}
        # part_rules is keyed by display_name verbatim; match case-insensitively
        # because workbook input is upper-cased and the manifest editor passes
        # the user-facing string through.
        if legacy_name in rules:
            return rules[legacy_name]
        target = legacy_name.strip().upper()
        for key, rule in rules.items():
            if key.strip().upper() == target:
                return rule
        return {}

    def manufacturers(self, legacy_name: str) -> list[str]:
        return list(self._workbook_rule(legacy_name).get("manufacturer", []) or [])

    def models(self, legacy_name: str) -> list[str]:
        return list(self._workbook_rule(legacy_name).get("models", []) or [])

    def locations(self, legacy_name: str) -> list[str]:
        return list(self._workbook_rule(legacy_name).get("locations", []) or [])


# ── Service ──────────────────────────────────────────────────────────────────


class PartsDbService:
    def __init__(self, paths: AppPaths):
        self._paths = paths
        self._cache: dict | None = None
        self._fallback = LegacyFallbackReader(paths)

    # ── loading ────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._cache is None:
            try:
                self._cache = load_config("parts_db.json", self._paths)
            except FileNotFoundError:
                # PR-1 ships before the data file. Treat missing as empty
                # and rely entirely on the legacy fallback.
                self._cache = _empty_doc()
            except Exception:
                logger.exception("Could not load parts_db.json; using empty doc")
                self._cache = _empty_doc()
        return self._cache

    def invalidate(self) -> None:
        """Drop the cached doc. Called from config_service after a save."""
        self._cache = None
        self._fallback.reload()

    def raw_doc(self) -> dict:
        """Return the full parts_db.json (for GET /api/parts-db)."""
        return self._load()

    # ── primary typed queries ──────────────────────────────────────────────

    def list_parts_by_category(self, category: str) -> list[Part]:
        doc = self._load()
        return [
            _hydrate_part(pid, spec)
            for pid, spec in (doc.get("parts") or {}).items()
            if spec.get("category") == category
        ]

    def list_manufacturers_for_part(self, part_id: str) -> list[Manufacturer]:
        doc = self._load()
        part = (doc.get("parts") or {}).get(part_id)
        if not part:
            return []
        mfg_id = part.get("manufacturer_id", "")
        if not mfg_id:
            return []
        mfg = (doc.get("manufacturers") or {}).get(mfg_id)
        if not mfg:
            return []
        return [_hydrate_manufacturer(mfg_id, mfg)]

    def list_models_for_part(self, part_id: str) -> list[Model]:
        doc = self._load()
        part = (doc.get("parts") or {}).get(part_id)
        if not part:
            return []
        return [_hydrate_model(m) for m in (part.get("models") or [])]

    def list_compatible_locations(self, part_id: str, vehicle_type: str) -> list[Location]:
        doc = self._load()
        part = (doc.get("parts") or {}).get(part_id)
        if not part:
            return []
        location_ids = (part.get("compatible_locations_by_vehicle") or {}).get(
            vehicle_type, []
        )
        locations = doc.get("locations") or {}
        out: list[Location] = []
        for loc_id in location_ids:
            spec = locations.get(loc_id)
            if spec:
                out.append(_hydrate_location(loc_id, spec))
        return out

    def list_compatible_colors(self, part_id: str) -> list[Color]:
        doc = self._load()
        part = (doc.get("parts") or {}).get(part_id)
        if not part:
            return []
        # Color compatibility is per-model; union them for the part-level view.
        supported: set[str] = set()
        for model in part.get("models", []):
            supported.update(model.get("supported_colors", []) or [])
        palette = doc.get("color_palette") or {}
        return [
            _hydrate_color(cid, palette[cid])
            for cid in supported
            if cid in palette
        ]

    def bracket_requirement(self, part_id: str) -> Optional[BracketRequirement]:
        doc = self._load()
        part = (doc.get("parts") or {}).get(part_id)
        if not part:
            return None
        if not part.get("bracket_required"):
            return None
        return BracketRequirement(
            required=True,
            compatible_bracket_part_ids=list(part.get("compatible_bracket_part_ids", []) or []),
        )

    def list_compatible_brackets(
        self, part_id: str, location: str | None = None
    ) -> list[Part]:
        doc = self._load()
        part = (doc.get("parts") or {}).get(part_id)
        if not part:
            return []
        bracket_ids = part.get("compatible_bracket_part_ids", []) or []
        parts = doc.get("parts") or {}
        out: list[Part] = []
        for bid in bracket_ids:
            spec = parts.get(bid)
            if not spec:
                continue
            if location is not None:
                allowed = spec.get("compatible_locations", []) or []
                if allowed and location not in allowed:
                    continue
            out.append(_hydrate_part(bid, spec))
        return out

    # ── compat shims (name-keyed; fall through to legacy) ──────────────────

    def lookup_part_by_name(self, name: str) -> Optional[Part]:
        doc = self._load()
        target = (name or "").strip().upper()
        if not target:
            return None
        for pid, spec in (doc.get("parts") or {}).items():
            candidates = [spec.get("legacy_workbook_name", ""), spec.get("friendly_name", "")]
            candidates.extend(spec.get("aliases", []) or [])
            if any(c and c.strip().upper() == target for c in candidates):
                return _hydrate_part(pid, spec)
        return None

    def manufacturers_by_legacy_name(self, name: str) -> list[str]:
        part = self.lookup_part_by_name(name)
        if part and part.manufacturer_id:
            doc = self._load()
            mfg = (doc.get("manufacturers") or {}).get(part.manufacturer_id)
            if mfg:
                return [mfg.get("label", part.manufacturer_id)]
        return self._fallback.manufacturers(name)

    def models_by_legacy_name(self, name: str) -> list[str]:
        part = self.lookup_part_by_name(name)
        if part and part.models:
            return [m.model_number or m.model_id for m in part.models if (m.model_number or m.model_id)]
        return self._fallback.models(name)

    def locations_by_legacy_name(self, name: str) -> list[str]:
        part = self.lookup_part_by_name(name)
        if part:
            # Union of compatible locations across all vehicles
            seen: list[str] = []
            for loc_ids in (part.compatible_locations_by_vehicle or {}).values():
                for lid in loc_ids:
                    if lid not in seen:
                        seen.append(lid)
            if seen:
                return seen
        return self._fallback.locations(name)


# ── hydration helpers ────────────────────────────────────────────────────────


def _hydrate_part(part_id: str, spec: dict) -> Part:
    return Part(
        part_id=part_id,
        friendly_name=spec.get("friendly_name", ""),
        category=spec.get("category", ""),
        manufacturer_id=spec.get("manufacturer_id", ""),
        build_section=spec.get("build_section", ""),
        template_section=spec.get("template_section", ""),
        legacy_workbook_name=spec.get("legacy_workbook_name", ""),
        aliases=list(spec.get("aliases", []) or []),
        models=[_hydrate_model(m) for m in (spec.get("models", []) or [])],
        compatible_vehicles=list(spec.get("compatible_vehicles", []) or []),
        compatible_locations_by_vehicle={
            k: list(v) for k, v in (spec.get("compatible_locations_by_vehicle") or {}).items()
        },
        color_asset_map=dict(spec.get("color_asset_map") or {}),
        bracket_required=bool(spec.get("bracket_required", False)),
        compatible_bracket_part_ids=list(spec.get("compatible_bracket_part_ids", []) or []),
        compatible_part_ids=list(spec.get("compatible_part_ids", []) or []),
        compatible_locations=list(spec.get("compatible_locations", []) or []),
        serialized=bool(spec.get("serialized", False)),
    )


def _hydrate_model(spec: dict) -> Model:
    return Model(
        model_id=spec.get("model_id", ""),
        model_number=spec.get("model_number", ""),
        submodel=spec.get("submodel", ""),
        color_count=int(spec.get("color_count", 1) or 1),
        power_outputs=int(spec.get("power_outputs", 0) or 0),
        supported_colors=list(spec.get("supported_colors", []) or []),
        price_usd=spec.get("price_usd"),
        qty_on_hand=spec.get("qty_on_hand"),
    )


def _hydrate_manufacturer(mfg_id: str, spec: dict) -> Manufacturer:
    return Manufacturer(
        manufacturer_id=mfg_id,
        label=spec.get("label", mfg_id),
        website=spec.get("website", ""),
    )


def _hydrate_location(loc_id: str, spec: dict) -> Location:
    return Location(
        location_id=loc_id,
        label=spec.get("label", loc_id),
        zone=spec.get("zone", ""),
    )


def _hydrate_color(color_id: str, spec: dict) -> Color:
    return Color(
        color_id=color_id,
        label=spec.get("label", color_id),
        hex=spec.get("hex", ""),
        naming_token=spec.get("naming_token", ""),
    )


# ── module-level singleton ────────────────────────────────────────────────────

_instance: PartsDbService | None = None


def get_parts_db_service(paths: AppPaths) -> PartsDbService:
    """Return (or build) the process-wide PartsDbService.

    A second call with different `paths` resets the singleton — this is the
    pattern used by tests that point the service at a tmp workspace.
    """
    global _instance
    if _instance is None or _instance._paths is not paths:
        _instance = PartsDbService(paths)
    return _instance


def reset_for_testing() -> None:
    global _instance
    _instance = None
