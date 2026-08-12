"""Production Customer-link migration tests (hermetic, no network/keychain)."""

from __future__ import annotations

import json

from dtm_buildsheet.app.services import agency_service as agencies
from dtm_buildsheet.app.services import qb_customer_migration_service as migration
from dtm_buildsheet.app.services import qb_sync_service
from dtm_buildsheet.domain.agency_models import AgencyRecord
from dtm_buildsheet.paths import AppPaths


def _customer(customer_id: str, name: str, **fields) -> dict:
    return {"qb_customer_id": customer_id, "name": name, **fields}


def test_name_plan_ignores_colliding_sandbox_ids_and_requires_unique_name():
    local = [
        AgencyRecord(agency_id="a", name="Alpha PD", qb_customer_id="20"),
        AgencyRecord(agency_id="b", name="Beta PD", qb_customer_id="10"),
        AgencyRecord(agency_id="c", name="Gamma PD", qb_customer_id="30"),
    ]
    production = [
        _customer("10", "Alpha Police Department", contact_email="alpha@example.test"),
        _customer("20", "Beta PD"),
        _customer("21", "Beta Police Dept."),
        _customer("40", "Production Only"),
    ]

    plan = migration._build_name_plan(local, production)

    assert plan["summary"] == {
        "local_agencies": 3,
        "production_customers": 4,
        "safe_unique_name_matches": 1,
        "ambiguous_local_agencies": 1,
        "local_without_name_match": 1,
        "production_without_local_name_match": 1,
    }
    safe = plan["safe_matches"][0]
    assert safe["agency"]["name"] == "Alpha PD"
    assert safe["production_customer"]["qb_customer_id"] == "10"
    assert safe["agency"]["baseline_qb_customer_id"] == "20"


def test_customer_migration_state_blocks_import_and_push(tmp_path, monkeypatch):
    paths = AppPaths(workspace_dir=tmp_path)
    (tmp_path / "agencies").mkdir()
    agencies._write_record(AgencyRecord(agency_id="a", name="Alpha PD"), paths)
    agencies._invalidate_cache(paths)
    (tmp_path / "quickbooks_customer_migration_state.json").write_text(
        json.dumps({"status": "required"}), encoding="utf-8"
    )
    called = []
    monkeypatch.setattr(qb_sync_service, "_build_client", lambda p: called.append(1))

    assert qb_sync_service.import_customers(paths) == {
        "ok": False,
        "error": "production_customer_migration_required",
    }
    assert qb_sync_service.push_agency(paths, "a") == {
        "ok": False,
        "error": "production_customer_migration_required",
    }
    assert called == []


def test_future_customer_preview_filters_owner_rejected_duplicates(tmp_path, monkeypatch):
    paths = AppPaths(workspace_dir=tmp_path)
    (tmp_path / "agencies").mkdir()
    agencies._write_record(
        AgencyRecord(agency_id="a", name="Alpha PD", qb_customer_id="100"), paths
    )
    agencies._invalidate_cache(paths)
    (tmp_path / "quickbooks_customer_migration_state.json").write_text(
        json.dumps({
            "status": "complete",
            "ignored_duplicate_customer_ids": ["101"],
        }),
        encoding="utf-8",
    )

    class Client:
        def fetch_active_customers(self):
            return [_customer("100", "Alpha PD"), _customer("101", "Alpha Police Department")]

    monkeypatch.setattr(qb_sync_service, "_build_client", lambda p: (Client(), None))

    assert qb_sync_service.preview_customer_import(paths) == {
        "ok": True,
        "total": 1,
        "would_create": 0,
        "would_update": 1,
    }


def test_finalize_reviewed_links_deletes_and_imports(tmp_path):
    paths = AppPaths(workspace_dir=tmp_path)
    (tmp_path / "agencies").mkdir()
    agencies._write_record(AgencyRecord(agency_id="link", name="Local Link"), paths)
    agencies._write_record(AgencyRecord(agency_id="delete", name="Delete Test"), paths)
    agencies._invalidate_cache(paths)
    migration._write_json(tmp_path / "quickbooks_production_customer_migration_plan.json", {
        "application_status": "safe_matches_applied_exceptions_pending",
        "safe_matches": [],
        "ambiguous": [{
            "agency": {"agency_id": "link", "name": "Local Link", "baseline_qb_customer_id": ""},
            "production_candidates": [
                _customer("100", "Local Link", contact_email="link@example.test"),
                _customer("101", "Local Link Duplicate"),
            ],
        }],
        "local_only": [{
            "agency": {"agency_id": "delete", "name": "Delete Test", "baseline_qb_customer_id": ""},
        }],
        "production_only": [_customer("200", "Imported Agency")],
    })

    result = migration.finalize_reviewed_exceptions(
        paths,
        links_by_agency_name={"Local Link": "100"},
        delete_agency_names=["Delete Test"],
        import_customer_ids=["200"],
        ignored_duplicate_customer_ids=["101"],
        owner_approved=True,
    )

    assert result["ok"] is True
    current = {record.name: record for record in agencies.load_agencies(paths)}
    assert set(current) == {"Local Link", "Imported Agency"}
    assert current["Local Link"].qb_customer_id == "100"
    assert current["Local Link"].contact_email == "link@example.test"
    assert current["Imported Agency"].qb_customer_id == "200"
    assert migration.customer_writes_blocked(paths) is False
    assert migration.ignored_production_customer_ids(paths) == {"101"}
