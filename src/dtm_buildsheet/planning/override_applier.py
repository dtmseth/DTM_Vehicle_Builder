from __future__ import annotations

import copy

from ..domain.plan_models import BuildPlan
from .layer_policy import enforced_render_layer


def apply_overrides(plan: BuildPlan, overrides: dict) -> BuildPlan:
    """Return a deep copy of *plan* with per-placement overrides applied.

    Override key format: "{line_id or part_id}:{view}".
    Supported override fields:
        visible (bool)      — False removes the placement from the plan
        rotation (float)    — replaces PlannedPlacement.rotation
        flip_h (bool)       — replaces flip_h
        flip_v (bool)       — replaces flip_v
        anchor_dx (float)   — delta added to anchor.x (relative_image units)
        anchor_dy (float)   — delta added to anchor.y (relative_image units)
        translate_dx (float)— uniform x translation applied after slot/mirror layout
        translate_dy (float)— uniform y translation applied after slot/mirror layout
        callout_dx (float)  — concealed-speaker callout x offset (relative_image units)
        callout_dy (float)  — concealed-speaker callout y offset (relative_image units)
        size_scale (float)  — multiplier applied to size_override w/h values
        size_w (float)      — absolute width  in inches (replaces size_scale)
        size_h (float)      — absolute height in inches (replaces size_scale)
        layer (int)         — Z-order layer (0 = default, positive = on top, negative = behind)

    The original plan is never mutated.
    """
    if not overrides:
        return plan

    plan_copy = copy.deepcopy(plan)

    for pp in plan_copy.planned_parts:
        kept = []
        for pl in pp.placements:
            key = f"{pl.line_id or pl.part_id}:{pl.view}"
            ov = overrides.get(key)
            if not ov:
                kept.append(pl)
                continue

            if not ov.get("visible", True):
                continue  # drop placement

            if "rotation" in ov:
                pl.rotation = float(ov["rotation"])
            if "flip_h" in ov:
                pl.flip_h = bool(ov["flip_h"])
            if "flip_v" in ov:
                pl.flip_v = bool(ov["flip_v"])

            if "anchor_dx" in ov or "anchor_dy" in ov:
                pl.anchor = dict(pl.anchor)
                pl.anchor["x"] = round(
                    float(pl.anchor.get("x", 0)) + float(ov.get("anchor_dx", 0)), 6
                )
                base_y = float(pl.anchor.get("y", 0))
                resolved_y = base_y + float(ov.get("anchor_dy", 0))
                # A vertically mirrored placement represents a pair reflected
                # about the vehicle centreline.  An off-canvas anchor therefore
                # pushes *both* instances beyond the image.  Ignore only that
                # invalid Y delta and retain the authored location position;
                # valid user adjustments continue to work unchanged.
                if pl.pattern == "vertical_mirror" and not 0.0 <= resolved_y <= 1.0:
                    resolved_y = base_y
                pl.anchor["y"] = round(resolved_y, 6)

            if "translate_dx" in ov:
                pl.translate_dx = float(ov["translate_dx"])
            if "translate_dy" in ov:
                pl.translate_dy = float(ov["translate_dy"])
            if "callout_dx" in ov:
                pl.callout_dx = float(ov["callout_dx"])
            if "callout_dy" in ov:
                pl.callout_dy = float(ov["callout_dy"])

            if "size_w" in ov or "size_h" in ov:
                # Explicit per-axis sizing from the inspector. Inputs are
                # absolute inches; preserve aspect ratio is the inspector's
                # responsibility — we just record what the user typed.
                cur = pl.size_override or {}
                new_w = float(ov.get("size_w", cur.get("w", 0))) or cur.get("w", 0)
                new_h = float(ov.get("size_h", cur.get("h", 0))) or cur.get("h", 0)
                if new_w > 0 and new_h > 0:
                    pl.size_override = {"w": round(new_w, 6), "h": round(new_h, 6)}
                    pl.size_scale = 1.0
            elif "size_scale" in ov:
                scale = float(ov["size_scale"])
                if scale > 0:
                    if pl.size_override:
                        # Scale the explicit size dict; size_scale stays 1.0 (already encoded).
                        pl.size_override = {
                            k: round(v * scale, 6) for k, v in pl.size_override.items()
                        }
                    else:
                        # No explicit size dict — store the multiplier for the renderer.
                        pl.size_scale = scale

            if "h_spacing_delta" in ov:
                base = pl.h_spacing if pl.h_spacing is not None else 0.0
                pl.h_spacing = max(round(base + float(ov["h_spacing_delta"]), 6), 0.001)

            if "layer" in ov:
                pl.layer = enforced_render_layer(pl.part_id, int(ov["layer"]))

            kept.append(pl)
        pp.placements = kept

    return plan_copy
