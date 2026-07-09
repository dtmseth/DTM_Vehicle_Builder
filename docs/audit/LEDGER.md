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

### FINDING-005: picker Edit mode destroys the edited part (name→"Part", SKU/model clobber, quantity→1, colors wiped)
- **Location:** `ui/js/part_picker.js:99-119` (`_pickerOpenEdit` hard-codes
  `type_id="lights"`, no category) + `part_picker.js:1370-1460` (`_pickerDoAdd`
  edit path)
- **Category:** fragile
- **Severity:** HIGH — data-destroying on a routine action
- **Status:** CONFIRMED
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
- **Disposition:** NEEDS-DESIGN — the edit flow needs a real contract (prefill
  type/category/config from the stored part; preserve name/qty/colors unless
  deliberately changed). A minimal SONNET-FIXABLE stopgap: in edit mode carry
  `editPart.name/quantity/raw_color` through `_pickerDoAdd` unless the user
  changed the corresponding control, and disable Save until something changed.

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
