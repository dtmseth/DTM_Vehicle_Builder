"""Tests for domain/project_codec.py — the shared serialization layer."""
from __future__ import annotations

import pytest

from dtm_buildsheet.domain.project_codec import (
    build_unit_from_dict,
    customer_from_dict,
    individual_unit_from_dict,
    preferences_from_dict,
    project_from_dict,
    reference_asset_from_dict,
    reference_assignment_from_dict,
)
from dtm_buildsheet.domain.project_models import (
    BuildReferenceAsset,
    BuildReferenceAssignment,
    BuildUnit,
    CustomerInfo,
    EquipmentPreferences,
    IndividualUnit,
    ProjectRecord,
)


class TestCustomerFromDict:
    def test_all_fields(self):
        d = {
            "name": "John", "agency": "City PD", "agency_id": "a1",
            "agency_abbreviation": "CPD",
            "quote_number": "Q-1", "build_year": "2026",
            "sales_rep": "Bob", "sales_rep_id": "r1",
            "contact": "Jane", "phone": "555-1234", "email": "j@pd.gov",
        }
        c = customer_from_dict(d)
        assert isinstance(c, CustomerInfo)
        assert c.name == "John"
        assert c.agency == "City PD"
        assert c.agency_id == "a1"
        assert c.agency_abbreviation == "CPD"
        assert c.sales_rep == "Bob"
        assert c.email == "j@pd.gov"

    def test_missing_fields_default_to_empty_string(self):
        c = customer_from_dict({})
        assert c.name == ""
        assert c.agency == ""
        assert c.email == ""

    def test_non_dict_returns_default(self):
        assert customer_from_dict(None) == CustomerInfo()
        assert customer_from_dict("bad") == CustomerInfo()
        assert customer_from_dict(42) == CustomerInfo()

    def test_legacy_customer_derives_agency_abbreviation_without_write_migration(self):
        assert customer_from_dict({
            "agency": "Custer County Sheriff",
        }).agency_abbreviation == "Custer"


class TestPreferencesFromDict:
    def test_all_fields(self):
        d = {
            "lighting_brands": ["Whelen", "Code 3"],
            "lighting_mode": "trio",
            "camera_brand": "Axon",
            "push_bumper_brand": "Setina",
            "cage_brand": "Jotto Desk",
            "console_brand": "Gamber Johnson",
            "slick_top": True,
            "mixed_brands": True,
            "notes": "custom note",
        }
        p = preferences_from_dict(d)
        assert isinstance(p, EquipmentPreferences)
        assert p.lighting_brands == ["Whelen", "Code 3"]
        assert p.lighting_mode == "trio"
        assert p.camera_brand == "Axon"
        assert p.cage_brand == "Jotto Desk"
        assert p.console_brand == "Gamber Johnson"
        assert p.slick_top is True
        assert p.mixed_brands is True
        assert p.notes == "custom note"

    def test_missing_lighting_brands_defaults_to_empty_list(self):
        p = preferences_from_dict({})
        assert p.lighting_brands == []
        assert p.lighting_mode == "duo"

    def test_invalid_lighting_mode_defaults_to_duo(self):
        assert preferences_from_dict({"lighting_mode": "quad"}).lighting_mode == "duo"

    def test_non_list_lighting_brands_defaults_to_empty(self):
        p = preferences_from_dict({"lighting_brands": "Whelen"})
        assert p.lighting_brands == []

    def test_non_dict_returns_default(self):
        assert preferences_from_dict(None) == EquipmentPreferences()


