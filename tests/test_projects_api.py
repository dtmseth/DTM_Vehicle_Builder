"""Tests for project service and draft-creation orchestration (Phase 4)."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from dtm_buildsheet.app.services.project_service import (
    handle_create_draft,
    handle_create_individual_draft,
    handle_delete_project,
    handle_get_project,
    handle_list_projects,
    handle_save_project,
    handle_set_project_completion,
)
from dtm_buildsheet.app.services.agency_service import handle_save_agency
from dtm_buildsheet.domain.project_models import (
    BuildUnit,
    CustomerInfo,
    EquipmentPreferences,
    IndividualUnit,
)
from dtm_buildsheet.inputs.project_drafts import draft_to_project_input, load_draft
from dtm_buildsheet.inputs.project_entry import load_project, new_project, save_project
from dtm_buildsheet.paths import AppPaths, BUNDLED_PRESETS_DIR


# ── helpers ────────────────────────────────────────────────────────────────────

def _paths(tmp_path: Path) -> AppPaths:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=projects_dir,
        workspace_drafts_dir=drafts_dir,
        bundled_presets_dir=BUNDLED_PRESETS_DIR,
        workspace_presets_dir=tmp_path / "presets",
    )


def _project_body(**overrides) -> dict:
    body = {
        "customer": {
            "name": "Test Customer",
            "agency": "Test PD",
            "quote_number": "Q-001",
            "build_year": "2026",
            "sales_rep": "Alice",
        },
        "preferences": {
            "lighting_brands": ["Whelen", "Code 3"],
            "camera_brand": "Axon",
            "slick_top": True,
        },
        "build_units": [
            {
                "unit_id": "unit-1",
                "vehicle_model": "Tahoe PPV",
                "build_type": "Patrol",
                "preset_id": "patrol_piu_standard",
                "quantity": 2,
            }
        ],
    }
    body.update(overrides)
    return body


# ── handle_save_project ────────────────────────────────────────────────────────

class TestHandleSaveProject:
    def test_creates_new_project(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        assert result["ok"] is True
        assert result["project_id"]

    def test_persists_to_disk(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        project = load_project(result["project_id"], paths)
        assert project.customer.agency == "Test PD"
        assert project.customer.quote_number == "Q-001"

    def test_saved_agency_abbreviation_populates_and_later_updates_project(self, tmp_path):
        paths = _paths(tmp_path)
        agency = handle_save_agency({
            "name": "United States Immigration and Customs Enforcement",
            "abbreviation": "ICE",
        }, paths)["agency"]
        body = _project_body(customer={
            "agency": agency["name"],
            "agency_id": agency["agency_id"],
            "build_year": "2026",
        })
        result = handle_save_project(body, paths)
        project = load_project(result["project_id"], paths)
        assert project.customer.agency_abbreviation == "ICE"

        handle_save_agency({
            "agency_id": agency["agency_id"],
            "name": agency["name"],
            "abbreviation": "HSI",
        }, paths)
        updated = load_project(result["project_id"], paths)
        assert updated.customer.agency_abbreviation == "HSI"

    def test_preserves_build_units(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        project = load_project(result["project_id"], paths)
        assert len(project.build_units) == 1
        unit = project.build_units[0]
        assert unit.unit_id == "unit-1"
        assert unit.vehicle_model == "Tahoe PPV"
        assert unit.quantity == 2

    def test_custom_build_type_is_saved_only_on_its_project_unit(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body(build_units=[{
            "unit_id": "unit-drone",
            "vehicle_model": "Tahoe PPV",
            "build_type": "Drone Squad",
            "quantity": 1,
        }])
        result = handle_save_project(body, paths)

        project = load_project(result["project_id"], paths)
        assert project.build_units[0].build_type == "Drone Squad"

    def test_preserves_preferences(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        project = load_project(result["project_id"], paths)
        assert project.preferences.lighting_brands == ["Whelen", "Code 3"]
        assert project.preferences.slick_top is True
        assert project.preferences.camera_brand == "Axon"

    def test_shared_project_note_is_copied_to_new_draft(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(
            project_notes="Keep the completed unit indoors until pickup.",
        ), paths)

        result = handle_create_draft(create["project_id"], "unit-1", paths)

        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert draft.project_notes == "Keep the completed unit indoors until pickup."

    def test_historical_vehicle_case_alias_creates_draft_with_canonical_layout_id(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(build_units=[{
            "unit_id": "archive-tahoe",
            "vehicle_model": "Tahoe",
            "build_type": "Patrol",
            "quantity": 1,
        }]), paths)

        result = handle_create_draft(create["project_id"], "archive-tahoe", paths)

        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert draft.vehicle_info["VehicleType"] == "TAHOE"

    def test_new_project_copies_agency_defaults_when_preferences_omitted(self, tmp_path):
        paths = _paths(tmp_path)
        agency = handle_save_agency({
            "name": "Alpha PD",
            "default_preferences": {
                "lighting_brands": ["Whelen"],
                "camera_brand": "Axon",
                "console_brand": "Havis",
            },
        }, paths)["agency"]

        result = handle_save_project({
            "customer": {"agency": "Alpha PD", "agency_id": agency["agency_id"], "build_year": "2026"},
            "build_units": [],
        }, paths)

        project = load_project(result["project_id"], paths)
        assert project.preferences.lighting_brands == ["Whelen"]
        assert project.preferences.camera_brand == "Axon"
        assert project.preferences.console_brand == "Havis"

    def test_exact_typed_agency_name_repairs_missing_agency_id(self, tmp_path):
        paths = _paths(tmp_path)
        agency = handle_save_agency({"name": "Seth Test"}, paths)["agency"]

        result = handle_save_project({
            "customer": {"agency": "Seth Test", "agency_id": "", "build_year": "2026"},
            "build_units": [],
        }, paths)

        project = load_project(result["project_id"], paths)
        assert project.customer.agency_id == agency["agency_id"]

    def test_explicit_project_preferences_override_agency_defaults(self, tmp_path):
        paths = _paths(tmp_path)
        agency = handle_save_agency({
            "name": "Alpha PD",
            "default_preferences": {"lighting_brands": ["Whelen"]},
        }, paths)["agency"]

        result = handle_save_project({
            "customer": {"agency": "Alpha PD", "agency_id": agency["agency_id"], "build_year": "2026"},
            "preferences": {"lighting_brands": ["Code 3"]},
            "build_units": [],
        }, paths)

        project = load_project(result["project_id"], paths)
        assert project.preferences.lighting_brands == ["Code 3"]

    def test_explicit_project_id_honored(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project({**_project_body(), "project_id": "my-proj"}, paths)
        assert result["ok"] is True
        assert result["project_id"] == "my-proj"

    def test_update_existing_project(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        update_body = {"project_id": pid, "customer": {"agency": "Updated PD"}}
        handle_save_project(update_body, paths)
        project = load_project(pid, paths)
        assert project.customer.agency == "Updated PD"

    def test_project_edit_preserves_server_owned_vehicle_and_folder_state(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["build_units"][0]["individuals"] = [{
            "individual_id": "vehicle-1",
            "unit_number": "02",
            "existing_unit_number": "03",
            "existing_vin": "OLDVIN654321",
        }]
        created = handle_save_project(body, paths)
        project = load_project(created["project_id"], paths)
        group = project.build_units[0]
        vehicle = group.individuals[0]
        group.shop_group_folder_id = "shop-group-id"
        group.shop_group_folder_path = "Shop/Original Group"
        vehicle.draft_id = "draft-id"
        vehicle.qb_project_id = "70995"
        vehicle.shop_vehicle_folder_id = "shop-vehicle-id"
        vehicle.shop_vehicle_folder_path = "Shop/Original Group/Unit 02"
        vehicle.company_vehicle_folder_id = "company-vehicle-id"
        vehicle.existing_year = "2018"
        vehicle.existing_make = "Ford"
        vehicle.existing_model = "Police Interceptor Utility"
        vehicle.existing_build_type = "Patrol"
        vehicle.existing_unit_number = "03"
        vehicle.existing_vin = "OLDVIN654321"
        save_project(project, paths)

        result = handle_save_project({
            "project_id": project.project_id,
            "build_units": [{
                "unit_id": group.unit_id,
                "vehicle_model": "PIU",
                "build_type": "Patrol",
                "quantity": 1,
                "individuals": [{
                    "individual_id": vehicle.individual_id,
                    "unit_number": "",
                    "vin": "ACTUAL123456",
                }],
            }],
        }, paths)

        assert result["ok"] is True
        saved_group = load_project(project.project_id, paths).build_units[0]
        saved = saved_group.individuals[0]
        assert saved_group.shop_group_folder_id == "shop-group-id"
        assert saved_group.shop_group_folder_path == "Shop/Original Group"
        assert saved.draft_id == "draft-id"
        assert saved.qb_project_id == "70995"
        assert saved.shop_vehicle_folder_id == "shop-vehicle-id"
        assert saved.shop_vehicle_folder_path == "Shop/Original Group/Unit 02"
        assert saved.company_vehicle_folder_id == "company-vehicle-id"
        assert saved.existing_year == "2018"
        assert saved.existing_make == "Ford"
        assert saved.existing_model == "Police Interceptor Utility"
        assert saved.existing_build_type == "Patrol"
        assert saved.existing_unit_number == "03"
        assert saved.existing_vin == "OLDVIN654321"
        assert saved.unit_number == ""
        assert saved.vin == "ACTUAL123456"

    def test_explicit_existing_vehicle_clear_is_accepted(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["build_units"][0]["individuals"] = [{
            "individual_id": "vehicle-1",
            "existing_year": "2018",
            "existing_make": "Ford",
            "existing_model": "PIU",
            "existing_build_type": "Patrol",
            "existing_unit_number": "03",
            "existing_vin": "OLDVIN654321",
        }]
        created = handle_save_project(body, paths)
        project = load_project(created["project_id"], paths)
        unit = project.build_units[0]

        raw_individual = {
            "individual_id": "vehicle-1",
            "existing_year": "",
            "existing_make": "",
            "existing_model": "",
            "existing_build_type": "",
            "existing_unit_number": "",
            "existing_vin": "",
        }
        result = handle_save_project({
            "project_id": project.project_id,
            "build_units": [{
                "unit_id": unit.unit_id,
                "vehicle_model": unit.vehicle_model,
                "build_type": unit.build_type,
                "quantity": 1,
                "individuals": [raw_individual],
            }],
        }, paths)

        assert result["ok"] is True
        saved = load_project(project.project_id, paths).build_units[0].individuals[0]
        assert saved.existing_year == ""
        assert saved.existing_make == ""
        assert saved.existing_model == ""
        assert saved.existing_build_type == ""
        assert saved.existing_unit_number == ""
        assert saved.existing_vin == ""

    def test_project_edit_refreshes_linked_draft_vehicle_fields(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["build_units"][0]["quantity"] = 1
        body["build_units"][0]["individuals"] = [{
            "individual_id": "vehicle-1",
            "unit_number": "STALE",
            "vin": "STALEVIN",
        }]
        created = handle_save_project(body, paths)
        draft_result = handle_create_individual_draft(
            created["project_id"], "unit-1", "vehicle-1", paths,
        )
        project = load_project(created["project_id"], paths)
        individual = project.build_units[0].individuals[0]
        individual.unit_number = ""
        individual.vin = "1FM5K8AB3TGB76739"
        individual.existing_year = "2018"
        individual.existing_make = "Ford"
        individual.existing_model = "Police Interceptor Utility"
        individual.existing_build_type = "Patrol"
        individual.existing_unit_number = "03"
        individual.existing_vin = "1FM5K8AR7JGB19177"
        individual.notes = "Leave room for the customer's mobile data terminal."

        result = handle_save_project(asdict(project), paths)

        assert result["ok"] is True
        draft = load_draft(draft_result["draft_id"], paths.workspace_drafts_dir)
        assert draft.vehicle_info["NewVehicle"]["UNIT ID"] == ""
        assert draft.vehicle_info["NewVehicle"]["VIN"] == "1FM5K8AB3TGB76739"
        assert draft.vehicle_info["ExistingVehicle"] == {
            "YEAR": "2018",
            "MAKE": "Ford",
            "MODEL": "Police Interceptor Utility",
            "BUILD TYPE": "Patrol",
            "UNIT ID": "03",
            "VIN": "1FM5K8AR7JGB19177",
        }
        assert draft.vehicle_info["CanonicalVehicleName"].endswith("VIN B76739")
        assert draft.vehicle_info["UnitNotes"] == (
            "Leave room for the customer's mobile data terminal."
        )

    def test_unsafe_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project({"project_id": "../escape"}, paths)
        assert result["ok"] is False
        assert "error" in result

    def test_returns_path(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)
        assert "path" in result

    def test_new_project_requires_build_year(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["customer"]["build_year"] = ""

        result = handle_save_project(body, paths)

        assert result == {
            "ok": False,
            "error_code": "build_year_required",
            "error": "Build year is required for a new project.",
        }

    def test_rejects_duplicate_agency_year_and_returns_existing_project(self, tmp_path):
        paths = _paths(tmp_path)
        agency = handle_save_agency({"name": "Alpha PD"}, paths)["agency"]
        first_body = _project_body(customer={
            "agency": "Alpha PD",
            "agency_id": agency["agency_id"],
            "build_year": "2026",
            "quote_number": "Q-100",
        })
        first = handle_save_project(first_body, paths)
        second_body = _project_body(customer={
            "agency": "Renamed Alpha Police Department",
            "agency_id": agency["agency_id"],
            "build_year": "2026",
            "quote_number": "Q-101",
        })

        second = handle_save_project(second_body, paths)

        assert second["ok"] is False
        assert second["error_code"] == "project_exists_for_agency_year"
        assert second["existing_project_id"] == first["project_id"]
        assert len(handle_list_projects(paths)["projects"]) == 1

    def test_same_agency_can_have_separate_build_years(self, tmp_path):
        paths = _paths(tmp_path)
        agency = handle_save_agency({"name": "Alpha PD"}, paths)["agency"]
        first = handle_save_project(_project_body(customer={
            "agency": "Alpha PD", "agency_id": agency["agency_id"], "build_year": "2026",
        }), paths)
        second = handle_save_project(_project_body(customer={
            "agency": "Alpha PD", "agency_id": agency["agency_id"], "build_year": "2027",
        }), paths)

        assert first["ok"] is True
        assert second["ok"] is True

    def test_quote_number_is_preserved_as_project_metadata(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_save_project(_project_body(), paths)

        project = load_project(result["project_id"], paths)

        assert project.quote_numbers == ["Q-001"]
        assert result["path"].endswith("project.json")

    def test_sparse_past_vehicle_can_be_saved_without_build_identity(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["customer"]["build_year"] = "2018"
        body["build_units"][0]["individuals"] = [{
            "individual_id": "archive-1",
            "model": "Tahoe",
        }]

        result = handle_save_project(body, paths)

        assert result["ok"] is True
        stored = load_project(result["project_id"], paths).build_units[0].individuals[0]
        assert stored.model == "Tahoe"
        assert stored.draft_id is None

# ── handle_get_project ─────────────────────────────────────────────────────────

class TestHandleGetProject:
    def test_returns_project_dict(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_get_project(pid, paths)
        assert result["ok"] is True
        assert result["project"]["project_id"] == pid
        assert result["project"]["customer"]["agency"] == "Test PD"

    def test_missing_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_get_project("nonexistent", paths)
        assert result["ok"] is False
        assert "error" in result

    def test_unsafe_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_get_project("../escape", paths)
        assert result["ok"] is False


# ── handle_list_projects ───────────────────────────────────────────────────────

class TestHandleListProjects:
    def test_empty_returns_empty_list(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_list_projects(paths)
        assert result["ok"] is True
        assert result["projects"] == []

    def test_lists_saved_projects(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_project(_project_body(), paths)
        handle_save_project(_project_body(customer={
            **_project_body()["customer"],
            "build_year": "2027",
        }), paths)
        result = handle_list_projects(paths)
        assert result["ok"] is True
        assert len(result["projects"]) == 2

    def test_each_item_has_required_keys(self, tmp_path):
        paths = _paths(tmp_path)
        handle_save_project(_project_body(), paths)
        result = handle_list_projects(paths)
        p = result["projects"][0]
        for key in ("project_id", "customer", "preferences", "build_units"):
            assert key in p


class TestProjectCompletion:
    def test_completed_project_moves_to_archive_state_and_can_be_reactivated(self, tmp_path):
        paths = _paths(tmp_path)
        created = handle_save_project(_project_body(), paths)
        project_id = created["project_id"]

        completed = handle_set_project_completion(
            project_id, {"completed": True, "actor": "Seth"}, paths,
        )

        assert completed["ok"] is True
        assert completed["project"]["project_status"] == "completed"
        assert completed["project"]["completed_at"]
        assert completed["project"]["completed_by"] == "Seth"
        stored = load_project(project_id, paths)
        assert stored.project_status == "completed"

        reopened = handle_set_project_completion(
            project_id, {"completed": False, "actor": "Seth"}, paths,
        )

        assert reopened["ok"] is True
        assert reopened["project"]["project_status"] == "active"
        assert reopened["project"]["completed_at"] == ""
        assert reopened["project"]["reactivated_at"]
        assert reopened["project"]["reactivated_by"] == "Seth"

    def test_completion_requires_boolean_and_existing_project(self, tmp_path):
        paths = _paths(tmp_path)

        assert handle_set_project_completion("missing", {"completed": "yes"}, paths) == {
            "ok": False, "error": "completed must be true or false",
        }
        assert handle_set_project_completion("missing", {"completed": True}, paths) == {
            "ok": False, "error": "Project not found: missing",
        }


# ── handle_delete_project ──────────────────────────────────────────────────────

class TestHandleDeleteProject:
    def test_deletes_project(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_delete_project(pid, paths)
        assert result["ok"] is True
        assert handle_get_project(pid, paths)["ok"] is False

    def test_missing_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_delete_project("nonexistent", paths)
        assert result["ok"] is False
        assert "error" in result

    def test_unsafe_id_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_delete_project("../escape", paths)
        assert result["ok"] is False


# ── handle_create_draft ────────────────────────────────────────────────────────

class TestHandleCreateDraft:
    def test_returns_ok_with_ids(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        assert result["ok"] is True
        assert result["draft_id"]
        assert result["project_id"] == pid
        assert result["unit_id"] == "unit-1"

    def test_draft_saved_to_disk(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft_id = result["draft_id"]
        draft = load_draft(draft_id, paths.workspace_drafts_dir)
        assert draft.draft_id == draft_id

    def test_draft_id_written_back_to_unit(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        project = load_project(pid, paths)
        assert project.build_units[0].draft_id == result["draft_id"]

    def test_vehicle_info_populated(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        info = draft.vehicle_info
        assert info["VehicleType"] == "Tahoe PPV"
        assert info["Agency"] == "Test PD"
        assert "QuoteNumber" not in info
        assert info["SalesRep"] == "Alice"
        assert info["BuildType"] == "Patrol"
        assert info["ProjectID"]

    def test_new_vehicle_block_set(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        nv = draft.vehicle_info.get("NewVehicle", {})
        assert nv.get("MODEL") == "Tahoe PPV"
        assert nv.get("UNIT ID") == "Group Build"
        assert draft.vehicle_info.get("ExistingVehicle") == {}

    def test_preset_parts_transferred(self, tmp_path):
        paths = _paths(tmp_path)
        # Seed a workspace preset (the cloud-synced cache stand-in) since
        # bundled presets no longer exist.
        paths.workspace_presets_dir.mkdir(parents=True, exist_ok=True)
        (paths.workspace_presets_dir / "patrol_piu_standard.json").write_text(
            json.dumps({
                "schema_version": 2,
                "preset_id": "patrol_piu_standard",
                "label": "Patrol PIU Standard",
                "vehicle_types": [],
                "agency_ids": [],
                "build_types": [],
                "tag": "",
                "parts": [{"name": "Headlight", "include": True}],
            })
        )
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert len(draft.parts) > 0

    def test_preset_retains_picker_skus_and_render_identity(self, tmp_path):
        paths = _paths(tmp_path)
        paths.workspace_presets_dir.mkdir(parents=True, exist_ok=True)
        (paths.workspace_presets_dir / "patrol_piu_standard.json").write_text(
            json.dumps({
                "schema_version": 3,
                "preset_id": "patrol_piu_standard",
                "label": "Patrol PIU Standard",
                "vehicle_types": [],
                "agency_ids": [],
                "build_types": [],
                "tag": "",
                "placement_overrides": {"front_interior_light_bar:front": {"dx": 0.1}},
                "parts": [{
                    "name": "Front Interior Light Bar",
                    "include": True,
                    "part_number": "Inner Edge FST",
                    "part_type": "front_interior_light_bar",
                    "components": [{"part_number": "BSFW50ZT", "quantity": 1}],
                    "picker_config": {"coverage": "full"},
                    "new_or_used": "Reused",
                }],
            })
        )
        create = handle_save_project(_project_body(), paths)
        result = handle_create_draft(create["project_id"], "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)

        assert draft.placement_overrides == {
            "front_interior_light_bar:front": {"dx": 0.1}
        }
        assert len(draft.parts) == 1
        part = draft.parts[0]
        assert part.part_type == "front_interior_light_bar"
        assert part.components == [{"part_number": "BSFW50ZT", "quantity": 1}]
        assert part.picker_config == {"coverage": "full"}
        assert part.new_or_used == "Reused"

    def test_individual_vehicle_retains_rich_preset_fields(self, tmp_path):
        paths = _paths(tmp_path)
        paths.workspace_presets_dir.mkdir(parents=True, exist_ok=True)
        (paths.workspace_presets_dir / "patrol_piu_standard.json").write_text(
            json.dumps({
                "schema_version": 3,
                "preset_id": "patrol_piu_standard",
                "label": "Patrol PIU Standard",
                "vehicle_types": [],
                "agency_ids": [],
                "build_types": [],
                "parts": [{
                    "name": "Rear Interior Light Bar",
                    "part_number": "Inner Edge RST",
                    "part_type": "rear_interior_light_bar",
                    "components": [{"part_number": "BS50ZT", "quantity": 1}],
                    "picker_config": {"coverage": "full"},
                }],
            })
        )
        body = _project_body()
        body["build_units"][0]["individuals"] = [{
            "individual_id": "vehicle-1",
            "unit_number": "101",
            "year": "2026",
            "vin": "ACTUAL123456",
            "existing_unit_number": "OLD-101",
            "existing_vin": "OLDVIN654321",
            "existing_year": "2018",
            "existing_make": "Ford",
            "existing_model": "Police Interceptor Utility",
            "existing_build_type": "Patrol",
        }]
        create = handle_save_project(body, paths)
        result = handle_create_individual_draft(
            create["project_id"], "unit-1", "vehicle-1", paths
        )
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)

        assert draft.parts[0].part_type == "rear_interior_light_bar"
        assert draft.parts[0].components == [
            {"part_number": "BS50ZT", "quantity": 1}
        ]
        assert draft.parts[0].picker_config == {"coverage": "full"}
        assert draft.vehicle_info["NewVehicle"]["VIN"] == "ACTUAL123456"
        assert draft.vehicle_info["ExistingVehicle"] == {
            "YEAR": "2018",
            "MAKE": "Ford",
            "MODEL": "Police Interceptor Utility",
            "BUILD TYPE": "Patrol",
            "UNIT ID": "OLD-101",
            "VIN": "OLDVIN654321",
        }

    def test_sparse_past_vehicle_can_be_configured_later(self, tmp_path):
        paths = _paths(tmp_path)
        project = new_project(build_units=[BuildUnit(
            unit_id="history",
            individuals=[IndividualUnit(individual_id="archive")],
        )])
        save_project(project, paths)

        result = handle_create_individual_draft(
            project.project_id, "history", "archive", paths,
        )

        assert result["ok"] is True
        assert result["draft_id"]

    def test_blank_custom_used_when_no_preset(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["build_units"][0]["preset_id"] = ""
        create = handle_save_project(body, paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        assert result["ok"] is True
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert draft.parts == []  # blank_custom has no parts

    def test_missing_preset_falls_back_to_blank(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["build_units"][0]["preset_id"] = "nonexistent-preset-xyz"
        create = handle_save_project(body, paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        assert result["ok"] is True

    def test_equipment_preferences_in_notes(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        pref_notes = draft.notes.get("EQUIPMENT PREFERENCES", [])
        combined = " ".join(pref_notes)
        assert "Whelen" in combined
        assert "Code 3" in combined
        assert "Axon" in combined
        assert "Slick top: Yes" in combined

    def test_draft_converts_to_project_input(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        project_input = draft_to_project_input(draft)
        assert project_input.info["VehicleType"] == "Tahoe PPV"
        assert project_input.info["Agency"] == "Test PD"
        assert project_input.info["ProjectID"]
        assert isinstance(project_input.parts, list)

    def test_missing_project_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        result = handle_create_draft("nonexistent-project", "unit-1", paths)
        assert result["ok"] is False
        assert "error" in result

    def test_missing_unit_returns_error(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "no-such-unit", paths)
        assert result["ok"] is False
        assert "error" in result

    def test_project_id_uses_persistent_project_id(self, tmp_path):
        paths = _paths(tmp_path)
        body = _project_body()
        body["customer"]["quote_number"] = "Q-999"
        create = handle_save_project(body, paths)
        pid = create["project_id"]
        result = handle_create_draft(pid, "unit-1", paths)
        draft = load_draft(result["draft_id"], paths.workspace_drafts_dir)
        assert draft.vehicle_info["ProjectID"] == pid

    def test_second_create_draft_updates_draft_id(self, tmp_path):
        paths = _paths(tmp_path)
        create = handle_save_project(_project_body(), paths)
        pid = create["project_id"]
        result1 = handle_create_draft(pid, "unit-1", paths)
        result2 = handle_create_draft(pid, "unit-1", paths)
        project = load_project(pid, paths)
        # The unit's draft_id should reflect the most recent creation
        assert project.build_units[0].draft_id == result2["draft_id"]
