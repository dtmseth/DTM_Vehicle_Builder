# Handoff: bulk-wire the remaining Whelen accessories (finish Phase 5b)

The accessories *feature* is fully built and shipped (schema, API, picker UI, draft
nesting, swap-edit). What remains is **data**: only 3 accessory products are wired so
far (the slice). This task attaches the rest of Whelen's accessory SKUs to their parent
products so the picker's per-category dropdowns populate across the whole line.

## State of the world (as of last session)

- **Done:** Whelen catalog Phases 1–4 (91 products, named/split/deduped/new families);
  accessories feature Phases 5a–5e; picker/UX fixes; cloud-clobber fix in the launcher.
- **Slice already wired** (`tools/qb_links/whelen_accessories_slice.json`):
  `whelen_ie_lighthead` (FST/RST shared heads), `whelen_ie_shroud`, `whelen_core_canport_cable`,
  wired to `whelen_fst`, `whelen_rst`, `whelen_core`.
- **Remaining: 159 unlinked Whelen SKUs** (description starts with "WHELEN", no `qb_item_id`
  referenced in parts_db). Rough categories:
  | category | count | | category | count |
  |---|---|---|---|---|
  | bracket_mount | 82 | | flange | 12 |
  | other | 39 | | lighthead | 9 |
  | flasher_power | 13 | | sub_assembly / cable | 3 / 1 |

## The model (already in parts_db.json)

- `accessory_categories` vocab: `lighthead, bracket_mount, cable, flange, shroud, flasher_power, other`.
- Accessory **part_types** exist: generic `lighthead/cable/flange/shroud/flasher_power`
  (type_id=lights), plus the original bracket types (`fw_bracket`, etc.) that carry
  `accessory_of` + `accessory_category`. Accessory products fit one of these so they
  DON'T appear as primary products in the picker.
- A product gets accessories two ways:
  1. **product-level** — `products.<id>.accessories = [{category, product_id, required}]`
  2. **part_type-level** — any product fitting an accessory part_type whose `accessory_of`
     matches one of the parent's `fits_part_types` (the generic-bracket path; auto-resolves).
- API: `GET /api/parts-db/accessories?product_id=<id>` returns both, grouped by category.

## The toolchain (use it — don't hand-edit parts_db.json)

`tools/qb_apply_links.py` mapping ops (all idempotent, dry-run by default, `--write` mirrors):
- `new_products` — create accessory products: `{product_id, model, fits_part_types:["lighthead"|"cable"|...]}`
- `links` — `{sku, product, vehicle_tags}` attaches a QB SKU (auto-pulls price + parses color/lens)
- `set_accessories` — `{<parent_id>: [{category, product_id, required}]}` wires parents
- (`rename`, `move`, `delete_products` also exist)

Apply: `.venv/bin/python tools/qb_apply_links.py tools/qb_links/<file>.json --write`

## Suggested approach (reviewable batches)

Work family-by-family, like the catalog passes. For each Whelen product family:
1. Find its accessory SKUs (brackets/cables/flanges/etc.) among the 159 — group by parent
   product and accessory category.
2. Create the accessory product(s) fitting the right accessory part_type; link the SKUs.
3. `set_accessories` to wire the parent product(s), marking `required: true` only when the
   parent genuinely can't function without it (e.g. a lighthead for a bare bar).
4. Dry-run, eyeball, `--write`, then `git commit`.

Many brackets are generic (fit `fw_bracket`/`side_warning_bracket` etc.) and may already
auto-resolve via the part_type-level path — check `GET /accessories` for a parent before
creating redundant product-level links. The `other`/`sub_assembly` buckets likely contain
non-accessories (final assemblies, junk) — flag, don't force.

## Find the remaining SKUs (starting query)

```python
import json,re
db=json.load(open('src/dtm_buildsheet/resources/config/parts_db.json'))
qb=json.load(open('workspace/quickbooks_items_cache.json'))['items']
ref={str(p['qb_item_id']) for v in db['products'].values()
     for p in (v.get('part_numbers') or []) if p.get('qb_item_id')}
wh=[i for i in qb if (i.get('description','') or '').upper().startswith('WHELEN')
    and str(i['qb_item_id']) not in ref]
```

## Gotchas

- **Launch via `Launch_DTM_VehicleBuilder.command`** (it sets `DTM_DEV_NO_SETTINGS_PULL=1`
  so the cloud doesn't overwrite local config). **Commit to git after each batch** — that's
  the real safety net.
- Editing accessory lines added before the metadata existed falls back to the full picker;
  re-add them to get the swap dropdown.
- Run `.venv/bin/python -m pytest tests/ -k "parts_db or schema or draft or qb"` after changes.

## Related docs
[PHASE5_ACCESSORIES_DESIGN.md](PHASE5_ACCESSORIES_DESIGN.md) ·
[WHELEN_NEW_PRODUCTS_PROPOSAL.md](WHELEN_NEW_PRODUCTS_PROPOSAL.md) ·
[WHELEN_PLACEHOLDER_REVIEW.md](WHELEN_PLACEHOLDER_REVIEW.md)
