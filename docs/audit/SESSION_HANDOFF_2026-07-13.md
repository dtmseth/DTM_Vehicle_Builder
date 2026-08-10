# Session Handoff — Picker flaw-fix pass (2026-07-13/14)

## 2026-08-10 v3.0.0 public-release checkpoint — CURRENT

The historical entries below explain how the picker was rebuilt. This section supersedes their
"next" instructions.

### Released baseline

- **v3.0.0 is published** at
  [the public GitHub release](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/tag/v3.0.0).
  It is a stable Mac + Windows release from `main` commit
  `4e271b4636ee33fdc844ec8241103971aacc470f`.
- The two targeted legacy projects were rebuilt through the new Part Picker. The release also
  includes the project/build UI and PowerPoint-manifest overhaul, per-part comments, project-wide
  notes, visual part editing, and the finalized preview placement/render fixes.
- Public QuickBooks controls are deliberately hidden. The catalog and estimate foundation remains,
  but production QuickBooks is a separately approved effort.
- The installer-discovered SharePoint startup issue is fixed: startup/periodic sync loads projects
  first; a build draft is downloaded only when that build is opened. A locally newer draft is not
  replaced, and Graph failures are sanitized before reaching logs or the UI.

### Release evidence and current watch

- Verification before publish: full cloud-off suite **1,928 passed, 1 skipped**; UI smoke
  **15/15**; contract, golden, packaging, and hosted post-merge checks passed.
- Corrected installers are now being received by devices with the previous version. The owner has
  confirmed the corrected app works; finish the ordinary over-install check (version 3.0.0,
  projects visible, and one build opens) before closing out rollout monitoring.
- Keep normal development cloud-off (`DTM_CLOUD=0`). Do not restore full historical-draft hydration
  at app startup; see `docs/GOTCHAS.md`.

### Recommended next work

1. **Do not connect production QuickBooks yet.** First build an isolated, read-only production
   catalog preview and exact-SKU mapping report. The production company has a different inventory
   layout, so no routine reconciliation or background polling may start before owner review.
   `docs/QUICKBOOKS.md` §§6–7 are the governing checklist.
2. Once that safety plan is either underway or intentionally parked, choose the next parts-data
   investment: scope Kit SKUs (the next explicit picker feature) and continue sales-readable
   catalog curation. The larger parts-db repository/legacy-consumer migration is valuable but not
   an urgent release follow-up.
3. Use any real user reports from v3.0.0 to prioritize small picker/render fixes; do not reopen
   historic flaw items solely because this handoff mentions them.

## 2026-08-06 continuation update

This continuation preserved the already-dirty tree, did not stage/commit/reset anything, and ran
all Python verification cloud-off (`DTM_CLOUD=0`). The owner explicitly asked to avoid the slow,
screen-capture-dependent test loop, so no UI smoke or screenshot pass was run.

### Completed in this continuation

- **Outer Edge rear pillars:** the selected housing is a `warning_light` semantically but auto-names
  and groups as **Rear Warning** at `PILLARS`. Duo construction creates six included IONs (three
  Red/secondary and three Blue/secondary); Trio creates six Red/Blue/Amber IONs. The included heads
  persist as nested quote lines, and preview/PPT render two centered three-head pillar stacks with
  mirrored ±55° rotations. The draft conversion now preserves picker `part_type` and
  `picker_config`, preventing saved previews from losing that assembly directive.
- **Radio SKU identity:** Radio Communications now presents actual radio-unit SKU cards and opens
  the guided setup immediately after selection. The selected SKU is saved with the system identity;
  it determines the all-in-one versus split layout, so the details guide no longer asks that
  question a second time. Only split systems request a radio-brick location.
- **Shared radio/console mic clip:** both setup orders now reconcile the physical microphone mount.
  A radio configured after a console clip asks whether it uses that clip or needs another; a console
  configured after a radio asks the inverse. Reusing the console clip keeps its C-MCB/Mag Mic line,
  rewrites the radio's display-only microphone component to reference the console, and removes only
  the radio-owned Magnetic Mic child while retaining cable-refresh children. The console replacement
  route performs that reconciliation in the same persisted draft write and rejects a reconciliation
  payload that lacks a console mic-clip row. PA-mic behavior is unchanged.
