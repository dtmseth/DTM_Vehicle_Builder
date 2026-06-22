# Phase 5 — Accessories feature (scope / design)

**Status: scoping — for sign-off before any build.**

## Goal

When a user adds a part, any accessories that part needs (lighthead, bracket, cable,
flange, …) must be **impossible to miss**. The picker presents one selector per
accessory category, and won't let the part be added until each category has been
addressed (a choice, or an explicit "none"). Linking the ~138 unlinked Whelen
accessory SKUs happens *through* this feature.

## What already exists (don't rebuild)

`parts_db.json` already models accessories — it's just **never read by any code**:
- 17 part_types carry `accessory_of` (e.g. `fw_bracket → forward_warning`,
  `siren_speaker_bracket → siren_speaker`, `arges_mount → arges_controller`).
- 19 products already `fits_part_types` a bracket type (DTM brackets, Westin tubes,
  SAK1/9, …).
- `DraftPart.components[]` exists (UI-only SKU breakdown), and parts are independent
  priced lines — so accessories can be real, priced build-sheet rows.

So the relationship spine exists at the **part_type level** (generic: any forward_warning
light → offer FW-bracket products). What's missing: (a) product-specific accessories,
(b) accessory categories beyond brackets, (c) all the UI, (d) linking the QB SKUs.

## Data model

### 1. Accessory categories (new small vocabulary)
A `accessory_categories` block, used to group the picker's selectors:
`lighthead`, `bracket`, `cable`, `flange_mount`, `shroud`, `flasher_power`, `other`.
Each accessory part_type gets an `accessory_category` field.

### 2. Two applicability levels (support both)
- **Part_type-level (existing `accessory_of`)** — generic. "Any product placed as
  `forward_warning` can take these FW brackets." Already modeled; just honor it.
- **Product-level (new `accessories` field on a product)** — specific. For cases where
  an accessory only belongs to one product:
  ```json
  "whelen_fst": {
    "model": "Inner Edge FST",
    "accessories": [
      {"category": "lighthead", "product_id": "whelen_ie_lighthead", "required": true},
      {"category": "shroud",    "product_id": "whelen_ie_shroud"}
    ]
  }
  ```
  Accessory products are normal products fitting an accessory part_type; the FST/RST
  shared lightheads become **one `whelen_ie_lighthead` accessory product** referenced
  by both FST and RST (solves the "shared between both" problem cleanly).

### 3. Linking the QB accessory SKUs
`qb_apply_links.py` gains an **`accessory` link** form so the 138 Whelen accessory SKUs
(IONBKT*, FST/RST heads, Tracer heads, flanges, cables) are linked to accessory products
the same reviewable, re-runnable way as everything else.

## Picker UX (the unmissable prompt)

When a primary product is selected, after resolving its applicable accessories (union of
its part_type-level `accessory_of` matches + its product-level `accessories`):

- A distinct **"Accessories" section appears** in the part tab (the parts list you
  already built) — visually flagged (accent banner + count, e.g. "⚠ 2 accessory types
  for this part").
- **One selector per accessory category** present (Lighthead ▾, Bracket ▾, Cable ▾ …),
  each listing the matching accessory products/SKUs + price, with a "None needed" option.
- **Gated add**: the Add button stays disabled until every category is addressed.
  `required: true` accessories can't be set to "None". Optional ones can.
- Picking an accessory shows its price inline so the running total reflects it.

If a product has **no** accessories, nothing appears and the flow is unchanged.

## Draft storage & build sheet

Each chosen accessory is added as its **own `DraftPart` line** carrying a new
`parent_line_id` (= the primary part's `line_id`):
- It's a real, priced row on the build sheet (accessories have real costs).
- The manifest UI nests it under its parent (like today's `components`), and deleting
  the parent cascades to its accessories.
- `parent_line_id` defaults empty → fully backward compatible with existing drafts.

## Build plan (sub-phases)

| | Work | Output |
|---|---|---|
| 5a | Data: accessory_categories + `accessory_category` on the 17 types; `accessories` field on products; backfill product-level links for ION, FST/RST, Tracer, etc. | parts_db schema + mappings |
| 5b | `qb_apply_links.py` `accessory` link form; link the 138 Whelen accessory SKUs | mappings, orphans drop |
| 5c | API: endpoint returning a product's resolved accessories (categories + options) | `/api/parts-db/accessories` |
| 5d | Picker UI: accessories section, per-category selectors, gated Add | `part_picker.js` |
| 5e | Draft: `parent_line_id`, nested manifest render, cascade delete, build-sheet rows | `project_drafts.py`, manifest UI |

## Decisions — LOCKED

1. **Applicability**: both product-level (`accessories` field) and part_type-level (`accessory_of`).
2. **Gating**: hard-gate the Add button until every accessory category is addressed (pick or explicit "None needed"); `required` accessories can't be skipped.
3. **Accessory categories**: Lighthead, Bracket/Mount, Cable, Flange, Shroud, Flasher/Power, Other.
4. **Storage**: child lines with `parent_line_id` (each accessory is its own priced row, nested under the parent).
5. **Delete behavior**: **confirm first** — deleting a parent with accessories shows "This part has N accessories — remove them too?" before removing. No silent cascade.
