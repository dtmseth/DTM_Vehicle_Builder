# Parts-DB Curation Audit (Phase 1 of the curation-intelligence session)

**Date:** 2026-07-07 · **Basis:** live `src/dtm_buildsheet/resources/config/parts_db.json`
(906 products · 108 part_types · 522 homed products used as convention exemplars ·
384 unhomed = the curation queue). Read-only audit — no data was changed.

Companion artifacts: `tools/curation/workbook_graph.json` (Phase 2),
`tools/curation/proposals/` (Phase 3), `docs/audit/PARTS_CLASSIFICATION_GUIDE.md` (Phase 4).

---

## 1. State snapshot

| Measure | Value |
|---|---|
| Products | 906 (522 homed · 384 unhomed; 4 of the unhomed are accessory-role → effectively homed) |
| Unhomed by manufacturer (top) | qb_unassigned 115 · havis 44 · whelen 35 · santa_cruz 35 · gamber_johnson 32 · feniex 30 |
| part_types | 108 (56 equipment · 34 lights · 12 structural · 7 extras/k9) |
| part_types with 0 products | 20 (see §4) |
| `reviewed` flag set | 28 / 522 homed |
| Manufacturers | 62 in catalog + **2 referenced but missing** (§2.1) · 17 with zero products |
| Warning-light collapse | **Done** — legacy zone-named warning part_types are gone; `warning_light` holds 41 products |
| Triage state | `tools/triage_products.json` = exactly the 384 unhomed (129 medium · 67 low · 188 no-rule); high tier already applied |

The homed exemplars establish these working conventions (all confirmed in recent
`tools/plans/*.json`): one product per model with SKU variants merged under it; new warning
lights → the single `warning_light` home; brackets → `bracket` home + child-side accessory
role (`accessory_category` + `accessory_of_products`); `light` tag drives color UI; junk/BOM
artifacts deleted via `delete_products`.

---

## 2. Integrity findings (mechanical fixes, propose-and-apply)

### 2.1 Missing manufacturers — `dtm` and `specify` (HIGH)
9 products reference manufacturer ids that don't exist in `manufacturers`:
- `dtm` (7): `dtm_universal_grill_bracket`, `dtm_l_bracket`, `dtm_angle_bracket`,
  `dtm_dtm_extended_cargo_window_bracket`, `dtm_license_plate_bracket`, `dtm_grommet_mount`,
  `dtm_twist_lock_adaptor`
- `specify` (2): `specify_whip_style`, `specify_cylinder_style` (antenna styles)

Options: create the manufacturers (note `5_0_fab_dtm` "5-0 Fab (Dtm)" already exists — the
`dtm` 7 may belong there), or re-point `manufacturer_id`. **Owner ruling needed** on
dtm ↔ 5_0_fab_dtm; `specify` looks like a placeholder brand that should become a real one
(or the products fold into their parent product as SKU variants).

### 2.2 Duplicate tag: `service` / `service_2` (LOW)
Both labeled "Service". Usage: `service` 0 products, `service_2` 1 product. Merge → keep
`service`, re-tag the 1 product, delete `service_2`.

### 2.3 Duplicate products: SoundOff spelling twins (HIGH)
- `soundoff_nforce` ("NFORCE") vs `soundoff_n_force` ("N-FORCE") — both `warning_light`, 1 SKU each.
- `soundoff_mpower` ("MPOWER") vs `soundoff_m_power` ("M-POWER", also fits roof_light_bar) — 1 SKU each.

Merge each pair (`curate.py merge`). Watch for the same pattern when curating the remaining
SoundOff/Feniex queue (QB descriptions spell model names inconsistently).

### 2.4 Real lights missing the `light` tag (MEDIUM)
11 products homed to light part_types with no `light` tag:
`whelen_2_lamp_tracer`, `whelen_tracer_3/5/6_lamp`, `whelen_mirror_beams`, `whelen_fst`,
`whelen_rst`, `whelen_xlp`, `whelen_cenator`, `whelen_outer_edge`, `whelen_ion_rear_pillar`.
Mostly tracers/interior bars whose color lives in child heads or configured SKUs — they're
exempt from the *needs-color* check but should still carry the tag for UI consistency
(`add_tags: ["light"]`). Note `whelen_cenator` was retired — if it's still in the DB it
should probably be deleted instead.

