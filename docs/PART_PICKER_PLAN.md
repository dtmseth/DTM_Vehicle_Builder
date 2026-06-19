# Intelligent Part Picker — Design & Implementation Plan

**Status**: Design locked. Implementation not started.
**Last updated**: 2026-06-17
**Author**: Seth + Boris
**Scope**: Replace the flat "Add Part" modal with a tree-guided intelligent picker that surfaces QB-linked part numbers, prices, and vehicle compatibility.

---

## 1. Overview

### The Problem

Today's "Add Part" modal is a flat form — 7 text fields backed by `workbook_rules.json` and `part_catalog.json`. It has no concept of:

- The parts_db.json hierarchy (Type → Section → Zone → Part Type → Product → Part Number)
- Multiple part numbers per product (e.g., ION has 16 SKUs at different prices)
- QuickBooks linkage (417 linked SKUs exist but are invisible to the build flow)
- Vehicle compatibility
- Agency brand/lens preferences

### The Goal

A guided part picker where the user answers one simple question at a time, seeing only valid options. Two entry paths lead to the same destination:

- **Guided Browse**: Navigate the hierarchy. "I need a warning light for the front."
- **Reverse Search**: Type what you know. "ION" or "Setina PB" or "partition."

Both paths converge on a SKU confirmation with price, QB status, and vehicle fit. The selection then resolves through a translation layer into individual `PartInput` records for the planner.

### Relationship to Roadmap

This work **completes the Phase 3 → Phase 4 bridge** on the official roadmap. Phase 3 built `parts_db.json` and its service layer. This plan makes it the authoritative data source for the build flow, then incrementally replaces the flat modal with an intelligent picker.

The QuickBooks parts-import work (Pass 2) runs in parallel — linking remaining manufacturers into `parts_db.json`. Every linked SKU immediately becomes visible in the new picker.

---

## 2. Design Decisions (Locked)

These are not up for debate without explicit re-discussion. Documented so we don't drift.

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Two paths, one destination.** Browse and Search both land on SKU confirmation. | Covers both "I know what I want" and "help me find it." |
| 2 | **One question at a time.** Each click is a simple choice, never a multi-field form. | Reduces cognitive load. The user always knows what they're being asked. |
| 3 | **Only ask what's ambiguous.** If data can resolve the answer, skip the question. | Partitions → only go in Interior/Forward of Cage → no zone question. Roof light bars → only roof → straight to products. |
| 4 | **≤6 placement rule.** If a filtered product set has 6 or fewer total placements across all zones, skip zone and show placements directly. | Zone is an unnecessary abstraction when there are only a few options. |
| 5 | **SKUs are immutable.** QB is the source of truth. Rules filter and search existing SKUs — they never fabricate, combine, or modify them. | Prevents data drift. If a color combo has no matching SKU, the user sees "No matching SKUs" rather than a silently wrong result. |
| 6 | **Show incompatible items, don't hide them.** "Doesn't Fit Vehicle" badge vs removing from view. | User can override. Sometimes the data is wrong or the user knows better. |
| 7 | **Flat modal stays as fallback until picker is proven.** Rewire it to parts_db immediately, remove after picker ships. | No regression. Power users keep their workflow. |
| 8 | **Color combo patterns are named presets, not code.** "Standard Split" = Driver-Red/Pass-Blue. Defined in parts_db.json, editable without a release. | Team can add patterns without code changes. |
| 9 | **Lens preference defaults to agency, overridable per part.** | Respects agency standard but allows one-off exceptions. |

---

## 3. Complete UI Flow

### Entry Points

```
Build Editor
  │
  ├─ [+ Add Part]  ──→  Picker Panel (Guided Browse)
  ├─ [🔍 Search]   ──→  Picker Panel (Search path active)
  └─ [add manually...] → Rewired Flat Modal (power user fallback)
```

### Picker Panel Layout

```
┌──────────────────────────────────────────────────────────┐
│  ← Back to Build                        ADD PART    [✕]  │
│                                                          │
│  🔍  Search parts, models, or SKUs...                    │
│                                                          │
│  [Lights ✕] [Warning ✕] [Front ✕]    ← active filters   │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │                                                      ││
│  │              SELECTION AREA                          ││
│  │         (changes based on filters)                   ││
│  │                                                      ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  Sticky footer: selected SKU · price · QB badge · [Add]  │
└──────────────────────────────────────────────────────────┘
```

### State 0 — Type Selection

Five large icon buttons for top-level types:

| Icon | Label | Description |
|------|-------|-------------|
| 💡 | Lights | Warning, scene, interior, bars, spotlights |
| 🔧 | Equipment | Cameras, radar, partitions, cages, consoles |
| 🏗️ | Structural | Push bumpers, pit bars, wing wraps |
| 🐕 | K-9 | Dog kennels, handlers, accessories |
| ⚡ | Extras | Services, misc line items |

### State 1a — Light Categories (when Lights selected)

Six buttons. Note: "Forward/Side/Rear Warning" are merged into "Warning Light." Zone is derived from placement selection later.

