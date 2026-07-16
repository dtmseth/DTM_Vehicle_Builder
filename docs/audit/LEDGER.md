# Audit Findings Ledger

Format per [AUDIT_REFACTOR_ROADMAP.md](../AUDIT_REFACTOR_ROADMAP.md) §1.2:
`FINDING-nnn: location · category [duplication|legacy|fragile|security|island|doc-drift|workbook-shape] · severity · disposition`.
Dispositions: **SONNET-FIXABLE** (mechanical, land under pins) vs **NEEDS-DESIGN**
(owner/architect call first). Verification: **CONFIRMED** (reproduced live) vs
**SUSPECTED** (static analysis only).

> **Note:** created ahead of roadmap Step 0 by the 2026-07-08 Part Picker + UI
> audit session; Step 0's ledger tooling should fold this file in. Sessions
> append; never rewrite prior entries.

---

## Session 2026-07-08 — Part Picker + UI slice (read-only audit)

**Scope:** `ui/js/part_picker.js`, `manifest_editor.js`, `settings/sku_grid.js`,
`state.js`, preview/canvas touchpoints, `app/routes/parts_db.py`
picker/placement endpoints, `planning/sku_resolver.py` + sibling resolvers, the
draft→plan boundary. **Method:** docs-first, then code, then empirical
reproduction against a hermetic boot (`tools/ui_smoke/hermetic.py`, throwaway
workspace, netguard clean on every run — zero egress). Probe scripts lived in
the session scratchpad; zero production-code changes. Baseline: production
`parts_db.json` (~930 products), fixture project `AUDIT-001`/PIU driven through
the real build editor with headless Chromium.

---

### FINDING-001: `_resolve_category_locations` zone-keyword map silently drops scene FRONT and ROOF placements
- **Location:** `app/routes/parts_db.py:139-191` (`_zone_keyword = {"front": "forward", ...}`)
- **Category:** fragile (label-keyword matching = legacy-naming assumption)
- **Severity:** HIGH — blocks curated scene lights from front placement
- **Status:** CONFIRMED
- **Repro:** `GET /api/parts-db/category-locations?type=lights&category=scene`
  → 15 locations, placement_zones = {side, rear, rear_side, rear_interior} —
  **zero front, zero roof** (warning returns 39 incl. all front zones). In the
  picker UI (scene → any product → Location tab) the view pills are
  Side/Top/Rear; Front never appears.
- **Mechanism:** for non-warning categories each placement's tree zone must map
  to a part_type via keyword — front→"forward". `front_scene` is labeled
  "Front Scene" ("forward" ∉ label) → every front placement is skipped; no
  keyword exists for "roof" at all, so scene's roof pool (in
  `_CATEGORY_PLACEMENT_ZONES`) is dead code.
- **Blast radius:** `whelen_par46`, `whelen_par32`, `whelen_wing_plow_light`
  are homed **only** to `front_scene` — selectable as products but impossible
  to place in their own zone.
- **Disposition:** NEEDS-DESIGN — entangled with the owner's pending scene
  collapse ruling (OPEN_QUESTIONS §B1.1; see capability notes below). If scene
  stays zone-split, the fix is mechanical (map placement→part_type via
  `tree_positions` instead of label keywords). If scene collapses to one home,
  this function needs the same special-case treatment `warning` already has.

### FINDING-002: interior / interior_bar / spotlight categories return ZERO locations — 9 real interior placements unreachable
- **Location:** same function as FINDING-001
- **Category:** fragile
- **Severity:** HIGH — interior lights (7 products) cannot be placed on their real placements
- **Status:** CONFIRMED
- **Repro:** `category-locations` for `interior`, `interior_bar`, `roof_bar`,
  `spotlight` all return `[]`. The DB has 9 placements with
  `interior`/`rear_interior` zones (CENTER OF DASH, HEADLINER, INTERIOR LIGHT
  BAR (FRONT), ON DASH, cargo windows, …) — none reachable. Picker UI shows
  only a free-text "type the mount location" field for interior lights.
- **Mechanism:** the same `zone_pt` keyword table only has front/side/rear
  keys; interior/roof tree zones never resolve a part_type → all skipped.
  (`roof_bar` is masked in practice: bars auto-locate client-side in
  `_pickerLightbarAutoLocation`. `spotlight` has no explicitly-categorized
  part_types yet — pending §B1.5.)
- **Disposition:** NEEDS-DESIGN (same design decision as FINDING-001).

### FINDING-003: lights location pool ignores the vehicle — locations without coords in the vehicle's views silently vanish
- **Location:** `app/routes/parts_db.py:182-189` (`"has_coords": True` hard-coded; `vehicle` param unused for lights)
- **Category:** fragile
- **Severity:** MEDIUM
- **Status:** CONFIRMED (by count) — scene returned 15 locations; on PIU only 6
  dots materialized across all views; the other 9 appear in no view and no
  dropdown (the client's dropdown branch only takes `has_coords: false`
  entries, which lights never produce).
- **Disposition:** SONNET-FIXABLE — intersect with the vehicle layout the way
  `_resolve_product_locations` already does, or return `has_coords` honestly so
  the client's dropdown fallback can catch the rest.

### FINDING-004: parts with a zero-option location step get named literal "Part" — planner-invisible, non-sequencing
- **Location:** `ui/js/part_picker.js:733-741` (free-text branch clears
  `name_pattern`/`base_label`) + `part_picker.js:1356-1368`
  (`_pickerSequencedName("","")` → `"Part"`)
- **Category:** workbook-shape (naming/rendering contract assumes workbook-era
  catalog names)
- **Severity:** HIGH — **the** blocker for the curated equipment queue
- **Status:** RESOLVED
- **Repro (live UI):** Add Part → Equipment → Havis 18" console → SKU Select →
  location step is free-text (console part_type: `location_mode: text`,
  **0 location_options**) → type anything → Add. Draft part lands as
  `name: "Part"`. `/api/preview/plan` then reports `Unmapped part: Part`
  (render impossible — `_find_part_type_by_name("Part")` matches nothing), and
  a second such add creates a *duplicate* "Part" row (no trailing number →
  `renumber_parts` never sequences it).
- **Blast radius:** every part_type with `location_mode: text` and no curated
  options — per probe: `console` (30 products), `gun_lock` (20),
  `gun_lock_bracket` (36), `remote_start` (5), `radar_display_unit` (4),
  `front_partition` (5), `floor_pan` (2)… i.e. most of the 384-product curation
  queue's destinations. Only 27 of 86 text-mode part_types carry options.
- **Disposition:** SONNET-FIXABLE — the picker already has the product's
  `fits_part_types` in the `category-skus` payload; the free-text branch should
  carry the part_type label as `base_label`/`name_pattern` instead of clearing
  them. (Seeding `location_options` for high-traffic types is the data-side
  complement, already on the curation roadmap.)
- **Fix:** `_pickerDrawLocation`'s free-text branch now resolves a real
  part_type label via a new `_pickerFreeTextPartTypeLabel()` helper — it reads
  the selected product's `fits_part_types` (already in the `category-skus`
  payload) intersected with the current `type_id`, backed by a lazily-fetched
  `/api/parts-db/part-types` label cache (`_pickerPartTypeMeta`) — and sets
  `loc.name_pattern = "{label} {n}"` / `loc.base_label = label` instead of
  clearing them, falling back to the product model if no part_type label is
  found. Client-side only; no server/contract changes. Verified live with the
  exact repro (Gamber Johnson PIU low-profile console, part_number
  `7170-0734-00`, `console` part_type with 0 `location_options`): two adds
  land as `"Console 1"` / `"Console 2"` with zero `plan.warnings`. Golden
  master + contract snapshots unchanged (client-only fix). Permanent
  regression guard: `tools/ui_smoke/flows.py:flow_add_text_mode_equipment_part`.
  **Superseded (2026-07-10):** the `"Console 1"` / `"Console 2"` verification
  detail above no longer holds — see FINDING-027. `console` is single-instance
  and now names to the bare `"Console"` label with no sequence number; the
  sequencing behavior this finding verified is still correct and still
  guarded, just on a different part_type (`gun_lock`).

### FINDING-005: picker Edit mode destroys the edited part (name→"Part", SKU/model clobber, quantity→1, colors wiped)
- **Location:** `ui/js/part_picker.js:99-119` (`_pickerOpenEdit` hard-codes
  `type_id="lights"`, no category) + `part_picker.js:1370-1460` (`_pickerDoAdd`
  edit path)
- **Category:** fragile
- **Severity:** HIGH — data-destroying on a routine action
- **Status:** RESOLVED (2026-07-10)
- **Repro (live UI):** seed "Forward Warning 1" (ION, qty 2, Red) → manifest ≡
  Edit → picker opens ("Save edits" **enabled immediately**). Click Save (or
  re-pick any product) → draft line becomes
  `{"name": "Part", "part_number": "<first SKU or model string>", "quantity": 1, "raw_color": ""}`.
  Also reproduced: search box matched "Midnight **Edition**" for query "ion"
  (substring), one click + Save rewrote the warning light into a Legacy bar
  line.
- **Mechanism:** edit mode resets `category_id=""` → `_pickerUsesColor()` false
  → color path off → non-color path substitutes `product.skus[0]`; the name is
  rebuilt from `_pickerChooseName(loc)` whose pattern/base are empty in edit
  mode → "Part"; quantity is hard-coded 1 in the non-color combo. Editing any
  non-light part is equally broken in the other direction: the panel lists
  **lights** products only (134 listed while editing). Accessories are
  explicitly unhandled in edit (`_pickerLoadAccessories` bails).
- **Disposition:** NEEDS-DESIGN — resolved by PICKER_REDESIGN.md Step 6 (2026-07-10).
- **Resolution (Step 6, 2026-07-10):** Full edit contract replacing the stopgap.
  *Persist:* `_pickerDoAdd` now writes a `picker_config` snapshot (mode,
  colorsPerHead, per-head colors, per-head skuChoices, count, lens) to every
  picker-created `DraftPart`. `DraftPart.picker_config` is a new additive
  dict field (validators + v2.2.14 ignore unknown keys; old parts get `{}`).
  *Pre-fill:* `_pickerOpenEdit` walks the browse tree to determine type_id /
  category_id, restores config from `picker_config` (or derives from
  raw_color / quantity for legacy parts), pre-selects the product by
  part_number, pre-sets `loc.selected` to the stored location, and
  re-expands the tree path so the user sees exactly where they are.
  *Type-lock:* `.pbt-leaf` nodes for other part_types render with class
  `locked` (dimmed, cursor:not-allowed); leaf click handler blocks navigation
  to a different `part_type`. Cross-type clobber ("Midnight Edition" for
  "ion") is structurally impossible.
  *Save:* removed `_editTouched` dirty-tracking entirely from
  `_pickerResetState`, `_pickerUpdateFooter`, `_pickerDoAdd`, and all event
  handlers. Save is enabled whenever `sel && ready` — pre-fill makes the
  initial state match the stored state, so a no-op save is byte-safe.
  *Name preservation:* in edit mode `baseName = ep.name` (never re-sequenced).
  Client-side only (JS + DraftPart field); golden masters and contract
  snapshots unchanged. Regression guard updated:
  `tools/ui_smoke/flows.py:flow_edit_preserves_fields`.

