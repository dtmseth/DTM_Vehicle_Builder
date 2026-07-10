# Part Picker Redesign — Design Spec

> **Purpose**: the single spec for the picker redesign the owner scoped 2026-07-07. Captures
> every design decision so the increment sessions (steps 1–6 below) build against one source
> instead of re-deriving intent. Owner-authored requirements; transcribed and organized here.
>
> **Status**: design locked, implementation not started. Step 0 (the DB taxonomy that unblocks
> the accordion) is in flight — see `PART_TYPE_TAXONOMY_PROPOSAL.md`.
>
> **How to use**: ship one increment at a time, in order — each is independently visible in the
> app and independently pin-protected. Do NOT batch. After each increment: golden masters must
> stay green (authoring-side changes; existing name-based builds render identically), re-record
> contract snapshots only if the DB was touched (`pytest tests/contract --contract-record`,
> after eyeballing the diff), and the `tools/ui_smoke` flows must pass.

---

## 1. Vision — two structural shifts

Everything below serves two ideas:

1. **Part types surface everywhere, as a browsable tree** — not just under Lights. Every
   sidebar category expands to reveal its part types (and part-type *families*) inline, so the
   user sees the whole map without navigating away. This replaces the current location-based
   browse tree with a `category → family → part_type` hierarchy (see Step 0).
2. **Product configuration lives in the product box, not the sidebar.** All the choices that
   define a light (mode, lens, color, colors-per-head, quantity) move out of the sidebar and
   into the selected product's box in the SKU grid, directly above the SKU dropdown — where
   they are most relevant to what's being configured.

---

## 2. Sequencing

| Step | Increment | Layer | Depends on |
|---|---|---|---|
| 0 | Taxonomy: fix `type_id`, invent families, re-base browse tree off families | DB | — (in flight) |
| 1 | Sidebar accordion — categories expand to families/part types inline | UI | 0 — ✅ shipped |
| 2 | Relocate light options (mode/lens/color/colors-per-head/qty) into the product box | UI | 1 |
| 3 | SKU dropdown rework — filter-by-options, per-head dropdowns, live title, "identical" | UI | 2 |
| 4 | Light visualization: footer → bottom of the product box | UI | 2 |
| 5 | Scene-light special case — qty only, in the product box | UI | 2,3 |
| 6 | Editor: pre-fill picker to the exact SKU(s) + lock the product type | UI | 1–5 |
| 7 | Multi-add flow — "Add and Finish" / "Add another part", return to picker position | UI | 1 |

Steps 1b (manifest-state highlight, folded into Step 1) and 7 are independent of the options
work (2–5) and can be prioritized whenever — both only need the accordion (Step 1).

Each increment ships and is testable on its own and sets up the next. The editor (Step 6) is
deliberately **last** — once the picker is restructured, edit becomes "open the picker with all
state pre-filled + the top-level type locked," so it can't be specced until 1–5 exist.

---

## 3. Increment specs

### Step 0 — Taxonomy (DB, in flight)
Detail in `PART_TYPE_TAXONOMY_PROPOSAL.md`. Outputs the picker depends on: corrected `type_id`
per part_type (e.g. center console → structural), the new **family** concept (schema + groupings;
families = part types that *belong together as one installed system*, not similar use/location/
kind), and the `category → family → part_type` browse hierarchy that Step 1 renders.

### Step 1 — Sidebar accordion (shipped 2026-07-09)
Implemented as designed: `GET /api/parts-db/browse-tree` (server-derived
`category → family → part_type`, `app/routes/parts_db.py`), rendered by
`ui/js/part_picker.js`'s `_pickerBrowseTreeHtml`/`_pickerWireFilters` (the old
"type" pill step + Lights-only "category" step are both replaced by the tree —
picking a light family leaf sets `category_id` to the family's `picker_flow`
and hands off to the unchanged colors/SKU/location flow). Non-light leaves
narrow `category-skus` via a new additive `part_type` query param (omitted →
old whole-category/whole-type behavior, unchanged). Manifest highlight (1b)
added a `part_type` field to `DraftPart`/the add-part payload; the tree
green-dots any part_type (and its parent family/category) with a part already
in the draft. Expansion state persists in a module-level `_pickerBrowseExpanded`
set for the session (Step 7 dependency). New `ui_smoke` flow:
`picker_browse_tree`; `add_text_mode_equipment_part` updated for the new
navigation (console moved under Structural › Console System per Step 0).

