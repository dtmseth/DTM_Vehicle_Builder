# Parts Classification Guide

**Purpose:** the decision rules actually used in the 2026-07-07 curation-intelligence session,
written so a smaller model (or a human in a hurry) can classify new/remaining QB imports
consistently. Companions: [PARTS_CURATION_AUDIT.md](PARTS_CURATION_AUDIT.md) (state findings),
`tools/curation/WORKBOOK_GRAPH.md` (legacy relationships), `tools/curation/proposals/`
(worked examples — ~400 of them with rationale).

---

## 0. Ground rules (violate these and the proposal is wrong)

1. **Description-driven, never token-matching.** Classify from the QB *Sales Description* read
   as a sentence, plus brand knowledge and the reference catalogs (`docs/reference/`). A keyword
   hit is a hint, not an answer — `tools/qb_match_items.py` was abandoned for over-matching, and
   the keyword triage misfiled WeatherTech floor *liners* as prisoner-area `floor_pan`.
2. **Proposals only; apply via reviewed plans.** Emit `tools/curate.py`-schema JSON
   (`create_part_types` / `merge` / `set_home` / `set_accessory` / `delete_products`), embed
   `_confidence` + `_why` (+ `_question` on every low), dry-run, let the owner apply `--write`.
   Never write parts_db directly (60s cloud sync reverts raw writes; the save path is also frozen
   until curation completes).
3. **LOW confidence must state the specific question.** Never guess silently. If you can't name
   what would resolve it, you haven't finished thinking.
4. **Validate before handing over:** `python tools/curation/build_review_sheet.py` dry-runs every
   plan and checks queue coverage. A plan that doesn't dry-run clean is not a deliverable.
5. **One product per model; variants are SKUs.** Color, mount style, cable length, vehicle
   fitment, size class → `part_numbers[]` entries under one product (`merge` op). Don't create
   per-color or per-vehicle products.
6. **Kits mirror QuickBooks exactly.** One QB item = one product = one estimate line, even when
   the description says "PACKAGE"/"KIT" (Havis PKG-PSM, Federal Signal Valor SSP package, SnowEx
   complete kit). Only a real QB bundle/group would expand to component lines — the sandbox
   inventory has none. Never invent kit semantics.

## 1. The decision sequence (per product)

**Q1 — Is it a catalog part at all?**
Bookkeeping (discount/shipping/tax/labor/travel/credit), QBO sandbox artifacts (gardening,
landscape design), and `<BRAND> PART` free-entry placeholders → `delete_products` (they stay in
QB). Configurator-artifact SKUs (long option-suffix strings like `RPBKR700-K15-ON-BOBX8-P1`,
`BW54UFX` configured assemblies) are *probably* BOM artifacts → delete with a question.

**Q2 — Whose is it?** Fix the brand while you're there — `merge` with a single source re-brands,
re-homes, and renames in one op. Clues: part-number grammar (`C-xx`=Havis, `7160/7170-`=Gamber,
`SC-`=Santa Cruz, `K5xxx`/`1001-B` LOK family=PAC Tool, `DE20xx`=Lind, `FN-`=Feniex,
`ENT/ENF/ETH/ETF`=SoundOff, `NRR/NRP`=NightRide, `1U78…`=JB Lund, `E/Z-…`=American Aluminum,
`295SL…`=Whelen siren amps, `21x000-0002`=Unity). **Never write a `manufacturer_id` that isn't in
the manufacturers catalog** — that's how the `dtm`/`specify` orphans happened. If the brand
doesn't exist yet (Streamlight, Pelican, Momento, Getac, BAK, Acari), keep the product in
`qb_unassigned` and ask for a grid-created manufacturer.

**Q3 — Is it a light?** Then apply §2 color semantics before choosing a home.

**Q4 — Is it a child part?** Lightheads, lens/endcap kits, wedges, install/mount kits, cables,
power supplies, service kits → child-side accessory role (`set_accessory`: `accessory_category` +
`accessory_of_products`). **An accessory with a parent needs no part-type home** — that IS its
home. Give it a generic home too (`bracket`, `lighthead`, `cable`) only when it's also sold/used
standalone or generic-fit. If you can't identify the parent, home it generically and ask.

**Q5 — Which home?** Existing part_type first (match against the exemplars in §3). A NEW part_type
needs: ≥1 real product now, a slot meaning ("what is it" — not a zone, not a brand), a `type_id`,
`location_mode` (+options), and `tree_positions`. Ten were added this session (tool_mount,
pedestal_mount, spotlight, flashlight, computer, step_bars, trailer, prisoner_transport_insert,
snow_plow, tonneau_cover) — see `proposals/01_new_part_types.json` for the justification pattern.