### 2.5 Light products with colorless SKUs (MEDIUM — readiness blockers)
14 tagged-light products have ≥1 SKU without a color, e.g. `soundoff_nforce`,
`soundoff_mpower` (the dup twins), `whelen_liberty` (1), `whelen_traffic_advisor` (2),
`soundoff_enftc001bw/enfwb003mp/enfwbfs`. Some are bars (exempt); the rest need color parsed
from the QB description or a ruling. List surfaces in the SKU grid "Needs" filter.

### 2.6 Holding bucket still populated
`qb_unassigned` holds 132 products — 115 unhomed (Phase 3 covers them) **plus 17 already
homed but never re-branded**. Phase 3 proposals include manufacturer reassignment for all
132 (the `merge` op carries `manufacturer_id`).

### 2.7 `Preimer K-9` typo
Still present (`preimer_k_9`, 0 products). Pending Seth's confirmation to rename → "Premier
K-9" — zero-cost while it has no products.

---

## 3. Tree-structure findings

### 3.1 Zone-named *bracket* part_types are stragglers of the warning collapse (MEDIUM)
The warning-light homes collapsed to `warning_light`, but their bracket types remain, all
`accessory_of: "warning_light"` now:

| part_type | products |
|---|---|
| `fw_bracket` | 4 (westin light tubes ×2, tracer L-brackets, dtm grill bracket) |
| `side_warning_bracket` | 3 · `rear_warning_bracket` 4 · `lower_liftgate_warning_bracket` 2 (dtm brackets, multi-homed) |
| `mirror_warning_bracket` | 1 (`whelen_u_mirror_mount`) · `front_side_bracket` 1 (`whelen_fender_mount`) |

Six part_types all meaning "warning-light mounting bracket," distinguished only by the zone —
which the placement step now decides. **Recommend:** collapse all six into `bracket` (or a
`light_bracket` if you want lights-only separation), re-home the ~10 products, and express
parenthood child-side (`accessory_of_products`). Zero code references (verified — only data
files mention these ids). *Exception to weigh:* the Westin light tubes are arguably products
in their own right (pit-bar-mounted light carriers), not accessories.

### 3.2 Empty tracer part_types are superseded (LOW, safe delete)
`tracer_2_lamp` / `tracer_5_lamp` / `tracer_6_lamp` hold 0 products — tracers now live on
`warning_light` and the tracer configurator keys off the product, not these types. No code
references. Delete via `delete_part_types` (curate.py refuses if anything still fits — safe).

### 3.3 Scene lights are still zone-split — the one big consistency question (OWNER RULING)
Warning collapsed to one home; **scene did not**: `front_scene` (13) · `rear_scene` (10) ·
`side_scene` (3), with products multi-homed to express "fits anywhere" (`whelen_ez_scene`
fits all three; 900 Series fits 3 scene + warning). This is exactly the pattern the warning
collapse eliminated. Options:
- **(a) Collapse to `scene_light`** (category `scene`, `location_mode: placement`) — symmetric
  with warning; zone comes from placement. Migration analogous to `migrate_warning_lights.py`.
- **(b) Keep zone-split** — if front/rear scene genuinely differ on the build sheet in a way
  placement doesn't capture.
Phase 3 proposals name scene homes as today's three types (no invented types), so nothing
blocks on this — but deciding before bulk-applying avoids re-touching ~30 products.

### 3.4 Accessory-model duality is coherent but under-linked (MEDIUM)
Two mechanisms coexist by design: accessory *part_types* (`bracket` 21, `flange` 10,
`lighthead` 7, `cable` 2, `shroud` 1 — generic homes, excluded from placement) and
*child-side roles* (only 13 products carry `accessory_category` + parents). The picker can
only offer an accessory contextually when the child-side role names parents. **Recommend:**
every bracket/flange/cable proposal in Phase 3 includes `set_accessory` with best-guess
parents (confidence-marked); generic-fit brackets stay home-only.

### 3.5 `preemption` sits in `lights` with no category (LOW)
Type `lights`, no `category`, `location_mode: text`, trees on roof + interior, plus the only
`allowed_placements` + `max_count: 1` in the DB. It's a GTT/Opticom emitter — arguably
`equipment`. Harmless today (no picker category = not offered in light flows); worth a
deliberate home when convenient.

### 3.6 `flasher_power` (0 products) duplicates an accessory_category name
It exists both as a part_type and an accessory category. `headlight_flasher` /
`tail_light_flasher` (0 products each) are the actual homes proposals will use for flasher
modules. Recommend deleting the `flasher_power` part_type (category suffices) once confirmed
nothing lands there in Phase 3 review.