**Data-quality note found during this ship:** several `lights` part_types
(`lighthead`, `cable`, `flange`, `shroud`, `flasher_power`, `bracket`,
`bar_takedown`, `tracer_2_lamp/5_lamp/6_lamp`) render as bare tree leaves but
are actually accessory-category placeholders or orphaned taxonomy entries (no
`accessory_of` set, so Step 1's exclusion rule — same one used elsewhere for
accessories — doesn't catch them). Left as-is; a Step 0 follow-up should
either set `accessory_of` on them or drop them from `part_types`.

Original spec (kept for reference):
- Every sidebar category (Structural, Equipment, Lights, K-9, Extras) **expands in place** to
  show its contents. Today only Lights shows part types, and it does so by navigating to a new
  sidebar page — change that to an **inline dropdown** so all categories stay visible without a
  back button.
- A category's children are a mix of **families** (which expand again to their member part types
  for finer filtering) and **bare part types** (no family). Example: Structural → Bumpers
  (family → push bumper, pit bar, wing wraps…), Rear Partitions, Front Partitions, Center
  Console.
- Center Console appears under **Structural** (it is stationary, metal furniture). Things that
  mount to it live under Equipment.
- **Manifest-state highlight (Step 1b):** when a part type already has a product selected in the
  manifest, show that on the part-type in the tree — a **green highlight** or equivalent — so it
  is obvious at a glance which part types are filled and which have nothing selected. A filled
  part type needs no further selection unless the user wants to change it. This is the browse-time
  progress indicator for a build.
- **Resolved design calls (Opus, 2026-07-07):**
  - **Browse-tree is server-derived.** Add `/api/parts-db/browse-tree` returning
    `category → family → part_type` from `type_id` + `families` + `family_id`; the client renders,
    it does not reconstruct the tree. This is the data contract later steps read.
  - **Step 1 is navigation-only.** The accordion changes how you browse *to* a part type; the
    existing downstream flow (options + SKU selection, still sidebar-based for lights) is untouched
    until Step 2. Keeps the working light flow intact mid-redesign.
  - **Highlight matches on `part_type`.** Green when the in-progress build has a part mapped to
    that part_type (works for picker-created parts — the case that matters). Legacy name-based
    parts are best-effort.
  - **Expansion state persists within a session** — required by Step 7's return-to-position.
- **Deferred to Step 2:** whether a part-type-with-accessories surfaces accessories in the product
  box or a filtered list (push bumpers are the decided exception, §4). Not a Step 1 concern — the
  accordion just selects the part type and hands off.

### Step 2 — Options into the product box
- Move the light-configuration controls — **mode, lens, color, colors-per-head, quantity** — out
  of the sidebar and into the **selected product's box in the SKU grid, directly above the SKU
  dropdown**.
- The sidebar returns to being purely a browse/select surface; configuration happens where the
  product is.
- **Resolved design calls (Opus, 2026-07-09):**
  - **Options are per-product, shown on selection — this is a flow change, not just a move.**
    Today: pick a light part type → options in the sidebar pre-filter the product grid → pick a
    product. New: pick a light part type → the product grid shows that part type's products →
    pick a product → **its box shows the options above the SKU dropdown**, configuring *that*
    product. The grid is no longer pre-filtered by global options.
  - **Scope: relocation + rewiring only.** Move the existing controls into the box and wire them
    to the existing color/SKU resolution, scoped to the selected product. The **SKU dropdown keeps
    its current single-dropdown behavior in Step 2** — the per-head dropdowns, option-filtering,
    live title, and "identical" rename are all Step 3. Don't pull Step 3 forward.
  - **Accessories unchanged.** Standard footer accessory picker stays as-is (§4). The push-bumper
    in-box "add other bumper parts?" flow is a separate later feature, not Step 2.
  - **Scene lights: leave as-is in Step 2.** If moving options generally sweeps scene along, a
    temporary full option set in a scene box is acceptable interim — Step 5 strips scene to
    qty-only. Don't special-case scene here.
  - **Guard rails.** This is authoring-side; the name-based render path and golden masters must be
    untouched. Re-record contract snapshots only if a route changes.

### Step 3 — SKU dropdown rework
- **Filter by selected options**: the SKU dropdown only offers SKUs that match the currently
  selected options, so the user can't pick a SKU that contradicts their configuration. (Supersedes
  the Step 2 lens sort-to-default interim with a real filter.)
- **"Remove options" escape hatch**: a button that clears the option filter, leaving a dropdown
  of *every* SKU in the product — for when the user wants a SKU the options don't surface.
