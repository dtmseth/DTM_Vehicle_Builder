# Preset System

Presets are JSON files (schema_version 2) that define reusable part configurations for
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

`blank_custom` is hardcoded in `preset_service` (no file on disk) — it's the only preset
that survives a fresh install with no cloud connection.

## Preset application

When creating a build unit, the user can select a preset by `preset_id`. The preset's parts
are applied to the build draft as the starting configuration. The `label` field is
auto-generated and reflects the agency + build_type + vehicle_types at preset creation time.
