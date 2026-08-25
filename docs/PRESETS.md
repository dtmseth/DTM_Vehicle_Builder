# Preset System

Presets are JSON files (schema_version 4) that define reusable part configurations for
builds. They are cached locally and mirrored to SharePoint — **the cloud is the source
of truth**, not the local cache.

## Schema

```json
{
  "preset_id": "...",
  "label": "St. Cloud PD Patrol PIU/Tahoe",
  "agency_ids": ["..."],   // [] = universal
  "build_types": ["Patrol"],
  "vehicle_types": ["PIU", "TAHOE"],
  "tag": "",               // optional suffix for General presets
  "parts": [...]
}
```

Each part preserves the complete reusable build shape, including `part_type`, concrete SKU
`components`, `picker_config`, accessory relationships, status, and per-part placement metadata.
The preset also preserves the draft-level `placement_overrides`. These fields are required for a
new vehicle created from a saved setup to render and estimate identically to its source build.

Schema v4 stores canonical supply fields on each part and guided component:

```json
{
  "supply_type": "new",
  "customer_condition": "",
  "customer_source": ""
}
```

`supply_type` is `new` or `customer_supplied`; a customer-supplied condition is `new` or `used`.
Explicit customer-supplied/used data must include `customer_source`. Older preset files remain
readable: blank/New becomes New, Used/Reused becomes customer-supplied/used, and legacy `source` is
preserved as `customer_source`. Normalized presets continue to carry the compatibility fields for
older consumers during the migration window.

Label is auto-generated from agency + build_type + vehicle_types.

## Storage

- **Cache location**: `workspace/presets/` (bundled app) or `src/dtm_buildsheet/resources/presets/` (dev mode)
- **Source of truth**: SharePoint `/Settings/presets/`
- **The cache is a local mirror**, not the canonical source
- Bundled presets were removed in v2.2.10; `resources/presets/*.json` is gitignored

## Preset manager (Settings → Presets)

Supports:
- Import from workbook
- Export to workbook
- Clone
- Delete

The Preset creator's agency choices are live data, not a tab-lifetime cache. Every Add/Edit/open
refetches `/api/agencies`, and agency create/delete/rename/import events refresh both the preset
table labels and an already-open creator. Mutable API GET requests use `cache: "no-store"`, so a
browser response cache cannot reintroduce an outdated list.

`blank_custom` is hardcoded in `preset_service` (no file on disk) — it's the only preset
that survives a fresh install with no cloud connection.

## Preset application

When creating a build unit, the user can select a preset by `preset_id`. The preset's parts
are applied to the build draft as the starting configuration. The `label` field is
auto-generated and reflects the agency + build_type + vehicle_types at preset creation time.

In the new-project wizard and existing Project Details editor, **All Presets** is intentionally
unfiltered: it lists every non-blank preset even when its saved vehicle or build type differs from
the current unit. The agency shortcut remains a narrower convenience list.

An existing build also exposes **Load Preset** beside **Save as New Preset**. The loader refreshes
the current preset list, shows only presets compatible with the build's vehicle and build type,
and replaces the draft's parts and placement overrides in one server-side operation. Vehicle/unit
identity, build notes, and project-wide notes remain unchanged. Loading is a copy operation for
that one build; it does not silently change the unit group's assigned preset or sibling vehicles.