- **One dropdown per light head, by quantity** — even when the heads are identical. If qty = 3,
  show 3 SKU dropdowns, so it is explicit how many and exactly what is being selected.
- **Rename "uniform" → "identical"** (clearer).
- **Live SKU title**: the dropdown title updates based on the **SKU actually selected** — whether
  chosen via options *or* changed manually (today it only tracks option changes, not manual SKU
  changes). The title includes the **lens color** when applicable.
- **Resolved design calls (Opus, 2026-07-09):**
  - **Per-head override promotes to custom.** Render N dropdowns for N heads. In "identical" mode
    all N default to the same resolved SKU. If the user manually changes one head's dropdown to a
    different SKU, that build becomes a **per-head (custom) configuration** — reuse the existing
    `c.custom` per-head machinery; the other heads keep their SKUs. (Notable interaction call —
    veto if you pictured per-head edits behaving differently.)
  - **"Remove options" = unfilter, don't erase.** The button switches the dropdown(s) to list
    *every* SKU in the product and lets manual selection drive; it does not delete heads or the
    product. **When active, HIDE the filter controls (mode/lens/color/cph) entirely — not dimmed —
    but keep quantity visible and usable** (qty still drives how many per-head dropdowns show).
    Because the filter controls are hidden, the toggle button itself is the re-engage path
    (toggle off → controls reappear and the filter re-applies); there are no option controls to
    "touch" while removed. Button styling: a compact, clearly-a-button control (not a full-width
    header bar) in a distinct/prominent color so it's noticeable.
  - **Title is per-dropdown.** Each head's dropdown label reflects *its* selected SKU + lens; the
    product box keeps the product name. No single combined title across differing heads.
  - **Scene stays out.** Scene lights are handled in Step 5 (qty only); do not build per-head
    SKU dropdowns for scene here.
  - **Guard rails.** Authoring-side; name-based render path and golden masters untouched.

### Step 4 — Light visualization into the product box
- Move the light visualization ("demo light heads") from the footer to the **bottom of the
  selected product's box, below the SKU dropdowns**, where it is most relevant to the product
  being configured.
- **Resolved design calls (Opus, 2026-07-09):** it renders in the *selected* product's box
  (per-product, on selection), reflecting the current per-head configuration (colors/count from
  Step 3); the footer visualization is removed, not duplicated. Same rendering logic, new
  location. Authoring-side — render path and golden masters untouched.

### Step 5 — Scene lights special case
- Scene lights do **not** use the full option set. Remove **all** options except **quantity** for
  scene part types (no mode, lens, color, or colors-per-head).
- That quantity control still lives in the product box (per Step 2).
- This is a real divergence from warning/other lights — the picker must branch on scene vs.
  non-scene.
- **Resolved design calls (Opus, 2026-07-09):**
  - **Detect scene by `category == "scene"`** (equivalently the `scene_lights` family). Branch the
    product-box rendering on it.
  - **Scene box = quantity + SKU dropdown(s) only.** Hide mode / lens / color / colors-per-head
    AND the "remove options" toggle (there are no options to filter by). Keep per-head SKU
    dropdowns (N for qty N) for consistency with the rest of the picker — just without the option
    row above them.
  - **Light viz for scene renders uncolored** (scene heads have no color) — plain heads reflecting
    quantity, or omit if it adds nothing.
  - **Spotlight is in the scene family — it gets the scene treatment** (qty + SKU only). Flag for
    owner: if a spotlight should behave differently from scene floods, say so; default is
    scene-identical.

### Step 6 — Editor: pre-fill + type-lock
- When an existing build item is opened for edit, the picker opens with **every filter, product
  box, and option pre-selected** exactly as if the user had just navigated through to the chosen
  SKU(s). The user edits from that state.
- **Product-type lock**: the item is locked to its top-level product type. The user may change
  options *within* that type — quantity, brand, model, color, which light type — and possibly the
  location, but may **not** switch to a different product type (e.g. cannot edit a bumper into a
  cargo light).
- This is the redesign of the F-005 stopgap into a real edit contract; it supersedes the interim
  dirty-tracking stopgap once landed.
