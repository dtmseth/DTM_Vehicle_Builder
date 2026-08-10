# Vague Product Name Audit - 2026-07-14

## Status update - 2026-07-15

This audit is now historical input, not a complete current queue. The high-priority exact-generic
rows, location-only rows, obvious missing vehicle tags, secondary bracket/mount rows, and ambiguous
model-code rows have had curation slices in `parts_db.json`, with data-quality guards added under
`tests/contract/test_parts_db_data_quality.py`.

Known remaining work is broader review: continue scanning sales-facing picker rows for names that
still need system/object context, and hide rows that are only locations, placeholders, or shop
details rather than real selectable products.

## Why this exists

The picker now exposes more of `parts_db.json` directly. That made a data-quality issue visible:
some product rows are named with generic fragments like `WINDOW MOUNT`, `W/BRACKET`, `CLIP`,
`ALL IN ONE UNIT`, or `VEHICLE SPECIFIC BRACKET`. A salesperson cannot tell what those products
are without already knowing the part type, manufacturer, or hidden QB friendly name.

Owner rule: every selectable product name needs enough detail to identify the item. If the source
data does not have that detail, curate it into `parts_db.json`; if the product is not a real
selectable item, remove it or hide it from browse.

## Audit result

Scripted pass over `src/dtm_buildsheet/resources/config/parts_db.json` flagged **81 products out of
784**. The highest-priority failures are the rows where the model itself is only a generic noun or
mounting phrase.

## Highest-priority cleanup

These should be fixed before continuing the rebuild workflow because they are genuinely hard to
understand in the picker.

| Product id | Manufacturer | Current model | Current leaf/family | Why it is a problem |
|---|---|---|---|---|
| `cradle_point_roof_mount` | Cradle Point | `ROOF MOUNT` | Cloud Antenna | Does not say CradlePoint/cloud antenna or carrier context. |
| `cradle_point_window_mount` | Cradle Point | `WINDOW MOUNT` | Cloud Antenna, Radio Antenna Top | Ambiguous; also appears in both cloud and radio antenna contexts. |
| `magnetic_mic_mmsu_1` | Magnetic Mic | `CLIP` | Radio Mic Clip | Bare noun; user cannot tell it is the Magnetic Mic MMSU-1 conversion clip. |
| `magnetic_mic_mmsu_1b` | Magnetic Mic | `W/BRACKET` | Radio Mic Clip | Bare modifier; needs the object and model context. |
| `motorola_all_in_one_unit` | Motorola | `ALL IN ONE UNIT` | Radio Head | Does not identify the radio head/control-head style clearly enough. |
| `motorola_split_unit` | Motorola | `SPLIT UNIT` | Radio Head | Does not identify the radio head/control-head style clearly enough. |
| `stalker_dual_swivel_bracket` | Stalker | `DUAL SWIVEL BRACKET` | Front/Rear Radar Antenna Mount | Needs radar antenna mount context. |
| `stalker_high_a_bracket` | Stalker | `HIGH A BRACKET` | Front/Rear Radar Antenna Mount | Needs radar antenna mount context. |
| `stalker_low_a_bracket` | Stalker | `LOW A BRACKET` | Front/Rear Radar Antenna Mount | Needs radar antenna mount context. |
| `stalker_vehicle_specific_bracket` | Stalker | `VEHICLE SPECIFIC BRACKET` | Front/Rear Radar Antenna Mount | Does not say what vehicle or what it mounts. |
| `watchguard_trab58003_wg1` | Watchguard | `ANTENNA` | Radio Antenna Top | Bare noun; likely needs WatchGuard/TRAB antenna context or removal from radio leaf. |
| `havis_vehicle_specific` | Havis | `VEHICLE SPECIFIC` | Console | Too generic for a console product. Needs exact console series/vehicle context or removal. |

## Secondary cleanup

These are less severe because they include some object context, but still need a sales-readable
label or a deliberate decision that the existing model code is enough.

