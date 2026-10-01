from __future__ import annotations

import json
from dataclasses import asdict

from dtm_buildsheet.app.services import vehicle_catalog_service
from dtm_buildsheet.app.services.project_service import _preserve_server_owned_build_state
from dtm_buildsheet.domain.project_codec import build_unit_from_dict
from tools import migrate_vehicle_identities


class _Response:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size: int) -> bytes:
        return self._raw

    def geturl(self) -> str:
        return "https://vpic.nhtsa.dot.gov/api/vehicles/GetAllMakes?format=json"


def test_legacy_vehicle_model_translates_to_richer_identity():
    unit = build_unit_from_dict({"unit_id": "u1", "vehicle_model": "PIU"})

    assert unit.vehicle_model == "PIU"
    assert asdict(unit.vehicle_identity) == {
        "source": "legacy",
        "model_year": "",
        "make": "",
        "model": "PIU",
        "package": "",
        "category": "automobile",
        "catalog_source": "",
        "catalog_make_id": "",
        "catalog_model_id": "",
        "layout_id": "PIU",
        "display_name": "PIU",
    }


def test_catalog_identity_round_trips_and_backfills_legacy_layout_id():
    unit = build_unit_from_dict({
        "unit_id": "u2",
        "vehicle_identity": {
            "source": "catalog",
            "model_year": "2026",
            "make": "Dodge",
            "model": "Durango",
            "package": "Pursuit",
            "catalog_source": "NHTSA vPIC",
            "layout_id": "DURANGO",
        },
    })

    assert unit.vehicle_model == "DURANGO"
    assert unit.vehicle_identity.display_name == "2026 Dodge Durango Pursuit"


def test_legacy_group_uses_consistent_individual_vehicle_fields_for_translation():
    unit = build_unit_from_dict({
        "unit_id": "u3", "vehicle_model": "PIU",
        "individuals": [
            {"individual_id": "i1", "year": "2025", "make": "Ford", "model": "Police Interceptor Utility"},
            {"individual_id": "i2", "year": "2025", "make": "Ford", "model": "Police Interceptor Utility"},
        ],
    })

    assert unit.vehicle_identity.model_year == "2025"
    assert unit.vehicle_identity.make == "Ford"
    assert unit.vehicle_identity.model == "Police Interceptor Utility"


def test_older_edit_payload_preserves_saved_identity_when_layout_is_unchanged():
    existing = build_unit_from_dict({
        "unit_id": "u2", "vehicle_model": "DURANGO",
        "vehicle_identity": {"source": "catalog", "model_year": "2026", "make": "Dodge", "model": "Durango", "package": "Pursuit", "layout_id": "DURANGO"},
    })
    incoming = build_unit_from_dict({"unit_id": "u2", "vehicle_model": "DURANGO"})

    _preserve_server_owned_build_state(
        [existing], [incoming], [{"unit_id": "u2", "vehicle_model": "DURANGO"}],
    )

    assert incoming.vehicle_identity.package == "Pursuit"
    assert incoming.vehicle_identity.model_year == "2026"


def test_police_overlay_includes_quick_choices_and_special_service_models():
    vehicles = vehicle_catalog_service.list_police_vehicles()
    names = {(item["make"], item["model"], item["package"]) for item in vehicles}

    assert ("Ford", "Police Interceptor Utility", "") in names
    assert ("Dodge", "Durango", "Pursuit") in names
    assert ("Chevrolet", "Tahoe", "PPV") in names
    assert ("Chevrolet", "Tahoe", "SSV") in names
    assert ("Ford", "F-150", "Police Responder") in names
    assert ("Ford", "F-150 Lightning", "SSV") in names
    assert ("Ford", "Transit", "PTV") in names
    assert ("Jeep", "Wagoneer", "Command Operations Vehicle") in names


