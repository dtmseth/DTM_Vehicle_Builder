"""Tests for Phase 10: override_applier and preview_service."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
from dtm_buildsheet.domain.plan_models import (
    BuildPlan,
    PlannedPart,
    PlannedPlacement,
    RenderInstance,
)
from dtm_buildsheet.planning.override_applier import apply_overrides


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_placement(part_id="led_bar", view="front", **kwargs) -> PlannedPlacement:
    defaults = dict(
        part_id=part_id,
        part_name="LED Bar",
        view=view,
        location_key="ROOF LIGHT BAR",
        render_kind="bar",
        asset_key="led_bar",
        size_class="xl_bar",
        color_profile="std_duo_rb_w",
        quantity_policy="location_slots",
        ordered_quantity=1,
        location_slot_count=1,
        anchor={"x": 0.5, "y": 0.1, "units": "relative_image"},
        pattern="single",
        size_override={"w": 4.0, "h": 0.3},
        instances=[RenderInstance(slot_index=1, slot_role="center", orientation="h",
                                  color_token="red_white", asset_path="bars/liberty_rw.png")],
    )
    defaults.update(kwargs)
    return PlannedPlacement(**defaults)


def _make_plan(*placements: PlannedPlacement) -> BuildPlan:
    parts = []
    for pl in placements:
        parts.append(PlannedPart(
            part_id=pl.part_id,
            part_name=pl.part_name,
            category="light_bar",
            render_kind=pl.render_kind,
            on_diagram=True,
            raw=PartInput(name=pl.part_name),
            placements=[pl],
        ))
    return BuildPlan(version="7.0", project={}, planned_parts=parts)


# ── apply_overrides: no-op when empty ────────────────────────────────────────

def test_apply_overrides_empty_noop():
    plan = _make_plan(_make_placement())
    result = apply_overrides(plan, {})
    assert result is plan  # same object returned when no overrides


def test_apply_overrides_unmatched_key_noop():
    pl = _make_placement(part_id="led_bar", view="front")
    plan = _make_plan(pl)
    result = apply_overrides(plan, {"siren:front": {"rotation": 45}})
    assert result.planned_parts[0].placements[0].rotation == 0.0


# ── rotation ──────────────────────────────────────────────────────────────────

def test_apply_overrides_rotation():
    plan = _make_plan(_make_placement(part_id="led_bar", view="front"))
    result = apply_overrides(plan, {"led_bar:front": {"rotation": 90}})
    assert result.planned_parts[0].placements[0].rotation == 90.0


def test_apply_overrides_rotation_negative():
    plan = _make_plan(_make_placement(part_id="led_bar", view="front"))
    result = apply_overrides(plan, {"led_bar:front": {"rotation": -45}})
    assert result.planned_parts[0].placements[0].rotation == -45.0


# ── flip flags ────────────────────────────────────────────────────────────────

def test_apply_overrides_flip_h():
    plan = _make_plan(_make_placement())
    result = apply_overrides(plan, {"led_bar:front": {"flip_h": True}})
    assert result.planned_parts[0].placements[0].flip_h is True


def test_apply_overrides_flip_v():
    plan = _make_plan(_make_placement())
    result = apply_overrides(plan, {"led_bar:front": {"flip_v": True}})
    assert result.planned_parts[0].placements[0].flip_v is True


def test_apply_overrides_flip_h_false_clears():
    pl = _make_placement()
    pl.flip_h = True
    plan = _make_plan(pl)
    result = apply_overrides(plan, {"led_bar:front": {"flip_h": False}})
    assert result.planned_parts[0].placements[0].flip_h is False


# ── visibility ────────────────────────────────────────────────────────────────

def test_apply_overrides_visible_false_drops_placement():
    plan = _make_plan(_make_placement())
    result = apply_overrides(plan, {"led_bar:front": {"visible": False}})
    assert result.planned_parts[0].placements == []


def test_apply_overrides_visible_true_keeps_placement():
    plan = _make_plan(_make_placement())
    result = apply_overrides(plan, {"led_bar:front": {"visible": True}})
    assert len(result.planned_parts[0].placements) == 1


def test_apply_overrides_visible_false_does_not_affect_other_views():
    pl_front = _make_placement(part_id="led_bar", view="front")
    pl_rear  = _make_placement(part_id="led_bar", view="rear")
    pp = PlannedPart(
        part_id="led_bar", part_name="LED Bar", category="light_bar",
        render_kind="bar", on_diagram=True,
        raw=PartInput(name="LED Bar"),
        placements=[pl_front, pl_rear],
    )
    plan = BuildPlan(version="7.0", project={}, planned_parts=[pp])
    result = apply_overrides(plan, {"led_bar:front": {"visible": False}})
    remaining = result.planned_parts[0].placements
    assert len(remaining) == 1
    assert remaining[0].view == "rear"


# ── anchor delta ──────────────────────────────────────────────────────────────

def test_apply_overrides_anchor_dx():
    plan = _make_plan(_make_placement(anchor={"x": 0.5, "y": 0.1, "units": "relative_image"}))
    result = apply_overrides(plan, {"led_bar:front": {"anchor_dx": 0.1}})
    assert abs(result.planned_parts[0].placements[0].anchor["x"] - 0.6) < 1e-5


def test_apply_overrides_anchor_dy():
    plan = _make_plan(_make_placement(anchor={"x": 0.5, "y": 0.1, "units": "relative_image"}))
    result = apply_overrides(plan, {"led_bar:front": {"anchor_dy": -0.05}})
    assert abs(result.planned_parts[0].placements[0].anchor["y"] - 0.05) < 1e-5


def test_apply_overrides_anchor_preserves_units():
    plan = _make_plan(_make_placement(anchor={"x": 0.5, "y": 0.1, "units": "relative_image"}))
    result = apply_overrides(plan, {"led_bar:front": {"anchor_dx": 0.0}})
    assert result.planned_parts[0].placements[0].anchor["units"] == "relative_image"


# ── size_scale ────────────────────────────────────────────────────────────────

def test_apply_overrides_size_scale():
    plan = _make_plan(_make_placement(size_override={"w": 4.0, "h": 0.3}))
    result = apply_overrides(plan, {"led_bar:front": {"size_scale": 2.0}})
    so = result.planned_parts[0].placements[0].size_override
    assert abs(so["w"] - 8.0) < 1e-5
    assert abs(so["h"] - 0.6) < 1e-5


def test_apply_overrides_size_scale_zero_ignored():
    plan = _make_plan(_make_placement(size_override={"w": 4.0, "h": 0.3}))
    result = apply_overrides(plan, {"led_bar:front": {"size_scale": 0}})
    so = result.planned_parts[0].placements[0].size_override
    assert so["w"] == 4.0  # unchanged


def test_apply_overrides_size_scale_no_size_override():
    # size_scale with no size_override should not crash
    plan = _make_plan(_make_placement(size_override=None))
    result = apply_overrides(plan, {"led_bar:front": {"size_scale": 2.0}})
    assert result.planned_parts[0].placements[0].size_override is None


# ── original plan is not mutated ──────────────────────────────────────────────

def test_apply_overrides_does_not_mutate_original():
    plan = _make_plan(_make_placement())
    original_rotation = plan.planned_parts[0].placements[0].rotation
    apply_overrides(plan, {"led_bar:front": {"rotation": 180, "visible": False}})
    assert plan.planned_parts[0].placements[0].rotation == original_rotation
    assert len(plan.planned_parts[0].placements) == 1


# ── multiple parts / overrides ────────────────────────────────────────────────

def test_apply_overrides_multiple_parts():
    pl1 = _make_placement(part_id="led_bar",  view="front")
    pl2 = _make_placement(part_id="spotlight", view="front",
                           part_name="Spotlight", asset_key="spotlight",
                           anchor={"x": 0.8, "y": 0.5, "units": "relative_image"})
    pp1 = PlannedPart(part_id="led_bar",   part_name="LED Bar",   category="light_bar",
                      render_kind="bar",  on_diagram=True, raw=PartInput(name="LED Bar"),
                      placements=[pl1])
    pp2 = PlannedPart(part_id="spotlight", part_name="Spotlight", category="equipment",
                      render_kind="equipment", on_diagram=True, raw=PartInput(name="Spotlight"),
                      placements=[pl2])
    plan = BuildPlan(version="7.0", project={}, planned_parts=[pp1, pp2])

    overrides = {
        "led_bar:front":   {"rotation": 45},
        "spotlight:front": {"visible": False},
    }
    result = apply_overrides(plan, overrides)

    assert result.planned_parts[0].placements[0].rotation == 45.0
    assert result.planned_parts[1].placements == []


# ── draft override persistence ────────────────────────────────────────────────

def test_draft_save_override_roundtrip(tmp_path):
    from dtm_buildsheet.inputs.project_drafts import new_draft, save_draft, load_draft

    draft = new_draft(vehicle_info={"VehicleType": "PIU"})
    save_draft(draft, tmp_path)

    # Simulate what handle_save_override does
    loaded = load_draft(draft.draft_id, tmp_path)
    loaded.placement_overrides["led_bar:front"] = {"visible": False, "rotation": 90}
    save_draft(loaded, tmp_path)

    reloaded = load_draft(draft.draft_id, tmp_path)
    ov = reloaded.placement_overrides.get("led_bar:front", {})
    assert ov.get("visible") is False
    assert ov.get("rotation") == 90


# ── preview_service ───────────────────────────────────────────────────────────

def test_preview_service_missing_draft_id(app_paths):
    from dtm_buildsheet.app.services.preview_service import handle_preview_plan
    res = handle_preview_plan({}, app_paths)
    assert not res["ok"]
    assert "draft_id" in res["error"]


def test_preview_service_unknown_draft(app_paths):
    from dtm_buildsheet.app.services.preview_service import handle_preview_plan
    res = handle_preview_plan({"draft_id": "nonexistent-uuid"}, app_paths)
    assert not res["ok"]


def test_preview_service_full_plan(app_paths, stearns_input):
    from dtm_buildsheet.app.services.preview_service import handle_preview_plan
    from dtm_buildsheet.inputs.project_drafts import draft_from_project_input, save_draft

    draft = draft_from_project_input(stearns_input)
    save_draft(draft, app_paths.workspace_drafts_dir)

    res = handle_preview_plan({"draft_id": draft.draft_id}, app_paths)
    assert res["ok"], res.get("error")
    assert "views" in res
    assert "planned_parts" in res
    assert len(res["views"]) > 0
    assert len(res["planned_parts"]) > 0


def test_preview_service_views_have_bg_url(app_paths, stearns_input):
    from dtm_buildsheet.app.services.preview_service import handle_preview_plan
    from dtm_buildsheet.inputs.project_drafts import draft_from_project_input, save_draft

    draft = draft_from_project_input(stearns_input)
    save_draft(draft, app_paths.workspace_drafts_dir)

    res = handle_preview_plan({"draft_id": draft.draft_id}, app_paths)
    assert res["ok"]
    for view_name, meta in res["views"].items():
        assert "bg_url" in meta
        assert "label" in meta
        assert view_name in meta["bg_url"]


def test_preview_service_placements_have_override_key(app_paths, stearns_input):
    from dtm_buildsheet.app.services.preview_service import handle_preview_plan
    from dtm_buildsheet.inputs.project_drafts import draft_from_project_input, save_draft

    draft = draft_from_project_input(stearns_input)
    save_draft(draft, app_paths.workspace_drafts_dir)

    res = handle_preview_plan({"draft_id": draft.draft_id}, app_paths)
    assert res["ok"]
    for pp in res["planned_parts"]:
        for pl in pp["placements"]:
            assert "override_key" in pl
            assert ":" in pl["override_key"]
            assert pl["override_key"].endswith(":" + pl["view"])


def test_preview_service_respects_visibility_override(app_paths, stearns_input):
    from dtm_buildsheet.app.services.preview_service import handle_preview_plan
    from dtm_buildsheet.inputs.project_drafts import draft_from_project_input, save_draft

    # First get the plan to find a real override key
    draft = draft_from_project_input(stearns_input)
    save_draft(draft, app_paths.workspace_drafts_dir)
    res1 = handle_preview_plan({"draft_id": draft.draft_id}, app_paths)
    assert res1["ok"] and res1["planned_parts"]

    # Grab first placement's override_key
    first_key = res1["planned_parts"][0]["placements"][0]["override_key"]
    part_id, view = first_key.rsplit(":", 1)

    # Reload draft, add visibility=False override, preview again
    from dtm_buildsheet.inputs.project_drafts import load_draft
    draft2 = load_draft(draft.draft_id, app_paths.workspace_drafts_dir)
    draft2.placement_overrides[first_key] = {"visible": False}
    save_draft(draft2, app_paths.workspace_drafts_dir)

    res2 = handle_preview_plan({"draft_id": draft.draft_id}, app_paths)
    assert res2["ok"]

    # The part should either have no placements for that view, or be absent
    hidden_keys = {
        pl["override_key"]
        for pp in res2["planned_parts"]
        for pl in pp["placements"]
    }
    assert first_key not in hidden_keys
