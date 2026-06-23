"""Tracer head-resolution engine — validated against the real wired parts_db.

Exercises the locked rules in docs/TRACER_LIGHTHEAD_SELECTION.md against the
actual Tracer housings + heads (batches 11/12), so a regression in the wiring
or the color rules trips here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.services.lighthead_resolver import resolve_tracer

_PARTS_DB = (Path(__file__).resolve().parents[1]
             / "src/dtm_buildsheet/resources/config/parts_db.json")


@pytest.fixture(scope="module")
def db():
    return json.loads(_PARTS_DB.read_text("utf-8"))


def _line(res, sku):
    return next((l for l in res["lines"] if l["sku"] == sku), None)


def test_5lamp_duo_white_generates_driver_passenger_pair(db):
    res = resolve_tracer(db, "whelen_tracer_5_lamp", mode="duo", secondary_color="white")
    assert res["ok"], res["problems"]
    assert res["lamp_count"] == 5
    assert [h["side"] for h in res["housings"]] == ["driver", "passenger"]
    assert _line(res, "TCRWX5")["qty"] == 2          # one housing per side
    assert _line(res, "TCRWXPD")["qty"] == 1         # driver primary R/W
    assert _line(res, "TCRWXSD")["qty"] == 4         # driver secondary R/W ×(5-1)
    assert _line(res, "TCRWXPE")["qty"] == 1         # passenger primary B/W
    assert _line(res, "TCRWXSE")["qty"] == 4


def test_2lamp_duo_white_single_front_housing_split(db):
    res = resolve_tracer(db, "whelen_2_lamp_tracer", mode="duo", secondary_color="white")
    assert res["ok"], res["problems"]
    assert len(res["housings"]) == 1 and res["housings"][0]["side"] == "front"
    assert _line(res, "TCRWX2")["qty"] == 1
    assert _line(res, "TCRWXPD")["qty"] == 1         # slot 1 = driver R/W (primary)
    assert _line(res, "TCRWXSE")["qty"] == 1         # slot 2 = passenger B/W (secondary)


def test_5lamp_trio_white_uses_pending_rbw_heads(db):
    res = resolve_tracer(db, "whelen_tracer_5_lamp", mode="trio", secondary_color="white")
    assert res["ok"], res["problems"]
    # Trio heads are identical on both sides (R/B/W); pending until QB has them.
    assert _line(res, "TCRWXPJC")["qty"] == 2        # 1 primary × 2 housings
    assert _line(res, "TCRWXSJC")["qty"] == 8        # (5-1) secondary × 2 housings
    assert _line(res, "TCRWXPJC")["pending"] is True


def test_5lamp_duo_amber_passenger_primary_is_pending(db):
    res = resolve_tracer(db, "whelen_tracer_5_lamp", mode="duo", secondary_color="amber")
    assert res["ok"], res["problems"]
    assert _line(res, "TCRWXPK")["qty"] == 1         # driver primary R/A (in QB)
    assert _line(res, "TCRWXPM")["qty"] == 1         # passenger primary B/A (pending)
    assert _line(res, "TCRWXPM")["pending"] is True
    assert _line(res, "TCRWXSM")["qty"] == 4         # passenger secondary B/A


def test_smoked_trio_missing_secondary_reports_problem(db):
    # Smoked primary trio (TCRXXPJC) exists, but the smoked secondary trio doesn't.
    res = resolve_tracer(db, "whelen_tracer_5_lamp", mode="trio",
                         secondary_color="white", lens="smoked")
    assert res["ok"] is False
    assert any(p.get("reason") == "missing_head_sku" and p.get("role") == "secondary"
               for p in res["problems"])


def test_bad_inputs(db):
    assert resolve_tracer(db, "whelen_tracer_5_lamp", mode="solo")["error"] == "bad_mode"
    assert resolve_tracer(db, "nope", mode="duo")["error"] == "unknown_housing"
