from __future__ import annotations

from ...paths import AppPaths
from ..services.generation_service import (
    generate_build_sheet_handler,
    handle_delete_old,
    handle_status,
    parse_workbook,
)
from ..services.template_service import pick_folder


def get_status(paths: AppPaths) -> dict:
    return handle_status(paths)


def get_pick_export_folder() -> dict:
    return pick_folder()


def post_parse(body: dict, paths: AppPaths) -> dict:
    return parse_workbook(body, paths)


def post_generate(body: dict, paths: AppPaths) -> dict:
    return generate_build_sheet_handler(body, paths)


def post_delete_old(body: dict, paths: AppPaths) -> dict:
    return handle_delete_old(body, paths)