### FINDING-006: plan warnings are rendered nowhere in the build editor; off-diagram parts vanish silently
- **Location:** `app/services/preview_service.py:141-250` (only
  `on_diagram` parts serialized; part-level warnings only ride on rendered
  parts) + zero `warnings` references in `ui/js/preview_canvas.js`,
  `manifest_editor.js`, `ui/js/projects/*.js` (grep-verified)
- **Category:** fragile (known gotcha "No silent failures" — never closed)
- **Severity:** MEDIUM-HIGH
- **Status:** CONFIRMED
- **Repro:** draft with a picker-shaped accessory child + a "Part" line →
  `/api/preview/plan` returns
  `warnings: ["Unmapped part: Forward Warning 1 · Universal Grill Bracket", "Unmapped part: Part"]`
  and the Console line (text location) is absent from `planned_parts` with its
  "No views found" warning unserialized. The build-editor UI displays none of
  this — the user just sees parts missing from the canvas.
- **Note:** accessory child lines and tracer heads are *intentionally*
  unmapped (descriptive names), yet each pollutes `plan.warnings` on every
  plan — warning noise that will bury real failures once surfaced.
- **Disposition:** SONNET-FIXABLE — (a) surface `plan.warnings` + per-part
  warnings in the manifest/preview ("not shown" area per the documented
  intent), (b) skip the unmapped warning for parts with `parent_line_id`
  (requires passing it through `draft_to_project_input`, which currently drops
  it — see FINDING-012).

### FINDING-007: manifest section grouping is workbook-slot-shaped AND only initializes after the legacy modal opens
- **Location:** `ui/js/manifest_editor.js:30-42` (`_meRebuildSections` reads
  `_workbookRules.template_sections`; sole call site is
  `_mePopulateDataLists:463`, reached only via the fallback flat modal)
- **Category:** workbook-shape + state bleed (DOM-singleton/lazy-global pattern)
- **Severity:** HIGH (workbook-shape default per roadmap §1.2)
- **Status:** CONFIRMED
- **Repro:** fresh build-editor open → `_meSections.length === 0` → **every**
  part renders under a single "Other" section. Execute `addPartManual()` once
  (open+cancel the legacy modal) → `_meSections.length === 24` → reload
  manifest → "Forward Warning 1" now groups under FRONT WARNING LIGHTS.
  Even then, grouping matches only names that coincide with the workbook's
  fixed rows: `forward warning 1/2` ∈ sections, but "Forward Warning 3",
  "Console", "Light Bar 1" → "Other" (verified against live
  `template_sections`).
- **Disposition:** NEEDS-DESIGN for the grouping source (parts_db `sections` /
  `tree_positions` is the Phase-4-shaped answer; workbook template_sections is
  the thing being retired). The init-order half (call `_meRebuildSections`
  from `loadDraftManifest` after ensuring `_workbookRules`) is SONNET-FIXABLE
  if the workbook source is deliberately kept in the interim.

### FINDING-008: accessory-homed products appear as ordinary top-level products in the picker grids
- **Location:** `app/routes/parts_db.py` `category-skus` (no accessory
  exclusion; contrast `sku_grid.js:_skgIsAccessoryPt` which *does* exclude them
  from its part-type selector)
- **Category:** doc-drift / dead-or-misleading UI state
- **Severity:** MEDIUM
- **Status:** CONFIRMED
- **Repro:** `category-skus?type=lights` includes 54 products homed to
  accessory part_types (dtm brackets, grommet mounts, …) + 4 with child-side
  accessory roles; equipment list includes 57. Docs
  (PARTS_DB_AND_PICKER §2.5) state an accessory "is selectable only as an
  accessory of its parent."
- **Note:** this leak is currently the *only* way to order a spare
  bracket/cable standalone — the planned "Accessories section in the picker"
  (§2.5) doesn't exist yet. Fixing the leak without that section removes a
  real (if accidental) capability.
- **Disposition:** NEEDS-DESIGN — decide the standalone-accessory UX first.

### FINDING-009: `planning/part_type_resolver.py` is an island
- **Location:** `planning/part_type_resolver.py` (49 LOC)
- **Category:** island
- **Severity:** LOW
- **Status:** CONFIRMED — repo-wide grep: only `tests/test_part_type_resolver.py`
  imports it. The planner instead re-implements name→part_type matching as
  `_find_part_type_by_name` (`planning/planner.py:64-90`), and sequencing lives
  in `inputs/project_drafts.py:renumber_parts` + the picker's client-side
  `_pickerSequencedName` — three parallel naming/sequencing implementations.
- **Disposition:** NEEDS-DESIGN (Pass 2): either make it the single naming
  authority or delete it. Flagging as the seed of a `duplication` cluster.

### FINDING-010: `sku-bulk` edit action trusts bare indexes — stale grid can hit the wrong SKUs
- **Location:** `app/routes/parts_db.py:590-617`; client `sku_grid.js:749-772`
- **Category:** fragile (data integrity in the curation tool)
- **Severity:** MEDIUM
- **Status:** SUSPECTED (static; single-user today, but the grid is stale by
  design — `_skg` is fetched once per app session, FINDING-014 — and the 60s
  SharePoint sync can rewrite the doc under it)
- **Failure scenario:** teammate sync (or another tab) reorders/removes
  `part_numbers` between grid load and a bulk delete → `sku-bulk` deletes by
  now-shifted index, destroying different SKUs than selected. Single
  `sku-update`/`sku-delete` already carry `expect_part_number`; bulk doesn't.
- **Disposition:** SONNET-FIXABLE — carry `expect_part_number` per target,
  skip-and-report mismatches.

### FINDING-011: duplicated brand-preference auto-select + `_brandAutoSet` never reset
- **Location:** `ui/js/part_picker.js:219-231` (in `_pickerFetchProducts`) vs
  `part_picker.js:496-503` (in `_pickerRenderProducts`); `_brandAutoSet` absent
  from `_pickerResetState`
- **Category:** duplication + state bleed
- **Severity:** LOW
- **Status:** SUSPECTED (static)
- **Failure scenario:** two competing implementations of "auto-pick preferred
  brand" run on different triggers; `_pickerState._brandAutoSet` survives
  picker close (only a page reload clears it), so the preferred-brand
  auto-select behaves differently on the second open of the same session.
- **Disposition:** SONNET-FIXABLE — single implementation, reset with the rest
  of the state.

### FINDING-012: `draft_to_project_input` drops `parent_line_id` / accessory fields — planner can't distinguish child lines
- **Location:** `inputs/project_drafts.py:238-274`
- **Category:** fragile
- **Severity:** MEDIUM (enabler for FINDING-006's warning noise; also blocks
  any future planner awareness of accessories)
- **Status:** CONFIRMED (accessory child produced a top-level "Unmapped part"
  warning in the plan)
- **Disposition:** SONNET-FIXABLE once FINDING-006's design point (how children
  should plan) is settled; flag together.

### FINDING-013: doc-drift cluster (picker docs vs verified behavior)
- **Category:** doc-drift · **Severity:** LOW · **Status:** CONFIRMED
- (a) PARTS_DB_AND_PICKER §7 "Non-light / no-color products still show a
  placeholder in the SKU step" — **stale**: the non-light flow renders a full
  SKU pick list with Select pills and works end-to-end (verified live). The
  actual finish-line gap is FINDING-004's naming, not a placeholder.
- (b) §2 "Trio is rejected at match time (a 3-color head isn't a single SKU)" —
  **stale**: `match_heads` matches tertiary_color; live probe: trio head on ION
  → `all_matched: true` via a real tri-color SKU. The sku_resolver docstring
  carries the same stale claim.
- (c) UI_STRUCTURE.md lists part-manager inner stabs as
  `catalog | parts | parts-db` — missing `sku-grid` (the primary surface since
  2026-06-29; the smoke harness already clicks it).
- (d) PARTS_DB_AND_PICKER §4 says 3/5/6-lamp tracers auto-pair on running
  boards, but `_pickerTracerAutoLocation` only fires for `lamps >= 5` — a
  3-lamp tracer gets the housing pair with no auto running-board location
  (SUSPECTED, static).
- **Disposition:** SONNET-FIXABLE (doc edits + decide (d) direction).

### FINDING-014: SKU grid caches `parts_db` for the whole app session
- **Location:** `ui/js/settings/sku_grid.js:27-34` (`if (!_skg) await _skgLoad()`)
- **Category:** fragile
- **Severity:** LOW (manual Reload button exists)
- **Status:** SUSPECTED
- **Failure scenario:** cloud sync or Hierarchy-tab edits change the doc; the
  Review grid keeps rendering (and index-addressing — FINDING-010) the stale
  copy until the user clicks ⟳.
- **Disposition:** SONNET-FIXABLE — refetch on tab activation.

### FINDING-015: tracer L-bracket quantity rule duplicated in two JS files
- **Location:** `ui/js/part_picker.js:1543-1549` vs
  `ui/js/manifest_editor.js:262-270` (`(lamps+1)×housings` + LBKT sniffing)
- **Category:** duplication
- **Severity:** LOW · **Status:** CONFIRMED (code identical in intent, drift-prone)
- **Disposition:** SONNET-FIXABLE (shared helper) — or server-side with the
  Pass-2 accessory work.

### FINDING-016: `qb_unit_price or price_usd` treats a legitimate $0 QB price as missing
- **Location:** `app/routes/parts_db.py` (category-skus, zone-products,
  accessories), `planning/sku_resolver.py:111`, `ui/js/settings/sku_grid.js:433`
- **Category:** fragile · **Severity:** LOW · **Status:** SUSPECTED
- **Disposition:** SONNET-FIXABLE (`is not None` discipline).

### FINDING-017: legacy config surface still feeding the picker slice (inventory, no action)
- **Category:** legacy · **Severity:** LOW (tracked for Phase 4) · **Status:** CONFIRMED
- The flat fallback modal drives entirely off `part_catalog.json` +
  `workbook_rules.part_rules` (by design until Chunk 9).
- `_resolve_product_locations` prefers `location_options` but still falls back
  to `svc.locations_by_legacy_name` (workbook rules) and uses
  `part_catalog.json` `default_views`/`render_kind` as the render test — the
  picker's "guaranteed to render" contract is pinned to the legacy catalog.
- Manifest section grouping: FINDING-007.
- **Disposition:** ledgered as Phase-4 cutover inputs, not individually fixable
  now.

---

## Capability notes for OPEN_QUESTIONS §B (facts only, no recommendations)

Empirically established 2026-07-08 against the live picker; for the owner's
taxonomy rulings.

1. **`accessory_of_products` children in the picker.**
   *Parent → child:* works. Selecting a parent product surfaces one dropdown
   per accessory category (`/api/parts-db/accessories` unions part_type-level,
   parent-side, and child-side declarations; e.g. `whelen_ion` → bracket_mount
   with 15 options); Add is hard-gated until every category has a choice or
   explicit "None"; chosen accessories become nested, individually
   editable/removable child lines with a category-scoped swap dropdown.
   *Child → parent:* **no path.** Nothing in the picker shows that a product is
   an accessory or names its parents (only the Part-Manager SKU grid shows
   "belongs to" chips). Accessory-homed products do appear as ordinary products
   in the picker grids (FINDING-008), so a user *can* add a bare bracket — but
   with no parent linkage, and (being text-mode/zero-option homes) it lands as
   a "Part" line (FINDING-004).

