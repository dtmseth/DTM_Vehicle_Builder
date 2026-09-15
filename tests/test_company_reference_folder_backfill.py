from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from dtm_buildsheet.app.services.company_reference_folder_backfill import (
    apply_reference_folders, plan_reference_folders,
)
from dtm_buildsheet.domain.project_models import BuildUnit, IndividualUnit
from dtm_buildsheet.inputs.project_entry import new_project


class Records:
    drive_id = "records"

    def __init__(self):
        self.project = new_project()
        self.project.build_units = [BuildUnit(unit_id="group", individuals=[IndividualUnit(
            individual_id="vehicle", company_vehicle_folder_id="parent",
            company_vehicle_folder_path="old-path",
        )])]
        self.etag = "v1"

    def list_children(self, path):
        assert path == "Projects"
        return [self.get_item("record")]

    def get_item(self, ident):
        assert ident == "record"
        return {"id": ident, "eTag": self.etag, "name": f"{self.project.project_id}.json"}

    def download_item(self, ident):
        assert ident == "record"
        return json.dumps(asdict(self.project)).encode()


class Company:
    drive_id = "company"

    def __init__(self):
        self.parent = {"id": "parent", "name": "Unit 1", "folder": {},
                       "parentReference": {"id": "year", "path": "/drives/company/root:/Database/Agency/2026"}}
        self.child = None
        self.creates = []

    def get_item(self, ident):
        return self.parent if ident == "parent" else self.child

    def get_item_by_path(self, path):
        assert path == "Database/Agency/2026/Unit 1/Build Reference Photos"
        return self.child

    def ensure_child_folder(self, parent_id, name):
        self.creates.append((parent_id, name))
        self.child = {"id": "reference", "name": name, "folder": {}, "parentReference": {"id": parent_id}}
        return self.child


def test_backfill_uses_live_parent_id_and_is_additive_and_retryable():
    records, company = Records(), Company()
    plan = plan_reference_folders(records, company, root="Database")
    assert plan["blockers"] == []
    assert plan["targets"][0]["parent_path"] == "Database/Agency/2026/Unit 1"
    assert company.creates == []
    report = apply_reference_folders(plan, records, company)
    assert report["ok"] and report["created"] == report["verified"] == 1
    assert company.creates == [("parent", "Build Reference Photos")]
    again = apply_reference_folders(plan, records, company)
    assert again["ok"] and again["created"] == 0 and again["verified"] == 1
    assert len(company.creates) == 1


@pytest.mark.parametrize("change", ["record", "parent", "file", "missing_id", "duplicate"])
def test_backfill_stops_for_unreviewed_or_ambiguous_targets(change):
    records, company = Records(), Company()
    plan = plan_reference_folders(records, company, root="Database")
    if change == "record":
        records.etag = "v2"
    elif change == "parent":
        company.parent["name"] = "Moved"
    elif change == "file":
        company.child = {"id": "file", "name": "Build Reference Photos", "file": {}}
    elif change == "missing_id":
        records.project.build_units[0].individuals[0].company_vehicle_folder_id = ""
        plan = plan_reference_folders(records, company, root="Database")
    else:
        records.project.build_units[0].individuals.append(IndividualUnit(
            individual_id="other", company_vehicle_folder_id="parent"))
        plan = plan_reference_folders(records, company, root="Database")
    if plan["blockers"]:
        with pytest.raises(ValueError):
            apply_reference_folders(plan, records, company)
    else:
        assert not apply_reference_folders(plan, records, company)["ok"]
    assert company.creates == []


def test_child_folder_creation_uses_parent_id_and_refuses_file_collision():
    from dtm_buildsheet.app.adapters.cloud.graph_drive_gateway import GraphDriveGateway, GraphDriveError

    class Response:
        def __init__(self, status, payload):
            self.status_code = status
            self.payload = payload

        def json(self):
            return self.payload

        def raise_for_status(self):
            assert self.status_code < 400

    class Session:
        def __init__(self):
            self.urls = []

        def get(self, url, **kwargs):
            self.urls.append(url)
            return Response(200, {"id": "parent", "folder": {}} if url.endswith("/parent")
                            else {"id": "blocking-file", "file": {}, "parentReference": {"id": "parent"}})

        def post(self, url, **kwargs):
            self.urls.append(url)
            assert url.endswith("/items/parent/children")
            assert kwargs["json"]["@microsoft.graph.conflictBehavior"] == "fail"
            return Response(409, {})

    session = Session()
    gateway = GraphDriveGateway(token="fixture", drive_id="company", session=session)
    with pytest.raises(GraphDriveError, match="file blocks"):
        gateway.ensure_child_folder("parent", "Build Reference Photos")
    assert all("root:" not in url for url in session.urls)
