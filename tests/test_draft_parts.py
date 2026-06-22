"""Tests for granular draft-part mutation (Phase 5)."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from dtm_buildsheet.inputs.project_drafts import (
    BuildDraft,
    DraftPart,
    _ensure_line_ids,
    draft_part_from_payload,
    find_part_by_line_id,
    load_draft,
    new_draft,
    save_draft,
)
from dtm_buildsheet.app.services.draft_service import (
    handle_add_part_to_draft,
    handle_remove_part_from_draft,
    handle_update_part_in_draft,
)
from dtm_buildsheet.paths import AppPaths


# ── helpers ────────────────────────────────────────────────────────────────────

def _paths(tmp_path: Path) -> AppPaths:
    d = tmp_path / "drafts"
    d.mkdir()
    return AppPaths(workspace_drafts_dir=d)


def _saved_draft(paths: AppPaths, parts: list[DraftPart] | None = None) -> BuildDraft:
    draft = new_draft(
        vehicle_info={"VehicleType": "TAHOE"},
        parts=parts or [],
    )
    _ensure_line_ids(draft)
    save_draft(draft, paths.workspace_drafts_dir)
    return draft


def _part(**kwargs) -> DraftPart:
    defaults = dict(name="Light Bar", quantity=1, line_id=str(uuid.uuid4()))
    defaults.update(kwargs)
    return DraftPart(**defaults)


# ── DraftPart.line_id ──────────────────────────────────────────────────────────

class TestLineId:
    def test_default_is_empty_string(self):
        dp = DraftPart(name="Siren")
        assert dp.line_id == ""

    def test_explicit_line_id_preserved(self):
        lid = str(uuid.uuid4())
        dp = DraftPart(name="Siren", line_id=lid)
        assert dp.line_id == lid

    def test_existing_instantiations_still_work(self):
        # Regression: all existing call sites omit line_id
        dp = DraftPart(name="X", include=False, quantity=2)
        assert dp.name == "X"
        assert dp.quantity == 2


# ── _ensure_line_ids ───────────────────────────────────────────────────────────

class TestEnsureLineIds:
    def test_assigns_ids_to_parts_without_one(self):
        # Simulate a draft loaded from an older JSON that predates line_id.
        # new_draft() now calls _ensure_line_ids internally, so bypass it here.
        draft = BuildDraft(
            draft_id="test",
            created_at="now",
            updated_at="now",
            vehicle_info={},
            parts=[DraftPart(name="A"), DraftPart(name="B")],
        )
        assert all(p.line_id == "" for p in draft.parts)
        _ensure_line_ids(draft)
        assert all(p.line_id for p in draft.parts)

    def test_does_not_overwrite_existing_ids(self):
        lid = str(uuid.uuid4())
        draft = new_draft(parts=[DraftPart(name="A", line_id=lid)])
        _ensure_line_ids(draft)
        assert draft.parts[0].line_id == lid

    def test_ids_are_unique(self):
        draft = new_draft(parts=[DraftPart(name="A"), DraftPart(name="B")])
        _ensure_line_ids(draft)
        ids = [p.line_id for p in draft.parts]
        assert len(set(ids)) == 2


# ── old-draft backward compatibility ──────────────────────────────────────────

class TestOldDraftCompat:
    def test_load_draft_without_line_ids(self, tmp_path):
        """Draft JSON written before line_id existed should load and get IDs assigned."""
        draft = new_draft(parts=[DraftPart(name="Siren", quantity=1)])
        # Manually strip line_id from JSON before saving
        raw = asdict(draft)
        for p in raw["parts"]:
            p.pop("line_id", None)
        path = tmp_path / f"{draft.draft_id}.json"
        path.write_text(json.dumps(raw), encoding="utf-8")

        loaded = load_draft(draft.draft_id, tmp_path)
        assert len(loaded.parts) == 1
        assert loaded.parts[0].line_id  # assigned by _ensure_line_ids


# ── find_part_by_line_id ───────────────────────────────────────────────────────

class TestFindPartByLineId:
    def test_finds_existing_part(self):
        lid = str(uuid.uuid4())
        draft = new_draft(parts=[DraftPart(name="X", line_id=lid)])
        result = find_part_by_line_id(draft, lid)
        assert result is not None
        idx, part = result
        assert idx == 0
        assert part.line_id == lid

    def test_returns_none_for_missing_id(self):
        draft = new_draft(parts=[DraftPart(name="X", line_id=str(uuid.uuid4()))])
        assert find_part_by_line_id(draft, "nonexistent") is None

    def test_returns_correct_index(self):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        draft = new_draft(parts=[DraftPart(name="A", line_id=a), DraftPart(name="B", line_id=b)])
        idx, part = find_part_by_line_id(draft, b)
        assert idx == 1
        assert part.name == "B"


# ── draft_part_from_payload ────────────────────────────────────────────────────

class TestDraftPartFromPayload:
    def _paths(self, tmp_path):
        return AppPaths(workspace_drafts_dir=tmp_path)

    def test_basic_fields(self, tmp_path):
        body = {"name": "Siren", "quantity": "2", "location": "Dash", "include": True}
        part = draft_part_from_payload(body, self._paths(tmp_path))
        assert part.name == "Siren"
        assert part.quantity == 2
        assert part.location == "Dash"
        assert part.include is True

    def test_assigns_uuid_when_no_line_id(self, tmp_path):
        part = draft_part_from_payload({"name": "X"}, self._paths(tmp_path))
        assert part.line_id
        try:
            uuid.UUID(part.line_id)
        except ValueError:
            pytest.fail("line_id is not a valid UUID")

    def test_preserves_provided_line_id(self, tmp_path):
        lid = str(uuid.uuid4())
        part = draft_part_from_payload({"name": "X", "line_id": lid}, self._paths(tmp_path))
        assert part.line_id == lid

    def test_quantity_coerced_to_int(self, tmp_path):
        part = draft_part_from_payload({"name": "X", "quantity": "3"}, self._paths(tmp_path))
        assert part.quantity == 3

    def test_negative_quantity_clamped_to_zero(self, tmp_path):
        part = draft_part_from_payload({"name": "X", "quantity": -5}, self._paths(tmp_path))
        assert part.quantity == 0

    def test_include_string_false(self, tmp_path):
        part = draft_part_from_payload({"name": "X", "include": "false"}, self._paths(tmp_path))
        assert part.include is False


# ── handle_add_part_to_draft ───────────────────────────────────────────────────

class TestAddPart:
    def test_adds_part(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        result = handle_add_part_to_draft(draft.draft_id, {"name": "Siren", "quantity": 1}, paths)
        assert result["ok"] is True
        assert result["line_id"]
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert len(loaded.parts) == 1
        assert loaded.parts[0].name == "Siren"

    def test_returns_draft_summary(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        result = handle_add_part_to_draft(draft.draft_id, {"name": "X"}, paths)
        assert "draft_summary" in result
        assert result["draft_summary"]["parts_count"] == 1

    def test_audit_trail_entry(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        handle_add_part_to_draft(draft.draft_id, {"name": "Siren"}, paths)
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert any(e["action"] == "part_added" for e in loaded.audit_trail)

    def test_missing_name_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        result = handle_add_part_to_draft(draft.draft_id, {"quantity": 1}, paths)
        assert result["ok"] is False
        assert "name" in result["error"]

    def test_unknown_draft_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_add_part_to_draft("ghost-id", {"name": "X"}, paths)
        assert result["ok"] is False

    def test_invalid_draft_id_rejected(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_add_part_to_draft("../etc/passwd", {"name": "X"}, paths)
        assert result["ok"] is False
        assert "invalid" in result["error"]


# ── handle_update_part_in_draft ────────────────────────────────────────────────

class TestUpdatePart:
    def test_updates_field(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part(name="Old Name")
        draft = _saved_draft(paths, parts=[part])
        result = handle_update_part_in_draft(draft.draft_id, part.line_id, {"name": "New Name"}, paths)
        assert result["ok"] is True
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert loaded.parts[0].name == "New Name"

    def test_line_id_unchanged_after_update(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part(name="A")
        draft = _saved_draft(paths, parts=[part])
        handle_update_part_in_draft(draft.draft_id, part.line_id, {"name": "B"}, paths)
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert loaded.parts[0].line_id == part.line_id

    def test_audit_trail_entry(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part()
        draft = _saved_draft(paths, parts=[part])
        handle_update_part_in_draft(draft.draft_id, part.line_id, {"quantity": 3}, paths)
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert any(e["action"] == "part_updated" for e in loaded.audit_trail)

    def test_bad_line_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        result = handle_update_part_in_draft(draft.draft_id, "nonexistent-lid", {"name": "X"}, paths)
        assert result["ok"] is False

    def test_unknown_draft_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_update_part_in_draft("ghost", "some-line", {"name": "X"}, paths)
        assert result["ok"] is False

    def test_invalid_line_id_rejected(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        result = handle_update_part_in_draft(draft.draft_id, "../etc", {"name": "X"}, paths)
        assert result["ok"] is False
        assert "invalid" in result["error"]

    def test_updates_quantity(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part(quantity=1)
        draft = _saved_draft(paths, parts=[part])
        handle_update_part_in_draft(draft.draft_id, part.line_id, {"quantity": 5}, paths)
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert loaded.parts[0].quantity == 5

    def test_returns_draft_summary(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part()
        draft = _saved_draft(paths, parts=[part])
        result = handle_update_part_in_draft(draft.draft_id, part.line_id, {"quantity": 2}, paths)
        assert "draft_summary" in result


# ── handle_remove_part_from_draft ──────────────────────────────────────────────

class TestRemovePart:
    def test_removes_part(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part()
        draft = _saved_draft(paths, parts=[part])
        result = handle_remove_part_from_draft(draft.draft_id, part.line_id, paths)
        assert result["ok"] is True
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert len(loaded.parts) == 0

    def test_removes_correct_part_by_line_id(self, tmp_path):
        paths = _paths(tmp_path)
        keep = _part(name="Keep")
        remove = _part(name="Remove")
        draft = _saved_draft(paths, parts=[keep, remove])
        handle_remove_part_from_draft(draft.draft_id, remove.line_id, paths)
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert len(loaded.parts) == 1
        assert loaded.parts[0].name == "Keep"

    def test_audit_trail_entry(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part()
        draft = _saved_draft(paths, parts=[part])
        handle_remove_part_from_draft(draft.draft_id, part.line_id, paths)
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert any(e["action"] == "part_removed" for e in loaded.audit_trail)

    def test_bad_line_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        result = handle_remove_part_from_draft(draft.draft_id, "nonexistent", paths)
        assert result["ok"] is False

    def test_unknown_draft_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_remove_part_from_draft("ghost-id", "any-line", paths)
        assert result["ok"] is False

    def test_invalid_draft_id_rejected(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_remove_part_from_draft("../etc/passwd", "x", paths)
        assert result["ok"] is False
        assert "invalid" in result["error"]

    def test_returns_draft_summary(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part()
        draft = _saved_draft(paths, parts=[part])
        result = handle_remove_part_from_draft(draft.draft_id, part.line_id, paths)
        assert "draft_summary" in result
        assert result["draft_summary"]["parts_count"] == 0


# ── generate from mutated draft ────────────────────────────────────────────────

class TestGenerateAfterMutation:
    """Smoke test: add → update → remove and ensure draft round-trips cleanly."""

    def test_draft_to_project_input_after_add_update_remove(self, tmp_path):
        from dtm_buildsheet.inputs.project_drafts import draft_to_project_input

        paths = _paths(tmp_path)
        draft = _saved_draft(paths, parts=[_part(name="Siren", quantity=1)])

        # add
        handle_add_part_to_draft(draft.draft_id, {"name": "Light Bar", "quantity": 1}, paths)
        # update the first part
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        siren_lid = loaded.parts[0].line_id
        handle_update_part_in_draft(draft.draft_id, siren_lid, {"quantity": 3}, paths)
        # remove the second part (Light Bar)
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        lb_lid = loaded.parts[1].line_id
        handle_remove_part_from_draft(draft.draft_id, lb_lid, paths)

        final = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert len(final.parts) == 1
        assert final.parts[0].name == "Siren"
        assert final.parts[0].quantity == 3

        # Should convert without error
        project = draft_to_project_input(final)
        assert len(project.parts) == 1


def test_remove_parent_cascades_accessories(tmp_path):
    paths = _paths(tmp_path)
    parent = DraftPart(name="ION", location="Grille", line_id="PARENT")
    a1 = DraftPart(name="ION · Bracket", location="Grille", line_id="A1", parent_line_id="PARENT")
    a2 = DraftPart(name="ION · Cable", location="Grille", line_id="A2", parent_line_id="PARENT")
    other = DraftPart(name="Siren", location="Engine", line_id="OTHER")
    draft = _saved_draft(paths, [parent, a1, a2, other])

    res = handle_remove_part_from_draft(draft.draft_id, "PARENT", paths)
    assert res["ok"] is True
    assert res["cascaded_accessories"] == 2
    remaining = {p.name for p in load_draft(draft.draft_id, paths.workspace_drafts_dir).parts}
    assert remaining == {"Siren"}


def test_remove_accessory_child_leaves_parent(tmp_path):
    paths = _paths(tmp_path)
    parent = DraftPart(name="ION", location="Grille", line_id="PARENT")
    a1 = DraftPart(name="ION · Bracket", location="Grille", line_id="A1", parent_line_id="PARENT")
    draft = _saved_draft(paths, [parent, a1])

    res = handle_remove_part_from_draft(draft.draft_id, "A1", paths)
    assert res["ok"] is True
    assert res.get("cascaded_accessories", 0) == 0
    remaining = {p.name for p in load_draft(draft.draft_id, paths.workspace_drafts_dir).parts}
    assert remaining == {"ION"}


def test_parent_line_id_round_trips_through_payload(tmp_path):
    part = draft_part_from_payload({"name": "Bracket", "parent_line_id": "PARENT"}, _paths(tmp_path))
    assert part.parent_line_id == "PARENT"
