from __future__ import annotations

from ..services.export_service import export_to_pdf, open_file


def post_open(body: dict) -> dict:
    return open_file(body)


def post_pdf(body: dict) -> dict:
    return export_to_pdf(body)
