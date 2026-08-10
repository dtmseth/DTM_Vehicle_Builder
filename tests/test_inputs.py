"""Tests for the inputs/ package: excel_reader shim, gui_entry, project_drafts."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from dtm_buildsheet.domain.input_models import PartInput, ProjectInput
from dtm_buildsheet.inputs.excel_reader import load_input
from dtm_buildsheet.inputs.gui_entry import project_input_from_form
from dtm_buildsheet.inputs.project_drafts import (
    BuildDraft,
    DraftPart,
    delete_draft,
    draft_from_project_input,
    draft_summary,
    draft_to_project_input,
    list_drafts,
    load_draft,
    new_draft,
    save_draft,
)

from .conftest import PRIMARY_XLS, SECONDARY_XLS


# ── excel_reader shim ─────────────────────────────────────────────────────────

class TestExcelReader:
    def test_load_primary(self):
        project = load_input(PRIMARY_XLS)
        assert isinstance(project, ProjectInput)
        assert project.parts

    def test_load_secondary(self):
        project = load_input(SECONDARY_XLS)
        assert isinstance(project, ProjectInput)
        assert project.parts

    def test_returns_same_data_as_shim(self):
        """inputs.excel_reader and input_reader shim must agree."""
        from dtm_buildsheet.input_reader import load_input as shim_load
        direct = load_input(PRIMARY_XLS)
        via_shim = shim_load(PRIMARY_XLS)
        assert direct.info["VehicleType"] == via_shim.info["VehicleType"]
        assert len(direct.parts) == len(via_shim.parts)


# ── gui_entry ─────────────────────────────────────────────────────────────────

class TestGuiEntry:
    def _minimal_form(self, **overrides) -> dict:
        data = {
            "vehicle_type": "TAHOE",
            "agency": "Anytown PD",
            "quote_number": "Q-2024-001",
            "parts": [
                {
                    "name": "Light Bar",
                    "include": True,
                    "location": "Roof",
                    "raw_color": "Red/Blue",
                    "quantity": 1,
                }
            ],
            "notes": {"INSTALLATION NOTES": ["Test note"]},
        }
        data.update(overrides)
        return data

    def test_returns_project_input(self):
        project = project_input_from_form(self._minimal_form())
        assert isinstance(project, ProjectInput)

    def test_vehicle_type_passed_through(self):
        project = project_input_from_form(self._minimal_form(vehicle_type="PIU"))
        assert project.info["VehicleType"] == "PIU"

    def test_vehicle_type_inferred_from_model(self):
        form = self._minimal_form(vehicle_type="", new_vehicle={"MODEL": "Tahoe PPV"})
        project = project_input_from_form(form)
        assert project.info["VehicleType"] == "TAHOE"

    def test_piu_inference(self):
        form = self._minimal_form(vehicle_type="", new_vehicle={"MODEL": "Police Interceptor Utility"})
        project = project_input_from_form(form)
        assert project.info["VehicleType"] == "PIU"

    def test_project_id_generated(self):
        project = project_input_from_form(self._minimal_form())
        pid = project.info["ProjectID"]
        assert pid
        assert " " not in pid
        assert "/" not in pid

    def test_project_id_from_agency_when_no_quote(self):
        project = project_input_from_form(self._minimal_form(quote_number=""))
        pid = project.info["ProjectID"]
        assert pid  # derived from agency

    def test_parts_parsed(self):
        project = project_input_from_form(self._minimal_form())
        assert len(project.parts) == 1
        p = project.parts[0]
        assert isinstance(p, PartInput)
        assert p.name
        assert p.location  # location is passed through canonical_name; just check non-empty
        assert p.include is True
        assert p.quantity == 1

    def test_part_include_bool_true(self):
        form = self._minimal_form()
        form["parts"][0]["include"] = True
        project = project_input_from_form(form)
        assert project.parts[0].include is True

    def test_part_include_bool_false(self):
        form = self._minimal_form()
        form["parts"][0]["include"] = False
        project = project_input_from_form(form)
        assert project.parts[0].include is False

    def test_part_include_string_no(self):
        form = self._minimal_form()
        form["parts"][0]["include"] = "no"
        project = project_input_from_form(form)
        assert project.parts[0].include is False

    def test_part_color_alias(self):
        """Accepts both 'raw_color' and 'color' field names."""
        form = self._minimal_form()
        form["parts"][0].pop("raw_color", None)
        form["parts"][0]["color"] = "Red/White"
        project = project_input_from_form(form)
        assert project.parts[0].raw_color == "Red/White"

    def test_part_qty_alias(self):
        """Accepts both 'quantity' and 'qty'."""
        form = self._minimal_form()
        form["parts"][0].pop("quantity", None)
        form["parts"][0]["qty"] = 3
        project = project_input_from_form(form)
        assert project.parts[0].quantity == 3

    def test_notes_parsed(self):
        project = project_input_from_form(self._minimal_form())
        assert project.notes == {"INSTALLATION NOTES": ["Test note"]}

    def test_empty_parts_list(self):
        project = project_input_from_form(self._minimal_form(parts=[]))
        assert project.parts == []

    def test_parts_with_empty_name_skipped(self):
        form = self._minimal_form()
        form["parts"].append({"name": "", "quantity": 1})
        project = project_input_from_form(form)
        assert len(project.parts) == 1

    def test_all_optional_info_fields(self):
        form = self._minimal_form(
            primary_contact="Jane Doe",
            phone="555-1234",
            email="jane@pd.gov",
            sales_rep="Bob",
            additional_info="Rush",
        )
        project = project_input_from_form(form)
        assert project.info["PrimaryContact"] == "Jane Doe"
        assert project.info["Phone"] == "555-1234"
        assert project.info["Email"] == "jane@pd.gov"
        assert project.info["SalesRep"] == "Bob"
        assert project.info["AdditionalInfo"] == "Rush"

    def test_vehicle_dicts_forwarded(self):
        form = self._minimal_form(
            new_vehicle={"YEAR": "2024", "MAKE": "Chevrolet"},
            existing_vehicle={"VIN": "ABC123"},
        )
        project = project_input_from_form(form)
        assert project.info["NewVehicle"]["YEAR"] == "2024"
        assert project.info["ExistingVehicle"]["VIN"] == "ABC123"


# ── DraftPart / BuildDraft dataclasses ────────────────────────────────────────

class TestDraftModels:
    def test_new_draft_defaults(self):
        draft = new_draft()
        assert draft.draft_id
        assert draft.created_at
        assert draft.updated_at
        assert draft.vehicle_info == {}
        assert draft.parts == []
        assert draft.notes == {}
        assert draft.placement_overrides == {}
        assert draft.validation_messages == []
        assert draft.audit_trail == []

    def test_new_draft_with_data(self):
        draft = new_draft(
            vehicle_info={"VehicleType": "TAHOE"},
            parts=[DraftPart(name="Light Bar")],
            notes={"INSTALLATION NOTES": ["note"]},
        )
        assert draft.vehicle_info["VehicleType"] == "TAHOE"
        assert len(draft.parts) == 1
        assert draft.notes == {"INSTALLATION NOTES": ["note"]}

    def test_draft_part_defaults(self):
        dp = DraftPart(name="Siren")
        assert dp.include is True
        assert dp.quantity == 0
        assert dp.placement_overrides == {}

    def test_draft_from_project_input_roundtrip(self):
        project = load_input(PRIMARY_XLS)
        draft = draft_from_project_input(project)
        assert len(draft.parts) == len(project.parts)
        assert draft.vehicle_info["VehicleType"] == project.info["VehicleType"]


# ── draft_to_project_input ────────────────────────────────────────────────────

class TestDraftToProjectInput:
    def _make_draft(self) -> BuildDraft:
        return new_draft(
            vehicle_info={
                "VehicleType": "TAHOE",
                "Agency": "Anytown PD",
                "QuoteNumber": "Q-001",
                "ProjectID": "Q-001",
                "NewVehicle": {},
                "ExistingVehicle": {},
            },
            parts=[
                DraftPart(
                    name="Light Bar",
                    include=True,
                    location="Roof",
                    raw_color="Red/Blue",
                    quantity=1,
                )
            ],
            notes={"INSTALLATION NOTES": ["note"]},
        )

    def test_returns_project_input(self):
        project = draft_to_project_input(self._make_draft())
        assert isinstance(project, ProjectInput)

    def test_vehicle_type_preserved(self):
        project = draft_to_project_input(self._make_draft())
        assert project.info["VehicleType"] == "TAHOE"

    def test_parts_converted(self):
        project = draft_to_project_input(self._make_draft())
        assert len(project.parts) == 1
        assert isinstance(project.parts[0], PartInput)

    def test_linked_manifest_part_is_still_sent_to_the_planner(self):
        draft = new_draft(
            vehicle_info={"VehicleType": "TAHOE"},
            parts=[
                DraftPart(name="Push Bumper", line_id="BUMPER"),
                DraftPart(
                    name="Forward Warning 1", location="TOP TUBE", quantity=4,
                    line_id="ION_LIGHTS", linked_parent_line_id="BUMPER",
                    part_type="warning_light",
                ),
            ],
        )

        project = draft_to_project_input(draft)

        assert [(part.name, part.location, part.quantity) for part in project.parts] == [
            ("Push Bumper", "", 0),
            ("Forward Warning 1", "TOP TUBE", 4),
        ]

    def test_accessory_parent_relationship_is_sent_to_the_planner(self):
        draft = new_draft(
            vehicle_info={"VehicleType": "TAHOE"},
            parts=[
                DraftPart(name="Push Bumper", line_id="BUMPER"),
                DraftPart(
                    name="Push Bumper · Bracket", line_id="BRACKET",
                    parent_line_id="BUMPER", accessory_category="bracket_mount",
                ),
            ],
        )

        project = draft_to_project_input(draft)

        assert project.parts[1].parent_line_id == "BUMPER"
        assert project.parts[1].accessory_category == "bracket_mount"

    def test_location_forwarded(self):
        project = draft_to_project_input(self._make_draft())
        assert project.parts[0].location == "Roof"  # canonical_name preserves case unless aliased

    def test_notes_forwarded(self):
        project = draft_to_project_input(self._make_draft())
        assert project.notes == {"INSTALLATION NOTES": ["note"]}

    def test_missing_vehicle_type_defaults_to_unknown(self):
        draft = new_draft(vehicle_info={})
        project = draft_to_project_input(draft)
        assert project.info["VehicleType"] == "UNKNOWN"

    def test_missing_project_id_generated(self):
        draft = new_draft(vehicle_info={"Agency": "TestPD"})
        project = draft_to_project_input(draft)
        assert project.info["ProjectID"]
        assert " " not in project.info["ProjectID"]

    def test_roundtrip_from_excel(self):
        original = load_input(PRIMARY_XLS)
        draft = draft_from_project_input(original)
        recovered = draft_to_project_input(draft)
        assert recovered.info["VehicleType"] == original.info["VehicleType"]
        assert len(recovered.parts) == len(original.parts)
        assert recovered.parts[0].name == original.parts[0].name


# ── persistence ───────────────────────────────────────────────────────────────

class TestDraftPersistence:
    def _draft(self) -> BuildDraft:
        return new_draft(
            vehicle_info={"VehicleType": "PIU", "Agency": "Test PD"},
            parts=[DraftPart(name="Siren", quantity=1)],
            notes={"INSTALLATION NOTES": ["Test note"]},
        )

    def test_save_creates_file(self, tmp_path):
        draft = self._draft()
        path = save_draft(draft, tmp_path)
        assert path.exists()
        assert path.suffix == ".json"

    def test_save_updates_updated_at(self, tmp_path):
        draft = self._draft()
        old_ts = draft.updated_at
        import time; time.sleep(0.01)
        save_draft(draft, tmp_path)
        assert draft.updated_at >= old_ts

    def test_load_roundtrip(self, tmp_path):
        draft = self._draft()
        save_draft(draft, tmp_path)
        loaded = load_draft(draft.draft_id, tmp_path)
        assert loaded.draft_id == draft.draft_id
        assert loaded.vehicle_info == draft.vehicle_info
        assert len(loaded.parts) == 1
        assert loaded.parts[0].name == "Siren"
        assert loaded.notes == {"INSTALLATION NOTES": ["Test note"]}

    def test_load_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_draft("nonexistent-id", tmp_path)

    def test_delete_removes_file(self, tmp_path):
        draft = self._draft()
        save_draft(draft, tmp_path)
        delete_draft(draft.draft_id, tmp_path)
        assert not (tmp_path / f"{draft.draft_id}.json").exists()

    def test_delete_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            delete_draft("ghost-id", tmp_path)

    def test_list_empty_dir(self, tmp_path):
        assert list_drafts(tmp_path) == []

    def test_list_returns_all(self, tmp_path):
        d1 = self._draft()
        d2 = self._draft()
        save_draft(d1, tmp_path)
        save_draft(d2, tmp_path)
        drafts = list_drafts(tmp_path)
        assert len(drafts) == 2

    def test_list_skips_corrupt(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")
        drafts = list_drafts(tmp_path)
        assert drafts == []

    def test_placement_overrides_persisted(self, tmp_path):
        draft = self._draft()
        draft.placement_overrides = {"Light Bar": {"slot": 2}}
        save_draft(draft, tmp_path)
        loaded = load_draft(draft.draft_id, tmp_path)
        assert loaded.placement_overrides == {"Light Bar": {"slot": 2}}

    def test_audit_trail_persisted(self, tmp_path):
        draft = self._draft()
        draft.audit_trail.append({"action": "part_added", "name": "Siren"})
        save_draft(draft, tmp_path)
        loaded = load_draft(draft.draft_id, tmp_path)
        assert len(loaded.audit_trail) == 1
        assert loaded.audit_trail[0]["action"] == "part_added"

    def test_draft_summary_keys(self, tmp_path):
        draft = self._draft()
        summary = draft_summary(draft)
        assert "draft_id" in summary
        assert "vehicle_type" in summary
        assert "agency" in summary
        assert "parts_count" in summary
        assert summary["parts_count"] == 1

    def test_json_is_valid(self, tmp_path):
        draft = self._draft()
        path = save_draft(draft, tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["draft_id"] == draft.draft_id
        assert "parts" in data
