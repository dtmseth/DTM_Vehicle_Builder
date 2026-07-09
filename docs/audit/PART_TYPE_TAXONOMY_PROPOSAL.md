# Part-Type Taxonomy Proposal — category corrections, families, re-based browse

**Status: PROPOSAL ONLY.** Zero writes to `parts_db.json`. This unblocks the picker-sidebar
redesign (category → family → part_type accordion). Companion machine-applyable artifact:
[`part_type_taxonomy_plan.json`](part_type_taxonomy_plan.json).

**Basis (verified, not re-derived):** live `src/dtm_buildsheet/resources/config/parts_db.json`.
All **118** part_types carry `type_id` (structural 16 · lights 31 · equipment 60 · k9 4 · extras 7).
`part_type.category` is populated on only 17 (warning 6 · scene 4 · interior 4 · interior_bar 2 ·
roof_bar 1) as a **lights-only sub-grouping**. `tree_positions` (95/118) is **location-based**
(section/zone/sub_zone) — this is the browse axis we move away from.

**Terminology (read this first — the word "category" is overloaded).**

| Term used here | Means | Field |
|---|---|---|
| **Category** (top browse level) | lights / equipment / structural / k9 / extras | `part_type.type_id` |
| **Family** (new, this proposal) | a browse group between category and part_type | new `part_type.family_id` + new top-level `families` |
| ~~light sub-category~~ (legacy) | warning / scene / interior / interior_bar / roof_bar | `part_type.category` — **folded into families** by this proposal |
| Location / zone | where on the vehicle (placement metadata) | `location_mode`, `placements`, `tree_positions[].zone` |
| Build section | how it groups on the printed sheet | `tree_positions[].section` |

The **three orthogonal axes stay distinct** (category=what-it-is · zone=where · section=how-it-prints).
**Families are a fourth, orthogonal browse concept** — they may span type_ids, zones, and sections,
and they never conflate with any of the three. Location is *removed from the browse path only*; it
survives untouched as placement metadata for the preview and the build sheet.

---

## Task 1 — `type_id` correction pass

Reviewed all 118 part_types against the owner rules (a center console is **structural** stationary
metal furniture; anything that **mounts to** the console is **equipment**; the push-bumper family is
**structural**). **Result: the catalog is almost entirely correct.** One confident correction; the
rest are low-confidence judgment flags surfaced as owner questions (no change applied).

### 1a. Confident correction (apply)

| part_type | from → to | conf | reasoning |
|---|---|---|---|
| **`console`** (31 products) | equipment → **structural** | **HIGH** | A center console is stationary metal furniture bolted into the vehicle — structural by the owner rule. The things that mount *to* it (armrest, faceplate, pedestal, dock, swing arm, 12v ports) correctly stay **equipment** — verified they are all already `equipment`, so no cascade. Flip is metadata-only: no home / product / fits change. |

Push-bumper family already correct: `push_bumper`, `pit_bar`, `wing_wraps`, `wire_covers` are all
`structural` today. ✔ No change.

### 1b. Judgment flags — surfaced, **no change applied** (owner questions)

| part_type(s) | current | candidate | conf | note |
|---|---|---|---|---|
| `preemption` | lights | equipment | MED | GTT/Opticom signal-**preemption emitter** — an electronic transmitter, not an emergency light. Audit §3.5 already flagged this. Harmless today (no picker light category). → **OQ-7** |
| `bracket`, `cable`, `flange` | lights | cross-cutting accessory | LOW | Generic accessory homes nominally typed `lights`, but they hold camera/tool/equipment/structural accessories too. Recommend **leave** until the accessory-browse surface is designed; just don't treat them as lights-only. → **OQ-8** |
| `motorcycle_box` | equipment | structural? | LOW | A mount/storage box (furniture-ish) vs a gear-mounting system. Leaning keep-equipment. |
| `harness` | extras | equipment? | LOW | Fuse modules / breakers / install wiring are electrical. Cosmetic; leaning leave. |
| `headlight_flasher`, `tail_light_flasher` | lights (category=warning) | keep | — | Flasher modules are colorless electronics yet carry `category=warning`. Kept as-is to preserve today's behavior; flagged as a pre-existing oddity to revisit. |

**Explicitly NOT re-opened** (settled owner rulings, OPEN_QUESTIONS §C): scene-light collapse (C1.1,
gated on the location-pool fix), zone-named bracket fold → `bracket` (C1.2), `console`-adjacent tube
chase home (C7.1). These are migrations that run *after* this taxonomy lands.

---

