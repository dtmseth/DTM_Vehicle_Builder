"""Tests for the picker SKU resolver (color selection → SKUs → build rows)."""

from __future__ import annotations

from dataclasses import dataclass

from dtm_buildsheet.planning import sku_resolver


@dataclass
class _PN:
    part_number: str
    color: str = ""
    secondary_color: str = ""
    lens_type: str = ""
    qb_unit_price: float | None = None
    price_usd: float | None = None
    qb_item_id: str = ""


# A trimmed ION-like SKU set.
SKUS = [
    _PN("IONR", color="red", lens_type="clear", qb_unit_price=178.0, qb_item_id="1"),
    _PN("IONB", color="blue", lens_type="clear", qb_unit_price=178.0, qb_item_id="2"),
    _PN("IOND", color="red", secondary_color="white", lens_type="clear", qb_unit_price=178.0, qb_item_id="3"),
    _PN("I2D", color="red", secondary_color="white", lens_type="clear", qb_unit_price=206.0, qb_item_id="4"),
    _PN("XI2D", color="red", secondary_color="white", lens_type="smoked", qb_unit_price=219.0, qb_item_id="5"),
    _PN("IONE", color="blue", secondary_color="white", lens_type="clear", qb_unit_price=178.0, qb_item_id="6"),
]


def test_single_color_matches_single_sku():
    res = sku_resolver.match_heads(SKUS, [["red"]])
    combos = res["combos"]
    assert len(combos) == 1
    assert combos[0]["matched"]
    assert combos[0]["default_sku"] == "IONR"
    assert res["all_matched"]


def test_duo_combo_returns_all_variants_ion_rank_then_price():
    res = sku_resolver.match_heads(SKUS, [["red", "white"]])
    skus = [s["part_number"] for s in res["combos"][0]["skus"]]
    # I2_ preferred (rank 0), others normal (rank 1), IOND/IONE deprecated (rank 2)
    # I2D rank=0 $206, XI2D rank=1 $219, IOND rank=2 $178
    assert skus == ["I2D", "XI2D", "IOND"]
    assert res["combos"][0]["default_sku"] == "I2D"


def test_color_set_is_order_insensitive():
    a = sku_resolver.match_heads(SKUS, [["white", "red"]])
    assert a["combos"][0]["default_sku"] == "I2D"


def test_no_color_filter_matches_every_sku():
    # The picker's "No color" choice sends one empty head ([[]]). Every SKU
    # must match (scene/interior lights are white and need no color filter) —
    # NOT just the colorless ones (the inverted-filter bug we fixed).
    scene_skus = SKUS + [_PN("M9SCENE", qb_unit_price=120.0, qb_item_id="9")]
    res = sku_resolver.match_heads(scene_skus, [[]])
    assert len(res["combos"]) == 1
    combo = res["combos"][0]
    assert combo["matched"]
    assert combo["count"] == 1
    matched_pns = {s["part_number"] for s in combo["skus"]}
    assert matched_pns == {s.part_number for s in scene_skus}  # all of them
    assert res["all_matched"]


def test_no_color_filter_still_respects_lens():
    res = sku_resolver.match_heads(SKUS, [[]], lens="smoked")
    matched_pns = {s["part_number"] for s in res["combos"][0]["skus"]}
    assert matched_pns == {"XI2D"}  # only the smoked SKU


def test_standard_split_groups_by_side():
    # 4 heads: R/W R/W B/W B/W → two combos of 2 each
    heads = [["red", "white"], ["red", "white"], ["blue", "white"], ["blue", "white"]]
    res = sku_resolver.match_heads(SKUS, heads)
    combos = {c["label"]: c["count"] for c in res["combos"]}
    assert combos == {"Red/White": 2, "Blue/White": 2}


def test_lens_filter_excludes_other_lenses():
    res = sku_resolver.match_heads(SKUS, [["red", "white"]], lens="smoked")
    skus = [s["part_number"] for s in res["combos"][0]["skus"]]
    assert skus == ["XI2D"]


def test_trio_is_unmatched():
    res = sku_resolver.match_heads(SKUS, [["red", "blue", "white"]])
    assert not res["combos"][0]["matched"]
    assert res["combos"][0]["default_sku"] == ""
    assert not res["all_matched"]


def test_no_match_for_absent_color():
    res = sku_resolver.match_heads(SKUS, [["green"]])
    assert not res["combos"][0]["matched"]


def test_duplicate_head_colors_never_match_a_lower_color_count_sku():
    """A bad Red/Red request must not silently resolve to the single-red SKU."""
    res = sku_resolver.match_heads(SKUS, [["red", "red"]])
    assert not res["combos"][0]["matched"]
    assert res["combos"][0]["default_sku"] == ""
    assert not res["all_matched"]


def test_build_rows_emits_one_parent_with_components():
    choices = [
        {"colors": ["red", "white"], "part_number": "IOND", "quantity": 2, "price": 178.0},
        {"colors": ["blue", "white"], "part_number": "IONE", "quantity": 2, "price": 178.0},
    ]
    cf = {"raw_color": "Red/White / Blue/White",
          "driver_color": "Red/White", "passenger_color": "Blue/White"}
    out = sku_resolver.build_rows("ION", "Whelen", "Push Bumper", "Forward Warning",
                                  "clear", choices, color_fields=cf, total_heads=4)
    # One simple parent line.
    assert len(out["rows"]) == 1
    parent = out["rows"][0]
    assert parent["name"] == "Forward Warning"
    assert parent["manufacturer"] == "Whelen"
    assert parent["part_number"] == "ION"          # product model, not a SKU
    assert parent["quantity"] == 4                  # total lightheads
    assert parent["location"] == "Push Bumper"
    assert parent["raw_color"] == "Red/White / Blue/White"
    assert parent["driver_color"] == "Red/White"
    assert parent["passenger_color"] == "Blue/White"
    # Concrete SKUs live in components (UI expand only, not the build sheet).
    comps = parent["components"]
    assert [c["part_number"] for c in comps] == ["IOND", "IONE"]
    assert [c["quantity"] for c in comps] == [2, 2]
    assert out["total"] == 712.0
    assert "(2) ION Red/White" in out["description"]
    assert "Push Bumper" in out["description"]


def test_build_rows_total_heads_defaults_to_component_sum():
    choices = [{"colors": ["red"], "part_number": "IONR", "quantity": 3, "price": 178.0}]
    out = sku_resolver.build_rows("ION", "Whelen", "", "Warning", "", choices)
    assert out["rows"][0]["quantity"] == 3
    assert out["rows"][0]["raw_color"] == "Red"


def test_build_rows_skips_zero_qty_and_blank_sku():
    choices = [
        {"colors": ["red"], "part_number": "IONR", "quantity": 0, "price": 178.0},
        {"colors": ["blue"], "part_number": "", "quantity": 2},
    ]
    out = sku_resolver.build_rows("ION", "Whelen", "", "Warning", "", choices)
    assert out["rows"] == []
