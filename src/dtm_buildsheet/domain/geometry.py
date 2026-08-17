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
        pattern: "single" | "horizontal" | "vertical" | "mirror" |
            "vertical_mirror" |
            "inner_edge_front" | "inner_edge_front_driver" |
            "inner_edge_front_passenger" | "inner_edge_rear" |
            "outer_edge_pillars"
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

    # Inner Edge Duo assemblies always split red/secondary on the driver
    # side and blue/secondary on the passenger side.  Explicit role lists
    # keep an odd assembly's extra head on the driver side rather than turning
    # it into the generic center/R+B icon.
    if pattern == "inner_edge_front_driver":
        return ["driver"] * slot_count
    if pattern == "inner_edge_front_passenger":
        return ["passenger"] * slot_count
    if pattern == "inner_edge_rear":
        driver_count = (slot_count + 1) // 2
        return ["driver"] * driver_count + ["passenger"] * (slot_count - driver_count)
    if pattern == "inner_edge_front":
        passenger_count = slot_count // 2
        return ["passenger"] * passenger_count + ["driver"] * (slot_count - passenger_count)

    # Outer Edge assemblies are two physical three-head stacks.  Every head
    # in one stack carries its side's color assignment: three red/secondary
    # and three blue/secondary heads for a Duo assembly.
    if pattern == "outer_edge_pillars":
        negative_count = (slot_count + 1) // 2
        return (
            [view_side_role(view_config, "negative_x")] * negative_count
            + [view_side_role(view_config, "positive_x")] * (slot_count - negative_count)
        )

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

    # Vertical patterns (including vertical_mirror) deliberately retain their
    # positional roles: upper/lower locations can need distinct colors.
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
        pattern: "single" | "horizontal" | "vertical" | "mirror" |
            "vertical_mirror" |
            "inner_edge_front" | "inner_edge_front_driver" |
            "inner_edge_front_passenger" | "inner_edge_rear" |
            "outer_edge_pillars"
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

    # RST is one contiguous rear-window row. FST is two visor-width groups
    # separated by a small center gap, or one group when only one module is
    # installed. The additional gap is expressed in the existing icon-width
    # spacing unit, keeping preview and PowerPoint geometry identical.
    if pattern == "inner_edge_rear":
        total_w = h_spacing * (slot_count - 1)
        start_x = anchor_x - total_w / 2
        return [(start_x + i * h_spacing, anchor_y) for i in range(slot_count)]

    if pattern in ("inner_edge_front", "inner_edge_front_driver", "inner_edge_front_passenger"):
        group_gap = h_spacing * 2.5
        if pattern == "inner_edge_front_driver":
            start_x = anchor_x + group_gap / 2
            return [(start_x + i * h_spacing, anchor_y) for i in range(slot_count)]
        if pattern == "inner_edge_front_passenger":
            start_x = anchor_x - group_gap / 2 - h_spacing * (slot_count - 1)
            return [(start_x + i * h_spacing, anchor_y) for i in range(slot_count)]

        passenger_count = slot_count // 2
        driver_count = slot_count - passenger_count
        passenger_start = anchor_x - group_gap / 2 - h_spacing * max(0, passenger_count - 1)
        driver_start = anchor_x + group_gap / 2
        return (
            [(passenger_start + i * h_spacing, anchor_y) for i in range(passenger_count)]
            + [(driver_start + i * h_spacing, anchor_y) for i in range(driver_count)]
        )

    # Use the existing PILLARS anchor as the two column centers, then stack
    # the IONs symmetrically around each pillar.  A centered layout falls back
    # to half the authored pillar spacing, which matches its two picker dots.
    if pattern == "outer_edge_pillars":
        center = 0.5
        offset = abs(anchor_x - center)
        if offset < 0.001 and h_spacing:
            offset = h_spacing / 2
        negative_count = (slot_count + 1) // 2
        positive_count = slot_count - negative_count
        sv = v_spacing if v_spacing is not None else h_spacing

        def stack(x: float, count: int) -> list[tuple[float, float]]:
            start_y = anchor_y - sv * (count - 1) / 2
            return [(x, start_y + i * sv) for i in range(count)]

        return stack(center - offset, negative_count) + stack(center + offset, positive_count)

    # ── Vertical ────────────────────────────────────────────────────────────
    if pattern == "vertical":
        sv = v_spacing if v_spacing is not None else h_spacing
        total_h = sv * (slot_count - 1)
        start_y = anchor_y - total_h / 2
        return [(anchor_x, start_y + i * sv) for i in range(slot_count)]

    # ── Vertical mirror ────────────────────────────────────────────────────
    # Like ``mirror``, but reflected around the image's vertical midpoint.
    # The authored anchor identifies one of the two physical positions; its
    # reflected counterpart is generated on the other side of center.
    if pattern == "vertical_mirror":
        center = 0.5
        sv = v_spacing if v_spacing is not None else h_spacing
        offset = abs(anchor_y - center)
        if offset < 0.001 and sv:
            offset = sv / 2
        if slot_count == 2:
            return [(anchor_x, center - offset), (anchor_x, center + offset)]
        half = slot_count // 2
        positions: list[tuple[float, float]] = []
        for i in range(half):
            o = offset + i * sv
            positions.append((anchor_x, center - o))
            positions.append((anchor_x, center + o))
        return positions

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
