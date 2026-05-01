from __future__ import annotations

import copy

from ..domain.plan_models import BuildPlan


def apply_overrides(plan: BuildPlan, overrides: dict) -> BuildPlan:
    """Return a deep copy of *plan* with per-placement overrides applied.

    Override key format: "{part_id}:{view}".
    Supported override fields:
        visible (bool)      — False removes the placement from the plan
        rotation (float)    — replaces PlannedPlacement.rotation
        flip_h (bool)       — replaces flip_h
        flip_v (bool)       — replaces flip_v
        anchor_dx (float)   — delta added to anchor.x (relative_image units)
        anchor_dy (float)   — delta added to anchor.y (relative_image units)
        size_scale (float)  — multiplier applied to size_override w/h values

    The original plan is never mutated.
    """
    if not overrides:
        return plan

    plan_copy = copy.deepcopy(plan)

    for pp in plan_copy.planned_parts:
        kept = []
        for pl in pp.placements:
            key = f"{pl.part_id}:{pl.view}"
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
                pl.anchor["y"] = round(
                    float(pl.anchor.get("y", 0)) + float(ov.get("anchor_dy", 0)), 6
                )

            if "size_scale" in ov:
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

            kept.append(pl)
        pp.placements = kept

    return plan_copy