| Icon | Label | Description |
|------|-------|-------------|
| 🚨 | Warning Light | Flashing, colored. Zone-derived naming (Forward/Side/Rear) |
| 💡 | Scene Light | White flood/illumination |
| 🏠 | Interior Light | Prisoner cage, cargo, dome lights |
| 🚙 | Roof Light Bar | Full lightbar on roof |
| 🪟 | Visor Light Bar | Interior windshield bar |
| 🔦 | Spotlight | Directional spot beam |

### State 1b — Smart Zone/Placement Navigation

**Rule**: If total placements across all zones for the filtered product set ≤ 6 → show placements directly. Otherwise → ask zone, then placements within zone.

| Scenario | Products | Placements | Behavior |
|----------|----------|------------|----------|
| Warning Light, Front | 12 products | 8+ placements | Ask zone (Front/Side/Rear) |
| Spotlight | 3 products | 2 placements | Skip zone. Show "A-Pillar" + "Side Mirror" |
| Partition cage | 5 products | 1 placement | Skip everything. Go to product grid |
| Scene Light | 6 products | 5 placements | Skip zone. Show all 5 placements |
| Roof Light Bar | 4 products | 1 placement | Straight to products |

### State 2 — Product Grid

Product cards in a grid. Filtered by brand preference and lens type.

```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  [ION img]   │ │  [M4 img]    │ │ [Vertex img] │
│  ION         │ │  M4 SERIES   │ │  Vertex      │
│  Whelen      │ │  Whelen      │ │  Whelen      │
│  16 SKUs     │ │  7 SKUs      │ │  7 SKUs      │
│  from $178   │ │  from $237   │ │  from $144   │
│  🅀 Fits Veh │ │  🅀 Fits Veh │ │  🅀 Fits Veh │
└──────────────┘ └──────────────┘ └──────────────┘
```

Each card shows: product image (placeholder → real), model name, manufacturer, SKU count, price range, QB badge, vehicle fit badge.

Filter bar above grid: `Brand: ★ Whelen | All`  `Lens: Any | Clear | Colored | Smoked`

Lens toggle defaults to agency preference. Overrideable per part.

### State 3 — Color Configurator (Warning Lights)

Three-layer design:

```
How many lightheads?
[4]  (▸ in push bumper top tube)

Color mode per head:   ● Single   ○ Duo   ○ Trio

Preset: [Standard Split ▾]
        Standard Split (Red driver / Blue passenger)
        Standard Split + White
        Uniform Red
        Alternating Red/Blue
        ...

┌─ Pos 1 ──────────────┐  ┌─ Pos 2 ──────────────┐  ┌─ Pos 3 ───...
│  🔴 Red    🔵 Blue   │  │  🔴 Red    🔵 Blue   │  │
│  ⚪ White  🟡 Amber  │  │  ⚪ White  🟡 Amber  │  │
│  🟢 Green  🟣 Purple │  │  🟢 Green  🟣 Purple │  │
│                      │  │                      │  │
│  Selected: Red White │  │  Selected: Blue White│  │
└──────────────────────┘  └──────────────────────┘  └───────────...

Live preview (auto-scaled):
  [🔴⚪ ION]  [🔵⚪ ION]  [🔴⚪ ION]  [🔵⚪ ION]
```

**Color availability**: Only colors with matching SKUs are lit. Unavailable colors dimmed.

### State 4 — SKU Confirmation

After colors selected, matching SKUs shown. For multi-lighthead configs, SKUs grouped as a paired set.

```
Driver: Red + White  |  Passenger: Blue + White

┌──────────────────────────────────────────────────┐
│ ★ IONR-W / IONB-W     $196/ea    🅀  Fits Vehicle│
│   (Red-Wht driver, Blue-Wht passenger)           │
│                                                   │
│   IONR-W / XIONB-W     $212/ea    🅀  Fits Vehicle│
│   (X-series, higher output)                       │
└──────────────────────────────────────────────────┘

Qty per position: [1]
Total lightheads: 4   Total: $784

Build sheet name: Forward Warning 1
Description: (2) ION Red-Wht driver, (2) ION Blue-Wht passenger

                                           [Add Part]
```

### Search Path

The search bar handles intent matching:

| User types | Result |
|-----------|--------|
| "ION" | Product card for ION, showing all categories it fits |
| "IONA" | Direct SKU row for IONA, with product context |
| "partition" | Partition products, filtered to agency-preferred brand |
| "Setina PB" | Product card for Setina PB family |
| "forward warning" | Warning Light → Front, show products |
| "rear scene" | Scene Light → Rear, show products |

Search that matches a single unambiguous SKU → auto-fills everything, shows confirmation. Ambiguous → asks placement question.

---

## 4. Data Model Changes

### 4.1 PartNumber — New Fields

```python
@dataclass
class PartNumber:
    part_number: str
    friendly_name: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    qty_on_hand: int | None = None
    price_usd: float | None = None
    # ↓ NEW
    color: str = ""            # primary color: "red", "blue", "amber", "white", "green", "purple"
    secondary_color: str = ""  # for dual-color: "white", "amber"
    lens_type: str = ""        # "clear", "colored", "smoked"
    vehicle_tags: list[str]    # already exists in QB-linked data
```

### 4.2 Color Population Strategy

