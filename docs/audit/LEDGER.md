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
