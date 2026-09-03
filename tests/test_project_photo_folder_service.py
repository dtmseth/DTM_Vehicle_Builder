from __future__ import annotations

from pathlib import Path
from concurrent.futures import Future

from dtm_buildsheet.app.services import photo_gallery_service as gallery
from dtm_buildsheet.app.services.project_photo_folder_service import (
    handle_sync_project_photo_folder,
    reconcile_project_photo_folder,
    scan_project_photo_folder,
)
from dtm_buildsheet.app.services import project_photo_folder_service as folder_service
from dtm_buildsheet.app.services.reference_photo_service import (
    handle_delete_reference,
    handle_import_gallery_references,
)
from dtm_buildsheet.domain.project_models import BuildReferenceAsset, BuildReferenceAssignment
from dtm_buildsheet.inputs.project_entry import load_project, new_project, save_project
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path: Path) -> AppPaths:
    projects = tmp_path / "projects"
    projects.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return AppPaths(workspace_dir=workspace, workspace_projects_dir=projects)


class _Gateway:
    drive_id = "company-drive"

    def __init__(self, children):
        self.children = children

    def list_children(self, remote_path, **_kwargs):
        return list(self.children.get(remote_path, []))


def _file(name: str, item_id: str) -> dict:
    return {
        "id": item_id,
        "name": name,
        "file": {},
        "eTag": f'etag-{item_id}',
        "size": 123,
        "webUrl": f"https://example.test/{item_id}",
    }


def test_year_folder_photos_become_unassigned_project_photos(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.company_year_folder_path = "Vehicle Project Database/Granite Falls/GFPD - 2026"
    save_project(project, paths)
    original_updated_at = load_project(project.project_id, paths).updated_at
    folder = f"{project.company_year_folder_path}/Reference Photos & Videos"
    gateway = _Gateway({
        folder: [
            _file("front.jpg", "front"),
            _file("walkaround.mov", "video"),
            {"id": "detail-folder", "name": "Details", "folder": {}},
        ],
        f"{folder}/Details": [_file("console.png", "console")],
    })

    discovered = scan_project_photo_folder(project, gateway=gateway)
    result = reconcile_project_photo_folder(project.project_id, discovered, paths)

    stored = load_project(project.project_id, paths)
    assert result["added"] == 2
    assert [asset.file_name for asset in stored.reference_assets] == ["console.png", "front.jpg"]
    assert all(asset.assignments == [] for asset in stored.reference_assets)
    assert all(asset.source_drive_id == "company-drive" for asset in stored.reference_assets)
    assert stored.updated_at == original_updated_at


def test_removed_folder_photo_stays_excluded_until_user_adds_it_again(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.company_year_folder_path = "Vehicle Project Database/Agency/A - 2026"
    folder = f"{project.company_year_folder_path}/Reference Photos & Videos"
    project.reference_assets = [BuildReferenceAsset(
        reference_id="folder-photo",
        file_name="front.jpg",
        source_drive_id="company-drive",
        source_item_id="front",
        source_path=f"{folder}/front.jpg",
        source_etag="etag-front",
    )]
    save_project(project, paths)

    assert handle_delete_reference(project.project_id, "folder-photo", paths)["ok"] is True
    stored = load_project(project.project_id, paths)
    assert stored.reference_assets == []
    assert stored.reference_source_exclusions == ["item:company-drive:front"]

    discovered = scan_project_photo_folder(
        stored,
        gateway=_Gateway({folder: [_file("front.jpg", "front")]}),
    )
    reconcile_project_photo_folder(project.project_id, discovered, paths)
    assert load_project(project.project_id, paths).reference_assets == []

    gallery_item = gallery.decorate_photo_items(
        project.project_id, discovered["photos"], paths,
    )[0]
    response = handle_import_gallery_references(project.project_id, {
        "source_project_id": project.project_id,
        "photo_tokens": [gallery_item["photo_token"]],
    }, paths)
    assert response["added"] == 1
    restored = load_project(project.project_id, paths)
    assert [asset.file_name for asset in restored.reference_assets] == ["front.jpg"]
    assert restored.reference_source_exclusions == []


def test_project_folder_sync_is_non_blocking_and_reports_change_once(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.company_year_folder_path = "Vehicle Project Database/Agency/A - 2026"
    save_project(project, paths)
    folder = f"{project.company_year_folder_path}/Reference Photos & Videos"
    scanned = scan_project_photo_folder(
        project, gateway=_Gateway({folder: [_file("front.jpg", "front")]}),
    )

    class _ImmediateExecutor:
        def submit(self, *_args, **_kwargs):
            future = Future()
            future.set_result(scanned)
            return future

    monkeypatch.setattr(folder_service, "_JOBS", {})
    monkeypatch.setattr(folder_service, "_RESULTS", {})
    monkeypatch.setattr(folder_service, "_EXECUTOR", _ImmediateExecutor())

    first = handle_sync_project_photo_folder(project.project_id, paths)
    second = handle_sync_project_photo_folder(project.project_id, paths)
    third = handle_sync_project_photo_folder(project.project_id, paths)

    assert first["loading"] is True
    assert second["loading"] is False
    assert second["added"] == second["changed"] == 1
    assert third["loading"] is False
    assert third["changed"] == 0


def test_missing_folder_file_is_retained_when_assigned_to_a_group(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.company_year_folder_path = "Vehicle Project Database/Agency/A - 2026"
    folder = f"{project.company_year_folder_path}/Reference Photos & Videos"
    project.reference_assets = [BuildReferenceAsset(
        reference_id="assigned-photo",
        file_name="assigned.jpg",
        source_drive_id="company-drive",
        source_item_id="assigned",
        source_path=f"{folder}/assigned.jpg",
        assignments=[BuildReferenceAssignment(scope="unit_group", target_id="group-1")],
    )]
    save_project(project, paths)
    empty_scan = scan_project_photo_folder(project, gateway=_Gateway({folder: []}))

    result = reconcile_project_photo_folder(project.project_id, empty_scan, paths)

    assert result["removed"] == 0
    assert [asset.reference_id for asset in load_project(project.project_id, paths).reference_assets] == [
        "assigned-photo",
    ]
