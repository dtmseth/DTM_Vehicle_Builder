from __future__ import annotations

from types import SimpleNamespace

from dtm_buildsheet.app.services.shop_publication_service import (
    handle_republish_vehicle_package,
    publish_vehicle_package,
    retry_pending_shop_publications,
    withdraw_vehicle_package,
)
from dtm_buildsheet.domain.project_models import (
    BuildReferenceAsset,
    BuildReferenceAssignment,
    BuildUnit,
    IndividualUnit,
)
from dtm_buildsheet.inputs.project_entry import load_project, new_project, save_project
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


class FakeShopGateway:
    def __init__(self):
        self.folders = []
        self.uploads = []
        self.deleted = []

    def ensure_folder(self, remote_path):
        self.folders.append(remote_path)
        return {"id": "folder:" + remote_path}

    def upload_file(self, remote_path, data):
        self.uploads.append((remote_path, data))
        return {"id": "item:" + remote_path}

    def move_item(self, item_id, *, parent_id, new_name):
        self.folders.append(f"MOVE:{item_id}:{parent_id}:{new_name}")
        return {"id": item_id, "name": new_name}

    def delete_item(self, item_id):
        self.deleted.append(item_id)


def _project(paths, pdf_path):
    project = new_project()
    project.customer.agency = "Lake/County"
    project.customer.build_year = "2027"
    project.build_units = [BuildUnit(
        unit_id="group-1",
        vehicle_model="ford_pi_utility",
        build_type="Patrol",
        individuals=[IndividualUnit(
            individual_id="vehicle-1",
            year="2027",
            make="Ford",
            model="Police Interceptor Utility",
            unit_number="12",
            vin="1FM5K8AR0HGA123456",
            status="finalized",
            pdf_path=str(pdf_path),
        )],
    )]
    save_project(project, paths)
    return project


def test_publish_creates_expected_tree_and_is_idempotent(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF test")
    project = _project(paths, pdf)
    gateway = FakeShopGateway()

    result = publish_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths, gateway=gateway,
    )

    assert result["ok"] is True
    vehicle = (
        "Shop Project Database/Lake County/LC - 2027/"
        "2027 LC PIU - Patrol - Unit 12 - VIN 123456"
    )
    assert gateway.folders == [
        "Shop Project Database/Lake County/LC - 2027",
        vehicle,
        vehicle + "/Build Reference Photos",
        vehicle + "/Completed Build Photos",
    ]
    assert gateway.uploads[0][0] == (
        vehicle + "/2027 LC PIU - Patrol - Unit 12 - VIN 123456.pdf"
    )
    stored = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert stored.shop_publication_status == "published"
    assert stored.shop_vehicle_folder_id == "folder:" + vehicle
    assert stored.shop_vehicle_folder_path == vehicle
    assert stored.shop_folder_status == "provisioned"
    assert stored.shop_pdf_item_id.startswith("item:Shop Project Database/")

    before = (list(gateway.folders), list(gateway.uploads), list(gateway.deleted))
    again = publish_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths, gateway=gateway,
    )
    assert again == {
        "ok": True,
        "unchanged": True,
        "folder_path": vehicle,
        "published_at": stored.shop_published_at,
    }
    assert (gateway.folders, gateway.uploads, gateway.deleted) == before


def test_refresh_replaces_only_owned_reference_items(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF test")
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"photo bytes")
    project = _project(paths, pdf)
    individual = project.build_units[0].individuals[0]
    individual.shop_reference_items = [{"item_id": "old-reference", "file_name": "old.jpg"}]
    individual.shop_pdf_item_id = "old-pdf"
    save_project(project, paths)
    asset = BuildReferenceAsset(reference_id="ref-1", file_name="source.jpg", source_etag="etag-1")
    assignment = BuildReferenceAssignment(scope="individual", target_id="vehicle-1", note="Copy this")
    package = SimpleNamespace(entries=(SimpleNamespace(
        asset=asset,
        assignment=assignment,
        origin="individual",
        published_file_name="01-source.jpg",
        local_path=photo,
    ),), errors=())
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.shop_publication_service.resolve_reference_package",
        lambda *args, **kwargs: package,
    )
    gateway = FakeShopGateway()

    result = publish_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths, gateway=gateway,
    )

    assert result["ok"] is True
    assert gateway.deleted == ["old-reference", "old-pdf"]
    assert not any("Completed Build Photos" in item_id for item_id in gateway.deleted)
    stored = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert stored.shop_reference_items[0]["reference_id"] == "ref-1"
    assert stored.shop_reference_items[0]["file_name"] == "01-source.jpg"


