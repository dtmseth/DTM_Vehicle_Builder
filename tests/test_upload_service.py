from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from pillow_heif import register_heif_opener

from dtm_buildsheet.app.services import photo_gallery_service as gallery
from dtm_buildsheet.app.services import shared_work_service
from dtm_buildsheet.app.services import upload_service as uploads
from dtm_buildsheet.domain.operations_policy import AppRole, Capability, capabilities_for_roles
from dtm_buildsheet.app.services.reference_photo_service import handle_remove_gallery_references
from dtm_buildsheet.domain.project_models import BuildReferenceAsset, BuildUnit, IndividualUnit
from dtm_buildsheet.inputs.project_entry import load_project, new_project, save_project
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path: Path) -> AppPaths:
    workspace = tmp_path / "workspace"
    projects = workspace / "projects"
    projects.mkdir(parents=True)
    return AppPaths(workspace_dir=workspace, workspace_projects_dir=projects)


def _disable_background_work(monkeypatch) -> None:
    monkeypatch.setattr(
        shared_work_service,
        "mirror_project_to_cloud_in_background",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(uploads, "start_upload_manager", lambda _paths: None)
    monkeypatch.setattr(
        uploads,
        "_manager_for",
        lambda _paths: SimpleNamespace(wake=lambda: None),
    )


class _Gateway:
    drive_id = "drive-company"

    def __init__(self, existing: dict | None = None):
        self.existing = existing
        self.folders: list[str] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.deleted: list[str] = []

    def ensure_folder(self, remote_path: str):
        self.folders.append(remote_path)

    def get_item_by_path(self, _remote_path: str, **_kwargs):
        return self.existing

    def upload_local_file(self, remote_path, local_path, *, progress, stop_event, **_kwargs):
        assert not stop_event.is_set()
        data = Path(local_path).read_bytes()
        progress(len(data), len(data))
        self.uploads.append((remote_path, data))
        return {
            "id": "item-1",
            "name": Path(remote_path).name,
            "webUrl": "https://contoso.sharepoint.com/item-1",
            "eTag": "etag-1",
        }

    def delete_item(self, item_id: str):
        self.deleted.append(item_id)


def test_heic_project_upload_writes_jpeg_to_sharepoint(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    _disable_background_work(monkeypatch)
    project = new_project(project_id="project-1")
    project.company_year_folder_path = "Vehicle Project Database/Metro/2026"
    save_project(project, paths)

    register_heif_opener()
    source = tmp_path / "iphone-photo.heic"
    Image.new("RGB", (24, 16), (25, 80, 140)).save(source, format="HEIF")
    data = source.read_bytes()
    created = uploads.create_upload_job(paths, {
        "project_id": project.project_id,
        "file_name": source.name,
        "file_size": len(data),
        "content_type": "image/heic",
    }, destination_kind="project")
    uploads.stage_upload_content(paths, created["job_id"], io.BytesIO(data), len(data))

    gateway = _Gateway()
    monkeypatch.setattr(uploads, "_gateway_for", lambda _library: gateway)
    result = uploads.process_upload_job(paths, created["job_id"])

    assert result["status"] == "complete"
    assert result["stored_name"] == "iphone-photo.jpg"
    assert result["converted_from"] == "HEIC"
    assert gateway.uploads[0][0].endswith("/Reference Photos & Videos/iphone-photo.jpg")
    assert gateway.uploads[0][1].startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(gateway.uploads[0][1])) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (24, 16)

    saved = load_project(project.project_id, paths)
    assert len(saved.reference_assets) == 1
    assert saved.reference_assets[0].file_name == "iphone-photo.jpg"
    assert saved.reference_assets[0].source_path.endswith("iphone-photo.jpg")
    assert saved.reference_assets[0].media_type == "photo"


def test_completed_documents_use_technician_files_and_appear_as_files(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    _disable_background_work(monkeypatch)
    project = new_project(
        project_id="project-2",
        build_units=[BuildUnit(
            unit_id="group-1",
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                shop_vehicle_folder_path="Shop Project Database/Metro/2026/Vehicle 1",
            )],
        )],
    )
    save_project(project, paths)
    job = {
        "destination_kind": "completed",
        "media_type": "file",
        "unit_id": "group-1",
        "individual_id": "vehicle-1",
    }

    library, folder = uploads._destination(project, job)

    assert library == "shop"
    assert folder.endswith("/Vehicle 1/Technician Files")
    technician_folder = tmp_path / "Technician Files"
    technician_folder.mkdir()
    (technician_folder / "wiring-diagram.pdf").write_bytes(b"%PDF-1.7\n")
    completed = gallery._CompletedFolder(
        remote_path=folder,
        label="Vehicle 1",
        unit_id="group-1",
        individual_id="vehicle-1",
        folder_kind="technician_files",
    )
    items = gallery._local_folder_items(technician_folder, completed)
    assert items[0]["media_type"] == "file"
    assert items[0]["source_kind"] == "shop_technician_file"
    assert gallery._completed_presence(items) == {"project": False, "targets": {}}


