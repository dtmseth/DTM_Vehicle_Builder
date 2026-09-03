from __future__ import annotations

from dtm_buildsheet.app.services.agency_service import (
    handle_save_agency,
    save_agency_folder_state,
)
from dtm_buildsheet.app.services.vehicle_folder_provisioning_service import (
    ProvisioningTargets,
    mark_project_folder_provisioning_pending,
    provision_agency_folders,
    provision_project_folders,
    retry_folder_provisioning,
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
    def __init__(self, prefix):
        self.prefix = prefix
        self.folders = []
        self.moves = []
        self.uploads = []
        self.deleted = []

    def ensure_folder(self, path):
        self.folders.append(path)
        return {"id": f"{self.prefix}:{path}"}

    def move_item(self, item_id, *, parent_id, new_name):
        self.moves.append((item_id, parent_id, new_name))
        return {"id": item_id, "name": new_name}

    def upload_file(self, path, data):
        self.uploads.append((path, data))
        raise AssertionError("provisioning must never upload or copy source files")

    def delete_item(self, item_id):
        self.deleted.append(item_id)
        raise AssertionError("provisioning must never delete existing data")


class ItemAwareGateway(FakeGateway):
    def __init__(self, prefix, items):
        super().__init__(prefix)
        self.items = items

    def get_item(self, item_id):
        return self.items.get(item_id)


def _agency(paths, name="Lake County"):
    result = handle_save_agency({"name": name}, paths)
    assert result["ok"] is True
    return result["agency"]["agency_id"]


def test_agency_provisioning_creates_both_roots_and_persists_item_ids(tmp_path):
    paths = _paths(tmp_path)
    agency_id = _agency(paths)
    company = FakeGateway("company")
    shop = FakeGateway("shop")

    result = provision_agency_folders(
        agency_id,
        paths,
        company_gateway=company,
        shop_gateway=shop,
    )

    assert result == {
        "ok": True, "enabled": True, "attempted": 2, "succeeded": 2, "failed": 0,
    }
    assert company.folders == ["Vehicle Project Database/Lake County"]
    assert shop.folders == ["Shop Project Database/Lake County"]
    from dtm_buildsheet.app.services.agency_service import get_agency
    stored = get_agency(paths, agency_id)
    assert stored.company_folder_id == "company:Vehicle Project Database/Lake County"
    assert stored.shop_folder_id == "shop:Shop Project Database/Lake County"
    assert stored.company_folder_status == stored.shop_folder_status == "provisioned"


def test_project_provisioning_builds_progressive_tree_with_stable_placeholders(tmp_path):
    paths = _paths(tmp_path)
    agency_id = _agency(paths)
    project = new_project()
    project.customer.agency_id = agency_id
    project.customer.agency = "Lake County"
    project.customer.build_year = "2027"
    project.build_units = [
        BuildUnit(
            unit_id="patrol",
            vehicle_model="Ford Police Interceptor Utility",
            build_type="Patrol",
            individuals=[
                IndividualUnit(individual_id="unit-12", unit_number="12"),
                IndividualUnit(individual_id="unknown"),
            ],
        ),
        BuildUnit(
            unit_id="past-build",
            vehicle_model="Chevrolet Tahoe",
            build_type="Command",
            individuals=[IndividualUnit(individual_id="archive")],
        ),
    ]
    save_project(project, paths)
    original_updated_at = load_project(project.project_id, paths).updated_at
    company = FakeGateway("company")
    shop = FakeGateway("shop")

    result = provision_project_folders(
        project.project_id,
        paths,
        company_gateway=company,
        shop_gateway=shop,
    )

    assert result["ok"] is True
    normal_name = "2027 LC PIU - Patrol - Unit 12"
    normal_shop = f"Shop Project Database/Lake County/LC - 2027/{normal_name}"
    assert "Vehicle Project Database/Lake County/LC - 2027/Reference Photos & Videos" in company.folders
    assert any(path.endswith(normal_name) for path in company.folders)
    assert normal_shop + "/Build Reference Photos" in shop.folders
    assert normal_shop + "/Completed Build Photos" in shop.folders
    assert company.uploads == shop.uploads == []
    assert company.deleted == shop.deleted == []

    stored = load_project(project.project_id, paths)
    assert stored.build_units[0].company_group_folder_path == ""
    assert stored.build_units[0].company_group_folder_id == ""
    assert stored.build_units[0].shop_group_folder_path == ""
    assert stored.build_units[0].shop_group_folder_id == ""
    normal, unknown = stored.build_units[0].individuals
    archive = stored.build_units[1].individuals[0]
    assert stored.updated_at == original_updated_at
    assert normal.shop_vehicle_folder_path == normal_shop
    assert unknown.company_folder_status == unknown.shop_folder_status == "provisioned"
    assert unknown.shop_vehicle_folder_path.endswith(
        "/2027 LC PIU - Patrol - Pending ID UNKNOWN"
    )
    assert archive.company_folder_status == archive.shop_folder_status == "provisioned"
    assert archive.company_vehicle_folder_path.endswith(
        "/2027 LC Tahoe - Command - Pending ID ARCHIVE"
    )
    assert archive.shop_vehicle_folder_path.endswith(
        "/2027 LC Tahoe - Command - Pending ID ARCHIVE"
    )


def test_renamed_vehicle_moves_existing_subtree_by_item_id(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.customer.agency = "Lake County"
    project.customer.build_year = "2027"
    project.build_units = [BuildUnit(
        unit_id="patrol",
        vehicle_model="Ford PI Utility",
        build_type="Patrol",
        individuals=[IndividualUnit(individual_id="vehicle", unit_number="12")],
    )]
    save_project(project, paths)
    shop = FakeGateway("shop")
    assert provision_project_folders(
        project.project_id, paths, shop_gateway=shop,
    )["ok"]
    stored = load_project(project.project_id, paths)
    vehicle = stored.build_units[0].individuals[0]
    folder_id = vehicle.shop_vehicle_folder_id
    vehicle.unit_number = "99"
    save_project(stored, paths)
    shop.moves.clear()

    assert provision_project_folders(
        project.project_id, paths, shop_gateway=shop,
    )["ok"]

    assert shop.moves
    assert shop.moves[-1][0] == folder_id
    assert shop.moves[-1][2].endswith("Unit 99")


def test_placeholder_folder_moves_by_item_id_when_vin_arrives(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.customer.agency = "Lake County"
    project.customer.build_year = "2027"
    project.build_units = [BuildUnit(
        unit_id="patrol",
        vehicle_model="PIU",
        build_type="Patrol",
        individuals=[IndividualUnit(
            individual_id="8a9743c8-e428-440c-b5f0-4833d7a33bfc",
            existing_unit_number="03",
        )],
    )]
    save_project(project, paths)
    shop = FakeGateway("shop")

    assert provision_project_folders(
        project.project_id, paths, shop_gateway=shop,
    )["ok"]
    stored = load_project(project.project_id, paths)
    vehicle = stored.build_units[0].individuals[0]
    folder_id = vehicle.shop_vehicle_folder_id
    assert vehicle.shop_vehicle_folder_name.endswith("Pending ID 8A9743C8")

    vehicle.vin = "1FM5K8AB6SGC43753"
    save_project(stored, paths)
    shop.moves.clear()
    assert provision_project_folders(
        project.project_id, paths, shop_gateway=shop,
    )["ok"]

    assert shop.moves[-1][0] == folder_id
    assert shop.moves[-1][2] == "2027 LC PIU - Patrol - VIN C43753"
    moved = load_project(project.project_id, paths).build_units[0].individuals[0]
    assert moved.shop_vehicle_folder_id == folder_id
    assert moved.shop_vehicle_folder_name == "2027 LC PIU - Patrol - VIN C43753"


def test_agency_rename_uses_current_agency_record_for_project_paths(tmp_path):
    paths = _paths(tmp_path)
    agency_id = _agency(paths, "Lake County")
    project = new_project()
    project.customer.agency_id = agency_id
    project.customer.agency = "Lake County"
    project.customer.build_year = "2027"
    project.build_units = [BuildUnit(
        unit_id="patrol",
        vehicle_model="Tahoe",
        build_type="Patrol",
        individuals=[IndividualUnit(individual_id="vehicle", unit_number="12")],
    )]
    save_project(project, paths)
    company = FakeGateway("company")
    shop = FakeGateway("shop")
    assert provision_project_folders(
        project.project_id, paths, company_gateway=company, shop_gateway=shop,
    )["ok"]
    assert handle_save_agency({
        "agency_id": agency_id,
        "name": "Lake County Sheriff's Office",
    }, paths)["ok"]
    company.folders.clear()
    company.moves.clear()
    shop.folders.clear()
    shop.moves.clear()

    assert provision_project_folders(
        project.project_id, paths, company_gateway=company, shop_gateway=shop,
    )["ok"]

    assert company.moves[0][2] == "Lake County Sheriff's Office"
    assert shop.moves[0][2] == "Lake County Sheriff's Office"
    assert all("/Lake County/" not in path for path in company.folders + shop.folders)
    stored = load_project(project.project_id, paths)
    assert stored.build_units[0].company_group_folder_id == ""
    assert stored.build_units[0].shop_group_folder_id == ""
    assert "/Lake County Sheriff's Office/Lake - 2027" in stored.company_year_folder_path
    assert "/Lake County Sheriff's Office/Lake - 2027" in stored.shop_year_folder_path


def test_vehicle_inside_legacy_group_moves_directly_under_renamed_year(tmp_path):
    paths = _paths(tmp_path)
    agency_id = _agency(paths, "Immigration & Customs Enforcement (ICE)")
    legacy_agency = "Vehicle Project Database/Immigration Customs Enforcement (ICE)"
    save_agency_folder_state(paths, agency_id, {
        "company_folder_id": "agency-id",
        "company_folder_path": legacy_agency,
        "company_folder_status": "provisioned",
    })
    project = new_project()
    project.customer.agency_id = agency_id
    project.customer.agency = "Immigration & Customs Enforcement (ICE)"
    project.customer.agency_abbreviation = "ICE"
    project.customer.build_year = "2026"
    legacy_group = (
        "Vehicle Project Database/Immigration Customs Enforcement (ICE)/2026/PIU - Admin"
    )
    individual = IndividualUnit(
        individual_id="vehicle",
        vin="1234567890C43753",
        company_vehicle_folder_id="vehicle-id",
        company_vehicle_folder_path=legacy_group + "/2026 PIU - Admin - VIN C43753",
    )
    project.build_units = [BuildUnit(
        unit_id="admin",
        vehicle_model="PIU",
        build_type="Admin",
        individuals=[individual],
    )]
    project.company_year_folder_id = "year-id"
    project.company_year_folder_path = (
        "Vehicle Project Database/Immigration Customs Enforcement (ICE)/2026"
    )
    save_project(project, paths)
    company = FakeGateway("company")

    assert provision_project_folders(
        project.project_id, paths, company_gateway=company,
    )["ok"]

    assert any(
        item_id == "vehicle-id"
        and new_name == "2026 ICE PIU - Admin - VIN C43753"
        for item_id, _parent_id, new_name in company.moves
    )
    assert legacy_group not in company.folders
    stored = load_project(project.project_id, paths)
    assert stored.build_units[0].company_group_folder_id == ""
    assert stored.build_units[0].company_group_folder_path == ""
    assert stored.build_units[0].individuals[0].company_vehicle_folder_path.endswith(
        "/ICE - 2026/2026 ICE PIU - Admin - VIN C43753"
    )


def test_out_of_band_vehicle_move_is_reconciled_from_durable_item_id(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.customer.agency = "Edina Police Department"
    project.customer.agency_abbreviation = "EPD"
    project.customer.build_year = "2025"
    old_group = "Shop Project Database/Edina Police Department/EPD - 2025/2025 EPD Vehicle - K-9 Build(s)"
    live_group = "Shop Project Database/Edina Police Department/EPD - 2025/2025 EPD PIU - K-9 Build(s)"
    vehicle_id = "durable-vehicle-id"
    individual = IndividualUnit(
        individual_id="k9",
        shop_vehicle_folder_id=vehicle_id,
        shop_vehicle_folder_path=f"{old_group}/2025 EPD Vehicle - K-9 - Pending ID K9",
    )
    project.build_units = [BuildUnit(
        unit_id="k9-group",
        vehicle_model="PIU",
        build_type="K-9",
        individuals=[individual],
    )]
    project.shop_year_folder_id = "year-id"
    project.shop_year_folder_path = "Shop Project Database/Edina Police Department/EPD - 2025"
    save_project(project, paths)
    shop = ItemAwareGateway("shop", {
        vehicle_id: {
            "id": vehicle_id,
            "name": "2025 EPD PIU - K-9 - Pending ID K9",
            "parentReference": {
                "id": "live-group-id",
                "path": f"/drives/shop/root:/{live_group}",
            },
        },
    })

    assert provision_project_folders(
        project.project_id, paths, shop_gateway=shop,
    )["ok"]

    assert all(path != old_group for path in shop.folders)
    assert not any(item_id == "live-group-id" for item_id, _parent, _name in shop.moves)
    assert any(item_id == vehicle_id for item_id, _parent, _name in shop.moves)
    stored = load_project(project.project_id, paths)
    unit = stored.build_units[0]
    vehicle = unit.individuals[0]
    assert unit.shop_group_folder_id == ""
    assert unit.shop_group_folder_path == ""
    assert vehicle.shop_vehicle_folder_id == vehicle_id
    assert vehicle.shop_vehicle_folder_path == (
        "Shop Project Database/Edina Police Department/EPD - 2025/"
        "2025 EPD PIU - K-9 - Pending ID K9"
    )


def test_flattening_rewrites_owned_descendant_publication_paths(tmp_path):
    paths = _paths(tmp_path)
    project = new_project()
    project.customer.agency = "Lake County"
    project.customer.build_year = "2027"
    group = "Shop Project Database/Lake County/LC - 2027/2027 LC PIU - Patrol Build(s)"
    individual = IndividualUnit(
        individual_id="vehicle",
        unit_number="12",
        shop_vehicle_folder_id="vehicle-id",
        shop_vehicle_folder_path=f"{group}/old-name",
        shop_pdf_item_id="pdf-id",
        shop_pdf_path=f"{group}/old-name/old-name.pdf",
        shop_reference_items=[{
            "item_id": "ref-id",
            "file_name": "01-reference.jpg",
            "path": f"{group}/old-name/Build Reference Photos/01-reference.jpg",
        }],
    )
    project.build_units = [BuildUnit(
        unit_id="patrol",
        vehicle_model="PIU",
        build_type="Patrol",
        individuals=[individual],
    )]
    save_project(project, paths)

    assert provision_project_folders(
        project.project_id, paths, shop_gateway=FakeGateway("shop"),
    )["ok"]

    moved = load_project(project.project_id, paths).build_units[0].individuals[0]
    flat = (
        "Shop Project Database/Lake County/LC - 2027/"
        "2027 LC PIU - Patrol - Unit 12"
    )
    assert moved.shop_vehicle_folder_path == flat
    assert moved.shop_pdf_path == f"{flat}/2027 LC PIU - Patrol - Unit 12.pdf"
    assert moved.shop_reference_items[0]["path"] == (
        f"{flat}/Build Reference Photos/01-reference.jpg"
    )


def test_pending_marker_survives_before_background_worker(monkeypatch):
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.vehicle_folder_provisioning_service.folder_provisioning_targets",
        lambda: ProvisioningTargets(True, True),
    )
    project = new_project()
    project.build_units = [BuildUnit(
        unit_id="group",
        individuals=[
            IndividualUnit(individual_id="build", vin="123456789"),
            IndividualUnit(individual_id="sparse"),
        ],
    )]

    assert mark_project_folder_provisioning_pending(project) is True
    normal, history = project.build_units[0].individuals
    assert project.company_folder_status == project.shop_folder_status == "pending"
    assert normal.company_folder_status == normal.shop_folder_status == "pending"
    assert history.company_folder_status == history.shop_folder_status == "pending"


def test_retry_ignores_standalone_agency_manager_records(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    standalone_id = _agency(paths, "Unrelated QBO Customer")
    linked_id = _agency(paths, "Current Project Agency")
    project = new_project()
    project.customer.agency_id = linked_id
    project.customer.agency = "Current Project Agency"
    project.customer.build_year = "2027"
    save_project(project, paths)

    agency_calls = []
    project_calls = []
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.vehicle_folder_provisioning_service.folder_provisioning_targets",
        lambda: ProvisioningTargets(True, True),
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.vehicle_folder_provisioning_service.provision_agency_folders",
        lambda agency_id, _paths: agency_calls.append(agency_id) or {"ok": True},
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.vehicle_folder_provisioning_service.provision_project_folders",
        lambda project_id, _paths: project_calls.append(project_id) or {"ok": True},
    )

    result = retry_folder_provisioning(paths)

    assert result == {"enabled": True, "agencies": 1, "projects": 1, "failed": 0}
    assert agency_calls == [linked_id]
    assert standalone_id not in agency_calls
    assert project_calls == [project.project_id]