- **Resolved design calls (Opus, 2026-07-09):**
  - **Persist the picker config on the draft part (additive), so edit pre-fills exactly.** Add an
    optional config to `DraftPart` (mode, colorsPerHead, per-head colors, per-head SKUs, count,
    lens) that `_pickerDoAdd` writes for picker-created parts. Edit reads it directly. Parts saved
    *before* this change (and legacy name-based parts) lack it → the editor falls back to deriving
    what it can from `components`/colors. Additive and safe (draft-local field; validators/2.2.14
    ignore unknown keys).
  - **Pre-fill = full reconstruction.** On edit: set the browse tree to the item's part_type,
    select the product (existing `components[0].part_number` match), restore options/colors/qty/
    per-head SKUs from the persisted config (or derive), restore location. Scene parts restore
    qty-only (Step 5).
  - **Type-lock at the part_type level.** The browse tree is locked to the item's part_type. Within
    it the user may change product / brand / model / color / mode / qty / lens / SKU / location
    freely; they may NOT navigate to a different part_type (no bumper→cargo-light). *(Interpretation
    to confirm: "changing what light type" = changing the product/model within the part_type, not
    switching part_type. Location IS editable.)*
  - **Save writes the full reconfigured state and removes the stopgap.** Delete the F-005
    dirty-tracking (`_editTouched`); with correct pre-fill a no-op save is harmless (writes the
    same state). Save is enabled whenever the configuration is valid.
  - **Regression bar:** the F-005 repros must be safe by *correctness*, not by disabling save —
    edit→save-unchanged preserves the item byte-for-byte; the type-lock makes the "search matched
    'Midnight Edition' for 'ion'" cross-part_type clobber structurally impossible.
  - **Accessories:** keep the existing manifest accessory-swap path
    (`accessory_category`/`accessory_parent_product`); full accessory re-config inside the editor
    is a follow-up if it proves complex — don't block Step 6 on it.

### Step 7 — Multi-add flow
- After a part is added, the picker **returns to where the user was** (same category/family/
  part-type position in the tree) instead of closing — so several parts can be added in one
  session without reopening and restarting. Adding a bumper *and* a cage, or all the lights at
  once, is a continuous flow.
- The final screen for a part gets **two buttons**: **"Add and Finish"** (add this part and close
  the picker) and **"Add another part"** (add this part and return to the tree at the prior
  position).
- The final screen is normally the location picker. **If a part has no location, or only one
  possible location**, the location step is skipped and these two finish buttons appear **directly
  on the part page**.
- Pairs naturally with the Step 1b manifest highlight: add a part → return to the tree → the
  filled part type shows green → pick the next empty one.
- **Resolved design calls (Opus, 2026-07-10):**
  - **"Add another part" lands on the browse tree at the preserved position** (expansion state
    from Step 1's `_pickerBrowseExpanded`), with the manifest highlight refreshed so the
    just-added part type now shows green. The user navigates to the next thing — it does not
    auto-return to the same part type's grid.
  - **"Add and Finish" adds and closes** the picker (today's behavior).
  - **Button placement:** on the location step (the normal final screen). When the part has no
    location or exactly one possible location, the location step is skipped and both buttons
    render on the part page itself (per the existing skip-location logic).
  - **Edit mode is single-shot:** when editing an existing item, save closes (no "add another") —
    multi-add is for building, not editing.
  - Authoring-side; render path and golden masters untouched.

---

## 4. Cross-cutting decisions

- **Accessory model — keep the standard flow, one exception.** The current footer accessory
  picker works well for standard parts; keep it. **Push bumpers are the exception**: inside the
  selected push bumper's product box, an **"add other bumper parts?"** control lets the user pick
  compatible **pit bars, wing wraps, wire covers, and the Westin light bracket**. Do **not**
  surface the normal footer accessory picker for bumpers.
- **Families are a browse concept, not a physical one.** They group part types that belong
  together as an installed system (radar, camera equipment, the Whelen control system, radio,
  computer + docking station, console + swing arm). They are orthogonal to the three existing
  axes (category / location-zone / build-section) and must not be conflated with them.
- **Naming**: "identical," not "uniform."
- **Scene ≠ warning**: the two diverge in configuration (Step 5); code must branch, not assume
  one light model.
- **Pins discipline per increment**: golden masters green (authoring-side changes don't move
  name-based build output); contract snapshots re-recorded only on DB touches, diff eyeballed
  first; `tools/ui_smoke` flows green; commit each increment separately.

---

## 5. Open design points (resolve when speccing each step)
- Step 1: accessories-in-box vs filtered-list for standard part-types-with-accessories (push
  bumper already decided — special in-box flow).
- Step 2/3: exact control layout inside the product box (option row order, per-head dropdown
  stacking).
- Step 6: which fields the type-lock allows editing (qty/brand/model/color/light-type/location
  confirmed; anything else?) and what "location" edits are permitted.