## Task 2 — the "family" concept

**Definition (strict).** A family groups part_types that **belong together as one installed system /
are always specified together** — *not* by similar use, similar location, or similar kind. Membership
is **single** (a part_type sits under at most one family). Families are **selective**: most part_types
sit directly under their category with **no** family.

### 2a. Schema representation

One mechanism, reconciling the legacy light `.category` into it (no second overlapping concept):

1. **New top-level `families` collection** (sibling of `part_types`, `products`):

   ```jsonc
   "families": {
     "radar": {
       "label": "Radar",
       "category": "equipment",        // owning type_id — where it browses
       "kind": "system",               // "system" | "lighting_group" (see below)
       "picker_flow": null,            // light families set "warning"/"scene"/… (replaces .category for picker flows)
       "members": ["radar_display_unit", "front_radar_antenna_mount",
                   "rear_radar_antenna_mount", "radar_cable"]   // ORDERED (spec/install order)
     }
   }
   ```

2. **New optional `part_type.family_id`** — the inverse pointer (the migration target for the legacy
   `.category`). A warning part_type's `category:"warning"` becomes `family_id:"warning_lights"`.

**Why both `members` (on the family) and `family_id` (on the part_type)?** Ordering is a family
property, so the ordered list lives on the family; `family_id` is the denormalized anchor the browse
tree and integrity checks read. 1-family-per-part_type keeps them consistent.

**Nesting / bare part_types.** The browse tree is `category → family(dropdown) → part_types(dropdown)`
**with bare part_types allowed directly under a category** (any part_type with no `family_id`). So a
category node renders its families first, then its family-less part_types.

**Reconciling the legacy `.category` — "one concept, not two."** The five light `.category` values
(warning/scene/interior/interior_bar/roof_bar) migrate into **five `kind:"lighting_group"` families**.
They carry a `picker_flow` hint so the picker's existing light color/placement flows (which today read
`f.category_id`) keep working by reading `family.picker_flow` instead. The new belong-together groups
are `kind:"system"` with `picker_flow:null`. **One collection, one `family_id` field, one browse
widget** — `kind` is a descriptive discriminator (lighting kind-group vs installed system), *not* a
second parallel mechanism. If you'd rather not carry `kind` at all, it can be dropped; only
`picker_flow` is load-bearing (it preserves light-flow behavior). → this is the "one vs two" call.

**Migration safety.** `part_type.category` is still read by the picker (`_pt_in_category`,
`category-skus`, `category-locations`, the `_COLOR_CATEGORIES` color check) and mapped into the
`PartType` dataclass. So the apply plan **preserves `.category`** on the light part_types; it is only
retired once the picker is switched to read `family_id` + `picker_flow`. Families are purely additive
until then — nothing breaks. (Validation additions are optional keys, so the suite stays green.)

### 2b. Proposed families

Ordered members reflect spec/install order. Full data in the plan JSON.

#### Lighting kind-groups (migrated from `.category` — behavior-preserving)

| family | picker_flow | members (ordered) | conf |
|---|---|---|---|
| **Warning** | warning | `warning_light`, `headlight_flasher`, `tail_light_flasher` | HIGH |
| **Scene** | scene | `front_scene`, `rear_scene`, `side_scene`, `spotlight` | HIGH |
| **Interior Lighting** | interior | `cargo_lighting`, `front_dome_light`, `rear_seat_cargo_lights`, `rear_seat_lights` | HIGH |
| **Interior Bars** | interior_bar | `front_interior_light_bar`, `rear_interior_light_bar` | HIGH |
| **Roof Bars** | roof_bar | `roof_light_bar` | HIGH |

These are grandfathered kind-groups (by lighting kind), migrated 1:1 from today's `.category` so the
warning/scene/lightbar flows are unchanged. They are *not* "systems" in the strict sense — they are the
one exception the reconciliation folds in.

#### System families (strict belong-together)

