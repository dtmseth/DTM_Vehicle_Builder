# Lighthead selection for tracers & lightbars (design)

**Status:** plan locked 2026-06-23 (Seth). Tracers first; lightbars are the same engine,
deferred pending per-bar research. **Head data staged** (batch 11 real heads + batch 12
pending heads; all four Duo/Trio · White/Amber configs buildable). **Engine + Duo/Trio/Custom
UX not yet built.** Validated against Estimate 1959 — see "Observed in practice" below.

## Problem

Three overlapping inputs currently fight over the color of a multi-head light:
1. **colors-per-head** segmented control (single/duo/trio)
2. **color matrix** (uniform / split / custom swatches) — already does driver=red /
   passenger=blue + a secondary color
3. **lighthead accessory dropdown** (batch 11) — pick a specific child head SKU

For a product whose color lives entirely in **child lightheads** (tracers, and lightbars
with head children), these collapse into one decision. This design replaces #1–#3 **for
head-parent products only** with a small Duo / Trio / Custom control plus a secondary-color
selector, and auto-resolves the exact head SKUs + quantities. **Every other light keeps
today's color picker unchanged.**

## Product model

- **Housing** = the bar/tracer product SKU. Carries **no color** (e.g. `TCRWX5` =
  "WECANX TRACER 5-LAMP HOUSING"). The housing's lamp count = number of head slots.
- **Head** = a child lighthead SKU that carries the color. Two roles:
  - **Primary** — required in **slot 1** of every housing.
  - **Secondary** — fills **slots 2…N**.
  - One head per slot.
- A product is a **head-parent** when it has `lighthead`-category accessories (the
  tracer/bar housings wired in batch 11). That flag drives the picker into this mode.

## User inputs (the whole UX)

Inside the selected tracer/bar, instead of the color matrix:
- **Three pills: `Standard Duo` · `Standard Trio` · `Custom`** (Custom = multi-select
  from the full head list, free choice).
- **Secondary color selector: `White` (default) · `Amber`.** (Tracers are almost always
  on side running boards → white; amber is for rear-facing positions. A manual selector
  beats auto-deriving from placement because tracer position is entered by hand.)

That's it. Color/lens filters on the left should **not** filter tracers out of the
results (a tracer can be any color); if the left-side color selection happens to match a
standard Duo/Trio, pre-select that pill when the tracer opens.

## Resolution rules

- **Slot count = housing lamp count** (`TCRWX2/3/5/6` → 2/3/5/6).
- **Duo** head = one warning color + the secondary color. **Red = driver side, Blue =
  passenger side.**
- **Trio** head = **red + blue + secondary** in every head (no left/right split needed).
- **2-lamp** → assume **front** mount → one housing, slot 1 = driver **R**, slot 2 =
  passenger **B**.
