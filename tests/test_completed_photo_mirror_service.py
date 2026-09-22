from __future__ import annotations

from dtm_buildsheet.app.services.completed_photo_mirror_service import (
    mirror_completed_build_photos,
)
from dtm_buildsheet.domain.project_models import BuildUnit, IndividualUnit
from dtm_buildsheet.inputs.project_entry import new_project, save_project
from dtm_buildsheet.paths import AppPaths


class FakeGateway:
    def __init__(self, folders=None, data=None):
        self.folders = dict(folders or {})
        self.data = dict(data or {})
        self.uploads = []

    def ensure_folder(self, path):
        self.folders.setdefault(path, [])
        return {"id": f"folder:{path}", "name": path.rsplit("/", 1)[-1], "folder": {}}

    def list_children(self, path, **_kwargs):
        if path not in self.folders:
            raise FileNotFoundError(path)
        return list(self.folders[path])

    def download_item(self, item_id, **_kwargs):
        return self.data[item_id]

    def upload_file(self, path, data, **_kwargs):
        self.uploads.append((path, data))
        return {"id": f"uploaded:{path}", "name": path.rsplit("/", 1)[-1], "size": len(data)}


def _paths(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    return AppPaths(workspace_dir=tmp_path, workspace_projects_dir=projects)


def test_mirror_copies_new_updates_changed_and_retains_company_only_files(tmp_path):
    paths = _paths(tmp_path)
    shop_base = "Shop Project Database/Agency/A - 2026/Vehicle"
    company_base = "Vehicle Project Database/Agency/A - 2026/Vehicle"
    source = f"{shop_base}/Completed Build Photos"
    target = f"{company_base}/Completed Build Photos"
    project = new_project(build_units=[BuildUnit(
        unit_id="patrol",
        individuals=[IndividualUnit(
            individual_id="vehicle-1",
            shop_vehicle_folder_path=shop_base,
            company_vehicle_folder_path=company_base,
        )],
    )])
    save_project(project, paths)

    shop = FakeGateway(
        folders={
            source: [
                {"id": "front-source", "name": "front.jpg", "size": 5,
                 "file": {"hashes": {"sha1Hash": "same"}}},
                {"id": "rear-source", "name": "rear.jpg", "size": 4, "file": {}},
                {"id": "detail-folder", "name": "Details", "folder": {}},
            ],
            f"{source}/Details": [
                {"id": "detail-source", "name": "console.png", "size": 7, "file": {}},
            ],
        },
        data={
            "front-source": b"front", "rear-source": b"new!",
            "detail-source": b"console",
        },
    )
    company = FakeGateway(
        folders={
            target: [
                {"id": "front-target", "name": "front.jpg", "size": 5,
                 "file": {"hashes": {"sha1Hash": "same"}}},
                {"id": "rear-target", "name": "rear.jpg", "size": 4, "file": {}},
                {"id": "company-only", "name": "keep.jpg", "size": 4, "file": {}},
            ],
        },
        data={"front-target": b"front", "rear-target": b"old!", "company-only": b"keep"},
    )

    result = mirror_completed_build_photos(
        paths, company_gateway=company, shop_gateway=shop,
    )

    assert result == {
        "enabled": True, "throttled": False, "vehicles": 1,
        "copied": 1, "updated": 1, "unchanged": 1, "failed": 0,
    }
    assert company.uploads == [
        (f"{target}/rear.jpg", b"new!"),
        (f"{target}/Details/console.png", b"console"),
    ]
    assert any(item["name"] == "keep.jpg" for item in company.folders[target])
