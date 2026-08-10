# Curation evidence log

Evidence session 2026-07-07. Each entry: part id → what was learned → source. F-numbers
cross-reference `OPEN_QUESTIONS.md` §A. Prices cited from the source were checked against the
QB unit price on the product's SKU (exact matches noted — strong identity confirmation).

Rules honored: nothing recorded here was inferred beyond what the source states; inconclusive
research is marked as such and the plan entry stays flagged.

---

## Whelen batch (PL26 = docs/reference/WHELEN_PRICE_LIST_PL26.md, parsed official price list)

- **whelen_sys109** (F2) — SYS109 = "Super-LED Systems #109: Two Stainless Steel Micro 400 with
  60' TPR Cable, LED Flasher/Junction Box and Install Kit", $3,460 (exact QB match). A complete
  hideaway warning system sold as one item. → home `warning_light` + light tag, confidence ↑.
  Source: PL26 "Super-LED Systems" section.

- **whelen_pfp2ap1** (F3) — PFP2AP1 = "Dual Panel Pioneer Plus, 115 VAC, with Pole/Pedestal
  Mount Adapter and On/Off Switch", $2,568 (exact QB match). Mains-powered pole/pedestal scene
  floodlight. Identity resolved; catalog-scope call (115 VAC ≠ vehicle 12V) → OPEN_QUESTIONS B4.4.
  Source: PL26 Pioneer Plus options section.

- **whelen_sp123bmc** (F1) — SP123BM Series = "Bumper Mount Speaker"; SP123BMC = "Bumper Mount,
  Chrome", $497 (exact QB match), listed under "Siren Speakers, SA315 & SA314 Projector Series —
  100-Watt Bumper/Concealed/Flange Mounted Speakers". It IS a 100W siren speaker, not a mount
  for something else. → re-homed `bracket` → `siren_speaker`, confidence ↑ high.
  Source: PL26 siren-speakers section.

- **whelen_m62t** (F4) — M62T = "LED, Turn Light Amber, with Multiple Flash Patterns, including
  Arrow Pattern, 10-30 VDC", $183 (exact QB match), in the M6-series surface-mount family next
  to M62BTT (brake/tail/turn) and M62BU (back-up). Standalone M6 lighthead variant, not a
  Traffic Advisor element. → merged as SKU of `whelen_m6`, confidence ↑ high.
  Source: PL26 M6/M7 series surface-mount section.

- **whelen_h35sn12** (F5) — H35SN12 = "35 Watt (White Dot) snap-in halogen bulb — 4000
  Motor/Reflector Assembly/Brushless, 52 Series, DOT3 Systems, Edge California Steady-Burn,
  RDX Series", $65 list. Replacement bulb for legacy halogen products (none are catalog
  products) — consumable service stock. Keep-vs-delete → OPEN_QUESTIONS B4.2.
  Source: PL26 "Snap-In Bulbs" service section.