- **3/5/6-lamp** → side running boards → **auto-generate a PAIR of housings** (driver +
  passenger), doubling the heads. Duo splits color across the pair (red housing / blue
  housing); Trio puts R/B heads in both. (Seth: "auto generate two housings and double
  light heads, split color if needed.")

### Concrete SKU mapping (tracers)

`N` = lamp count. Where a pair is generated, totals are per pair.

Clear lens shown; `TCRXX…` = smoked equivalents for smoked builds. Pending-QB heads
(batch 12) marked ⧗.

| Config | Driver housing | Passenger housing |
|---|---|---|
| **Duo · White** | `1× TCRWXPD` (R/W) + `(N-1)× TCRWXSD` | `1× TCRWXPE` (B/W) + `(N-1)× TCRWXSE` |
| **Duo · Amber** | `1× TCRWXPK` (R/A) + `(N-1)× TCRWXSK` | `1× TCRWXPM`⧗ (B/A) + `(N-1)× TCRWXSM` |
| **Trio · White** | `1× TCRWXPJC`⧗ (R/B/W) + `(N-1)× TCRWXSJC`⧗ | same |
| **Trio · Amber** | `1× TCRWXPJA`⧗ (R/B/A) + `(N-1)× TCRWXSJA`⧗ | same |
| **2-lamp front · Duo · White** | single housing: `TCRWXPD` (slot 1) + `TCRWXSE` (slot 2) | — |

All four configs are now buildable: the heads missing from QB were added as **pending-QB
parts** (batch 12, `whelen_accessories_b12_pending_tracer_heads.json`) — usable now, flagged
on the estimate. Smoked trio `TCRXXPJC` (R/B/W) is a real QB SKU (batch 11).

## Observed in practice — Estimate 1959 (Drone PIU, all-trio smoked)

Real estimate from the sales team, confirms the structure and one decision:
- **Line shape:** housing line(s) + a **separate head line, qty = total lamp positions.**
  FST `BSFW50ZT`×1 → heads `ISTBCA`×10; tracer `TCRWX5`**×2** → heads `TCRXXPJC`**×10**
  (= 2 housings × 5). Confirms the **auto-pair-of-housings** rule and **qty = lamps ×
  housings**, and that a smoked build pulls the `TCRXX…` SKUs.
- **Primary/secondary:** the estimate listed *all* heads as the **primary** SKU
  (`TCRXXPJC×10`). **Decision (Seth): the engine does the spec-correct split instead** —
  `1 primary + (N-1) secondary` per housing (cheaper; secondary heads omit the lamp
  driver). This is why batch 11 split into `whelen_tracer_wcx_primary` /
  `_secondary` products — keep both.
- **A color error slipped through:** the FST heads were quoted `B/W/A` but should have been
  `R/B/W`. Exactly the manual mistake auto-resolution prevents — motivation for this feature.
  **Confirmed Inner Edge front/rear default (Seth):** front gets white → **FST = R/B/W**;
  rear gets amber → **RST = R/B/A**. (Consistent with the general rule: front/sides → white,
  rear → amber. For tracers the secondary color stays a manual White/Amber selector.)
- **Pending-QB notation:** the sales lead confirmed the "note it in the description" method
  works for her. We keep the **DescriptionOnly** estimate note (not a placeholder-billed
  item) — matches how she already handles `MISC PART` / `INSTALL SUPPLIES` lines.

## Manifest & estimate output

- **Manifest (UI):** one **parent tracer/bar line** with the resolved heads **nested**
  under it; the parent line carries a **`Duo` / `Trio` tag** for the build sheet. (When a
  pair is generated, two parent lines — driver & passenger.)
- **Estimate:** every resolved head SKU is its own line item (qty rolled up), plus the
  housing SKU(s) — so QuickBooks sees real parts.
- **Build-sheet tag:** the parent line's Duo/Trio (+ secondary color) is the only
  user-facing summary needed on the sheet.

## Whelen color-code key (from the official Tracer WeCanX spec)

Part numbers: `TCRWX` = clear lens, `TCRXX` = smoked lens · `P` = primary (slot 1),
`S` = secondary (slots 2–6) · then the color code:
- **Solo `*`:** A=Amber, B=Blue, C=White, G=Green, R=Red
- **Duo `#`:** D=R/W, E=B/W, F=A/W, J=R/B, **K=R/A**, L=R/G, **M=B/A**, P=A/G
- **Trio `#*`:** **JA=R/B/A**, **JC=R/B/W**, KC=R/A/W, KG=R/A/G, LC=R/G/W, MC=B/A/W,
  MG=B/A/G, NC=B/G/W, PC=G/A/W

So standard **Duo** = D/E (white) or K/M (amber); standard **Trio** = **JC** (white) or
**JA** (amber).

## Data gaps → add as pending-QB parts (SKUs confirmed)

These heads are needed for full Duo·Amber and Trio coverage but aren't in DTM's QB yet.
Add via the **[pending-QB-part mechanism](PENDING_QB_PARTS.md)** (real SKU + price, no
`qb_item_id`) so they work immediately and the estimate flags them. Clear lens shown;
smoked (`TCRXX…`) variants exist if needed (`TCRXXPJC` smoked-primary R/B/W is already in
QB from batch 11).

| Role | Part # | Colors | Lens | Price |
|---|---|---|---|---|
| Duo passenger-amber, **primary** | `TCRWXPM`  | Blue/Amber       | clear | $59  |
| Trio White, **primary**          | `TCRWXPJC` | Red/Blue/White   | clear | $116 |
| Trio White, **secondary**        | `TCRWXSJC` | Red/Blue/White   | clear | $116 |
| Trio Amber, **primary**          | `TCRWXPJA` | Red/Blue/Amber   | clear | $116 |
| Trio Amber, **secondary**        | `TCRWXSJA` | Red/Blue/Amber   | clear | $116 |

(`TCRWXSM` B/A secondary, and `TCRWXSK`/`TCRWXPK` R/A, are already in QB.)

## Lightbars (deferred — same engine)

Same Duo/Trio/Custom + secondary-color model. Extra research needed per bar:
- head **count and front/rear split** per size SKU (a roof bar mixes white front heads +
  amber rear heads in one unit — secondary color may vary **by slot**, not one selector);
- whether each bar exposes **size SKUs** (user picks size, ideally auto-filtered by
  vehicle) and/or **head children**, which differs across bars.
Capture each bar's slot layout (front_count / rear_count per size) before wiring.

## Open implementation notes

- Detection: treat a product as head-parent iff it resolves `lighthead`-category
  accessories. May want an explicit `head_parent: true` + a `slot_count` source later.
- The current `split` color mode (driver red / passenger blue + secondary) is the
  building block — reuse its logic, drive it from the pills instead of the matrix.
