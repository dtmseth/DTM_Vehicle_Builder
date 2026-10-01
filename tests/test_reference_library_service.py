from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dtm_buildsheet.app.adapters.cloud.graph_drive_gateway import GraphDriveGateway
from dtm_buildsheet.app.services import reference_library_service as library
from dtm_buildsheet.app.services.request_access_service import required_capabilities
from dtm_buildsheet.app.services.reference_library_service import (
    _BrowseRoot,
    discover_agency_reference_media,
)
from dtm_buildsheet.domain.operations_policy import Capability
from dtm_buildsheet.domain.project_models import BuildUnit, IndividualUnit
from dtm_buildsheet.inputs.project_entry import new_project, save_project
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path):
    for name in ("projects", "drafts", "config", "output"):
        (tmp_path / name).mkdir()
    return AppPaths(
        workspace_dir=tmp_path,
        workspace_projects_dir=tmp_path / "projects",
        workspace_drafts_dir=tmp_path / "drafts",
        workspace_config_dir=tmp_path / "config",
        workspace_output_dir=tmp_path / "output",
    )


class TreeGateway:
    def __init__(self, drive_id, tree):
        self.drive_id = drive_id
        self.tree = tree

    def list_children(self, remote_path):
        if remote_path not in self.tree:
            raise FileNotFoundError(remote_path)
        return self.tree[remote_path]


def _folder(name, item_id):
    return {"id": item_id, "name": name, "folder": {}}


def _file(name, item_id, *, size=10):
    return {"id": item_id, "name": name, "size": size, "eTag": "etag-" + item_id,
            "webUrl": "https://example.invalid/" + item_id, "file": {}}


