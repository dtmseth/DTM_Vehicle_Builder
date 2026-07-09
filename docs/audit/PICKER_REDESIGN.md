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
| 1 | Sidebar accordion — categories expand to families/part types inline | UI | 0 |
| 2 | Relocate light options (mode/lens/color/colors-per-head/qty) into the product box | UI | 1 |
| 3 | SKU dropdown rework — filter-by-options, per-head dropdowns, live title, "identical" | UI | 2 |
| 4 | Light visualization: footer → bottom of the product box | UI | 2 |
| 5 | Scene-light special case — qty only, in the product box | UI | 2,3 |
| 6 | Editor: pre-fill picker to the exact SKU(s) + lock the product type | UI | 1–5 |

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

### Step 1 — Sidebar accordion
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
- **Open design point (resolve here):** when a part-type-with-accessories is selected from the
  tree (e.g. Push Bumper), do its accessories surface in the same product box or as a filtered
  list? See §4 accessory model — push bumpers are a deliberate exception.

### Step 2 — Options into the product box
- Move the light-configuration controls — **mode, lens, color, colors-per-head, quantity** — out
  of the sidebar and into the **selected product's box in the SKU grid, directly above the SKU
  dropdown**.
- The sidebar returns to being purely a browse/select surface; configuration happens where the
  product is.

### Step 3 — SKU dropdown rework
- **Filter by selected options**: the SKU dropdown only offers SKUs that match the currently
  selected options, so the user can't pick a SKU that contradicts their configuration.
- **"Remove options" escape hatch**: a button that clears the option filter, leaving a dropdown
  of *every* SKU in the product — for when the user wants a SKU the options don't surface.
- **One dropdown per light head, by quantity** — even when the heads are identical. If qty = 3,
  show 3 SKU dropdowns, so it is explicit how many and exactly what is being selected.
- **Rename "uniform" → "identical"** (clearer).
- **Live SKU title**: the dropdown title updates based on the **SKU actually selected** — whether
  chosen via options *or* changed manually (today it only tracks option changes, not manual SKU
  changes). The title includes the **lens color** when applicable.

### Step 4 — Light visualization into the product box
- Move the light visualization from the footer to the **bottom of the product box**, where it is
  most relevant to the product being configured.

### Step 5 — Scene lights special case
- Scene lights do **not** use the full option set. Remove **all** options except **quantity** for
  scene part types (no mode, lens, color, or colors-per-head).
- That quantity control still lives in the product box (per Step 2).
- This is a real divergence from warning/other lights — the picker must branch on scene vs.
  non-scene.

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
