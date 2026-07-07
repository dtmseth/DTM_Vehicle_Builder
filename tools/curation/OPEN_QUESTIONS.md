# Open-questions triage — FACT vs PREFERENCE

Evidence session 2026-07-07. Source: every ❓/🔴 flag and low/medium-confidence entry in
`proposals/REVIEW_SHEET.md` (72 named questions) plus the audit rulings
(`docs/audit/PARTS_CURATION_AUDIT.md`). Findings with sources live in `EVIDENCE.md`;
resolved entries are updated in place in the plan files.

**FACT** = answerable by manufacturer evidence (what the part is, what a suffix encodes,
whether a QB line is a bundle, what it fits). **PREFERENCE** = taxonomy/judgment calls only
the owner can make. Goal: the owner sitting covers section B only.

---

## A. FACT questions (researched this session)

Status: ✅ resolved (plan updated, see EVIDENCE.md) · ◑ partial (narrowed, residual is a
preference call — cross-referenced in §B) · ❌ inconclusive (stays flagged; findings recorded).

| # | Part(s) | Question | Status |
|---|---|---|---|
| F1 | whelen_sp123bmc | what does the $497 chrome bumper mount carry? | ✅ it doesn't — it IS a speaker: SP123BM series 100W bumper-mount siren speaker (PL26) → siren_speaker |
| F2 | whelen_sys109 | what is System 109? | ✅ PL26: Super-LED System #109 — two stainless Micro 400 hideaways + 60' TPR cable + LED flasher/junction box + install kit |
| F3 | whelen_pfp2ap1 | what is PFP2AP1? | ✅ PL26: Dual Panel Pioneer Plus floodlight, 115 VAC, pole/pedestal mount adapter + on/off switch ($2,568 match). ◑ whether a 115 VAC pole flood belongs in vehicle builds → §B4 |
| F4 | whelen_m62t | standalone turn light or Traffic Advisor element? | ✅ PL26: M6-series surface-mount LED turn light (M62BTT/M62BU siblings) — standalone, not a TA element → M6 family |
| F5 | whelen_h35sn12 | replacement bulb for which product? | ✅ PL26: 35W snap-in halogen for 52 Series, DOT3 systems, Edge CA steady-burn, RDX, 4000 motor/reflector — legacy-halogen service stock. ◑ keep-vs-delete → §B4 |
| F6 | whelen_qfford1/1s/1w, qfram2/2s | S/W suffix meaning; which bars are QuickFit-compatible? | ✅ PL26: blank=black aluminum (no magnet lights), S=black **steel** (magnet-OK), W=white aluminum, SW=white steel. Platform carries Whelen beacons, Responder LP/HD, Mini Century, Mini Liberty II, Mini Legacy (last two need MK9S) — NOT the full-size Legacy/Liberty/Freedom. Parents re-pointed to whelen_r416_beacon / whelen_responder_lp / whelen_century / whelen_mini_legacy |
| F7 | whelen_22leca, whelen_22reca | '22' prefix — Legacy or another family? | ✅ PL26: options for the **WeCanX 2250 Series Build-A-Bar** surface-mount bars (angled endcaps for aerial-recognition light, 30–50" bars, $144 match). ◑ no 2250-series product exists in the catalog → §B5 |
| F8 | whelen_lcphoto | Legacy-only or also Liberty/Freedom? | ✅ PL26: neither — Logic Level Photocell for SLFLASH, CenCom Core/Sapphire/Carbide, CanTrol → accessory of whelen_core (CenCom Core) |
| F9 | whelen_cc5k2 | which catalog product is CCSRN5? | ✅ CCSRN-5 = CenCom **Carbide** siren & light controller (whelen.com/danasafetysupply). Not in the catalog (only CenCom Core) → install kit stays home-only `bracket`. ◑ create a Carbide product? → §B5 |
| F10 | whelen_linz6r merge | is LINZ6 the same family as "LINZ V-Series"? | ✅ PL26 section header: "LINZ6 & LINV2 V-Series Linear Super-LED Lightheads" — same family; merge confirmed |
| F11 | whelen_bw54ufx | configured-order BOM artifact? | ✅ NO — real PL26 line item: Inner Edge **XLP** upper-front two-piece unit, twelve 6-LED DUO, Tahoe PPV/SSV 2021-26 ($2,254 exact match). Delete reversed → merge as SKU of whelen_xlp |
| F12 | whelen_68_1183491a16 | which product is "Freedom Micro Edge"? | ◑ 68-1183491A·· is the **9M/Edge-9000-series lens** family (zips.com lists 68-1183491A02B "9M Series Lens – Amber") — points at a legacy *Micro Edge* bar, which is NOT whelen_freedom (that's the Micro Freedom). No Micro Edge product in catalog; stays flagged → §B5 |
| F13 | qb_unassigned_eluc3h010e | whose part is ELUC3H010E? | ✅ **SoundOff Signal** Universal UnderCover LED Insert — standalone screw-in hideaway kit (insert + extreme-angle lens + inline flasher, dual blue/white, 10' 5-wire). Not a bar child → re-brand soundoff + home warning_light (hideaway convention) |
| F14 | qb_unassigned_pel2b | PEL2B brand/series? | ❌ see EVIDENCE.md — research inconclusive, stays flagged |
| F15 | stalker_200_0243_00 | counting-unit mount: antenna-mount family or display bracket? | see EVIDENCE.md |
| F16 | stalker_200_1503_00/_11 | speed modules optioned per-radar or sold standalone? | see EVIDENCE.md |
| F17 | gamber_johnson_7160_0826 | mag clip: mic clip or console accessory? | see EVIDENCE.md |
| F18 | gamber_johnson_7160_1048 | what is the "universal storage box for electrical equipment"? | see EVIDENCE.md |
| F19 | feniex_fml | Fusion mini bar: roof or dash/deck? | see EVIDENCE.md |
| F20 | feniex_fenflas | what is FENFLAS ($47.90)? | see EVIDENCE.md |
| F21 | federal_signal_hkb_fpiu20 | hook kit = Valor bar mounting or pushbumper part? | see EVIDENCE.md |
| F22 | federal_signal_z865100372a | is there another Valor bar the 44" dome kit should parent to? | ✅ catalog fact: no — federal_signal_valor_ssp_package_4 is the only Valor product. ◑ 44"-kit-under-51"-package parenting → §B5 |
| F23 | night_ride NRP-SI-E vs NRP-SL-E | typo or distinct model? | see EVIDENCE.md |
| F24 | unity_189 | which spotlight does bracket #189 fit? | see EVIDENCE.md |
| F25 | unity_spotlight_2016_fpiu | confirm brand is Unity | see EVIDENCE.md |
| F26 | qb_unassigned_36_010_key | TufBox brand? | see EVIDENCE.md |
| F27 | qb_unassigned_rtm_101_lp_ford_r | Acari platform — which bar family does it carry? | see EVIDENCE.md |
| F28 | qb_unassigned_rbe13421 | air pressure switch — what system? | see EVIDENCE.md |
| F29 | american_aluminum_aaadish vs _ameralu_water | same product (mergeable) or distinct dishes? | see EVIDENCE.md |
| F30 | qb_unassigned_1019_b | real PAC Tool item or import artifact? | see EVIDENCE.md |
| F31 | qb_unassigned_rv_3xl/oversize/regular | what are the RV- items (Ray Allen?) | see EVIDENCE.md |
| F32 | qb_unassigned_bu_353n | GlobalSat BU-353N — laptop/AVL GPS or radar speed source? | see EVIDENCE.md |
| F33 | ace_k_9_ha_fkt10_p / ha_fwg_10 | which product is the heat-alarm base unit? | ✅ catalog fact: ace_k_9_hp_5020 (Hot-N-Pop Pro) + ace_k_9_ha_2520 (Heat Alarm Pro) — parents re-pointed (HA- prefix = Heat Alarm series) |
| F34 | qb_unassigned_light_kit_led | what is "LIGHT KIT-LED (RED & WHITE)" $0? | ❌ no brand, no part number, $0 — unresearchable; delete-with-question stands → §B6 |

## B. PREFERENCE questions — the owner sitting

Grouped so one pass answers everything. Items marked ◑ carry facts already gathered in §A.

### B1. Taxonomy rulings (biggest blast radius — answer these first)
1. **Scene-light collapse** (audit §3.3): collapse front/side/rear_scene → one `scene_light`
   (placement decides zone, symmetric with warning), or keep zone-split? ~30 products.
2. **Zone-named bracket collapse** (audit §3.1): fold the 6 zone-named warning-bracket types
   into `bracket`? Includes the Westin light-tubes exception (products vs accessories).
3. **control_head vs light_controller split**: officer-touched controller → `control_head`,
   trunk module → `light_controller` (feniex_c_4017 Typhoon gated on this). Agree?
4. **Havis C-EB equipment brackets** → `special_face_plate` (console-furniture convention) or
   `bracket` + accessory of the radio products? (3 products)
5. **Spotlights**: own `spotlight` part_type (proposed, 8 products) or fold into front_scene?
6. **Traffic advisors**: eventually their own part_type + arrow-pattern UI, or stay
   `warning_light`? (soundoff_enftcdxs1208, whelen_traffic_advisor precedent)
7. **Transfer-kit components**: home RP47/SP47 panels under `front_partition_transfer_kit`
   alongside the TK, or accessory-only children of it?
8. **GJ 7160-1048 storage box**: `equipment_tray` or `rear_storage_box`? (◑ see F18 evidence)
9. **ChargeGuard-Select**: `battery_tender` or `vehicle_interface`? (power-management timer)
10. **setina_pb10 workbook conflict**: pit_bar vs wing_wraps (from WORKBOOK_GRAPH, 2 true conflicts).

### B2. Catalog-scope rulings (does DTM sell/track these in the builder at all?)
1. **Trailers** (13 JB Lund products, $6–7k units) — catalog or QB-only?
2. **Snow plows** (2 SnowEx, $9.8k) — catalog-worthy for municipal truck builds?
3. **Tonneau cover** (1 BAK) — worth a part_type, or generic truck-exterior home?
4. **Computers** (Getac S410) — sold-hardware slot in catalog, or unbilled/agency-line treatment?
5. **Motorcycle boxes** (5 Whelen M4B6-family products) — does DTM sell motorcycle builds?
6. **Step bars** (Westin R5) — proposed new part_type, confirm.
7. **Services in products**: powder-coating + remote-start-labor lines — delete from parts_db
   (services stay QB-only) or keep?

### B3. Missing manufacturers — create in the SKU grid, then the re-brands apply
Streamlight (SL-20) · Pelican (8060) · Momento (M-6 dash cam) · Getac (S410) ·
BAK Industries (tonneau) · Acari (roof platform). Also confirm: **dtm ↔ 5-0 Fab identity**
(7 dtm_* products; audit §2.1) and the `specify` placeholder brand (2 antenna styles).

### B4. Consumables / service-stock keep-vs-delete (◑ facts in §A)
1. Ford front-seat bolts W709980-S439 ($5) — keep or delete as install-hardware noise?
2. Whelen H35SN12 halogen bulb (◑ F5: legacy-halogen service stock) — keep or delete?
3. National Foam 3% concentrate 5-gal pail — delete, or do fire consumables belong?
4. Whelen PFP2AP1 (◑ F3: 115 VAC pole/pedestal flood) — is this used on vehicle builds, or a
   shop/command-post sale that shouldn't be in the builder catalog?
5. Whelen 9M amber lens 68-1183491A-16 (◑ F12: legacy Micro Edge service part) — keep (where?)
   or delete?
6. RPBKR700-K15-ON-BOBX8-P1 "Radiant ECO LED lamphead" $0 — confirm configurator-artifact delete.
7. qb_unassigned_light_kit_led (◑ F34: unidentifiable, $0) — confirm delete.
8. qb_unassigned_1019_b — pending F30 evidence; if real PAC Tool part, keep + re-brand.

### B5. Parent/product-shape calls left after evidence (◑ facts in §A)
1. 2250-series endcaps (◑ F7): create a WeCanX 2250 bar product for them to parent to, or leave
   the endcaps home-only until a 2250 bar is actually sold?
2. CenCom Carbide (◑ F9): create a Carbide product so CC5K2 can parent to it, or leave the
   install kit home-only?
3. Valor 44" dome service kit (◑ F22): parent to the 51" SSP package anyway, or leave home-less
   accessory unset?
4. Havis PT-A-409 HVAC option: home under prisoner_transport_insert or accessory-only of PT-C02?
5. qb_unassigned_cctv8 monitor: parents = the two Trailblazer thermal units — right?
6. Stalker speed modules (pending F16): accessory of DSR/DSR-2X or standalone radar_display_unit?

### B6. Merge-preference calls (no facts missing — pure convention choice)
1. Water dishes: merge aaadish + ameralu_water (+ hinged twin) into one product? (◑ F29)
2. Brother PocketJet power cable: merge the plan-11 twin with brother_printer_power?
3. Ethernet 10ft/25ft: merge as SKUs of one Ethernet Cable product?
4. Feniex Fusion sticks: all sizes (200/400/600/800/Rocker) one product, or per size class?
5. feniex_fsma: merge into feniex_fusion_surface_mount as the amber SKU?
6. Valor bundle: name it "Valor SSP Package"?
7. NRP-SI-E vs NRP-SL-E merge — pending F23 evidence.

### B7. Owner-knowledge facts (only DTM knows — not researchable)
1. 5_0_fab_dtm_tube_chase — what is a "tube chase" ($75)?
2. feniex_fenflas — pending F20; if research failed, what did DTM sell as "FENIEX" $47.90?
3. qb_unassigned_rbe13421 air pressure switch — pending F28; which install used it?
