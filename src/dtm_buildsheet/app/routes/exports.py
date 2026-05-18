from __future__ import annotations

from ...paths import AppPaths
from ..services.export_service import export_to_pdf, open_file


def post_open(body: dict, paths: AppPaths | None = None) -> dict:
    return open_file(body, paths)


def post_pdf(body: dict, paths: AppPaths | None = None) -> dict:
    return export_to_pdf(body, paths)