- **Guided system entry:** Radio, Radar, and Camera family entries no longer expand into their
  individual internal component leaves. Selecting the family starts guided setup; each setup offers
  **Choose SKUs manually** as an explicit escape hatch to the full family catalog. Radar's guided
  selector now shows only `radar_display_unit` products, excluding antenna mounts, brackets, and
  cables.

### Verification completed

- Earlier in this continuation: 258 focused picker/planner/render tests; 242 contract/config/schema/
  render tests; then 76 planner/preview tests after the final ±55° pillar tuning. A cloud-off direct
  Outer Edge PowerPoint generation also succeeded.
- Final guided-system/mic-clip pass: `node --check src/dtm_buildsheet/ui/js/part_picker.js` and
  `DTM_CLOUD=0 .venv/bin/python -m pytest tests/test_draft_parts.py tests/test_parts_db_routes.py -q`
  — **133 passed**. The draft regression verifies radio-first console reconciliation removes the
  old Magnetic Mic but preserves a radio cable-refresh child; a validation regression rejects a
  shared-clip request without an actual console mic clip.
- `git diff --check` passed. No contract snapshots were changed for these client/draft-route changes.

### Next safe continuation

1. Owner acceptance can use the normal app without screenshots: start each guided family from its
   top-level entry, confirm only platform choices appear, and use **Choose SKUs manually** only for
   a standalone component.
2. Keep the UI smoke suite unrun unless the owner authorizes it. Existing worktree changes outside
   the files named above remain unrelated and must be preserved.

## 2026-08-05 continuation update

This is an in-progress owner-led picker find-and-fix pass. The working tree was already dirty
before this slice; do not reset, checkout, stage, or overwrite unrelated changes. Run cloud-off
(`DTM_CLOUD=0`) because cloud sync can replace `parts_db.json`.

### Completed in this slice

- **Product-driven light picker context:** `products.<id>.picker_primary_part_type` now declares a
  product's semantic picker type independent of the browse leaf. T-Series and Mega T-Series declare
  `warning_light`, so choosing either from **Lights** now opens the same warning-light picker as the
  Warning leaf. The old `global_search_part_type` is accepted only as an input compatibility alias.
- **Scene-light locations:** category placement resolution now trusts a part type's declared
  `tree_positions` before presentation-label keyword fallbacks. `CENTER PLATE OF PB` is now a
  shared Front Scene option (alongside `TOP OF PUSH BUMPER`) for all scene-light products that
  fit Front Scene; Pioneer SlimLine retains its Rear Scene `UNDER TAILGATE` option. A scene
  selection's quantity now drives both picker dots and rendered heads: one stays centered at the
  location and two or more use the location's authored pattern (or a horizontal row from a
  single-dot anchor).
- **Custom locations:** after a user names the custom shop location, its vehicle placement step now
  optionally exposes every exterior view and all ordinary placement + fixture dots. A named custom
  location may be saved without a render spot; it remains a manifest/shop reference and deliberately
  has no diagram placement. **Set your own** hides the dots and enables add/remove free points
  directly on the vehicle image, including multiple points across views. Saved picker config uses
  `custom_location.placements`; the planner renders each point as a `CUSTOM:<VIEW>:<n>` placement.
  Classic custom locations using `render_location` still work.
- **Tracers:** the tracer card has Clear/Smoked lens pills; resolution and add now use that tracer
  choice rather than the unrelated general picker lens filter.
- **CCTL5 control head:** CCTL5 declares that it has no PA microphone, so it skips the PA-mic
  setup and child-line workflow. It retains **In Center Console** and explicitly allows a Custom
  shop-reference location alongside it. A single control head is named **Control Head**; two or
  more renumber as **Control Head 1**, **Control Head 2**, etc., and return to the bare name when
  only one remains.
- **Console preference:** the selectable **Console** family header now honors
  `preferences.console_brand` just like its Console leaf. A Havis preference therefore starts
  either entry point filtered to Havis; the separate Motion Attachment leaf remains unfiltered.
