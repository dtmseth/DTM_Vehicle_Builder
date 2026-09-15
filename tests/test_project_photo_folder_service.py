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
from dtm_buildsheet.domain.project_models import BuildReferenceAsset, BuildReferenceAssignment, BuildUnit, IndividualUnit
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


def _vehicle_project(paths):
    project = new_project()
    project.company_year_folder_path = "Vehicle Project Database/Agency/A - 2026"
    project.build_units = [BuildUnit(unit_id="group-1", individuals=[
        IndividualUnit(individual_id="vehicle-1", company_vehicle_folder_id="parent-1",
                       company_vehicle_folder_path="Vehicle Project Database/Agency/A - 2026/Unit 1"),
        IndividualUnit(individual_id="vehicle-2", company_vehicle_folder_id="parent-2",
                       company_vehicle_folder_path="Vehicle Project Database/Agency/A - 2026/Unit 2"),
    ])]
    save_project(project, paths)
    return project


class _VehicleGateway(_Gateway):
    def __init__(self, project, children):
        super().__init__(children)
        self.parents = {}
        for unit in project.build_units:
            for vehicle in unit.individuals:
                path = Path(vehicle.company_vehicle_folder_path)
                self.parents[vehicle.company_vehicle_folder_id] = {
                    "id": vehicle.company_vehicle_folder_id, "name": path.name, "folder": {},
                    "parentReference": {"id": "year-id", "path": f"/drives/company-drive/root:/{path.parent}"},
                }

    def get_item(self, ident):
        return self.parents.get(ident)


def test_vehicle_discovery_assigns_to_group_once_and_preserves_unassignment(tmp_path):
    paths = _paths(tmp_path)
    project = _vehicle_project(paths)
    vehicle = project.build_units[0].individuals[0]
    folder = f"{vehicle.company_vehicle_folder_path}/Build Reference Photos"
    gateway = _VehicleGateway(project, {folder: [_file("front.jpg", "front")]})
    result = reconcile_project_photo_folder(project.project_id, scan_project_photo_folder(project, gateway=gateway), paths)
    assert result["added"] == 1
    stored = load_project(project.project_id, paths)
    asset = stored.reference_assets[0]
    assert [(a.scope, a.target_id) for a in asset.assignments] == [("unit_group", "group-1")]
    assert asset.source_path == f"{folder}/front.jpg"
    from dtm_buildsheet.domain.reference_photos import resolve_build_reference_photos
    assert all(len(resolve_build_reference_photos(stored, unit_id="group-1", individual_id=v.individual_id)) == 1
               for v in stored.build_units[0].individuals)
    asset.assignments = []
    save_project(stored, paths)
    gateway.children[folder] = [_file("renamed.jpg", "front")]
    again = reconcile_project_photo_folder(project.project_id, scan_project_photo_folder(stored, gateway=gateway), paths)
    assert again["added"] == 0
    stored = load_project(project.project_id, paths)
    assert len(stored.reference_assets) == 1
    assert stored.reference_assets[0].assignments == []
    assert stored.reference_assets[0].file_name == "renamed.jpg"
    assert handle_delete_reference(project.project_id, asset.reference_id, paths)["ok"]
    reconcile_project_photo_folder(project.project_id, scan_project_photo_folder(stored, gateway=gateway), paths)
    assert load_project(project.project_id, paths).reference_assets == []


def test_moved_vehicle_resolves_item_id_without_scanning_stale_path(tmp_path):
    paths = _paths(tmp_path)
    project = _vehicle_project(paths)
    gateway = _VehicleGateway(project, {"Archive/Renamed/Build Reference Photos": [_file("photo.jpg", "photo")]})
    gateway.parents["parent-1"].update(name="Renamed", parentReference={"id": "archive-id", "path": "/drives/company-drive/root:/Archive"})
    scanned = scan_project_photo_folder(project, gateway=gateway)
    assert scanned["available"]
    assert scanned["photos"][0]["source_path"] == "Archive/Renamed/Build Reference Photos/photo.jpg"
    assert scanned["photos"][0]["unit_id"] == "group-1"


def test_failed_or_stale_vehicle_scan_keeps_existing_references(tmp_path):
    paths = _paths(tmp_path)
    project = _vehicle_project(paths)
    gateway = _VehicleGateway(project, {})
    scanned = scan_project_photo_folder(project, gateway=gateway)
    project.build_units[0].individuals.pop()
    save_project(project, paths)
    assert reconcile_project_photo_folder(project.project_id, scanned, paths)["changed"] == 0
    gateway.parents.pop("parent-1")
    failed = scan_project_photo_folder(project, gateway=gateway)
    assert not failed["available"] and failed["warnings"]
    assert reconcile_project_photo_folder(project.project_id, failed, paths)["changed"] == 0


