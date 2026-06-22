# Whelen new-products proposal (Phase 4b) — APPLIED 2026-06-22

**Status: applied** via `tools/qb_links/whelen_phase4b.json` (19 new products + folds).
Adjustments made per owner review:
- 4in Flat (2FC00ZCR) folded into **Round Lighthead** (with the 3" round SKUs), not its own product.
- **L31** and **L32** split into two products.
- **M08DT** = its own product **ION-T HD Array** (Harley/Electra Glide), not ION-V.
- **2250 Traffic Advisor** (TA2230F/TA2240F/WX2230) folded into existing `whelen_traffic_advisor`.
- FST/RST shared lightheads → **deferred to Phase 5** as accessories of FST/RST (family: "Inner Edge lightheads").
- Placements: Micron/L31/L32/V2/LINZ/R416 = all-warning; 700 = all-scene; 900 = all-scene+all-warning; Round = cargo (incl. liftgate).

### Flags to revisit
- **System 109 (`SYS109`, $3,460)** — HELD, not created. QB desc is bare "WHELEN SYSTEM 109"; identify before adding.
- **Avenger II** — set to `forward_warning`, but owner notes it physically only mounts **upper-windshield driver/passenger**. `fits_part_types` can't express that position restriction; may need placement-zone handling.
- **PAR-46** (P46FLC/P46SC) — color parser mis-tagged "purple/amber" from "PAR"; they're white spot lights. Fix colors.
- **MCRNSD** (Micron red/white) — QB price $964 vs ~$161 for siblings; likely a QB data error, verify.

---

## Original proposal (for reference)
# Whelen new-products proposal (Phase 4b)

The ~115 non-accessory orphan QB SKUs are mostly **product families not yet in the
catalog**, not missing color variants of existing products. This proposes new
products for them. **Approve / edit the `model` and `placement` columns, then I
create them** (via `qb_apply_links` `new_products` + `links`, so color/price auto-parse).

Placements use the `part_types` vocabulary. ⚠ = my placement guess is uncertain, confirm.

## Group A — Standalone new products

| Proposed product_id | model | placement(s) | SKUs |
|---|---|---|---|
| `whelen_micron` | Micron | side_warning, rear_warning, lower_liftgate_warning | MCRNSA, MCRNSB, MCRNSBX, MCRNSD, MCRNSF, MCRNSR, MCRNSRX |
| `whelen_responder_lp` | Responder LP | roof_light_bar | R1LPMF, R1LPPA, R2LPHPA, R2LPPA |
| `whelen_700_series` | 700 Series | rear_warning, tail_light_flasher ⚠ | 704BTT, 704BU, 70B02FCR, 70R02FCR |
| `whelen_900_series` | 900 Series | side_warning, rear_warning ⚠ | 90RC5FCR |
| `whelen_avenger_2` | Avenger II | forward_warning, rear_warning ⚠ (dash/deck) | AVC21RB, AVC22DD, AVC22EE |
| `whelen_3in_round` | 3in Round | rear_seat_cargo_lights ⚠ (compartment) | 3SBCCDCR, 3SC0CDCR, 3SRCCDCR |
| `whelen_4in_flat` | 4in Flat | side_scene ⚠ | 2FC00ZCR |
| `whelen_fluorent_plus` | Fluorent+ | cargo_lighting ⚠ (compartment) | F54PC, F63PC |
| `whelen_r416_beacon` | R416 Beacon | rear_warning ⚠ (rotating beacon) | R416BF, R416RF |
| `whelen_par46` | PAR-46 | front_scene ⚠ | P46FLC, P46SC |
| `whelen_par32` | PAR-32 | front_scene ⚠ | P32F2RB |
| `whelen_l3x` | L31/L32 | side_warning ⚠ | L31HRF, L32LAF |
| `whelen_v2_series` | V2 Series | side_warning ⚠ | V23ATPB |
| `whelen_linz_v_series` | LINZ V-Series | side_warning, rear_warning ⚠ | LINSV2A, LINSV2B, LINSV2BX, LINSV2R, LINSV2RX, LINV2A |
| `whelen_2250_traffic_advisor` | 2250 Traffic Advisor | rear_warning ⚠ (or fold into Traffic Advisor?) | TA2230F, TA2240F, WX2230 |
| `whelen_strip_lite_plus` | Strip-Lite+ | cargo_lighting ⚠ | PSCOMPH |
| `whelen_wing_plow_light` | Wing Plow Light | front_scene ⚠ (snow plow) | WPLOW1A |

**Equipment / control (not lights):**
| `whelen_wecan_control_point` | WeCan Universal Control Point | control_head ⚠ | WCCP |
| `whelen_system_109` | System 109 | ? ⚠ (identify first) | SYS109 |
| `whelen_ws321_mic` | WS-321 Mic | pa_mic | WSMIC321 |

## Group B — Probably variants/components of EXISTING products (fold, with your OK)

| Orphan SKUs | Fold into | Note |
|---|---|---|
| MBI2D, MBI2E, MBXI2D, MBXI2E, MBXI2J, MBIONVB, MBIONVR, MBXONVB, MBXONVR | `whelen_mirror_beams` | Mirror-Beam mounts w/ ION & ION-V heads — color variants |
| OEI2D, OEI2E, OEI2K, OEI2M, OEI3RBA | `whelen_ion_rear_pillar` | "Lighthead for RPWD/RPWT series" = the colored heads for the rear pillar |
| ISDD, ISDE, ISDJ, ISDK, ISDM, ISTBCA, ISSB, ISSR, ISTRBA, ISTRBC | `whelen_fst` and/or `whelen_rst` | "For FST AND RST series" — shared heads; which product? needs a call |
| TCRWXP*, TCRWXS*, TCRXXP*, TCRXXS* (20) | tracer products | Primary/secondary color heads for the Tracer system — but which lamp-count product? generic |
| IONHD3FM, M08DT | `whelen_ion_v_series`? | Motorcycle (Electra Glide) fork-mount ION-V / ION-T array |
| ITL12 | `whelen_liberty` | "Liberty II + 2 long 12-LED takedowns" — a Liberty config/option |

## Group C — Accessories / sub-assemblies → Phase 5 or skip

QuickFit roof platforms (QFFORD1*, QFRAM2*), TIONWEDG (mounting wedges),
M4B6LR (M/C box), 01-0244499-* (Alley Warning sub-assembly),
01-086A664-00 (Howler final assembly), BWD#/BWP# (low-profile lamp options),
M62T (turn light option), WSMIC321 if treated as accessory.
