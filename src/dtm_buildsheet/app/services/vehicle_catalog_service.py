"""Read-only vehicle catalog backed by the public NHTSA vPIC API."""
from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from requests.certs import where as requests_ca_bundle

from ...storage.local import LocalStorageProvider

_BASE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles"
_PRODUCTS_BASE_URL = "https://api.nhtsa.gov/products/vehicle"
_ALLOWED_HOSTS = {"vpic.nhtsa.dot.gov", "api.nhtsa.gov"}
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_CACHE_SECONDS = 24 * 60 * 60
_MAX_PROJECT_YEAR = 2040
_PERSISTENT_CACHE_SCHEMA = 1
_MAX_PERSISTENT_CACHE_BYTES = 64 * 1024 * 1024
_MAX_PERSISTENT_ENTRIES = 512
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_LOCK = threading.Lock()
_REFRESHING: set[tuple[str, str]] = set()
_log = logging.getLogger(__name__)
_HTTPS_CONTEXT = ssl.create_default_context(cafile=requests_ca_bundle())

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
    {"make": "Ford", "model": "Police Interceptor Utility", "package": "", "from_year": 2013, "to_year": 2026, "quick_choice": True, "future_selectable": True},
    {"make": "Dodge", "model": "Durango", "package": "Pursuit", "from_year": 2018, "to_year": 2026, "quick_choice": True, "future_selectable": True},
    # Previewed at the 2026 Police Fleet Expo; keep visibly upcoming until
    # Stellantis publishes final ordering specifications.
    {"make": "Dodge", "model": "Charger", "package": "PPV", "from_year": 2027, "to_year": 2027, "quick_choice": True, "availability": "upcoming", "future_selectable": True},
    {"make": "Chevrolet", "model": "Tahoe", "package": "PPV", "from_year": 2015, "to_year": 2027, "quick_choice": True, "future_selectable": True},
    {"make": "Chevrolet", "model": "Tahoe", "package": "SSV", "from_year": 2015, "to_year": 2027, "future_selectable": True},
    {"make": "Ford", "model": "F-150", "package": "Police Responder", "from_year": 2018, "to_year": 2024},
    {"make": "Ford", "model": "F-150 Lightning", "package": "SSV", "from_year": 2023, "to_year": 2025},
    {"make": "Ford", "model": "Expedition", "package": "SSV", "from_year": 2018, "to_year": 2024},
    {"make": "Ford", "model": "Transit", "package": "PTV", "from_year": 2015, "to_year": 2024},
    {"make": "Chevrolet", "model": "Silverado 1500", "package": "PPV", "from_year": 2023, "to_year": 2026, "future_selectable": True},
    {"make": "Chevrolet", "model": "Silverado 1500", "package": "SSV", "from_year": 2022, "to_year": 2026, "future_selectable": True},
    {"make": "Chevrolet", "model": "Blazer EV", "package": "PPV", "from_year": 2024, "to_year": 2027, "future_selectable": True},
    {"make": "Ram", "model": "1500", "package": "SSV", "from_year": 2012, "to_year": 2026, "future_selectable": True},
    {"make": "Ram", "model": "2500", "package": "SSV", "from_year": 2014, "to_year": 2026, "future_selectable": True},
    {"make": "Ram", "model": "3500", "package": "SSV", "from_year": 2014, "to_year": 2026, "future_selectable": True},
    {"make": "Jeep", "model": "Wagoneer", "package": "Command Operations Vehicle", "from_year": 2025, "to_year": 2026, "future_selectable": True},
    {"make": "Jeep", "model": "Grand Wagoneer", "package": "Command Operations Vehicle", "from_year": 2025, "to_year": 2026, "future_selectable": True},
    {"make": "Ram", "model": "2500 HD", "package": "Emergency Response Vehicle", "from_year": 2027, "to_year": 2027, "future_selectable": True},
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
    if year < 1995 or year > _MAX_PROJECT_YEAR:
        raise ValueError("Model year is outside the supported range")
    return year


def _catalog_year(value: object) -> int:
    """Use the newest available catalog for farther-future project years."""
    return min(_valid_year(value), datetime.now().year)


def _police_vehicle_available(item: dict, model_year: int) -> bool:
    """Keep current vehicle lines selectable for unconfirmed future years."""
    from_year = int(item["from_year"])
    to_year = int(item.get("to_year", from_year))
    return model_year >= from_year and (
        model_year <= to_year or bool(item.get("future_selectable"))
    )


