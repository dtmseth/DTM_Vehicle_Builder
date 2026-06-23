# Pending-QB parts (design)

**Status:** plan locked 2026-06-23 (Seth). Not yet implemented.

## Goal

Let us pre-add a real, orderable part to `parts_db.json` **before it exists in
QuickBooks**, and use it normally — without blocking Vehicle Builder users. When the
part lands on an estimate, the estimate **flags it as missing from QB inventory** so the
QuickBooks user resolves it (creates the item) during review. This turns a blocker into
a to-do that travels with the work.

First consumer: the missing Tracer Trio / passenger-Amber heads
([TRACER_LIGHTHEAD_SELECTION.md](TRACER_LIGHTHEAD_SELECTION.md)). But this is a **general
capability** for any not-yet-in-QB SKU.

## Data representation

A `part_numbers[]` entry that is intentionally pre-added:
- has its real **`part_number`** (the Whelen/vendor SKU) and a **`price_usd`** we set by
  hand (since there's no `qb_unit_price` to pull);
- has **no `qb_item_id`** (empty);
- carries an explicit **`qb_pending: true`** flag.

`qb_pending` distinguishes "deliberately pre-added, awaiting QB" from the many legacy
entries that merely happen to lack a `qb_item_id`. Reconciliation (below) keys off it.

## Behavior

- **Vehicle Builder:** pending parts are fully selectable, placeable, and addable to a
  build — visually marked (e.g. a small "pending QB" chip in the picker/manifest) but
  never blocked.
- **Estimate push:** the part goes on the estimate like any other line, but annotated —
  e.g. a line note / flag **"⚠ Not in QB inventory — create item `<SKU>` ($<price>)"** —
  so the reviewer sees exactly what to create. (Decide: can the estimate still post to QB
  with a placeholder/non-inventory line, or does it hold that line for manual entry?
  Lean toward posting with a clear note so VB users stay unblocked.)
- **Build sheet:** renders normally (it's a real part with a price).

## Reconciliation (when the SKU appears in QB)

The QB items sync already pulls the catalog. On sync, for any `qb_pending` part whose
`part_number` now matches a QB item's SKU/name: fill in `qb_item_id` + `qb_unit_price`
and clear `qb_pending`. Surface a small "N pending parts resolved" note. This closes the
loop automatically once the QB user creates the item.

## Tooling

- `qb_apply_links.py` currently **requires** every linked SKU to be in the QB items cache
  (raises otherwise). Add a path to declare a pending part — e.g. a `pending_parts` op or
  a `pending: true` + `price` on a link — that skips the cache lookup, writes the entry
  with `qb_pending: true` and the supplied price, and never sets `qb_item_id`.
- Schema/UI: add `qb_pending` to the `PartNumber` model + part-manager editor; show the
  chip wherever SKUs render.

## Open questions

- Estimate posting: placeholder QB line vs. held line (above).
- Do pending parts need an approval/owner field, or is the estimate flag enough?
- Should `qb_pending` parts be excluded from any inventory/availability math until linked?