def test_discovers_only_organized_same_agency_media(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.customer.agency = "Lake County"
    save_project(project, paths)
    company = TreeGateway("company-drive", {
        "Vehicle Project Database/Lake County": [_folder("2025", "y25"), _folder("2026", "y26")],
        "Vehicle Project Database/Lake County/2025": [
            _folder("Reference Photos & Videos", "refs"),
            _file("loose.jpg", "loose"),
        ],
        "Vehicle Project Database/Lake County/2025/Reference Photos & Videos": [
            _file("push-bumper.jpg", "photo-1"),
            _file("unsupported.heic", "heic"),
            _file("walkaround.mov", "video-1"),
        ],
        "Vehicle Project Database/Lake County/2026": [],
    })
    shop = TreeGateway("shop-drive", {
        "Shop Project Database/Lake County": [_folder("2024", "y24")],
        "Shop Project Database/Lake County/2024": [_folder("Tahoe - Patrol", "patrol")],
        "Shop Project Database/Lake County/2024/Tahoe - Patrol": [_folder("2024 Tahoe - Patrol - Unit 12", "unit")],
        "Shop Project Database/Lake County/2024/Tahoe - Patrol/2024 Tahoe - Patrol - Unit 12": [
            _folder("Build Reference Photos", "shop-refs"),
            _folder("Completed Build Photos", "completed"),
        ],
        "Shop Project Database/Lake County/2024/Tahoe - Patrol/2024 Tahoe - Patrol - Unit 12/Build Reference Photos": [
            _file("published.jpg", "published"),
        ],
        "Shop Project Database/Lake County/2024/Tahoe - Patrol/2024 Tahoe - Patrol - Unit 12/Completed Build Photos": [
            _file("finished.png", "completed-1"),
            _file("shop-video.mp4", "shop-video"),
        ],
    })

    result = discover_agency_reference_media(project.project_id, paths, roots=[
        _BrowseRoot(company, "Vehicle Project Database/Lake County", "company_reference"),
        _BrowseRoot(shop, "Shop Project Database/Lake County", "shop_completed"),
    ])

    assert result["ok"] is True
    assert result["available"] is True
    assert {(item["source_item_id"], item["media_type"], item["source_kind"])
            for item in result["references"]} == {
        ("photo-1", "photo", "company_reference"),
        ("video-1", "video", "company_reference"),
        ("completed-1", "photo", "shop_completed"),
    }
    assert not any(item["source_item_id"] in {"loose", "heic", "published", "shop-video"}
                   for item in result["references"])


def test_cloud_off_discovery_is_a_safe_empty_state(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.customer.agency = "Lake County"
    save_project(project, paths)

    result = discover_agency_reference_media(project.project_id, paths)

    assert result["ok"] is True
    assert result["available"] is False
    assert result["references"] == []
    assert "cloud-off" in result["warnings"][0]


def test_discovered_video_can_open_in_browser_and_request_microsoft_preview(
    tmp_path, monkeypatch,
):
    paths = _paths(tmp_path)
    enriched = library._enrich_thumbnails("project-1", {  # noqa: SLF001
        "references": [{
            "file_name": "walkaround.mp4",
            "media_type": "video",
            "source_kind": "company_reference",
            "source_drive_id": "company-drive",
            "source_item_id": "video-1",
            "source_path": "Agency/Reference Photos & Videos/walkaround.mp4",
            "source_web_url": "https://tenant.sharepoint.com/walkaround.mp4",
            "source_etag": "etag-video-1",
        }],
    }, paths)
    video = enriched["references"][0]
    opened = []
    monkeypatch.setattr(library.webbrowser, "open", lambda url, new=0: opened.append((url, new)) or True)

    class PreviewGateway:
        def __init__(self, *, token, drive_id):
            assert (token, drive_id) == ("TOKEN", "company-drive")

        def preview_item(self, item_id):
            assert item_id == "video-1"
            return "https://tenant.sharepoint.com/preview/video-1"

    bundle = SimpleNamespace(
        identity=SimpleNamespace(is_signed_in=lambda: True),
        storage=SimpleNamespace(_token_provider=lambda: "TOKEN"),
    )
    monkeypatch.setattr(library.wiring, "_cloud_flag_enabled", lambda: True)
    monkeypatch.setattr(library.wiring, "get_active_bundle", lambda: bundle)
    monkeypatch.setattr(library, "GraphDriveGateway", PreviewGateway)

    opened_result = library.handle_open_reference_video(
        "project-1", {"video_token": video["video_token"]},
    )
    preview_result = library.handle_preview_reference_video(
        "project-1", {"video_token": video["video_token"]},
    )

    assert opened_result == {"ok": True}
    assert opened == [("https://tenant.sharepoint.com/walkaround.mp4", 2)]
    assert preview_result == {
        "ok": True,
        "preview_url": "https://tenant.sharepoint.com/preview/video-1",
        "file_name": "walkaround.mp4",
    }
    assert library.handle_open_reference_video(
        "other-project", {"video_token": video["video_token"]},
    )["ok"] is False


def test_graph_gateway_requests_short_lived_drive_item_preview():
    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"getUrl": "https://tenant.sharepoint.com/short-lived-preview"}

    class Session:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    session = Session()
    gateway = GraphDriveGateway(token="TOKEN", drive_id="company-drive", session=session)

    assert gateway.preview_item("video/item") == "https://tenant.sharepoint.com/short-lived-preview"
    url, kwargs = session.calls[0]
    assert url.endswith("/drives/company-drive/items/video%2Fitem/preview")
    assert kwargs["json"] == {}
    assert kwargs["headers"]["Authorization"] == "Bearer TOKEN"


def test_reference_video_ui_and_routes_are_read_only():
    root = Path(__file__).parents[1]
    script = (root / "src/dtm_buildsheet/ui/js/projects/reference_photos.js").read_text("utf-8")
    html = (root / "src/dtm_buildsheet/ui/index.html").read_text("utf-8")

    assert "Play here" in script
    assert "Play in browser" in script
    assert "PT_previewReferenceVideo" in script
    assert "PT_openGalleryVideo" in script
    assert "_ptLoadCurrentProjectVideos" in script
    assert "data-project-reference-summary" in script
    assert "_ptSetProjectVideoCount(sourceProject, videos.length)" in script
    assert "checking videos…" in script
    assert 'data-reference-media-type="${esc(asset.media_type || "photo")}"' in script
    assert 'row.dataset.referenceMediaType !== "video"' in script
    assert 'galleryItems = [...galleryItems, ...videos]' in script
    assert 'item.media_type === "video" ? -1 : itemIndex' in script
    assert 'id="reference-video-frame"' in html
    assert 'referrerpolicy="no-referrer"' in html
    assert required_capabilities(
        "POST", "/api/project/project-1/references/video-open",
    ) == frozenset({Capability.PROJECTS_VIEW})
    assert required_capabilities(
        "POST", "/api/project/project-1/references/video-preview",
    ) == frozenset({Capability.PROJECTS_VIEW})


def test_discovers_photos_in_nested_completed_subfolders(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.customer.agency = "Lake County"
    save_project(project, paths)
    shop = TreeGateway("shop-drive", {
        "Shop Project Database/Lake County": [_folder("2025", "year")],
        "Shop Project Database/Lake County/2025": [_folder("Completed Build Photos", "done")],
        "Shop Project Database/Lake County/2025/Completed Build Photos": [_folder("K9", "k9")],
        "Shop Project Database/Lake County/2025/Completed Build Photos/K9": [
            _file("cargo.jpg", "cargo"),
        ],
    })

    result = discover_agency_reference_media(project.project_id, paths, roots=[
        _BrowseRoot(shop, "Shop Project Database/Lake County", "shop_completed"),
    ])

    assert [item["source_item_id"] for item in result["references"]] == ["cargo"]


def test_discovery_adds_vehicle_and_build_context_from_durable_folder_paths(tmp_path):
    paths = _paths(tmp_path)
    vehicle_path = "Shop Project Database/Lake County/LC - 2025/Patrol/2025 LC Tahoe - Patrol - Unit 12"
    project = new_project(build_units=[BuildUnit(
        unit_id="group-1",
        vehicle_model="Tahoe",
        build_type="Patrol",
        individuals=[IndividualUnit(
            individual_id="vehicle-1",
            make="Chevrolet",
            model="Tahoe",
            unit_number="12",
            shop_vehicle_folder_path=vehicle_path,
        )],
    )])
    project.customer.agency = "Lake County"
    project.customer.build_year = "2025"
    save_project(project, paths)
    shop = TreeGateway("shop-drive", {
        "Shop Project Database/Lake County": [_folder("LC - 2025", "year")],
        "Shop Project Database/Lake County/LC - 2025": [_folder("Patrol", "group")],
        "Shop Project Database/Lake County/LC - 2025/Patrol": [_folder("2025 LC Tahoe - Patrol - Unit 12", "unit")],
        vehicle_path: [_folder("Completed Build Photos", "photos")],
        f"{vehicle_path}/Completed Build Photos": [_file("rear.jpg", "rear")],
    })

    result = discover_agency_reference_media(project.project_id, paths, roots=[
        _BrowseRoot(shop, "Shop Project Database/Lake County", "shop_completed"),
    ])

    item = result["references"][0]
    assert item["source_agency"] == "Lake County"
    assert item["source_build_year"] == "2025"
    assert item["source_vehicle_make"] == "Chevrolet"
    assert item["source_vehicle_model"] == "Tahoe"
    assert item["source_build_type"] == "Patrol"
    assert all(value in item["source_vehicle_name"] for value in (
        "2025", "LC", "Tahoe", "Patrol", "Unit 12",
    ))
