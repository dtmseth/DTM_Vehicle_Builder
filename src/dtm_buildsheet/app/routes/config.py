from __future__ import annotations

from ...paths import AppPaths
from ..services.config_service import load_config_file, save_config_file

# Maps GET path → config filename
GET_ROUTES: dict[str, str] = {
    "/api/catalog": "part_catalog.json",
    "/api/layouts": "vehicle_layouts.json",
    "/api/manifest": "asset_manifest.json",
    "/api/parts-library": "parts_library.json",
    "/api/workbook-rules": "workbook_rules.json",
    "/api/app-settings": "app_settings.json",
    "/api/project-options": "project_options.json",
}

# Maps POST save path → config filename
POST_ROUTES: dict[str, str] = {
    "/api/catalog/save": "part_catalog.json",
    "/api/layouts/save": "vehicle_layouts.json",
    "/api/manifest/save": "asset_manifest.json",
    "/api/parts-library/save": "parts_library.json",
    "/api/workbook-rules/save": "workbook_rules.json",
    "/api/app-settings/save": "app_settings.json",
}


def get_config(path: str, paths: AppPaths) -> dict:
    return load_config_file(GET_ROUTES[path], paths)


def post_save(path: str, body: dict, paths: AppPaths) -> dict:
    return save_config_file(POST_ROUTES[path], body, paths)
