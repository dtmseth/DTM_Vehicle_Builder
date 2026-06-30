# Whelen: remaining unlinked SKUs (need catalog decisions)

After Phase 5b accessory wiring (batches 1–11), **47 Whelen SKUs remain unlinked**.
These were deliberately *not* wired — they aren't simple accessories of an existing
product; each bucket needs a catalog decision (a new primary product, a color-variant
lighthead family, or a judgment about parent identity). Recommendations below.

Find the live list any time with the standard query (handoff doc) — filter to
`description` starting "WHELEN" with no `qb_item_id` in parts_db.

## ~~Tracer WCX lightheads~~ — DONE (batch 11)
Wired in `whelen_accessories_b11_tracer_wcx_heads.json`: 18 concrete color SKUs split
into `whelen_tracer_wcx_primary` / `whelen_tracer_wcx_secondary` (lighthead), accessories
of all four tracer products. Only the two `#` order-code placeholders (`TCRWXP#`,
`TCRWXS#`) stay unlinked — intentional (concrete colored SKUs cover them).

## Primary products (not accessories) — need their own catalog entries
- **V2V sync modules (2):** `CV2V`, `CLBV2V` ($371) → fit the existing `v2v_sync`
  part_type. Standalone equipment, create as primary products.
- **Headlight/LED flashers (6):** `SSFPOS`, `SSFPOSI6` (solid-state headlight flasher),
  `ULF44` (universal 4-outlet), `PLF46` (programmable), `M62T` (amber turn light),
  `70RC6FCR` (700-series linear flasher). Mostly primary `headlight_flasher` /
  `tail_light_flasher` items. `70RC6FCR`/`FSBPS` *could* instead be `flasher_power`
  accessories of whelen_700_series / whelen_field_series — confirm which.
- **Power supply (1):** `FSBPS` — Field Series power supply (see above).
- **Switch/control + options (misc):** `PCC6W` (switch control center), `LCPHOTO`
  (photocell), `LINZ6R` (LINZ6 light), `H35SN12` (halo bulb), `SYS109` ($3460 system),
  `PFP2AP1` ($2568 pole/ped mount), `68-1183491A16` (Freedom Micro Edge lens).

## Lighthead families
- **DUO low-profile lamps (2):** `BWD#`, `BWP#` — driver/passenger 6-LED DUO lamps,
  `#`-placeholder order codes ($0). Color-variant lightheads; model like Tracer WCX heads.
- **`BW54UFX`** ($2254) — a full WCX Duo Inner-Edge 12-lamp assembly for 2021 Tahoe
  (a built unit, likely a configured product not a part).

## Motorcycle box system (6)
`M1BATT`, `M1GROUND`, `M4B6CHRG`, `M4B6LR` ($1768), `M4BSEP`, `MBADPT14` — Whelen
motorcycle battery-box system + Harley adapter. Specialized; own product family if DTM
sells motorcycle builds, else leave unlinked.

## QuickFit roof platforms (5)
`QFFORD1` / `QFFORD1S` / `QFFORD1W` (Ford) and `QFRAM2` / `QFRAM2S` (Ram) — roof-mount
platforms for lightbars ($488). **Could** be wired as a `bracket_mount` accessory of the
full-size roof bars (like `whelen_lightbar_mount_kit`), but the S/W variant meanings are
unclear — resolve the finish/version suffixes before wiring.

## Legacy lightbar options (8)
`ES2ME`/`ES8ME` (Midnight Edition 48"/54"), `GB2X`/`GB8X` (smoked lens kits),
`GBAWD`/`GBAWE` (add warn/alley module R/W, B/W), `22LECA`/`22RECA` (angled endcaps).
Config add-ons for the Legacy bar — some are accessories (lens kit, endcap), some are
light modules. Wire as Legacy accessories once the category per SKU is decided.

## Sub-assemblies / final assemblies (3) — probably not catalog parts
`01-0244499-23`/`-53` (alley-warning sub-assemblies), `01-086A664-00` (final Howler
siren assembly). Build/BOM artifacts, likely excluded from the picker.

## Flagged singletons (parent not identifiable)
- `FSBBB` ($0) — bail bracket "per FSB light array"; no clear FSB product.
- `SP123BMC` ($497) — chrome bumper mount; no clear parent.
- `HWLFE29` ($756) — siren amp+speaker that *includes* a bracket; it's an amp assembly,
  belongs with siren amplifiers, not as a bracket accessory.
- `CC5K2` ($0) — install kit for CCSRN5 (CenCom siren) — wire once CCSRN5 is modeled.
