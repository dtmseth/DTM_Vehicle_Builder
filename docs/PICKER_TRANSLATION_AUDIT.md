# Part Picker — Schema Translation Audit & Open Questions

**Date:** 2026-06-18 (overnight autonomous pass)
**Scope:** Comb the old workbook/catalog rules, verify they translated into the new
schema, fix what was clearly broken, and surface what needs owner input.

---

## TL;DR — what was wrong and what I fixed

| # | Issue | Status |
|---|-------|--------|
| 1 | **parts_db.json edits silently reverted** (categories gone, colors partially lost) | ✅ Root cause found; data re-applied via sanctioned path. **Needs owner action to persist — see Q1.** |
| 2 | Placements that don't load in the preview | ✅ Fixed — 142/142 offered placements now load (was failing on view/name/non-render mismatches) |
| 3 | Non-rendering parts (Tail/Headlight Flasher) offered as placeable dots | ✅ Excluded from the location step (they're line items with no diagram icon) |
| 4 | Light size wrong for "certain models" | 🔶 Diagnosed (31 models default to "sm"); **fix needs owner input — see Q2** |
| 5 | Bracket dependencies (old `required_dependencies`) | ✅ Already translated correctly as `accessory_of` in parts_db |

Tests: **1621 pass.**

---

## 1. The big one — parts_db.json changes keep reverting (cloud sync)

**Symptom:** the `category` field I added to 22 light part_types was completely gone
(0 keys in the file), and the Whelen color parse was partially reverted (e.g.
`VX3BACX` was back to blank colors).

**Root cause:** `cloud_config.json` has `"enabled": true`. The app's SharePoint sync
pulls the cloud copy of `parts_db.json` and overwrites local edits. My category write
used a **direct `json.dump`**, which is exactly the "direct writes are reverted by sync"
gotcha documented in CLAUDE.md / GOTCHAS. The color parse partly survived only because
`qb_apply_links.py --write` saves through `save_config_file` (which queues for cloud).

**What I did:** re-applied categories through `save_config_file` and re-ran the parser
through `qb_apply_links.py --write`. The data is now correct on disk and validated:
- 22 light part_types carry `category` (warning/scene/interior/interior_bar/roof_bar).
- 164 Whelen SKUs carry color, 16 trios carry `tertiary_color`.

**⚠️ Q1 (BLOCKER):** These changes live in the working `parts_db.json` now, but will
**revert again on the next app launch unless they reach the cloud.** How do you want to
persist parts_db changes going forward?
- (a) Sign in + Force Sync so the local change pushes to SharePoint, **then** commit, or
- (b) Treat git as source of truth and reconcile the cloud copy from git, or
- (c) Something else.
Until this is settled, **any parts_db data work (categories, colors, future curation)
is at risk of being wiped.** This is almost certainly the "schema didn't transfer well"
you were sensing — the code translated fine; the *data* kept getting reverted.

---

## 2. Placements that don't load — fixed (root causes)

The planner only renders a part when **both** are true: the part `name` matches a catalog
`display_name`, and the chosen `location` exists in the vehicle layout within that part's
catalog `default_views`. Two translation gaps broke this:

1. **View mismatch.** The picker offered locations by logical `placement_zone`, which is
   *not* the visual layout view. e.g. `PUSH BUMPER MOUNT` is zoned `primary_front` but its
   coordinates live in the **side** view, so a front-rendering "Forward Warning" could
   never find it.
2. **Name mismatch.** Names came from parts_db `workbook_label_pattern`
   ("Front Side Warning {n}") but the planner recognizes the catalog `display_name`
   ("Front Side Warning", no number). The numbered ones ("Forward Warning 1/2") are a
   **fixed set** in the catalog.

**Fix:** `_resolve_product_locations` now reads `part_catalog.json` and only offers a
location if it exists in the layout within the part's `default_views`, tagging each with
the exact catalog `display_name`(s). The picker names parts from those catalog names
(lowest unused). Audit: **142 distinct (name, location) combos offered across all 64 light
products → 0 fail to load.**

---

## 3. Non-rendering parts excluded from placement

`Tail Light Flasher` and `Headlight Flasher` are `render_kind: "none"` — line items that
flash the vehicle's existing lights, with no diagram icon. They were being offered as
placeable warning dots (and failing at every spot). Now excluded from the location step.

**Q3 (follow-up, not a guess):** Non-rendering parts are still valid build line items but
have no placement. The picker currently can't add a part without a location. Do you want
an "add without placement" path for these (and similar no-diagram items), or should they
be a separate non-placed category? Left as-is for now.

---

## 4. Light size — diagnosed, needs your input

Size is **auto-derived from the part number** (= the product model on the parent line) via
`asset_manifest.json → part_number_size_rules` (ION→sm, M4→md, VERTEX→rd, VXE→sq), mapped to
pixel dimensions in `size_rule_definitions`. There is **no user-facing size picker** today;
the old workbook didn't have one either — size followed the model.

**The bug:** 31 light models have **no size rule** and fall back to the default "sm",
so they likely render too small ("wonky"). The legit lights among them:

- `M2 SERIES`, `M6 SERIES`, `M7 SERIES` (M-series — M4 is "md", but the number may imply size)
- `M9 SCENE`, `SUMMIT FLOOD`, `EZ SCENE LIGHT` (scene lights)
- `500 SERIES TIR`, `CENTURY`, `OUTER EDGE`, `TRAFFIC ADVISOR`, `AVENGER X1/X2`
- Lightbars: `LIBERTY`, `LEGACY`, `FREEDOM`, `9X EDGE` (these may use the separate `bar_assets` path)

I did **not** guess sizes — the size classes map to physically-calibrated dimensions, and a
wrong guess makes the render wrong.

**Q2:** Two parts:
- (a) Is "light size selection" meant to be **auto** (just fix the missing rules) or a
  **user-facing picker** in the left rail? If user-facing, what are the options per model?
- (b) For each fall-through model above, what size class (sm / md / rd / sq, or a new one)?
  In particular: are M2/M6/M7 the same size as M4 ("md"), or does the number imply size?

---

## 5. Bracket dependencies — already correct

The old `build_rules.json → required_dependencies` (e.g. "FW 1 Bracket requires Forward
Warning 1") translated correctly into the new schema as `accessory_of` on the part_type
(fw_bracket → forward_warning, etc.) — 18 accessory links present. The picker doesn't yet
*auto-suggest/add* accessories when you add a parent part, but the data is there and
schema-correct. (Follow-up if you want auto-suggest.)

---

## 6. Other observations (for later, not blocking)

- **Placement breadth for multi-fit products.** Products like ION fit four warning
  part_types, so it offers ~50 placements (all load). For tighter, fully-curated lists,
  the schema-correct lever is populating `allowed_placements` per part_type in parts_db
  (currently empty for most). The current behavior derives placements from
  `default_views` ∩ layout, which is correct but broad. Worth a curation pass later.
- **Location-name spelling drift.** A few workbook-rule names don't match the layout/
  placements table (e.g. "HEADLIGHTS CUT OUTS" vs "HEADLIGHT CUT OUTS"). These just don't
  show a dot; harmless but worth normalizing in a data pass.
- **Interior views have no dots** in `vehicle_layouts` (internal.console/cargo/rear_seat
  have 0 located coords), which is why interior placements render as buttons. If you want
  interior dots, those views need coordinates in placement settings.