def test_restart_recovers_a_fully_staged_file(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    recover_uploads = uploads.start_upload_manager
    _disable_background_work(monkeypatch)
    project = new_project(project_id="project-3")
    project.company_year_folder_path = "Vehicle Project Database/Metro/2026"
    save_project(project, paths)
    data = b"durable staged bytes"
    created = uploads.create_upload_job(paths, {
        "project_id": project.project_id,
        "file_name": "notes.txt",
        "file_size": len(data),
    }, destination_kind="project")
    job = uploads._load_job(paths, created["job_id"])
    staged = Path(job["staged_path"])
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.with_suffix(staged.suffix + ".part").write_bytes(data)
    uploads._update_job(paths, created["job_id"], status="staging", phase="Copying")

    recover_uploads(paths)
    recovered = uploads._load_job(paths, created["job_id"])

    assert recovered["status"] == "queued"
    assert staged.read_bytes() == data
    assert recovered["bytes_staged"] == len(data)
    assert recovered["sha256"]


def test_restart_adopts_a_completed_sharepoint_item_without_duplicate_upload(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    _disable_background_work(monkeypatch)
    project = new_project(project_id="project-4")
    project.company_year_folder_path = "Vehicle Project Database/Metro/2026"
    save_project(project, paths)
    data = b"already reached SharePoint"
    created = uploads.create_upload_job(paths, {
        "project_id": project.project_id,
        "file_name": "install-notes.txt",
        "file_size": len(data),
    }, destination_kind="project")
    uploads.stage_upload_content(paths, created["job_id"], io.BytesIO(data), len(data))
    remote_path = "Vehicle Project Database/Metro/2026/Project Files/install-notes.txt"
    uploads._update_job(
        paths,
        created["job_id"],
        status="uploading",
        remote_path=remote_path,
    )
    gateway = _Gateway(existing={
        "id": "recovered-item",
        "name": "install-notes.txt",
        "size": len(data),
        "webUrl": "https://contoso.sharepoint.com/recovered-item",
        "eTag": "etag-recovered",
    })
    monkeypatch.setattr(uploads, "_gateway_for", lambda _library: gateway)

    result = uploads.process_upload_job(paths, created["job_id"])

    assert result["status"] == "complete"
    assert result["source_item_id"] == "recovered-item"
    assert gateway.uploads == []
    assert load_project(project.project_id, paths).reference_assets[0].source_item_id == "recovered-item"


def test_shop_role_can_upload_completed_media_but_not_project_media():
    capabilities = capabilities_for_roles([AppRole.SHOP_EDITOR])
    assert Capability.COMPLETED_MEDIA_UPLOAD in capabilities
    assert Capability.PROJECT_MEDIA_UPLOAD not in capabilities


def test_completed_upload_notice_can_be_acknowledged(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    _disable_background_work(monkeypatch)
    project = new_project(project_id="project-5")
    project.company_year_folder_path = "Vehicle Project Database/Metro/2026"
    save_project(project, paths)
    created = uploads.create_upload_job(paths, {
        "project_id": project.project_id,
        "file_name": "diagram.pdf",
        "file_size": 12,
    }, destination_kind="project")
    uploads._update_job(
        paths,
        created["job_id"],
        status="complete",
        phase="Complete",
        completed_at="2026-10-20T12:00:00+00:00",
    )

    assert uploads.list_upload_jobs(paths)["unacknowledged_complete_count"] == 1
    result = uploads.acknowledge_completed_uploads(paths)
    status = uploads.list_upload_jobs(paths)

    assert result == {"ok": True, "acknowledged": 1}
    assert status["unacknowledged_complete_count"] == 0
    assert status["jobs"][0]["acknowledged_at"]


def test_project_file_can_be_removed_from_gallery_without_deleting_source(tmp_path):
    paths = _paths(tmp_path)
    project = new_project(project_id="project-6")
    project.reference_assets.append(BuildReferenceAsset(
        reference_id="file-reference",
        file_name="wiring-diagram.pdf",
        media_type="file",
        source_kind="company_reference",
        source_drive_id="drive-company",
        source_item_id="file-item",
        source_path="Vehicle Project Database/Metro/2026/Project Files/wiring-diagram.pdf",
    ))
    save_project(project, paths)

    result = handle_remove_gallery_references(project.project_id, {
        "photo_tokens": [],
        "reference_ids": ["file-reference"],
        "target_unit_id": "",
    }, paths)

    assert result["ok"] is True
    assert result["removed"] == 1
    saved = load_project(project.project_id, paths)
    assert saved.reference_assets == []
    assert saved.reference_source_exclusions == ["item:drive-company:file-item"]