class TestIndividualUnitFromDict:
    def test_basic_fields(self):
        d = {
            "individual_id": "i1", "unit_number": "U001",
            "year": "2024", "make": "Ford", "model": "Interceptor",
            "color": "White", "vin": "VIN123", "qb_project_id": "447322633",
            "existing_year": "2018", "existing_make": "Ford",
            "existing_model": "Police Interceptor Utility",
            "existing_build_type": "Patrol",
            "existing_unit_number": "03", "existing_vin": "OLDVIN123",
            "qb_estimate_snapshot": {"doc_number": "1001", "lines": []},
            "qb_estimate_snapshot_at": "2026-08-21T12:00:00Z",
        }
        ind = individual_unit_from_dict(d)
        assert isinstance(ind, IndividualUnit)
        assert ind.individual_id == "i1"
        assert ind.unit_number == "U001"
        assert ind.make == "Ford"
        assert ind.existing_year == "2018"
        assert ind.existing_make == "Ford"
        assert ind.existing_model == "Police Interceptor Utility"
        assert ind.existing_build_type == "Patrol"
        assert ind.existing_unit_number == "03"
        assert ind.existing_vin == "OLDVIN123"
        assert ind.qb_project_id == "447322633"
        assert ind.qb_estimate_snapshot == {"doc_number": "1001", "lines": []}
        assert ind.qb_estimate_snapshot_at == "2026-08-21T12:00:00Z"

    def test_missing_individual_id_auto_generated(self):
        ind = individual_unit_from_dict({"unit_number": "U1"})
        assert ind.individual_id  # UUID auto-generated

    def test_draft_id_none_when_absent(self):
        ind = individual_unit_from_dict({"individual_id": "i1"})
        assert ind.draft_id is None

    def test_draft_id_preserved(self):
        ind = individual_unit_from_dict({"individual_id": "i1", "draft_id": "d-abc"})
        assert ind.draft_id == "d-abc"

    def test_vehicle_folder_and_publication_identity_round_trips(self):
        ind = individual_unit_from_dict({
            "individual_id": "i1",
            "company_vehicle_folder_id": "company-folder",
            "company_vehicle_folder_name": "2027 Tahoe - Patrol - Unit 1",
            "company_pdf_item_id": "company-pdf",
            "company_pdf_path": "Vehicle Project Database/Agency/2027/Patrol/Unit 1/Unit 1.pdf",
            "company_publication_fingerprint": "company-hash",
            "company_publication_status": "published",
            "shop_vehicle_folder_id": "shop-folder",
            "shop_pdf_item_id": "shop-pdf",
            "shop_pdf_path": "Build Photos/Agency/2027/Patrol/Unit 1/Unit 1.pdf",
            "shop_publication_fingerprint": "shop-hash",
            "shop_publication_status": "published",
            "shop_reference_items": [{"item_id": "ref-1", "reference_id": "source-1"}],
        })
        assert ind.company_vehicle_folder_id == "company-folder"
        assert ind.company_pdf_item_id == "company-pdf"
        assert ind.company_publication_fingerprint == "company-hash"
        assert ind.shop_vehicle_folder_id == "shop-folder"
        assert ind.shop_pdf_item_id == "shop-pdf"
        assert ind.shop_reference_items == [{"item_id": "ref-1", "reference_id": "source-1"}]

    def test_non_dict_raises(self):
        with pytest.raises(ValueError):
            individual_unit_from_dict("bad")


class TestBuildUnitFromDict:
    def test_basic_fields(self):
        d = {
            "unit_id": "u1", "vehicle_model": "Tahoe PPV",
            "build_type": "Patrol", "preset_id": "p1",
            "quantity": 3,
        }
        u = build_unit_from_dict(d)
        assert isinstance(u, BuildUnit)
        assert u.unit_id == "u1"
        assert u.vehicle_model == "Tahoe PPV"
        assert u.quantity == 3

    def test_quantity_normalized_to_minimum_one(self):
        assert build_unit_from_dict({"unit_id": "u1", "quantity": 0}).quantity == 1
        assert build_unit_from_dict({"unit_id": "u1", "quantity": -3}).quantity == 1

    def test_missing_unit_id_auto_generated(self):
        u = build_unit_from_dict({"vehicle_model": "Explorer"})
        assert u.unit_id

    def test_individuals_parsed(self):
        d = {
            "unit_id": "u1",
            "individuals": [{"individual_id": "i1"}, {"individual_id": "i2"}],
        }
        u = build_unit_from_dict(d)
        assert len(u.individuals) == 2

    def test_non_dict_individuals_skipped(self):
        d = {"unit_id": "u1", "individuals": ["not-a-dict", {"individual_id": "i1"}]}
        u = build_unit_from_dict(d)
        assert len(u.individuals) == 1

    def test_group_folder_identity_round_trips(self):
        u = build_unit_from_dict({
            "unit_id": "u1",
            "company_group_folder_id": "company-group",
            "company_group_folder_path": "Vehicle Project Database/Agency/APD - 2027/group",
            "shop_group_folder_id": "shop-group",
            "shop_group_folder_path": "Shop Project Database/Agency/APD - 2027/group",
        })
        assert u.company_group_folder_id == "company-group"
        assert u.company_group_folder_path.endswith("/group")
        assert u.shop_group_folder_id == "shop-group"

    def test_non_dict_raises(self):
        with pytest.raises(ValueError):
            build_unit_from_dict("bad")