1. **Parse from QB Sales Description** (first): "ION T-SERIES RED/WHITE" → color=red, secondary=white
2. **Parse from SKU naming conventions** (fallback):
   - Suffix letters: R=Red, B=Blue, A=Amber, W=White, G=Green, P=Purple
   - X prefix/suffix → Smoked lens
   - Dual-color: "IONR-W" → color=red, secondary=white
3. **Smoked detection**: Sales Description contains "smoked" or "SMK", OR SKU contains X

### 4.3 EquipmentPreferences — New Field

```python
@dataclass
class EquipmentPreferences:
    lighting: str = ""
    camera: str = ""
    bumper: str = ""
    cage: str = ""
    slick_top: bool = False
    notes: str = ""
    lens: str = ""  # ← NEW: "clear", "colored", "smoked"
```

### 4.4 Color Combo Patterns (SUPERSEDED — see Chunk 6)

> **⚠️ This static-preset design was dropped on 2026-06-17.** Presets are
> replaced by mode-based selection (Uniform / Standard Split / Custom × Single /
> Duo / Trio) computed in the UI — no `color_combo_patterns` section is added to
> parts_db.json, and no preset endpoint/service methods are built. The schema
> below is kept only for historical context. See Chunk 6 for the live design.

```json
"color_combo_patterns": {
  "standard_split": {
    "label": "Standard Split",
    "description": "Driver-Red / Passenger-Blue",
    "positions": {
      "driver": {"primary": ["red"], "secondary": []},
      "passenger": {"primary": ["blue"], "secondary": []},
      "center": {"primary": [], "secondary": []}
    }
  },
  "standard_split_white": {
    "label": "Standard Split + White",
    "description": "Driver-Red-White / Passenger-Blue-White",
    "positions": {
      "driver": {"primary": ["red"], "secondary": ["white"]},
      "passenger": {"primary": ["blue"], "secondary": ["white"]},
      "center": {"primary": [], "secondary": []}
    }
  },
  "uniform_red": {
    "label": "Uniform Red",
    "positions": {
      "driver": {"primary": ["red"], "secondary": []},
      "passenger": {"primary": ["red"], "secondary": []},
      "center": {"primary": ["red"], "secondary": []}
    }
  },
  "alternating_rb": {
    "label": "Alternating Red/Blue",
    "pattern": "alternating",
    "colors": [["red"], ["blue"]]
  }
}
```

---

## 5. Translation Layer

### 5.1 Problem

One user selection can produce multiple `PartInput` records. Example: "ION, 4 lightheads, alternating Red/Blue on push bumper" → 4 PartInputs, each with its own part_number, color, and slot role.

### 5.2 Resolver

New module: `planning/sku_resolver.py`

```python
def resolve_part_selection(selection: PartSelection, vehicle: VehicleType) -> list[PartInput]:
    """
    selection has: product_id, placement location, lighthead_count,
                   color selections per position, quantity_per_position
    Returns: list[PartInput] for the planner
    """
```

### 5.3 Build Sheet Description

The resolver produces a consolidated description:

```
Input: 4x ION, push bumper top tube, alternating Red/Blue
Output:
  (4) ION: Alternating Red/Blue, Push Bumper top tube
  → 4 PartInput records: IONA, IONB, IONA, IONB
```

The existing planner and renderer don't change. They process `PartInput` records as always. The resolver just produces more of them with richer data.

---

## 6. Implementation Chunks

### Chunk 1 — Data Foundation
**Goal**: PartNumber fields + lens preference + color population. Pure backend.

| File | Change |
|------|--------|
| `domain/parts_db_models.py` | Add `color`, `secondary_color`, `lens_type`, `qb_item_id`, `qb_unit_price`, `qb_sku`, `qb_inactive`, `vehicle_tags` to PartNumber |
| `domain/project_models.py` | Add `lens: str = ""` to EquipmentPreferences |
| `app/services/parts_db_service.py` | Update `_hyd_part_number` to include all new fields |
| `tools/qb_apply_links.py` | Parse color from Sales Description + SKU patterns; populate new fields. Only tags light products (checks `fits_part_types` against `type_id=lights` part_types to avoid false positives on non-light SKUs). |

**Dependencies**: None. First chunk, no blockers.
**Status**: ✅ Done — 1594 tests pass. 173 SKUs with color, 193 with lens_type. Part Manager tree browser updated to show color/lens/price/QB per SKU. Verified in UI.

### Chunk 2 — Rewire Flat Modal
**Goal**: Close Phase 3. Make flat modal read from parts_db. Add price/QB/vehicle badges.

| File | Change |
|------|--------|
| `app/routes/parts_db.py` | New `GET /api/parts-db/manifest-data?part_type=...` endpoint. Returns manufacturers (with IDs), part_numbers (with price/QB/color), locations. Direct lookup by part_type label → part_type_id → products. Falls back to legacy index + workbook_rules. |
| `ui/js/manifest_editor.js` | `_mePopulateDataLists` keeps catalog names for part type dropdown (planner compatibility). `_meFetchManifestData` calls new endpoint, strips trailing numbers ("Forward Warning 1" → "Forward Warning") to match parts_db labels. `_meUpdateManufacturers` / `_meUpdatePartNumbers` / `_meUpdateLocations` all read from parts_db with workbook_rules fallback. Added Product dropdown between Manufacturer and Part Number. Model/SKU dropdown shows `$price` and `🅀` badge. |
| `ui/index.html` | Added Product field to modal. Renamed "Model #" labels to "Part #". Moved Color field to Location/Qty row. |