def test_police_overlay_is_bounded_to_actual_model_years():
    names_2026 = {
        (item["make"], item["model"], item["package"])
        for item in vehicle_catalog_service.list_police_vehicles(2026)
    }
    names_2027 = {
        (item["make"], item["model"], item["package"])
        for item in vehicle_catalog_service.list_police_vehicles(2027)
    }

    assert ("Ford", "Police Interceptor Utility", "") in names_2026
    assert ("Chevrolet", "Silverado 1500", "PPV") in names_2026
    assert ("Ford", "F-150", "Police Responder") not in names_2026
    assert ("Chevrolet", "Tahoe", "PPV") in names_2027
    assert ("Ram", "2500 HD", "Emergency Response Vehicle") in names_2027
    assert ("Dodge", "Charger", "PPV") in names_2027
    assert next(
        item for item in vehicle_catalog_service.list_police_vehicles(2027)
        if item["make"] == "Dodge" and item["model"] == "Charger"
    )["availability"] == "upcoming"
    assert ("Dodge", "Durango", "Pursuit") not in names_2027


def test_nhtsa_results_are_deduplicated_and_normalized(monkeypatch):
    vehicle_catalog_service._CACHE.clear()
    payload = {"Results": [
        {"Make_ID": 460, "Make_Name": " Ford "},
        {"Make_ID": 999, "Make_Name": "FORD"},
        {"Make_ID": 0, "Make_Name": ""},
        {"Make_ID": 467, "Make_Name": "Chevrolet"},
    ]}
    monkeypatch.setattr(vehicle_catalog_service, "urlopen", lambda *_args, **_kwargs: _Response(payload))

    assert vehicle_catalog_service.list_makes(2026) == [
        {"id": "467", "name": "Chevrolet", "vehicle_types": ["Car", "Truck", "SUV / MPV"], "is_specialty": False},
        {"id": "999", "name": "Ford", "vehicle_types": ["Car", "Truck", "SUV / MPV"], "is_specialty": False},
    ]


def test_make_search_keeps_specialty_manufacturers_searchable_and_tagged(monkeypatch):
    vehicle_catalog_service._CACHE.clear()

    def fake_urlopen(request, **_kwargs):
        url = request.full_url
        if "api.nhtsa.gov/products" in url:
            rows = [{"make": "Ford"}, {"make": "Yamaha"}]
        elif "GetAllMakes" in url:
            rows = [
                {"Make_ID": 460, "Make_Name": "Ford"},
                {"Make_ID": 474, "Make_Name": "Yamaha"},
            ]
        elif "Motorcycle" in url:
            rows = [{"MakeId": 474, "MakeName": "Yamaha"}]
        elif any(value in url for value in ("Passenger%20Car", "Truck", "Multipurpose")):
            rows = [{"MakeId": 460, "MakeName": "Ford"}]
        else:
            rows = []
        response = _Response({"Results": rows})
        response.geturl = lambda: url
        return response

    monkeypatch.setattr(vehicle_catalog_service, "urlopen", fake_urlopen)

    assert vehicle_catalog_service.list_makes(2026) == [
        {"id": "460", "name": "Ford", "vehicle_types": ["Car", "Truck", "SUV / MPV"], "is_specialty": False},
    ]
    assert vehicle_catalog_service.list_makes(2026, "yama") == [
        {"id": "474", "name": "Yamaha", "vehicle_types": ["Motorcycle"], "is_specialty": True},
    ]


def test_make_menu_omits_automotive_make_without_models_for_year(monkeypatch):
    vehicle_catalog_service._CACHE.clear()

    def fake_urlopen(request, **_kwargs):
        url = request.full_url
        if "api.nhtsa.gov/products" in url:
            rows = [{"make": "Ford"}]
        elif "GetAllMakes" in url:
            rows = [
                {"Make_ID": 460, "Make_Name": "Ford"},
                {"Make_ID": 441, "Make_Name": "Tesla"},
            ]
        elif any(value in url for value in ("Passenger%20Car", "Truck", "Multipurpose")):
            rows = [
                {"MakeId": 460, "MakeName": "Ford"},
                {"MakeId": 441, "MakeName": "Tesla"},
            ]
        else:
            rows = []
        response = _Response({"Results": rows})
        response.geturl = lambda: url
        return response

    monkeypatch.setattr(vehicle_catalog_service, "urlopen", fake_urlopen)

    assert [item["name"] for item in vehicle_catalog_service.list_makes(2026)] == ["Ford"]