- **Havis console setup:** selecting **Mounted to pedestal** for a motion attachment now reveals
  a required, vehicle-compatible Havis pedestal/mount-base picker. Its selected `pedestal_mount`
  and the optional Havis C-MCB radio mic clip bracket are persisted with the console setup as
  nested console build lines. The setup action is product-driven: selecting any
  main-console SKU (from a family header, broad category, search, or subleaf) skips placement and
  goes directly to the console setup. Choosing the clip now asks whether to add the live-QB
  Magnetic Mic `MMSU-1`; it defaults to Yes but can be explicitly declined. A printer armrest
  now similarly prompts for a printer (default Yes), requires that selection when accepted, and
  offers its real linked power/USB cable SKUs nested beneath that separate printer parent. Havis faceplate
  choices now require exact Havis, live-QB SKUs, excluding generic migration placeholders and
  legacy non-Havis contextual faceplates.
- **Pending-QB secondary control-head harness:** Whelen `CCTLHARN` is selectable under a dedicated
  **Secondary Control Head Harness** leaf in Light Control System. It carries the Whelen catalog
  description, the $10 catalog price, and `qb_pending: true`, so it can be selected now and will
  reconcile automatically once QuickBooks contains the SKU. Adding a second control head also
  preselects it as an optional, contextual recommendation; the user can choose **None needed**.
- **Light size rules:** the settings page uses named profiles plus searchable part-type, product,
  and SKU assignments backed by `parts_db.json`; free-text and substring size rules are retired.
  Sizing resolves SKU → product → part type → Small default, with `model_aliases` only for exact
  legacy product identity translation. Exact per-target dimensions are editable for render metadata,
  locked profile aspect ratios stay synchronized, and manifest profile saves now reload in the
  running preview/PPT process without an app restart.

### Verification completed

- `node --check src/dtm_buildsheet/ui/js/part_picker.js`
- `DTM_CLOUD=0 .venv/bin/python -m pytest tests/test_parts_db_routes.py tests/test_planner.py tests/test_preview.py tests/test_config_loads.py tests/test_size_rules.py -q` — 203 passed
- `DTM_CLOUD=0 .venv/bin/python -m pytest tests/test_parts_db_schema_validation.py tests/test_parts_db_service.py -q` — 51 passed
- `DTM_CLOUD=0 .venv/bin/python -m pytest tests/contract/test_parts_db_contract.py -q` — 44 passed
- `git diff --check`

Focused size-rule verification also passed: `node --check` for the redesigned settings script and
cloud-off route/planner/config coverage, including 205 tests across the size-rule, planner,
config-load, parts-db-route, and parts-db-service suites. No UI smoke was run.

The complete contract set was intentionally re-recorded against the current dirty parts DB; the
Front Scene type snapshots now include the shared center-plate placement. The broad refresh also
captures the pre-existing size-rule and QB-metadata normalization work. No interactive UI smoke was
run in this slice.

### Next safe continuation

1. With a restarted cloud-off app, visually test: add T-Series from **Lights** (expect standard
   warning colors), Pioneer SlimLine (expect CENTER PLATE OF PB or TOP OF PUSH BUMPER), and a custom light with free front
   + side points (expect gold custom dots and rendered placement in both views).
2. Continue the owner's broader picker defect list only after preserving this dirty tree. Read
   `docs/GOTCHAS.md`, this handoff, and `docs/audit/LEDGER.md` first.

## 2026-07-15 current state update

This is the active handoff. The older 2026-07-13/14 sections below are historical context; several
items listed there as open are now complete or superseded.

Current shipped state in the working tree:

- **Siren render/quantity/bracket behavior is complete** for the owner-visible picker and preview
  flow. Siren speaker image/size rules now hydrate from `parts_db.json` at the part-type level.
- **Manifest grouping is complete for the app view.** Grouping data lives in `parts_db.json` and is
  exposed through `/api/parts-db/manifest-groups`. PDF/export grouping is still deferred.
- **Picker browse and search have moved past the old "Chunks 1-7 only" state.** Category and family
  headers are selectable filters, empty visible browse leaves were curated to zero, and search now
  defaults to all categories/brands/vehicle tags with a "Current filters only" option.