**Dependencies**: Chunk 1
**Status**: ✅ Functional backup. QB data, prices, product dropdown all work. Modal lampshades acting as fallback until picker ships.

### Chunk 3 — Picker Shell + Type Selection
**Goal**: Structurally replace the modal. "Add Part" opens the picker panel. Type buttons + search bar work.

| File | Change |
|------|--------|
| `ui/index.html` | Added `#picker-panel` overlay with header, search bar, filter chips area, body area, sticky footer. |
| `ui/styles.css` | Picker panel, type grid, product grid, chip, and footer styles. |
| `ui/js/part_picker.js` | New file. `openPicker()` / `pickerClose()`. Renders 5 Type buttons loaded from `/api/parts-db/types`. Filter chips update on type selection. Footer shows selection path. |
| `ui/js/manifest_editor.js` | `addPart()` opens picker instead of modal. `addPartManual()` opens old modal via "add manually..." link. |

**Dependencies**: Chunk 2
**Status**: ✅ Panel opens, Type buttons render, filter chips work. "add manually..." fallback works.

### Chunk 4 — Smart Navigation (Categories + Zones)
**Goal**: Category buttons for Lights. Zone/placement navigation. Category→zone endpoint.

| File | Change |
|------|--------|
| `app/routes/parts_db.py` | New `GET /api/parts-db/category-zones?type=...&category=...` endpoint. Finds part_types by type+label keyword match, extracts unique zones from tree_positions. |
| `ui/js/part_picker.js` | 6 category buttons hardcoded for lights (Warning, Scene, Interior, Roof Bar, Visor Bar, Spotlight). Categories render after type selection. Zone buttons render with zone-specific icons. Skip-zone logic for Roof/Visor/Interior categories. |

**Dependencies**: Chunk 3
**Status**: ✅ Categories and zones navigate. Non-lights types go directly to products.

### Chunk 5 — Products Grid
**Goal**: Product cards with prices, QB badges, SKU counts.

| File | Change |
|------|--------|
| `app/routes/parts_db.py` | New `GET /api/parts-db/zone-products?type=...&zone=...` endpoint. Two modes: (1) `group=zone` returns zones with product counts, (2) zone-specific returns product cards with manufacturer, SKU count, price_min, qb_count. Empty zone returns all products for the type. |
| `ui/js/part_picker.js` | `_pickerRenderProducts()` fetches products and renders card grid. Each card shows model letter, model name, manufacturer, SKU count, price range, QB badge. |

**Dependencies**: Chunk 4
**Status**: ✅ Done. Product grid renders 26 products for lights/front with prices and QB badges. Bug fixed: the `zone-products` handler seeded `price_min = p.price_usd`, but `price_usd` lives on `PartNumber`, not `Product` — every call raised `AttributeError`, returned a 500 (HTML), and the JS `api()` helper threw on the non-JSON body, landing in the "Error loading products" catch. Fixed by deriving `price_min` purely from the part numbers. `api()` now throws a status-bearing error on non-JSON responses, and the picker catch blocks `console.error` so the next backend 500 is diagnosable.

### Chunk 6 — Color Configurator
**Goal**: Mode-based color selection for warning lights. Live lighthead preview row.

**DESIGN CHANGE (2026-06-17):** the static `color_combo_patterns` preset table (§4.4)
is **superseded** by two selection axes — no JSON presets, no preset endpoint/service
methods. The only hardcoded convention is "red = driver, blue = passenger."

- **Colors per head**: Single / Duo / Trio (1/2/3 color slots).
- **Mode**:
  - **Uniform** — pick the color(s); applied to every head.
  - **Standard Split** — primary auto by side (red driver / blue passenger),
    **contiguous halves** (4 heads = R R B B). Even counts only; Single & Duo only
    (Trio collapses to Uniform). Duo secondary is one pick, same on both sides.
  - **Custom** — per-head multi-select, up to `colorsPerHead` colors each.
- Only colors present in the product's SKUs are selectable; others dimmed.

| File | Change |
|------|--------|
| `ui/js/part_picker.js` | `_pickerRenderColorConfig()` + helpers: count stepper, Single/Duo/Trio + mode segmented controls, swatch rows (single-select for uniform/split, multi-select for custom), live preview row. Reuses existing `GET /products/{id}/part-numbers` for color availability — no new endpoint. Resolved per-head colors stored in `_pickerState.config` for Chunk 7. |
| `ui/styles.css` | Configurator, segmented control, stepper, swatch, and lighthead-preview styles. |

**Dependencies**: Chunk 5 (product must be selected before color config)
**Status**: ✅ Done — configurator renders for color-bearing products (e.g. ION: 16 SKUs, red/blue/amber + white). All three modes work; only available colors selectable; preview updates live. Footer "Add" stays disabled until Chunk 7 wires SKU resolution. **Not yet verified in the running app.**

