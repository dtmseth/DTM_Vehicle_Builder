from dtm_buildsheet.app.services.company_vehicle_folder_service import (
    publish_company_vehicle_pdf,
    retry_pending_company_vehicle_pdfs,
)
from dtm_buildsheet.domain.project_models import BuildUnit, IndividualUnit
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


class FakeGateway:
    def __init__(self):
        self.folders = []
        self.uploads = []
        self.deleted = []

    def ensure_folder(self, path):
        self.folders.append(path)
        return {"id": "folder:" + path}

    def upload_file(self, path, data):
        self.uploads.append((path, data))
        return {"id": "item:" + path}

    def move_item(self, item_id, *, parent_id, new_name):
        self.folders.append(f"MOVE:{item_id}:{parent_id}:{new_name}")
        return {"id": item_id, "name": new_name}

    def delete_item(self, item_id):
        self.deleted.append(item_id)


def test_company_vehicle_pdf_uses_canonical_tree_and_replaces_exact_old_item(tmp_path):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "build.pdf"
    pdf.write_bytes(b"%PDF company")
    project = new_project()
    project.customer.agency = "Lake County"
    project.customer.build_year = "2027"
    project.build_units = [BuildUnit(
        unit_id="group-1",
        vehicle_model="Ford PI Utility",
        build_type="Patrol",
        individuals=[IndividualUnit(
            individual_id="vehicle-1", unit_number="12", vin="12345678901234567",
            year="2027", make="Ford", model="Police Interceptor Utility",
            pdf_path=str(pdf), company_pdf_item_id="old-company-pdf",
        )],
    )]
    save_project(project, paths)
    gateway = FakeGateway()

    result = publish_company_vehicle_pdf(
        project.project_id, "group-1", "vehicle-1", paths, gateway=gateway,
    )

    year_root = "Vehicle Project Database/Lake County/LC - 2027"
    vehicle = year_root + "/2027 LC PIU - Patrol - Unit 12 - VIN 234567"
    assert result["ok"] is True
    assert gateway.folders == [
        year_root,
        year_root + "/Reference Photos & Videos",
        vehicle,
    ]
    assert gateway.uploads[0][0] == vehicle + "/2027 LC PIU - Patrol - Unit 12 - VIN 234567.pdf"
    assert gateway.deleted == ["old-company-pdf"]
    stored = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert stored.company_vehicle_folder_id == "folder:" + vehicle
    assert stored.company_vehicle_folder_path == vehicle
    assert stored.company_folder_status == "provisioned"
    assert stored.company_publication_status == "published"

    counts = (len(gateway.folders), len(gateway.uploads), len(gateway.deleted))
    again = publish_company_vehicle_pdf(
        project.project_id, "group-1", "vehicle-1", paths, gateway=gateway,
    )
    assert again == {"ok": True, "unchanged": True, "path": stored.company_pdf_path}
    assert (len(gateway.folders), len(gateway.uploads), len(gateway.deleted)) == counts


def test_retry_catches_exported_pdf_from_before_company_cutover(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    pdf = paths.workspace_output_dir / "existing-export.pdf"
    pdf.write_bytes(b"%PDF existing")
    project = new_project()
    project.build_units = [BuildUnit(
        unit_id="group-1",
        individuals=[
            IndividualUnit(
                individual_id="vehicle-1",
                pdf_path=str(pdf),
                company_publication_status="not_published",
            ),
            IndividualUnit(
                individual_id="vehicle-without-local-pdf",
                pdf_path="",
                company_publication_status="not_published",
            ),
        ],
    )]
    save_project(project, paths)
    calls = []
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.company_vehicle_folder_service.company_vehicle_folders_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.company_vehicle_folder_service.publish_company_vehicle_pdf",
        lambda project_id, unit_id, individual_id, paths: calls.append(individual_id) or {"ok": True},
    )

    result = retry_pending_company_vehicle_pdfs(paths)

    assert result == {"enabled": True, "attempted": 1, "succeeded": 1, "failed": 0}
    assert calls == ["vehicle-1"]