- **Vague product-name cleanup has had three curation slices.** Exact-generic names, location-only
  names such as waterproof/roof/window mount, obvious missing vehicle tags, secondary bracket/mount
  names, and ambiguous model-code names have been cleaned up with data-quality guards. The broad
  naming audit remains a useful historical seed, not the only current queue.
- **Push bumper fixture behavior is implemented.** Fixtures auto-locate instead of asking for a
  manual placement. Setina PB450L lighted bumpers inject render-only included lights for 2/4/6-light
  variants and group them with the bumper in preview. Westin bumper options add wire-cover/light
  channel accessory rows; the later "choose billed lights for the channel" workflow still needs a
  fuller product decision.
- **Radio Communications has a guided system flow** in the main SKU/product area under
  `Equipment > Radio Communications`. It adds the normal radio part_types together, limits the radio
  brick to equipment tray/front of partition, keeps the radio head out of the tray, assumes a speaker
  and asks only for its location, simplifies antenna styles, and uses short Mag Mic labels.
- **Current verification state:** `tests/contract` passes 45 tests; route/service focused tests pass
  74 tests; `.venv/bin/python tools/ui_smoke/run_smoke.py` passes 10/10. The combined
  `pytest tests/golden tests/contract` command is not currently green because 5 golden digests drift
  from the in-progress data/UI changes; do not call the old pins green until those are reviewed.

Current audit follow-up:

- See `docs/audit/PICKER_POST_RADIO_AUDIT_2026-07-15.md` for the deep-dive findings after the radio
  workflow/user-expectation pass. The highest-risk issue found is that some radio location choices
  are friendly text values without matching render coordinates.

## 2026-07-14 continuation update

This handoff has been continued by Codex on 2026-07-14. The original 2026-07-13 notes below are
kept for context, but several formerly-open items are now complete.

Current status:

- **Siren render/quantity work is complete.** Siren speaker render image/size data now lives in
  `parts_db.json` at the `siren_speaker` part-type level, with schema/domain/service/planner
  support. Quantity 1/2, placement-dot behavior, per-speaker bracket selection, vertical bracket
  stacking, and image aspect ratio were fixed. The final owner-visible size/aspect issue was resolved.
- **Manifest grouping UI is complete for the app view.** Shared `manifest_groups` data now lives in
  `parts_db.json`, is exposed through `/api/parts-db/manifest-groups`, and drives the manifest
  editor's sales-oriented grouping. Main categories use a navy full-width header. PDF/build-sheet
  export is intentionally deferred per owner instruction.
- **Picker header behavior is complete.** Main category and family headers can act as filters and
  expand/collapse controls. The dropdown caret was enlarged and selected headers auto-expand with
  a second click/caret collapse path.
- **Empty visible leaves are resolved.** Owner rulings were applied for cameras, radio cables,
  radio speaker, body cam dock, wireless mic charger, door-lock button, K-9 control head, and
  cloud/CradlePoint. A fresh sweep showed zero visible empty leaves.
- **Cloud / CradlePoint is now its own family.** Cloud tray, cloud antenna, and CradlePoint were
  separated from light control systems for browse/manifest organization.
- **New open data-quality issue:** product names like `WINDOW MOUNT`, `ROOF MOUNT`, `W/BRACKET`,
  `CLIP`, `ALL IN ONE UNIT`, and `VEHICLE SPECIFIC BRACKET` are too vague for sales-facing picker
  use. See `docs/audit/VAGUE_PRODUCT_NAME_AUDIT_2026-07-14.md` and FINDING-036 in the ledger.

Last green pins after 2026-07-14 code/data changes:

- `pytest tests/golden tests/contract` — 45 passed.
- `.venv/bin/python tools/ui_smoke/run_smoke.py` — 9/9 flows passed at that time.

The previous copy/paste handoff prompt was folded into this file and removed on 2026-07-15.

> Branch `claude/quickbooks-integration-design-rcgula`. Pins GREEN at HEAD (`5e9032c`):
> `pytest tests/golden tests/contract` 43/43, `tools/ui_smoke/run_smoke.py` 9/9, full suite 1709.
> Working tree CLEAN (see "Stashes" below). Read this first, then `docs/audit/LEDGER.md`
> (FINDING-025 … 035) and `docs/PARTS_DB_AND_PICKER.md`.