> **⚠️ Carry into Chunk 7:** SKUs hold at most **two** colors (`color` + `secondary_color`) — there is no tertiary field. A true 3-color "trio" SKU is not representable in the current schema. The configurator allows Trio selection, but SKU matching must decide how to handle it (multiple SKUs per head? schema add? reject trio at match time?). Decide before building `match_skus_by_colors()`.

### Chunk 4.5 — Placement step (zone → placement → product)
**Goal**: Insert a placement selection between zone and product. **Lights** pick a
**physical location** filtered by the selected zone; **non-lights** pick a
**part_type** (which pins naming and scopes products).

| File | Change |
|------|--------|
| `app/routes/parts_db.py` | New `GET /placements?type=&category=&zone=`. Lights → physical locations from the `placements` table via a tree-zone→placement_zone map (`_ZONE_TO_PLACEMENT_ZONES`, `_CATEGORY_TO_PLACEMENT_ZONES`). Non-lights → part_types of the type as placement options. Also added a `part_type` filter param to `zone-products` so non-lights products scope to the chosen part_type. |
| `ui/js/part_picker.js` | `_pickerRenderPlacements()` between zone and product; placement chip + footer + cascade-clear removal; products URL scopes by `part_type` when set. |

**Status**: ✅ Done — lights/front shows 24 physical locations; equipment shows its part_types. Backend verified; **not yet eyeballed in the app**.

> The tree-zone→placement_zone map is hardcoded in the route (judgment mapping).
> Candidate to move into parts_db.json `placement_zones` as a `tree_zone` field so
> the team can edit it without a release.

### Chunk 7 — SKU Table + Translation Layer
**Goal**: Show matched SKUs. Resolve selection into PartInput records. Build sheet descriptions.

| File | Change |
|------|--------|
| `ui/js/part_picker.js` | `_pickerRenderSkuConfirm()` / `_pickerDrawSkuConfirm()` — per-combo SKU dropdown (output/lens variants, cheapest default), qty, editable name + location, live total, unmatched-combo warning. `_pickerDoAdd()` resolves → POSTs rows to `/api/draft/{id}/part` → refreshes manifest. "Find matching SKUs →" button added to the configurator. |
| `planning/sku_resolver.py` | **New file.** `match_heads()` groups heads by color set (set-equality on color+secondary_color), finds matching SKUs, flags unmatched (incl. trio). `build_rows()` → PartInput-shaped rows (collapsed by SKU, summed qty) + consolidated description. Pure, no I/O. |
| `app/routes/parts_db.py` | `POST /match-skus` and `POST /resolve-selection` (both wrap the resolver). |
| `tests/test_sku_resolver.py` | 9 tests — single/duo/split matching, order-insensitivity, lens filter, trio unmatched, row collapsing, qty/blank skipping. |

**Trio decision:** trio is **rejected at match time** — a 3-color head produces no
SKU match and shows an "⚠️ No SKU matches (3-color heads aren't a single SKU)"
warning. No schema change. Multi-SKU-per-head can be revisited later if needed.

**Dependencies**: Chunk 6
**Status**: ✅ Done — full pipeline verified end-to-end against ION (4-head split duo → IOND ×2 / IONE ×2, $712, "(2) ION Red/White, (2) ION Blue/White — Push Bumper"). 1603 tests pass. **Frontend not yet eyeballed in the running app.** No-color products (most non-lights) still show a placeholder — a plain SKU-list add for those is a follow-up.

### Chunk 8 — Search Path
**Goal**: Reverse lookup from search bar.

| File | Change |
|------|--------|
| `ui/js/part_picker.js` | Search input handler, intent matching, direct SKU jump, auto-fill |
| `app/routes/parts_db.py` | `search` endpoint (fuzzy match across products, SKUs, models) |
| `app/services/parts_db_service.py` | `search_parts(query) → list[SearchResult]` |
| Tests | Search matching tests |

**Dependencies**: Chunk 3 (search bar exists)
**Status**: 🔴 Not started

### Chunk 9 — Polish + Remove Flat Modal
**Goal**: Images, vehicle diagrams, animation. Remove the old modal.

| File | Change |
|------|--------|
| `ui/index.html` | Remove flat modal HTML (or comment out) |
| `ui/js/manifest_editor.js` | Remove `addPart()`, `openPartEditModal()`, `savePartEdit()`, `meCancelModal()` and associated wiring |
| `ui/js/part_picker.js` | Real product images, vehicle diagram in zone picker, transitions |
| `ui/css/styles.css` | Final polish |
| Tests | Confirm no regressions from modal removal |

**Dependencies**: Chunks 1-8 confirmed working
**Status**: 🔴 Not started

---

## 7. Current State Inventory

What exists before we start:

| Component | State |
|-----------|-------|
| parts_db.json | ✅ 227 products, 106 part types, 5 types, 2 sections, 8 zones |
| parts_db_service.py | ✅ All query methods built, 3-tier fallback in place |
| Part Manager tree browser | ✅ 691 lines, admin tool at Settings → Advanced → Part Manager → Database v2 |
| QB-linked SKUs | ✅ 417 (251 Whelen, 160 Setina, 6 Arctic Start) |
| QB items cache | ✅ workspace/quickbooks_items_cache.json |
| Flat modal (manifest_editor.js) | ✅ 381 lines, reads workbook_rules + part_catalog |
| PartNumber.color field | ✅ Added — 219 of 546 part numbers populated |
| PartNumber.lens_type field | ✅ Added — 42 smoked, 7 clear identified |
| EquipmentPreferences.lens field | ✅ Added |
| Picker panel HTML | ❌ Doesn't exist |
| Color combo patterns | ❌ Doesn't exist |
| SKU resolver | ✅ `planning/sku_resolver.py` — match_heads / build_rows (Chunk 7) |