class TestBuildReferencesFromDict:
    def test_assignment_normalizes_scope_and_order(self):
        assignment = reference_assignment_from_dict({
            "scope": "INDIVIDUAL",
            "target_id": "vehicle-1",
            "note": "  Match this bracket. ",
            "sort_order": "4",
        })

        assert assignment == BuildReferenceAssignment(
            scope="individual",
            target_id="vehicle-1",
            note="Match this bracket.",
            sort_order=4,
        )

    def test_project_assignment_clears_target(self):
        assignment = reference_assignment_from_dict({
            "scope": "project", "target_id": "stale-id",
        })
        assert assignment.target_id == ""

    def test_asset_parses_portable_identity_and_assignments(self):
        asset = reference_asset_from_dict({
            "reference_id": "photo-1",
            "file_name": "console.jpg",
            "media_type": "photo",
            "source_kind": "shop_completed",
            "source_drive_id": "drive-1",
            "source_item_id": "item-1",
            "source_path": "Agency/2025/Patrol/Unit 1/Completed Build Photos/console.jpg",
            "source_size": "1200",
            "assignments": [{"scope": "unit_group", "target_id": "group-1"}],
        })

        assert isinstance(asset, BuildReferenceAsset)
        assert asset.source_item_id == "item-1"
        assert asset.source_size == 1200
        assert asset.assignments == [
            BuildReferenceAssignment(scope="unit_group", target_id="group-1")
        ]

    def test_invalid_media_and_source_fall_back_safely(self):
        asset = reference_asset_from_dict({
            "reference_id": "bad", "media_type": "document", "source_kind": "internet",
        })
        assert asset.media_type == "photo"
        assert asset.source_kind == "company_reference"


class TestProjectFromDict:
    def test_minimal_required_fields(self):
        d = {"project_id": "p1", "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"}
        p = project_from_dict(d)
        assert isinstance(p, ProjectRecord)
        assert p.project_id == "p1"
        assert p.build_units == []
        assert p.project_status == "active"

    def test_completed_project_lifecycle_round_trip(self):
        p = project_from_dict({
            "project_id": "p1",
            "created_at": "t",
            "updated_at": "t",
            "project_status": "completed",
            "completed_at": "2026-08-27T12:00:00+00:00",
            "completed_by": "Seth",
        })

        assert p.project_status == "completed"
        assert p.completed_at == "2026-08-27T12:00:00+00:00"
        assert p.completed_by == "Seth"

    def test_unknown_project_status_falls_back_to_active(self):
        p = project_from_dict({
            "project_id": "p1", "created_at": "t", "updated_at": "t",
            "project_status": "deleted",
        })
        assert p.project_status == "active"

    def test_nested_customer_parsed(self):
        d = {
            "project_id": "p1", "created_at": "t", "updated_at": "t",
            "customer": {"name": "Alice", "agency": "PD"},
        }
        p = project_from_dict(d)
        assert p.customer.name == "Alice"
        assert p.customer.agency == "PD"

    def test_build_units_parsed(self):
        d = {
            "project_id": "p1", "created_at": "t", "updated_at": "t",
            "build_units": [{"unit_id": "u1", "vehicle_model": "Tahoe"}],
        }
        p = project_from_dict(d)
        assert len(p.build_units) == 1
        assert p.build_units[0].vehicle_model == "Tahoe"

    def test_legacy_export_dir_is_ignored(self):
        # ProjectRecord.export_dir was dropped in Phase 0. Old records that still
        # carry the field on disk must load without error; the value is discarded.
        d = {"project_id": "p1", "created_at": "t", "updated_at": "t", "export_dir": "/some/old/path"}
        p = project_from_dict(d)
        assert not hasattr(p, "export_dir")

    def test_legacy_quote_number_seeds_quote_numbers(self):
        p = project_from_dict({
            "project_id": "p1", "created_at": "t", "updated_at": "t",
            "customer": {"quote_number": "Q-100"},
        })
        assert p.quote_numbers == ["Q-100"]

    def test_missing_reference_assets_is_backward_compatible(self):
        p = project_from_dict({"project_id": "p1", "created_at": "t", "updated_at": "t"})
        assert p.reference_assets == []

    def test_reference_source_exclusions_round_trip(self):
        p = project_from_dict({
            "project_id": "p1",
            "created_at": "t",
            "updated_at": "t",
            "reference_source_exclusions": ["item:drive:item", "", None],
        })
        assert p.reference_source_exclusions == ["item:drive:item"]
