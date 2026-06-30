# Whelen placeholders needing more info

Products kept in `parts_db.json` that have **no QuickBooks match** and need a real
SKU / price / description added later. They will not surface a price on a build
sheet until linked. Source of truth: Whelen Auto List PL26.0WL + DTM QBO.

## Real products, not in DTM's QuickBooks (keep, add SKU when stocked)

| Product ID | Name | Notes |
|---|---|---|
| `whelen_9x_edge` | Edge 9X | Current product (PDF: "Edge® 9X Series WeCanX DUO"). No QB SKU on hand. |
| `whelen_cctl8` | CCTL8 | CCTL5/6/7/9 are in QB; CCTL8 specifically is not. |
| `whelen_intersectors` | Intersectors | Whelen Intersector. **Not in the 2026 price list** — verify still current / discontinued. |
| `whelen_cenator` | Cenator | **Not in the 2026 price list** — likely discontinued. Confirm before keeping. |
| `whelen_lc_howler` | LC Howler | Older Howler variant; **not in 2026 list**. WCX Howler (`whelen_wcx_howler`) is the current one. |
| `whelen_wc_howler` | WC Howler | Older Howler variant; **not in 2026 list**. |

## Ambiguous — needs a specific call

| Product ID | Name | Question |
|---|---|---|
| `whelen_core_control_head` | Core Control Head | Placement is `special_face_plate`, but the WeCanX control heads (`CCTL5/6/7/9`) use `control_head`. Is this a duplicate of one of those, a faceplate accessory, or its own thing? Not deleted pending your call. |

## Deferred to Phase 5 (accessories)

These are mounts/brackets, not standalone products. They become accessories
selectable within a parent product's dropdown:

- `whelen_arges_w_versatile_bail_bracket` — Arges bail bracket
- `whelen_light_bar_mount` — QB `RMKEZ85` (Whelen lightbar replacement mount kit) is a candidate link
- `whelen_tracer_l_brackets_x2_per` — Tracer L-brackets
- `whelen_rear_view_mirror_plastic` — QB `AVBKT2` (dual rear-view-mirror mount kit) is a candidate link