---

## 8. Constraints & Invariants

- **PYTEST_CURRENT_TEST guards**: All cloud I/O tests must respect these.
- **save_config_file for parts_db.json writes**: Must use `--push-to-cloud` or `save_config_file()` — direct writes are reverted by SharePoint sync.
- **Pre-launch command**: Before opening dev app after any parts_db.json change, run: `cd /Users/skreev/Desktop/DTM_BuildSheet_POC_v7 && for f in tools/qb_links/*.json; do .venv/bin/python3 tools/qb_apply_links.py "$f" --write; done`
- **Venv required**: All Python commands use `.venv/bin/python3`.
- **Route pattern**: Every route module exports `route_xxx(handler, method, path, body, paths) → bool`.
- **JS patterns**: Modal pattern = `.modal-overlay` + `.modal` + `classList.add/remove("open")`. Each save button owned by exactly ONE IIFE.
- **Cache-Control: no-store** on QB response routes.

---

## 9. Open Questions

| # | Question | Status |
|---|----------|--------|
| 1 | Do QB Sales Descriptions reliably contain color info for parsing? | ⬜ Verify during Chunk 1 |
| 2 | Are there standardized SKU letter patterns for all manufacturers, or only Whelen? | ⬜ Verify during Chunk 1 |
| 3 | Do QB items distinguish smoked lenses with "X" in SKU consistently? | ⬜ Verify during Chunk 1 |
| 4 | Should the color combo patterns list include "Solid Blue," "Solid Amber," etc.? | ⬜ Owner to confirm |
| 5 | Real product images — when available, what format/naming convention? | ⬜ Owner to provide |

---

## 10. Changelog

