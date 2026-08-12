# DTM Vehicle Builder — Config File Schemas

Reference for all JSON configuration and data files. Config files live in `workspace/config/` (editable) and `src/dtm_buildsheet/resources/config/` (bundled defaults). Workspace data files (agencies, sales reps, projects, presets) live directly in `workspace/` or its sub-directories.

Last updated: 2026-05-18 (Phases 1–5)

---

## Table of Contents

1. [part_catalog.json](#part_catalogjson)
2. [vehicle_layouts.json](#vehicle_layoutsjson)
3. [asset_manifest.json](#asset_manifestjson)
4. [parts_library.json](#parts_libraryjson)
5. [workbook_rules.json](#workbook_rulesjson)
6. [app_settings.json](#app_settingsjson)
7. [project_options.json](#project_optionsjson)
8. [agencies.json](#agenciesjson)
9. [sales_reps.json](#sales_repsjson)
10. [Preset Files](#preset-files)
11. [parts_db.json](#parts_dbjson)
12. [Common Conventions](#common-conventions)

---

## part_catalog.json

Defines every known part type: how it is named, categorized, and rendered. This is the central rules engine.

```
{
  "schema_version": 1,
  "parts": [ <PartSpec>, ... ]
}
```

### PartSpec Object

```
{
  "part_id":                 <string, required, unique>,
  "display_name":            <string, required>,
  "category":                <string, required>,
  "render_kind":             <string, required>,
  "default_views":           <list[string], required>,

  "aliases":                 <list[string], optional>,
  "asset_key":               <string, optional — defaults to part_id>,
  "is_fixture":              <bool, optional — default false>,
  "diagram":                 <bool, optional — default true>,

  "render_quantity_policy":  <string, optional>,
  "quantity_rules":          <list[QuantityRule], optional>,
  "co_part_rules":           <list[CoPartRule], optional>,
  "model_remaps":            <dict[string, string], optional>,
  "location_asset_rules":    <dict[string, string], optional>,

  "accessory_of":            <string or list[string], optional>,
  "size_per_view":           <dict[view, SizeSpec], optional>,
  "group_shapes":            <bool, optional — default false>,
  "default_location_key":    <string, optional>,
  "default_color_profile":   <string, optional>,
  "conditions":              <dict, optional — metadata only>
}
```

#### category values
| Value | Meaning |
|---|---|
| `"equipment"` | Physical equipment (bumpers, lights, etc.) |
| `"warning_light"` | Warning/emergency light |
| `"appearance_note"` | Non-rendered appearance annotation |

#### render_kind values
| Value | Rendering behavior |
|---|---|
| `"equipment"` | Renders a static equipment image |
| `"light"` | Renders a light icon; filename constructed from color token + orientation |
| `"bar"` | Renders a light bar image |
| `"none"` | No icon placed on diagram |

#### render_quantity_policy values
| Value | Behavior |
|---|---|
| `"location_slots"` | slot_count from location definition; mismatch → warning |
| `"single_per_line"` | One billable line; normally one visual slot, or `render_slot_count` from the view's location when supplied; qty > 1 → warning |
| `"quantity_as_slots"` | slot_count = max(1, ordered_quantity); sets group_shapes |

### QuantityRule Object
```
{
  "qty":          <int, required — exact ordered_quantity to match>,
  "pattern":      <string, optional>,
  "slot_count":   <int, optional>,
  "slot_indices": <list[int], optional — 1-based; selects subset of position array>
}
```

### CoPartRule Object
```
{
  "co_part":    <string, required — display name or part_number of the other part>,
  "if_present": <CoPartBranch, optional>,
  "if_absent":  <CoPartBranch, optional>
}
```

### CoPartBranch Object
```
{
  "skip":      <bool, optional — if true, suppress this part entirely>,
  "asset_key": <string, optional — use different equipment image>,
  "pattern":   <string, optional — override layout pattern>,
  "side":      <string, optional — force slot role ("driver"|"passenger"|"center")>
}
```

### SizeSpec Object
```
{ "w": <float, inches>, "h": <float, inches> }
```

---

## vehicle_layouts.json

Defines, per vehicle type, the fixture coordinates and named location points used to place parts on diagram slides.

```
{
  "schema_version": 1,
  "vehicles": {
    "<VehicleType>": <VehicleLayout>,
    ...
  }
}
```

`<VehicleType>` is an uppercase string matching the value returned by `input_reader.detect_vehicle_type()` (e.g., `"PIU"`, `"TAHOE"`).

### VehicleLayout Object
```
{
  "fixtures": {
    "<part_id>": {
      "<view>": <LocationPoint>,
      ...
    },
    ...
  },
  "views": {
    "<view>": {
      "locations": {
        "<LOCATION_KEY>": <LocationPoint>,
        ...
      }
    },
    ...
  }
}
```

`<view>` is one of `"front"`, `"side"`, `"top"`, `"rear"`.

`<LOCATION_KEY>` must be UPPERCASE (enforced by validation on save).

### LocationPoint Object
```
{
  "x":               <float, required — normalized 0-1 (anchor left edge of icon array)>,
  "y":               <float, required — normalized 0-1 (anchor top edge of icon array)>,
  "units":           <string, required — "relative_image">,
  "orientation":     <string, required — "h" | "v" | "bar">,
  "slot_count":      <int, optional — number of positions; default 1>,
  "render_slot_count": <int, optional — visual instances for a `single_per_line` fixture; default 1>,
  "pattern":         <string, optional — "single" | "horizontal" | "vertical" | "mirror" | "vertical_mirror">,
  "h_spacing":       <float, optional — gap between icons>,
  "v_spacing":       <float, optional — gap between icons>,
  "h_spacing_units": <string, optional — "relative_image" | "icon_width">,
  "rotation":        <float, optional — degrees clockwise>,
  "flip_h":          <bool, optional>,
  "flip_v":          <bool, optional>,
  "flip_mirrored_h": <bool, optional — flip_h only on mirrored right-side slots>,
  "behind_vehicle":  <bool, optional — render under vehicle image>,
  "side_roles": {
    "negative_x":        <string — role for left-side slots>,
    "positive_x":        <string — role for right-side slots>,
    "default_slot_role": <string — fallback role>
  }
}
```

#### Coordinate System
- `x=0.0` is the left edge of the vehicle image; `x=1.0` is the right edge.
- `y=0.0` is the top edge; `y=1.0` is the bottom edge.
- The anchor point `(x, y)` is the top-left of the icon or icon array.

#### Orientation Values
| Value | Meaning |
|---|---|
| `"h"` | Horizontal (standard light icon) |
| `"v"` | Vertical |
| `"bar"` | Light bar (uses bar-specific asset) |

---

## asset_manifest.json

Maps asset keys to image files and defines color profile rules for light icons.

```
{
  "schema_version": 1,

  "light_icon_rule": <LightIconRule>,
  "light_color_tokens": [ <string>, ... ],

  "equipment_assets": {
    "<asset_key>": {
      "<view>": <string — relative path from workspace_assets_dir>,
      ...
    },
    ...
  },

  "placeholder_assets": {
    "<view>": <string — relative path>,
    ...
  },

  "color_profiles": {
    "<profile_id>": <ColorProfile>,
    ...
  },

  "legacy_color_aliases": {
    "<raw_color_string>": <string — color token>,
    ...
  },

  "size_rule_definitions": {
    "<profile_id>": <SizeProfile>,
    ...
  }
}
```

### LightIconRule Object
```
{
  "subfolder":        <string — relative path from workspace_assets_dir>,
  "filename_pattern": <string — template with {color_token} and {orientation}>
}
```

Example: `"sm_{color_token}_{orientation}.png"` → `"sm_red-blue_h.png"`

### ColorProfile Object
```
{
  "label": <string — human-readable label>,
  "slot_tokens": {
    "driver":    <string — color token>,
    "passenger": <string — color token>,
    "center":    <string — color token>,
    "default":   <string — color token; fallback for any unmatched role>
  }
}
```

#### Built-in Color Profiles
| profile_id | Label |
|---|---|
| `"legacy_uniform"` | Single uniform color (token comes from `raw_color`) |
| `"duo_r_b"` | Red/Blue duo |
| `"std_duo_rb_w"` | Std Duo RB/W |
| `"duo_ra_ba"` | Red/Amber + Blue/Amber duo |
| `"specify_palette"` | Specify per-slot (user fills driver/passenger/center fields) |
| `"custom"` | Per-slot custom (user fills driver/passenger/center fields) |
| `"none"` | No color mapping; raw_color passed through |

### light_color_tokens
An exhaustive list of valid color token strings used in light icon filenames. If `raw_color` matches one of these tokens directly, it is treated as `legacy_uniform`.

### legacy_color_aliases
Maps non-standard color strings (as typed by users) to canonical color tokens. Example: `{"red blue": "red-blue"}`.

### SizeProfile Object
```
{
  "label": <string — human-readable profile label>,
  "maintain_aspect_ratio": <boolean>,
  "views": {
    "<view>": {"w": <number — inches>, "h": <number — inches>},
    ...
  }
}
```

`size_rule_definitions` contains the named icon-size profiles used by `parts_db.json`.
The retired `part_number_size_rules` field is retained as an empty compatibility field in
existing manifests; the render path does not read it. An unassigned light uses the `"sm"`
profile until its part type or product is explicitly assigned.

---

## parts_library.json

Manufacturer and model data for dropdowns in the Excel template.

```
{
  "schema_version": 1,
  "parts": [ <LibraryEntry>, ... ]
}
```

### LibraryEntry Object
```
{
  "display_name":      <string — matches part catalog display_name or alias>,
  "manufacturer":      <string>,
  "model_number":      <string>,
  "compatible_types":  <list[string] — display names of compatible part types>,
  "notes":             <string, optional>
}
```

- `model_number` is indexed in `ConfigBundle.parts_lib_by_model` (uppercased).
- `compatible_types` entries are canonicalized via `canonical_name()` during validation.
- Library entries are merged into template dropdowns as fallbacks when `workbook_rules.part_rules` does not have a specific entry.

---

## workbook_rules.json

Controls the structure of the Excel input template: which sections and rows appear, and what dropdown options are offered per part type.

```
{
  "schema_version": 1,
  "template_sections": [ <TemplateSection>, ... ],
  "part_rules": {
    "<display_name>": <PartRule>,
    ...
  }
}
```

### TemplateSection Object
```
{
  "section_name": <string — section header row label>,
  "parts": [ <string — display_name >, ... ]
}
```

Sections are written to the template in the order they appear in this list. An empty `template_sections` array causes template generation to fail.

### PartRule Object
```
{
  "_row":          <int, metadata only — not used by code>,
  "manufacturer":  <list[string]>,
  "models":        <list[string]>,
  "locations":     <list[string]>,
  "colors":        <list[string]>,
  "quantities":    <list[string | int]>,
  "lens":          <list[string]>
}
```

`part_rules` entries are authoritative. `parts_library` entries are merged as fallback for manufacturers and models. Dropdown option lists are deduplicated after merging.

**Inline dropdown limit**: If the combined string of options exceeds 240 characters, the list is silently truncated. Parts with many variants may lose some options.

---

## app_settings.json

Application-level settings not related to part or vehicle config.

```
{
  "schema_version": 1,
  "template_save_dir": <string — absolute path or "" for default>
}
```

| Key | Default | Description |
|---|---|---|
| `template_save_dir` | `""` | Directory where generated Excel templates are saved. Empty = workspace/input/ |

---

## project_options.json

Read-only dropdown option lists used by the project wizard and project editor. Not user-editable through the GUI (changes require editing the JSON directly).

Served at `GET /api/project-options`. The workspace copy (`workspace/config/project_options.json`) takes precedence over the bundled default (`resources/config/project_options.json`).

```
{
  "schema_version": 1,
  "build_types":      <list[string]>,
  "camera_brands":    <list[string]>,
  "lighting_brands":  <list[string]>,
  "bumper_brands":    <list[string]>,
  "cage_brands":      <list[string]>
}
```

---

## agencies.json

Workspace-root file at `workspace/agencies.json`. Not a config file — not versioned in `workspace/config/`.

```
{
  "schema_version": 1,
  "agencies": [ <AgencyRecord>, ... ]
}
```

### AgencyRecord Object
```
{
  "agency_id":      <string, UUID — auto-generated>,
  "name":           <string, required — canonical agency name>,
  "contact_name":   <string, required on creation>,
  "contact_info":   <string, required on creation — phone or email>,
  "customer_since": <string, optional — free-text year>,
  "created_at":     <string, ISO 8601>,
  "updated_at":     <string, ISO 8601>
}
```

Managed through Settings → Agencies or the project wizard's agency combo. The fuzzy search endpoint normalizes abbreviations before matching (PD → police department, SO → sheriff's office, St. → saint, etc.).

---

## sales_reps.json

Workspace-root file at `workspace/sales_reps.json`. Not a config file.

```
{
  "schema_version": 1,
  "sales_reps": [ <SalesRepRecord>, ... ]
}
```

### SalesRepRecord Object
```
{
  "rep_id":     <string, UUID — auto-generated>,
  "name":       <string, required>,
  "email":      <string, optional>,
  "phone":      <string, optional>,
  "created_at": <string, ISO 8601>,
  "updated_at": <string, ISO 8601>
}
```

Managed through Settings → Sales Reps or the project wizard's sales rep combo.

---

## Preset Files

Individual JSON files in `workspace/presets/` (bundled app) or `src/dtm_buildsheet/resources/presets/` (dev mode).

Each file represents one preset and is named `{preset_id}.json`.

### Preset Object (schema_version 2)
```
{
  "schema_version": 2,
  "preset_id":     <string, slug-style unique ID>,
  "label":         <string — auto-generated; see auto-naming rules>,
  "agency_ids":    <list[string] — [] = universal>,
  "build_types":   <list[string] — [] = any build type>,
  "vehicle_types": <list[string] — [] = any vehicle>,
  "tag":           <string, optional — suffix for General presets>,
  "parts":         <list[PartInput-like dicts]>
}
```

### Auto-Naming Rules
Label is computed by `preset_service._auto_name()`:
1. Prefix: first matched agency name, or `"General"` if `agency_ids` is empty.
2. Append build_type if exactly one value.
3. Append vehicle_types joined with `/` (e.g. `"PIU/Tahoe"`).
4. Append `" — {tag}"` if tag is non-empty.

Example: `"St. Cloud PD Patrol PIU/Tahoe"`, `"General Patrol PIU/Tahoe — Fleet23"`.

### v1 Compatibility
Existing presets without `schema_version` are treated as v1 (no `agency_ids`, `build_types`, or `tag` fields). They behave as universal presets.

---

## parts_db.json

The canonical Part Picker catalog. The full picker behavior and data-routing notes live in
[`PARTS_DB_AND_PICKER.md`](PARTS_DB_AND_PICKER.md). Product records may include a structured
console-kit definition when one QuickBooks console SKU includes multiple shop components.
Guided-system cable refresh choices live in `system_cable_refreshes`; each listed billing option
must refer to a live QB-linked SKU.

```json
{
  "products": {
    "<product_id>": {
      "manufacturer_id": "<string>",
      "model": "<string>",
      "fits_part_types": ["console"],
      "picker_primary_part_type": "<part type in fits_part_types>",
      "part_numbers": ["<PartNumber>"],
      "location_options": ["<shop-reference location>"],
      "fixed_location": "<single shop-reference location>",
      "allow_custom_location": true,
      "pa_mic_required": false,
      "handheld_mag_mic_prompt": true,
      "default_colors": ["red", "white"],
      "accessories_disabled": true,
      "console_kit": {
        "style": "<non-empty string>",
        "included": {
          "cup_holder": true,
          "oem_relocation_plate": true,
          "armrest": "printer",
          "motion_attachment": "mongoose"
        }
      }
    }
  },
  "customer_pricing": {
    "default_rule": {
      "name": "Default",
      "manufacturer_discounts": {
        "gamber_johnson": 40,
        "havis": 20,
        "pac_tool": 5,
        "santa_cruz": 25,
        "setina": 20,
        "westin": 15,
        "whelen": 38
      }
    }
  },
  "part_types": {
    "control_head": {
      "label": "Light Control Head",
      "type_id": "equipment",
      "recommended_accessories": [
        {
          "category": "control_head_harness",
          "product_id": "whelen_cctlharn",
          "when_existing_part_type": "control_head",
          "minimum_existing_count": 1,
          "message": "Recommended for a secondary control head"
        }
      ]
    }
  },
  "system_cable_refreshes": {
    "radar": [
      {
        "id": "front_antenna_cable",
        "label": "Front antenna cable",
        "part_type": "radar_cable",
        "billing_options": [
          {"product_id": "stalker_antenna_cable", "part_number": "155-2591-08"}
        ]
      }
    ]
  }
}
```

`customer_pricing.default_rule` is the shared customer sales-price schedule. Keys must reference
existing manufacturer IDs and values are percentages from 0 through 100. QuickBooks Item prices
remain list prices; this schedule is applied only when validating/creating estimates. Individual
agency files may store a sparse `pricing_overrides` object for customer-specific exceptions.

`location_options` is optional and belongs on the product when a model has more precise
shop-reference choices than its part type. `fixed_location` skips the location step entirely for
a product that can only be installed in one place. `default_colors` optionally preselects a
light's colors for a new picker selection; it never overwrites an existing line's saved colors.
`allow_custom_location` lets a product retain the Custom choice even when it has exactly one
curated location. `pa_mic_required` applies to `control_head` products and defaults to `true`;
set it to `false` for a control head that does not include a PA microphone.
`handheld_mag_mic_prompt` replaces that PA-mic setup with a simple Mag Mic yes/no choice and
adds MMSU-1 directly, without asking about a bracket accessory.
`picker_primary_part_type` is optional and chooses the product's semantic part-picker context;
it must also be listed in that product's `fits_part_types`. It applies no matter how the product
was reached, so a product with multiple physical homes consistently opens the right configurator.
`global_search_part_type` remains accepted only for backward compatibility with existing config.
`accessories_disabled` suppresses both explicit and inferred accessory options for a product.
`console_kit` is optional and belongs on the
product (not the individual SKU): it identifies the kit's selectable style and the physical
components already covered by its QuickBooks price.
`included` is a free-form object so it can describe the precise armrest or motion variant when
needed. Included components remain on the shop manifest and are intentionally skipped by estimate
resolution.

`system_cable_refreshes` is an optional per-system catalog for guided radio, radar, and camera
workflows. A user first selects the cable run, then selects the exact SKU if that run has several
lengths. Every `billing_options[]` reference must resolve to an active `part_numbers[]` entry with
`qb_item_id`; selected refreshes become nested, billable draft lines rather than manifest-only text.

`families.<family_id>.picker_part_label` is optional. It gives every part selected through that
family one shared Part-column label without changing the individual part types used for manifest
grouping, editing, or catalog compatibility.

`families.<family_id>.fixed_location` is optional. It skips the location step for every member of
that family and saves the supplied shop-reference location; a product-level `fixed_location` takes
precedence when that product has a more specific location.

`part_types.<part_type_id>.recommended_accessories` declares optional, contextual accessories for
every product in that part type. The picker shows and preselects the referenced product when the
draft already contains at least `minimum_existing_count` top-level lines with
`when_existing_part_type`; the user can still choose **None needed**. The condition is not applied
when editing an existing line, except that an already-saved accessory remains editable.

`part_types.<part_type_id>.render` owns picker-built render metadata. In addition to `asset_key`,
`images`, `size_per_view`, and `quantity_rules`, it may set `size_rule_id`, `is_fixture`,
`default_views`, `render_quantity_policy`, and `co_part_rules` with the same meaning as the
corresponding `part_catalog.json` fields. `size_rule_id` is an explicit reference to an
`asset_manifest.json` `size_rule_definitions` profile. A fixture uses the matching key in
`vehicle_layouts.json`'s `fixtures` map rather than a picker-selected location.

Products may carry the same optional `render.size_rule_id` and `render.size_per_view` fields
when one product needs a more specific setting than its part type. A product may also set
`render.center_single_at_mirror_location: true` when a one-head selection should occupy the
center of a mirrored mount while multi-head selections retain the mount's normal pattern. A concrete
`products.<product_id>.part_numbers[]` entry may additionally carry `size_rule_id` as a
last-resort SKU override. Older rows whose `part_number` contains a model name can resolve through
the product's explicit `model_aliases`. The planner resolves size in the order SKU → product →
part type → `"sm"` default. This keeps the Size Rules page tied to real canonical identities
rather than free-text matching.

---

## Common Conventions

### schema_version
All config files have a `schema_version` integer. Currently defaults to `1`. Used for future migration support.

### Location Key Casing
All location keys in `vehicle_layouts.json` must be UPPERCASE. Validation enforces this on save. User input from the Excel workbook is uppercased before lookup.

### canonical_name() and Alias Normalization
- `display_name` values in `part_catalog.json` are passed through `canonical_name()` during validation, which applies a small set of hard-coded typo corrections.
- The `display_name` is automatically added to the `aliases` list if not already present.

### Part Lookup
Parts are looked up by `display_name.upper()` or any alias (uppercased). If a part cannot be found, it is skipped with a warning rather than crashing the pipeline.

### Asset Paths
All asset paths in the manifest are stored relative to `workspace_assets_dir`. They must not contain `..` segments (asset upload enforces `Path(filename).name`).

### Saving & Validation
All saves go through `config_validation.py` before writing. Invalid data is rejected with an error response. Saves write with 2-space indentation and a trailing newline.
