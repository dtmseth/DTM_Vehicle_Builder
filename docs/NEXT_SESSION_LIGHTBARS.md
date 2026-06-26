# Next session — tracer & lightbar lighthead selection (pickup)

Both the **tracer head-builder** and the **roof-lightbar config** are built, GUI-verified,
and committed (through ~`8622363`, 2026-06-26). This is the handoff for finishing the
loose ends. Full design + rationale: [TRACER_LIGHTHEAD_SELECTION.md](TRACER_LIGHTHEAD_SELECTION.md);
the pending-QB mechanism: [PENDING_QB_PARTS.md](PENDING_QB_PARTS.md).

## What's done

- **Tracers:** Standard Duo / Standard Trio / Custom in the part picker. Engine
  `app/services/lighthead_resolver.py::resolve_tracer` → `GET /api/parts-db/tracer-heads` →
  `#picker-tracer` panel. Auto-pairs driver+passenger housings for 3/5/6-lamp; renders as
  `tracer_Nlamp` (planner `_TRACER_RENDER_BY_SKU`); brackets: L-bracket = (lamps+1)×housings,
  vehicle kit = 1×housing (Add **and** manifest swap). Missing heads added as pending-QB.
- **Roof lightbars:** SKU picker + `#picker-lightbar` panel — Setup (Standard/Custom + order
  notes), Edition (Clear/Smoked/Midnight). Bars are fixtures → auto-located to "ROOF LIGHT
  BAR", no location prompt; `roof_bar` is no longer a color category (no head preview).
  Mini/micro bars skip the panel. Render fixed via planner `_BAR_ASSET_KEY`.
- **Pending-QB parts** feature is complete (model flag, `qb_apply_links.py` `pending_parts`
  op, estimate DescriptionOnly note, picker chip, auto-reconcile on QB sync, part-manager edit).

## Loose ends to pick up

1. **Pending-QB prices are $0 placeholders** — tracer vehicle kits `TCRB*`, black straps
   `STPBK*`, and the pending tracer heads. **Decided 2026-06-26 (Seth): leave for QB
   reconcile** — prices auto-fill when the SKUs land in QuickBooks; estimates already carry
   the price in the DescriptionOnly note. No action.
2. **Edge 9X** — **DONE 2026-06-26**: `"9X EDGE"` placeholder removed; 6 made-to-order SKUs
   wired as pending-QB on `whelen_9x_edge` (short `9XS` + tall `9XT`, lengths 48"/54",
   colors `DDDD`=R/W & `DEDE`=Duo R/B — mirrors Legacy). $0 placeholder prices (list prices
   in [reference doc](reference/WHELEN_PRICE_LIST_PL26.md) if set later). **Cenator** still
   a placeholder (`"CENATOR"`): it's a real Whelen bar (dropped from the printed PL26 list
   but live on whelen.com — TY/TB/TP/TJ SOLO/DUO WeCanX, T-series TRIO, CV/CX standard).
   **Blocked on Seth picking which Cenator series/length/color config(s) to wire.**
3. **Midnight Edition → black straps**: **Decided 2026-06-26 (Seth): keep reminder only,
   not enforced** — the picker shows the "needs black straps" note but Add isn't blocked.
4. ~~**Responder LP** config panel~~ — **DONE 2026-06-26**: Responder LP now skips the
   config panel like the mini/micro bars (its `R1LP*`/`R2LP*` SKUs are fixed-config). Rule
   extended in `part_picker.js::_pickerIsLightbar` (`responder lp` added to the skip regex).
5. **More bar SKUs/configs** may be wanted beyond the few wired (Legacy 3, Liberty 2,
   Edge 9X 6). Blocked on Seth providing the SKUs.

## Full-size bar vehicle tags (rule locked 2026-06-26, Seth)

Full-size roof bars filter by vehicle via per-SKU `vehicle_tags` (exact match vs the build's
`VehicleType`; vocabulary = `PIU, TRAVERSE, TAHOE, DURANGO, F-150`; no "all-except"
wildcard). **Rule: 48" → Durango only; 54" → everything else** → 54" SKUs carry
`["PIU","TRAVERSE","TAHOE","F-150"]`, 48" carry `["DURANGO"]`. Applied to Legacy, Liberty
(`BB2SP3J`), and Edge 9X. **When a new vehicle type is added, extend the 54" tag lists.**
Mini/micro/Responder LP bars stay `["any"]`. Left untagged on purpose: `ITL12` (a takedown
*option* mis-filed as a Liberty bar — data smell, revisit) and SoundOff `M-POWER` (non-Whelen,
no length data). Reference: [WHELEN_PRICE_LIST_PL26.md](reference/WHELEN_PRICE_LIST_PL26.md)
is the full PL26.0WL price list (all SKUs/prices, grep-able).
6. **Custom tracer color tint:** a Custom build tints the rendered lamp row by the *first*
   picked head's colors only (mixed-color customs render one tint). Fine for now; revisit if
   it matters.

## Conventions (so you don't re-derive them)

- Wire SKUs with `tools/qb_apply_links.py` mapping files in `tools/qb_links/` (`links`,
  `pending_parts`, `set_accessories`, `new_part_types`); dry-run → `--write` → commit.
- Every part link carries `friendly_name` + `vehicle_tags` (see [[project_accessory_wiring]]).
- Picker bottom panels (tracer/lightbar/accessories) each have an ✕ that cancels the
  selection (`_pickerClearSelection`).
- After parts_db changes run: `.venv/bin/python -m pytest tests/ -k "parts_db or schema or
  draft or qb or planner"`. Launch the app via `Launch_DTM_VehicleBuilder.command`.
