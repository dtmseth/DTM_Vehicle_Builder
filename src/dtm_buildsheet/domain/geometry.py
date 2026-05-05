"""Placement geometry: slot role assignment and normalized position computation.

All positions are expressed in normalized image coordinates — fractions of the
vehicle image width (x) and height (y), where (0, 0) is the top-left corner.
Renderers are responsible for converting these to their own coordinate space.
"""
from __future__ import annotations


def view_side_role(view_config: dict, direction: str) -> str:
    """Return the slot role name for a horizontal direction in a view."""
    return view_config.get("side_roles", {}).get(direction, "center")


def slot_roles(
    pattern: str,
    slot_count: int,
    view_config: dict,
    forced_side: str = "",
    uniform_color: bool = False,
) -> list[str]:
    """Assign a slot role to each slot in a placement.

    Args:
        pattern: "single" | "horizontal" | "vertical" | "mirror"
        slot_count: number of slots
        view_config: view configuration dict (provides side_roles and default_slot_role)
        forced_side: if set, all slots collapse to this single role
        uniform_color: if True, all slots get the "uniform" sentinel role so
                       the color profile's "default" token is used for every slot

    Returns:
        List of role strings, one per slot.
    """
    if uniform_color and slot_count > 1:
        return ["uniform"] * slot_count

    if slot_count <= 1 or pattern == "single":
        if forced_side:
            return [forced_side]
        return [view_config.get("default_slot_role", "center")]

    if pattern == "mirror":
        if slot_count == 2:
            return [
                view_side_role(view_config, "negative_x"),
                view_side_role(view_config, "positive_x"),
            ]
        roles: list[str] = []
        half = slot_count // 2
        roles.extend([view_side_role(view_config, "negative_x")] * half)
        roles.extend([view_side_role(view_config, "positive_x")] * half)
        return roles

    if pattern == "horizontal":
        roles = []
        middle_left = (slot_count - 1) / 2
        for i in range(slot_count):
            if i < middle_left:
                roles.append(view_side_role(view_config, "negative_x"))
            elif i > middle_left:
                roles.append(view_side_role(view_config, "positive_x"))
            else:
                roles.append("center")
        return roles

    # "vertical" and unknown patterns
    return [f"slot_{i + 1}" for i in range(slot_count)]


def slot_relative_positions(
    pattern: str,
    slot_count: int,
    anchor_x: float,
    anchor_y: float,
    h_spacing: float,
    v_spacing: float | None = None,
    slot_roles_list: list[str] | None = None,
) -> list[tuple[float, float]]:
    """Compute normalized slot positions relative to the vehicle image.

    Args:
        pattern: "single" | "horizontal" | "vertical" | "mirror"
        slot_count: number of slots to position
        anchor_x: horizontal anchor as fraction of image width (0–1)
        anchor_y: vertical anchor as fraction of image height (0–1)
        h_spacing: gap between horizontal slots, as fraction of image width
        v_spacing: gap between vertical slots, as fraction of image height;
                   defaults to h_spacing when None
        slot_roles_list: slot roles; used only when a single-slot mirror
                         placement must be placed on a specific side

    Returns:
        List of (x, y) tuples in normalized image coordinates, one per slot.
    """
    # ── Single / degenerate case ─────────────────────────────────────────────
    if slot_count <= 1 or pattern == "single":
        if pattern == "mirror" and slot_roles_list:
            center = 0.5
            offset = abs(anchor_x - center)
            role = slot_roles_list[0]
            if role in ("passenger", "negative_x"):
                return [(center - offset, anchor_y)]
            if role in ("driver", "positive_x"):
                return [(center + offset, anchor_y)]
        return [(anchor_x, anchor_y)]

    # ── Horizontal ──────────────────────────────────────────────────────────
    if pattern == "horizontal":
        total_w = h_spacing * (slot_count - 1)
        start_x = anchor_x - total_w / 2
        return [(start_x + i * h_spacing, anchor_y) for i in range(slot_count)]

    # ── Vertical ────────────────────────────────────────────────────────────
    if pattern == "vertical":
        sv = v_spacing if v_spacing is not None else h_spacing
        total_h = sv * (slot_count - 1)
        start_y = anchor_y - total_h / 2
        return [(anchor_x, start_y + i * sv) for i in range(slot_count)]

    # ── Mirror ───────────────────────────────────────────────────────────────
    if pattern == "mirror":
        center = 0.5
        offset = abs(anchor_x - center)
        # When the anchor is at center (e.g. a co_part_rule forced pattern=mirror
        # on a location whose x=0.5), fall back to h_spacing/2 so slots don't overlap.
        if offset < 0.001 and h_spacing:
            offset = h_spacing / 2
        if slot_count == 2:
            return [(center - offset, anchor_y), (center + offset, anchor_y)]
        half = slot_count // 2
        positions: list[tuple[float, float]] = []
        for i in range(half):
            o = offset + i * h_spacing
            positions.append((center - o, anchor_y))
            positions.append((center + o, anchor_y))
        return positions

    return [(anchor_x, anchor_y)]