| Date | Change |
|------|--------|
| 2026-06-17 | Initial design locked. All 9 chunks defined. |
| 2026-06-17 | Chunks 1-5 implemented. Chunks 1-4 working. Chunk 5 backend works (26 products for lights/front verified via Python), but JS product fetch silently fails. |
| 2026-06-19 | ⭐ Direction change: placements move to the **category level** (all warning lights share one placement pool; unlimited instances; product/location restrictions become explicit exceptions). Breaks the legacy catalog-slot / per-name `default_views` model that was capping the picker. Full design + required work + open questions Q5–Q7 in docs/PICKER_TRANSLATION_AUDIT.md §8. Next session is a fresh start (see docs/NEXT_SESSION_PROMPT.md). No code changed this turn — investigation + docs only. |
| 2026-06-18 | Overnight schema-translation audit (see docs/PICKER_TRANSLATION_AUDIT.md). Found the real "schema didn't transfer" cause: **parts_db.json edits were being reverted by SharePoint sync** (categories wiped to 0; colors partially reverted) — direct json.dump writes don't stick. Re-applied categories + re-ran the color parser via the sanctioned `save_config_file` path (22 categories, 164 colored SKUs, 16 trios restored). Fixed remaining placement-load failures: excluded non-rendering part_types (Tail/Headlight Flasher, render_kind=none) from the location step — comprehensive audit now **142/142 offered placements load, 0 fail** across all 64 light products. Diagnosed light-size issue (31 models fall through to default "sm" because they lack `part_number_size_rules`); did NOT guess sizes — flagged for owner. Confirmed bracket dependencies already translated correctly as `accessory_of`. Open questions Q1 (persist parts_db past sync — BLOCKER), Q2 (size meaning + values), Q3 (non-rendering parts add path) documented. 1621 tests pass. |
| 2026-06-17 | Picker iteration 5 — fixed "placements don't load in preview" (the schema-translation bug). Two root causes: (a) offered locations whose layout coords live in a view NOT in the part's catalog `default_views` (planner only searches default_views, e.g. PUSH BUMPER MOUNT's coords are in the *side* view but Forward Warning renders *front*), and (b) names from parts_db `workbook_label_pattern` that don't match the catalog `display_name` (front_side_warning pattern "Front Side Warning {n}" vs catalog "Front Side Warning"). Fix: `_resolve_product_locations` now reads `part_catalog.json` — offers only locations present in the vehicle layout within the part's `default_views`, and tags each with the exact catalog `display_name`s. The picker names parts from those catalog names (lowest unused, e.g. Forward Warning 1→2). Endpoint takes `&vehicle=`. Verified every offered placement loads: ION 52/52, M4 4/4, VERTEX 21/21, scene 1/1. Also: hovering one mirrored dot now highlights its pair. 1621 tests pass. No change to placement settings. |
| 2026-06-17 | Picker iteration 4 (mirrored dots + part-aware placements). (1) **Mirrored/spread dots** — ported `getSlotPositions` verbatim (`_pickerSlotPositions`) so a location with pattern:mirror/horizontal draws all its slot dots (driver+passenger, rows) exactly like the placement settings preview, instead of one centered dot. Clicking any slot selects that location. (2) **Placements are now product-aware** — new product-scoped `category-locations?product=` uses the schema's `fits_part_types` (all 227 products carry it) so a selected lighthead only offers placements it can actually take; warning lights no longer show spotlight/light-bar/interior spots. Per fit part_type, locations come from its workbook rule, else a tightened tree-zone fallback. Tightened `prisoner_area→rear_interior` (cargo windows stay as side warnings; dash/headliner dropped) and excluded light-bar placements from warning/scene fallback. Verified: ION warning = 40 valid spots w/ cargo windows, no leakage; M4 = 5; PIONEER scene = scene-only. Did NOT change placement settings. 1621 tests pass. |
| 2026-06-17 | Picker iteration 3 (dot alignment + sort + tooltip). (1) **Dot positioning** now matches placement settings — overlay is sized to the actual rendered image box via getBoundingClientRect (contain box), so dots land exactly where the layout coords put them. (2) This also fixed the **"parts land in the wrong spot"** report: verified the planner already places picker parts at the exact layout coords (it uppercases the location key and matches vehicle_layouts — both "TOP TUBE"/"Top Tube" resolve to front x0.5/y0.435, same as the old workbook parts). The real cause was mis-placed picker dots → clicking selected a different location than intended; fixed by (1). No change to placement settings. (3) **Matching products sort to the top** and re-sort live as filters/colors change (match-first, then preferred brand, then model). (4) **Instant custom tooltip** (14px bold) replaces the slow native title on hover. 1621 tests pass. |
| 2026-06-17 | Picker redesign iteration 2 (feedback on the two-pane build). (1) **Left pane is now a click-through wizard** — one page per step (Part type → Light type → Colors & options) with breadcrumbs + Back, instead of one long scroll; clicking an option advances. Right product list still narrows live. (2) **Right pane: SKU override** — a selected color product shows each color combo with a dropdown of SKU variants (matches first, then "(other)" SKUs), so the user can change the matched SKU or pick something else; choices keyed by color-set and applied in resolve. Brand refine bar added above the list. (3) **Location fixes** — view pills now highlight on select; internal views appear only when the category has interior placements; interior locations render as **buttons** (no image) while exterior stay image+dots; interior dots excluded from exterior views. (4) **Footer lighthead preview** — a row of stacked color swatches, one per lighthead in chosen order, showing what's about to be added. Front/rear dot clustering is source-data (those views stack placements on the centerline), not a render bug. 1621 tests pass. Still a blind build — needs eyeballing. |
| 2026-06-17 | Major picker UI redesign (two-pane + tabs + dot-picker). Per owner direction: (1) **Two-pane Part tab** — left = live filters (search, type, category, brand, lens, and the full color config: count/mode/swatches); right = always-visible product list that narrows live, each product expandable to its SKUs, single result auto-expands, matching SKUs highlighted (no-exact-match shows all). (2) **Location tab** = vehicle diagram (`/assets/vehicles/{veh}_{view}.png`) with clickable dots from `vehicle_layouts.json`, view pills, hover label; only category-relevant located placements show; click selects + resolves part_type/name. (3) **Tabs Part/Location**, revisitable; Add enabled once product + location set. (4) **Edit reuses the same picker** (product preselected by SKU). New `/category-skus` endpoint returns products+SKUs in one call. No typing except search. Full rewrite of part_picker.js + new HTML/CSS. 1621 tests pass. **Blind build — needs browser eyeballing; known rough edges: edit doesn't pre-select location/name yet, non-lights location list is broad, internal views have no dots.** |
| 2026-06-17 | Categorization + flow reorder + edit-through-picker (rest of the picker-review feedback). (1) Added explicit `category` field to PartType (model + hydration + parts_db data for 22 light part_types: warning/scene/interior/interior_bar/roof_bar; brackets+preemption left uncategorized). Categorization is by **usage, not mounting** — cargo-window stays Warning, prisoner_area no longer surfaces as a warning step. 6 categories (visor bar folded into interior bar). (2) Reordered the lights flow to **category → product → SKU/color → location-last** (matches non-lights). Products now scoped by the category field across all zones; the zone step is gone (fixes the "locations don't match zone" bug). New `/category-locations` endpoint resolves each location → part_type for naming (cargo window → Side Warning, pit bars → Pit Bar Warning, etc.). (3) Editing a part now opens the **picker panel** (`_pickerOpenEdit`), not the old flat modal, preserving components. Verified end-to-end: category=warning → 38 products → ION duo-split matches IOND/IONE → TOP TUBE → "Forward Warning 1" → planner renders as light. 1621 tests pass. |
| 2026-06-17 | SKU color/lens parser rewrite + trio support (data foundation for the picker-review feedback). Audited 251 linked Whelen SKUs: old parser left 28% blank with 22 clear mis-parses (dashes "R-W", no-separator "BAW", trios "R/B/W", plus false positives like TCRWX2→white). Rewrote `_parse_color_from_item` in qb_apply_links.py to handle spelled-out/abbrev/initial colors with `/ - space none` separators, parenthesized colors, DUO/TRIO/SPLIT-gated bare codes, WeCanX skip, and conservative smoked detection. Added `tertiary_color` to PartNumber (+ hydration, + sku_resolver matching) so trios store/match. Re-applied to parts_db.json: 164/251 colored (rest legitimately colorless — antennas/sirens/brackets/WeCanX bars), 16 trios captured. 17 parser tests; 1621 total pass. **Still TODO from this feedback round:** explicit `category` field + usage-based recategorization (drop prisoner_area from warning, cargo→side, interior-bar split, 6 categories), flow reorder (category→product→SKU→location-last), edit-through-picker. |
| 2026-06-17 | Preview-not-rendering fix + caret UX. **Root cause:** the planner/preview only renders a part whose `name` matches the part_type's `workbook_label_pattern` ("Forward Warning 1" renders; "Forward Warning" → render_kind=none; "Front Scene" renders but "Front Scene 1" doesn't). The picker was emitting bare zone-derived names. **Fix:** `/placements` now attaches `part_type_id` + `name_pattern` + `base_label` to each option (lights: location→part_type via legacy map, else the zone's primary part_type like Forward Warning; non-lights: the part_type itself). The picker names parts via the pattern, appending the next sequence number from the draft when it contains "{n}". Verified: picker-named "Forward Warning 1" renders as a light with correct colors. Lights still scope products by zone (part_type used for naming only). Caret: whole parent row is now clickable to expand, caret enlarged. |
| 2026-06-17 | Feedback round on the ION flow. (1) "Find matching SKUs" / "Add to build" moved to the sticky footer (was below the fold). (2) Lights product grid now scoped by category — warning vs scene no longer mixed (`zone-products` honors a `category` keyword filter). (3) Products sorted by agency brand preference (`window._PT.viewProject.preferences.lighting_brands`), then QB-linked, then SKU count. (4) **Model change:** the picker now adds ONE simple parent line, not N rows. Concrete SKUs become `components` on the `DraftPart` — shown as expandable child rows in the manifest, persisted in the draft, but NOT passed to the planner/renderer (`draft_to_project_input` drops them), so the build sheet + preview see the same simple line they always have. `sku_resolver.build_rows` rewritten to emit the parent + components + color fields (raw_color / driver / passenger from the color mode). |
| 2026-06-17 | Chunk 4.5 (placement step) + Chunk 7 built. Placement: lights pick physical location by zone, non-lights pick part_type. Chunk 7: `sku_resolver.py` (match_heads/build_rows) + match-skus/resolve-selection endpoints + SKU-confirmation UI + Add-to-build wiring. Trio rejected at match time. 9 resolver tests; 1603 total pass. Frontend not yet eyeballed. |
| 2026-06-17 | Chunk 6 built. Static `color_combo_patterns` presets (§4.4) dropped in favor of mode-based selection (Uniform / Standard Split / Custom × Single / Duo / Trio). Standard Split = contiguous halves, even counts only, secondary same both sides. Configurator reuses the existing part-numbers endpoint for color availability — no new backend. Flagged trio↔2-color-SKU schema gap for Chunk 7. |
| 2026-06-17 | Chunk 5 bug found and fixed. Root cause was server-side, not JS: `zone-products` accessed `Product.price_usd` (a `PartNumber`-only field) → `AttributeError` → 500 → non-JSON body → `api()` `.json()` threw → "Error loading products" catch. Fixed the attribute access; hardened `api()` to throw status-bearing errors on non-JSON; added `console.error` to picker catches. Chunk 5 now ✅. |

## 11. Debugging Notes for Chunk 5 (RESOLVED)

**The bug was server-side, not in the JS.** The earlier theory (JS race condition / CORS / pywebview caching) was wrong — the JS chain was correct the whole time.

**Root cause:** the `zone-products` handler seeded `price_min = p.price_usd` where `p` is a `Product`. `price_usd` is a field on `PartNumber`, not `Product` (see `domain/parts_db_models.py`). Every call raised `AttributeError`, the route returned a 500 with an HTML error page, and the JS `api()` helper (`.then(r => r.json())`) threw parsing the non-JSON body — landing in `_pickerRenderProducts`'s `catch`, which displays "Error loading products."

**Why zones worked but products didn't:** `category-zones` never touches `Product.price_usd`, so it returned valid JSON. Only `zone-products` hit the bad attribute, which is why navigation worked right up to the final step.

**Why "verified via Python" was misleading:** the Python check exercised the *service* methods (`list_products_for_part_type`), which are healthy. It never ran the *route handler*, where the bad attribute access lived. When debugging a route, test the route handler's code path, not just the service.

**The fix (all three landed):**
1. `app/routes/parts_db.py` — derive `price_min` from `p.part_numbers` only (`price_min = None` seed, no `p.price_usd`).
2. `ui/js/api.js` — `api()` now throws a status-bearing error (`"<path> → <status> <statusText> (non-JSON response)"`) when the body isn't JSON, instead of a silent generic failure. Non-2xx responses that carry a JSON body still resolve so callers can read `res.error`.
3. `ui/js/part_picker.js` — all three picker catch blocks `console.error(e)` so the next backend 500 is visible in the console.

**Lesson for future chunks:** a generic "Error loading X" in the picker almost always means a backend 500 returning non-JSON. Check the server log / network tab first; the JS catch is rarely the actual fault.
