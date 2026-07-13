"""Tests for domain/project_codec.py — the shared serialization layer."""
from __future__ import annotations

import pytest

from dtm_buildsheet.domain.project_codec import (
    build_unit_from_dict,
    customer_from_dict,
    individual_unit_from_dict,
    preferences_from_dict,
    project_from_dict,
)
from dtm_buildsheet.domain.project_models import (
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
            "quote_number": "Q-1", "build_year": "2026",
            "sales_rep": "Bob", "sales_rep_id": "r1",
            "contact": "Jane", "phone": "555-1234", "email": "j@pd.gov",
        }
        c = customer_from_dict(d)
        assert isinstance(c, CustomerInfo)
        assert c.name == "John"
        assert c.agency == "City PD"
        assert c.agency_id == "a1"
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


class TestPreferencesFromDict:
    def test_all_fields(self):
        d = {
            "lighting_brands": ["Whelen", "Code 3"],
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
        assert p.camera_brand == "Axon"
        assert p.cage_brand == "Jotto Desk"
        assert p.console_brand == "Gamber Johnson"
        assert p.slick_top is True
        assert p.mixed_brands is True
        assert p.notes == "custom note"

    def test_missing_lighting_brands_defaults_to_empty_list(self):
        p = preferences_from_dict({})
        assert p.lighting_brands == []

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
            "color": "White", "vin": "VIN123",
        }
        ind = individual_unit_from_dict(d)
        assert isinstance(ind, IndividualUnit)
        assert ind.individual_id == "i1"
        assert ind.unit_number == "U001"
        assert ind.make == "Ford"

    def test_missing_individual_id_auto_generated(self):
        ind = individual_unit_from_dict({"unit_number": "U1"})
        assert ind.individual_id  # UUID auto-generated

    def test_draft_id_none_when_absent(self):
        ind = individual_unit_from_dict({"individual_id": "i1"})
        assert ind.draft_id is None

    def test_draft_id_preserved(self):
        ind = individual_unit_from_dict({"individual_id": "i1", "draft_id": "d-abc"})
        assert ind.draft_id == "d-abc"

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

    def test_non_dict_raises(self):
        with pytest.raises(ValueError):
            build_unit_from_dict("bad")


class TestProjectFromDict:
    def test_minimal_required_fields(self):
        d = {"project_id": "p1", "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"}
        p = project_from_dict(d)
        assert isinstance(p, ProjectRecord)
        assert p.project_id == "p1"
        assert p.build_units == []

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
