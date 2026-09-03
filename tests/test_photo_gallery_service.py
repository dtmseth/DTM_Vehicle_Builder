from __future__ import annotations

import time
import threading
from concurrent.futures import Future
from types import SimpleNamespace
from pathlib import Path

from PIL import Image

from dtm_buildsheet.app.services import photo_gallery_service as gallery
from dtm_buildsheet.domain.project_models import (
    BuildReferenceAsset,
    BuildReferenceAssignment,
    BuildUnit,
    IndividualUnit,
)
from dtm_buildsheet.inputs.project_entry import new_project, save_project
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path: Path) -> AppPaths:
    projects = tmp_path / "projects"
    projects.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return AppPaths(
        workspace_dir=workspace,
        workspace_projects_dir=projects,
    )


def _photo(path: Path) -> None:
    Image.new("RGB", (1200, 800), (35, 85, 125)).save(path, "JPEG")


def test_cloud_portrait_thumbnail_uses_exact_source_without_letterboxing(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    source = tmp_path / "portrait.jpg"
    Image.new("RGB", (800, 1200), (28, 74, 116)).save(source, "JPEG")
    item = gallery._PhotoSource(
        token="portrait-exact-source",
        project_id="project-1",
        file_name="portrait.jpg",
        source_kind="shop_completed",
        source_drive_id="drive-1",
        source_item_id="item-1",
    )
    monkeypatch.setattr(
        gallery,
        "resolve_reference_media",
        lambda _asset, _paths, **_kwargs: SimpleNamespace(path=source),
    )

    thumbnail = gallery._build_thumbnail(item, paths)

    assert thumbnail == paths.workspace_reference_cache_dir / "thumbnails-v2" / "portrait-exact-source.jpg"
    with Image.open(thumbnail) as image:
        assert image.size == (320, 480)


def test_reference_gallery_is_immediate_and_scope_aware(tmp_path):
    paths = _paths(tmp_path)
    project = new_project(build_units=[BuildUnit(
        unit_id="group-1",
        individuals=[IndividualUnit(individual_id="vehicle-1")],
    )])
    project.reference_assets = [BuildReferenceAsset(
        reference_id="project-photo",
        file_name="front.jpg",
        source_drive_id="drive-1",
        source_item_id="photo-1",
        source_path="Vehicle Project Database/Agency/2025/Reference Photos & Videos/front.jpg",
        assignments=[BuildReferenceAssignment(scope="project", note="Copy this bracket")],
    )]
    save_project(project, paths)

    result = gallery.handle_photo_gallery(project.project_id, {
        "kind": "reference", "unit_id": "group-1", "individual_id": "vehicle-1",
    }, paths)

    assert result["ok"] is True
    assert result["loading"] is False
    assert len(result["photos"]) == 1
    item = result["photos"][0]
    assert item["note"] == "Copy this bracket"
    assert item["assignment_state"] == "legacy"
    assert item["source_key"] == "drive-1::photo-1"
    assert item["thumbnail_url"].endswith("/thumbnail")
    assert "source_drive_id" not in item


def test_project_gallery_marks_assigned_and_unassigned_photos(tmp_path):
    paths = _paths(tmp_path)
    project = new_project(build_units=[BuildUnit(unit_id="group-1")])
    project.reference_assets = [
        BuildReferenceAsset(
            reference_id="unassigned",
            file_name="front.jpg",
            source_path="Company/Reference Photos & Videos/front.jpg",
        ),
        BuildReferenceAsset(
            reference_id="assigned",
            file_name="rear.jpg",
            source_path="Company/Reference Photos & Videos/rear.jpg",
            assignments=[BuildReferenceAssignment(
                scope="unit_group", target_id="group-1", note="Match the bracket",
            )],
        ),
    ]
    save_project(project, paths)

    result = gallery.handle_photo_gallery(project.project_id, {"kind": "reference"}, paths)

    by_name = {item["file_name"]: item for item in result["photos"]}
    assert by_name["front.jpg"]["assignment_state"] == "unassigned"
    assert by_name["front.jpg"]["label"] == "Unassigned"
    assert by_name["rear.jpg"]["assignment_state"] == "assigned"
    assert by_name["rear.jpg"]["note"] == "Match the bracket"


class _SharedThumbnailGateway:
    def __init__(self, *, existing: bytes | None = None):
        self.existing = existing
        self.ensured = []
        self.uploaded = []

    def get_item_by_path(self, remote_path, **_kwargs):
        if self.existing is None:
            return None
        return {"id": "shared-thumb", "name": Path(remote_path).name, "file": {}}

    def download_item(self, item_id, **_kwargs):
        assert item_id == "shared-thumb"
        return self.existing

    def ensure_folder(self, remote_path, **_kwargs):
        self.ensured.append(remote_path)
        return {"id": "folder", "folder": {}}

    def upload_file(self, remote_path, data, **_kwargs):
        self.uploaded.append((remote_path, data))
        return {"id": "uploaded", "name": Path(remote_path).name}


def test_shared_thumbnail_cache_avoids_original_photo_download(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    shared = tmp_path / "shared.jpg"
    Image.new("RGB", (320, 480), (40, 80, 120)).save(shared, "JPEG")
    gateway = _SharedThumbnailGateway(existing=shared.read_bytes())
    source = gallery._PhotoSource(
        token="a" * 32,
        project_id="project-1",
        file_name="portrait.jpg",
        source_kind="shop_completed",
        source_drive_id="drive-1",
        source_item_id="item-1",
        source_etag="etag-1",
    )
    monkeypatch.setattr(gallery, "_shared_thumbnail_gateway", lambda _source: gateway)
    monkeypatch.setattr(
        gallery,
        "resolve_reference_media",
        lambda *_args: (_ for _ in ()).throw(AssertionError("original should not download")),
    )

    thumbnail = gallery._build_thumbnail(source, paths)

    assert thumbnail.is_file()
    assert gateway.uploaded == []
    with Image.open(thumbnail) as image:
        assert image.size == (320, 480)


def test_generated_thumbnail_is_uploaded_to_shared_cache(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    original = tmp_path / "original.jpg"
    _photo(original)
    gateway = _SharedThumbnailGateway()
    source = gallery._PhotoSource(
        token="b" * 32,
        project_id="project-1",
        file_name="finished.jpg",
        source_kind="shop_completed",
        source_drive_id="drive-1",
        source_item_id="item-1",
        source_etag="etag-1",
    )
    monkeypatch.setattr(gallery, "_shared_thumbnail_gateway", lambda _source: gateway)
    monkeypatch.setattr(
        gallery,
        "resolve_reference_media",
        lambda _asset, _paths, **_kwargs: SimpleNamespace(path=original),
    )

    gallery._build_thumbnail(source, paths)

    assert gateway.ensured == ["Settings/_DTM Photo Thumbnail Cache/v2/bb"]
    assert len(gateway.uploaded) == 1
    remote_path, data = gateway.uploaded[0]
    assert remote_path.endswith(f"/{'b' * 32}.jpg")
    assert data


def test_completed_gallery_scans_in_background_and_serves_cached_thumbnail(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    source = tmp_path / "finished.jpg"
    _photo(source)
    project = new_project(build_units=[BuildUnit(
        unit_id="group-1",
        vehicle_model="Tahoe",
        individuals=[IndividualUnit(
            individual_id="vehicle-1",
            shop_vehicle_folder_path="Shop Project Database/Agency/A - 2025/Group/Vehicle",
        )],
    )])
    save_project(project, paths)
    monkeypatch.setattr(gallery, "_scan_completed", lambda folders: ([{
        "file_name": "finished.jpg",
        "source_kind": "shop_completed",
        "source_path": f"{folders[0].remote_path}/finished.jpg",
        "source_etag": "local:1",
        "source_size": source.stat().st_size,
        "local_path": str(source),
        "label": folders[0].label,
        "_unit_id": folders[0].unit_id,
        "_individual_id": folders[0].individual_id,
    }], []))

    result = gallery.handle_photo_gallery(project.project_id, {"kind": "completed"}, paths)
    assert result["loading"] is True
    for _attempt in range(100):
        result = gallery.handle_photo_gallery(project.project_id, {"kind": "completed"}, paths)
        if not result["loading"]:
            break
        time.sleep(0.01)

    assert result["loading"] is False
    assert [item["file_name"] for item in result["photos"]] == ["finished.jpg"]
    presence = gallery.handle_photo_gallery(project.project_id, {
        "kind": "completed", "presence_only": True,
    }, paths)
    assert presence["photos"] == []
    assert presence["presence"] == {
        "project": True,
        "targets": {"group-1::vehicle-1": 1},
    }
    token = result["photos"][0]["photo_token"]
    status, data, content_type, _name, cache_state = gallery.get_gallery_media(token, "thumbnail", paths)
    assert status == 200
    assert content_type == "image/jpeg"
    assert cache_state == "preview"
    assert len(data) < source.stat().st_size
    for _attempt in range(100):
        status, data, content_type, _name, cache_state = gallery.get_gallery_media(
            token, "content", paths,
        )
        if status != 202:
            break
        time.sleep(0.01)
    assert status == 200
    assert content_type == "image/jpeg"
    assert cache_state == "ready"
    assert data == source.read_bytes()


def test_completed_presence_cache_is_returned_while_folder_refresh_runs(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    project = new_project(build_units=[BuildUnit(
        unit_id="group-1",
        vehicle_model="Tahoe",
        individuals=[IndividualUnit(
            individual_id="vehicle-1",
            shop_vehicle_folder_path="Shop Project Database/Agency/A - 2025/Group/Vehicle",
        )],
    )])
    save_project(project, paths)
    folders = gallery._completed_folders(project, unit_id="", individual_id="")
    scan_key = gallery._scan_key(project.project_id, folders)
    cached_item = {
        "file_name": "finished.jpg",
        "_unit_id": "group-1",
        "_individual_id": "vehicle-1",
    }
    gallery._save_completed_presence(scan_key, [cached_item], [], paths)

    pending = Future()
    fake_executor = SimpleNamespace(submit=lambda *_args, **_kwargs: pending)
    monkeypatch.setattr(gallery, "_SCAN_RESULTS", {})
    monkeypatch.setattr(gallery, "_SCAN_JOBS", {})
    monkeypatch.setattr(gallery, "_SCAN_EXECUTOR", fake_executor)

    result = gallery.handle_photo_gallery(project.project_id, {
        "kind": "completed", "presence_only": True,
    }, paths)

    assert result["loading"] is True
    assert result["presence"] == {
        "project": True,
        "targets": {"group-1::vehicle-1": 1},
    }


def test_transient_completed_scan_does_not_erase_known_presence(tmp_path):
    paths = _paths(tmp_path)
    scan_key = "known-completed-folder"
    cached_item = {
        "file_name": "finished.jpg",
        "_unit_id": "group-1",
        "_individual_id": "vehicle-1",
    }
    gallery._save_completed_presence(scan_key, [cached_item], [], paths)

    gallery._save_completed_presence(
        scan_key, [], ["Could not load completed photos."], paths,
    )

    assert gallery._load_completed_presence(scan_key, paths)["project"] is True


def test_unknown_gallery_token_cannot_read_arbitrary_local_file(tmp_path):
    status, data, content_type, _name, cache_state = gallery.get_gallery_media(
        "0" * 32, "content", _paths(tmp_path),
    )
    assert (status, data, content_type) == (404, b"Not found", "text/plain")
    assert cache_state == "missing"


def test_visible_thumbnail_returns_preparing_instead_of_waiting_forever(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    token = "c" * 32
    source = gallery._PhotoSource(
        token=token,
        project_id="project-1",
        file_name="slow.jpg",
        source_kind="shop_completed",
        local_path=str(tmp_path / "not-downloaded.jpg"),
    )
    future = Future()
    monkeypatch.setattr(gallery, "_SOURCES", {token: source})
    monkeypatch.setattr(gallery, "_THUMBNAIL_FOREGROUND_WAIT_SECONDS", 0)
    monkeypatch.setattr(
        gallery,
        "_schedule_thumbnail",
        lambda requested, _paths, *, foreground: future
        if requested == token and foreground else None,
    )

    status, data, content_type, name, cache_state = gallery.get_gallery_media(
        token, "thumbnail", paths,
    )

    assert (status, data, content_type, name) == (
        202, b"Preparing", "text/plain", "slow.jpg",
    )
    assert cache_state == "preparing"


def test_visible_thumbnail_falls_back_to_exact_after_preview_failure(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    token = "9" * 32
    source = gallery._PhotoSource(
        token=token,
        project_id="project-1",
        file_name="fallback.jpg",
        source_kind="shop_completed",
    )
    failed_preview = Future()
    failed_preview.set_result(None)
    exact_pending = Future()
    exact_calls = []
    monkeypatch.setattr(gallery, "_SOURCES", {token: source})
    monkeypatch.setattr(gallery, "_PREVIEW_JOBS", {token: failed_preview})
    monkeypatch.setattr(
        gallery,
        "_schedule_preview",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a failed preview must not restart in the request loop")
        ),
    )
    monkeypatch.setattr(
        gallery,
        "_schedule_thumbnail",
        lambda requested, _paths, *, foreground: (
            exact_calls.append((requested, foreground)) or exact_pending
        ),
    )

    status, data, content_type, name, cache_state = gallery.get_gallery_media(
        token, "thumbnail", paths,
    )

    assert (status, data, content_type, name, cache_state) == (
        202, b"Preparing", "text/plain", "fallback.jpg", "preparing",
    )
    assert exact_calls == [(token, True)]


def test_thumbnail_network_work_yields_to_full_resolution_priority(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    source = gallery._PhotoSource(
        token="5" * 32,
        project_id="project-1",
        file_name="yield.jpg",
        source_kind="shop_completed",
        source_drive_id="drive-1",
        source_item_id="item-1",
    )
    monkeypatch.setattr(gallery, "_wait_for_full_resolution_priority", lambda: False)
    monkeypatch.setattr(
        gallery,
        "_source_thumbnail_gateway",
        lambda _source: (_ for _ in ()).throw(
            AssertionError("thumbnail network work must remain paused")
        ),
    )

    assert gallery._build_preview(source, paths) is None


def test_visible_thumbnail_serves_persistent_preview_before_exact_cache(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    token = "2" * 32
    source = gallery._PhotoSource(
        token=token,
        project_id="project-1",
        file_name="fast.jpg",
        source_kind="shop_completed",
    )
    preview = tmp_path / "preview.jpg"
    Image.new("RGB", (320, 240), (20, 70, 110)).save(preview, "JPEG")
    gallery._preview_path(token, paths).parent.mkdir(parents=True, exist_ok=True)
    gallery._preview_path(token, paths).write_bytes(preview.read_bytes())
    pending = Future()
    monkeypatch.setattr(gallery, "_SOURCES", {token: source})
    monkeypatch.setattr(gallery, "_schedule_thumbnail", lambda *_args, **_kwargs: pending)

    status, data, content_type, name, cache_state = gallery.get_gallery_media(
        token, "thumbnail", paths,
    )

    assert (status, content_type, name, cache_state) == (
        200, "image/jpeg", "fast.jpg", "preview",
    )
    assert data == preview.read_bytes()


def test_cache_prepare_registers_project_photos_and_reports_progress(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    photo = tmp_path / "reference.jpg"
    _photo(photo)
    project = new_project()
    project.reference_assets = [BuildReferenceAsset(
        reference_id="reference-1",
        file_name="reference.jpg",
        source_path=str(photo),
        source_etag="local:1",
    )]
    save_project(project, paths)
    key = gallery._cache_prep_key(paths)
    monkeypatch.setitem(gallery._CACHE_PREP_STATES, key, {
        "phase": "discovering", "projects_done": 0, "projects_total": 0,
    })
    scheduled = []
    monkeypatch.setattr(
        gallery, "_schedule_preview",
        lambda token, _paths, *, foreground: scheduled.append((token, foreground)),
    )
    monkeypatch.setattr(
        gallery, "_schedule_thumbnail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("startup must not hydrate full-resolution photos")
        ),
    )

    gallery._prepare_thumbnail_cache(paths, key)

    assert len(scheduled) == 1
    assert scheduled[0][1] is False
    assert gallery._CACHE_PREP_STATES[key] == {
        "phase": "preparing", "projects_done": 1, "projects_total": 1,
    }


def test_cache_prepare_never_scans_every_completed_folder(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    project = new_project(build_units=[BuildUnit(
        unit_id="group-1",
        individuals=[IndividualUnit(
            individual_id="vehicle-1",
            shop_vehicle_folder_path="Shop Project Database/Agency/A - 2025/Group/Vehicle",
        )],
    )])
    save_project(project, paths)
    key = gallery._cache_prep_key(paths)
    monkeypatch.setitem(gallery._CACHE_PREP_STATES, key, {
        "phase": "checking", "projects_done": 0, "projects_total": 0,
    })
    monkeypatch.setattr(
        gallery,
        "_scan_completed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("startup must not scan every completed-photo folder")
        ),
    )

    gallery._prepare_thumbnail_cache(paths, key)

    assert gallery._CACHE_PREP_STATES[key]["projects_done"] == 1


def test_unchanged_photo_catalog_skips_background_prepare(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    save_project(project, paths)
    projects = [project]
    gallery._save_photo_catalog_fingerprint(
        paths, gallery._photo_catalog_fingerprint(projects),
    )
    key = gallery._cache_prep_key(paths)
    monkeypatch.setattr(gallery, "_CACHE_PREP_JOBS", {})
    monkeypatch.setattr(gallery, "_CACHE_PREP_STATES", {})
    monkeypatch.setattr(gallery, "_SOURCES", {})
    monkeypatch.setattr(gallery, "_PREVIEW_JOBS", {})
    monkeypatch.setattr(gallery, "_THUMBNAIL_JOBS", {})
    monkeypatch.setattr(gallery, "_FULL_RESOLUTION_JOBS", {})

    status = gallery.start_thumbnail_cache_prepare(paths)

    assert status["active"] is False
    assert status["phase"] == "complete"
    assert status["projects_done"] == status["projects_total"] == 1


def test_thumbnail_cache_status_reports_ready_preparing_and_failed(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    ready_token = "d" * 32
    pending_token = "e" * 32
    failed_token = "f" * 32
    sources = {
        token: gallery._PhotoSource(
            token=token,
            project_id="project-1",
            file_name=f"{token[0]}.jpg",
            source_kind="shop_completed",
        )
        for token in (ready_token, pending_token, failed_token)
    }
    gallery._thumbnail_path(ready_token, paths).parent.mkdir(parents=True, exist_ok=True)
    gallery._thumbnail_path(ready_token, paths).write_bytes(b"cached")
    pending = Future()
    failed = Future()
    failed.set_result(None)
    exact_still_queued = Future()
    monkeypatch.setattr(gallery, "_SOURCES", sources)
    monkeypatch.setattr(gallery, "_PREVIEW_JOBS", {
        pending_token: pending,
        failed_token: failed,
    })
    monkeypatch.setattr(gallery, "_THUMBNAIL_JOBS", {
        failed_token: exact_still_queued,
    })

    assert gallery.get_thumbnail_cache_status(paths) == {
        "ok": True,
        "active": True,
        "phase": "preparing",
        "total": 3,
        "ready": 1,
        "preparing": 1,
        "failed": 1,
        "projects_done": 0,
        "projects_total": 0,
        "full_resolution_active": False,
        "full_resolution_count": 0,
        "full_resolution_file": "",
    }


def test_photo_gallery_shutdown_cancels_queued_work_without_waiting(monkeypatch):
    shutdown_event = threading.Event()
    pending = [Future() for _ in range(5)]

    class _Executor:
        def __init__(self):
            self.calls = []

        def shutdown(self, **kwargs):
            self.calls.append(kwargs)

    executors = [_Executor() for _ in range(6)]
    monkeypatch.setattr(gallery, "_SHUTDOWN_EVENT", shutdown_event)
    monkeypatch.setattr(gallery, "_SCAN_JOBS", {"scan": pending[0]})
    monkeypatch.setattr(gallery, "_THUMBNAIL_JOBS", {"exact": pending[1]})
    monkeypatch.setattr(gallery, "_PREVIEW_JOBS", {"preview": pending[2]})
    monkeypatch.setattr(gallery, "_CACHE_PREP_JOBS", {"prep": pending[3]})
    monkeypatch.setattr(gallery, "_FULL_RESOLUTION_JOBS", {"full": pending[4]})
    monkeypatch.setattr(gallery, "_THUMBNAIL_PREP_EXECUTOR", executors[0])
    monkeypatch.setattr(gallery, "_PREVIEW_BACKGROUND_EXECUTOR", executors[1])
    monkeypatch.setattr(gallery, "_THUMBNAIL_EXACT_EXECUTOR", executors[2])
    monkeypatch.setattr(gallery, "_THUMBNAIL_FOREGROUND_EXECUTOR", executors[3])
    monkeypatch.setattr(gallery, "_SCAN_EXECUTOR", executors[4])
    monkeypatch.setattr(gallery, "_FULL_RESOLUTION_EXECUTOR", executors[5])

    gallery.shutdown_photo_gallery_workers()

    assert shutdown_event.is_set()
    assert all(future.cancelled() for future in pending)
    assert all(executor.calls == [{"wait": False, "cancel_futures": True}] for executor in executors)


def test_full_resolution_gallery_download_has_a_bounded_cloud_timeout(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    token = "1" * 32
    source = gallery._PhotoSource(
        token=token,
        project_id="project-1",
        file_name="full.jpg",
        source_kind="company_reference",
        source_drive_id="drive-1",
        source_item_id="item-1",
    )
    observed = {}
    def resolve(_asset, _paths, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(path=None)

    monkeypatch.setattr(gallery, "resolve_reference_media", resolve)

    assert gallery._build_full_resolution(source, paths) is None

    assert observed["download_timeout_seconds"] == 18


def test_full_resolution_content_reports_background_download_then_serves_cache(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    token = "7" * 32
    source = gallery._PhotoSource(
        token=token,
        project_id="project-1",
        file_name="full.jpg",
        source_kind="company_reference",
    )
    pending = Future()
    monkeypatch.setattr(gallery, "_SOURCES", {token: source})
    monkeypatch.setattr(gallery, "_FULL_RESOLUTION_JOBS", {token: pending})

    status, data, content_type, name, cache_state = gallery.get_gallery_media(
        token, "content", paths,
    )

    assert (status, data, content_type, name, cache_state) == (
        202, b"Downloading", "text/plain", "full.jpg", "preparing",
    )

    cached = gallery._full_resolution_path(source, paths)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"full photo")
    pending.set_result(cached)
    status, data, content_type, name, cache_state = gallery.get_gallery_media(
        token, "content", paths,
    )

    assert (status, data, content_type, name, cache_state) == (
        200, b"full photo", "image/jpeg", "full.jpg", "ready",
    )


def test_local_full_resolution_is_copied_into_persistent_app_cache(tmp_path):
    paths = _paths(tmp_path)
    original = tmp_path / "local.jpg"
    original.write_bytes(b"local full photo")
    source = gallery._PhotoSource(
        token="8" * 32,
        project_id="project-1",
        file_name="local.jpg",
        source_kind="shop_completed",
        local_path=str(original),
    )

    cached = gallery._build_full_resolution(source, paths)

    assert cached == gallery._full_resolution_path(source, paths)
    assert cached != original
    assert cached.read_bytes() == original.read_bytes()


def test_full_resolution_status_takes_priority_over_thumbnail_progress(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    token = "6" * 32
    pending_full = Future()
    pending_preview = Future()
    source = gallery._PhotoSource(
        token=token,
        project_id="project-1",
        file_name="priority.jpg",
        source_kind="shop_completed",
    )
    monkeypatch.setattr(gallery, "_SOURCES", {token: source})
    monkeypatch.setattr(gallery, "_PREVIEW_JOBS", {token: pending_preview})
    monkeypatch.setattr(gallery, "_FULL_RESOLUTION_JOBS", {token: pending_full})
    monkeypatch.setattr(gallery, "_FULL_RESOLUTION_CURRENT_TOKEN", token)

    status = gallery.get_thumbnail_cache_status(paths)

    assert status["active"] is True
    assert status["phase"] == "full_resolution"
    assert status["full_resolution_active"] is True
    assert status["full_resolution_count"] == 1
    assert status["full_resolution_file"] == "priority.jpg"