| family | category | members (ordered) | conf | rationale |
|---|---|---|---|---|
| **Radar** | equipment | `radar_display_unit`, `front_radar_antenna_mount`, `rear_radar_antenna_mount`, `radar_cable` | HIGH | Owner example. Display + 1–2 antennas + mounts + cabling, always one system. Antenna mounts are already `accessory_of radar_display_unit` — corroborates belonging. |
| **Radio Communications** | equipment | `radio_head`, `radio_speaker`, `radio_cable`, `radio_mic_clip`, `radio_antenna_cable` | HIGH | Owner example ("radio"). `radio_antenna_top` **excluded** (shared roof antenna — "don't group all antennas"). `pa_mic`/`pa_mic_clip` **excluded** pending PA ruling (**OQ-3**). |
| **Camera System** | equipment | `camera_dvr`, `front_camera`, `rear_camera`, `rear_seat_camera` | HIGH | Owner example ("camera equipment"). DVR + cameras, one system. |
| **Light Control System** | equipment | `control_head`, `external_amp`, `expansion_module`, `cloud_system_tray`, `cloud_antenna`, `v2v_sync` | HIGH | Owner example verbatim: "core, external amp, expansion modules, cloud, vehicle-sync". Brand-neutral label (**OQ-4**). Flagged extras: `light_controller`, `photo_eye`, `power_timer` (**OQ-5**). |
| **Computer Workstation** | equipment | `computer`, `docking_station` | HIGH | Owner example ("computer + docking station"). Console **excluded** (owner: computer goes *in* the console = location). |
| **Thermal Imaging** | equipment | `thermal_imager`, `thermal_imager_monitor` | HIGH | Camera + its dedicated monitor, specified together. |
| **Push Bumper System** | structural | `push_bumper`, `pit_bar`, `wing_wraps`, `wire_covers` | HIGH | Owner example verbatim. **Westin light bracket** is not a part_type — per C1.2 it's a **product-level accessory** of `push_bumper` (Westin light tubes = push-bumper accessories), discoverable through this family. |
| **Console System** | structural | `console`, `motion_attachment` (swing arm) | MED | Owner example ("console + swing arm"). Console-furniture part_types are flagged, not auto-included (**OQ-2**). |

#### Deliberately **ungrouped** (proof of selectivity)

- **Printer** (`printer` + `printer_mount`/`printer_power`/`printer_usb`) — the last three are already
  `accessory_of printer`; a family would duplicate the accessory mechanism. Accessory-only.
- **Siren** (`siren_speaker` + `siren_speaker_bracket` accessory) — no sibling system; bare.
- **`radio_antenna_top`**, **`gun_lock`**(+bracket accessory), and standalone equipment
  (`remote_start`, `battery_tender`, `vehicle_interface`, `gpd`, `auto_eject`, `howler`, `flashlight`,
  `tool_mount`, `arges_*`) — bare under their category.

**Family vs. accessory mechanism (they coexist, orthogonally).** `accessory_of` = *build-time gating*
(surfaced/hard-gated when you add the parent, nested as child lines). `family` = *browse-time grouping*
(sibling part_types under one node). Radar's antenna mounts are **both** (accessory of the display AND
family members) — that's fine and expected. A cluster that is *only* parent+accessory (Printer) does
**not** need a family.

---

## Task 3 — re-based browse hierarchy

**Derived from `type_id` + `family_id`, NOT from `tree_positions`.**

### Before (today — location-driven, `part_manager.js::_pdbBuildTree`)

```
type_id → section → zone → sub_zone → part_type
```
- A `warning_light` appears under **lights → exterior → front / rear / side / roof**, duplicated across
  every zone it has a `tree_position` for.
- 23 part_types with no `tree_position` fall into an **"⚠ Unplaced"** bucket.
- Location (where on the vehicle) *is* the navigation — the exact thing the warning-light and scene
  rulings say should be decided at placement time, not baked into the browse path.

### After (proposed — category + families)

```
Category (type_id) → Family (optional) → part_type
                   ↘ bare part_types (no family_id) directly under the category
```

