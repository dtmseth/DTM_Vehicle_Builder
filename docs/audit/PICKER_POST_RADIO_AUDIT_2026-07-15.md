# Picker Post-Radio Audit - 2026-07-15

## Scope

Deep-dive after the push-bumper, vague-name, search, Opticom, and Radio Communications changes.
The goal was not to implement the next feature slice; it was to document recent changes and identify
bugs, gotchas, or behavior likely to surprise the owner during the Granite Falls rebuild.

Files reviewed included `part_picker.js`, `planner.py`, `preview_service.py`, `vehicle_layouts.json`,
`parts_db.json`, route/service tests, preview tests, smoke flows, and current docs.

## Recently shipped behavior to preserve

- Search defaults to all categories, brands, vehicle tags, product/SKU text, and descriptions. The
  "Current filters only" toggle scopes it back to the current browse context.
- Brand is shown as a product-card chip instead of being forced into product names, so products such
  as ION sort under their model rather than under Whelen.
- Fixtures, including push bumpers and roof lightbars, auto-locate instead of asking for manual
  placement.
- Setina PB450L 2/4/6-light push bumpers inject render-only included tri-color lights. Tests assert
  the 6-light bumper adds top-tube plus side-push-bumper lights and shares the bumper preview group.
- Radio Communications now runs in the main picker product area and adds the normal radio rows as a
  guided system.

## Findings

### 1. Radio cargo-window antenna locations are friendly text, not render coordinates

**Severity:** high. **Ledger:** FINDING-037.

The radio workflow offers `LEFT CARGO WINDOW` and `RIGHT CARGO WINDOW` for antenna location. The
layout file has `UPPER CARGO WINDOW` and `LOWER CARGO WINDOW`, plus `REAR LEFT ROOF`; it does not
have exact left/right cargo-window keys. The synthesized planner path resolves views by exact
location key, so those choices can produce a valid draft row that does not render.

Recommended fix: decide whether these should be new layout coordinates, aliases to existing cargo
window points, or text-only radio install notes. If they should render, add the coordinates/alias
and a preview/PPT regression test.

### 2. Plan/render warnings are still not visible in the build editor

**Severity:** medium-high. **Ledger:** FINDING-038 and existing FINDING-006.

Planner warnings already say when a part has no views, no location, missing assets, or duplicate
placement keys. Those warnings reach service payloads and generated warning data, but the build
editor preview/manifest does not surface them clearly. With more picker-created synthesized parts,
this can look like "I added it and nothing happened."

Recommended fix: show plan, planned-part, placement, and instance warnings near the build preview or
manifest row with the part name and location.

### 3. Radio speaker UX is location-only, but implementation still depends on a hidden product row

**Severity:** medium. **Ledger:** FINDING-039.

The owner-facing rule is correct: a radio speaker is assumed; only its location matters. The current
workflow still loads a `radio_speaker` product/SKU and requires it before add is enabled. If that
hidden shop-detail product is removed, filtered, or renamed incorrectly, the radio flow can dead-end
without a visible product choice.

Recommended fix: make speaker a synthetic workflow row, or add a guard/test that exactly one stable
unbilled default speaker product is always available to radio workflow loading.

### 4. Westin push-bumper workflow is intentionally incomplete

**Severity:** medium.

Westin base bumpers currently ask for wire covers and a light channel, then add those accessory rows.
The owner's later requirement, choosing billed light heads based on the selected channel, is not yet
fully designed because the exact Westin channel-to-light rules are still uncertain.

Recommended fix: treat this as a next feature slice after the radio/render gotchas are settled.
Start with known channel SKUs and their supported light families, then gate add until the billed
lights have been chosen for channels that require them.

### 5. Radio workflow test coverage misses several owner-facing rules

**Severity:** low-medium. **Ledger:** FINDING-040.

Current coverage checks route data and a smoke add path. It does not explicitly assert that custom
speaker text persists, all-in-one radio hides the brick row, control head never offers tray
placement, or the radio workflow remains in the main SKU table area.

Recommended fix: add a focused UI smoke or DOM-level check the next time radio code changes.

### 6. Obsolete picker docs were creating false expectations

**Severity:** medium.

Several docs still said search was not started, Part Picker was roughly 80% complete, smoke was
9/9, parts_db was not wired into production reads, and the old 2026-07-14 handoff prompt was the
thing to read. Those statements conflicted with current code and test state.

Resolution in this docs pass: current-state handoff, gotchas, picker doc, roadmap, vague-name audit,
and ledger were updated; the obsolete handoff prompt was removed after folding relevant content into
the active handoff.

## Current verification snapshot

- `.venv/bin/python -m pytest tests/contract -q` passed 45 tests earlier in this working tree.
- `.venv/bin/python tools/ui_smoke/run_smoke.py` passed 10/10 earlier in this working tree.
- `pytest tests/golden tests/contract` currently has known golden drift in 5 golden cases; do not
  re-record or call it green without owner review.