def test_explicit_republish_requires_existing_owned_shop_pdf(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF test")
    project = _project(paths, pdf)
    calls = []
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.shop_publication_service.publish_vehicle_package",
        lambda project_id, unit_id, individual_id, paths: calls.append(
            (project_id, unit_id, individual_id)
        ) or {"ok": True, "unchanged": False},
    )

    missing = handle_republish_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths,
    )
    assert missing["ok"] is False
    assert "existing Shop PDF" in missing["error"]
    assert calls == []

    stored = load_project(project.project_id, paths)
    stored.build_units[0].individuals[0].shop_pdf_item_id = "owned-shop-pdf"
    save_project(stored, paths)
    result = handle_republish_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths,
    )

    assert result == {"ok": True, "unchanged": False}
    assert calls == [(project.project_id, "group-1", "vehicle-1")]


def test_name_change_moves_existing_vehicle_folder_by_id(tmp_path):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF first")
    project = _project(paths, pdf)
    gateway = FakeShopGateway()
    assert publish_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths, gateway=gateway,
    )["ok"]
    stored_project = load_project(project.project_id, paths)
    stored = stored_project.build_units[0].individuals[0]
    original_folder_id = stored.shop_vehicle_folder_id
    stored.unit_number = "99"
    pdf.write_bytes(b"%PDF renamed")
    save_project(stored_project, paths)
    gateway.folders.clear()
    gateway.uploads.clear()
    gateway.deleted.clear()

    result = publish_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths, gateway=gateway,
    )

    assert result["ok"] is True
    assert gateway.folders[0] == "Shop Project Database/Lake County/LC - 2027"
    assert gateway.folders[1].startswith(
        f"MOVE:{original_folder_id}:folder:Shop Project Database/"
    )
    assert gateway.folders[1].endswith(
        ":2027 LC PIU - Patrol - Unit 99 - VIN 123456"
    )
    assert not any("Completed Build Photos" in item_id for item_id in gateway.deleted)
    moved = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert moved.shop_vehicle_folder_id == original_folder_id
    assert "Unit 99" in moved.shop_vehicle_folder_name


def test_withdraw_deletes_exact_owned_ids_and_preserves_folder(tmp_path):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF test")
    project = _project(paths, pdf)
    individual = project.build_units[0].individuals[0]
    individual.status = "reopened"
    individual.shop_vehicle_folder_id = "vehicle-folder"
    individual.shop_vehicle_folder_name = "Readable vehicle"
    individual.shop_pdf_item_id = "owned-pdf"
    individual.shop_reference_items = [
        {"item_id": "owned-reference-1"},
        {"item_id": "owned-reference-2"},
    ]
    save_project(project, paths)
    gateway = FakeShopGateway()

    result = withdraw_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths, gateway=gateway,
    )

    assert result == {"ok": True, "deleted": 3}
    assert gateway.deleted == ["owned-pdf", "owned-reference-1", "owned-reference-2"]
    assert gateway.folders == []
    stored = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert stored.shop_vehicle_folder_id == "vehicle-folder"
    assert stored.shop_vehicle_folder_name == "Readable vehicle"
    assert stored.shop_pdf_item_id == ""
    assert stored.shop_reference_items == []
    assert stored.shop_publication_status == "not_published"


def test_publication_failure_is_durable_and_retryable(tmp_path):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF test")
    project = _project(paths, pdf)

    class BrokenGateway(FakeShopGateway):
        def upload_file(self, remote_path, data):
            raise RuntimeError("remote detail that should not be exposed")

    result = publish_vehicle_package(
        project.project_id, "group-1", "vehicle-1", paths, gateway=BrokenGateway(),
    )

    assert result == {
        "ok": False,
        "error": "Shop publication could not be completed. It will retry during cloud sync.",
    }
    stored = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert stored.status == "finalized"
    assert stored.shop_publication_status == "error"
    assert "remote detail" not in stored.shop_publication_error


def test_retry_catches_finalized_build_from_before_shop_cutover(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "existing-final.pdf"
    pdf.write_bytes(b"%PDF existing")
    project = _project(paths, pdf)
    individual = project.build_units[0].individuals[0]
    individual.shop_publication_status = "not_published"
    save_project(project, paths)
    calls = []
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.shop_publication_service.shop_publication_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.shop_publication_service.publish_vehicle_package",
        lambda project_id, unit_id, individual_id, paths: calls.append(individual_id) or {"ok": True},
    )

    result = retry_pending_shop_publications(paths)

    assert result == {"enabled": True, "attempted": 1, "succeeded": 1, "failed": 0}
    assert calls == ["vehicle-1"]