## What we're working on

Rebuild the three legacy **name-based** draft projects (`workspace/projects/*` →
`workspace/drafts/*`: Test/PIU-Patrol, Granite Falls PD, Toppenish PD) using the **new Part
Picker**, fixing picker/placement flaws as they surface. The owner supplied an 8-item flaw
list, then a second follow-up batch. The flaws are the *friction* blocking the rebuild; the
actual end-to-end rebuild of the three drafts has **not** been done yet (deferred until the
siren work below is settled — siren size/placement affects every build).

## Where we're at — SHIPPED this session (14 commits, `0f2d352`..`5e9032c`)

| Owner item | Status | Commit(s) | Ledger |
|---|---|---|---|
| Flaw 3 — empty part types | Fixed the real bug (cross-type family `motion_attachment` returned empty grid). 10 remaining empties are genuinely unhomed slots → **owner curation call** | `0f2d352` | F-025 (done), F-026 (owner) |
| Flaw 2 — "Console 1" | Single-instance part_types (console/equipment_tray/preemption) name bare ("Console") | `8a69b76` | F-027 |
| Flaw 1 — Gamber tags | 25 vehicle-specific kits fixed from `["any"]` to their real vehicle | `8f20b1c` | F-028 |
| Flaw 5 — brand auto-select | Preferred brand (lighting/bumper/cage/camera) auto-selects first + "preferred" badge, others collapse into a dropdown; killed FINDING-011 dup | `7ace723` | F-029 |
| Flaw 4 — manifest grouping | Groups by parts_db category+family via browse-tree (auto-follows sidebar); fixed FINDING-007 init-order | `691a7b1` | F-030 |
| Flaws 7+8 — sidebar restructure | Kept 5 headers; families-first order; selectable Warning/Interior/Scene/Spotlight; collapsed Scene/Spotlight (browse-level, no data merge); unified Light Bars; Structural = Push Bumper/Cage/Console/Storage | `80a5dfd`,`1e7a8af` | F-031 |
| Flaw 6 — siren brackets | Removed mis-homed Stalker *radar* bracket from siren accessory pool | `1783fb3` | F-032 |
| Follow-up — siren→lighting pref + `console_brand` | Sirens follow lighting brand pref; new console-manufacturer agency preference end-to-end (domain/codec/UI/notes/picker) | `25cdef5` | F-034 |

Owner rulings captured in memory: `project_sidebar_restructure_ruling` (keep 5 headers,
families-first, scene-collapse, Storage = stationary storage only).

## Where we're headed — OPEN work

### A. Siren size — NEEDS PARTS_DB DESIGN (blocked; owner-directed) — see F-035
The siren "extra large" bug is understood but the **fix approach was rejected** and reverted
(stashed). Facts:
- Sirens are `render_kind == "equipment"`. `get_icon_size()`'s equipment branch **ignores
  `size_class` entirely** — size = `EQUIP_SIZES[part.name]` (no siren entry) → `size_per_view`
  override → else raw-PNG aspect scaled to a 1.0" box (`siren_speaker_wo_bracket_front.png` is
  portrait 1920×2194 → oversized).
- The **assigned** size is the legacy Part-Type manager's **"Render size (inches)"** = `size_per_view`
  = front **0.59×0.65** (part_catalog "Siren Speaker 1"). It only attaches by exact legacy NAME
  ("Siren Speaker 1/2") and one library model (SA315P), so any other SKU / non-"1/2" name
  (all picker-built sirens once qty-naming lands) falls through → balloons.
- `028102a` (siren `size_class → sm` in `asset_manifest.json`) is **cosmetic / dead code** for
  equipment render — misplaced legacy-file data by the principle below; unwind when we do this right.

**Owner architectural directive (2026-07-13):** size + image data must live in the **parts_db**,
at the **part-type level** (with per-part override), NOT sprayed per-SKU across the legacy
`parts_library.json` / `part_catalog.json` / `asset_manifest.json`. The render pipeline reads
size/images from parts_db. Editing is either (a) the **revived legacy size/image UI pointed at
parts_db**, or (b) a **new feature in the new Part Manager**. This is a real feature to design,
not a data patch. **Do NOT reintroduce SKU-level size edits in the legacy files.**