def test_models_for_automotive_make_use_vehicle_type_filtered_endpoint(monkeypatch):
    vehicle_catalog_service._CACHE.clear()
    requested: list[str] = []

    def fake_urlopen(request, **_kwargs):
        url = request.full_url
        requested.append(url)
        if "GetMakesForVehicleType/Passenger%20Car" in url:
            rows = [{"MakeId": 474, "MakeName": "Honda"}]
        elif "GetModelsForMakeYear" in url and "vehicletype/Passenger%20Car" in url:
            rows = [{"Model_ID": 1861, "Model_Name": "Accord"}]
        else:
            rows = []
        response = _Response({"Results": rows})
        response.geturl = lambda: url
        return response

    monkeypatch.setattr(vehicle_catalog_service, "urlopen", fake_urlopen)

    assert vehicle_catalog_service.list_models(2026, "Honda") == [
        {"id": "1861", "name": "Accord", "vehicle_types": ["Car"], "is_specialty": False},
    ]
    assert all("GetModelsForMakeYear" not in url or "vehicletype" in url for url in requested)


def test_picker_uses_clear_layout_language_and_custom_categories():
    source = open("src/dtm_buildsheet/ui/js/projects/vehicle_picker.js", encoding="utf-8").read()
    styles = open("src/dtm_buildsheet/ui/styles.css", encoding="utf-8").read()

    assert "Vehicle layout available" in source
    assert "Vehicle layout needed" in source
    assert "Snowmobile" in source and "ATV / UTV" in source and "Trailer" in source
    assert "vehicle-search-input" in source and "vehicle-type-tag" in source
    assert 'data-vehicle-search="year"' in source
    assert 'data-vehicle-search="package"' in source
    assert 'packageField.hidden = !packageItems.length' in source
    assert "updateQuickChoices" not in source
    assert 'data-police-quick="Dodge|Charger|PPV"' in source
    assert "const makeChoices = await fetchMakes(selectedMake)" not in source
    assert "requires no" in source and "external catalog request" in source
    assert '_ptSetVehicleSearchValue(picker, "make", makeOption)' in source
    assert '_ptSetVehicleSearchValue(picker, "model", modelOption)' in source
    assert "clip-path:polygon" in styles
    assert ".proj-unit-header,.proj-edit-unit-hdr" in styles


def test_vehicle_identity_migration_uses_exact_layout_and_preserves_legacy_id():
    unit = {
        "unit_id": "u1", "vehicle_model": "PIU",
        "individuals": [{"year": "2026", "make": "", "model": "PIU"}],
    }
    layouts = {"piu": {"make": "Ford", "model": "Police Interceptor Utility"}}

    identity, reason = migrate_vehicle_identities._identity_for(unit, layouts)

    assert reason == ""
    assert identity["model_year"] == "2026"
    assert identity["make"] == "Ford"
    assert identity["model"] == "Police Interceptor Utility"
    assert identity["package"] == ""
    assert identity["layout_id"] == "PIU"
    assert "vehicle_identity" not in unit


def test_vehicle_identity_migration_refuses_mixed_or_conflicting_data():
    layouts = {"tahoe": {"make": "Chevrolet", "model": "Tahoe"}}
    mixed_year = {
        "vehicle_model": "TAHOE",
        "individuals": [
            {"year": "2025", "make": "Chevrolet", "model": "Tahoe"},
            {"year": "2026", "make": "Chevrolet", "model": "Tahoe"},
        ],
    }
    conflicting_model = {
        "vehicle_model": "TAHOE",
        "individuals": [{"year": "2025", "make": "Chevrolet", "model": "Tahoe & Silverado"}],
    }

    assert migrate_vehicle_identities._identity_for(mixed_year, layouts)[0] is None
    assert migrate_vehicle_identities._identity_for(conflicting_model, layouts)[0] is None
