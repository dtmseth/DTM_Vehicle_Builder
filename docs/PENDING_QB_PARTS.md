# Pending-QB parts (design)

**Status:** plan locked 2026-06-23 (Seth). **Implemented** 2026-06-23 — model flag, tool
op, estimate resolution + push, API payloads, picker chip, auto-reconciliation on QB sync,
**part-manager editing**, tests. Feature complete.

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
- **Estimate push (implemented):** a pending part posts to QBO as a **`DescriptionOnly`**
  line carrying **"⚠ NOT IN QB INVENTORY — create item `<SKU>`: `<name>` — `<qty>` × $`<price>`"**.
  This needs no `ItemRef`, never breaks the request, and shows the reviewer exactly what to
  create. Trade-off: a DescriptionOnly line carries **no Amount**, so the pending part isn't
  billed in QB until the item is created — the note carries the price for the reviewer to
  enter. The VB-side total (validate/manifest) **does** include the pending amount, so there's
  a known gap between the internal total and the posted QB subtotal until reconciliation.
  `validate_estimate` / `create_estimate` return `pending_count` (+ a `pending` list) so the
  UI can warn; pending is **not** a blocker (`can_create` stays true).
- **Build sheet:** renders normally (it's a real part with a price).

## Reconciliation (when the SKU appears in QB)

The QB items sync already pulls the catalog. On sync, for any `qb_pending` part whose
`part_number` now matches a QB item's SKU/name: fill in `qb_item_id` + `qb_unit_price`
and clear `qb_pending`. Surface a small "N pending parts resolved" note. This closes the
loop automatically once the QB user creates the item.

## Tooling

- **`qb_apply_links.py` `pending_parts` op (implemented):** `{product, part_number, price,
  color?, secondary_color?, tertiary_color?, lens_type?, friendly_name?, vehicle_tags?}`.
  Skips the cache lookup, writes the entry with `qb_pending: true` + `price_usd`, never sets
  `qb_item_id`. Idempotent.
- **Model/API/UI (implemented):** `PartNumber.qb_pending`; exposed on accessory + primary
  sku payloads; a "pending QB" chip in the part picker (primary rows + accessory dropdown).
- **Part-manager editor (implemented):** each part-number row has a **"Pending QB"**
  checkbox + the existing price field; the checkbox is disabled (with a green "QB" chip)
  once the SKU is linked. The product save now **preserves every per-SKU field** the form
  doesn't expose (qb_item_id, color, lens, vehicle_tags, …) by round-tripping the original
  SKU through an `encodeURIComponent`'d row attribute — previously a save rebuilt
  `part_numbers` from only part#/friendly_name/price and silently dropped the rest.

## Reconciliation (implemented)

`qb_sync_service.reconcile_linked_parts` (run after every items pull via `run_full_sync`)
walks all `part_numbers`: for any `qb_pending` entry whose `part_number` now matches a synced
QB item by **name or sku** (case-insensitive), it fills `qb_item_id` + `qb_sku` +
`qb_unit_price`, sets `qb_last_synced`, and clears `qb_pending`. Returns `reconciled_pending`
in the stats. Writes through `save_config_file` (SharePoint mirror) only when something
changed — so once the QB user creates the item, the pending flag clears itself on the next
sync and the part bills normally.

## Open questions

- Do pending parts need an approval/owner field, or is the estimate flag enough?
- Should `qb_pending` parts be excluded from any inventory/availability math until linked?
- Optional later: a configured placeholder QB item so pending lines can bill an Amount
  (instead of DescriptionOnly), closing the internal-vs-QB total gap before reconciliation.
