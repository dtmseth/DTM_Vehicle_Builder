from __future__ import annotations

from ...paths import AppPaths
from ..services.preview_service import handle_preview_plan


def route_preview(handler, method: str, path: str, body: dict, paths: AppPaths) -> bool:
    if method == "POST" and path == "/api/preview/plan":
        handler._api(handle_preview_plan(body, paths))
        return True
    return False