2. **Multi-homed products.** 26 products carry >1 home. Within one picker
   category the product list de-dupes: `whelen_ez_scene` (front+rear+side
   scene) appears **once** in the scene grid. No product is homed across two
   *types* today, so cross-type double-listing is untested behavior. The homes'
   only other UI effect is the SKU-grid tree filters (product matches each
   zone's filter). The location pool is category-wide regardless of which scene
   home(s) a product has — multi-homing does **not** widen or narrow placement
   choices (and per FINDING-001 front/roof are dropped for everyone).

3. **Kit/system parent with component SKUs — not expressible today.** The
   schema has no kit fields (probe: zero `*kit*` keys on any of ~1,290 SKUs).
   The three existing composite mechanisms are: (a) `DraftPart.components` —
   picker-generated, per-draft display-only breakdown, dropped before the
   planner; (b) accessory parent/child product links — separate priced lines,
   not one billed unit; (c) the tracer/lightbar resolvers — hard-coded family
   logic. A kit SKU that mirrors QB billing (one line, fixed members) matches
   none of these; it is the new per-SKU concept scoped in
   PARTS_DB_AND_PICKER §7 "Kit SKUs".

4. **What actually distinguishes zone-split part_types vs placement-driven
   zoning.** For scene (`front/rear/side_scene`), the split is load-bearing in
   exactly three places today: (i) the SKU-grid tree filters; (ii)
   `_resolve_category_locations`' per-zone label-keyword lookup, which uses the
   zone-named labels to pick the base name ("Rear Scene 2") — and is already
   broken for front/roof (FINDING-001); (iii) multi-homing as the "fits
   anywhere" idiom (§2 above shows it's cosmetic for placement). **If the owner
   collapses scene to one `scene_light`:** with no code change, scene would
   behave like `interior` does today — the keyword lookup finds no part_type
   for *any* zone and the location step returns **zero** placements
   (FINDING-002 shows this exact failure mode live); making it work requires
   the same special-casing `warning_light` already has (single home +
   `_WARNING_ZONE_NAME`-style zone→base-name table — warning's empty
   `tree_positions` prove the tree can be bypassed). **If scene stays split:**
   FINDING-001's keyword table still needs fixing (front/roof unreachable
   now). The zone-named *bracket* types (audit §3.1) are accessory part_types —
   excluded from placement selectors entirely, so collapsing them cannot change
   any picker placement behavior; their only picker surface is via accessory
   dropdowns and the FINDING-008 leak.

Special-UI candidates (PARTS_CURATION_AUDIT §6) — what each gets from the
picker **today** (all CONFIRMED via probe):

| Candidate | Products | Location step today | Accessories today |
|---|---|---|---|
| front_partition | 5 | free-text (0 options) → "Part" naming (F-004) | `other` ×4 |
| push_bumper | 23 | 45 diagram dots (placement mode — works) | none wired |
| gun_lock (+bracket) | 20 (+36) | free-text → "Part" | bracket_mount ×36 |
| remote_start | 5 | free-text → "Part" | none wired |
| radar_display_unit | 4 | free-text → "Part" | bracket_mount ×4, cable ×2 |
| console | 30 | free-text → "Part" | none wired |
| seat_covers | 8 | 5-option dropdown (works, names correctly) | none |
| floor_pan | 2 | free-text → "Part" | none |

I.e. before any special configurator work, FINDING-004 + zero
`location_options` make five of the eight candidates produce unusable manifest
lines through the standard flow; `seat_covers` demonstrates the same flow
working once options exist.

---

## Prioritized fix queue — "blocks curated parts from being usable" first

1. **FINDING-004** (SONNET-FIXABLE) — "Part" naming on zero-option location
   steps. Kills the standard flow for most of the 384-product curation queue's
   target part_types. Pair with seeding `location_options` for
   console/gun_lock/docking_station (data work already roadmapped).
2. **FINDING-005** (NEEDS-DESIGN; stopgap SONNET-FIXABLE) — edit mode corrupts
   parts. Any curated part touched via ≡ Edit is destroyed; this will bite the
   moment real builds use picker parts.
3. **FINDING-001 + FINDING-002** (NEEDS-DESIGN — one decision) — scene
   front/roof + interior location pools. Blocks scene/interior lights;
   the fix shape depends on the owner's scene-collapse ruling, so putting the
   ruling first unblocks both.
4. **FINDING-006 (+012)** (SONNET-FIXABLE) — surface plan warnings, stop
   dropping off-diagram parts silently, de-noise accessory-child warnings.
   Makes every remaining gap *visible* instead of a support mystery.
5. **FINDING-007** (split) — init-order half now (SONNET-FIXABLE) so sections
   at least render consistently; grouping-source half joins the Phase 4
   pipeline-inversion decision.
6. **FINDING-003** (SONNET-FIXABLE) — vehicle-aware lights location pool.
7. **FINDING-010 + 014** (SONNET-FIXABLE) — curation-tool data-integrity
   hardening (bulk expect-guards, grid refresh).
8. **FINDING-008** (NEEDS-DESIGN) — standalone-accessory UX (decide before
   closing the leak).

---

## Session 2026-07-08 — §8.1 Step 0 (audit workspace instrumentation)

**Scope:** Phase A tooling only — `tools/audit_scan.py` (new, generates
`MANIFEST.md`), plus folding in findings already surfaced by prior design
sessions but never formally ledgered: the two named findings from
`PARTS_DB_REPOSITORY_SPEC.md` §1.4 (F-1, F-4), the bandit first-pass triage,
the `DTM_CLOUD`/packaged-app path-injection gap from `UI_SMOKE_SPEC.md` §2.1,
and the Step 2 import-linter baseline (`pyproject.toml`). **Method:**
docs-first (spec + GOTCHAS.md), then direct tool runs (`bandit`,
`audit_scan.py`) against the repo as it stands post-curation (13 curation
plans applied this session, see git log — parts_db.json product count 906→779).
Zero production-code changes.

### FINDING-018: 60s cloud sync never invalidates the `PartsDbService` read cache (spec F-1)
- **Location:** `app/server.py::_run_sync_cycle` -> `sync_shared_settings_at_startup`
  (writes `/Settings/parts_db.json` into the workspace config dir and bumps
  `data_version`); `app/services/parts_db_service.py` (singleton cache, no
  subscriber to the sync event)
- **Category:** fragile · **Severity:** MEDIUM — multi-device correctness, not
  data loss (cache heals on next local mutation or process restart)
- **Status:** SUSPECTED (design-session finding, not re-reproduced live this
  session — reproduction would require two cloud-connected devices)
- **Mechanism:** a teammate's parts_db edit lands on this device's disk via the
  60s sync loop, but the in-memory `PartsDbService` cache (picker, SKU grid,
  estimates all read through it) is never told to `invalidate()`. Stale reads
  persist until something else happens to call it.
- **Disposition:** SONNET-FIXABLE, scheduled as Stage C4 of the Step 4
  parts-DB repository extraction (`PARTS_DB_REPOSITORY_SPEC.md` §4 C4) — the
  repository owns invalidation as a first-class concern; fix is a flagged
  behavior improvement (§3.2 opt-in diff, own commit + ROADMAP decision-log
  entry), not bundled into the extraction's mechanical move.

### FINDING-019: GOTCHAS.md #21 claims parts_db isn't wired into production reads — false, doc-drift (spec F-4)
- **Location:** `docs/GOTCHAS.md` #21 ("`parts_db.json` is populated but not
  wired into production reads (Phase 3)... generator, planner, manifest
  editor, rule engine, and excel reader still drive off `workbook_rules.json`
  / `parts_library.json` / `vehicle_layouts.json` / `part_catalog.json`")
- **Category:** doc-drift · **Severity:** LOW (misleads future editors, no
  runtime effect) · **Status:** CONFIRMED — `planning/planner.py:152` lazy-
  imports `app.services.parts_db_service` as a live catalog fallback (the
  baselined upward import in the layer-lint contract below), and the picker,
  SKU grid, and QB estimate flows all read parts_db in production today
  (PARTS_DB_AND_PICKER.md "SHIPPED" sections; Step 3 picker cluster shipped
  2026-07-01).
- **Disposition:** doc fix, not code — correct GOTCHAS #21 when the Step 4
  parts-DB repository extraction lands (three-way reconciliation rule, roadmap
  §7); until then the entry stays as a known-stale marker rather than being
  silently deleted, since dispositioning docs outside a landing change risks
  losing the "why" context the extraction session needs.

### FINDING-020: bandit first-pass triage — 51 low / 4 medium / 1 high (report-only, `checks.yml` doesn't fail the build on findings)
- **Location:** `.github/workflows/checks.yml` `bandit` job (`bandit -r
  src/dtm_buildsheet -f txt`, no `-ll`/exit-code gate — Phase A wired it
  report-only per roadmap §6 "standing tooling, not one-off effort")
