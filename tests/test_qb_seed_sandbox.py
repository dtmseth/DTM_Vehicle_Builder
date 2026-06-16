"""Tests for the sandbox-seeding tool's pure core + Item-create payload.

Hermetic — the live run (which needs a real sandbox connection) is not
exercised here; only the testable planning/payload logic is.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def seed():
    spec = importlib.util.spec_from_file_location(
        "qb_seed_sandbox", _REPO / "tools" / "qb_seed_sandbox.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(name, desc="", price=""):
    return {"Product/Service Name": name, "Sales Description": desc, "Price": price}


def test_build_item_payload_maps_fields(seed):
    p = seed.build_item_payload(_row("01-244", "Whelen alley B/W", "169"), "79")
    assert p["Name"] == "01-244" and p["Sku"] == "01-244"
    assert p["Type"] == "NonInventory"
    assert p["UnitPrice"] == 169.0
    assert p["Description"] == "Whelen alley B/W"
    assert p["IncomeAccountRef"] == {"value": "79"}


def test_build_item_payload_blank_price_and_desc(seed):
    p = seed.build_item_payload(_row("ABC", "", ""), "79")
    assert p["UnitPrice"] == 0.0
    assert "Description" not in p


def test_build_item_payload_strips_colon_and_skips_nameless(seed):
    assert seed.build_item_payload(_row("", "x", "1"), "79") is None
    p = seed.build_item_payload(_row("A:B", "x", "1"), "79")
    assert p["Name"] == "A-B"


def test_plan_seed_skips_existing_and_dupes(seed):
    rows = [_row("AA", price="1"), _row("BB", price="2"), _row("AA", price="3"), _row("", "x")]
    to_create, skipped, unseedable = seed.plan_seed(rows, {"bb"}, "79")
    names = [n for n, _ in to_create]
    assert names == ["AA"]          # BB already exists; second AA is a dupe
    assert "BB" in skipped and "AA" in skipped
    assert unseedable == [""]


def test_plan_seed_case_insensitive_existing(seed):
    to_create, skipped, _ = seed.plan_seed([_row("Whelen-1", price="5")], {"WHELEN-1"}, "79")
    assert to_create == [] and skipped == ["Whelen-1"]