**Q6 — vehicle_tags** go on SKUs when the description names fitment years/models ("2020-2026 FORD
INTERCEPTOR UTILITY"). Real names even for out-of-app vehicles (Blazer, Charger, Ram-1500…) —
Seth adds them to the app later. `qb_apply_links.py` handles per-SKU tags; curate.py merges keep
whatever the SKUs carry.

## 2. Color semantics by category (what color words mean for THIS part)

| Category | What R/B/W/A words mean | Action |
|---|---|---|
| Warning lights (`warning_light`, hideaways, surface sticks) | The head's fixed color pair — `R/W`, `B/W`, `DUAL COLOR - RED/WHITE` are **SKU variants**, one product | colored (anything beyond white) → `warning_light` + `light` tag; color/secondary_color on the SKU |
| Scene/utility (white-only: work lights, floods, spotlights, PAR-46) | "WHITE"/no color words = it's illumination, not warning | → scene/spotlight homes; still `light`-tagged |
| **The rule that decides between them:** a light with color options (not just white) is a warning light; white-only is scene/utility | | |
| Tracers / roof bars / interior bars | Color lives in child heads or the configured SKU (`EB2DEDE` bakes color in) | product gets `light` tag but is **exempt from needs-color**; don't parse bar SKU colors by hand |
| Lightheads (child) | The color in the description is that head's fixed output (Whelen Duo codes: D=R/W, E=B/W, K=R/A, M=B/A; Trio JC=R/B/W, JA=R/B/A; TCRWX clear / TCRXX smoked) | SKU color fields; parent stays colorless |
| Flashers (headlight/tail) | "R/C", pattern words = flash patterns, **not** lens colors | no color fields; not `light`-tagged (electronics) |
| Non-lights (brackets "BLACK", consoles, seats "BLK") | Finish, not light color | ignore for color fields |
| WeCanX / WCX / programmable | Per-config multi-color | never fix a color |

Lens words: SMOKED/SMK → smoked · CLEAR/CLR → clear · with a color present, default clear.

## 3. Home cheat-sheet (conventions verified against homed exemplars)

**Console world** (all Havis/Gamber unless noted):
- Console body / console kit ("CONSOLE BOX", "WIDE BODY CONSOLE") → `console`
- …but a console kit whose headline is the **armrest** → `arm_rest` (existing convention)
- Pockets, filler plates/panels, knockouts, cup holders, flashlight-charger pockets, console
  "wings", C-EB equipment brackets → `special_face_plate` (the console-furniture home)
- Faceplates ("FACEPLATE FOR MOTOROLA XTL…") → `special_face_plate`
- Armrests (incl. printer-mount armrests) → `arm_rest`
- Poles, base plates, leg kits, vehicle bases, tunnel mounts, pedestal packages, slide arms,
  braces, steps → `pedestal_mount` (new)
- Tilt/swivel/motion adapters, swing arms → `motion_attachment`
- Docks, cradles, tablet mounts, **dock power supplies (Lind)** → `docking_station`
- The laptop itself → `computer` (new)
- USB/12V chargers, lighter plugs, Kussmaul pass-throughs → `aux_12v_ports`

**Weapons:** complete racks (rack+lock, any mount style incl. K9/trunk-lid variants) →
`gun_lock`; rails, bases, hinges, muzzle cups/plates, shields, keys, release switches, RFID
add-ons, roll-bar mounts → `gun_lock_bracket`.

**Fire tools:** LOK-series (HookLok/HandleLok/JumboLok), axe/Halligan/bolt-cutter hangers,
extinguisher & SCBA mounts → `tool_mount` (new).

**Radar (Stalker):** display units → `radar_display_unit`; antenna/display mounts →
`front_/rear_radar_antenna_mount` (multi-home both when generic); VSS kits + antenna/display
cables → `radar_cable`; sun shields, speed modules → accessory of `stalker_dsr`/`_2x`.

**Thermal/camera:** NightRide units (Trailblazer/PRO-SL, incl. ethernet/grille variants as SKUs)
→ `thermal_imager`; 8" display kits & generic monitors → `thermal_imager_monitor`; dash cameras
w/ recording → `camera_dvr`; camera mounting brackets → `bracket` + accessory of the camera
(cameras themselves are often `unbilled` — agency-supplied).

**K9:** kennels/containment/transport platforms → `k9_kennel`; heat alarms, door poppers,
CoolGuard systems, stall sensors, AceWatchDog → `k9_heat_alarm_popper`; water dishes, mats, fans,
fan guards → `k9_add_ons`.

**Structural:** push bumpers → `push_bumper` · pit bars → `pit_bar` (shared Setina/Westin — never
relabel) · wing wraps = headlight guards → `wing_wraps` (fender wraps are "pit wraps") · wire
covers → `wire_covers` · window model #6/#8/#10VS = features of `front_partition`, not products
(6=solid stationary, 8=half-metal/half-poly, 10=sliding) · cargo-area barriers → `rear_partition`
· transfer kits + their recess/extension panels → `front_partition_transfer_kit` · vaults,
TufBoxes, drawers → `rear_storage_box` · prisoner-area ABS pans → `floor_pan` · consumer floor
liners (WeatherTech) → `floor_mats` · seat covers (incl. "bucket seat" covers) → `seat_covers` ·
TPO replacement seats → `replacement_rear_seat`.

**Audio/electrical:** siren amps, speakers, mechanical Q-sirens, handheld sirens →
`siren_speaker`; speaker brackets → `siren_speaker_bracket`; officer-facing combined controllers
→ `control_head`; trunk lighting controllers/switch centers → `light_controller`; headlight
flasher modules → `headlight_flasher`; taillight flashers → `tail_light_flasher`; fuse
modules/breakers/install-supply wiring → `harness`; battery chargers/maintainers (and, pending a
question, ChargeGuard timers) → `battery_tender`.

**QK prefix ≠ seats** (QK0491 = floor pans). **Generic RAM ball/arm hardware** → `bracket`,
home-only (no single parent).

## 4. Ambiguity playbook

- **Two products, same model, different spelling** (NFORCE/N-FORCE, MPOWER/M-POWER, AM900 twice)
  → merge; QB descriptions spell model names inconsistently, expect more.
- **"KIT"/"PACKAGE"/"MOUNT" with no other signal** → what does it *attach to*? The parent decides
  (accessory role); the noun decides the home only if standalone.
- **A rack vs. its rail**: the thing that holds the weapon/tool is the product; the thing the
  product bolts to is the bracket.
- **"For 20XX <vehicle>" in every SKU of a family** → one product, per-vehicle SKUs with
  vehicle_tags (Westin pit bars, Go Rhino bumpers, WeatherTech liners).
- **Zone words in descriptions ("REAR", "FRONT")** do NOT pick zone-named part_types for warning
  lights — the single `warning_light` home + placement decides. (Scene lights are still
  zone-split pending the audit §3.3 ruling — use front/side/rear_scene as-is until then.)
- **$0 prices + name-only descriptions** → suspect placeholder/junk; propose delete with a
  question rather than inventing a classification.
- **Brand exists with 0 products** (Ray Allen, Troy, Husky, TruckVault, Kenwood…) — that's a
  hint the workbook expected this brand somewhere: check `WORKBOOK_GRAPH.md`'s manufacturer↔slot
  matrix for where it was sold from.
- **When the reference catalogs disagree with the description, trust the description** (it's what
  QB bills) and flag the discrepancy.

## 5. Tooling map (what to emit, what applies it)

| Need | Tool |
|---|---|
| Home/merge/re-brand/accessory-role/delete + new part_types | `tools/curate.py <plan> [--write]` — plan schema in its docstring; extra `_`-prefixed keys are ignored, so rationale lives inline |
| Link QB SKUs to products, per-SKU vehicle_tags/colors, pending-QB parts | `tools/qb_apply_links.py <mapping> [--write]` |
| Validate plans + regenerate the review sheet | `tools/curation/build_review_sheet.py` |
| Regenerate the workbook relationship graph | `tools/curation/build_workbook_graph.py` |
| Location options seeding (already run) | `tools/seed_part_type_locations.py` |

**curate.py quirks to respect:** `merge` drops `accessory_category`/`accessory_of_products`
unless restated in the merge entry · `merge` reads `tag_ids` (not `add_tags` — that's a
`set_home` key) · `delete_products` silently skips unknown ids (so typos don't error — the
coverage check in build_review_sheet.py is what catches them) · `delete_part_types` refuses while
any product still fits.

**Apply rhythm:** close the dev app → dry-run → `--write` (goes through `save_config_file`, so
the cloud mirror fires) → commit → next plan. Plans are ordered by filename (00 integrity → 01
new part_types → 10+ batches).

## 6. Open rulings that gate consistency (ask, don't assume)

Tracked in `proposals/00_integrity.json` + the audit: scene-light collapse (§3.3) · zone-named
bracket collapse (§3.1) · dtm ↔ 5-0 Fab identity · trailers/plows/tonneau in-catalog or QB-only ·
motorcycle box family (sell m/c builds?) · services-vs-delete for labor lines · Whelen
singletons (SYS109, PFP2AP1, SP123BMC, QuickFit S/W suffixes).