- **Category:** security · **Severity:** see breakdown below · **Status:**
  CONFIRMED (`.venv/bin/bandit -r src/ -q` run this session, matches the
  roadmap's recorded 51L/4M/1H exactly)
- **High (1):** `B324:hashlib` — `paths.py:109` `_md5()` uses MD5
  (`hashlib.md5`) for a **file-change-detection checksum** in
  `_copy_missing_tree` (bundled-asset seeding), not for anything
  security-sensitive (no secrets, no integrity-critical verification). Fix is
  trivial (`usedforsecurity=False` kwarg, Python 3.9+) but not urgent —
  ledgered as SONNET-FIXABLE, not a hotfix per §6 triage (no exploitable
  boundary).
- **Medium (4):** `B608:hardcoded_sql_expressions` — `app/adapters/quickbooks/
  api_client.py:115,138,169,201`, all string-built QB query filters (e.g.
  `WHERE Id = '{id}'`-shaped QBO query-language strings, not SQL against a
  local DB — QuickBooks Online's query API has no separate parameterized-query
  mechanism in the REST surface this client uses). Confidence is Low per
  bandit's own scoring (pattern-matched, not data-flow-verified). Needs a
  boundary-specific answer (do the interpolated values come only from
  internal IDs, or can user input reach them?) — **NEEDS-DESIGN**, scoped to
  the §6 QuickBooks OAuth/API boundary session, not fixed here.
- **Low (51):** not itemized per-line in this pass (Phase B ledger material
  per roadmap §8 Phase C exit gate: "no open high-severity... retirement-slated
  ones dispositioned"); dominated by `try/except/pass` (`B110`) and subprocess/
  shell patterns typical of a desktop packaging codebase. One sampled:
  `ppt_helpers.py:217` swallows an exception around optional logo placement
  (cosmetic-failure-tolerant by design, not a hidden bug — still worth a
  narrower `except` when that function is next touched).
- **Disposition:** ledgered for Phase B/C triage per roadmap §8 (Phase C
  handles boundary/crash findings; legacy-slated locations are fixed-by-D, not
  patched twice — none of these four boundary/high findings sit in a
  retirement-slated module, so none qualify for that exemption).

### FINDING-021: `cloud_config_path()` reads a module-level constant, not the injected `AppPaths` — hermetic-workspace isolation gap outside test/smoke code
- **Location:** `app/adapters/cloud/config.py::cloud_config_path()` (reads
  `WORKSPACE_DIR` from `paths.py` module scope); `paths.py`
  `ensure_workspace()` (seeds `cloud_config.json` from
  `resources/default_data/` into any fresh workspace — a deliberate
  teammate-first-launch convenience, confirmed present at
  `src/dtm_buildsheet/resources/default_data/cloud_config.json`)
- **Category:** doc-drift / fragile (architecture-rule violation: `AppPaths`
  is the documented dependency-injection seam for all path-scoped state,
  `ARCHITECTURE.md`'s ports-and-adapters framing implies cloud config should
  flow through it too) · **Severity:** MEDIUM — no production bug (the live
  app always wants the module-level workspace), but it is a real trap for any
  future code assuming `AppPaths` injection is sufficient for isolation
- **Status:** CONFIRMED — this exact gap is what forced `UI_SMOKE_SPEC.md`
  §2.1 to add `DTM_CLOUD=0` as a *mandatory* isolation layer on top of the
  hermetic `AppPaths` workspace (a hermetic `AppPaths` alone does **not**
  disable cloud); documented in the smoke-harness design but never entered as
  a ledger finding in its own right.
- **Disposition:** NEEDS-DESIGN if ever "fixed" (making `cloud_config_path()`
  take an `AppPaths` would touch every call site and the seeding behavior is
  intentional product behavior, not a bug) — for now this is a **documented
  constraint**, not a defect: any future harness/test code touching cloud
  config must use the three-layer isolation pattern (`UI_SMOKE_SPEC.md`
  §2.2: env + throwaway workspace + netguard), never `AppPaths` substitution
  alone. No fix scheduled; ledgered so the constraint survives past this
  session instead of living only in one design doc.

### FINDING-022: Step 2 import-linter baseline — five grandfathered violation clusters (inventory, no new action)
- **Location:** `pyproject.toml` `[tool.importlinter]` (shipped commit
  `6d0e699`, verified still current this session)
- **Category:** legacy / fragile · **Severity:** tracked per-entry, none newly
  discovered · **Status:** CONFIRMED (read directly from the live contracts)
- **Layers contract** (`ignore_imports`, layered-core): `planning.planner ->
  app.services.parts_db_service` (upward; retires at Step 4 repository
  extraction), `planning.planner -> config.loader` (retires at Step 4/6),
  `planning.planner -> config_loader` shim (retires at Step 6, also listed
  below), `inputs.project_drafts -> app.services.shared_work_service` and
  `inputs.project_entry -> app.services.shared_work_service` (both: inputs→app
  cloud-mirroring upward dependency, retirement scheduled as a Phase E finding
  via the Step 7 breadth-audit ledger — no extraction step currently owns it).
- **Forbidden-shim contract**: `__main__ -> gui_server` (retires Step 6c);
  `generator -> config_loader/input_reader/planner` (retires Step 6a);
  `template_builder -> config_store` (retires Step 6b); `app.services.
  generation_service -> input_reader` (retires Step 6a); `planning.planner ->
  config_loader` (retires Step 6, duplicate entry with the layers contract
  above — same underlying import, two contracts flag it).
- **External-I/O contract**: `app.services.exports_upload_service -> requests`
  and `app.services.build_state_service -> requests` (both call Graph/HTTP
  directly instead of going through an `app.adapters` port; Phase E findings
  via Step 7 ledger, no extraction step currently owns either).
- **Disposition:** no action this session — this entry exists so the
  baseline's current membership is captured in the findings ledger (not only
  in `pyproject.toml` comments), satisfying the roadmap's request to fold
  "Phase E lint-baseline entries" into `LEDGER.md`. The baseline is
  shrink-only and self-enforcing (import-linter errors on unmatched ignores);
  each entry's retiring step is unchanged from Step 2's landing commit.

---
9. **FINDING-009, 011, 013, 015, 016, 017** — Pass-2 / doc hygiene batch.

---

### NOTE-023: migration safety — curation does not change existing (name-based) build output
- **Verified 2026-07-07** (Opus, pre/post render diff). Both real anonymized PIU draft
  fixtures (`draft_piu_admin`, `draft_piu_patrol`) render to a **byte-identical normalized
  PPTX digest** with the pre-curation parts_db (906 products, commit 42c9f4b) vs the
  post-curation HEAD (779 products) — code held constant, only parts_db swapped in a
  hermetic workspace.
- **Why it matters:** existing builds (and other users' builds) reference parts by workbook
  **role name + freeform part number** (e.g. "Forward Warning 1 / ION"), never by parts_db
  `product_id`/SKU. The name-based rendering path is inert to the product merges/deletes/
  re-homes curation performed, so pushing the curated parts_db cannot regress existing
  name-shaped builds' output.
- **Scope / honesty:** 2 PIU drafts are the only real fixtures available (other vehicle
  types have none — corpus TODO). The mechanism generalizes, but this is representative,
  not exhaustive. Separately, this does NOT verify that a teammate's *deployed app version*
  can load `schema_version: 2` parts_db without error — that is a distinct pre-push
  compatibility check (owner to confirm deployed version).
- **Pipeline-inversion tie-in:** the very inertness that makes today's push safe IS the
  `workbook-shape` consumer seam Phase 4 eventually inverts. Safe now; deliberately changed
  later, through the §3.2 re-record protocol.

---

### FINDING-024: orphaned/accessory `lights` part_types render as selectable browse-tree leaves
- **Found 2026-07-09** (Step 1 ship). Several part_types typed `lights` show as bare, selectable
  leaves in the new accordion but are not real user-pickable parts: accessory-category
  placeholders (`lighthead`, `cable`, `flange`, `shroud`, `flasher_power`, `bracket`,
  `bar_takedown`) and orphaned warning-collapse leftovers (`tracer_2_lamp`, `tracer_5_lamp`,
  `tracer_6_lamp`). They lack `accessory_of`, so Step 1's accessory-exclusion rule doesn't catch
  them.
- **Category:** doc/data-drift (browse-tree clutter) — cosmetic now, but degrades the Step 1
  result and will confuse the accessory-browse UX later.
- **Disposition:** Step 0 follow-up (DB, SONNET-FIXABLE). For each: either set
  `accessory_of`/`accessory_category` so the exclusion rule hides it, or drop it from
  `part_types` if truly orphaned (the empty tracer types are warning-collapse leftovers already
  flagged in PARTS_CURATION_AUDIT §3). Ties into OQ-8 (generic bracket/cable/flange homes,
  deferred to the accessory-browse design) — resolve together.
- **Status:** RESOLVED (2026-07-09). `_build_browse_tree` now skips any part_type with
  `accessory_category` set (covers the 7 accessory-home types) and any with `browse_hidden: true`
  (covers the 3 tracer orphans — retained in data for the planner's name-based resolution but
  invisible in the browse tree). Browse-tree contract re-recorded; 10 junk leaves removed.
  Golden masters unchanged. Full pytest green (1709 passed).

---

### NOTE-025: push-safety re-assessed for teammates on v2.2.14 (supersedes the optimistic read of NOTE-023)
- **Teammate app version: v2.2.14** (a tag in this repo). Two push risks assessed against it:
- **Load compatibility — SAFE.** v2.2.14's `_validate_parts_db` (schema_version 2, same as ours)
  `setdefault`s required top-level keys and checks per-entity *required* keys only — it does NOT
  reject unknown keys. So the additive `families` top-level collection and `family_id` on
  part_types are tolerated; v2.2.14 ignores them. (Small confirm remaining: that every curated
  product/part_type still carries v2.2.14's *required* keys — very likely, same schema era.)
- **Legacy render correctness — the wrongness is PRE-EXISTING, not push-caused.** The owner
  observed legacy projects render imperfectly in the dev preview. Diagnosis: (a) NOTE-023 —
  curation/taxonomy *data* is byte-inert to legacy render; (b) the Step 1 picker code does NOT
  reach the render path — `DraftPart.part_type` (new) defaults `""` and is authoring-only; the
  planner still resolves rendering by NAME (`planner.py:197` `_find_part_type_by_name`). So
  neither the data nor the recent code changed legacy rendering. Pushing cannot make teammates'
  legacy rendering worse — the imperfection lives in the name-based path the push doesn't touch.
- **Correction to earlier framing:** "curation doesn't change output" (verified) is NOT the same
  as "legacy builds render correctly." They render imperfectly, pre-existing — the workbook-shape
  consumer seam (Phase 4). **Fix = remake the two existing builds in the new picker/SKU system**
  (already the owner's plan), not debug the legacy name-based path or block the push.
- **Net:** the push is materially safe for v2.2.14 teammates on both load and render grounds.

---

## Session 2026-07-10 — Legacy-project rebuild in the new picker (owner flaw list)

**Scope:** drive the real app (cloud-off) to rebuild the 3 legacy name-based drafts
(`workspace/projects/*` → `workspace/drafts/*`: Test/PIU-Patrol 6 parts, Granite Falls 55,
Toppenish 50) through the redesigned Part Picker, fixing picker/placement flaws as they
surface. Owner supplied an 8-item starting flaw list. Curation queue is now fully drained
(0 unhomed non-accessory products; docs still say 673 — stale).

### FINDING-025: cross-type family member returns an empty product grid (owner flaw #3, part 1)
- **Location:** `app/routes/parts_db.py` `category-skus` handler (the `pt.type_id == type_id`
  gate) — client passes the family's *display* `type_id`, not the member's own.
- **Category:** fragile · **Severity:** MEDIUM (a populated part_type looks empty) · **Status:** RESOLVED (2026-07-10)
- **Repro:** picker → Structural → Console System → Motion Attachment → empty grid, though
  `motion_attachment` has 5 homed products. It is the *only* cross-type family member
  (`type_id: equipment`, surfaced under the Structural `console_system` family). The leaf
  sets `data-type="structural"`; `category-skus?type=structural&part_type=motion_attachment`
  then filtered on `pt.type_id == "structural"` and dropped it.
- **Fix:** when an exact `part_type` filter is supplied (every non-light sidebar leaf), look
  it up directly (`svc.get_part_type`) instead of gating on the display-derived type/category.
  Server-only; contract snapshots + golden masters unchanged (recorded queries never hit the
  cross-type case), 8/8 ui_smoke. Commit `0f2d352`.

### FINDING-026: 10 browse-tree leaves are genuinely unhomed slots (owner flaw #3, part 2) — NEEDS-OWNER
- **Status:** OPEN · needs an owner curation ruling, not a code fix.
- After FINDING-025, a full live sweep of all 94 browse leaves leaves **10 empty**, all
  because no product is homed to them (queue is drained, so no unhomed product to assign):
  - **Cameras** — `front_camera`, `rear_camera`, `rear_seat_camera`, `body_camera_dock`:
    camera products exist but are all homed to `camera_dvr` (the DVR unit). The individual
    position slots have nothing.
  - **`cradle_point` (Cloud System)**, **`door_lock_button`**, **`wireless_mic_charger`**:
    no matching product exists anywhere in the DB (agency-supplied / not catalogued).
  - **`radio_speaker`**, **`radio_antenna_cable`**: radio products are homed to sibling
    slots (`radio_head`/`radio_cable`/`radio_antenna_top`/`radio_mic_clip`), none to these.
  - **`k9_control_head`**: K9 products homed to `k9_kennel`/`k9_heat_alarm_popper`/`k9_add_ons`,
    none to control-head.
- **Owner decision per slot:** (a) create/home a product, (b) keep as an intentional
  agency-supplied placeholder (perhaps show a "supplied by agency" note instead of an empty
  grid), or (c) remove the slot. Ties into the `unbilled` tag convention (cameras/radios are
  the canonical unbilled items). No guessing — flagged for the owner.

### FINDING-027: "Console 1" sequencing removed for single-instance part_types (owner flaw #2) — RESOLVED
- **Location:** `ui/js/part_picker.js` `_pickerDrawLocation` free-text location
  branch + new `_pickerFreeTextPartTypeMax(f)` helper.
- **Category:** workbook-shape (naming contract assumed every part_type
  auto-sequences) · **Severity:** LOW (cosmetic, but user-facing) · **Status:** RESOLVED (2026-07-10)
- **Owner flaw #2:** "The 'Console 1' concept is unnecessary. There will only
  ever be one console in a vehicle."
- **Fix:** part_types with `max_count == 1` (exactly `console`,
  `equipment_tray`, `preemption`) now resolve `loc.name_pattern` to the bare
  part_type label with no `{n}` suffix — `"Console"`, not `"Console 1"`.
  Every other text-mode part_type keeps the `"{label} {n}"` auto-sequence from
  FINDING-004. Client-side JS only; no server/contract changes.
- **ui_smoke:** both console-touching flows updated. `flow_add_text_mode_equipment_part`
  (FINDING-004's regression guard) is repurposed as the single-instance guard —
  two adds now assert `names == ["Console", "Console"]` instead of the old
  `["Console 1", "Console 2"]`. `flow_picker_multi_add` (Step 7 multi-add) moved
  off `console` (no longer sequences, so it can't guard numbering) onto
  `gun_lock` (Equipment > Gun Lock, a bare text-mode leaf with no family) to
  preserve multi-instance sequencing coverage — asserts `"Gun Lock 1"` /
  `"Gun Lock 2"` after two adds. This supersedes the `"Console 1"` / `"Console 2"`
  verification detail in FINDING-004's resolution note. 8/8 ui_smoke,
  `tests/contract` + `tests/golden` unchanged (client-only change).

### FINDING-028: 25 Gamber Johnson SKUs mis-tagged vehicle_tags:["any"] (owner flaw #1) — RESOLVED
- **Location:** `src/dtm_buildsheet/resources/config/parts_db.json`, 25 Gamber Johnson
  part_number entries (console/leg/pedestal kits).
- **Category:** data-curation (workbook-shape leftover) · **Severity:** MEDIUM (wrong parts
  offered per vehicle) · **Status:** RESOLVED (2026-07-10)
- **Owner flaw #1:** vehicle-specific console/leg/pedestal kits were tagged
  `vehicle_tags: ["any"]`, so a kit built for one vehicle (e.g. a PIU-specific box) showed up
  for every vehicle in the picker's compat filter.
- **Fix:** corrected each of the 25 SKUs' `vehicle_tags` to the vehicle(s) actually named in
  its product description — verified per-SKU, no guessing. Genuinely-universal Gamber parts
  (blank filler panels, universal cradles, docking stations) were left `["any"]` since they
  really do fit any vehicle.
- **Verification:** golden masters unchanged (`tests/golden -q`, 6/6 — vehicle_tags is inert
  to the name-based render path, NOTE-023/025); contract snapshots re-recorded intentionally
  (`root_doc`, `products_all`, `category_skus_by_part_type` embed `vehicle_tags`; diffs
  eyeballed to be exactly the 25 SKUs' `"any"` → specific-vehicle changes, nothing else,
  37/37 passing after re-record); 8/8 `tools/ui_smoke/run_smoke.py`.

### FINDING-029: brand preference auto-select unified + extended to all prefs (owner flaw #5) — RESOLVED
- **Location:** `ui/js/part_picker.js` — new `_pickerPreferredBrand(f)` helper +
  `_PREF_BUMPER_PART_TYPES` / `_PREF_CAGE_PART_TYPES` / `_PREF_CAMERA_PART_TYPES` scope
  consts, `_pickerFetchProducts`, `_pickerRenderProducts`, `_pickerWireBrand`,
  `_pickerResetState`, `_pickerOpenEdit`, browse-tree leaf-click handler; `ui/styles.css`
  new `.pp-brandbar-pref` / `.pp-pref-chip` / `.pp-pref-badge` / `.pp-brand-more` rules.
- **Category:** picker UX (auto-select scope + information architecture) · **Severity:**
  MEDIUM (wrong/missing brand pre-selection, cluttered brand row) · **Status:** RESOLVED (2026-07-10)
- **Also closes FINDING-011** (duplicate lighting-only auto-select: it ran once in
  `_pickerFetchProducts` and again in `_pickerRenderProducts`, both lighting-only, and the
  `_brandAutoSet` latch was never reset in `_pickerResetState` so it could leak across picker
  opens). Both call sites are now one `_pickerPreferredBrand(f)` call, and the latch resets
  on every `_pickerResetState()`.
- **Owner flaw #5:** "Right now light brands are auto selected based on agency preference,
  but no other preferences seem to auto select a brand. And also the brand that is the
  preference should be the first in the line of brands always. In fact, the other brands
  should be collapsed into a dropdown to select only if they want to. And the preferential
  brand should be notated as so, so its clear why its pre selected."
- **Fix:**
  1. `_pickerPreferredBrand(f)` resolves a preferred brand for lighting (`type_id==="lights"`
     → `preferences.lighting_brands[0]`), bumper (`push_bumper`/`pit_bar`/`wing_wraps` →
     `preferences.push_bumper_brand`), cage (`cage`/`front_partition`/`rear_partition`/
     `rear_seat_divider`/`floor_pan`/`replacement_rear_seat`/`k9_kennel` →
     `preferences.cage_brand`), and camera (`camera_dvr`/`front_camera`/`body_camera_dock`/
     `rear_seat_camera`/`rear_camera` → `preferences.camera_brand`) — the part_type_id scopes
     mirror parts_db.json's (currently otherwise-unused) `preference_filters` block. Only
     returns a brand that actually appears among the loaded products.
  2. Product list "preferred brand first" sort (previously lighting-only) now uses the same
     helper, so it applies to all four scopes.
  3. Brand bar: when a preferred brand exists, it renders as its own chip with a
     `"preferred"` badge (`.pp-pref-badge`), selected by default; every other brand + "All
     brands" collapse into a closed-by-default `<select class="pp-brand-more">`. No
     preference (or preferred brand absent from the loaded products) falls back to the
     original plain pill row; a single brand still renders nothing.
  4. Edit mode: `_pickerFetchProducts`'s auto-select is skipped while `editLineId` is set;
     `_pickerOpenEdit` instead sets `filters.brand` directly from the part's own product once
     it's resolved, so an explicit prior brand is never overridden by a preference.
  5. Browse-tree leaf clicks reset `filters.brand`/`_brandAutoSet` (outside edit mode) so
     navigating between scopes (e.g. lighting → cage) re-resolves the preference for the new
     context instead of carrying a stale brand filter forward.
- **Verification:** `tests/golden` + `tests/contract` unchanged (43/43, client-only change).
  `tools/ui_smoke/run_smoke.py` 9/9 (added `brand_preference_collapse`, which seeds
  `lighting_brands:["Whelen"]` explicitly — `_seed_project_with_draft`'s default fixture has
  no preferences set at all, so a new optional `preferences` kwarg was added to it,
  backward-compatible with every existing caller). The new flow asserts
  `_pickerState.filters.brand` auto-selects `"Whelen"` for a Warning-light part type, that
  `.pp-brand-more`'s options do not include the preferred brand, and that the preferred chip
  reads "preferred". Manually verified live (`DTM_CLOUD=0`) against a real project with
  `lighting=Whelen`/`push_bumper=Setina`/`cage=Setina`: Whelen auto-selects and shows
  "Whelen · PREFERRED" with a collapsed dropdown for Warning Light; Setina independently
  auto-selects for Push Bumper and for Front Partition (cage scope, single-brand catalog
  there so the bar itself doesn't render, but the filter still auto-applies); selecting
  another brand from the dropdown deselects the preferred chip and re-filters the grid;
  re-clicking the preferred chip restores it. No console errors observed.

### FINDING-030: manifest grouping moved to parts_db category+family (owner flaw #4) — RESOLVED
- **Location:** `ui/js/manifest_editor.js` — new `_meBuildGroupMap` /
  `_meSectionKeyForName` / `_meSectionForPart` replace `_meRebuildSections` /
  `_meSectionFor`; `loadDraftManifest`, `_mePopulateDataLists`, `_meRender`,
  `addPartInSection` updated to use the new grouping; `ui/styles.css` new
  `.me-cat-group-head` rule.
- **Category:** workbook-shape default + state bleed (DOM-singleton/lazy-global
  pattern) · **Severity:** HIGH (was) · **Status:** RESOLVED (2026-07-10)
- **Owner flaw #4:** "The parts manifest should use new categories to sort
  everything by main category and part type family."
- **Resolves FINDING-007 in full** — both the NEEDS-DESIGN grouping-source
  question (answered: parts_db taxonomy, not workbook `template_sections`) and
  the SONNET-FIXABLE init-order half (a fresh manifest no longer needs the
  legacy modal opened once before sections populate).
- **Fix:**
  1. `_meBuildGroupMap()` fetches `GET /api/parts-db/browse-tree` once
     (cached module-level) and builds a `part_type_id → {section_key,
     section_label, type_id, type_label, order}` reverse map: a part_type
     groups into its family if it's a family member, else into itself,
     mirroring the picker sidebar exactly. `order` is a counter that walks
     categories/children in the exact order the server returns them, so the
     manifest's section order — and its grouping — auto-follows any future
     sidebar/category restructure (e.g. owner flaws #7/#8) with zero code
     changes here.
  2. `loadDraftManifest` now awaits `_meBuildGroupMap()` before the first
     `_meRender()`, so a freshly opened build editor groups correctly
     immediately — the old code only populated `_meSections` as a side effect
     of `_mePopulateDataLists`, reachable only by opening the legacy flat-modal
     fallback at least once.
  3. Picker-added parts (carry `part_type`) resolve exactly via the reverse
     map. Legacy name-based parts (no `part_type`) get a best-effort match:
     strip a trailing sequence number, lowercase, look up against an index of
     family/part_type labels; a unique match wins, anything unmatched or
     ambiguous (label shared by more than one section) falls to a single
     "Other" section rendered last — deliberately best-effort per FINDING-007,
     not over-engineered.
  4. `_meRender` orders sections by the `order` field (Other always last) and
     renders a muted uppercase `.me-cat-group-head` bar whenever the main
     category changes between consecutive sections, so "sort by main category
     + part-type family" is visible at a glance (e.g. `LIGHTS`, `STRUCTURAL`,
     `EQUIPMENT`, `EXTRAS`) without collapsing/hiding anything.
  5. `addPartInSection` keeps working: the intelligent picker has no
     scoped-open entry point (`part_picker.js` intentionally untouched — out
     of scope), so it still opens the picker unscoped via `addPart()`; for the
     flat-modal fallback it reorders the part-name datalist so the target
     section's catalog entries sort first, using the same best-effort label
     match as legacy grouping. Never leaves the button non-functional.
  6. `_meRebuildSections` and `_meSectionFor` (and the workbook
     `template_sections` grouping dependency) are deleted; `_workbookRules`
     itself is still loaded in `_mePopulateDataLists` since other code
     (manufacturer/part-number/location fallbacks) still reads
     `part_rules` from it.
- **Verification:** `tests/golden` + `tests/contract` unchanged (43/43,
  client-only change, no route/DB touched). `tools/ui_smoke/run_smoke.py` 9/9,
  no flow modified — a repo-wide check confirmed no smoke flow asserts on
  `.me-cat-section`/section labels/"Other" grouping. Manually verified live
  (`DTM_CLOUD=0`): "Granite Falls Police Department" (55 legacy name-based
  parts) — build editor opens straight to grouped sections (`EXTRAS` → Floor
  Mats/Harness/Seat Covers, `STRUCTURAL` → Chicago Barrier/Front
  Partition/Rear Partition/Rear Window Bars, `EQUIPMENT` → Equipment
  Tray/Radio/Siren Speaker/Special Face Plates/Vehicle Data Tags, `Other` →
  legacy light parts like Forward Warning/Mirror Warning/Side Warning/Rear
  Light Bar) with **no** prior legacy-modal open — confirming the init-order
  fix. "Test" project (6 picker-added parts, `part_type` set) — grouped
  exactly right: `STRUCTURAL` → Console System (Console 1), `EQUIPMENT` →
  Siren Speaker, `LIGHTS` → Warning (Forward Warning 1/2, Side Warning 1), and
  one orphaned accessory line (Forward Warning 2 · Universal Grill Bracket, no
  `part_type`) correctly falls to `Other`. No console errors observed.

### FINDING-031: picker sidebar restructured — families-first ordering, selectable light categories, Scene/Spotlight standalone, Light Bars unified (owner flaws #7+#8) — RESOLVED
- **Location:** `resources/config/parts_db.json` (`families` collection + `spotlight`/
  `warning_light`/light-bar part_types), `app/routes/parts_db.py` `_build_browse_tree`,
  `ui/js/part_picker.js` (`_pickerBrowseTreeHtml`/`_pickerWireFilters`), `ui/styles.css`.
- **Category:** design-follows-owner-ruling (new UI affordance, not a bug) · **Severity:**
  N/A (feature) · **Status:** RESOLVED (2026-07-10)
- **Owner flaws #7+#8:** restructure the Lights and Structural sidebars — families/dropdowns
  first (owner-specified order), standalones below; light categories (Warning/Scene/Interior/
  Spotlight) selectable by clicking the header, no forced sub-leaf; Scene collapses to one
  selectable row (no front/side/rear); Spotlight pulled out of Scene as its own standalone;
  Interior + Roof light bars merge into one "Light Bars" family. Implements the owner's
  2026-07-10 rulings captured in memory `project_sidebar_restructure_ruling` — **kept the 5
  category headers** (did not flatten).
- **Data (commit 1, `80a5dfd`):**
  - New family fields (additive, tolerated by `config/schemas.py` `_validate_parts_db`
    unchanged — it only checks required keys): `order` (int, families-first sort),
    `selectable` (bool — header alone filters by `picker_flow`), `browse_collapsed` (bool —
    render as one row, no members, e.g. Scene/Spotlight).
  - Renamed `push_bumper_system` → label "Push Bumper", `console_system` → label "Console".
  - New families: `light_bars` (lights, merges the old `interior_bars`+`roof_bars`, no single
    flow — members carry their own via `category`), `cage_prisoner_containment` (structural,
    8 members), `storage_equipment` (structural: `rear_storage_box`/`equipment_tray`/
    `tonneau_cover` — `equipment_tray` is a cross-type member, `type_id: equipment` surfaced
    under a Structural family, same mechanism FINDING-025 fixed).
  - `spotlight` part_type: `category` "scene" → "spotlight" — its 5 products (all Unity)
    re-resolve from `category=scene` to `category=spotlight` cleanly (verified via
    `category-skus` contract diff: 5 removed from scene, same 5 present under spotlight, none
    orphaned). `_CATEGORY_KEYWORDS`/`_LIGHT_CATEGORIES`(JS)/`_COLOR_CATEGORIES`(JS)/
    `_CATEGORY_PLACEMENT_ZONES` already carried a `spotlight` entry from an earlier session —
    no further wiring needed.
  - **Scene-collapse implemented at the BROWSE level only** (owner's long-pending ruling,
    LEDGER FINDING-001/002): `front_scene`/`rear_scene`/`side_scene` stay in
    `scene_lights.members` and in `part_types` untouched — only hidden from the *rendered*
    tree. This does **not** trigger the FINDING-001/002 placement-migration risk (no part_type
    merge, no data migration).
- **Route (`_build_browse_tree`):** sorts a type's children families-first (`order` then
  label), standalones after (label); emits `order`/`selectable`/`browse_collapsed` per family
  and a per-**member** `picker_flow` (the member's own part_type `category`, falling back to
  the family's) — needed because `light_bars` has no single flow (members split
  `interior_bar`/`roof_bar`).
- **Bug found + fixed by ui_smoke (commit 2, `1e7a8af`):** the initial commit-1 approach
  *removed* `warning_light` from `warning_lights.members` outright (spec said "drop from
  VISIBLE members"). That broke `_pickerOpenEdit`'s browse-tree lookup — with `warning_light`
  absent from both the bare-part-type list (`browse_hidden`) *and* the family's member list,
  editing a warning-light part could no longer resolve its family/flow, so the Step 6
  type-lock silently stopped locking (`edit_preserves_fields` smoke flow caught this). Fix:
  `warning_light` **stays** in `members` (so edit-mode pre-fill/type-lock still resolves it)
  but each member now carries a `browse_hidden` bool (from the part_type's own flag) that only
  the **render** path (`_pickerBrowseTreeHtml`) filters on — `anyFilled`/lock computations use
  the full member list. This is the general mechanism for "member exists in data, invisible in
  the tree" and is reusable for any future browse_hidden family member.
- **JS (`_pickerBrowseTreeHtml`/`_pickerWireFilters`):** a `selectable` family renders a new
  `.pbt-fam-select` button (same data-attributes/handoff as a `.pbt-leaf` — merged into one
  click handler with `.pbt-leaf`) plus, if also expandable, a separate small
  `.pbt-fam-caret-btn` that only toggles member visibility — clicking the label filters,
  clicking the caret expands, independently. `browse_collapsed` families render `.pbt-fam-select`
  alone with no caret and no member body at all. Non-selectable expand-only families (Light
  Bars, all Equipment/Structural system families) keep the original `.pbt-fam-head`
  toggle-only behavior verbatim — zero behavior change there. Server child order is never
  re-sorted client-side.
- **Verification:** `tests/golden` 6/6 unchanged both commits (authoring-side only — name-based
  render path untouched). `tests/contract` — `browse_tree` re-recorded (eyeballed: exactly the
  intended structure/order/labels, see route diff below); `root_doc` re-recorded (mirrors the
  same parts_db.json edits, no unexpected fields); `part_types_all`/`part_types_by_type`
  re-recorded (single-field `spotlight.category` diff only); `category_skus` (type=lights,
  category=scene) re-recorded (5 spotlight products removed, confirmed present under
  category=spotlight, none lost) — all other cases unchanged. Full `pytest` suite: 1709
  passed/1 skipped after each commit. `tools/ui_smoke/run_smoke.py`: 9/9 after commit 2 (2
  genuine failures surfaced along the way and were fixed, not silenced — the type-lock bug
  above in `edit_preserves_fields`, and `brand_preference_collapse`, which targeted the
  now-removed `.pbt-fam-head[data-fam='warning_lights']`/`warning_light` leaf and was repointed
  to the new `.pbt-fam-select[data-flow='warning']` header). Flows touched: `add_text_mode_
  equipment_part` (comment only — `console_system`'s `family_id`/selector are unchanged, only
  its label text changed), `scene_light_qty_only` (Part A repointed to the collapsed
  `.pbt-fam-select[data-flow='scene']` row + asserts zero member leaves; Part B repointed to
  the selectable `.pbt-fam-select[data-flow='warning']` header), `brand_preference_collapse`
  (repointed as above), `edit_preserves_fields` (strengthened the type-lock assertions:
  `warning_light` must render as zero leaves; the part's own family header must not be
  locked), `picker_browse_tree` (added a families-sort-before-standalones assertion under
  Structural). `light_options_in_product_box`/`sku_dropdown_rework` needed no functional
  change (their "first family" `.pbt-fam-head` target already resolved to the same
  color-configured category before and after — comments updated for accuracy only).
  `picker_multi_add`/`picker_browse_tree`'s core assertions (Equipment/Radar/gun_lock) are
  structurally untouched by this session. Visual verification (`DTM_CLOUD=0`, live app):
  screenshotted the Lights sidebar (Warning/Light Bars/Interior Lighting dropdowns with
  carets, Scene/Spotlight as plain standalone rows) and Structural sidebar (Push Bumper/Cage
  /Console/Storage families, Running Boards/Nerf Bars standalone last); clicked Warning →
  header goes active, 61 products load filtered to `category=warning`, no navigation; clicked
  Scene → active, 15 products filtered to `category=scene`, zero member leaves rendered
  anywhere in the DOM; clicked the Warning caret independently → expands to show only
  Headlight Flasher/Tail Light Flasher (confirms `warning_light` is invisible as intended,
  with the header itself its only home).

### FINDING-032: wrong bracket offered for siren speakers (owner flaw #6, brackets) — RESOLVED
- **Location:** `resources/config/parts_db.json` — `stalker_vehicle_specific_bracket.fits_part_types`.
- **Category:** data mis-homing (product homed to an accessory part_type it doesn't belong to) ·
  **Severity:** MEDIUM · **Status:** RESOLVED (2026-07-10)
- **Owner flaw #6 (brackets part):** the siren-speaker accessory dropdown offered a Stalker
  RADAR-antenna bracket (`stalker_vehicle_specific_bracket`, model "VEHICLE SPECIFIC BRACKET")
  that has nothing to do with siren speakers.
- **Root cause:** the product's `fits_part_types` listed `siren_speaker_bracket` alongside its
  two legitimate radar-mount homes (`front_radar_antenna_mount`, `rear_radar_antenna_mount`).
  `siren_speaker_bracket` is an accessory part_type of `siren_speaker`, so the accessories
  endpoint surfaced this radar bracket in the siren speaker's bracket dropdown.
- **Fix:** removed only `siren_speaker_bracket` from `stalker_vehicle_specific_bracket.
  fits_part_types`; its two radar-antenna-mount homes are untouched. The correct Whelen siren
  brackets (SAK1, SAK9, SA-315 mount kit, SA-350M mount kit) were already offered and remain so
  — confirmed via a direct `fits_part_types` check on `whelen_sak1`/`whelen_sak9`/
  `whelen_sa315_mount_kit`/`whelen_sa350m_mount_kit`/`5_0_fab_dtm_dtmsak`.
- **Verification:** `tests/golden` 6/6 unchanged (name-based render path is inert to
  accessory-homing changes). `tests/contract` — `root_doc` and `products_all` re-recorded;
  diffed against the prior snapshots and confirmed the *only* change in each is the removal of
  the `"siren_speaker_bracket"` line from this one product's embedded `fits_part_types` array —
  re-run green after recording. `tools/ui_smoke/run_smoke.py`: 9/9, no flow touched.
- **Not in scope (separately flagged, other flaw-6 parts):** siren speaker render size uses a
  loose-substring match in `asset_resolver.size_class_for_part` (separate bug); the
  qty-driven PB-center-plate placement/dots feature for siren speakers (separate feature work).
  Neither is addressed by this change.

### FINDING-033: siren speakers rendered oversized — "3"→rd substring rule caught SA315P etc. (owner flaw #6, size) — SUPERSEDED (cosmetic)
- **Location:** `planning/asset_resolver.py::size_class_for_part` +
  `resources/config/asset_manifest.json` `part_number_size_rules`.
- **Category:** substring-match collision (loose fallback rule caught digits inside an
  unrelated SKU) · **Severity:** MEDIUM (visibly oversized/distorted render, no data loss) ·
  **Status:** RESOLVED (2026-07-13)
- **Owner flaw #6 (size part):** siren speakers rendered "extra large" and distorted.
- **Root cause:** `size_class_for_part` first checks for an exact SKU match, then falls back to
  a substring loop over `part_number_size_rules`. That table has `"3": "rd"` (meant to size
  3-inch round lights), and Python dict iteration hits it before any siren-specific key would.
  None of the 5 Whelen SA-series siren SKUs (`SA315P`, `SA315U`, `SA350MH`, `SP123BMC`,
  `295SLSA6`) had an exact-match entry, so each one's embedded digit(s) matched the `"3"` rule
  and got sized as a 0.2×0.2 `rd` square instead of the correct wide-short siren box. The other
  siren brands (Feniex/Federal) have no digit collision and already defaulted correctly to `sm`.
- **Fix:** added 5 explicit exact-match `"sm"` entries to `part_number_size_rules` for the
  affected SKUs, so the exact-match check (which runs before the substring loop) wins. Restores
  the pre-regression/legacy siren size and matches what every other siren brand already gets.
  Substring-matching logic itself untouched (too broad a fix, would move unrelated goldens).
- **Verification:** resolver-level check — all 5 SKUs now return `"sm"`; unrelated part numbers
  (`ION`, a literal `"3"`, and a synthetic 3-inch-round SKU containing `"3"`) unchanged. Full
  `pytest` suite: 1709 passed, 1 skipped. `tests/contract`: 37/37 unchanged (asset_manifest is
  not part of the parts_db contract). `tools/ui_smoke/run_smoke.py`: 9/9.
- **Golden masters — intentionally re-recorded (§3.2 opt-in behavior-change path, not silent
  drift):** `tests/golden` failed on the 6 fixtures containing siren speakers, all with the
  identical, expected diff — `size_class: "rd"` → `"sm"` on `siren_speaker` placements, nothing
  else. Every golden SKU exercised is `SA315P` at the `front` view, which already carries a
  pre-existing per-model `size_per_view` override in `parts_library.json`
  (`w:0.53, h:0.65`) that takes precedence over `size_class` at render time — so the rendered
  `.pptx` digest is byte-identical in all 6 cases; only the plan JSON's `size_class` metadata
  field moved. Confirmed no other shapes, text, or positions changed before re-recording with
  `pytest tests/golden --golden-record`; re-run green (6/6). This means `SA315U`/`SA350MH`/
  `SP123BMC`/`295SLSA6` and any siren SKU rendered at a view without a `size_per_view` override
  are not exercised by the current golden corpus, but the resolver-level check above confirms
  the fix applies uniformly to all 5 SKUs.
- **SUPERSEDED / corrected (2026-07-13):** this fix is **cosmetic** — it changes only the plan
  JSON's `size_class` metadata, which is **dead code for `render_kind == "equipment"`**.
  `ppt_helpers.get_icon_size()`'s equipment branch never consults `size_class`; siren size comes
  from `EQUIP_SIZES[name]` (no siren entry) → `size_per_view` override → raw-PNG aspect. So the
  visible "extra large" was NOT the `rd` rule — it is the `size_per_view`/fallback path. The real
  fix is FINDING-035. The `asset_manifest.json` `sm` rules added here are harmless but misplaced
  legacy-file data (owner directive: size belongs in parts_db); candidate to unwind when F-035 lands.

### FINDING-034: siren→lighting brand pref + console_brand preference added (owner follow-up) — RESOLVED
- **Location:** `ui/js/part_picker.js::_pickerPreferredBrand`, `domain/project_models.py`
  `EquipmentPreferences`, `domain/project_codec.py::preferences_from_dict`,
  `ui/js/projects/{detail_edit,detail_overview,wizard}.js`, `ui/index.html` (wizard preferences
  step), `app/services/project_service.py` (`pref_notes` builders, both draft-creation paths).
- **Category:** brand-preference scope extension (mirrors flaw #5's machinery, commit
  `7ace723`) · **Severity:** LOW (usability — extra manual brand picks) · **Status:** RESOLVED
  (2026-07-13)
- **Owner follow-up (two requests):**
  (A) "the siren speakers should still be filtered by agency preference, so if whelen is
  selected [lighting brand], they get whelen speaker options" — siren speakers were not wired
  into any brand-preference scope at all, so the picker never auto-selected/collapsed by brand
  for `siren_speaker`, even though sirens are functionally a Whelen-family lighting accessory.
  (B) "we need to add center console manufacturer as an agency preference to be selected along
  with the other agency preferences" — no `console_brand` preference existed; console SKUs had
  no preferred-brand collapse in the picker at all.
- **Fix (A):** added `_PREF_LIGHTING_EXTRA_PART_TYPES = new Set(["siren_speaker"])` in
  `part_picker.js`; `_pickerPreferredBrand(f)` now resolves `siren_speaker` through the same
  `preferences.lighting_brands?.[0]` branch as `type_id === "lights"`. No new preference field
  needed — sirens ride the existing lighting-brand preference.
- **Fix (B):** added `console_brand: str = ""` to `EquipmentPreferences` (after `cage_brand`,
  mirroring its text+datalist shape); wired through `preferences_from_dict` (serialization is
  generic `dataclasses.asdict`, so no `_to_dict` change was needed — there is no such function,
  contrary to the initial ask's assumption). Added the field to: the Edit tab's read-only
  summary and edit-mode form (`detail_edit.js`, new `#et-console-brand` input + `#et-console-list`
  datalist), the Overview tab summary (`detail_overview.js`), the new-project wizard's
  Preferences step (new `#proj-console-brand` field in `ui/index.html` + load/save wiring in
  `wizard.js` — the wizard *does* render brand fields, so it was included, not skipped), the
  `pref_notes` builders in `project_service.py` (both `handle_create_group_draft` and
  `handle_create_individual_draft`), and a new `_PREF_CONSOLE_PART_TYPES = new Set(["console"])`
  scope in `part_picker.js` (`motion_attachment` deliberately excluded per instruction).
- **Datalist source:** `project_options.json` (the config-driven source for
  `bumper_brands`/`cage_brands`) has no `console_brands` key, and its schema validator in
  `config/schemas.py` enumerates a fixed field list — extending it would touch config-schema
  code and a second contract-adjacent surface outside this change's scope. Used a static
  fallback list (`Gamber Johnson`, `Havis`, `Tiger Tough`, the DB's known console
  manufacturers) in both `detail_edit.js` and `wizard.js`, structured so it still prefers
  `_PT.projectOptions.console_brands` if that key is ever added later.
- **Skipped (documented, not silently dropped):** `parts_db.json`'s `preference_filters` block
  already has `lighting_brand`/`bumper_brand`/`cage_brand`/`camera_brand` entries that are an
  unread documentation-only island (the picker hardcodes its own scopes client-side — see the
  comment at `part_picker.js` line ~62). Adding a `console_brand` entry there was explicitly
  optional per the task and would have moved `tests/contract/expected/parts_db/root_doc.json`
  (confirmed by grep — that file snapshots `preference_filters` verbatim), so it was left alone
  to keep this commit contract-clean.
- **Verification:** `pytest tests/golden tests/contract` — 43/43 unchanged. Full suite — 1709
  passed, 1 skipped (unchanged from before this change). `tests/test_project_codec.py` extended
  (`TestPreferencesFromDict.test_all_fields`) to assert `cage_brand`/`console_brand` round-trip.
  `tools/ui_smoke/run_smoke.py` — 9/9. Visual, local mode (`DTM_CLOUD=0`): set Console Brand to
  "Gamber Johnson" on a test project's Edit tab, saved, confirmed it appears on both Edit
  (read-only) and Overview tabs. Opened the picker on a Console part type — brand pill showed
  "Gamber Johnson PREFERRED", product list restricted to Gamber Johnson SKUs. Opened the picker
  on Siren Speaker with lighting pref = Whelen — brand pill showed "Whelen PREFERRED", product
  list showed Whelen siren SKUs including `SA315P Speaker` and `SA315U Speaker` with other
  brands collapsed into the "Other brands…" dropdown, matching the existing lights/bumper/cage/
  camera UX exactly.

### FINDING-035: siren render size must move into parts_db at the part-type level (owner flaw #6, size — the real fix) — NEEDS-DESIGN
- **Supersedes the cosmetic FINDING-033.** Owner directive (2026-07-13): size + image data
  belongs in the **parts_db, at the part-type level** (with per-part override), NOT in the legacy
  `parts_library.json` / `part_catalog.json` / `asset_manifest.json`, and NOT sprayed per-SKU.
- **Mechanism (confirmed):** siren speakers are `render_kind == "equipment"`.
  `ppt_helpers.get_icon_size()`'s equipment branch = `EQUIP_SIZES[part.name]` (hardcoded; no siren
  entry) → `size_per_view` override → else raw-PNG aspect scaled to a 1.0" box. The siren asset
  (`siren_speaker_wo_bracket_front.png`) is portrait 1920×2194, so the fallback balloons it. The
  **assigned** dimension (legacy Part-Type manager "Render size (inches)" = `size_per_view` =
  front **0.59×0.65**) is honored only when the part matches an exact legacy NAME
  ("Siren Speaker 1/2", from `part_catalog.json`) or the one library MODEL `SA315P`
  (`parts_library.json`). Every other siren SKU / non-"1/2" name (all picker-built sirens once
  qty-naming lands, any 3rd+ siren) matches neither → balloons. This is precisely the owner's
  "the size rules should have been transferred over" gap.
- **Category:** workbook-shape (render size lives in legacy name/SKU-keyed stores, not parts_db) ·
  **Severity:** MEDIUM (visible on every new siren build) · **Status:** NEEDS-DESIGN
- **Rejected approach (do NOT repeat):** writing `size_per_view` onto every siren SKU in the
  legacy `parts_library.json`/`part_catalog.json`. An interrupted subagent partially applied it;
  reverted to `stash@{0}` ("REJECTED siren-size SKU-level hack"). It is SKU-level, in the wrong
  data store, and duplicative.
- **Design to do:** (1) a `size_per_view` (+ image) field on parts_db `part_types` (and an
  optional per-`product`/per-`part_number` override); (2) the render pipeline (`planner` →
  `get_icon_size`/`resolve_asset_path`) reads size/images from parts_db for picker-shaped parts,
  keeping the legacy name/model path only for legacy name-based drafts; (3) an editing surface —
  either revive the legacy size/image UI (`ui/js/settings/{part_types,parts_library,size_rules}.js`)
  pointed at parts_db, or build it into the new Part Manager. Ties into the Phase-4 pipeline
  inversion and `docs/audit/PARTS_DB_REPOSITORY_SPEC.md` (size/images are more parts_db data the
  repository should own). Scope with the owner before building.
- **Related still-open siren work (this session, not started):** qty(1/2) selector + Top/Under
  Push-Bumper mirrored-slot render (qty=1 CENTERED, qty=2 both) + dot count; bracket-nesting fix
  (accessory child lands in "Other" — group children into the parent's section in
  `manifest_editor.js`); qty=2 → two brackets. See `docs/audit/SESSION_HANDOFF_2026-07-13.md` §B/§C.

## Session 2026-07-14 — Codex continuation

### FINDING-026 update: empty visible browse leaves curated — RESOLVED
- **Status:** RESOLVED (2026-07-14).
- Owner rulings were applied in `parts_db.json`: front camera is hidden/inferred; camera DVR keeps
  selectable tray-vs-passenger-seat location options; rear camera and prisoner camera are visible
  unbilled shop-facing details; body cam dock and wireless mic charger live with the camera system;
  radio cables are consolidated into one visible `Radio Cables` leaf; radio speaker is an unbilled
  mount-location detail; radio antenna cable, door-lock button, and K-9 control head are hidden.
- Cloud tray, cloud antenna, and CradlePoint are now grouped under a dedicated
  `cloud_cradlepoint` family. A fresh visible-leaf sweep after curation returned zero empty leaves.

### FINDING-035 update: siren render/qty/bracket behavior implemented — RESOLVED
- **Status:** RESOLVED (2026-07-14) for the owner-visible picker/render behavior.
- Implemented part-type render metadata in `parts_db.json` and hydrated it through the
  parts_db domain/service/schema path. The planner now consumes parts_db render image/size data
  for picker-built siren speakers instead of falling through to raw image size or legacy
  name/model-only size rules.
- Implemented siren quantity 1/2 behavior, curated siren placement options, per-speaker bracket
  selection, vertical bracket stacking for dual speakers, and image aspect-ratio preservation.
- Final owner tuning removed the temporary 70% scale once the blocker was found; the selected
  image's natural aspect ratio is preserved with height held stable and width adjusted.

### FINDING-036: vague product display names in parts_db picker — OPEN
- **Location:** `src/dtm_buildsheet/resources/config/parts_db.json` product `model` values and the
  picker product-card display that exposes those names.
- **Category:** data-curation / picker UX · **Severity:** MEDIUM (salesperson cannot identify some
  selectable products) · **Status:** OPEN.
- **Owner complaint:** products are showing up as non-descript names such as `WINDOW MOUNT`,
  `ROOF MOUNT`, `W/BRACKET`, `CLIP`, `ALL IN ONE UNIT`, and `VEHICLE SPECIFIC BRACKET`.
- **Audit:** `docs/audit/VAGUE_PRODUCT_NAME_AUDIT_2026-07-14.md` flags 81 products out of 784.
  Highest-priority exact/generic rows include `cradle_point_roof_mount`,
  `cradle_point_window_mount`, `magnetic_mic_mmsu_1`, `magnetic_mic_mmsu_1b`,
  `motorola_all_in_one_unit`, `motorola_split_unit`, `stalker_dual_swivel_bracket`,
  `stalker_high_a_bracket`, `stalker_low_a_bracket`, `stalker_vehicle_specific_bracket`,
  `watchguard_trab58003_wg1`, and `havis_vehicle_specific`.
- **Fix direction:** every selectable product row needs a sales-readable product name containing
  enough object/system context to identify it. Prefer curated `parts_db.json` display/model text
  copied from known QB friendly-name detail where available. If the product is only a shop detail
  or agency-supplied placeholder, mark it unbilled or browse-hidden consistently. If it is not a
  real selectable item, remove it from browse. Add a data-quality guard for exact generic model
  names after the first curation pass.

### FINDING-036 update: high-priority exact-generic picker names curated — PARTIAL
- **Status:** high-priority slice complete; secondary cleanup remains open. Curated sales-readable
  `model` values for the exact generic selectable rows in the audit: CradlePoint roof/window mounts,
  Magnetic Mic MMSU-1/MMSU-1B, Motorola all-in-one/split radio heads, Stalker radar antenna brackets,
  and WatchGuard TRAB58003-WG1 antenna.
- **Hidden instead of renamed:** `havis_vehicle_specific` had no exact console series or vehicle
  application data, so its `fits_part_types` were cleared and its description now marks it as a
  placeholder hidden from the picker until curated.
- **Guard:** `tests/contract/test_parts_db_data_quality.py` now fails when exact generic model names
  (`CLIP`, `W/BRACKET`, `WINDOW MOUNT`, `ROOF MOUNT`, `ALL IN ONE UNIT`, `SPLIT UNIT`, `ANTENNA`,
  `VEHICLE SPECIFIC`, `VEHICLE SPECIFIC BRACKET`) remain attached to selectable products.

### FINDING-036 update: location-title products and obvious vehicle tags curated — PARTIAL
- **Status:** second cleanup slice complete; broad secondary naming review remains open.
- Renamed Kussmaul `WATER PROOF` / `NON-WATER PROOF` to sales-readable Auto Eject products.
- Collapsed location-only picker rows: CradlePoint roof/window variants, carrier roof/window cloud
  system variants, and Globesat `FRONT RIGHT OF DASH` / `ROOF MOUNTED`. One real product remains
  selectable per choice, and the mount wording moved to the relevant part-type `location_options`.
- Added obvious `vehicle_tags` where SKU text clearly names a supported vehicle family, including
  existing partial-tag rows where the text named additional vehicles.
- Extended `tests/contract/test_parts_db_data_quality.py` to guard those exact location-only titles
  and to fail when explicit vehicle-fit text lacks the matching vehicle tag.

### FINDING-036 update: secondary bracket/mount and model-code titles curated — PARTIAL
- **Status:** secondary audit slice complete. Renamed the listed bracket/mount rows to include
  product/system context, including 5-0 Fab warning brackets, Santa Cruz gun-lock brackets, Setina
  gun-lock/cargo brackets, Stalker radar cable/display mount, Havis/Gamber radio/console details,
  and Whelen/Feniex mount kits.
- Reviewed the short model-code rows and renamed the ambiguous picker-facing ones with object
  context, e.g. Setina PB-series guard/wrap rows, Whelen WeCanX control heads and expansion modules,
  Whelen ION/VXE/L31/L32 lights, Whelen SAK siren-speaker brackets, Stalker DSR, WatchGuard M500,
  Pro-Gard HDX, SoundOff M4, and Setina Polycarbonate Window Barrier.
- Extended the exact-title data-quality guard to block the old secondary/model-code labels from
  returning as selectable product names.

## Session 2026-07-15 — docs + post-radio audit

### FINDING-037: radio cargo-window antenna choices are not guaranteed renderable — OPEN
- **Location:** `src/dtm_buildsheet/ui/js/part_picker.js` radio workflow,
  `src/dtm_buildsheet/resources/config/parts_db.json` `radio_antenna_top.location_options`,
  `src/dtm_buildsheet/resources/config/vehicle_layouts.json`.
- **Category:** picker/render data contract · **Severity:** HIGH · **Status:** OPEN.
- The radio workflow offers `LEFT CARGO WINDOW` and `RIGHT CARGO WINDOW`, but the layout file
  currently has `UPPER CARGO WINDOW` / `LOWER CARGO WINDOW` coordinates and no exact left/right
  cargo-window keys. The synthesized planner path resolves views by exact location key, so these
  choices can add a friendly draft row without drawing where the salesperson expects.
- **Fix direction:** decide whether left/right cargo-window antenna choices should be new layout
  coordinates, aliases to existing upper/lower cargo-window points, or text-only shop details. If
  they should render, add/migrate exact coordinates or a resolver alias and test the preview/PPT.

### FINDING-038: plan/render warnings remain hidden in the build editor — OPEN
- **Location:** existing FINDING-006 area; planner/preview warnings reach service payloads but are
  not surfaced in the manifest/preview editing flow.
- **Category:** UX/debuggability · **Severity:** MEDIUM-HIGH · **Status:** OPEN.
- The current picker makes more synthesized parts and text-location choices, so hidden warnings now
  directly affect user expectation. A row can be added successfully while failing to render, with
  the reason only visible in generated-warning data or tests.
- **Fix direction:** surface `plan.warnings`, planned-part warnings, placement warnings, and
  instance warnings in the build editor near the preview/manifest, with enough context to identify
  the part and location.

### FINDING-039: radio speaker is presented as location-only but still depends on hidden product data — OPEN
- **Location:** `src/dtm_buildsheet/ui/js/part_picker.js` `_pickerLoadRadioWorkflow` /
  `_pickerAddRadio`, and `parts_db.json` `radio_speaker` product rows.
- **Category:** picker workflow robustness · **Severity:** MEDIUM · **Status:** OPEN.
- Owner expectation is that a radio speaker is assumed and the user only chooses where it goes.
  The implemented workflow still loads a hidden/default `radio_speaker` product/SKU and requires it
  to satisfy the flow. If that hidden shop-detail row is later removed or filtered unexpectedly,
  the radio workflow can become impossible to complete with no visible product decision to fix.
- **Fix direction:** make radio speaker a true synthetic workflow row, or add a guard/test ensuring
  exactly one stable unbilled default speaker row is always available to the workflow.

### FINDING-040: radio workflow test coverage is mostly data/API, not UX contract — OPEN
- **Location:** `tools/ui_smoke/flows.py`, `tests/test_parts_db_routes.py`.
- **Category:** regression coverage · **Severity:** LOW-MEDIUM · **Status:** OPEN.
- Current tests cover the constrained radio data and a smoke add path, but they do not assert the
  exact owner-facing UX rules: custom speaker text persists, all-in-one hides the brick row, head
  never offers tray placement, and the radio flow stays in the main SKU/product pane.
- **Fix direction:** add one focused UI smoke assertion set or lightweight JS/route-backed test for
  those rules after the next radio workflow code change.
