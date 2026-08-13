# DTM Vehicle Builder — Feature Inventory

This document enumerates every feature and non-obvious rule in the current codebase. It is the reference for contributors who need to understand system behavior without reverse-engineering the source.

Last updated: 2026-05-18 (Phases 1–5: Agency DB, Sales Rep DB, Preset Manager, Project Layout Redesign, Embedded Build Editor)

---

## Table of Contents

1. [Data Flow Overview](#data-flow-overview)
2. [Excel Input Parsing](#excel-input-parsing)
3. [Project Metadata](#project-metadata)
4. [Part Catalog Rules](#part-catalog-rules)
5. [Build Planning (Planner)](#build-planning-planner)
6. [Color Resolution](#color-resolution)
7. [Placement Patterns & Geometry](#placement-patterns--geometry)
8. [Slot Roles](#slot-roles)
9. [Quantity Rules](#quantity-rules)
10. [Co-Part Rules](#co-part-rules)
11. [Model Remaps](#model-remaps)
12. [Asset Resolution](#asset-resolution)
13. [Fixture vs Location Parts](#fixture-vs-location-parts)
14. [PowerPoint Output](#powerpoint-output)
15. [Excel Template Generation](#excel-template-generation)
16. [Config System](#config-system)
17. [Project Manager](#project-manager)
18. [Agency Database](#agency-database)
19. [Sales Rep Database](#sales-rep-database)
20. [Preset Manager](#preset-manager)
21. [Embedded Build Editor](#embedded-build-editor)
22. [GUI HTTP Server & API Routes](#gui-http-server--api-routes)
23. [Asset Upload & Management](#asset-upload--management)
24. [String Normalization](#string-normalization)
25. [Warning System](#warning-system)

---

## Data Flow Overview

```
Excel Workbook (.xlsx)          GUI BuildDraft
        ↓  inputs/excel_reader.py     ↓  inputs/gui_entry.py
                        ProjectInput
                                ↓  planning/planner.py
                             BuildPlan
                                ↓  render_ppt.py  (consumes AppPaths)
                        Output .pptx + .md summary
```

`config/loader.py` assembles the active workspace config from the JSON config files and passes it to the planner. `generator.py` orchestrates the full pipeline from a file path.

---

## Excel Input Parsing

**Module**: `input_reader.py`

### Header Detection
- Scans rows 1 through `max_row` searching for a row whose first non-empty cell normalizes to contain `"part"` (case-insensitive, whitespace-collapsed).
- All subsequent rows are treated as data rows.

### Row Skipping Rules
A row is silently skipped if:
- The normalized part name is blank after stripping.
- The name is all-uppercase AND no other part fields contain data (section-header pattern used in some workbooks).
- Every relevant column is empty.

### Column Resolution
Each logical column (Manufacturer, Location, Color, etc.) has a list of known header variants tried in order. If none match, a hardcoded fallback column index is used.

### Include/Exclude Column
- Blank, `None`, or empty string → **included** (default is yes).
- `"n"`, `"no"`, `"false"`, `"0"`, `"off"` (any case) → **excluded**.
- Any other truthy value → included.

### Notes Sheet
- Sheet named `"Notes"` is optional.
- Rows 2+ are read; column 2 is the text value (column 1 is ignored).

### PartInput Fields
| Field | Source Column | Notes |
|---|---|---|
| `name` | Part | Normalized via `canonical_name()` |
| `include` | ✓ | Defaults to True |
| `new_or_used` | New/Used | Stored as-is |
| `source` | Source | Stored as-is |
| `manufacturer` | Manufacturer | Stored as-is |
| `part_number` | Model/Part# | Stored as-is |
| `location` | Location | Stored as-is |
| `raw_color` | Color | Stored as-is |
| `quantity` | Qty | `int()` parse; 0 on failure |
| `lens` | Lens | Stored as-is |
| `notes` | Notes | Stored as-is |
| `explicit_color_profile` | (none in base template) | Can be added to extended templates |
| `driver_color` | (none in base template) | Used with specify_palette |
| `passenger_color` | (none in base template) | Used with specify_palette |
| `center_color` | (none in base template) | Used with specify_palette |

---

## Project Metadata

**Module**: `input_reader.py`

### Vehicle Type Detection
Priority order (first match wins):
1. If model field contains `"PIU"` or `"UTILITY"` → `"PIU"`
2. If model field contains `"TAHOE"` → `"TAHOE"`
3. If model field contains `"DURANGO"` → `"DURANGO"`
4. If model field contains `"CHARGER"` → `"CHARGER"`
5. First 24 characters of model, uppercased, spaces replaced with underscores.
6. Fallback: `"UNKNOWN"`

Matching is case-insensitive substring.

### ProjectID Generation
Priority chain: `QuoteNumber` → `Agency` → `"PROJECT"`

The chosen value is passed through `safe_project_id()`:
- Strips all characters except `[A-Za-z0-9._-]`
- Truncates to 80 characters
- Returns `"PROJECT"` if result is empty

### Info Dict Keys
`agency`, `contact`, `vin`, `VehicleType`, `ProjectID`, `quote_number`, `vehicle_year`, `vehicle_make`, `vehicle_model`, `vehicle_color`, `new_or_existing`

---

## Part Catalog Rules

**Config file**: `part_catalog.json` → validated by `config_validation.py`

### Lookup
Parts are indexed two ways in `ConfigBundle`:
- `parts_by_name`: `display_name.upper()` and all aliases (uppercased) → spec dict
- `parts_by_id`: `part_id` → spec dict

During planning, a `PartInput.name` is looked up in `parts_by_name`. If not found, the part is skipped with a warning.

### Part Spec Fields
| Field | Type | Description |
|---|---|---|
| `part_id` | str | Unique identifier |
| `display_name` | str | User-visible label; also used as first alias |
| `category` | str | `"equipment"`, `"warning_light"`, `"appearance_note"`, etc. |
| `render_kind` | str | `"equipment"`, `"light"`, `"bar"`, `"none"` |
| `asset_key` | str | Key into `asset_manifest.equipment_assets`; defaults to `part_id` |
| `is_fixture` | bool | If true, location comes from `vehicle_layouts.fixtures`, not user input |
| `diagram` | bool | Whether to place on diagram slides |
| `default_views` | list[str] | Views where this part renders by default |
| `render_quantity_policy` | str | `"location_slots"`, `"single_per_line"`, `"quantity_as_slots"` |
| `quantity_rules` | list | Per-qty overrides for pattern/slot_count/slot_indices |
| `co_part_rules` | list | Conditional behavior based on presence of another part |
| `model_remaps` | dict | Swap to different part spec when part_number matches |
| `location_asset_rules` | dict | Use different asset key for specific location keys |
| `accessory_of` | str or list[str] | Parent part(s) for nested legend display |
| `aliases` | list[str] | Alternative lookup names (display_name is always included) |
| `size_per_view` | dict | `{view: {w, h}}` in inches; overrides manifest defaults |
| `group_shapes` | bool | Treat all slots as uniform color |
| `default_location_key` | str | Fallback if user doesn't specify location |
| `default_color_profile` | str | Fallback color profile ID |
| `conditions` | dict | Metadata only (e.g., `template_section`) |

---

## Build Planning (Planner)

**Module**: `planner.py`

The planner iterates over all included `PartInput` objects and, for each, produces a `PlannedPart` with one or more `PlannedPlacement` objects (one per view per location).

### Steps per Part
1. Look up spec in `parts_by_name`.
2. Apply **model remaps** — may swap to a different part spec.
3. Apply **co-part rules** — may skip, change asset, pattern, or side.
4. Resolve **color profile**.
5. Resolve **quantity rules** → overrides for pattern/slot_count/slot_indices.
6. For each view in `spec.default_views`:
   a. Resolve location → coordinates from `vehicle_layouts`.
   b. Determine `size_class` from `asset_manifest.part_number_size_rules`.
   c. Resolve **asset path** per slot role.
   d. Build `RenderInstance` objects.
   e. Emit `PlannedPlacement`.

### Present Part Names Set
Used for co-part rule matching. For each part, the set is built from:
- `part.name`
- `canonical_name(part.name).upper()`
- `part.part_number`
- `canonical_name(part.part_number).upper()`

All four forms are tried. This lets co-part rules match by display name or model number.

---

## Color Resolution

**Module**: `planner.py` → `_resolve_profile()`

Returns `(profile_id, color_token)`. Resolution order:

1. **Explicit profile**: If `explicit_color_profile` is set and found in `color_profiles` → use it, token = `""`.
2. **Preset map**: Matches on `raw_color` (case-insensitive):
   - `"blue"` → `("legacy_uniform", "blue")`
   - `"white"` → `("legacy_uniform", "white")`
   - `"amber"` → `("legacy_uniform", "amber")`
   - `"red/blue"` → `("legacy_uniform", "red-blue")`
   - `"red and blue"` → `("duo_r_b", "")`
   - `"red/white blue/white"` → `("std_duo_rb_w", "")`
   - `"red/amber blue/amber"` → `("duo_ra_ba", "")`
   - `"single color (specify)"` → `("specify_palette", "single")`
   - `"dual color (specify)"` → `("specify_palette", "duo")`
   - `"tri color (specify)"` → `("specify_palette", "trio")`
3. **Specify palette**: If profile is `specify_palette`, check `part.notes` for a named preset or legacy alias. User must also have filled `driver_color`, `passenger_color`, `center_color` — no automatic fallback.
4. **Custom colors**: If any of `driver_color`, `passenger_color`, `center_color` are filled → `("custom", "")`.
5. **Legacy alias**: Check `raw_color` against `legacy_color_aliases` in manifest.
6. **Token check**: If `raw_color` is in `light_color_tokens` → `("legacy_uniform", raw_color)`.
7. **Default profile**: Use `spec.default_color_profile` if set.
8. **Fallback**: `("none", raw_color)`.

### Color Profiles
Defined in `asset_manifest.json → color_profiles`. Each profile maps slot roles to color tokens:
```json
{
  "label": "Std Duo RB/W",
  "slot_tokens": {
    "driver": "red-white",
    "passenger": "blue-white",
    "center": "red-blue-white",
    "default": "red-blue-white"
  }
}
```
The `"default"` key is the fallback when the slot role has no explicit entry.

---

## Placement Patterns & Geometry

**Module**: `planner.py`, `render_ppt.py`

Patterns are defined per-location in `vehicle_layouts.json` and can be overridden by quantity rules or co-part rules.

| Pattern | Description |
|---|---|
| `"single"` | One icon at the anchor point |
| `"horizontal"` | N icons spread left-to-right |
| `"mirror"` | Icons split symmetrically around center: left half on driver side, right half on passenger side |
| `"vertical"` | N icons stacked top-to-bottom |

### Coordinates
- `x`, `y`: Normalized 0–1 (fraction of vehicle image width/height) when `units = "relative_image"`.
- `h_spacing`, `v_spacing`: Gap between icons.
- `h_spacing_units`: `"relative_image"` or `"icon_width"` (fraction of icon width).

### Transforms
| Field | Description |
|---|---|
| `rotation` | Degrees clockwise |
| `flip_h` | Horizontal flip |
| `flip_v` | Vertical flip |
| `flip_mirrored_h` | Applies `flip_h` only to mirrored (right-side) slots |

### Anchor Snap Rule
When a co-part rule forces `pattern="single"` on a mirror location that has no `forced_side`, the anchor x is snapped to `0.5` (center of vehicle image). This prevents the icon from appearing offset at the original mirror anchor.

### Slot Indices
When set, only the specified slot indices are rendered, but `position_slot_count` reflects the full array size. This allows, for example, rendering slots 1 and 3 out of a 5-slot array at their naturally-spaced positions without recomputing coordinates.

### Size Override Merge
Three layers (later wins on conflict):
1. Manifest library defaults (`lib_size_per_view`)
2. Catalog `size_per_view`
3. Per-model catalog `size_per_view` (from model remaps or library)

---

## Slot Roles

**Module**: `planner.py` → `_build_slot_roles()`

Slot roles are identifiers used to look up the correct color token in a color profile.

| Role | Meaning |
|---|---|
| `"driver"` | Left/driver side slot |
| `"passenger"` | Right/passenger side slot |
| `"center"` | Middle slot |
| `"slot_1"`, `"slot_2"`, ... | Positional (vertical pattern) |
| `"uniform"` | Sentinel — always uses `"default"` color token; ignores profile |
| `"negative_x"` | Driver-side in mirror pattern |
| `"positive_x"` | Passenger-side in mirror pattern |

### Role Assignment Rules
- `group_shapes=True` OR `render_quantity_policy="quantity_as_slots"` → all slots get `"uniform"`.
- Pattern `"single"`: Role is `forced_side` if set, else the view's `default_slot_role`.
- Pattern `"mirror"` with qty=2: `[negative_x, positive_x]`. With qty>2: first half `negative_x`, second half `positive_x`.
- Pattern `"horizontal"`: Slots left of middle index → `negative_x`; right of middle → `positive_x`; exact middle → `center`.
- Pattern `"vertical"`: `[slot_1, slot_2, ...]`.
- `forced_side` on any pattern: overrides everything; forces `slot_count=1` with the given role.

---

## Quantity Rules

**Module**: `planner.py` → `_apply_quantity_rules()`

Defined in `part_catalog.json → quantity_rules` as a list of objects:
```json
[{"qty": 2, "pattern": "mirror", "slot_count": 2}]
```

- Matched by exact integer value of `ordered_quantity`.
- Return overrides: `pattern`, `slot_count`, `slot_indices`.
- Only the first matching rule applies.

### Quantity Policy Modes
| Mode | Behavior |
|---|---|
| `"location_slots"` | `slot_count` comes from location definition. If user qty differs → warning. |
| `"single_per_line"` | Always `slot_count=1`. If user qty > 1 → warning. |
| `"quantity_as_slots"` | `slot_count = max(1, ordered_quantity)`. Also sets `group_shapes=True`. |

---

## Co-Part Rules

**Module**: `planner.py` → `_apply_co_part_rules()`

Defined in `part_catalog.json → co_part_rules` as a list of objects:
```json
[{
  "co_part": "Other Part Name",
  "if_present": {"pattern": "single", "side": "driver"},
  "if_absent": {"skip": true}
}]
```

- `co_part` is matched against the present-part-names set (see [Build Planning](#build-planning-planner)).
- The matching branch (`if_present` or `if_absent`) can include:
  - `skip: true` — suppress this part entirely.
  - `asset_key` — use a different image asset.
  - `pattern` — override the layout pattern.
  - `side` — force a specific slot role.
- Rules are applied once per part (view-agnostic).
- Only the first matching rule in the list is applied.

---

## Model Remaps

**Module**: `planner.py`

Defined in `part_catalog.json → model_remaps` as:
```json
{"SOME_MODEL_KEY": "other_part_id"}
```

- If `part.part_number` matches a key (case-insensitive), the entire spec is swapped to the target `part_id`.
- Silently changes rendering spec mid-plan with no warning emitted.
- Used for parts that share a display name but have different rendering specs by model number.

---

## Asset Resolution

**Module**: `planner.py` → `_resolve_asset_path()`

### Equipment / Bar Parts
- Looks up `asset_key` in `asset_manifest.equipment_assets[view]`.
- Falls back to `asset_manifest.placeholder_assets[view]`.
- `location_asset_rules` in the spec can override `asset_key` per location.

### Light Parts
- Filename constructed from `asset_manifest.light_icon_rule.filename_pattern`.
- Template variables: `{color_token}` and `{orientation}`.
- Example: `"sm_{color_token}_{orientation}.png"` → `"sm_red-blue_h.png"`.
- File expected in `workspace_assets_dir / light_icon_rule.subfolder /`.

### Size Class
Determined by `_size_class_for_part()`:
1. Exact `part_number` match in `asset_manifest.part_number_size_rules`.
2. Substring match: `part_number.upper()` contains rule key.
3. Default: `"sm"`.

Size class prefixes the color token in light filenames (e.g., `"sm_"` vs `"lg_"`).

---

## Fixture vs Location Parts

**Module**: `planner.py`, `vehicle_layouts.json`

### Fixture Parts (`is_fixture: true`)
- Location coordinates come from `vehicle_layouts.vehicles[VehicleType].fixtures[part_id][view]`.
- The user's `location` field is **ignored**.
- If the fixture entry is missing for the current vehicle type or view, the view is skipped.

### Non-Fixture Parts
- Location comes from the user's `location` field, normalized to uppercase via `canonical_name()`.
- If blank, `spec.default_location_key` is used.
- The location key is looked up in `vehicle_layouts.vehicles[VehicleType].views[view].locations`.
- If the location key is not found, the part is unplaced for that view with a warning.

---

## PowerPoint Output

**Module**: `render_ppt.py`, `ppt_helpers.py`

### Slide Structure (fixed order)
| Position | Slide | Description |
|---|---|---|
| 0 | Cover | Agency, contact, VIN, logo, vehicle image |
| 1 | Parts Manifest | Tabular part list (may be multiple slides) |
| 2 | Front view | Vehicle diagram with icons |
| 3 | Side view | Vehicle diagram with icons |
| 4 | Top view | Vehicle diagram with icons |
| 5 | Rear view | Vehicle diagram with icons |
| 6 | Notes | Project notes |

Manifest slides are appended last, then moved to position 1 via `_move_slides_to_position()`.

### Rendering per View Slide
1. Place vehicle background image.
2. For each `PlannedPlacement` in the view:
   - Compute `slot_positions` from pattern, anchor, spacing.
   - For each slot, add icon picture at computed position and size.
   - Apply transforms (rotation, flip_h, flip_v, flip_mirrored_h).
   - If `behind_vehicle=True`, move shape behind vehicle image in XML.
   - If `group_shapes=True`, group all slot shapes together.
3. Place `specify_palette` swatch if applicable.
4. Place legend grid (placed parts) and unplaced legend.

### Legend
- Parts with placements appear in the placed legend per view.
- Parts without placements appear in the unplaced legend.
- `accessory_of` creates indented child entries under parent parts.

### Footer
Applied to every slide: project metadata text bar at bottom.

### Logo Placement
- Cover slide: large logo.
- View slides with left-side vehicle image: logo at bottom.
- View slides with centered vehicle image: logo at default position.

---

## Excel Template Generation

**Module**: `template_builder.py`

### Column Layout
| Column | Header | Width |
|---|---|---|
| A | ✓ | 4 |
| B | Part | 30 |
| C | New/Used | 11 |
| D | Source | 13 |
| E | Manufacturer | 22 |
| F | Model/Part# | 20 |
| G | Location | 28 |
| H | Color | 20 |
| I | Qty | 8 |
| J | Lens | 22 |
| K | Notes | 32 |

### Template Structure
- **Rows 1–13**: Agency info, contact, VIN; vehicle type dropdown; new/existing vehicle fields.
- **Row 14**: Column header row (navy background).
- **Row 15+**: Part data rows from `workbook_rules.template_sections`, with alternating light-gray row backgrounds.

### Dropdown Sources
- **Vehicle Type**: All vehicle keys from `vehicle_layouts.vehicles`.
- **New/Used**: Fixed list `[NEW, USED, REUSED, N/A]`.
- **Manufacturer, Models, Location, Color, Qty, Lens**: Merged from `workbook_rules.part_rules` (authoritative) + `parts_library` entries (fallback). Deduplicated.

### Inline Dropdown Limit
If a combined option list exceeds 240 characters, it is truncated. This can silently drop options for parts with many variants.

### Dropdown Deduplication
Identical option sets are cached and the same `DataValidation` object is reused, which prevents Excel from creating redundant validation definitions.

---

## Config System

**Modules**: `config/loader.py`, `config/store.py`, `config/schemas.py`, `config/migrations.py`

### Config Files
| File | Purpose |
|---|---|
| `part_catalog.json` | Part specs, rendering rules |
| `vehicle_layouts.json` | Per-vehicle fixture coords and location definitions |
| `asset_manifest.json` | Equipment image keys, light filename rules, color profiles |
| `parts_library.json` | Manufacturer/model dropdown data |
| `workbook_rules.json` | Excel template sections and per-part dropdown overrides |
| `app_settings.json` | App-level settings (template save dir, etc.) |
| `project_options.json` | Project wizard dropdown lists (build types, brands) |
| `build_rules.json` | Dependency, incompatibility, vehicle/location compatibility, group, and preset rules |

### Validation (`config/schemas.py`)
- All files must be JSON objects.
- `schema_version` is added (default 1) if missing.
- `part_catalog.json`: requires `"parts"` array; each entry needs `part_id`, `display_name`, `category`, `render_kind`, `default_views`; `display_name` is canonicalized and added to aliases.
- `vehicle_layouts.json`: requires `"vehicles"` object; all location keys normalized to UPPERCASE.
- `asset_manifest.json`: requires `"equipment_assets"`; `"placeholder_assets"` added if missing.
- `parts_library.json`: requires `"parts"` array; `compatible_types` entries canonicalized.
- `workbook_rules.json`: requires `"template_sections"`.
- `app_settings.json`: sets default `"template_save_dir": ""` if missing.
- `build_rules.json`: validates known rule groups, rule IDs, and severity values.

### Save Behavior
- Config saves write with 2-space indentation and a final newline.
- Saves go through validation first; invalid data is rejected.
- Template regeneration is triggered server-side by `app/services/config_service.py` after saves to template-feeding config files.

### Workspace vs Bundled
- Dev: workspace in `{repo}/workspace/`, resources in `src/dtm_buildsheet/resources/`.
- Bundled: workspace in `~/Library/Application Support/DTM Vehicle Builder` (Mac) or `%APPDATA%\DTM Vehicle Builder` (Windows).
- On first run, bundled defaults are copied to workspace. User edits in workspace are never overwritten.

---

## Project Manager

**Modules**: `domain/project_models.py`, `inputs/project_entry.py`, `app/services/project_service.py`, `app/routes/projects.py`, `ui/js/projects/` (split UI: `detail_builds.js`, `detail_overview.js`, `detail_edit.js`, `list.js`, `wizard.js`, etc.)

### Project Record Structure
Projects are stored as individual JSON files in `workspace/projects/{project_id}.json`.

| Field | Type | Notes |
|---|---|---|
| `project_id` | str | Derived from agency/quote via `safe_project_id()` |
| `customer` | CustomerInfo | Agency name + agency_id + sales_rep_id + quote + year + notes |
| `preferences` | EquipmentPreferences | Lighting, camera, bumper, cage, slick top, notes |
| `build_units` | list[BuildUnit] | Each unit group has a vehicle model, build type, quantity, preset, and individual list |
| `export_dir` | str | Empty = default output location; user-configurable |
| `created_at` / `updated_at` | str | ISO timestamps |

Each `IndividualUnit` within a `BuildUnit` carries its own `draft_id` (links to `workspace/drafts/`) and `output_path` (set when the build sheet is generated).

### Project Detail View (Overview / Edit / Builds)
The project detail view has three sub-tabs:

- **Overview**: read-only two-column layout (customer info card left, preferences card right), fleet unit groups below.
- **Edit**: read-only by default; `[✏️ Edit]` button activates edit mode with full input fields. Save stays on the detail view; Cancel discards changes. The 4-step wizard (`#proj-editor`) is only for new projects.
- **Builds**: per-unit cards with `[Setup Build]`/`[Edit Build]`, `[Generate ▶]` (disabled until draft_id set), and `[Export PDF]` (disabled until output_path set). Bottom row: `[⚡ Generate All]` and `[📄 Export All PDFs]`.

### Create Draft Flow
`POST /api/project/{project_id}/unit/{unit_id}/create-draft` — creates a new `BuildDraft` from the unit's preset (if assigned) and returns the draft_id. This wires the unit to the draft system. Individual units use a parallel endpoint that includes the `individual_id` segment.

---

## Agency Database

**Modules**: `domain/agency_models.py`, `app/services/agency_service.py`, `app/routes/agencies.py`, `ui/js/settings/agencies.js`

### Storage
`workspace/agencies.json`:
```json
{"schema_version": 1, "agencies": [AgencyRecord, ...]}
```

### AgencyRecord Fields
| Field | Notes |
|---|---|
| `agency_id` | UUID |
| `name` | Canonical name, e.g. "St. Cloud PD" |
| `contact_name` | Required on creation |
| `contact_info` | Required on creation (phone or email) |
| `customer_since` | Free text year / best guess |
| `default_preferences` | Equipment defaults copied into new projects |
| `pricing_overrides` | Sparse manufacturer discounts that prefill the estimate modal's optional Custom pricing; estimates still default to Retail |
| `qb_customer_id` | Company-local QuickBooks Customer ID |
| `created_at` / `updated_at` | ISO timestamps |

### Fuzzy Search
`handle_search_agencies(query, paths)`:
1. Normalizes query: lowercase, strip punctuation.
2. Expands abbreviations: `pd` → `police department`, `so` → `sheriff's office`, `st.` → `saint`, `dept` → `department`, etc.
3. Runs `difflib.get_close_matches(normalized_query, normalized_names, n=5, cutoff=0.6)`.
4. Returns matches sorted by score.

The project wizard shows a live-search combo for agency. On blur, if matches exist, a suggestion modal appears ("Did you mean…?").

### REST Endpoints
| Method | Path | Description |
|---|---|---|
| GET | `/api/agencies` | List all agencies |
| GET | `/api/agencies/search?q=…` | Fuzzy search |
| POST | `/api/agency/save` | Create or update agency |
| DELETE | `/api/agency/{agency_id}` | Delete agency |

---

## Sales Rep Database

**Modules**: `domain/sales_rep_models.py`, `app/services/sales_rep_service.py`, `app/routes/sales_reps.py`, `ui/js/settings/sales_reps.js`

### Storage
`workspace/sales_reps.json`:
```json
{"schema_version": 1, "sales_reps": [SalesRepRecord, ...]}
```

### REST Endpoints
| Method | Path | Description |
|---|---|---|
| GET | `/api/sales-reps` | List all sales reps |
| GET | `/api/sales-reps/search?q=…` | Search by name |
| POST | `/api/sales-rep/save` | Create or update rep |
| DELETE | `/api/sales-rep/{rep_id}` | Delete rep |

The project wizard has a live-search combo for sales rep (same pattern as agency). Contact info comes from the agency record; there is no separate contact field on the project.

---

## Preset Manager

**Modules**: `app/services/preset_service.py`, `app/routes/presets.py`, `ui/js/settings/presets_mgr.js`

### Preset Schema (v2)
Preset JSON files live in `src/dtm_buildsheet/resources/presets/` (dev) or `workspace/presets/` (bundled app).

```json
{
  "schema_version": 2,
  "preset_id": "...",
  "label": "St. Cloud PD Patrol PIU/Tahoe",
  "agency_ids": [],     // [] = universal (any agency)
  "build_types": [],    // [] = any build type
  "vehicle_types": [],
  "tag": "",            // optional suffix, shown only for General presets
  "parts": [...]
}
```

### Auto-Naming Logic
`_auto_name(payload, paths)`:
- If `agency_ids` non-empty: look up first agency name → prefix.
- Else: prefix = `"General"`.
- Append `build_types` value if exactly one.
- Append vehicle_types joined with `/` (e.g. `"PIU/Tahoe/Durango"`).
- If tag non-empty: append `" — {tag}"`.

Duplicate detection: if a preset already exists with the same agency + build_type + vehicle_types combination, the API returns a conflict and the UI asks the user to overwrite.

### REST Endpoints
| Method | Path | Description |
|---|---|---|
| GET | `/api/presets` | List all presets (bundled + workspace) |
| GET | `/api/presets/{id}` | Get single preset |
| GET | `/api/presets/{id}/export-workbook` | Fill blank template with preset parts → downloadable `.xlsx` |
| POST | `/api/presets/save` | Create or update preset |
| POST | `/api/presets/import-workbook` | Parse `.xlsx` body → extract parts → return preset payload |
| POST | `/api/presets/{id}/clone` | Copy with new ID, strip agency_ids |
| DELETE | `/api/presets/{id}` | Delete workspace preset (cannot delete bundled) |

### Preset Filtering in Project Editor
`projects_tab.js` filters the preset dropdown by:
1. `vehicle_types` — compatible with current unit's vehicle model (soft filter: compatible shown first, others grayed).
2. `agency_ids` — agency-specific presets appear in a separate "Agency Presets" section.
3. `build_types` — filtered to current unit's build type.

---

## Embedded Build Editor

**Modules**: `ui/js/projects_tab.js` (`_showBuildEditor`, `_hideBuildEditor`), `ui/js/preview_canvas.js` (`pvLoad`, `pvReload`), `ui/js/manifest_editor.js` (`loadDraftManifest`)

### DOM Structure
`#proj-build-editor` is a sibling of `#proj-list-view`, `#proj-detail-view`, and `#proj-editor` inside `#tab-projects`. It contains:
- `#pbe-header` — unit context line + "← Back to Project" button
- `#pbe-preview-section` — preview canvas (reuses `#card-preview`)
- `#pbe-manifest-section` — manifest editor (reuses `#card-manifest`)
- `#pbe-footer` — "💾 Save & Return to Project" button

`#card-preview` and `#card-manifest` exist only here — they are not duplicated in Settings → Tools.

### Show/Hide Flow
**`_showBuildEditor(draftId, unit, project, returnTab)`**:
1. Hides `#proj-detail-view` (and `#proj-editor` if open).
2. Shows `#proj-build-editor`.
3. Populates `#pbe-unit-info` with unit context.
4. Stores `_pbeReturnProject` and `_pbeReturnTab = "builds"`.
5. Calls `pvLoad(draftId)` and `loadDraftManifest(draftId)`.

**`_hideBuildEditor()`**:
1. Hides `#proj-build-editor`, shows `#proj-detail-view`.
2. Reloads project from API.
3. Re-renders all three detail tabs (Overview, Edit, Builds).
4. Calls `_setDetailTab("builds")`.

**`#pbe-save-return` click**:
1. Calls `saveDraftManifest()` to persist the draft.
2. Calls `_hideBuildEditor()`.

**Triggering the editor** — from the Builds tab, clicking "Setup Build" or "Edit Build" calls `_showBuildEditor` directly. "Setup Build" first calls the create-draft API to get a `draft_id`.

### pvReload
`pvReload()` in `preview_canvas.js` reloads using the internally stored `_pvDraftId` — no external state needed.

---

## GUI HTTP Server & API Routes

**Modules**: `gui_server.py` compatibility shim, `app/server.py`, `app/routes/*`, `app/services/*` — HTTP server on `127.0.0.1:7655`

### GET Routes
| Path | Description |
|---|---|
| `/` | Serves `ui/index.html` |
| `/status` | Returns `{"status": "ok"}` |
| `/api/catalog` | Returns `part_catalog.json` |
| `/api/layouts` | Returns `vehicle_layouts.json` |
| `/api/manifest` | Returns `asset_manifest.json` |
| `/api/parts-library` | Returns `parts_library.json` |
| `/api/workbook-rules` | Returns `workbook_rules.json` |
| `/api/app-settings` | Returns `app_settings.json` |
| `/api/template/info` | Returns info about current template file |
| `/api/template/pick-folder` | Opens native folder picker dialog |
| `/api/assets/list` | Lists available workspace asset files |
| `/api/draft/list` | Lists saved GUI drafts |
| `/api/agencies` | List all agencies |
| `/api/agencies/search?q=…` | Fuzzy agency search |
| `/api/sales-reps` | List all sales reps |
| `/api/sales-reps/search?q=…` | Sales rep name search |
| `/api/presets` | List all presets (bundled + workspace) |
| `/api/presets/{id}` | Get single preset |
| `/api/presets/{id}/export-workbook` | Download preset as filled `.xlsx` |
| `/api/projects` | List all projects |
| `/api/project/{project_id}` | Get single project |
| `/favicon.ico` | Serves app icon |

### POST Routes
| Path | Description |
|---|---|
| `/parse` | Upload `.xlsx`, parse to `ProjectInput`, return JSON |
| `/generate` | Run full pipeline on last-uploaded workbook, return result paths |
| `/api/catalog/save` | Validate and save `part_catalog.json` |
| `/api/layouts/save` | Validate and save `vehicle_layouts.json` |
| `/api/manifest/save` | Validate and save `asset_manifest.json` |
| `/api/parts-library/save` | Validate and save `parts_library.json` |
| `/api/workbook-rules/save` | Validate and save `workbook_rules.json` |
| `/api/app-settings/save` | Validate and save `app_settings.json` |
| `/api/assets/upload` | Upload image file to workspace assets |
| `/api/assets/delete` | Remove image file from workspace assets |
| `/api/template/generate` | Regenerate Excel template workbook |
| `/api/validate` | Run build rule validation |
| `/api/preview/plan` | Build preview data from draft/session state |
| `/api/export/pdf` | Export generated PPTX to PDF; hydrates a shared cross-instance PPTX first when necessary |
| `/api/draft/*` | Save, load, update, or delete GUI drafts |
| `/api/agency/save` | Create or update agency |
| `/api/sales-rep/save` | Create or update sales rep |
| `/api/presets/save` | Create or update preset |
| `/api/presets/import-workbook` | Parse `.xlsx` body → return preset payload |
| `/api/presets/{id}/clone` | Clone preset with new ID |
| `/api/project/save` | Create or update project |
| `/api/project/{id}/unit/{uid}/create-draft` | Create build draft for a BuildUnit |
| `/api/project/{id}/unit/{uid}/individual/{iid}/create-draft` | Create build draft for an IndividualUnit |
| `/api/project/{id}/export-all-pdf` | Export all generated sheets for a project to PDF |

### DELETE Routes
| Path | Description |
|---|---|
| `/api/agency/{agency_id}` | Delete agency |
| `/api/sales-rep/{rep_id}` | Delete sales rep |
| `/api/presets/{preset_id}` | Delete workspace preset (cannot delete bundled) |
| `/api/project/{project_id}` | Delete project |

### Template Regeneration Trigger
After saving any config that feeds `template_builder.py`, `app/services/config_service.py` starts template regeneration as a server-side side effect. Adding a new template-feeding config file requires updating `TEMPLATE_REGEN_FILES`.

### pywebview Integration
- `app/server.py:main()` starts the HTTP server (`gui_server.py` is a compatibility shim that calls it).
- With pywebview installed: server moves to daemon thread; pywebview opens a native window (must own macOS main thread).
- Without pywebview: falls back to `webbrowser.open()`.

---

## Asset Upload & Management

**Module**: `app/services/asset_service.py`, `app/routes/assets.py`

### Upload
- Accepts multipart form data with `filename` and `data` (base64 or raw bytes).
- Filename is sanitized (`Path(filename).name` — directory traversal stripped).
- Written to `workspace_assets_dir / filename`.

### Delete
- Accepts `{"filename": "..."}`.
- Removes file from `workspace_assets_dir`.
- Does not update `asset_manifest.json` automatically; the caller is responsible.

---

## String Normalization

**Module**: `naming.py`

### `canonical_name(name)`
- Applies hard-coded corrections from `CANONICAL_NAME_FIXES` for known typos.
- Returns the corrected name or original if no fix applies.

### `safe_project_id(raw)`
- Strips everything except `[A-Za-z0-9._-]`.
- Truncates to 80 characters.
- Returns `"PROJECT"` if result is empty.

### Header Normalization (in `input_reader.py`)
- Lowercases the string.
- Replaces `"\n"` with a space.
- Strips leading/trailing whitespace.

### Location Key Normalization
- All location keys in `vehicle_layouts.json` are UPPERCASE after validation.
- User input is uppercased via `canonical_name()` before lookup.

---

## Warning System

Warnings are strings collected at multiple levels and flattened in `generator.py`.

| Level | Where stored |
|---|---|
| Plan-level | `BuildPlan.warnings` |
| Part-level | `PlannedPart.warnings` |
| Placement-level | `PlannedPlacement.warnings` |
| Instance-level | `RenderInstance.warnings` |

`generator.py` flattens all levels into `GenerationResult.warnings`.

### Common Warning Conditions
- Part name not found in catalog.
- Part location not found in vehicle layout.
- Fixture entry missing for vehicle type or view.
- User quantity does not match location's `slot_count` (when policy is `"location_slots"`).
- Asset file not found.
- `specify_palette` used without per-slot color fields filled.
- Model remap target part_id not found in catalog.
