from __future__ import annotations

from ...paths import AppPaths
from ..services.asset_service import delete_asset, list_assets, serve_asset, upload_asset


def get_list(paths: AppPaths) -> dict:
    return list_assets(paths)


def get_asset(rel_path: str, paths: AppPaths) -> tuple[int, bytes, str]:
    """Returns (status_code, body, content_type) for raw binary delivery."""
    return serve_asset(rel_path, paths)


def post_upload(body: dict, paths: AppPaths) -> dict:
    return upload_asset(body, paths)


def post_delete(body: dict, paths: AppPaths) -> dict:
    return delete_asset(body, paths)
