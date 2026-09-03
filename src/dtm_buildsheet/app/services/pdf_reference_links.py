"""Add optional relative full-resolution photo links to exported PDFs."""
from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from ...domain.reference_photo_layout import plan_reference_photo_pages
from ...inputs.project_entry import load_project
from ...paths import AppPaths
from .reference_package_service import resolve_reference_package


logger = logging.getLogger(__name__)
_SLIDE_WIDTH_IN = 13.333
_SLIDE_HEIGHT_IN = 7.5
_CONTENT_RECT_IN = (0.48, 1.08, 12.83, 6.98)


def _safe_relative_target(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "Build Reference Photos":
        return ""
    if path.parts[1] in {"", ".", ".."}:
        return ""
    return path.as_posix()


def _safe_web_url(value: str) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    return candidate if parsed.scheme == "https" and parsed.netloc else ""


def _image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as original:
            return ImageOps.exif_transpose(original).size
    except Exception:
        return (1, 1)


def add_reference_photo_links(
    pdf_path: Path,
    targets: list[str],
    *,
    sizes: list[tuple[int, int]] | None = None,
    web_urls: list[str] | None = None,
) -> dict:
    """Annotate the final reference pages; link failure never breaks export."""
    entries = []
    for index, value in enumerate(targets):
        target = _safe_relative_target(value)
        if not target:
            continue
        size = sizes[index] if sizes is not None and index < len(sizes) else (1, 1)
        web_url = web_urls[index] if web_urls is not None and index < len(web_urls) else ""
        entries.append((target, size, _safe_web_url(web_url)))
    if not entries:
        return {"ok": True, "links_added": 0}
    try:
        import fitz

        document = fitz.open(pdf_path)
        pages = plan_reference_photo_pages([entry[1] for entry in entries])
        reference_pages = len(pages)
        if document.page_count < reference_pages:
            document.close()
            return {"ok": False, "links_added": 0, "error": "reference_pages_missing"}
        first_page = document.page_count - reference_pages
        links_added = 0
        content_x0, content_y0, content_x1, content_y1 = _CONTENT_RECT_IN
        content_w = content_x1 - content_x0
        content_h = content_y1 - content_y0
        for page_index, layout_page in enumerate(pages):
            page = document[first_page + page_index]
            for placement in layout_page.placements:
                target, _size, web_url = entries[placement.source_index]
                x0 = content_x0 + content_w * placement.left
                y0 = content_y0 + content_h * placement.top
                x1 = x0 + content_w * placement.width
                y1 = y0 + content_h * placement.height
                rect = fitz.Rect(
                    x0 / _SLIDE_WIDTH_IN * page.rect.width,
                    y0 / _SLIDE_HEIGHT_IN * page.rect.height,
                    x1 / _SLIDE_WIDTH_IN * page.rect.width,
                    y1 / _SLIDE_HEIGHT_IN * page.rect.height,
                )
                # LibreOffice may preserve the PPT picture's relative link.
                # Replace overlapping converted annotations so Apple Preview
                # cannot choose the stale launch action instead of this link.
                for existing in list(page.get_links()):
                    existing_rect = fitz.Rect(existing.get("from") or ())
                    if existing_rect.is_valid and existing_rect.intersects(rect):
                        page.delete_link(existing)
                link = ({"kind": fitz.LINK_URI, "from": rect, "uri": web_url}
                        if web_url else
                        {"kind": fitz.LINK_LAUNCH, "from": rect, "file": target})
                page.insert_link(link)
                links_added += 1
        temporary = pdf_path.with_name(pdf_path.name + ".linked")
        document.save(temporary, garbage=4, deflate=True)
        document.close()
        temporary.replace(pdf_path)
        return {"ok": True, "links_added": links_added}
    except Exception as exc:
        logger.warning("Could not add reference-photo PDF links (%s)", type(exc).__name__)
        try:
            pdf_path.with_name(pdf_path.name + ".linked").unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "links_added": 0, "error": "reference_link_annotation_failed"}


def add_build_reference_links(pdf_path: Path, body: dict, paths: AppPaths | None) -> dict:
    if paths is None:
        return {"ok": True, "links_added": 0}
    project_id = str(body.get("project_id") or "").strip()
    unit_id = str(body.get("unit_id") or "").strip()
    individual_id = str(body.get("individual_id") or "").strip()
    if not project_id or not unit_id:
        return {"ok": True, "links_added": 0}
    try:
        project = load_project(project_id, paths)
        package = resolve_reference_package(
            project,
            unit_id=unit_id,
            individual_id=individual_id,
            paths=paths,
        )
    except Exception as exc:
        logger.warning("Could not resolve PDF reference links (%s)", type(exc).__name__)
        return {"ok": False, "links_added": 0, "error": "reference_package_unavailable"}
    result = add_reference_photo_links(
        pdf_path,
        [f"Build Reference Photos/{entry.published_file_name}" for entry in package.entries],
        sizes=[_image_size(entry.local_path) for entry in package.entries],
        web_urls=[entry.asset.source_web_url for entry in package.entries],
    )
    if package.errors:
        result["reference_errors"] = list(package.errors)
    return result
