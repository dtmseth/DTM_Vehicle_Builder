"""Read-only vehicle catalog backed by the public NHTSA vPIC API."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

_BASE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles"
_PRODUCTS_BASE_URL = "https://api.nhtsa.gov/products/vehicle"
_ALLOWED_HOSTS = {"vpic.nhtsa.dot.gov", "api.nhtsa.gov"}
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_CACHE_SECONDS = 24 * 60 * 60
_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}
_CACHE_LOCK = threading.Lock()

_AUTOMOTIVE_TYPES = {
    "Passenger Car": "Car",
    "Truck": "Truck",
    "Multipurpose Passenger Vehicle (MPV)": "SUV / MPV",
}
_OTHER_TYPES = {
    "Motorcycle": "Motorcycle",
    "Bus": "Bus",
    "Trailer": "Trailer",
    "Low Speed Vehicle (LSV)": "Low-speed vehicle",
    "Incomplete Vehicle": "Incomplete vehicle",
    "Off Road Vehicle": "Off-road vehicle",
}
_COMMON_AUTOMOTIVE_MAKES = (
    "Acura", "Alfa Romeo", "Audi", "BMW", "Buick", "Cadillac", "Chevrolet",
    "Chrysler", "Dodge", "Fiat", "Ford", "Genesis", "GMC", "Honda", "Hyundai",
    "Infiniti", "Jaguar", "Jeep", "Kia", "Land Rover", "Lexus", "Lincoln",
    "Lucid", "Maserati", "Mazda", "Mercedes-Benz", "Mercury", "Mini",
    "Mitsubishi", "Nissan", "Oldsmobile", "Polestar", "Pontiac", "Porsche",
    "Ram", "Rivian", "Saab", "Saturn", "Scion", "Subaru", "Tesla", "Toyota",
    "Volkswagen", "Volvo",
)
_COMMON_MAKE_NAMES = {name.casefold(): name for name in _COMMON_AUTOMOTIVE_MAKES}

# Manufacturer-special-service packages are an overlay because vPIC catalogs
# production models, not the upfit/usage package attached to them.
POLICE_VEHICLES = (
    # Ford markets the Explorer-platform PI Utility as a purpose-built model,
    # not as an Explorer package, so its package value intentionally stays empty.
    {"make": "Ford", "model": "Police Interceptor Utility", "package": "", "from_year": 2013, "to_year": 2026, "quick_choice": True},
    {"make": "Dodge", "model": "Durango", "package": "Pursuit", "from_year": 2018, "to_year": 2026, "quick_choice": True},
    # Previewed at the 2026 Police Fleet Expo; keep visibly upcoming until
    # Stellantis publishes final ordering specifications.
    {"make": "Dodge", "model": "Charger", "package": "PPV", "from_year": 2027, "to_year": 2027, "quick_choice": True, "availability": "upcoming"},
    {"make": "Chevrolet", "model": "Tahoe", "package": "PPV", "from_year": 2015, "to_year": 2027, "quick_choice": True},
    {"make": "Chevrolet", "model": "Tahoe", "package": "SSV", "from_year": 2015, "to_year": 2027},
    {"make": "Ford", "model": "F-150", "package": "Police Responder", "from_year": 2018, "to_year": 2024},
    {"make": "Ford", "model": "F-150 Lightning", "package": "SSV", "from_year": 2023, "to_year": 2025},
    {"make": "Ford", "model": "Expedition", "package": "SSV", "from_year": 2018, "to_year": 2024},
    {"make": "Ford", "model": "Transit", "package": "PTV", "from_year": 2015, "to_year": 2024},
    {"make": "Chevrolet", "model": "Silverado 1500", "package": "PPV", "from_year": 2023, "to_year": 2026},
    {"make": "Chevrolet", "model": "Silverado 1500", "package": "SSV", "from_year": 2022, "to_year": 2026},
    {"make": "Chevrolet", "model": "Blazer EV", "package": "PPV", "from_year": 2024, "to_year": 2027},
    {"make": "Ram", "model": "1500", "package": "SSV", "from_year": 2012, "to_year": 2026},
    {"make": "Ram", "model": "2500", "package": "SSV", "from_year": 2014, "to_year": 2026},
    {"make": "Ram", "model": "3500", "package": "SSV", "from_year": 2014, "to_year": 2026},
    {"make": "Jeep", "model": "Wagoneer", "package": "Command Operations Vehicle", "from_year": 2025, "to_year": 2026},
    {"make": "Jeep", "model": "Grand Wagoneer", "package": "Command Operations Vehicle", "from_year": 2025, "to_year": 2026},
    {"make": "Ram", "model": "2500 HD", "package": "Emergency Response Vehicle", "from_year": 2027, "to_year": 2027},
    {"make": "Dodge", "model": "Charger", "package": "Pursuit", "from_year": 2006, "to_year": 2023},
    {"make": "Ford", "model": "Crown Victoria", "package": "Police Interceptor", "from_year": 1992, "to_year": 2011},
    {"make": "Ford", "model": "Taurus", "package": "Police Interceptor Sedan", "from_year": 2013, "to_year": 2019},
    {"make": "Chevrolet", "model": "Caprice", "package": "PPV", "from_year": 2011, "to_year": 2017},
    {"make": "Chevrolet", "model": "Impala", "package": "9C1 / 9C3 Police", "from_year": 2000, "to_year": 2016},
)


class VehicleCatalogError(RuntimeError):
    pass


def _valid_year(value: object) -> int:
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("A valid model year is required") from exc
    if year < 1995 or year > datetime.now().year + 2:
        raise ValueError("Model year is outside the supported range")
    return year


def _fetch_results(path: str, *, base_url: str = _BASE_URL) -> list[dict]:
    url = f"{base_url}/{path}"
    cached = _CACHE.get(url)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "DTM-Vehicle-Builder"})
    try:
        with urlopen(request, timeout=8) as response:  # nosec B310 - HTTPS host allowlist above
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in _ALLOWED_HOSTS:
                raise VehicleCatalogError("The vehicle catalog returned an unsafe redirect")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except Exception as exc:
        raise VehicleCatalogError("The vehicle catalog is temporarily unavailable") from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise VehicleCatalogError("The vehicle catalog response was too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VehicleCatalogError("The vehicle catalog returned an invalid response") from exc
    results = payload.get("Results", payload.get("results", [])) if isinstance(payload, dict) else []
    clean = [item for item in results if isinstance(item, dict)]
    with _CACHE_LOCK:
        _CACHE[url] = (now, clean)
    return clean


def _make_rows_for_type(vehicle_type: str) -> list[dict]:
    return _fetch_results(f"GetMakesForVehicleType/{quote(vehicle_type, safe='')}?format=json")


def _classified_makes(include_specialty: bool) -> dict[str, dict]:
    type_labels = dict(_AUTOMOTIVE_TYPES)
    if include_specialty:
        type_labels.update(_OTHER_TYPES)
    with ThreadPoolExecutor(max_workers=min(3, len(type_labels))) as pool:
        results = list(pool.map(_make_rows_for_type, type_labels))
    classified: dict[str, dict] = {}
    for (type_name, label), rows in zip(type_labels.items(), results):
        for row in rows:
            name = " ".join(str(row.get("MakeName", row.get("Make_Name", ""))).strip().split())
            if not name:
                continue
            key = name.casefold()
            item = classified.setdefault(key, {
                "id": str(row.get("MakeId", row.get("Make_ID", "")) or ""),
                "name": name,
                "vehicle_types": [],
            })
            if label not in item["vehicle_types"]:
                item["vehicle_types"].append(label)
    return classified


def _active_make_names(year: int) -> set[str]:
    paths = [f"makes?modelYear={year}&issueType=r", f"makes?modelYear={year}&issueType=c"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        result_sets = list(pool.map(
            lambda path: _fetch_results(path, base_url=_PRODUCTS_BASE_URL), paths,
        ))
    names: set[str] = set()
    for row in (item for rows in result_sets for item in rows):
        name = " ".join(str(
            row.get("make", row.get("Make", row.get("manufacturer", row.get(
                "MakeName", row.get("Make_Name", ""),
            ))))
        ).strip().split())
        if name:
            names.add(name.casefold())
    names.update(
        str(item["make"]).casefold()
        for item in list_police_vehicles(year)
    )
    return names


def list_makes(year: object, query: object = "") -> list[dict]:
    model_year = _valid_year(year)
    rows = _fetch_results("GetAllMakes?format=json")
    values: dict[str, dict] = {}
    for row in rows:
        name = " ".join(str(row.get("Make_Name", "")).strip().split())
        if name:
            key = name.casefold()
            values[key] = {
                "id": str(row.get("Make_ID", "") or ""),
                "name": _COMMON_MAKE_NAMES.get(key, name),
                "vehicle_types": [], "is_specialty": True,
            }
    search = " ".join(str(query or "").strip().split()).casefold()
    active_names = _active_make_names(model_year)
    classified = _classified_makes(include_specialty=bool(search))
    for key, classified_item in classified.items():
        target = values.setdefault(key, classified_item)
        target["vehicle_types"] = list(classified_item["vehicle_types"])
        target["is_specialty"] = not any(
            label in _AUTOMOTIVE_TYPES.values() for label in target["vehicle_types"]
        )
    if search:
        for item in values.values():
            if not item["vehicle_types"]:
                item["vehicle_types"] = ["Other / unclassified"]
    if search:
        matches = [
            item for item in values.values()
            if search in item["name"].casefold() and item["name"].casefold() in active_names
        ]
        return sorted(matches, key=lambda item: (
            not item["name"].casefold().startswith(search), item["is_specialty"], item["name"].casefold(),
        ))[:50]
    common_order = {name.casefold(): index for index, name in enumerate(_COMMON_AUTOMOTIVE_MAKES)}
    common = [
        item for key, item in values.items()
        if key in common_order and key in active_names and not item["is_specialty"]
    ]
    return sorted(common, key=lambda item: common_order[item["name"].casefold()])


def list_models(year: object, make: object) -> list[dict]:
    model_year = _valid_year(year)
    make_name = " ".join(str(make or "").strip().split())
    if not make_name or len(make_name) > 80:
        raise ValueError("A valid make is required")
    classification = _classified_makes(include_specialty=False).get(make_name.casefold(), {})
    if not classification:
        classification = _classified_makes(include_specialty=True).get(make_name.casefold(), {})
    make_types = list(classification.get("vehicle_types", []))
    automotive_queries = [
        type_name for type_name, label in _AUTOMOTIVE_TYPES.items() if label in make_types
    ]
    values: dict[str, dict] = {}
    if automotive_queries:
        paths = [
            f"GetModelsForMakeYear/make/{quote(make_name, safe='')}/modelyear/{model_year}/vehicletype/{quote(type_name, safe='')}?format=json"
            for type_name in automotive_queries
        ]
        with ThreadPoolExecutor(max_workers=len(paths)) as pool:
            result_sets = list(pool.map(_fetch_results, paths))
        typed_results = zip(automotive_queries, result_sets)
    else:
        rows = _fetch_results(f"GetModelsForMakeYear/make/{quote(make_name, safe='')}/modelyear/{model_year}?format=json")
        typed_results = [("", rows)]
    for type_name, rows in typed_results:
        label = _AUTOMOTIVE_TYPES.get(type_name, "")
        for row in rows:
            name = " ".join(str(row.get("Model_Name", "")).strip().split())
            if not name:
                continue
            item = values.setdefault(name.casefold(), {
                "id": str(row.get("Model_ID", "") or ""), "name": name,
                "vehicle_types": [] if label else make_types or ["Specialty"],
                "is_specialty": not bool(label),
            })
            if label and label not in item["vehicle_types"]:
                item["vehicle_types"].append(label)
    return sorted(values.values(), key=lambda item: item["name"].casefold())


def list_police_vehicles(year: object | None = None) -> list[dict]:
    model_year = _valid_year(year) if year not in (None, "") else None
    return [dict(item) for item in POLICE_VEHICLES if model_year is None or (
        model_year >= int(item["from_year"]) and model_year <= int(item.get("to_year", model_year))
    )]
