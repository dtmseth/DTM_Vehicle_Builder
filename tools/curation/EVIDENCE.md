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