def _read_persistent_cache(path: Path) -> dict:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_PERSISTENT_CACHE_BYTES:
            return {"schema_version": _PERSISTENT_CACHE_SCHEMA, "entries": {}}
        payload = json.loads(LocalStorageProvider().read_text(str(path)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"schema_version": _PERSISTENT_CACHE_SCHEMA, "entries": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
        return {"schema_version": _PERSISTENT_CACHE_SCHEMA, "entries": {}}
    return payload


def _persistent_result(cache_path: Path | None, url: str) -> tuple[float, list[dict]] | None:
    if cache_path is None:
        return None
    with _CACHE_LOCK:
        entry = _read_persistent_cache(cache_path).get("entries", {}).get(url)
    if not isinstance(entry, dict):
        return None
    try:
        fetched_at = float(entry.get("fetched_at") or 0)
    except (TypeError, ValueError):
        return None
    results = entry.get("results")
    if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
        return None
    return fetched_at, results


def _remember_results(cache_path: Path | None, url: str, results: list[dict]) -> None:
    now = time.time()
    with _CACHE_LOCK:
        _CACHE[url] = (time.monotonic(), results)
        if cache_path is None:
            return
        payload = _read_persistent_cache(cache_path)
        entries = payload.setdefault("entries", {})
        entries[url] = {"fetched_at": now, "results": results}
        if len(entries) > _MAX_PERSISTENT_ENTRIES:
            def fetched_at(key: str) -> float:
                try:
                    return float((entries.get(key) or {}).get("fetched_at") or 0)
                except (AttributeError, TypeError, ValueError):
                    return 0.0

            oldest = sorted(
                entries, key=fetched_at,
            )[:len(entries) - _MAX_PERSISTENT_ENTRIES]
            for key in oldest:
                entries.pop(key, None)
        payload["schema_version"] = _PERSISTENT_CACHE_SCHEMA
        try:
            LocalStorageProvider().write_text(
                str(cache_path), json.dumps(payload, separators=(",", ":")) + "\n",
            )
        except (OSError, TypeError, ValueError) as exc:
            _log.warning("Vehicle catalog cache write failed: %s", type(exc).__name__)


def _fetch_remote(url: str) -> list[dict]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "DTM-Vehicle-Builder"})
    try:
        with urlopen(  # nosec B310 - HTTPS host allowlist above
            request, timeout=8, context=_HTTPS_CONTEXT,
        ) as response:
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
    return [item for item in results if isinstance(item, dict)]


def _refresh_in_background(cache_path: Path, url: str) -> None:
    key = (str(cache_path), url)
    with _CACHE_LOCK:
        if key in _REFRESHING:
            return
        _REFRESHING.add(key)

    def refresh() -> None:
        try:
            _remember_results(cache_path, url, _fetch_remote(url))
        except VehicleCatalogError as exc:
            _log.warning("Vehicle catalog background refresh failed: %s", type(exc).__name__)
        finally:
            with _CACHE_LOCK:
                _REFRESHING.discard(key)

    threading.Thread(target=refresh, name="vehicle-catalog-refresh", daemon=True).start()


def _fetch_results(
    path: str,
    *,
    base_url: str = _BASE_URL,
    cache_path: Path | None = None,
) -> list[dict]:
    url = f"{base_url}/{path}"
    cached = _CACHE.get(url)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]

    persisted = _persistent_result(cache_path, url)
    if persisted is not None:
        fetched_at, results = persisted
        age = max(0.0, time.time() - fetched_at)
        with _CACHE_LOCK:
            _CACHE[url] = (now - min(age, _CACHE_SECONDS + 1), results)
        if age >= _CACHE_SECONDS and cache_path is not None:
            _refresh_in_background(cache_path, url)
        return results

    results = _fetch_remote(url)
    _remember_results(cache_path, url, results)
    return results


def _make_rows_for_type(vehicle_type: str, cache_path: Path | None = None) -> list[dict]:
    return _fetch_results(
        f"GetMakesForVehicleType/{quote(vehicle_type, safe='')}?format=json",
        cache_path=cache_path,
    )


def _classified_makes(include_specialty: bool, cache_path: Path | None = None) -> dict[str, dict]:
    type_labels = dict(_AUTOMOTIVE_TYPES)
    if include_specialty:
        type_labels.update(_OTHER_TYPES)
    with ThreadPoolExecutor(max_workers=min(3, len(type_labels))) as pool:
        results = list(pool.map(
            lambda vehicle_type: _make_rows_for_type(vehicle_type, cache_path),
            type_labels,
        ))
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


def _active_make_names(year: int, cache_path: Path | None = None) -> set[str]:
    paths = [f"makes?modelYear={year}&issueType=r", f"makes?modelYear={year}&issueType=c"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        result_sets = list(pool.map(
            lambda path: _fetch_results(
                path, base_url=_PRODUCTS_BASE_URL, cache_path=cache_path,
            ),
            paths,
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


def list_makes(
    year: object,
    query: object = "",
    *,
    cache_path: Path | None = None,
) -> list[dict]:
    model_year = _catalog_year(year)
    rows = _fetch_results("GetAllMakes?format=json", cache_path=cache_path)
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
    active_names = _active_make_names(model_year, cache_path)
    classified = _classified_makes(include_specialty=bool(search), cache_path=cache_path)
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


def list_models(
    year: object,
    make: object,
    *,
    cache_path: Path | None = None,
) -> list[dict]:
    model_year = _catalog_year(year)
    make_name = " ".join(str(make or "").strip().split())
    if not make_name or len(make_name) > 80:
        raise ValueError("A valid make is required")
    classification = _classified_makes(
        include_specialty=False, cache_path=cache_path,
    ).get(make_name.casefold(), {})
    if not classification:
        classification = _classified_makes(
            include_specialty=True, cache_path=cache_path,
        ).get(make_name.casefold(), {})
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
            result_sets = list(pool.map(
                lambda path: _fetch_results(path, cache_path=cache_path), paths,
            ))
        typed_results = zip(automotive_queries, result_sets)
    else:
        rows = _fetch_results(
            f"GetModelsForMakeYear/make/{quote(make_name, safe='')}/modelyear/{model_year}?format=json",
            cache_path=cache_path,
        )
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
    return [
        dict(item) for item in POLICE_VEHICLES
        if model_year is None or _police_vehicle_available(item, model_year)
    ]
