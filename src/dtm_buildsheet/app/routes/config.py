from __future__ import annotations

import re
import threading

from ...paths import AppPaths
from ..services.config_service import load_config_file, save_config_file


CREATE_PLACEHOLDER_VEHICLE_ROUTE = "/api/layouts/vehicles/create"
_VEHICLE_CREATE_LOCK = threading.Lock()

# Maps GET path → config filename
GET_ROUTES: dict[str, str] = {
    "/api/catalog": "part_catalog.json",
    "/api/layouts": "vehicle_layouts.json",
    "/api/manifest": "asset_manifest.json",
    "/api/parts-library": "parts_library.json",
    "/api/workbook-rules": "workbook_rules.json",
    "/api/app-settings": "app_settings.json",
    "/api/project-options": "project_options.json",
    "/api/estimate-charges": "estimate_charges.json",
}

# Maps POST save path → config filename
POST_ROUTES: dict[str, str] = {
    "/api/catalog/save": "part_catalog.json",
    "/api/layouts/save": "vehicle_layouts.json",
    "/api/manifest/save": "asset_manifest.json",
    "/api/parts-library/save": "parts_library.json",
    "/api/workbook-rules/save": "workbook_rules.json",
    "/api/app-settings/save": "app_settings.json",
    "/api/estimate-charges/save": "estimate_charges.json",
}


def get_config(path: str, paths: AppPaths) -> dict:
    return load_config_file(GET_ROUTES[path], paths)


def post_save(path: str, body: dict, paths: AppPaths) -> dict:
    return save_config_file(POST_ROUTES[path], body, paths)


def _clean_vehicle_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _vehicle_type_token(value: str) -> str:
    token = re.sub(r"[^A-Z0-9-]+", " ", value.upper())
    return " ".join(token.split()).strip(" -")


def _placeholder_vehicle_layout(make: str, model: str) -> dict:
    """Create an assignable vehicle without pretending artwork exists."""

    labels = {"front": "Front", "side": "Side", "top": "Top", "rear": "Rear"}
    views = {
        view: {
            "label": label,
            "category": "external",
            "legend_layout": "grid" if view in {"side", "top"} else "standard",
            "logo_position": "bottom" if view in {"side", "top"} else "top-right",
            "coord_space": "relative_image",
            "locations": {},
        }
        for view, label in labels.items()
    }
    views["front"]["side_roles"] = {
        "negative_x": "passenger",
        "positive_x": "driver",
    }
    views["side"]["default_slot_role"] = "driver"
    views["rear"]["side_roles"] = {
        "negative_x": "driver",
        "positive_x": "passenger",
    }
    views.update({
        "internal.console": {
            "label": "Console",
            "category": "internal",
            "legend_layout": "standard",
            "logo_position": "top-right",
            "coord_space": "relative_image",
            "locations": {},
        },
        "internal.cargo": {
            "label": "Cargo Area",
            "category": "internal",
            "legend_layout": "standard",
            "logo_position": "top-right",
            "coord_space": "relative_image",
            "locations": {},
        },
        "internal.rear_seat": {
            "label": "Rear Seat",
            "category": "internal",
            "legend_layout": "standard",
            "logo_position": "top-right",
            "coord_space": "relative_image",
            "locations": {},
        },
    })
    aliases = list(dict.fromkeys(value for value in (model, f"{make} {model}") if value))
    return {
        "make": make,
        "model": model,
        "aliases": aliases,
        "placeholder": True,
        "fixtures": {},
        "views": views,
        "view_order": [*labels, "internal.console", "internal.cargo", "internal.rear_seat"],
    }


def post_create_placeholder_vehicle(body: dict, paths: AppPaths) -> dict:
    """Create or select a make/model vehicle entry with artwork pending."""

    if not isinstance(body, dict):
        return {"ok": False, "error": "Vehicle details must be an object"}
    make = _clean_vehicle_text(body.get("make"))
    model = _clean_vehicle_text(body.get("model"))
    if not make or not model:
        return {"ok": False, "error": "Make and model are required"}
    if len(make) > 80 or len(model) > 80:
        return {"ok": False, "error": "Make and model must be 80 characters or fewer"}

    with _VEHICLE_CREATE_LOCK:
        layouts = load_config_file("vehicle_layouts.json", paths)
        vehicles = layouts.setdefault("vehicles", {})
        folded_make = make.casefold()
        folded_model = model.casefold()
        for vehicle_id, vehicle in vehicles.items():
            if not isinstance(vehicle, dict):
                continue
            if (
                _clean_vehicle_text(vehicle.get("make")).casefold() == folded_make
                and _clean_vehicle_text(vehicle.get("model")).casefold() == folded_model
            ):
                return {
                    "ok": True,
                    "created": False,
                    "vehicle_id": vehicle_id,
                    "vehicle": vehicle,
                }

        model_token = _vehicle_type_token(model)
        if not model_token:
            return {"ok": False, "error": "Model must contain a letter or number"}
        vehicle_id = model_token
        if vehicle_id in vehicles:
            make_token = _vehicle_type_token(make)
            vehicle_id = " ".join(value for value in (make_token, model_token) if value)
        base_id = vehicle_id
        suffix = 2
        while vehicle_id in vehicles:
            vehicle_id = f"{base_id} {suffix}"
            suffix += 1

        vehicle = _placeholder_vehicle_layout(make, model)
        vehicles[vehicle_id] = vehicle
        saved = save_config_file("vehicle_layouts.json", layouts, paths)
        if not saved.get("ok"):
            return saved
        normalized_vehicle = (load_config_file("vehicle_layouts.json", paths).get("vehicles") or {}).get(
            vehicle_id,
            vehicle,
        )
        return {
            **saved,
            "created": True,
            "vehicle_id": vehicle_id,
            "vehicle": normalized_vehicle,
        }
