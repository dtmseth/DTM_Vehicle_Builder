from __future__ import annotations

from ...paths import AppPaths
from ..services.generation_service import (
    generate_build_sheet_handler,
    handle_status,
    parse_workbook,
)


def get_status(paths: AppPaths) -> dict:
    return handle_status(paths)


def post_parse(body: dict, paths: AppPaths) -> dict:
    return parse_workbook(body, paths)


def post_generate(body: dict, paths: AppPaths) -> dict:
    return generate_build_sheet_handler(body, paths)
