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
    handle_add_custom_part_to_draft,
    handle_add_part_to_draft,
    handle_list_custom_parts,
    handle_remove_part_from_draft,
    handle_replace_console_setup_parts,
    handle_update_part_in_draft,
)
from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.app.services import parts_db_service


# ── helpers ────────────────────────────────────────────────────────────────────

def _paths(tmp_path: Path) -> AppPaths:
    d = tmp_path / "drafts"
    d.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    return AppPaths(workspace_dir=tmp_path, workspace_drafts_dir=d, workspace_config_dir=config)


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

    def test_preserves_part_condition(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        result = handle_add_part_to_draft(
            draft.draft_id, {"name": "Siren", "new_or_used": "Used"}, paths,
        )
        assert result["ok"] is True
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert loaded.parts[0].new_or_used == "Used"

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

    def test_matching_separately_added_speakers_merge_into_a_pair(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        payload = {
            "name": "Siren Speaker", "part_type": "siren_speaker",
            "part_number": "SA315P", "manufacturer": "Whelen",
            "location": "TOP OF PUSH BUMPER", "new_or_used": "New", "quantity": 1,
        }
        first = handle_add_part_to_draft(draft.draft_id, payload, paths)
        second = handle_add_part_to_draft(draft.draft_id, {**payload, "name": "Siren Speaker 2"}, paths)

        assert first["ok"] is True
        assert second["ok"] is True
        assert second["merged"] is True
        assert second["line_id"] == first["line_id"]
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert len(loaded.parts) == 1
        assert loaded.parts[0].quantity == 2
        assert any(entry["action"] == "part_merged" for entry in loaded.audit_trail)

    def test_speakers_with_different_locations_remain_separate(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        payload = {
            "name": "Siren Speaker", "part_type": "siren_speaker",
            "part_number": "SA315P", "manufacturer": "Whelen",
            "new_or_used": "New", "quantity": 1,
        }
        handle_add_part_to_draft(draft.draft_id, {**payload, "location": "TOP OF PUSH BUMPER"}, paths)
        result = handle_add_part_to_draft(draft.draft_id, {**payload, "location": "BEHIND OEM BUMPER"}, paths)

        assert result.get("merged") is None
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert len(loaded.parts) == 2

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


class TestCustomPart:
    def test_persists_billable_snapshot_and_reuse_history(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)

        result = handle_add_custom_part_to_draft(draft.draft_id, {
            "sku": "VND-042", "description": "Vendor supplied cable kit",
            "unit_price": "42.50", "quantity": "2",
        }, paths)

        assert result["ok"] is True
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert len(loaded.parts) == 1
        part = loaded.parts[0]
        assert part.line_id == result["line_id"]
        assert part.part_type == "custom_part"
        assert part.picker_config["custom_part"] == {
            "sku": "VND-042", "description": "Vendor supplied cable kit", "unit_price": 42.5,
        }
        history = handle_list_custom_parts(paths)["parts"]
        assert len(history) == 1
        assert history[0]["sku"] == "VND-042"
        assert history[0]["description"] == "Vendor supplied cable kit"
        assert history[0]["unit_price"] == 42.5
        assert history[0]["last_used_at"]
        assert any(entry["action"] == "custom_part_added" for entry in loaded.audit_trail)

    def test_catalog_sku_requires_explicit_custom_override(self, tmp_path):
        paths = _paths(tmp_path)
        (paths.workspace_config_dir / "parts_db.json").write_text(json.dumps({
            "schema_version": 2,
            "manufacturers": {"whelen": {"label": "Whelen"}},
            "products": {"ion": {
                "manufacturer_id": "whelen", "model": "ION T",
                "part_numbers": [{"part_number": "ION-T-RW", "qb_item_id": "12"}],
            }},
        }), "utf-8")
        parts_db_service.reset_for_testing()
        draft = _saved_draft(paths)
        payload = {
            "sku": "ion-t-rw", "description": "Manual ION override",
            "unit_price": 99, "quantity": 1,
        }
        try:
            blocked = handle_add_custom_part_to_draft(draft.draft_id, payload, paths)
            assert blocked["error"] == "catalog_sku_exists"
            assert blocked["catalog_part"]["model"] == "ION T"
            assert load_draft(draft.draft_id, paths.workspace_drafts_dir).parts == []

            allowed = handle_add_custom_part_to_draft(
                draft.draft_id, {**payload, "allow_existing_duplicate": True}, paths,
            )
            assert allowed["ok"] is True
        finally:
            parts_db_service.reset_for_testing()

    def test_rejects_missing_or_fractional_cent_price(self, tmp_path):
        paths = _paths(tmp_path)
        draft = _saved_draft(paths)
        base = {"sku": "VND-1", "description": "Vendor cable", "quantity": 1}

        missing = handle_add_custom_part_to_draft(draft.draft_id, base, paths)
        fractional_cent = handle_add_custom_part_to_draft(
            draft.draft_id, {**base, "unit_price": "1.999"}, paths,
        )

        assert missing["error"] == "price is required"
        assert fractional_cent["error"] == "price must use no more than two decimal places"


class TestConsoleSetupReplacement:
    def test_reconciliation_requires_a_console_radio_mic_clip(self, tmp_path):
        paths = _paths(tmp_path)
        console = _part(name="Center Console", part_type="console")
        radio = _part(
            name="Radio Control Head", part_type="radio_head",
            picker_config={"system_type": "radio"},
        )
        draft = _saved_draft(paths, [console, radio])

        result = handle_replace_console_setup_parts(draft.draft_id, console.line_id, {
            "rows": [], "printer": None, "printer_cables": [],
            "radio_reconciliation": {
                "radio_line_id": radio.line_id,
                "use_console_clip": True,
            },
        }, paths)

        assert result == {
            "ok": False,
            "error": "radio reconciliation requires a console radio mic clip",
        }

    def test_replaces_console_tree_in_one_persisted_draft(self, tmp_path):
        """Console, printer, and printer cables survive a fresh draft load."""
        paths = _paths(tmp_path)
        console = _part(name="Center Console", part_type="console")
        stale_faceplate = _part(
            name="Old faceplate", parent_line_id=console.line_id,
            accessory_category="console_faceplate",
        )
        stale_printer = _part(
            name="Old printer", part_type="printer",
            picker_config={"console_setup_owner_line_id": console.line_id},
        )
        stale_cable = _part(name="Old printer cable", parent_line_id=stale_printer.line_id)
        unrelated = _part(name="Keep this unrelated part")
        draft = _saved_draft(
            paths, [console, stale_faceplate, stale_printer, stale_cable, unrelated],
        )

        result = handle_replace_console_setup_parts(draft.draft_id, console.line_id, {
            "rows": [
                {
                    "name": "Center Console · Face Plate 1", "part_number": "C-FP-1",
                    "part_type": "special_face_plate", "accessory_category": "console_faceplate",
                },
                {
                    "name": "Center Console · Docking Station", "part_number": "DS-1",
                    "part_type": "docking_station", "accessory_category": "console_component",
                },
                {
                    "name": "Center Console · Radio Mic Clip", "part_number": "C-MCB",
                    "part_type": "radio_mic_clip", "accessory_category": "console_component",
                },
            ],
            "printer": {
                "name": "Printer", "part_number": "PJ-822", "part_type": "printer",
                "picker_config": {"console_setup_owner_line_id": console.line_id},
            },
            "printer_cables": [
                {
                    "name": "Printer · Power Cable", "part_number": "14331", "part_type": "printer_power",
                    "accessory_category": "printer_power_cable",
                },
                {
                    "name": "Printer · USB Cable", "part_number": "14831", "part_type": "printer_usb",
                    "accessory_category": "printer_usb_cable",
                },
            ],
        }, paths)

        assert result["ok"] is True
        assert result["count"] == 6
        assert result["printer_line_id"]
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert {part.name for part in loaded.parts} == {
            "Center Console", "Center Console · Face Plate 1",
            "Center Console · Docking Station", "Center Console · Radio Mic Clip",
            "Printer", "Printer · Power Cable", "Printer · USB Cable",
            "Keep this unrelated part",
        }
        printer = next(part for part in loaded.parts if part.name == "Printer")
        assert printer.parent_line_id == ""
        assert {part.parent_line_id for part in loaded.parts if part.name.startswith("Printer ·")} == {
            printer.line_id,
        }
        assert all(
            part.parent_line_id == console.line_id
            for part in loaded.parts
            if part.name.startswith("Center Console ·")
        )
        assert any(entry["action"] == "console_setup_replaced" for entry in loaded.audit_trail)

    def test_reuses_existing_radio_mic_clip_without_duplicate_magnetic_mic(self, tmp_path):
        """A later console setup can adopt the radio's mic mount atomically."""
        paths = _paths(tmp_path)
        console = _part(name="Center Console", part_type="console")
        radio = _part(
            name="Radio Control Head", part_type="radio_head",
            picker_config={
                "system_type": "radio",
                "choices": {
                    "micMount": "magnetic_with_bracket",
                    "micLoc": "TOP PLATE OF CONSOLE",
                },
                "details": [
                    {"key": "micMount", "label": "Microphone mount", "value": "Magnetic Mic with bracket"},
                    {"key": "micLoc", "label": "Microphone location", "value": "Top plate of console"},
                ],
            },
            components=[{
                "label": "Radio microphone", "part_type": "radio_mic_clip",
                "location": "TOP PLATE OF CONSOLE", "detail": "Magnetic Mic with bracket", "quantity": 1,
            }],
        )
        radio_mag_mic = _part(
            name="Radio Control Head · Mag Mic with Bracket", parent_line_id=radio.line_id,
            accessory_category="magnetic_mic", part_type="radio_mic_clip", part_number="MMSU-1B",
        )
        radio_cable = _part(
            name="Radio Control Head · Cable refresh", parent_line_id=radio.line_id,
            accessory_category="system_cable_refresh", part_type="radio_cable", part_number="RLN4857A",
        )
        draft = _saved_draft(paths, [console, radio, radio_mag_mic, radio_cable])

        result = handle_replace_console_setup_parts(draft.draft_id, console.line_id, {
            "rows": [{
                "name": "Center Console · Radio Mic Clip", "part_number": "C-MCB",
                "part_type": "radio_mic_clip", "accessory_category": "console_component",
                "picker_config": {
                    "console_setup_owner_line_id": console.line_id,
                    "console_component_key": "radioMicClip",
                },
            }],
            "printer": None,
            "printer_cables": [],
            "radio_reconciliation": {
                "radio_line_id": radio.line_id,
                "use_console_clip": True,
            },
        }, paths)

        assert result["ok"] is True
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        saved_radio = next(part for part in loaded.parts if part.line_id == radio.line_id)
        choices = saved_radio.picker_config["choices"]
        assert choices["micClipRelation"] == "use_console_clip"
        assert choices["micMount"] == ""
        assert choices["micLoc"] == ""
        assert saved_radio.components[-1] == {
            "label": "Radio microphone", "part_type": "radio_mic_clip",
            "location": "ON CENTER CONSOLE",
            "detail": "Uses the selected center-console mic clip", "quantity": 1,
        }
        assert not any(
            part.parent_line_id == radio.line_id and part.accessory_category == "magnetic_mic"
            for part in loaded.parts
        )
        assert any(part.line_id == radio_cable.line_id for part in loaded.parts)
        assert any(part.part_number == "C-MCB" for part in loaded.parts)
        audit = loaded.audit_trail[-1]
        assert audit["radio_mic_clip_reconciled"] is True


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

    def test_updates_manifest_comment(self, tmp_path):
        paths = _paths(tmp_path)
        part = _part()
        draft = _saved_draft(paths, parts=[part])

        result = handle_update_part_in_draft(
            draft.draft_id, part.line_id, {"comment": "Confirm final aiming with customer."}, paths,
        )

        assert result["ok"] is True
        loaded = load_draft(draft.draft_id, paths.workspace_drafts_dir)
        assert loaded.parts[0].comment == "Confirm final aiming with customer."

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


def test_remove_parent_cascades_linked_manifest_part(tmp_path):
    paths = _paths(tmp_path)
    bumper = DraftPart(name="Push Bumper", location="Front", line_id="BUMPER")
    channel = DraftPart(name="Push Bumper · ION channel", line_id="CHANNEL", parent_line_id="BUMPER")
    # This is a normal Forward Warning manifest row, not an accessory child.
    lights = DraftPart(
        name="Forward Warning 1", location="TOP TUBE", quantity=4,
        line_id="LIGHTS", linked_parent_line_id="BUMPER", part_type="warning_light",
    )
    old_nested_light = DraftPart(name="Push Bumper · ION", line_id="OLDLIGHT", parent_line_id="CHANNEL")
    other = DraftPart(name="Siren", location="Engine", line_id="OTHER")
    draft = _saved_draft(paths, [bumper, channel, lights, old_nested_light, other])

    res = handle_remove_part_from_draft(draft.draft_id, "BUMPER", paths)

    assert res["ok"] is True
    assert res["cascaded_accessories"] == 3
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
    part = draft_part_from_payload(
        {"name": "Bracket", "parent_line_id": "PARENT", "linked_parent_line_id": "BUMPER"},
        _paths(tmp_path),
    )
    assert part.parent_line_id == "PARENT"
    assert part.linked_parent_line_id == "BUMPER"


def test_renumber_closes_gaps_on_delete(tmp_path):
    paths = _paths(tmp_path)
    parts = [
        DraftPart(name="Forward Warning 1", line_id="F1"),
        DraftPart(name="Forward Warning 2", line_id="F2"),
        DraftPart(name="Forward Warning 3", line_id="F3"),
        DraftPart(name="Forward Warning 3 · Bracket", line_id="A", parent_line_id="F3"),
        DraftPart(name="Side Warning 1", line_id="S1"),
    ]
    draft = _saved_draft(paths, parts)
    handle_remove_part_from_draft(draft.draft_id, "F2", paths)
    names = [p.name for p in load_draft(draft.draft_id, paths.workspace_drafts_dir).parts]
    assert names == [
        "Forward Warning 1",
        "Forward Warning 2",
        "Forward Warning 2 · Bracket",
        "Side Warning 1",
    ]


def test_accessory_fields_round_trip(tmp_path):
    part = draft_part_from_payload(
        {"name": "ION · Bracket", "parent_line_id": "P",
         "accessory_category": "bracket_mount", "accessory_parent_product": "whelen_ion"},
        _paths(tmp_path))
    assert part.accessory_category == "bracket_mount"
    assert part.accessory_parent_product == "whelen_ion"


def test_renumber_on_add_closes_gap(tmp_path):
    paths = _paths(tmp_path)
    draft = _saved_draft(paths, [
        DraftPart(name="Forward Warning 1", line_id="F1"),
        DraftPart(name="Forward Warning 2", line_id="F2"),
    ])
    handle_add_part_to_draft(draft.draft_id, {"name": "Forward Warning 5"}, paths)
    names = sorted(p.name for p in load_draft(draft.draft_id, paths.workspace_drafts_dir).parts)
    assert names == ["Forward Warning 1", "Forward Warning 2", "Forward Warning 3"]


def test_control_head_names_number_only_when_multiple_and_keep_accessory_prefixes(tmp_path):
    paths = _paths(tmp_path)
    draft = _saved_draft(paths)
    payload = {"name": "Control Head 1", "part_type": "control_head", "part_number": "CCTL5"}

    first = handle_add_part_to_draft(draft.draft_id, payload, paths)
    assert first["ok"] is True
    assert first["name"] == "Control Head"

    harness = handle_add_part_to_draft(draft.draft_id, {
        "name": "Control Head · CenCom Core Secondary Control Head Harness",
        "parent_line_id": first["line_id"],
        "part_number": "CCTLHARN",
    }, paths)
    assert harness["ok"] is True

    second = handle_add_part_to_draft(draft.draft_id, payload, paths)
    assert second["ok"] is True
    assert second["name"] == "Control Head 2"
    names = [part.name for part in load_draft(draft.draft_id, paths.workspace_drafts_dir).parts]
    assert names == [
        "Control Head 1",
        "Control Head 1 · CenCom Core Secondary Control Head Harness",
        "Control Head 2",
    ]

    removed = handle_remove_part_from_draft(draft.draft_id, second["line_id"], paths)
    assert removed["ok"] is True
    names = [part.name for part in load_draft(draft.draft_id, paths.workspace_drafts_dir).parts]
    assert names == [
        "Control Head",
        "Control Head · CenCom Core Secondary Control Head Harness",
    ]
