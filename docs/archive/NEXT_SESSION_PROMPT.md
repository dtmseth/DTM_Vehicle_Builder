# Prompt for the next session

Copy everything in the fenced block below into a fresh Claude Code session.

---

```
We're rebuilding how the intelligent Part Picker assigns PLACEMENT LOCATIONS, to
stop the legacy catalog from limiting the new parts_db schema. Do NOT start coding
until you've read the context docs and confirmed a plan with me.

## Read these first (in order)
- docs/PART_PICKER_PLAN.md — the picker design + full changelog of what's built.
- docs/PICKER_TRANSLATION_AUDIT.md — especially §8 (the direction change driving
  this session) and §7 (the bug that motivated it). §1 explains a cloud-sync
  gotcha that affects persisting parts_db changes.
- docs/GOTCHAS.md and CLAUDE.md — repo rules, footguns, key commands.
- docs/ARCHITECTURE.md, docs/DATA_MODELS.md, docs/CONFIG_SCHEMA.md — schema shape.

## The goal (owner's direction — see §8 of the audit doc)
Placements are chosen at the CATEGORY level, not per-product or per-catalog-slot:
- Every Warning light offers the SAME pool of warning placements; same for Scene,
  Interior, Interior Bar, Roof Bar, Spotlight.
- NO instance limits — I must be able to add 4+ Forward Warnings (any/mixed
  products), unlimited, names auto-sequencing (Forward Warning 1,2,3,4,…).
- Any product can go in any location in its category BY DEFAULT. Product/location
  restrictions (e.g. Under Mirror = specific models; light-bar/spotlight/thermal-
  camera placements) are EXCEPTIONS, added as explicit rules as needed.
- Stop deriving behavior from the legacy part_catalog.json (fixed numbered slots,
  per-name default_views, name→spec lookup). Use the parts_db schema as intended.

## What's currently broken because of the old model
A 3rd Forward Warning silently doesn't render (only catalog slots "Forward Warning
1/2" exist → the picker reused a name → duplicate part_id:view override_key →
dropped with no warning). Products that don't fit a location's "owner" part_type
get mis-assigned (e.g. Mini T at fog light renders on the side view, not where
expected). Root cause + the 6 required changes are in audit §8.

## The hard parts to investigate BEFORE proposing a plan
1. planner.build_plan (src/dtm_buildsheet/planning/planner.py) resolves a part by
   its exact NAME → catalog spec (default_views, asset_key, size). Arbitrary counts
   ("Forward Warning 3") aren't in the catalog → render_kind=none → silent drop.
   Figure out how to resolve render rules by part_type/category (strip the sequence
   number) so any count renders, and render in the view(s) where the chosen
   LOCATION has coords (not a fixed default_views).
2. render_ppt.py / the PPTX template: does it have fixed named rows/anchors that
   also cap instances? This decides how deep the change goes. (Open question Q6.)
3. preview_service.py:169 `override_key = part_id:view` collides for same-named
   parts — key by draft line_id instead.
4. No silent failures: PlannedPart.warnings exists but isn't surfaced to the
   manifest/build sheet. Plumb it through and warn on unplaceable/duplicate parts.

## Where the schema/data lives
- parts_db.json: src/dtm_buildsheet/resources/config/parts_db.json. part_types now
  carry an explicit `category` (warning/scene/interior/interior_bar/roof_bar). The
  schema has `allowed_placements` and `max_count` (currently empty for lights) —
  candidates for encoding category pools + exceptions, but design it the schema's
  intended way (confirm in DATA_MODELS/CONFIG_SCHEMA, propose if adding a structure).
- Placement coordinates per vehicle/view: vehicle_layouts.json (the picker's
  Location tab draws dots from this; reuse settings/placements.js geometry).
- Picker code: src/dtm_buildsheet/ui/js/part_picker.js (two-pane tabbed UI),
  endpoints in src/dtm_buildsheet/app/routes/parts_db.py
  (_resolve_product_locations is the current product-scoped resolver to replace
  with category-level), translation in src/dtm_buildsheet/planning/sku_resolver.py.

## Open questions to ask me before building (don't guess)
- Q5: naming convention for unlimited instances — is "Forward Warning {n}" the
  pattern for ALL warnings regardless of sub-type, or does zone/sub-type still set
  the base name? How is the base name chosen when placement is category-level?
- Q6: can the build-sheet PPT render arbitrary dynamic counts, or are rows fixed?
- Q7: confirm a category's placement pool = all located placements (in the
  category's relevant views) for the draft's vehicle, minus exceptions.
- Plus the still-open Q2 (light size for ~31 models that default to "sm") and Q3
  (add-without-placement for non-rendering parts like flashers), in the audit doc.

## Hard constraints (from CLAUDE.md / GOTCHAS / plan §8)
- Python via .venv: `.venv/bin/python -m pytest` (full suite ~1621 tests must stay
  green). All commands use `.venv/bin/python3`.
- parts_db.json writes MUST go through `save_config_file(...)` (or
  `tools/qb_apply_links.py --write`) — direct file writes are reverted by the
  SharePoint sync. To persist parts_db to cloud, it must be saved while the app is
  signed in (direct-mirror + proposal). See audit §1.
- Route modules export `route_xxx(handler, method, path, body, paths) -> bool`.
- JS: modal/panel pattern, one IIFE owns each save button; no build step.
- This is a real cloud-synced app — confirm before any destructive or outward
  action. The dev app runs on 127.0.0.1:7655 (`.venv/bin/python -m dtm_buildsheet`).

## How I want you to work
Read the docs, investigate the planner/renderer reality, then come back with a
proposed design + plan and your answers to Q5–Q7 (ask me what you can't determine).
Don't write band-aids — implement it the way the schema intends. Keep tests green.
After changes, I review via git on branch claude/quickbooks-integration-design-rcgula
(latest picker commit: "Part picker: two-pane tabbed redesign + schema-translation
fixes").
```

---

## Quick status for me (the owner)
- **Done & committed** (commit `4fa49b3`): two-pane tabbed picker, color configurator,
  SKU parser + tertiary color, single parent line + expandable components, dot-picker
  location tab, mirror dots/tooltip/sort, categories applied, 1621 tests green.
- **Cloud-pushed** parts_db via the signed-in one-liner (proposal `f1547af7`).
- **Remaining / next session**: the category-level placement rebuild (audit §8),
  plus open questions Q2 (sizes), Q3 (non-rendering parts), Q4 (surface warnings),
  Q5–Q7 (naming, PPT dynamic rows, pool definition).
