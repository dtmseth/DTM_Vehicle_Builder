from __future__ import annotations

from dtm_buildsheet.domain.project_models import BuildUnit, CustomerInfo, IndividualUnit
from dtm_buildsheet.domain.vehicle_naming import (
    qb_project_name,
    unit_group_name,
    vehicle_display_name,
    vehicle_folder_name,
    vehicle_label_from_project_info,
    vehicle_model_label,
    vehicle_placeholder_identifier,
    vin_last_six,
)
from dtm_buildsheet.inputs.project_entry import new_project


def _project(unit: BuildUnit):
    return new_project(
        customer=CustomerInfo(agency="Test PD", build_year="2027"),
        build_units=[unit],
    )


def test_vehicle_name_includes_year_model_unit_and_vin_last_six():
    individual = IndividualUnit(
        individual_id="vehicle-1",
        unit_number="12",
        vin="1FM5K8AB0HGA123456",
        make="Ford",
        model="Police Interceptor Utility",
    )
    unit = BuildUnit(
        unit_id="group-1", vehicle_model="PIU", build_type="Patrol",
        individuals=[individual],
    )
    project = _project(unit)

    assert vehicle_display_name(project, unit, individual) == (
        "2027 TP PIU - Patrol - Unit 12 - VIN 123456"
    )
    assert qb_project_name(project, unit, individual) == (
        "2027 TP PIU | Patrol | Unit 12 | VIN 123456"
    )
    assert unit_group_name(project, unit) == "2027 TP PIU - Patrol Build(s)"


def test_vin_only_and_unit_only_names_remain_complete():
    vin_only = IndividualUnit(individual_id="vin", vin="ABC987654", model="Tahoe")
    unit_only = IndividualUnit(individual_id="unit", unit_number="77", model="Tahoe")
    group = BuildUnit(
        unit_id="group", vehicle_model="Tahoe", build_type="Patrol",
        individuals=[vin_only, unit_only],
    )
    project = _project(group)

    assert vehicle_display_name(project, group, vin_only) == "2027 TP Tahoe - Patrol - VIN 987654"
    assert vehicle_display_name(project, group, unit_only) == "2027 TP Tahoe - Patrol - Unit 77"


def test_sparse_vehicle_name_uses_stable_placeholder_identity():
    archive = IndividualUnit(individual_id="archive", model="Tahoe")
    group = BuildUnit(
        unit_id="historical", vehicle_model="Tahoe", build_type="Command",
        individuals=[archive],
    )

    assert vehicle_placeholder_identifier(archive) == "Pending ID ARCHIVE"
    assert vehicle_display_name(_project(group), group, archive) == (
        "2027 TP Tahoe - Command - Pending ID ARCHIVE"
    )


def test_model_label_does_not_repeat_make_or_vehicle_year():
    group = BuildUnit(unit_id="group", vehicle_model="2026 Ford Tahoe")
    individual = IndividualUnit(individual_id="one", make="Ford", model="2026 Ford Tahoe")
    assert vehicle_model_label(group, individual) == "Tahoe"

    expedition = BuildUnit(unit_id="expedition", vehicle_model="2026 Ford Expedition")
    assert vehicle_model_label(expedition) == "Expedition"

    lightning = BuildUnit(unit_id="lightning", vehicle_model="2026 Ford F-150 Lightning")
    assert vehicle_model_label(lightning) == "Lightning"
    lightning_project = _project(lightning)
    assert unit_group_name(lightning_project, lightning) == "2027 TP Lightning - Build(s)"


def test_folder_sanitization_preserves_readable_identity():
    individual = IndividualUnit(individual_id="one", unit_number="12/3", model="Tahoe")
    group = BuildUnit(unit_id="group", vehicle_model="Tahoe", individuals=[individual])
    assert vehicle_folder_name(_project(group), group, individual) == "2027 TP Tahoe - Unit 12 3"


def test_folder_sanitization_preserves_ampersands():
    from dtm_buildsheet.domain.vehicle_naming import safe_vehicle_folder_name
    assert safe_vehicle_folder_name("Immigration & Customs") == "Immigration & Customs"


def test_project_info_fallback_uses_last_six_vin():
    assert vehicle_label_from_project_info({
        "BuildYear": "2027",
        "VehicleType": "PIU",
        "NewVehicle": {"MODEL": "2026 Ford PIU", "VIN": "ABC123456"},
    }) == "2027 PIU - VIN 123456"
    assert vin_last_six("1 fm-abc123456") == "123456"


def test_existing_vehicle_identifiers_never_become_build_identity():
    individual = IndividualUnit(
        individual_id="actual-vehicle",
        existing_unit_number="OLD-12",
        existing_vin="OLDVIN654321",
        model="Tahoe",
    )
    group = BuildUnit(
        unit_id="group", vehicle_model="Tahoe", build_type="Patrol",
        individuals=[individual],
    )
    project = _project(group)

    assert vehicle_display_name(project, group, individual) == (
        "2027 TP Tahoe - Patrol - Pending ID ACTUALVE"
    )
    assert qb_project_name(project, group, individual) == (
        "2027 TP Tahoe | Patrol | Pending ID ACTUALVE"
    )
    assert vehicle_label_from_project_info({
        "BuildYear": "2027",
        "VehicleType": "Tahoe",
        "NewVehicle": {},
        "ExistingVehicle": {"UNIT ID": "OLD-12", "VIN": "OLDVIN654321"},
    }) == "2027 Tahoe - Group Build"

    individual.vin = "ACTUAL123456"
    assert vehicle_display_name(project, group, individual) == (
        "2027 TP Tahoe - Patrol - VIN 123456"
    )
