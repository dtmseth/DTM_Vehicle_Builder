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

## 8. ⭐ DIRECTION CHANGE — placements are category-level, no slot limits (2026-06-19)

**Owner decision (supersedes the per-part-type / catalog-slot approach in §2 & §7).**
The old system is still constraining the new schema. Fix it at the foundation:

- **Placements are chosen at the CATEGORY level.** Every **Warning** light offers the
  same pool of warning placements; every **Scene** light the same scene pool; etc.
  A product does NOT get its placement list from its `fits_part_types` or from the
  catalog's `default_views`.
- **No instance limits.** You can add 4+ Forward Warnings (all ION, or mixed), any
  number of any category part. The catalog's fixed slots ("Forward Warning 1/2",
  "Side Warning 1/2/3", "Front Side Warning" = 1) must NOT cap anything. Names must
  auto-sequence arbitrarily (Forward Warning 1, 2, 3, 4, …).
- **Any product → any location in its category, by default.** If a specific product
  can't take a location, or a location only accepts specific products, that's an
  **exception rule**, added as needed — not the default. Known exceptions to model
  later: **Under Mirror** (only specific workbook-named models), **light-bar**
  placements, **spotlight** placements, **thermal-camera** placements.
- **Stop deriving behavior from the legacy catalog.** The catalog's per-name
  `default_views`, fixed numbered slots, and name→spec lookup are exactly what cap
  us. The new schema (parts_db `categories`, `placements`, `allowed_placements`,
  `max_count`) is meant to own this.

### What this requires (for the next session to design + build)

1. **Category → placement pool** in parts_db (the schema's intended home), e.g. a
   per-category list of placement location keys (sourced from `vehicle_layouts`
   per vehicle). The picker offers that pool after product+SKU, location-last.
2. **Exception rules**: location → allowed products/part_types (and the reverse).
   Model the four known ones above when their data is ready; default is "no
   restriction."
3. **Unlimited, arbitrary naming.** Drop the catalog-slot cap. A part's build-sheet
   name should sequence per category/zone without a ceiling. Decide the naming
   convention (e.g. "Forward Warning {n}" with n unbounded) and where it's authored.
4. **Planner/renderer must resolve by part_type/category, not exact catalog name.**
   This is the crux. Today `planner.build_plan` looks up `spec` by the part *name*
   and reads `default_views`, `asset_key`, etc. "Forward Warning 3" isn't in the
   catalog → `render_kind=none` → silent drop. The resolver must strip the sequence
   number / key off the part_type so any count renders, and a part should render in
   whatever view(s) its chosen **location** has coords (not a fixed `default_views`).
5. **Unique part identity.** `override_key = part_id:view` (preview_service.py:169)
   collides for same-named parts. Key by the draft `line_id` so duplicates/many
   instances never overwrite each other.
6. **No silent failures (Q4).** Plumb `PlannedPart.warnings` to the manifest row +
   build sheet "not shown" area, and warn explicitly when a part can't place.

### Open questions to resolve with the owner (next session)
- **Q5 — naming convention** for unlimited instances: is "Forward Warning 1..N" the
  pattern for every warning regardless of sub-type (forward/side/rear/pit/mirror)?
  Or does the zone/sub-type still drive the base name? How is the base name chosen
  when placement is category-level (no part_type picked)?
- **Q6 — build-sheet rendering of arbitrary counts.** Does the PPT template have
  fixed named rows/anchors (which would also cap us), or can it render N dynamic
  rows? This determines how deep the renderer change goes. **Investigate
  `render_ppt.py` / the template before building.**
- **Q7 — category placement pools per vehicle.** Pools come from `vehicle_layouts`
  (each vehicle has different located placements). Confirm the pool is
  "all located placements in the views relevant to the category" for the draft's
  vehicle, with exceptions subtracted.

---

## 7. Part/location combos that silently don't render (2026-06-19) — SUPERSEDED by §8 direction

**Report:** ION / Mini T / Mega T added to FOG LIGHT AREA show nothing in the
preview or PPT, with no "not shown" note. VXE at FOG LIGHT AREA works. ION works
at TOP TUBE / TOP OF PUSH BUMPER.

**Root cause — one design flaw with two symptoms.** The picker offers a location
to a part_type using the broad `default_views ∩ layout` fallback (every location
visible in the part's render view), instead of the location's *true owner*. FOG
LIGHT AREA is curated (workbook rule) as a **Front Side Warning** location. Only
VXE/Surface-Mount-ION fit `front_side_warning`, so for them it's correct. ION,
Mini T, Mega T do **not** fit front_side_warning, so the fallback mis-assigns FOG
LIGHT AREA to whatever part_type they *do* fit:

- **ION → `forward_warning`.** But the catalog defines only **two** forward-warning
  slots ("Forward Warning 1/2"), and the draft already used both (TOP TUBE, TOP OF
  PUSH BUMPER). `_pickerChooseName` ran out of unused catalog names and **silently
  reused "Forward Warning 2"** — a duplicate. The preview/PPT key placements by
  `override_key = part_id:view` (preview_service.py:169); two "Forward Warning 2"
  in the front view collide on the same key, so the new one is silently dropped.
  (The planner *does* produce both — the loss is downstream at the override/render
  layer.) This is why the 1st and 2nd ION work but the 3rd vanishes — it has
  nothing to do with the location itself.

- **Mini T / Mega T → `side_warning`** (they don't fit forward/front-side). Side
  Warning renders **only in the side view**. So the part *does* render — just on
  the side view, not the front view where the user is looking. It looks missing
  but isn't. (Verified: Mini T @ FOG LIGHT AREA → "Side Warning 1", view=`side`.)

**Why this is the schema-translation gap:** the new schema has `allowed_placements`
(per part_type) and `max_count` — both **empty/None for every light part_type**.
Those are exactly the fields that should encode "which locations this part_type
owns" and "how many instances exist." With them empty, the picker falls back to
the view heuristic, which over-offers locations to the wrong part_types and can't
enforce capacity. The old workbook never hit this because its parts came pre-named
into fixed slots.

**Fix direction (NOT yet implemented — per your instruction):**
1. Drive location offering from **curated per-part-type ownership** (populate
   `allowed_placements`, or use the workbook-rule location lists as the owner
   set) instead of the `default_views` fallback. Then FOG LIGHT AREA is only
   offered for front-side-warning-capable products (VXE), and a location always
   maps to the part_type that actually renders it.
2. **Enforce `max_count` / catalog slot capacity.** When a part_type's slots are
   exhausted, the picker must stop offering it (or clearly warn) rather than
   silently reusing a name.
3. Make `override_key`/part identity **unique per added part** (e.g. include the
   draft `line_id`) so two same-named parts can't collide in the render.

**Q4 — surface failures, never silent (you asked for this):** anywhere a part
fails to find a location, asset, view, or unique slot, it must produce a visible
warning (in the manifest row and/or build sheet "not shown" area). Today the
planner *records* per-part warnings (`PlannedPart.warnings`) but the UI/PPT don't
surface them, and the override-key collision drops a part with **no** warning at
all. Recommend: (a) plumb `PlannedPart.warnings` through to the manifest + build
sheet, and (b) add an explicit "could not place / duplicate slot" warning at the
point of collision.

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