def test_same_filename_in_two_vehicles_keeps_distinct_sources(tmp_path):
    paths = _paths(tmp_path)
    project = _vehicle_project(paths)
    children = {f"{v.company_vehicle_folder_path}/Build Reference Photos": [_file("front.jpg", v.individual_id)]
                for v in project.build_units[0].individuals}
    result = scan_project_photo_folder(project, gateway=_VehicleGateway(project, children))
    reconcile_project_photo_folder(project.project_id, result, paths)
    stored = load_project(project.project_id, paths)
    assert len(stored.reference_assets) == 2
    assert len({a.source_item_id for a in stored.reference_assets}) == 2
    assert reconcile_project_photo_folder(project.project_id, result, paths)["changed"] == 0


def test_new_references_flag_finalized_builds_without_publishing(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    project = _vehicle_project(paths)
    vehicle = project.build_units[0].individuals[0]
    vehicle.status = "finalized"
    vehicle.shop_publication_status = "published"
    vehicle.shop_pdf_item_id = "approved-pdf"
    project.updated_at = "2020-01-01T00:00:00Z"
    from dtm_buildsheet.inputs.project_entry import save_project_operational_state
    save_project_operational_state(project, paths)
    folder = f"{vehicle.company_vehicle_folder_path}/Build Reference Photos"
    result = scan_project_photo_folder(project, gateway=_VehicleGateway(project, {folder: [_file("new.jpg", "new")]}))
    reconciled = reconcile_project_photo_folder(project.project_id, result, paths)
    stored = load_project(project.project_id, paths)
    assert stored.updated_at != project.updated_at
    assert stored.build_units[0].individuals[0].shop_publication_status == "reference_review_required"
    assert stored.build_units[0].individuals[0].shop_pdf_item_id == "approved-pdf"
    assert reconciled["warnings"]
    from dtm_buildsheet.app.services.shop_publication_service import publish_vehicle_package, retry_pending_shop_publications
    assert not publish_vehicle_package(project.project_id, "group-1", "vehicle-1", paths)["ok"]
    monkeypatch.setattr("dtm_buildsheet.app.services.shop_publication_service.shop_publication_configured", lambda: True)
    assert retry_pending_shop_publications(paths)["attempted"] == 0


def test_existing_inbox_photo_moved_into_vehicle_folder_gets_group_assignment(tmp_path):
    paths = _paths(tmp_path)
    project = _vehicle_project(paths)
    project.reference_assets = [BuildReferenceAsset(
        reference_id="existing", file_name="moved.jpg", source_drive_id="company-drive",
        source_item_id="same-item", source_etag="etag-same-item", source_size=123,
        source_path=f"{project.company_year_folder_path}/Reference Photos & Videos/moved.jpg",
    )]
    save_project(project, paths)
    folder = project.build_units[0].individuals[0].company_vehicle_folder_path + "/Build Reference Photos"
    gateway = _VehicleGateway(project, {folder: [_file("moved.jpg", "same-item")]})
    scanned = scan_project_photo_folder(project, gateway=gateway)
    result = reconcile_project_photo_folder(project.project_id, scanned, paths)
    assert result["added"] == 0 and result["changed"] == 1
    stored = load_project(project.project_id, paths)
    assert len(stored.reference_assets) == 1
    asset = stored.reference_assets[0]
    assert asset.reference_id == "existing" and asset.source_item_id == "same-item"
    assert [(a.scope, a.target_id) for a in asset.assignments] == [("unit_group", "group-1")]
    assert reconcile_project_photo_folder(project.project_id, scanned, paths)["changed"] == 0
    asset.assignments = []
    save_project(stored, paths)
    reconcile_project_photo_folder(project.project_id, scanned, paths)
    assert load_project(project.project_id, paths).reference_assets[0].assignments == []


def test_inbox_move_does_not_add_to_existing_manual_assignment(tmp_path):
    paths = _paths(tmp_path)
    project = _vehicle_project(paths)
    project.reference_assets = [BuildReferenceAsset(
        reference_id="existing", file_name="moved.jpg", source_drive_id="company-drive",
        source_item_id="same-item",
        source_path=f"{project.company_year_folder_path}/Reference Photos & Videos/moved.jpg",
        assignments=[BuildReferenceAssignment(scope="project", note="Keep this instruction")],
    )]
    save_project(project, paths)
    folder = project.build_units[0].individuals[0].company_vehicle_folder_path + "/Build Reference Photos"
    scanned = scan_project_photo_folder(project, gateway=_VehicleGateway(project, {folder: [_file("moved.jpg", "same-item")]}))
    reconcile_project_photo_folder(project.project_id, scanned, paths)
    asset = load_project(project.project_id, paths).reference_assets[0]
    assert len(asset.assignments) == 1
    assert asset.assignments[0].scope == "project" and asset.assignments[0].note == "Keep this instruction"
