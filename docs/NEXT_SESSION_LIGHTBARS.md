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
   `STPBK*`, and the pending tracer heads. Set real prices (part manager) or let them
   reconcile when the SKUs land in QB. Seth said prices are low-priority.
2. **Cenator & Edge 9X** roof bars carry placeholder SKUs (no real QB SKU) — need the real
   part numbers wired (with friendly names) before they're orderable.
3. **Midnight Edition → black straps** is a reminder only, not enforced. If wanted: require a
   black-strap mount (`STPBK*`/`MKEZ*` black) selected when Edition=Midnight before Add.
4. **Responder LP** still shows the lightbar config panel; its SKUs (`R1LP*`/`R2LP*`) look
   fixed-config like the mini bars — confirm with Seth whether it should skip the panel.
5. **More bar SKUs/configs** may be wanted beyond the few wired (Legacy has 3, Liberty 2).
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