### B. Siren qty (1/2) + Top/Under Push Bumper placement + render — NOT STARTED
- `TOP OF PUSH BUMPER` (slot_count=2, `pattern: mirror`) and `UNDER PUSH BUMPER` (slot_count=2,
  `pattern: horizontal`) in `vehicle_layouts.json` (PIU front) both draw 2 dots by fixed
  `slot_count`, regardless of the part's quantity — that's why 2 sirens render when qty=1.
- Owner ruling: add a **qty selector (1/2)** for siren speakers (in the accessory area);
  qty drives the render AND the location-picker dot count. **qty=1 → single speaker CENTERED**
  between the two mirror positions; qty=2 → one at each. Retire the old "Speaker 1/2" naming.
- Accessory: qty=2 → allow selecting **two brackets**.

### C. Siren bracket nests in "Other" — DIAGNOSED, NOT FIXED (bundle with D)
Owner: the selected speaker bracket lands as a top-level **"Other"** manifest row instead of
nested under the parent siren. Cause: flaw-4's per-section grouping runs **before** `_meMakeRows`
nests children; an accessory child (`parent_line_id` set) whose own part_type (`siren_speaker_bracket`,
browse-hidden) maps to a different section ("Other") gets separated from its parent.
**Fix:** in `_meRender`'s grouping, assign a part with `parent_line_id` to its **parent's** section
(`manifest_editor.js`). Same file as D.

### D. Manifest visual hierarchy — DIAGNOSED, NOT STARTED (`manifest_editor.js` + `styles.css`)
Owner: main-category headers are LESS prominent than sub-section headers, and subs add too much
space. CSS today: `.me-cat-group-head` (main, 10px muted) < `.me-cat-header` (sub, 11px navy bold
+ border); `.me-cat-section{margin-bottom:12px}`. Fixes: make main-cat headers prominent (can keep
space), sub-headers tight; and **drop the sub-header entirely when a section has only ONE
top-level part** (redundant — e.g. Auto Eject, Light Bar), keeping headers only where they group
>1 part/accessory (Console). Bundle the bracket-nesting fix (C) here.

### E. Sidebar: make ALL headers selectable AND dropdown — DIAGNOSED, NOT STARTED
Owner: every main-category header AND every family header should work as a **filter** *and* a
dropdown; today only the light families (with `picker_flow`) are selectable. Main-category filter
already works server-side (`category-skus?type=<type_id>` returns whole-type). Family filter needs
a union across member part_types — add a `family` param to `category-skus` (expand to members),
then make category + non-flow family headers selectable in `part_picker.js` (pattern already exists:
`.pbt-fam-select` + separate caret button from flaws 7+8).

### F. Flaw 3 leftovers — OWNER CURATION CALL (F-026)
10 empty browse leaves (cameras homed only to the DVR; Cloud System, Door Lock Button, Wireless
Mic Charger, Radio Speaker/Cable, K-9 Control Head). Each: home a product, keep as an
agency-supplied placeholder, or remove.

## Stashes (nothing lost)
- `stash@{0}` — **REJECTED siren-size SKU-level hack** (this session's interrupted agent). Do NOT
  apply; superseded by the parts_db design (A). Drop it once A lands: `git stash drop stash@{0}`.
- `stash@{1}` — old `WIP on main` dated **2026-06-15** (pre-session, not on this branch; app_settings
  /asset_manifest/part_catalog). Owner believes it isn't theirs; stale — safe to drop.

## Working norms that held up this session
- Run the app **cloud-off**: `DTM_CLOUD=0 .venv/bin/python -m dtm_buildsheet` (or preview config "DTM App").
- Pins are the safety net: golden masters must NOT move from authoring/DB changes; contract snapshots
  re-recorded ONLY on intended DB/route changes after eyeballing; 9 ui_smoke flows.
- Fixes were delegated to **Sonnet subagents** (mechanical, pin-protected); Opus did diagnosis/design.
  One subagent per coherent unit, serialized (they share git + LEDGER.md — concurrent commits race).
- **Golden re-records** are opt-in behavior changes (roadmap §3.2): eyeball the digest is
  the intended shape-only diff before recording.
