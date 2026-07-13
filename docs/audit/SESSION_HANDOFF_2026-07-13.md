# Session Handoff — Picker flaw-fix pass (2026-07-13)

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
