"""Project reference-asset metadata and assignment endpoints.

This service never moves or deletes source media. Company/Shop drive browsing
and finalization publication are separate adapter concerns; this boundary owns
only portable project metadata and scope validation.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import PurePosixPath

from ...domain.project_codec import reference_asset_from_dict
from ...domain.project_models import BuildReferenceAssignment
from ...domain.reference_photos import (
    invalid_reference_targets,
    resolve_build_reference_photos,
)
from ...inputs.project_entry import load_project, save_project
from ...paths import AppPaths


_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}


def _source_identity(*, drive_id: str = "", item_id: str = "", source_path: str = "") -> str:
    drive_id = str(drive_id or "").strip()
    item_id = str(item_id or "").strip()
    if drive_id and item_id:
        return f"item:{drive_id}:{item_id}"
    portable = str(source_path or "").replace("\\", "/").strip("/").casefold()
    return f"path:{portable}" if portable else ""


def _asset_source_identity(asset) -> str:
    return _source_identity(
        drive_id=asset.source_drive_id,
        item_id=asset.source_item_id,
        source_path=asset.source_path,
    )


def _is_project_photo_folder_asset(project, asset) -> bool:
    year_path = str(project.company_year_folder_path or "").replace("\\", "/").strip("/")
    source_path = str(asset.source_path or "").replace("\\", "/").strip("/")
    if not year_path or not source_path or asset.source_kind != "company_reference":
        return False
    folder = f"{year_path}/Reference Photos & Videos".casefold()
    source_key = source_path.casefold()
    return source_key == folder or source_key.startswith(f"{folder}/")


def _exclude_removed_project_folder_asset(project, asset) -> None:
    if not _is_project_photo_folder_asset(project, asset):
        return
    identity = _asset_source_identity(asset)
    if identity and identity not in project.reference_source_exclusions:
        project.reference_source_exclusions.append(identity)


def _validate_asset(asset) -> str | None:
    if not asset.file_name:
        return "Reference filename is required."
    if "/" in asset.file_name or "\\" in asset.file_name or asset.file_name in {".", ".."}:
        return "Reference filename must not contain a folder path."
    suffix = PurePosixPath(asset.file_name).suffix.casefold()
    allowed = _PHOTO_SUFFIXES if asset.media_type == "photo" else _VIDEO_SUFFIXES
    if suffix not in allowed:
        return (
            "Reference photos must be JPG or PNG. Convert HEIC photos before assigning them."
            if asset.media_type == "photo"
            else "Reference videos must be MP4, MOV, or M4V."
        )
    if asset.source_kind == "shop_completed" and asset.media_type != "photo":
        return "Shop Completed Build Photos cannot contain reference videos."
    if not asset.source_item_id and not asset.source_path:
        return "Reference source item ID or portable source path is required."
    if asset.source_path:
        portable = PurePosixPath(asset.source_path.replace("\\", "/"))
        if portable.is_absolute() or ".." in portable.parts:
            return "Reference source path must be portable and remain inside its configured library."
    seen: set[tuple[str, str]] = set()
    for assignment in asset.assignments:
        key = (assignment.scope, assignment.target_id)
        if key in seen:
            return "A reference cannot repeat the same assignment scope and target."
        seen.add(key)
        if assignment.scope != "project" and not assignment.target_id:
            return f"{assignment.scope.replace('_', ' ').title()} assignment requires a target ID."
    return None


def handle_list_references(project_id: str, paths: AppPaths) -> dict:
    try:
        project = load_project(project_id, paths)
        return {"ok": True, "references": [asdict(asset) for asset in project.reference_assets]}
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_reference(project_id: str, body: dict, paths: AppPaths) -> dict:
    try:
        project = load_project(project_id, paths)
        raw = body.get("reference", body)
        asset = reference_asset_from_dict(raw)
        error = _validate_asset(asset)
        if error:
            return {"ok": False, "error": error}

        existing_index = next(
            (
                index for index, candidate in enumerate(project.reference_assets)
                if candidate.reference_id == asset.reference_id
            ),
            None,
        )
        if existing_index is None:
            project.reference_assets.append(asset)
        else:
            project.reference_assets[existing_index] = asset

        target_errors = invalid_reference_targets(project)
        if target_errors:
            return {"ok": False, "error": target_errors[0], "errors": target_errors}

        save_project(project, paths)
        return {"ok": True, "reference": asdict(asset)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def handle_delete_reference(project_id: str, reference_id: str, paths: AppPaths) -> dict:
    """Delete assignment metadata only; never delete the source media item."""

    try:
        project = load_project(project_id, paths)
        removed_asset = next((
            asset for asset in project.reference_assets
            if asset.reference_id == reference_id
        ), None)
        remaining = [
            asset for asset in project.reference_assets
            if asset.reference_id != reference_id
        ]
        if len(remaining) == len(project.reference_assets):
            return {"ok": False, "error": f"Reference not found: {reference_id}"}
        if removed_asset is not None:
            _exclude_removed_project_folder_asset(project, removed_asset)
        project.reference_assets = remaining
        save_project(project, paths)
        return {"ok": True}
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def handle_effective_references(project_id: str, body: dict, paths: AppPaths) -> dict:
    try:
        project = load_project(project_id, paths)
        unit_id = str(body.get("unit_id", "") or "").strip()
        individual_id = str(body.get("individual_id", "") or "").strip()
        if not unit_id:
            return {"ok": False, "error": "unit_id is required"}
        resolved = resolve_build_reference_photos(
            project,
            unit_id=unit_id,
            individual_id=individual_id,
        )
        return {
            "ok": True,
            "references": [
                {
                    "asset": asdict(item.asset),
                    "assignment": asdict(item.assignment),
                    "origin": item.origin,
                }
                for item in resolved
            ],
        }
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def handle_import_gallery_references(project_id: str, body: dict, paths: AppPaths) -> dict:
    """Add authorized gallery photos to a project, optionally assigned to one group."""
    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if project.project_status == "completed":
        return {"ok": False, "error": "Reopen the destination project before adding references."}

    target_unit_id = str(body.get("target_unit_id") or "").strip()
    if target_unit_id and target_unit_id not in {unit.unit_id for unit in project.build_units}:
        return {"ok": False, "error": "The selected destination unit group no longer exists."}

    source_project_id = str(body.get("source_project_id") or "").strip()
    raw_tokens = body.get("photo_tokens")
    if not source_project_id or not isinstance(raw_tokens, list):
        return {"ok": False, "error": "Source project and selected photos are required."}
    tokens = [str(value or "").strip() for value in raw_tokens if str(value or "").strip()]
    if not tokens or len(tokens) > 300:
        return {"ok": False, "error": "Select between 1 and 300 photos."}

    from .photo_gallery_service import reference_sources_from_tokens
    sources = reference_sources_from_tokens(source_project_id, tokens)
    if len(sources) != len(set(tokens)):
        return {"ok": False, "error": "One or more selected photos expired. Reopen the gallery."}

    by_key = {
        (asset.source_drive_id, asset.source_item_id or asset.source_path): asset
        for asset in project.reference_assets
    }
    added = already_in_project = 0
    for source in sources:
        key = (
            str(source.get("source_drive_id") or ""),
            str(source.get("source_item_id") or source.get("source_path") or ""),
        )
        source_identity = _source_identity(
            drive_id=source.get("source_drive_id", ""),
            item_id=source.get("source_item_id", ""),
            source_path=source.get("source_path", ""),
        )
        if source_identity in project.reference_source_exclusions:
            project.reference_source_exclusions.remove(source_identity)
        asset = by_key.get(key)
        was_new = asset is None
        if asset is None:
            raw = {
                **source,
                "reference_id": str(uuid.uuid4()),
                "assignments": [],
            }
            asset = reference_asset_from_dict(raw)
            error = _validate_asset(asset)
            if error:
                return {"ok": False, "error": error}
            project.reference_assets.append(asset)
            by_key[key] = asset
        elif not target_unit_id:
            already_in_project += 1
            continue

        if target_unit_id:
            if any(
                assignment.scope == "unit_group" and assignment.target_id == target_unit_id
                for assignment in asset.assignments
            ):
                already_in_project += 1
                continue
            asset.assignments.append(BuildReferenceAssignment(
                scope="unit_group",
                target_id=target_unit_id,
                note="",
                sort_order=sum(
                    1
                    for candidate in project.reference_assets
                    for assignment in candidate.assignments
                    if assignment.scope == "unit_group" and assignment.target_id == target_unit_id
                ),
            ))
        # A new unassigned photo or a new group assignment is one successful add.
        if was_new or target_unit_id:
            added += 1

    if added:
        target_errors = invalid_reference_targets(project)
        if target_errors:
            return {"ok": False, "error": target_errors[0], "errors": target_errors}
        save_project(project, paths)
    return {
        "ok": True,
        "added": added,
        "already_in_project": already_in_project,
        # Retained for older UI clients that still read this response field.
        "already_assigned": already_in_project,
        "project_id": project.project_id,
        "target_unit_id": target_unit_id,
    }


def handle_remove_gallery_references(project_id: str, body: dict, paths: AppPaths) -> dict:
    """Remove selected project/group reference metadata without deleting sources."""

    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if project.project_status == "completed":
        return {"ok": False, "error": "Reopen this project before removing references."}

    target_unit_id = str(body.get("target_unit_id") or "").strip()
    if target_unit_id and target_unit_id not in {unit.unit_id for unit in project.build_units}:
        return {"ok": False, "error": "The selected unit group no longer exists."}

    raw_tokens = body.get("photo_tokens")
    if not isinstance(raw_tokens, list):
        return {"ok": False, "error": "Selected photos are required."}
    tokens = [str(value or "").strip() for value in raw_tokens if str(value or "").strip()]
    if not tokens or len(tokens) > 300:
        return {"ok": False, "error": "Select between 1 and 300 photos."}

    from .photo_gallery_service import reference_sources_from_tokens
    sources = reference_sources_from_tokens(project_id, tokens)
    if len(sources) != len(set(tokens)):
        return {"ok": False, "error": "One or more selected photos expired. Reopen the gallery."}
    keys = {
        (
            str(source.get("source_drive_id") or ""),
            str(source.get("source_item_id") or source.get("source_path") or ""),
        )
        for source in sources
    }
    if target_unit_id:
        removed = 0
        for asset in project.reference_assets:
            if (asset.source_drive_id, asset.source_item_id or asset.source_path) not in keys:
                continue
            original_count = len(asset.assignments)
            asset.assignments = [
                assignment
                for assignment in asset.assignments
                if not (
                    assignment.scope == "unit_group"
                    and assignment.target_id == target_unit_id
                )
            ]
            removed += original_count - len(asset.assignments)
    else:
        original_count = len(project.reference_assets)
        removed_assets = [
            asset
            for asset in project.reference_assets
            if (asset.source_drive_id, asset.source_item_id or asset.source_path) in keys
        ]
        for asset in removed_assets:
            _exclude_removed_project_folder_asset(project, asset)
        project.reference_assets = [
            asset
            for asset in project.reference_assets
            if (asset.source_drive_id, asset.source_item_id or asset.source_path) not in keys
        ]
        removed = original_count - len(project.reference_assets)
    if removed:
        save_project(project, paths)
    return {
        "ok": True,
        "removed": removed,
        "project_id": project.project_id,
        "target_unit_id": target_unit_id,
    }