```
Lights
├─ Warning ▸           warning_light · headlight_flasher · tail_light_flasher
├─ Scene ▸             front_scene · rear_scene · side_scene · spotlight
├─ Interior Lighting ▸ cargo_lighting · front_dome_light · rear_seat_cargo_lights · rear_seat_lights
├─ Interior Bars ▸     front_interior_light_bar · rear_interior_light_bar
├─ Roof Bars ▸         roof_light_bar
└─ (bare)              bar_takedown · preemption
                       [accessory homes bracket/cable/flange/lighthead/shroud NOT shown — accessory surface]

Equipment
├─ Radar ▸               radar_display_unit · front_radar_antenna_mount · rear_radar_antenna_mount · radar_cable
├─ Radio Communications ▸ radio_head · radio_speaker · radio_cable · radio_mic_clip · radio_antenna_cable
├─ Camera System ▸        camera_dvr · front_camera · rear_camera · rear_seat_camera
├─ Light Control System ▸ control_head · external_amp · expansion_module · cloud_system_tray · cloud_antenna · v2v_sync
├─ Computer Workstation ▸ computer · docking_station
├─ Thermal Imaging ▸      thermal_imager · thermal_imager_monitor
└─ (bare)                 siren_speaker · radio_antenna_top · auto_eject · howler · gun_lock · tool_mount ·
                          flashlight · printer · remote_start · battery_tender · power_timer · vehicle_interface ·
                          gpd · photo_eye · light_controller · arges_face · arges_controller · pa_mic · motorcycle_box
                          [accessory homes for mounts/cables/clips NOT shown]

Structural
├─ Push Bumper System ▸ push_bumper · pit_bar · wing_wraps · wire_covers   (+ Westin bracket = product accessory)
├─ Console System ▸     console · motion_attachment
└─ (bare)               front_partition · rear_partition · rear_seat_divider · rear_window_bars · chicago_barrier ·
                        floor_pan · prisoner_transport_insert · rear_storage_box · replacement_rear_seat ·
                        running_boards_nerf_bars · tonneau_cover

K-9
└─ (bare)               k9_kennel · k9_heat_alarm_popper · k9_add_ons · k9_control_head

Extras
└─ (bare)               seat_covers · bullet_proof_door_panel · bullet_proof_door_window · floor_mats ·
                        window_tint · decals · harness
```

### What location-based grouping is being removed from the browse path

- **Removed as browse levels:** `section` (exterior/interior), `zone` (front/rear/side/roof/
  prisoner_area/side_storage/…), `sub_zone`. The sidebar **stops reading `tree_positions`.**
- **Retained as data / metadata (unchanged):** `tree_positions` still exists on part_types and is still
  read by the **SKU-grid filters** and **schema validation**; **location** still lives on the part_type
  as `location_mode` (`placement` vs `text`) + `location_options` and drives the **preview drawing**
  (placement mode) and the **build-sheet location text** (text mode). Nothing about *where a part ends
  up on the vehicle or the sheet* changes — only *how you navigate to pick it*.

### Before/after for three representative part_types

| part_type | Before (browse path) | After (browse path) | Placement still via |
|---|---|---|---|
| `warning_light` | lights → exterior → front **and** rear **and** side **and** roof | **Lights → Warning** | `location_mode: placement` at add-time |
| `radar_display_unit` | equipment → interior → forward_of_cage (one zone) | **Equipment → Radar** | `location_mode: text` options |
| `console` | equipment → interior → forward_of_cage | **Structural → Console System** | `location_mode: text` options |

---

## Apply path (determined)

**A small plan file + a one-shot applier — not Hierarchy-editor actions, not `curate.py`.** Reasons:

- The **Hierarchy editor** (`part_manager.js`) has no UI for a `families` collection and no `family_id`
  field on the part_type form; it also can't flip through the browse rebase. It *does* preserve unknown
  fields on save (full-doc merge), so it won't clobber families once they exist — but it can't *create*
  them.
- **`tools/curate.py`** ops (`create_part_types`/`merge`/`set_home`/`set_accessory`/`delete_products`)
  have no family concept.

**Plan:** [`part_type_taxonomy_plan.json`](part_type_taxonomy_plan.json) holds the console correction,
the `families` collection, and the `family_id` assignments. Applying it requires (owner-gated, separate
step — **not part of this proposal**):

1. **Additive schema support** in `config/schemas.py::_validate_parts_db` — accept an optional
   top-level `families` (dict) and an optional `part_type.family_id` (string). Both optional ⇒ existing
   data validates unchanged, suite stays green.
2. A one-shot **`tools/apply_family_taxonomy.py`** that loads `parts_db.json`, applies the plan, and
   persists via **`save_config_file`** (cloud-safe; a raw `json.dump` is reverted by the 60 s SharePoint
   sync — see §1 write invariant). Idempotent, dry-run by default, `--write` to persist while signed in.
3. Add `family_id` to `_PART_TYPE_EDIT_FIELDS` (parts_db.py:398) so the Hierarchy editor can later edit
   it. (`category` is already whitelisted there — the picker migration flips reads from `category` to
   `family_id`/`picker_flow` as a *follow-up*.)

The plan is **additive and non-destructive**: no part_type deleted, no `fits_part_types`/home changed,
no product touched.

---

## Skim-and-approve review section

Every proposed change, with confidence. ✅ = apply now · ❓ = owner question (nothing applied).

### Changes to apply