---

## 4. Zero-product part_types — keep vs. delete

**Keep (real build-sheet slots the queue will fill — Phase 3 proposes into several):**
`body_camera_dock`, `cradle_point`, `door_lock_button`, `front_camera`, `rear_camera`,
`rear_seat_camera`, `wireless_mic_charger`, `radio_speaker`, `radio_antenna_cable`,
`pa_mic_clip`, `printer_power`, `printer_usb`, `k9_control_head`, `floor_mats`,
`headlight_flasher`, `tail_light_flasher`, `wire_covers`.

**Delete (superseded/duplicated):** `tracer_2_lamp`, `tracer_5_lamp`, `tracer_6_lamp` (§3.2),
`flasher_power` (§3.6).

---

## 5. Three-axis conformance

- **Axis 1 (`part_type.category` — what it is):** populated only for lights (warning /
  scene / interior / interior_bar / roof_bar) — by design; the picker's light flows key off
  it. Non-light part_types carry no category (fine). Gaps: none that matter except §3.5.
- **Axis 2 (zone via placement):** placement-mode part_types (22) correctly cover the
  visual/coordinate world (warning_light, scenes, bars via fixture, push_bumper, pit_bar,
  wing_wraps, howler, siren_speaker, thermal_imager, auto_eject, radio_antenna_top,
  arges_face). Text-mode (86) covers interior/equipment. **No part_type lacks a
  location_mode.** 27 text-mode types carry curated `location_options`; the rest fall back to
  free text — the workbook graph (Phase 2) supplies option lists for high-traffic ones
  (`console`, `gun_lock`, `docking_station` currently have zero options).
- **Axis 3 (build-sheet section via tree_positions):** accessory part_types correctly have
  empty `tree_positions` (not in the browse tree). All product-holding non-accessory types
  have at least one tree position. `gun_lock` legitimately appears in 3 sections.

---

## 6. Categories needing special picker UI (flag only — no design here)

Already shipped: tracer configurator, roof-lightbar Setup/Edition panel.

| Category | Why the standard flow isn't enough |
|---|---|
| **Front partition** (`front_partition`) | Window model #6/#8/#10VS is a *feature* of the partition (solid / half-poly / sliding), plus recessed-panel and transfer-kit pairing — wants an option-driven configurator, not SKU-list. |
| **Push bumper** (`push_bumper`) | Vehicle-specific SKU + add-on cluster (pit wraps, wing wraps, wire covers, light channel population) — a fitment-then-accessories flow. |
| **Gun locks** (`gun_lock` + 36-product `gun_lock_bracket`) | Real-world selection is lock model × mount/bracket × location combo; Santa Cruz SKUs enumerate combinations. |
| **Remote start** (`remote_start`) | Arctic Start = base unit × vehicle-specific harness/kit (183-part catalog is mostly fitment kits). |
| **Radar** (`radar_display_unit` + antenna mounts + cables) | Multi-component system (display, 1–2 antennas, mounts, cables) — accessory gating may suffice, but flag for a system-builder review. |
| **Console build-out** (`console` + faceplates/armrests/cup holders/mounts) | Havis/Gamber-Johnson consoles are configured from a body + N faceplates + accessories; the current accessory mechanism can express it but the UX will want a dedicated flow. |
| **Seat covers / floor** (`seat_covers`, `floor_pan`, `floor_mats`) | Pure vehicle-fitment pickers (year/make/model), no color/placement. |

---

## 7. Recommended action order (all via existing tooling, proposals-first)

1. Mechanical integrity plan (§2.1, 2.2, 2.3, 2.4): one `tools/curation/proposals/` plan,
   owner reviews, `tools/curate.py --write`.
2. Owner rulings: dtm ↔ 5-0 Fab (§2.1) · scene collapse (§3.3) · zone-bracket collapse (§3.1)
   · Westin light tubes product-vs-accessory (§3.1).
3. Phase 3 batches per manufacturer (biggest first: qb_unassigned, havis, whelen,
   santa_cruz, gamber_johnson, feniex) — each a curate.py plan + review-sheet section.
4. Post-curation: delete empty superseded part_types (§4), re-run this audit's integrity
   checks, then unfreeze the SKU-grid save path (Stage C2 gate).
