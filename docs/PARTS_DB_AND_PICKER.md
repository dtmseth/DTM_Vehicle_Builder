# Parts DB & Intelligent Part Picker

**Single entry point for the unified parts catalog and the build-flow part picker.** Merges the
former `PART_PICKER_PLAN.md` (design + chunk status), `PICKER_TRANSLATION_AUDIT.md` (enduring
lessons), `PENDING_QB_PARTS.md`, `TRACER_LIGHTHEAD_SELECTION.md`, and `PHASE5_ACCESSORIES_DESIGN.md`.

**Related**: [QUICKBOOKS.md](QUICKBOOKS.md) (the SKU/price source), [ROADMAP.md](ROADMAP.md)
(where this sits — Phase 3/4), [DATA_MODELS.md](DATA_MODELS.md), [CONFIG_SCHEMA.md](CONFIG_SCHEMA.md).
Historical blow-by-blow changelogs live in [archive/](archive/).

> **Foundation note:** `parts_db.json` now references parts at **SKU granularity** (real vendor part
> numbers + QB pricing), not just product name / part type. That is a fundamentally different basis
> than the legacy `workbook_rules.json` / `part_catalog.json` model. The Part Picker and every
> downstream consumer depend on real QB data being in the DB — which is why the QB import is the
> *foundation* of this work, not a side track.

---

## 1. The `parts_db.json` schema (as actually built)

The ROADMAP §7 sketch is an early draft; this is the live shape. Authoritative copy:
`src/dtm_buildsheet/resources/config/parts_db.json`. Service: `app/services/parts_db_service.py`
(23 typed queries + 3-tier fallback). Routes: `app/routes/parts_db.py` (`/api/parts-db/*`).
Models: `domain/parts_db_models.py` (13 dataclasses). Validation: `config/schemas.py::_validate_parts_db`.

**Six-level hierarchy** (Type → Section → Zone → Part Type → Product → Part Number) plus
cross-cutting catalogs (manufacturers, tags, placements, accessory categories):

| Key | What it is |
|-----|-----------|
| `types` | Top-level kind: lights, equipment, structural, k9, extras |
| `sections` | Build-sheet grouping (presentation) |
| `zones` / `sub_zones` | Where on the vehicle (drives role naming for lights) |
| `part_types` | The "slot types" (Forward Warning, Radar, …). Carry `type_id`, `tree_positions[{section,zone,sub_zone}]`, `tag_ids`, `max_count`, `accessory_of`, `accessory_category`, `accessories[]`, `allowed_products[]`, `allowed_placements[]`, `workbook_label_pattern`, `sequence_scope`, `category` (warning/scene/interior/interior_bar/roof_bar) |
| `products` | A catalog product (e.g. ION). Carry `model`, `manufacturer_id`, `description`, `fits_part_types[]`, `tag_ids[]`, `accessories[]`, `part_numbers[]` |
| `part_numbers` | A concrete SKU under a product. Carry `part_number`, `friendly_name`, `color`/`secondary_color`/`tertiary_color`, `lens_type`, `vehicle_tags[]`, `price_usd`, QB fields (`qb_item_id`, `qb_sku`, `qb_sales_description`, `qb_unit_price`, `qb_inactive`, `qb_last_synced`), `qb_pending`, `options{}` |
| `manufacturers` | `label`, `website` |
| `tags` | `label` (vehicle/attribute tags) |
| `placements` | Physical location vocabulary |
| `accessory_categories` | Picker-facing group vocabulary (for example `lighthead`, `bracket_mount`, `cable`, and the printer-specific `printer_mount`, `printer_power_cable`, `printer_usb_cable`) |
| `system_cable_refreshes` | Guided radio/radar/camera refresh choices. Each choice maps only to live QB-linked SKU options, and can expose a length-specific follow-up choice. |