| Product id | Manufacturer | Current model | Current leaf/family |
|---|---|---|---|
| `dtm_angle_bracket` | 5-0 Fab (Dtm) | `ANGLE BRACKET` | Side Warning Bracket |
| `dtm_grommet_mount` | 5-0 Fab (Dtm) | `GROMMET MOUNT` | Rear / Lower Lift Gate Warning Bracket |
| `dtm_l_bracket` | 5-0 Fab (Dtm) | `L BRACKET` | Side / Rear / Lower Lift Gate Warning Bracket |
| `dtm_license_plate_bracket` | 5-0 Fab (Dtm) | `LICENSE PLATE BRACKET` | Rear Warning Bracket |
| `dtm_universal_grill_bracket` | 5-0 Fab (Dtm) | `UNIVERSAL GRILL BRACKET` | Front Warning Bracket |
| `federal_signal_fs_q_mt` | Federal Signal | `RECESS MOUNTING BRACKET` | Bracket / Mount |
| `feniex_fusion_rotating_bracket` | Feniex | `Fusion Rotating Bracket` | Bracket / Mount |
| `feniex_fusion_surface_mount` | Feniex | `Fusion Surface Mount` | Warning Light |
| `feniex_fn_4016` | Feniex | `MOUNTING BRACKET` | Bracket / Mount |
| `gamber_johnson_7160_0826` | Gamber Johnson | `ADJUSTABLE MAG CLIP` | Radio Mic Clip |
| `havis_c_arm_102` | Havis | `SIDE MOUNT ARMREST` | Armrest |
| `night_ride_nv3_display_kit` | Night Ride | `NV3 Display Kit` | Thermal Imager Monitor |
| `santa_cruz_front_overhead_brackets` | Santa Cruz | `FRONT OVERHEAD BRACKETS` | Gun Lock Bracket |
| `santa_cruz_rear_overhead_brackets` | Santa Cruz | `REAR OVERHEAD BRACKETS` | Gun Lock Bracket |
| `santa_cruz_sc_9302` | Santa Cruz | `MOUNTING HINGE` | Gun Lock Bracket |
| `santa_cruz_sc_932` | Santa Cruz | `ROLL BAR MOUNT` | Gun Lock Bracket |
| `santa_cruz_sc_9903` | Santa Cruz | `L-BRACKET` | Gun Lock Bracket |
| `setina_cargo_bracket_kit` | Setina | `CARGO BRACKET KIT` | Equipment Tray |
| `setina_t_rail_mount_kit` | Setina | `T-RAIL MOUNT KIT` | Gun Lock Bracket |
| `stalker_remote_display_cable` | Stalker | `Remote Display Cable` | Radar Cable |
| `stalker_200_1089_00` | Stalker | `TAHOE DISPLAY MOUNT` | Radar Antenna Mount |
| `stalker_200_0622_00` | Stalker | `VSS INSTALLATION KIT` | Radar Cable |
| `qb_unassigned_ethernet_cable` | Unassigned (QB Import) | `Ethernet Cable` | Cable |
| `qb_unassigned_fire_extinguisher_brackets` | Unassigned (QB Import) | `FIRE EXTINGUISHER BRACKETS` | Tool Mount |
| `whelen_avenger_headliner` | Whelen | `Avenger Mount Kit` | Bracket / Mount |
| `whelen_fender_mount` | Whelen | `Fender Mount` | Front Side Bracket |
| `whelen_howler_mount_bracket` | Whelen | `Howler Mounting Bracket` | Bracket / Mount |
| `whelen_ion_grille_mount` | Whelen | `ION Grille Mount` | Bracket / Mount |
| `whelen_ion_lp_bracket` | Whelen | `ION License-Plate Bracket` | Bracket / Mount |
| `whelen_ion_t_mount_kit` | Whelen | `ION-T Mount Kit` | Bracket / Mount |
| `whelen_m2_lp_bracket` | Whelen | `M2 License-Plate Bracket` | Bracket / Mount |
| `whelen_strip_lite_mount` | Whelen | `Strip-Lite+ Mount Kit` | Bracket / Mount |
| `whelen_tracer_mount_kit` | Whelen | `Tracer Mounting Kit` | Bracket / Mount |
| `whelen_u_mirror_mount` | Whelen | `U-Series Under-Mirror Mount` | Mirror Warning Bracket |
| `whelen_vertex_adapter` | Whelen | `Vertex Adapter Kit` | Bracket / Mount |

## Model-code rows to review

These are short code/model names. Some are probably fine if the UI combines manufacturer, model,
part type, and friendly-name detail well. They should not be blindly renamed, but they should be
checked against the sales-facing picker display.

`pro_gard_hdx`, `setina_pb10`, `setina_pb5`, `setina_pb6`, `setina_pb8`, `setina_pb9`,
`setina_poly`, `soundoff_m4`, `stalker_dsr`, `watchguard_m500`, `whelen_cctl5`,
`whelen_cctl6`, `whelen_cctl7`, `whelen_cctl8`, `whelen_cctl9`, `whelen_cem16`,
`whelen_cem24`, `whelen_cem8`, `whelen_ion`, `whelen_l31`, `whelen_l32`, `whelen_sak1`,
`whelen_sak9`, `whelen_vxe`.

## Recommended fix path

1. Add a display-name curation pass to `parts_db.json` for the high-priority rows first.
2. Prefer product names that include object + system context, for example:
   - `Magnetic Mic MMSU-1 Radio Mic Clip`
   - `Magnetic Mic MMSU-1B Radio Mic Clip With Bracket`
   - `Stalker Dual-Swivel Radar Antenna Bracket`
   - `CradlePoint Roof-Mount Cloud Antenna`
3. If the product is only a shop-facing detail or agency-supplied placeholder, mark it unbilled or
   browse-hidden consistently instead of leaving it as a vague selectable product.
4. For rows where QB friendly names contain the missing detail, copy the useful human wording into
   the product model/display data so the picker does not depend on hidden import text.
5. Add a lightweight data-quality test after curation: fail on exact generic model names such as
   `CLIP`, `W/BRACKET`, `WINDOW MOUNT`, `ROOF MOUNT`, `ALL IN ONE UNIT`, and
   `VEHICLE SPECIFIC BRACKET` unless the product is browse-hidden.
