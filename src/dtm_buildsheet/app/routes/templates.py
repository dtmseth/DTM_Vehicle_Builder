from __future__ import annotations

from ...paths import AppPaths
from ..services.template_service import generate_template, get_template_info, pick_folder


def get_info(paths: AppPaths) -> dict:
    return get_template_info(paths)


def get_pick_folder() -> dict:
    return pick_folder()


def post_generate(body: dict, paths: AppPaths) -> dict:
    return generate_template(paths)
