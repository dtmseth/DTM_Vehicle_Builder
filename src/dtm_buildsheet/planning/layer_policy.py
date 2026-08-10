"""Rendering-layer invariants shared by planner and placement overrides."""
from __future__ import annotations


# The inspector only permits -10 through +10.  Reserve lower values for the
# physical bumper assembly so an authored or dragged light always remains in
# front of it, while the frame itself is beneath its attached components.
_BUMPER_LAYER_CEILINGS: dict[str, int] = {
    "push_bumper": -20,
    "pit_bar": -15,
    "wing_wraps": -15,
}


def enforced_render_layer(part_id: str, requested_layer: int = 0) -> int:
    """Return the layer after applying non-negotiable bumper stacking rules."""
    requested = int(requested_layer)
    ceiling = _BUMPER_LAYER_CEILINGS.get(part_id)
    return min(requested, ceiling) if ceiling is not None else requested