| # | Change | conf | note |
|---|---|---|---|
| 1 | `console` type_id: equipment → **structural** | ✅ HIGH | the known one |
| 2 | Add `families` collection + `family_id` (additive schema) | ✅ HIGH | optional keys; suite stays green |
| 3 | 5 lighting kind-group families (Warning/Scene/Interior/Interior Bars/Roof Bars) migrated from `.category` | ✅ HIGH | behavior-preserving via `picker_flow`; `.category` kept until picker migrates |
| 4 | Radar family | ✅ HIGH | owner example |
| 5 | Radio Communications family (5 members; PA + antenna_top excluded) | ✅ HIGH | edges deferred to OQ-3 |
| 6 | Camera System family | ✅ HIGH | owner example |
| 7 | Light Control System family (6 core members) | ✅ HIGH | label + 3 extras → OQ-4/OQ-5 |
| 8 | Computer Workstation family | ✅ HIGH | owner example |
| 9 | Thermal Imaging family | ✅ HIGH | |
| 10 | Push Bumper System family (4 members) | ✅ HIGH | Westin bracket = product accessory (C1.2) |
| 11 | Console System family (console + swing arm) | ✅ MED | furniture members → OQ-2 |

### Owner questions (nothing applied until answered)

| id | question |
|---|---|
| **OQ-1** | Approve `console` → structural? (recommended) |
| **OQ-2** | Console System: include console-furniture part_types (`arm_rest`, `special_face_plate`, `pedestal_mount`, `aux_12v_ports`) as members, or keep console + swing arm only? |
| **OQ-3** | PA (`pa_mic`, `pa_mic_clip`): Radio Comms family, a new Siren/PA family, or bare? (currently bare) |
| **OQ-4** | Light Control System label: brand-neutral "Light Control System" vs your "Whelen Control System"? |
| **OQ-5** | Light Control System members: add `light_controller` / `photo_eye`? Treat `power_timer` (ChargeGuard) as a member or a bare alternative-to-Core? |
| **OQ-6** | `pedestal_mount` (shared console/computer base): leave bare, or assign to Console System / Computer Workstation? |
| **OQ-7** | `preemption` type_id lights → equipment? (medium — it's a preemption emitter, not a light) |
| **OQ-8** | Generic accessory homes `bracket`/`cable`/`flange` are typed `lights` but hold cross-category accessories — leave until accessory-browse is designed? (recommended) |
| **OQ-9** | Carry the `kind` discriminator ("lighting_group" vs "system") on families, or drop it and keep only `picker_flow`? |

### Captured, not implemented (downstream)

- **Push-bumper in-box flow.** Push bumpers will get a special "add other bumper parts?" flow in the
  product box later. The **Push Bumper System** family + `push_bumper`'s product-level accessories
  (Westin tubes) are the linkage that flow reads. Members are linked/discoverable now; the picker UX is
  a separate downstream step.

---

## Owner answers (2026-07-07) — all 8 questions resolved; plan is final

Apply these when finalizing `part_type_taxonomy_plan.json` in the build session:

- **OQ-1 — console → structural:** ✅ APPROVED (metadata-only, no product cascade).
- **OQ-2 — Console System members:** **console + motion_attachment (swing arm) ONLY.** Leave
  `arm_rest`, `special_face_plate`, `pedestal_mount`, `aux_12v_ports` **bare** — they mount to
  the console (location), they don't belong to it as a system. Drop the flagged candidates.
- **OQ-3 — PA (`pa_mic`, `pa_mic_clip`):** **bare.** Not radio_comms, no PA family for now.
  radio_comms stays as-is (5 members, PA excluded).
- **OQ-4 — Light Control System label:** keep **brand-neutral "Light Control System"** (control
  heads may be Whelen/Feniex/SoundOff).
- **OQ-5 — Light Control System members:** **add `light_controller`** (trunk module) → 7 members.
  `photo_eye` stays a **product-level accessory** of the Core (NOT a family member).
  `power_timer` (ChargeGuard) stays **bare** — it's the alternative to a Core, not a co-installed
  member.
- **OQ-6 — `pedestal_mount`:** **bare** (shared base for console AND computer; belongs cleanly to
  neither).
- **OQ-7 — `preemption` type_id lights → equipment:** ✅ **FLIP to equipment** (owner: Opticom
  belongs in equipment). Add this as a second `task1_type_id_corrections` entry alongside console.
- **OQ-8 — generic bracket/cable/flange homes:** **defer** — leave until the accessory-browse UX
  is designed. No change now.

Net plan changes: `light_control_system` gains `light_controller` (7 members); a second type_id
correction (`preemption` → equipment); all flagged candidates resolved (console-furniture bare,
PA bare, photo_eye/power_timer not members). Families: 13 (5 lighting_group + 8 system).
