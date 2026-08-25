"""Tests for domain/geometry.py — slot role assignment and normalized position computation."""
from __future__ import annotations

import pytest

from dtm_buildsheet.domain.geometry import (
    compound_slot_relative_positions,
    slot_relative_positions,
    slot_roles,
    view_side_role,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

VIEW_CFG = {
    "default_slot_role": "center",
    "side_roles": {
        "negative_x": "driver",
        "positive_x": "passenger",
    },
}

EMPTY_CFG: dict = {}


# ── view_side_role ────────────────────────────────────────────────────────────

class TestViewSideRole:
    def test_negative_x(self):
        assert view_side_role(VIEW_CFG, "negative_x") == "driver"

    def test_positive_x(self):
        assert view_side_role(VIEW_CFG, "positive_x") == "passenger"

    def test_unknown_direction_defaults_to_center(self):
        assert view_side_role(VIEW_CFG, "up") == "center"

    def test_missing_side_roles_key_defaults_to_center(self):
        assert view_side_role({}, "negative_x") == "center"


# ── slot_roles ────────────────────────────────────────────────────────────────

class TestSlotRoles:
    # uniform_color
    def test_uniform_color_overrides_all_slots(self):
        roles = slot_roles("mirror", 4, VIEW_CFG, uniform_color=True)
        assert roles == ["uniform", "uniform", "uniform", "uniform"]

    def test_uniform_color_single_slot_not_triggered(self):
        # uniform_color only activates when slot_count > 1
        roles = slot_roles("single", 1, VIEW_CFG, uniform_color=True)
        assert roles == ["center"]

    # forced_side
    def test_forced_side_collapses_to_one_slot(self):
        # The caller (planner) reduces slot_count to 1 before calling slot_roles
        # when forced_side is set, so this function receives slot_count=1.
        roles = slot_roles("mirror", 1, VIEW_CFG, forced_side="driver")
        assert roles == ["driver"]

    def test_forced_side_on_single_pattern(self):
        roles = slot_roles("single", 1, VIEW_CFG, forced_side="passenger")
        assert roles == ["passenger"]

    # single pattern
    def test_single_pattern_uses_default_role(self):
        roles = slot_roles("single", 1, VIEW_CFG)
        assert roles == ["center"]

    def test_single_pattern_missing_default_falls_back_to_center(self):
        roles = slot_roles("single", 1, EMPTY_CFG)
        assert roles == ["center"]

    # mirror pattern
    def test_mirror_two_slots(self):
        roles = slot_roles("mirror", 2, VIEW_CFG)
        assert roles == ["driver", "passenger"]

    def test_mirror_four_slots(self):
        roles = slot_roles("mirror", 4, VIEW_CFG)
        assert roles == ["driver", "driver", "passenger", "passenger"]

    def test_mirror_six_slots(self):
        roles = slot_roles("mirror", 6, VIEW_CFG)
        assert roles == ["driver", "driver", "driver", "passenger", "passenger", "passenger"]

    # horizontal pattern
    def test_horizontal_one_slot_uses_default(self):
        roles = slot_roles("horizontal", 1, VIEW_CFG)
        assert roles == ["center"]

    def test_horizontal_two_slots(self):
        roles = slot_roles("horizontal", 2, VIEW_CFG)
        # left = driver (negative_x), right = passenger (positive_x)
        assert roles == ["driver", "passenger"]

    def test_horizontal_three_slots_center_middle(self):
        roles = slot_roles("horizontal", 3, VIEW_CFG)
        assert roles == ["driver", "center", "passenger"]

    def test_horizontal_four_slots_no_center(self):
        roles = slot_roles("horizontal", 4, VIEW_CFG)
        assert roles == ["driver", "driver", "passenger", "passenger"]

    def test_horizontal_five_slots_center_middle(self):
        roles = slot_roles("horizontal", 5, VIEW_CFG)
        assert roles == ["driver", "driver", "center", "passenger", "passenger"]

    # vertical pattern
    def test_vertical_slots_are_positional(self):
        roles = slot_roles("vertical", 3, VIEW_CFG)
        assert roles == ["slot_1", "slot_2", "slot_3"]

    def test_vertical_single_slot_is_positional(self):
        # slot_count==1 triggers the single/degenerate path → default role
        roles = slot_roles("vertical", 1, VIEW_CFG)
        assert roles == ["center"]

    # unknown pattern falls back to positional
    def test_unknown_pattern_positional(self):
        roles = slot_roles("diagonal", 2, VIEW_CFG)
        assert roles == ["slot_1", "slot_2"]

    def test_inner_edge_front_keeps_duo_split_without_a_center_head(self):
        assert slot_roles("inner_edge_front", 5, VIEW_CFG) == [
            "passenger", "passenger", "driver", "driver", "driver",
        ]

    def test_inner_edge_single_module_uses_one_side_color(self):
        assert slot_roles("inner_edge_front_driver", 4, VIEW_CFG) == ["driver"] * 4
        assert slot_roles("inner_edge_front_passenger", 4, VIEW_CFG) == ["passenger"] * 4

    def test_outer_edge_pillars_keep_one_color_role_per_stack(self):
        assert slot_roles("outer_edge_pillars", 6, VIEW_CFG) == [
            "driver", "driver", "driver", "passenger", "passenger", "passenger",
        ]


# ── slot_relative_positions ───────────────────────────────────────────────────

class TestSlotRelativePositions:
    # single
    def test_single_returns_anchor(self):
        pos = slot_relative_positions("single", 1, 0.3, 0.4, 0.1)
        assert pos == [(0.3, 0.4)]

    def test_single_slot_count_returns_anchor(self):
        pos = slot_relative_positions("horizontal", 1, 0.5, 0.2, 0.05)
        assert pos == [(0.5, 0.2)]

    # single with mirror override (slot_count==1, but pattern mirror, role-based)
    def test_single_mirror_passenger_goes_left(self):
        pos = slot_relative_positions("mirror", 1, 0.3, 0.5, 0.05,
                                      slot_roles_list=["passenger"])
        x, y = pos[0]
        assert y == pytest.approx(0.5)
        # passenger/negative_x → center - offset = 0.5 - |0.3 - 0.5| = 0.5 - 0.2 = 0.3
        assert x == pytest.approx(0.3)

    def test_single_mirror_driver_goes_right(self):
        pos = slot_relative_positions("mirror", 1, 0.3, 0.5, 0.05,
                                      slot_roles_list=["driver"])
        x, y = pos[0]
        assert y == pytest.approx(0.5)
        # driver/positive_x → center + offset = 0.5 + 0.2 = 0.7
        assert x == pytest.approx(0.7)

    def test_single_mirror_no_roles_returns_anchor(self):
        pos = slot_relative_positions("mirror", 1, 0.3, 0.5, 0.05)
        assert pos == [(0.3, 0.5)]

    # horizontal
    def test_horizontal_two_slots_centered_on_anchor(self):
        pos = slot_relative_positions("horizontal", 2, 0.5, 0.2, 0.1)
        assert len(pos) == 2
        x0, y0 = pos[0]
        x1, y1 = pos[1]
        assert y0 == pytest.approx(0.2)
        assert y1 == pytest.approx(0.2)
        assert x0 == pytest.approx(0.45)
        assert x1 == pytest.approx(0.55)

    def test_horizontal_three_slots_middle_is_anchor(self):
        pos = slot_relative_positions("horizontal", 3, 0.5, 0.3, 0.1)
        xs = [p[0] for p in pos]
        assert xs[1] == pytest.approx(0.5)   # middle slot at anchor
        assert xs[0] == pytest.approx(0.4)
        assert xs[2] == pytest.approx(0.6)

    def test_horizontal_four_slots_symmetric(self):
        pos = slot_relative_positions("horizontal", 4, 0.5, 0.5, 0.1)
        xs = [p[0] for p in pos]
        assert xs[0] == pytest.approx(0.35)
        assert xs[1] == pytest.approx(0.45)
        assert xs[2] == pytest.approx(0.55)
        assert xs[3] == pytest.approx(0.65)

    # vertical
    def test_vertical_two_slots_centered_on_anchor(self):
        pos = slot_relative_positions("vertical", 2, 0.5, 0.5, 0.1)
        assert len(pos) == 2
        x0, y0 = pos[0]
        x1, y1 = pos[1]
        assert x0 == pytest.approx(0.5)
        assert x1 == pytest.approx(0.5)
        assert y0 == pytest.approx(0.45)
        assert y1 == pytest.approx(0.55)

    def test_vertical_uses_v_spacing_when_provided(self):
        pos = slot_relative_positions("vertical", 2, 0.5, 0.5, h_spacing=0.1, v_spacing=0.2)
        y0, y1 = pos[0][1], pos[1][1]
        assert y1 - y0 == pytest.approx(0.2)

    def test_vertical_falls_back_to_h_spacing(self):
        pos = slot_relative_positions("vertical", 2, 0.5, 0.5, h_spacing=0.15)
        y0, y1 = pos[0][1], pos[1][1]
        assert y1 - y0 == pytest.approx(0.15)

    # vertical mirror
    def test_vertical_mirror_two_slots_reflect_across_image_center(self):
        pos = slot_relative_positions("vertical_mirror", 2, 0.72, 0.3, h_spacing=0.05)
        assert pos == pytest.approx([(0.72, 0.3), (0.72, 0.7)])

    def test_vertical_mirror_uses_v_spacing_when_anchor_is_centered(self):
        pos = slot_relative_positions(
            "vertical_mirror", 2, 0.5, 0.5, h_spacing=0.05, v_spacing=0.18,
        )
        assert pos[0] == pytest.approx((0.5, 0.41))
        assert pos[1] == pytest.approx((0.5, 0.59))

    # mirror
    def test_mirror_two_slots_symmetric_around_center(self):
        pos = slot_relative_positions("mirror", 2, 0.3, 0.5, 0.05)
        x0, x1 = pos[0][0], pos[1][0]
        # center=0.5, offset=|0.3-0.5|=0.2
        assert x0 == pytest.approx(0.3)   # 0.5 - 0.2
        assert x1 == pytest.approx(0.7)   # 0.5 + 0.2

    def test_mirror_four_slots_second_pair_spreads(self):
        pos = slot_relative_positions("mirror", 4, 0.3, 0.5, 0.05)
        assert len(pos) == 4
        # offset = 0.2; second pair: offset + spacing = 0.25
        xs = [p[0] for p in pos]
        assert xs[0] == pytest.approx(0.3)   # center - 0.2
        assert xs[1] == pytest.approx(0.7)   # center + 0.2
        assert xs[2] == pytest.approx(0.25)  # center - 0.25
        assert xs[3] == pytest.approx(0.75)  # center + 0.25

    def test_mirror_y_constant(self):
        pos = slot_relative_positions("mirror", 4, 0.3, 0.6, 0.05)
        assert all(p[1] == pytest.approx(0.6) for p in pos)

    # unknown pattern
    def test_unknown_pattern_returns_anchor(self):
        pos = slot_relative_positions("diagonal", 3, 0.4, 0.4, 0.1)
        assert pos == [(0.4, 0.4)]

    def test_inner_edge_front_creates_two_visor_groups_with_center_gap(self):
        positions = slot_relative_positions("inner_edge_front", 10, 0.5, 0.2, 0.02)
        xs = [x for x, _ in positions]
        ordinary_gap = xs[1] - xs[0]
        center_gap = xs[5] - xs[4]
        assert ordinary_gap == pytest.approx(0.02)
        assert center_gap == pytest.approx(0.05)  # 2.5 × regular head spacing
        assert xs[4] < 0.5 < xs[5]

    def test_inner_edge_rear_is_one_contiguous_row(self):
        positions = slot_relative_positions("inner_edge_rear", 4, 0.5, 0.2, 0.02)
        assert [x for x, _ in positions] == pytest.approx([0.47, 0.49, 0.51, 0.53])

    def test_inner_edge_rear_duo_orders_driver_red_before_passenger_blue(self):
        assert slot_roles("inner_edge_rear", 4, VIEW_CFG) == [
            "driver", "driver", "passenger", "passenger",
        ]

    def test_outer_edge_pillars_are_two_centered_vertical_stacks(self):
        positions = slot_relative_positions(
            "outer_edge_pillars", 6, 0.5, 0.22, h_spacing=0.59, v_spacing=0.045,
        )
        assert [x for x, _ in positions] == pytest.approx([0.205, 0.205, 0.205, 0.795, 0.795, 0.795])
        assert [y for _, y in positions] == pytest.approx([0.175, 0.22, 0.265, 0.175, 0.22, 0.265])

    def test_dual_groups_position_two_heads_around_each_mirrored_unit(self):
        positions = compound_slot_relative_positions(
            "mirror", group_count=2, group_size=2, instance_count=4,
            anchor_x=0.3, anchor_y=0.5, group_h_spacing=0.05,
            item_h_spacing=0.02,
        )
        assert positions == pytest.approx([
            (0.29, 0.5), (0.31, 0.5),
            (0.69, 0.5), (0.71, 0.5),
        ])