**Three orthogonal axes** (never conflate): `part_type.category` = *what it is* · zone (via a
placement's zone) = *where on the vehicle* · `product.build section` = *how it groups on the sheet*.

**Current population** (approx, post full-QB import 2026-07-01): 5 types · 2 sections · 8 zones ·
62 manufacturers · **932 products** · 113 part_types · 59 placements · **~1,290 QB-linked SKUs**
(the full sandbox QBO inventory). ~673 of those products have **no part-type home yet** — the
curation queue (filter the SKU grid to "— No part-type —"). Every part_type now carries a
`location_mode` + (text mode) `location_options`. Import tool: `tools/qb_import_all.py`.

**Write invariant:** all `parts_db.json` writes go through `save_config_file(...)` (or
`tools/qb_apply_links.py --write`, or `tools/qb_inventory_import*.py --push-to-cloud`). A direct
`Path.write_text` / `json.dump` is **reverted by the 60s SharePoint sync**. To persist to cloud the
save must happen while signed in (direct-mirror + proposal). This was the real "schema didn't
transfer" symptom — the code translated fine; the *data* kept getting reverted.

---

## 2. The Intelligent Part Picker

Replaces the flat "Add Part" modal with a tree-guided picker surfacing QB-linked part numbers,
prices, vehicle compatibility, and color configuration. Two entry paths, one destination:
**Guided Browse** ("warning light for the front") and **Reverse Search** ("ION" / "Setina PB").
Both converge on SKU confirmation or a guided-system workflow → resolve into `PartInput` records
via the translation layer.

**Status: actively usable and under owner rebuild testing.** The original Chunks 1-8 are built.
Current work is polish, guided-system coverage, data quality, and retiring old fallback surfaces
once the owner rebuilds the real projects.

| Chunk | Goal | Status |
|-------|------|--------|
| 1 — Data foundation | PartNumber color/lens fields + color population from SKU/QB description | ✅ Done |
| 2 — Rewire flat modal | Flat modal reads parts_db; price/QB/product badges | ✅ Done (kept as power-user fallback) |
| 3 — Picker shell + type selection | `#picker-panel`, type buttons, search bar | ✅ Done |
| 4 — Smart navigation | Light categories + zone/placement nav | ✅ Done |
| 4.5 — Placement step | Lights pick physical location by zone; non-lights pick part_type | ✅ Done |
| 5 — Products grid | Product cards w/ price, QB badge, SKU count | ✅ Done (the "Chunk 5 JS bug" was a server-side `AttributeError`, fixed) |
| 6 — Color configurator | Mode-based color selection (Uniform / Standard Split / Custom × Single/Duo/Trio) | ✅ Done |
| 7 — SKU table + translation | `planning/sku_resolver.py` (`match_heads`/`build_rows`); `/match-skus`, `/resolve-selection`; SKU-confirm UI | ✅ Done |
| 8 — Search path | Reverse lookup from search bar | ✅ Done; defaults to all categories/brands/vehicle tags |
| 9 — Polish + remove flat modal | Images, vehicle diagrams, remove the old modal | 🟡 In progress |

**Sidebar browse (shipped 2026-07-09, extended 2026-07-14/15):** the sidebar is a server-derived
`category → family → part_type` accordion — `GET /api/parts-db/browse-tree` — every category/family
expands inline, and headers are also selectable filters. Every visible part type is browsable, not
just Lights. Picking a light family leaf hands off to the category/color/SKU flow; a non-light leaf
narrows `category-skus` via `type`, `family`, or `part_type` query params. Filled part types show a
green manifest-highlight dot (matches on the `part_type` field carried by picker-added `DraftPart`s).

**Search behavior (owner-corrected 2026-07-15):** typing in the picker search box searches across
all categories, brands, vehicle tags, product names, SKU text, and sales descriptions by default.
The "Current filters only" checkbox scopes search back to the selected category/family/brand/vehicle
filters when the user wants to stay inside the current browse context.

Key files: `ui/js/part_picker.js` (panel UI), `app/routes/parts_db.py` (endpoints),
`planning/sku_resolver.py` (translation), `ui/js/manifest_editor.js` (entry + fallback modal).

**Locked design decisions:** two paths/one destination · one question at a time · only ask what's
ambiguous · ≤6-placement rule (skip zone when few options) · **SKUs are immutable** (QB is truth;
rules filter, never fabricate) · show incompatible items with a badge, don't hide · flat modal stays
as fallback until the picker is proven · color combos are **mode-based** (Uniform / Standard Split =
red driver/blue passenger contiguous halves / Custom), not a static preset table · lens defaults to
agency, overridable per part.

### Placement model (category-level — locked direction)
Placements are chosen at the **category** level, not per-product or per-catalog-slot. Every Warning
light offers the same warning placement pool; same for Scene/Interior/etc. **No instance limits** —
add unlimited Forward Warnings, names auto-sequencing ("Forward Warning 1, 2, 3, …"). Any product →
any location in its category by default; restrictions (Under Mirror = specific models; light-bar /
spotlight / thermal-camera placements) are **exception rules** added as needed. The picker stopped
deriving placement from the legacy `part_catalog.json` `default_views` / fixed numbered slots.

For **scene lights**, the selected quantity is the number of heads to draw and is never capped by a
location's historical dot count: one head uses the centered location dot, while two or more use that
location's authored pattern or spread horizontally from a single-dot anchor. The picker dots, live
preview, and PowerPoint renderer use the same rule.

### Warning-light home model (locked w/ Seth 2026-07-01)
**A warning light is NOT assigned a zone by its part_type.** Zone/location is decided by *where the
part is placed during the build*, not baked into the part. So there is **one warning-light home**
(the `warning_light` part_type, `category: warning`); zones exist within the warning category but are
not tied to any specific part_type. All colored warning lights fit that single home; the picker's
category-level placement step chooses the actual location. The legacy zone-named warning part_types
(Forward Warning, Front/Side/Rear Warning, Mirror Warning, Pit Bar Warning, Lower Lift Gate Warning…)
are **superseded** by the single home — collapsing existing products onto it is a follow-up migration.
**Classification rule:** a light with **color options (not just white) is a warning light**; a
white-only light is scene/utility, not warning. **Granularity:** one product per model; mount-type
and color are **SKU variants** under that product, not separate products.

### Translation layer
`planning/sku_resolver.py` turns one user selection into the right `PartInput`/`DraftPart` shape.
The picker adds **one parent line**; concrete SKUs become `components[]` on the `DraftPart` (shown as
expandable child rows, persisted, but dropped before the planner/renderer so the build sheet sees the
same simple line). `match_heads()` groups heads by color set; `build_rows()` emits parent +
components + color fields. **Trio is rejected at match time** (a 3-color head isn't a single SKU;
SKUs hold at most `color` + `secondary_color`, with `tertiary_color` for trio *storage/matching* only).

---

## 2.5 Part Manager — SKU Review grid + Hierarchy (data-curation UI, shipped 2026-06-29/30)

The self-service tool for curating `parts_db.json` — built to let the owner rip through the ~1,200-item
QB import without prompting Claude per item. Lives at **Settings → Advanced → Part Manager**, with four
inner tabs:
- **Review (SKUs)** — the new primary surface (`ui/js/settings/sku_grid.js`).
- **Hierarchy** — the editable tree (`ui/js/settings/part_manager.js`, the old "Database v2"); edits a
  part_type's `tree_positions` + a product's `fits_part_types`, which is what drives picker sorting/placement.
- **Part Types (legacy)** / **Parts Library (legacy)** — kept until the Phase 4 consumer cutover.

Files: `ui/js/settings/sku_grid.js`, `app/routes/parts_db.py` (the `/api/parts-db/edit/*` endpoints),
`ui/index.html` (`#stab-sku-grid`), `ui/styles.css` (`.skg-*`). Tabs wired in `ui/js/tabs.js`.
Tests: `tests/test_parts_db_edit_routes.py`, `tests/test_qb_estimate_unbilled.py`.

### The mental model — three independent axes (this is the clarity the tab is built around)

1. **QB backing** (per SKU): **In QB** (`qb_item_id` set → price/sales-description/active are the real
   QuickBooks values, shown read-only) · **Pending QB** (`qb_pending` → pre-added, hand-set price,
   auto-reconciles on sync) · **Not in QB** (DB-only) · **Unbilled** (the `unbilled` tag — agency-supplied,
   see below). **"Linked" means exactly "has a `qb_item_id`," nothing more.**
2. **App-readiness**: a product is **Ready** when it has a **home** and, **for lights only**, every SKU has
   a **color**. A product's "home" is normally a part-type (`fits_part_types` ≥1) — but **an accessory's
   home is its parent product**, so a product with an Accessory role (`accessory_category` + ≥1
   `accessory_of_products`) needs **no** part-type and is selectable only as an accessory of its parent.
   (A product declared an accessory with no parent yet shows "Needs: parent".) Description and price are
   *not* required. The header badge spells out what's missing ("Needs: home, color").
3. **Reviewed**: a manual **Complete** checkbox per product → green highlight. Human sign-off, independent
   of 1 & 2. Stored as `product.reviewed` (syncs to the team).

### Features
- Brand-sorted; expand a product to edit **every field inline**. Value-set fields are **selectors
  populated from `parts_db.json`** (brand, part-types, tags, vehicle-tags, colors, lens), each with a
  **"+ Create new…"** option that opens a **validating modal** when more than a name is needed.
- **Move a SKU between products** (incl. **"➕ Create new product…"** inline), add/delete products +
  SKUs, **bulk** actions (set lens / clear pending / delete), and **filters**: brand · **Type · Section ·
  Zone · Part-type** (part-picker-style tree filters, cascading; "— No part-type —" surfaces the import
  queue) · QB state · readiness (ready/needs) · review (complete/incomplete) · search.
- **Light bars** (roof/interior/visor) are exempt from the "needs color" readiness check — their color
  is baked into the configured SKU.
- **Part-type locations** are edited in the **Hierarchy** editor (mode = placement/text + options),
  not here — locations are a part_type concept, not per-product (see §4-location below).
- **Read-only QB-source line** under each SKU (from the `/api/quickbooks/items` cache by `qb_item_id`):
  name · sku · sales description · price · type — so decisions are made against real QB data.
- **Sales Description** = the `friendly_name` field (relabeled). **⤵ Descriptions from QB** backfills it
  from the QB cache into empty SKUs (never clobbers a custom one).

### Conventions established (tag-driven, user-correctable)
- **`light` tag** drives the color/lens/3rd-color fields + the "needs color" readiness. Detection is
  tag-based; until any light tag exists it **falls back** to the legacy `type_id=="lights"` heuristic.
  **⚡ Seed light tags** creates the tag + seeds it (products with a colored SKU or fitting a light-category
  part_type), then the per-product **Light** checkbox corrects individuals. *(Not all Whelen parts are lights.)*
- **`unbilled` tag** = agency-supplied items (cameras, radios) the shop installs but never bills. Toggle in
  the grid; **estimate generation skips them** (no line, no blocking problem — `qb_estimate_service._unbilled_keys`).
  They need no QB id.
- **Accessory role** (its own section, separate from part-types): a product is marked a bracket/flange/etc.
  via `accessory_category` + **which parent product(s)** it belongs to (`accessory_of_products`, + optional
  `accessory_required`). Stored **on the child**; `_resolve_accessories` honors it (3rd source, alongside
  parent-side `accessories` and part_type `accessory_of`). Accessory part_types are excluded from the
  placement selector. **An accessory needs no part-type home** — readiness skips the home check (its home
  is the parent), so it's selectable only as an accessory of its parent in the picker.
  **Planned:** an *Accessories* section in the part picker to add accessories on their own when needed
  (e.g. ordering a spare bracket without its parent).

### Granular edit endpoints (`POST /api/parts-db/edit/<action>`)
Small patch in, server applies to the full doc + persists via `save_config_file` (validation + SharePoint
mirror). Actions: `product-update` / `product-create` / `product-delete` · `sku-update` / `sku-add` /
`sku-delete` / `sku-move` / `sku-bulk` · `manufacturer-create` / `tag-create` / `part-type-create` /
`part-type-update` · `backfill-descriptions` · `seed-light-tags`. (Whitelisted product fields include
`reviewed`, `accessory_category`, `accessory_of_products`, `accessory_required`; QB-owned price is protected
on linked SKUs.)

### Reference catalogs (parsed for curation; part# + descriptions, no prices)
`docs/reference/WHELEN_PRICE_LIST_PL26.md` · `docs/reference/SETINA_2026.md` (2,221 parts) ·
`docs/reference/ARCTIC_START_2026.md` (183 parts, Firstech/DAS remote-start).

---

## 3. Accessories (Phase 5 — shipped)

When a user adds a part, any accessories it needs (lighthead, bracket, cable, flange, …) are
**impossible to miss**: the picker shows one selector per accessory category and won't allow Add
until each is addressed (a choice, or explicit "None"). Linking the unlinked Whelen accessory SKUs
happens *through* this feature.

- **Data:** `accessory_categories` supplies the shop-facing selector label. Use a distinct category
  whenever one parent needs separate decisions (for example Printer **Bracket / Mount**, **Power
  Cable**, and **USB Cable**) rather than putting unlike items in a generic Cable selector. Two
  applicability levels: **part_type-level**
  (`accessory_of` — generic, e.g. any forward_warning → FW brackets) and **product-level**
  (`products.<id>.accessories = [{category, product_id, required}]` — specific). A specific
  relationship can set `include_generic: true` when its option is additional rather than a
  replacement for the normal compatible group. A product named by a specific relationship is
  excluded from other products' generic choices. For an item that is merely filed under an
  accessory part type but is not universally compatible (such as a push-bumper light channel),
  set `include_in_generic_accessory_options: false` until it is linked to its intended parent.
  Use the `custom_patch` category for a billable custom-patch option that belongs with its parent
  product (for example, Tiger Tough seat-cover embroidery).
- **API:** `GET /api/parts-db/accessories?product_id=<id>` returns both, grouped by category.
- **Picker UX:** an "Accessories" section appears with per-category selectors + "None needed";
  users can add another item within a selector when the install needs multiples. **Hard-gated Add**
  prevents required accessories from being skipped; prices show inline. Each choice leads with its
  orderable SKU (when one exists), then its shop description so similarly named brackets and cables
  remain distinguishable. Editing the parent restores its selected accessory children in the same
  picker and replaces that selected set on Save. Saved manifest children also remain selectable
  during an edit when an old SKU is no longer linked in the current catalog; saving normalizes their
  metadata without requiring the user to rebuild the choice by hand.
- **Contextual recommendations:** a parent part type can declare `recommended_accessories` for an
  optional item that applies only after an authored draft condition is met. The picker shows its
  reason and preselects it, but **None needed** remains an explicit opt-out. For example, the
  second Light Control Head recommends the pending-QB CCTLHARN secondary-control-head harness.
- **Draft/build sheet:** each chosen accessory is its own priced `DraftPart` line carrying
  `parent_line_id`; nested under its parent in the manifest; **delete confirms first** ("This part
  has N accessories — remove them too?").
- **Tooling:** `tools/qb_apply_links.py` `new_products` / `links` / `set_accessories` ops (idempotent,
  dry-run by default, `--write` mirrors). Batches 1–11 wired the bracket_mount group, flanges, cable
  accessories, Micron stud-mount heads, and Tracer WCX lightheads. Every link carries a
  `friendly_name` + real `vehicle_tags`; the picker has a persisted "Only show <Vehicle>-compatible
  parts" toggle. See [[project_accessory_wiring]].

---

## 4. Tracer & roof-lightbar lighthead selection (shipped, GUI-verified)

For products whose color lives in **child lightheads** (tracers; some bars), the color decision
collapses into a small **Standard Duo / Standard Trio / Custom** control + a **White/Amber** secondary
selector, auto-resolving the exact head SKUs + quantities. Every other light keeps the normal color
picker.

- **Tracers:** engine `app/services/lighthead_resolver.py::resolve_tracer` (pure, tested) →
  `GET /api/parts-db/tracer-heads` → `#picker-tracer` panel. Housing = bar/tracer SKU (no color);
  head = child SKU carrying color (slot 1 = primary, slots 2…N = secondary). 2-lamp → front, single
  housing (driver R / passenger B); 3/5/6-lamp → side running boards → **auto-pair of housings**
  (driver + passenger), doubling heads. Renders as `tracer_Nlamp`; brackets auto-added (L-bracket =
  (lamps+1)×housings, vehicle kit = 1×housing). Manifest shows the parent line with heads nested + a
  Duo/Trio tag; estimate lists each head SKU as its own line. Missing heads added as pending-QB.
  - Whelen color key: `TCRWX`=clear, `TCRXX`=smoked · `P`=primary, `S`=secondary · Duo D=R/W E=B/W
    K=R/A M=B/A; Trio JC=R/B/W JA=R/B/A. Standard Duo = D/E (white) or K/M (amber); standard Trio =
    JC (white) or JA (amber).
- **Outer Edge rear pillars:** the selected `whelen_ion_rear_pillar` housing opens a dedicated
  included-ION setup backed by `resolve_outer_edge_pillar` →
  `GET /api/parts-db/outer-edge-pillar-heads`. The housing SKU controls the construction: a Duo
  asks for White or Amber and adds a typical split of **3 Red/secondary + 3 Blue/secondary** IONs;
  a Trio is fixed to **6 Red/Blue/Amber** `OEI3RBA` IONs. The housing stays one parent QB line and
  the six included IONs persist as nested QB child lines so manifest and estimate quantities agree.
  It auto-locates as **Rear Warning** at `PILLARS`, suppresses the irrelevant generic
  bracket/mount and location questions, and renders only on the rear diagram as two mirrored,
  inward-angled vertical stacks of three IONs centered on the authored pillar anchors.
- **Roof lightbars:** research finding — bars are ordered as **whole configured SKUs** (color baked
  into the part number, e.g. Legacy `EB2DEDE`), **not** a head builder. So the model is **pick the
  SKU + a config tag**: `#picker-lightbar` panel — Setup (Standard / Custom + required order-notes
  textarea), Edition (Clear / Smoked / Midnight; Midnight flags black straps required, not enforced).
  Bars are fixtures → auto-located to "ROOF LIGHT BAR" (named "Light Bar N"), no location prompt.
  Mini/micro bars + Responder LP skip the panel (fixed-config single SKUs). Render via planner
  `_BAR_ASSET_KEY`.
  - Full-size bar **vehicle tags** (locked 2026-06-26): 48" → Durango only; 54" → everything else.
    When a new vehicle type is added, extend the 54" tag lists.

---

## 4.5 Guided systems and fixtures (current rebuild work)

Some picker entries are systems or fixtures rather than ordinary "choose product, then choose
location" rows.

- **Fixtures auto-locate.** Part types/products marked as fixtures, such as push bumpers and roof
  lightbars, skip the manual location prompt and use their fixture render/location metadata.
- **Render metadata lives in `parts_db`.** Part-type render data can carry `asset_key`,
  `size_rule_id`, `size_per_view`, `images`, `quantity_rules`, and fixture behavior (`is_fixture`,
  `default_views`, `render_quantity_policy`, `co_part_rules`); planner hydration consumes it for
  picker-built parts such as siren speakers, push bumpers, Pit Bars, and Wing Wraps. Do not re-add
  these rules to legacy per-SKU files.
  A product may override the part-type profile through `render.size_rule_id`, exact dimensions,
  or `center_single_at_mirror_location` for a one-head mirrored mount, and a concrete SKU may
  carry a rare `size_rule_id` override. Older product-name
  rows can resolve through a curated product `model_aliases` identity. Resolution is SKU →
  product → part type → Small default; it never uses a substring or product-name size rule.
- **Setina PB450L lighted push bumpers.** Recognized 2/4/6-light PB450L SKUs inject render-only
  included Whelen tri-color lights. They are not manifest or quote lines. They share a preview group
  with the push bumper so moving the bumper moves the included lights.
- **Westin push bumpers.** Base Westin bumpers can add wire-cover and light-channel accessory rows.
  Westin does not sell pre-lighted bumpers; the later billed-light choice for a selected channel is
  still a product/workflow follow-up.
- **Howler WCX vehicle routing.** With vehicle filtering enabled, the picker recommends exactly one
  current Howler assembly: `CHWLDD36` for Durango, `CHWLFE29` for PIU, and the untagged universal
  `CHWLUNI` for every other vehicle. These assemblies already include their mounting bracket, so
  the picker suppresses the legacy extra-bracket prompt for them. A historical saved SKU remains
  visible while editing so the user can review and deliberately migrate it.
- **Two-speaker dual tones.** A siren-speaker selection with quantity two asks whether the
  agency wants dual siren tones. Choosing Yes adds one linked `CEXAMP` as a concrete child component;
  estimates therefore bill two speaker SKUs plus one external amplifier, while rendering remains
  driven by the two-speaker parent quantity.
- **Guided systems.** Radio, radar, and camera families first select the system on the
  SKU tab. Radio uses the selected radio-unit SKU as that identity and opens its setup details
  immediately; radar and camera select a platform before their Details tab. The guided workflow
  then asks one clear question at a time. The family sidebar deliberately hides individual
  system-piece leaves; **Choose SKUs manually** is the explicit escape hatch for adding a
  standalone antenna, mount, cable, or other component. The guided workflow
  writes one expandable kit line. Its child rows are the concrete shop components with their
  selected mounting data; the manifest deliberately does not repeat the full questionnaire.
  Purchase text is retained in the kit’s saved choices/notes for Sales. Location choices are
  shop-reference data and always include Custom — they do not create render placements. Editing a
  guided kit restarts at question one while retaining all saved answers, and its manifest-section
  **Add** button returns directly to the matching picker family or leaf.
  - **Radio Communications** writes `radio_head`, `radio_brick`, `radio_antenna_top`,
    `radio_speaker`, and `radio_mic_clip` component rows. Split-head is the default; the center
    console setup owns the control-head position, so radio setup does not ask for it again.
    The selected radio-unit SKU determines whether it is an all-in-one or split system, so the
    setup never repeats that decision; only a split system asks for the radio-brick location.
    When a center-console radio mic clip is already present, radio setup asks whether it is the
    same physical clip or an additional radio clip; console setup asks the inverse when radio was
    configured first. Reusing the console clip leaves one physical clip/Mag Mic line while the
    radio component retains its install note.
    cylinder and whip antennas are restricted to rear-left roof (or Custom); mic location is top
    plate of console (or Custom). Choosing either Magnetic Mic option also adds its real, QB-linked
    Mag Mic SKU as a billable child line under the radio kit. Any selected cable refresh creates a
    separate nested QB-linked cable line; the shared Radio Refresh Cable Kit bills once even when
    more than one of its included cable runs is refreshed.
  - **Radar System** records each antenna location and its bracket separately. Short A-bracket is
    the default front choice and tall A-bracket the default rear choice; either can instead use a
    swivel arm. A split system writes separate display and counting-unit component rows, while an
    integrated system uses one combined row. The rear seatbelt-slot option appears only for a Tahoe
    build. Refreshed radar cable runs require an exact, QB-linked length/SKU selection before they
    are added as billable child lines.
  - **Light Control System.** Every leaf follows the project’s preferred lighting brand. Its
    non-rendered shop-reference locations use selection cards plus Custom text rather than a native
    dropdown. Light Control Head offers In Center Console or Custom. PA-capable control heads then
    record the PA-mic location as Driver's door or Custom, along with a Magnetic mic or Manufacturer
    clip. The selected PA-mic setup is retained in the control-head picker data/notes and is shown
    in the control-head detail rather than as its own manifest line. A Magnetic mic additionally
    creates its real, QB-linked Mag Mic SKU as a billable child line; a Manufacturer clip remains
    shop detail only.
    CCTL5 declares `pa_mic_required: false` and `handheld_mag_mic_prompt: true`, so Details asks
    whether to add an MMSU-1 Mag Mic without offering a bracket accessory. A single control head
    is named **Control Head**; adding a second renames the pair **Control Head 1** and
    **Control Head 2** (and child-row prefixes track that change). Removing back to one drops the
    numeric suffix again.
  - **Center Console.** It has one fixed physical location (In Center Console). **Set up Center
    Console** starts with the console style and required features, then selects the best compatible
    QuickBooks kit. Core and radio faceplates are always placed in the lineup; vehicle-specific
    kits also place their OEM relocation plate and, when supplied, cupholder plate in physical
    shop order. Included kit items remain visible under the console in the manifest but are not
    billed separately. An armrest or motion attachment is omitted as a separate estimate line
    when that exact feature is included with the selected kit; docking stations and other non-kit
    hardware remain independent billed lines. Faceplates and related hardware are filtered to the
    preferred console manufacturer. Vehicle-specific console wings remain an optional detail
    rather than a numbered faceplate; the current catalog offers Gamber Johnson 2015+ Tahoe wings
    only on Tahoe builds. A pedestal-mounted motion attachment requires a compatible
    `pedestal_mount` selection; that base is saved as its own related build line. The setup also
    offers an optional manufacturer-matched radio-mic clip — for Havis consoles this includes the
    live-QB Havis C-MCB Mic Clip Bracket. Setup and the fixed console location are selected from
    the product's `fits_part_types`/primary part type, not the browse leaf, so every path that
    selects a main console product goes directly to setup rather than placement. Selecting a
    radio-mic clip then asks whether to add its live-QB Magnetic Mic `MMSU-1`; this defaults to
    Yes and is saved as a nested console component, with an explicit No option. Console faceplates,
    armrests, pedestals, motion attachments, docking stations, and mic hardware all nest under the
    Center Console manifest row. Selecting a printer armrest likewise asks whether to add a printer
    (default Yes); the printer remains a separate manifest parent and its explicitly-linked power
    and USB cable SKUs nest directly below it. The Havis faceplate
    chooser exposes only exact Havis products with a live, vehicle-compatible QuickBooks SKU;
    generic migration placeholders and other manufacturers' equipment brackets are not options.
  - **Camera System** asks for platform before components. Axon Fleet 3 only exposes front and
    prisoner cameras; WatchGuard 4RE and M500 also expose rear camera, body-camera dock, and
    wireless-mic charger. Front and rear cameras use fixed upper-window locations. Camera refresh
    choices appear only when a corresponding QB-linked cable SKU is available.

**Location/render caveat:** text `location_options` are only friendly choices unless the same key
exists in `vehicle_layouts.json` or has an alias. See
`docs/audit/PICKER_POST_RADIO_AUDIT_2026-07-15.md` for the current radio antenna cargo-window risk.

---

## 5. Pending-QB parts (shipped)

Lets us pre-add a real, orderable part to `parts_db.json` **before it exists in QuickBooks**, and use
it normally — turning a blocker into a to-do that travels with the work. First consumer: the missing
Tracer Trio / passenger-Amber heads.

- **Data:** a `part_numbers[]` entry with its real `part_number` + a hand-set `price_usd`, **no**
  `qb_item_id`, and `qb_pending: true`.
- **Behavior:** fully selectable/placeable in the builder (marked with a "pending QB" chip, never
  blocked). On estimate push it posts as a **`DescriptionOnly`** line — `"⚠ NOT IN QB INVENTORY —
  create item <SKU>: <name> — <qty> × $<price>"` — needing no `ItemRef`. Trade-off: a DescriptionOnly
  line carries no Amount, so the pending part isn't billed until the QB item is created (the note
  carries the price). VB-side totals **do** include the pending amount; `validate/create` return
  `pending_count` so the UI warns; pending is **not** a blocker (`can_create` stays true).
- **Reconciliation:** `qb_sync_service.reconcile_linked_parts` (after every items pull) fills
  `qb_item_id`/`qb_sku`/`qb_unit_price` and clears `qb_pending` for any pending entry whose
  `part_number` now matches a synced QB item by name or sku. Closes the loop automatically.
- **Tooling/UI:** `qb_apply_links.py` `pending_parts` op; a "Pending QB" chip in the picker; a
  "Pending QB" checkbox in the Part Manager SKU row (disabled once linked).

---

## 6. One-off custom parts (shipped)

Use **Add custom part** at the bottom of the Part Picker sidebar for a billable, one-time item that
must not become a `parts_db.json` product or a QuickBooks inventory item. SKU, description, unit
price, and quantity are required and are saved in the draft row's
`picker_config.custom_part` snapshot. The row stays in the manifest but intentionally has no
vehicle placement or render asset.

Custom rows reopen this same form from the manifest Edit button. SKU, description, quantity, price,
and an optional manifest category can be changed without entering the managed Part Picker. The
category uses an existing manifest section for organization only; it does not turn the row into a
catalog product or change its draft-local pricing snapshot.

- An exact SKU match in `parts_db.json` is detected case-insensitively. The picker offers to open
  the catalog SKU's normal setup/placement flow; the operator can explicitly keep a distinct custom
  line only when that is intentional.
- Recent custom entries are retained locally in `workspace/custom_parts.json` for fast re-entry.
  This convenience history is not inventory, is not a settings change, and is not cloud-synced;
  the authoritative quote data remains with the shared draft.
- Estimate resolution makes the saved unit price and quantity a `custom: true` sales line through
  the literal active QuickBooks `MISC PART` Item (case-sensitive because this company also contains
  a distinct `Misc Part` Item). The entered SKU, description, quantity, unit price,
  and extended amount remain visible on the estimate line, so QBO includes it in the document total.
  If `MISC PART` is unavailable, estimate creation is blocked instead of silently posting a $0 note.

---

## 7. Enduring lessons & gotchas (from the schema-translation audit)

- **parts_db writes vs. SharePoint sync** is the #1 footgun — see §1 write invariant. Categories and
  colors silently reverted because a direct `json.dump` doesn't reach the cloud.
- **A generic "Error loading X" in the picker almost always means a backend 500 returning non-JSON.**
  Check the server log / network tab first; the JS catch is rarely the fault. `api()` now throws a
  status-bearing error on non-JSON bodies, and picker catches `console.error`.
- **When debugging a route, exercise the route handler, not just the service.** The Chunk 5 bug lived
  in the handler (`Product.price_usd` doesn't exist — price is on `PartNumber`); the service methods
  were healthy, which made "verified via Python" misleading.
- **The planner renders by exact part name** historically — arbitrary counts ("Forward Warning 3")
  weren't in the catalog → `render_kind=none` → silent drop. The category-level placement model + a
  part_type/category resolver (strip the sequence number) fixes this; key placements by draft
  `line_id`, not `part_id:view`, so same-named instances don't collide.
- **No silent failures:** `PlannedPart.warnings` exists — plumb it to the manifest row + build-sheet
  "not shown" area and warn on unplaceable/duplicate parts.
- **Non-rendering parts** (Tail/Headlight Flasher, `render_kind:none`) are valid line items with no
  diagram icon — excluded from the placement step.

---

## 8. Open items & data backlog

### Open questions (need owner input — don't guess)
- **Q2 — Light size curation:** all old text rules are now explicit part-type/product/SKU
  assignments. Products without a curated assignment inherit their part type's Small profile.
  Review actual dimensions before assigning new profiles for M2/M6/M7, M9 Scene, Summit Flood,
  EZ Scene, 500 Series TIR, Century, Outer Edge, Traffic Advisor, Avenger X1/X2, and lightbars.
- **Q3 — Add-without-placement** path for non-rendering parts (flashers, etc.).
- **Q5 — Naming** for unlimited instances: is "Forward Warning {n}" the pattern for all warnings, or
  does zone/sub-type set the base name when placement is category-level?
- **Q6 — PPT dynamic counts:** does `render_ppt.py` / the template have fixed named rows that cap
  instances? Investigate before deepening the renderer change.
- **Q7 — Category placement pool per vehicle:** confirm pool = all located placements (in the
  category's relevant views) for the draft's vehicle, minus exceptions.

### Whelen catalog decisions still open (the ~47 remaining unlinked + flagged items)
- **New primary products to create:** V2V sync modules (`CV2V`, `CLBV2V`); headlight/LED flashers
  (`SSFPOS`, `SSFPOSI6`, `ULF44`, `PLF46`, `M62T`, `70RC6FCR`); Field Series power supply (`FSBPS`);
  misc switch/control (`PCC6W`, `LCPHOTO`, `LINZ6R`, `H35SN12`, `SYS109` $3460, `PFP2AP1`).
- **Lighthead families:** DUO low-profile lamps (`BWD#`/`BWP#`); `BW54UFX` (a configured 12-lamp
  assembly, probably not a part).
- **Motorcycle box system (6 SKUs):** own family only if DTM sells motorcycle builds, else leave.
- **QuickFit roof platforms (5):** could be `bracket_mount` accessories of the full-size bars —
  resolve the S/W finish-suffix meanings first.
- **Legacy lightbar options (8):** Midnight kits, smoked-lens kits, alley modules, angled endcaps —
  wire as Legacy accessories once each SKU's category is decided.
- **Sub-assemblies / final assemblies:** alley-warning + Howler final assembly — likely BOM
  artifacts, exclude from the picker.
- **Flagged singletons:** `FSBBB`, `SP123BMC`, `HWLFE29`, `CC5K2` — parent not identifiable; judge case-by-case.
- **Naming calls (from the naming audit):** Freedom vs "Freedom IV"; Legacy SOLO vs DUO; Liberty vs
  "Liberty II".
- **Phase 4b flags:** System 109 (identify before adding); Avenger II (physically upper-windshield
  driver/passenger only — `fits_part_types` can't express the position restriction, needs
  placement-zone handling); PAR-46 mis-tagged purple/amber (they're white spotlights — fix colors);
  Micron `MCRNSD` QB price $964 vs ~$161 siblings (likely a QB data error — verify).
- **Resolved (for the record):** Edge 9X wired (pending-QB); Cenator retired (discontinued);
  Responder LP skips the config panel; ITL12 reclassified as a Liberty take-down accessory.

### Picker + placement cluster — SHIPPED (2026-07-01)

The interrelated cluster that had blocked build-flow testing is done:

1. **#4/#7 — Location model rebuilt at the part_type level (the real fix).** The "70 lost
   placements" framing was a partial misdiagnosis: external-light placements were essentially
   complete; what was missing was per-part-type locations for **non-light** parts. Locations now live
   on the part_type with a **`location_mode`**: `placement` (external/visual — lights, bumpers, arges,
   sirens: the location tells the preview *where to draw*; coordinate-driven) vs `text` (interior/
   equipment: a curated **pick-list** printed on the sheet, no visual placement). `location_options`
   holds the text list. The non-light picker location step now renders a **dropdown** (curated options,
   or a **free-text field** when a part_type has none) instead of a blank vehicle diagram. Seeded from
   the workbook by `tools/seed_part_type_locations.py` (22 placement · 91 text · 27 with options);
   editable in the **Part Manager Hierarchy** editor (mode selector + add/remove options). Resolver:
   `_resolve_product_locations` prefers `location_options`; `category-locations` routes non-lights to
   it. Validation in `config/schemas.py`; edit action `part-type-update` whitelists the fields.
2. **#5 — Scene no-color filter.** Root cause was server-side: `sku_resolver.match_heads` treated an
   empty head (the picker's "No color" choice) as "match only colorless SKUs" — inverted. Fixed to
   match all; scene/interior now **default to no color filter** (`part_picker.js`).
3. **#8b — SKU sales description** already renders on non-light SKU rows (`friendly_name`).

**Still open:** #7(a) auto-skip the location step for a part with *zero* options (currently shows the
free-text field — acceptable, low priority).

### Product-driven picker context and custom placement (2026-08-05)

Some products have more than one valid physical part-type home. A product may set
`picker_primary_part_type` to declare the semantic picker flow that always configures it; the value
must be one of `fits_part_types`. For example, T-Series products are warning lights even when they
were reached from the broad **Lights** leaf, so they use the normal warning-light color and SKU
picker. The prior `global_search_part_type` key is accepted as a compatibility alias only.

The custom-location flow retains its shop-facing label. Rendering is optional: without an anchor,
the saved line is a valid manifest/shop-reference item with no diagram placement. When it should
render, it can use either of two anchors:

- **Vehicle dots** shows every saved placement and fixture dot on each exterior vehicle view and
  saves the selected standard dot as `custom_location.render_location`.
- **Set your own** hides the saved dots and lets the user add or remove exact points in one or more
  exterior views. These persist as `custom_location.placements` (`{view: [{x, y}, ...]}`) and the
  planner creates a separate placement for every point. This deliberately supports unusual custom
  light installations without inventing a misleading standard location.

Tracer configuration owns its own **Clear / Smoked** lens selection; the chosen lens is used for
both the live SKU resolution and the saved tracer lighthead lines.

### Kit SKUs (after the picker cluster)
Let a SKU be marked a **kit** that **includes other SKUs**. New per-SKU concept (e.g. `is_kit: true` +
`kit_skus: [part_number…]`) — needs: data model + SKU-grid UI (mark kit + pick members) + a decision on
estimate behavior (does the kit bill as one line, or expand to its components?). Scope before building.

### Picker finish-line work (lower priority)
- **Chunk 9 polish**: real images where useful, final visual QA, and retiring the flat modal once
  picker rebuilds prove it is no longer needed.
- **Guided-system hardening**: finish Westin light-channel billed-light selection, resolve radio
  render/text location aliasing, and broaden UI smoke coverage for owner-facing workflow rules.
- **Non-light / no-color products** still need continued data-quality review so sales-facing names
  explain the object and system context without relying on hidden QB descriptions.
- **More bar SKUs/configs** beyond the few wired (Legacy 3, Liberty 2, Edge 9X 6) — blocked on Seth
  providing SKUs.

> The Parts Manager **SKU Review grid is shipped** (see §2.5) — the owner can now curate SKUs,
> tags (light/unbilled), accessory roles, and readiness self-service. The remaining blocker for
> *testing the build flow* is the picker+placement cluster above.

---

## 8. Constraints & invariants

- **parts_db writes** must go through `save_config_file` / `--push-to-cloud` (SharePoint sync reverts
  raw writes). Persist to cloud while signed in.
- **`PYTEST_CURRENT_TEST` guards** on all cloud I/O. Full suite ~1600+ tests must stay green
  (`.venv/bin/python -m pytest`).
- **Route pattern:** every route module exports `route_xxx(handler, method, path, body, paths) -> bool`.
- **JS:** modal/panel pattern (`.modal-overlay`/`.modal` + `classList.add/remove("open")`); each save
  button owned by exactly one IIFE; no build step.
- **`Cache-Control: no-store`** on QB response routes.
- **Don't enumerate light color combinations** — derive from a 1–3-color selection.
- **Don't change `PartInput.name` / `DraftPart.name` semantics** — the rules engine matches on
  `_norm(part.name)`; new naming goes in new fields.
- Launch the dev app via `.venv/bin/python -m dtm_buildsheet` (127.0.0.1:7655), or
  `Launch_DTM_VehicleBuilder.command` (sets `DTM_DEV_NO_SETTINGS_PULL=1` so the cloud doesn't
  overwrite local config during data work). **Commit after each data batch — that's the safety net.**
