# Lighthead selection for tracers & lightbars (design)

**Status:** plan locked 2026-06-23 (Seth). Tracers first; lightbars are the same engine,
deferred pending per-bar research. Not yet implemented.

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

| Config | Driver housing | Passenger housing |
|---|---|---|
| **Duo · White** | `1× TCRWXPD` (R/W) + `(N-1)× TCRWXSD` | `1× TCRWXPE` (B/W) + `(N-1)× TCRWXSE` |
| **Duo · Amber** | `1× TCRWXPK` (R/A) + `(N-1)× TCRWXSK` | ⚠️ `1× <B/A primary — MISSING>` + `(N-1)× TCRWXSM` |
| **Trio · White** | `1× <R/B/W primary> + (N-1)× <R/B/W secondary>` | same | 
| **Trio · Amber** | `1× <R/B/A primary> + (N-1)× <R/B/A secondary>` | same |
| **2-lamp front · Duo · White** | single housing: `TCRWXPD` (slot 1) + `TCRWXSE` (slot 2) | — |

**Only Duo·White (and Duo·Amber driver) is fully buildable from QB today.** The rest
depend on heads that don't exist in QuickBooks yet — see "Data gaps" below.

## Manifest & estimate output

- **Manifest (UI):** one **parent tracer/bar line** with the resolved heads **nested**
  under it; the parent line carries a **`Duo` / `Trio` tag** for the build sheet. (When a
  pair is generated, two parent lines — driver & passenger.)
- **Estimate:** every resolved head SKU is its own line item (qty rolled up), plus the
  housing SKU(s) — so QuickBooks sees real parts.
- **Build-sheet tag:** the parent line's Duo/Trio (+ secondary color) is the only
  user-facing summary needed on the sheet.

## Data gaps (block Trio and passenger-side Amber)

QuickBooks is missing these logical heads; the standard Trio is **R/B/W** but only the
smoked primary (`TCRXXPJC`) exists:
- Primary **Blue/Amber** duo head (secondary `TCRWXSM` exists; no primary)
- **R/B/W trio:** clear primary, clear secondary, smoked secondary (only smoked primary
  `TCRXXPJC` exists)
- **R/B/A trio** (amber): primary + secondary, clear + smoked

These are added via the **[pending-QB-part mechanism](PENDING_QB_PARTS.md)** so Trio/Amber
work immediately and the estimate flags the missing SKUs for the QB user to resolve.
Exact Whelen part numbers TBD — Seth to supply or pull from Whelen spec sheets.

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