- **whelen_qfford1 / qfford1s / qfford1w / qfram2 / qfram2s** (F6) — QuickFit Bolt-On Mounting
  Platform Series: "Black or White Powder-Coated Steel or Aluminum Housing. For use with Whelen
  Beacons, Responder LP/HD's, Mini Century, Mini Liberty II and Mini Legacy. (Mini Liberty II
  and Mini Legacy Requires MK9S Mounting.)" Suffix decode: blank = black **aluminum** housing
  ("Not for Use with Magnetic Mount Lights"), **S** = black **steel** ("Will work with Magnetic
  Mount Lights"), **W** = white aluminum, **SW** = white steel. QFFORD1* = Ford F-150
  PPV/Lightning, F-250–F-600, 2015-2025; QFRAM2* = Ram 1500 Classic 2019-2025 + RAM 2500/3500
  2022-2025. All $488 (exact QB matches). Parents corrected: mini bars/beacons in catalog
  (whelen_r416_beacon, whelen_responder_lp, whelen_century, whelen_mini_legacy) — NOT full-size
  Legacy/Liberty/Freedom. Source: PL26 QuickFit section (printed p.39-40).

- **whelen_22leca / whelen_22reca** (F7) — "One Angled Left/Right End Cap for use with One
  Aerial Recognition Light, for Bars 30\" to 50\"", $144 each (exact QB match), listed under
  "Options for 2250 Lightbars" in the **WeCanX 2250 Series Super-LED Surface Mount Lightbars /
  Build-A-Bar** section (WX2250…WX2270 models). '22' prefix = 2250 Series, NOT Legacy. No
  2250-series bar product exists in the catalog → former accessory-of-whelen_legacy links
  removed; parenting decision → OPEN_QUESTIONS B5.1. Source: PL26 2250 section.

- **whelen_lcphoto** (F8) — LCPHOTO = "Logic Level Photocell for use with SLFLASH, CenCom
  Core, CenCom Sapphire, CenCom Carbide and CanTrol", $128. A control-system option, not a
  lightbar option. → re-parented whelen_legacy → whelen_core (CenCom Core — the only compatible
  catalog product), confidence ↑ high. Source: PL26 Flashers section.

- **whelen_cc5k2** (F9) — CCSRN5 = **CenCom Carbide** siren & light controller (CCSRN-5).
  The catalog has no Carbide product (only whelen_core = CenCom Core), so the Chevy install
  kit stays home-only `bracket`; create-Carbide-product decision → OPEN_QUESTIONS B5.2.
  Sources: https://www.whelen.com/product/cencom-carbide/ ;
  https://danasafetysupply.com/whelen-cencom-carbide-ccsrn-5-siren-and-light-controller-with-canport-obdii-interface/

- **whelen_linz_v_series ← whelen_linz6r merge** (F10) — PL26 section header "LINZ6 & LINV2
  V-Series Linear Super-LED Lightheads" (+ TOC "Options for TIR3, LIN3, LINZ6 & LINV2
  V-Series") — LINZ6 is a V-Series linear lighthead model; same family. Merge confidence ↑ high.
  Source: PL26 lighthead sections.

- **whelen_bw54ufx** (F11) — BW54UFX = "Chevy Tahoe PPV/SSV, 2021-2026, Chevy Suburban
  2024-2026, Twelve 6-LED DUO Lamps, Upper Front Two Piece Unit, Individual Driver and
  Passenger Side Units", $2,254 (exact QB match), in the **Inner Edge XLP Extra Low-Profile**
  DUO+ Upper Front series. A real orderable vehicle-fitment model, NOT a configured-order BOM
  artifact — delete proposal reversed; merged as SKU of whelen_xlp. Source: PL26 Inner Edge
  XLP section.

- **whelen_68_1183491a16** (F12, PARTIAL) — the 68-1183491A·· part-number family is Whelen's
  9M/Edge-9000-series replacement lens line (Zip's sells 68-1183491A02B as "Whelen 9M Series
  Lens – Amber"). That matches a legacy *Micro Edge* bar (Edge-9000 derivative), NOT the Micro
  Freedom (whelen_freedom) the plan had guessed — accessory link removed. No Micro Edge product
  exists in the catalog; exact -A16 variant not independently confirmed → stays flagged
  (OPEN_QUESTIONS B4.5). Source: https://zips.com/parts-detail/whelen-9m-series-lens-amber-68-1183491a02b

- **qb_unassigned_eluc3h010e** (F13) — ELUC3H010E is a **SoundOff Signal** part: Universal
  UnderCover LED Insert single-light kit — screw-in hideaway insert (6 Gen-3 LEDs) with Lens #1
  (extreme angle), inline dual-color flasher, blue/white, 10' 5-wire harness, 9-32 VDC;
  retrofits 1" strobe-tube cutouts in headlight/taillight housings. Standalone hideaway kit,
  not a bar child. → merge re-brands to soundoff, home `warning_light` + light tag, confidence
  ↑ high. Sources: https://www.soundoffsignal.com/s/product/universal-undercover-led-insert/01t5f0000044tBPAAY ;
  https://www.mallory.com/2762569/product/soundoff-signal-eluc3h010e ("SOI UNIV UNDERCOVER LED
  INSERT, 5 WIRE BLUE/WHITE")

## Catalog-fact resolutions (live parts_db reads, no writes)

- **ace_k_9_ha_fkt10_p / ace_k_9_ha_fwg_10** (F33) — the heat-alarm base units ARE in the
  catalog: `ace_k_9_hp_5020` (HOT-N-POP PRO temperature alarm & door popper) and
  `ace_k_9_ha_2520` (HEAT ALARM PRO temperature alarm system), both homed
  k9_heat_alarm_popper. The HA- prefix on the fan kit / fan guard matches the Heat Alarm
  series. Parents re-pointed from the ace_k_9_ace_k_9 faceplate (which is a Gamber-Johnson
  console faceplate, wrong parent) to the two alarm systems.

- **federal_signal_z865100372a** (F22) — catalog fact: federal_signal_valor_ssp_package_4 is
  the only Valor product in the DB; there is no separate 44" Valor bar. Parenting the 44" dome
  service kit under the 51" package → OPEN_QUESTIONS B5.3.

## Non-Whelen batch (web research, 2026-07-07)

- **stalker_200_0243_00** (F15) — "Counting Unit Mount – Tall": mounts the counting (display)
  unit to the dashboard, velcro + 2 thumbscrews, compatible DSR / DSR 2X / DUAL / PATROL.
  Generic display-side bracket → multi-homed front+rear radar antenna mount (bracket precedent),
  confidence ↑ high. Source: https://stalkerradar.com/product/counting-unit-mount-tall/

- **stalker_200_1503_00 / _11** (F16) — Stalker Speed Module (internal / external GPS,
  Ka-band): GPS + inertial patrol-speed source for DSR/DSR 2X moving radar, replacing
  VSS/OBD-II speed feeds. Sold as a radar accessory (own product pages under Speed Module
  category) — per-radar component, accessory role confirmed, confidence ↑ high.
  Sources: https://stalkerradar.com/product/speed-module-with-internal-gps-ka-band/ ;
  https://stalkerradar.com/product/speed-module-with-external-gps-ka-band/

- **gamber_johnson_7160_0826** (F17) — GJ's own catalog name is "Adjustable Mic Clip" ($55):
  mounts a handheld mic at adjustable heights, over/away from radios. QB's "ADJUSTABLE MAG
  CLIP" is a MIC typo. → radio_mic_clip, confidence ↑ high.
  Sources: https://www.gamberjohnson.com/products/adjustable-mic-clip ;
  https://www.barcodegiant.com/gamber-johnson/part-7160-0826.htm

- **gamber_johnson_7160_1048** (F18) — "Equipment Storage Box for Electronics": 18"H × 38"W
  lockable, vented steel enclosure that mounts to the cargo partition; houses routers, mobile
  DVRs, radio controllers; removable equipment tray + cable knockouts. The trunk electronics
  enclosure, not cargo storage → equipment_tray, confidence ↑ high.
  Sources: https://www.gamberjohnson.com/product/7160-1048/ ;
  https://danasafetysupply.com/gamber-johnson-7160-1048-storage-box-for-electronic-equipment-in-suvs-18h-x-38w-x-6d/

- **feniex_fml** (F19) — Fusion Mini is sold under Feniex's "Mini Lightbars" category (12"/14",
  magnet mount standard, permanent bracket optional); dash/deck products are the separate
  Fusion Interior line. → roof mini bar, roof_light_bar confirmed, confidence ↑ high.
  Sources: https://www.feniex.com/minilightbars-police/p-Fusion-Mini ;
  https://feniex.com/brackets/Fusion_Mini_Lightbar_Mounts

- **feniex_fenflas** (F20, LEAD ONLY — stays flagged) — no product named FENFLAS exists on
  feniex.com. Feniex sells exactly one flasher: the 4X Flasher H-2220 (4-output, $59.99 MSRP —
  QB's $47.90 is plausible dealer cost), and "FENFLAS" reads as FENiex FLASher. Owner
  confirmation required before homing. Sources: https://www.feniex.com/flasher ;
  https://ultrabrightlightz.com/products/feniex-4-output-flasher

- **federal_signal_hkb_fpiu20** (F21) — Federal Signal hook-mount guide lists HKB-FPIU20 as
  the roof hook kit for 44/45/46/51/53" full-size light bars (incl. Valor) on the 2020-2021
  Ford Police Interceptor Utility. Lightbar mounting confirmed (not pushbumper), Valor parent
  upheld, confidence ↑ high. Sources: https://www.fedsig.com/hook-mount-reference-guide/ ;
  https://www.magnumelectronics.com/shop/hkb-fpiu20-hp-federal-signal-hkb-fpiu20-hp-hook-mount-kit-2020-ford-interceptor-utility-131717

- **federal_signal_z865100372a** (F22, PARTIAL) — Z8651003-72A = "KIT, VALR44 DOME SERVICE",
  a Valor 44"-bar replacement-dome kit (Federal Signal dome-service-kit manual 25500083 covers
  the Valor/Integrity kit family). Catalog has only the 51" SSP package; whether the 44" kit
  fits the 51" bar is unconfirmed → parenting stays an owner call (B5.3).
  Sources: https://wfgear.com/p-20272-federal-signal-z865100372a-kitvalr44-dome-service.aspx ;
  https://www.fedsig.com/sites/default/files/resource_library_document/Valor%20and%20Integrity%20Light%20Bar%20Dome%20Service%20Kit%20Manual%20%2025500083.pdf

- **night_ride_nrp_si_e** (F23) — NightRide's complete camera catalog lists every
  Trailblazer/Pro-SL SKU; there is NO SI model. NRP-SL-E ("Pro-SL S04 (Ring) 384 w/ Ethernet")
  is the real part; NRP-SI-E (same $2,394, near-identical description) is a QB typo twin.
  Merge upheld, confidence ↑ high. Source: https://getnightride.com/collections/nightride-cameras

- **unity_189** (F24) — Unity 189 = post-mount spotlight installation kit (bracket, gasket,
  fasteners, trim, drill bushing, template), ordered per vehicle year/make/model (e.g. 189 =
  2009-14 Dodge RAM driver side; 189RH = passenger). Generic to Unity post-mount spotlights →
  parents = the Unity spotlight products, confidence ↑ high.
  Sources: https://www.unityusa.com/189-Installation-Kit_p_786.html ;
  https://www.amazon.com/Unity-189-Post-Mount-Spotlight-Installation/dp/B002HVETZW

- **qb_unassigned_211020_0002 → unity_spotlight_2016_fpiu** (F25) — brand CONFIRMED Unity:
  unityusa.com lists 211020-0002 as "Halogen 6\" Spotlight Black (325)(S04) LH" — 325-series 6"
  halogen post-mount spotlight, S04 shell, driver side, 3000 lm, 12V. Confidence ↑ high.
  Source: https://www.unityusa.com/211020-0002-Halogen-6-Spotlight-Black-325-S04-LH_p_1702.html

- **qb_unassigned_36_010_key** (F26) — brand = **Tufloc**: TufBox 36-010 welded-steel SUV
  security cargo drawer, 12"H × 38"W × 32"D (exact QB dimension match), key/combination or
  T-handle lock, 12-ga steel. rear_storage_box confirmed; Tufloc manufacturer must be created
  before re-brand (B3). Sources: https://tufloc.com/product/security-drawers-for-suvs/ ;
  https://danasafetysupply.com/Tufloc/Tufloc+TufBox+WeldedSteel+Cargo+Drawer+36010+for+SUVs+38x32x12+CombinationKey+Lock+or+THandle+Lock+Optional+Riser+Base

- **qb_unassigned_rtm_101_lp_ford_r** (F27) — ACARI RTM-101-LP: drill-free 22" low-profile
  roof mounting platform (clamps through third-brake-light opening, ~1.15" profile, 210 sq-in,
  30-lb capacity) for warning lights, antennas and work lights — generic-fit, no single bar
  family → home-only bracket, no accessory parent. -R = Ranger fitment (Acari 2019-Ranger
  install guide). Acari manufacturer must be created before re-brand (B3).
  Sources: https://acariproducts.com/products/ ;
  https://www.magnumelectronics.com/shop/product/rtm-101-lp-ford-acari-drill-free-low-profile-roof-mount-ford-aluminum-123897

- **qb_unassigned_rbe13421** (F28, INCONCLUSIVE — stays flagged) — no exact RBE13421 part
  found. Lead: WABCO air-brake low-pressure switch RBE13241 (fleetpride.com) — possible digit
  transposition. Which DTM install used it remains owner knowledge (B7.3).
  Source: https://www.fleetpride.com/parts/wabco-air-system-pressure-switch-rbe13241

- **american_aluminum_aaadish / ameralu_water / hinged_water_dish** (F29) — American Aluminum
  sells ONE 1-gallon spill-proof dish line: the E/Z Spill-Proof Water Dish (bracket-mounted,
  compatible with all their K-9 transport systems); the AAADISH QB description itself
  enumerates "(UNIVERSAL, HINGED, OR PERMANENT MOUNT)" — mount variants of one product →
  merged into american_aluminum_water_dish. Sources:
  https://ezrideronline.com/products/k9/ez-spill-proof-water-dish/ ;
  https://www.rayallen.com/american-aluminum-e-z-spill-proof-water-dish/

- **qb_unassigned_1019_b** (F30) — 1019-B is a REAL PAC Tool part: Universal Hanger model
  1019, -B = black variant (PAC's suffix convention, cf. 1004-B HandleLok). Weather/UV-proof
  non-conductive hanger for cords/ropes/chains/tools, flat-surface or PAC TRAC mounting.
  Removed from plan-10 delete list → re-branded pac_tool + tool_mount home in plan 11.
  Sources: https://pactoolmounts.com/products/universal-hanger-1019/ ;
  https://firepenny.com/PAC_Tool_Universal_Hanger_p/PAC-1019.htm

- **qb_unassigned_rv_regular / rv_oversize / rv_3xl_red_fire** (F31) — the RV- items are
  **Fire Ninja "UltraBright Red" Fire/Public Safety vests** — Fire Ninja's SKU pattern is
  exactly RV-<SIZE> (vendor listing URL ends /RV-SMALL), and Fire Ninja is already a DTM QB
  vendor with catalog manufacturer fireninja_safety_equipment. RV-REGULAR/OVERSIZE ($49.99) +
  RV-3XL RED FIRE ($52.99) = size SKUs of one vest → merged into
  fireninja_ultrabright_red_vest (homeless; apparel-scope question B4). NOT Ray Allen.
  Sources: https://ipp-ips.com/FIRENINJA-UltraBright-Red-Fire-Public-Safety-Vest/RV-SMALL ;
  https://firesafetyusa.com/products/ultrabright-red-fire-safety-vest

- **qb_unassigned_bu_353n** (F32) — GlobalSat BU-353N: USB GNSS receiver (75-channel
  GPS/GLONASS/Galileo/BeiDou, patch antenna, 5' USB cable), presents a virtual COM port for
  NMEA mapping software on a laptop/PC. Laptop AVL/mapping gear, not a radar speed source →
  cloud_antenna + re-brand to existing `globesat` manufacturer, confidence ↑ high.
  Sources: https://www.globalsat.com.tw/en/a4-11222/BU-353N.html ;
  https://www.gpscity.com/us-globalsat-bu-353n-usb-high-sensitivity-gps-receiver

- **qb_unassigned_pel2b** (F14 — resolved after all) — PEL2B = **Whelen Perimeter Enhancement
  Light**, black flange: WHITE steady LED, projected downward 40° for ground illumination,
  NFPA 1901 rear-ground-lighting certified, 10-30 VDC. White-only ground lighting → SCENE per
  the color rule (former warning_light guess corrected); re-branded whelen + multi-homed
  front/rear/side_scene like whelen_ez_scene. Sources:
  https://www.whelen.com/scene-lighting/perimeter-enhancement-light ;
  https://sirennet.com/whelen-perimeter-enhancement-light-pel-steady-black-flange-white-led.html
