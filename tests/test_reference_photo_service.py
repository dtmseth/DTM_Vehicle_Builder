from __future__ import annotations

from dtm_buildsheet.app.services.reference_photo_service import (
    handle_delete_reference,
    handle_effective_references,
    handle_list_references,
    handle_import_gallery_references,
    handle_remove_gallery_references,
    handle_save_reference,
)
from dtm_buildsheet.domain.project_models import BuildUnit, IndividualUnit
from dtm_buildsheet.inputs.project_entry import new_project, save_project
from dtm_buildsheet.paths import AppPaths


def _paths(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    return AppPaths(workspace_dir=tmp_path, workspace_projects_dir=projects)


def _saved_project(paths):
    project = new_project(
        project_id="project-1",
        build_units=[BuildUnit(
            unit_id="group-1",
            individuals=[IndividualUnit(individual_id="vehicle-1")],
        )],
    )
    save_project(project, paths)
    return project


def _reference(**overrides):
    reference = {
        "reference_id": "photo-1",
        "file_name": "console.jpg",
        "media_type": "photo",
        "source_kind": "shop_completed",
        "source_drive_id": "shop-drive",
        "source_item_id": "item-1",
        "source_path": "Agency/2025/Patrol/Unit 1/Completed Build Photos/console.jpg",
        "assignments": [{
            "scope": "individual",
            "target_id": "vehicle-1",
            "note": "Match this mounting position.",
            "sort_order": 2,
        }],
    }
    reference.update(overrides)
    return reference


def test_save_list_and_resolve_reference(tmp_path):
    paths = _paths(tmp_path)
    _saved_project(paths)

    saved = handle_save_reference("project-1", {"reference": _reference()}, paths)
    listed = handle_list_references("project-1", paths)
    effective = handle_effective_references(
        "project-1", {"unit_id": "group-1", "individual_id": "vehicle-1"}, paths,
    )

    assert saved["ok"] is True
    assert [item["reference_id"] for item in listed["references"]] == ["photo-1"]
    assert effective["references"][0]["assignment"]["note"] == "Match this mounting position."
    assert effective["references"][0]["origin"] == "individual"


def test_upsert_replaces_metadata_without_duplicating(tmp_path):
    paths = _paths(tmp_path)
    _saved_project(paths)
    handle_save_reference("project-1", _reference(), paths)

    updated = _reference(file_name="updated.jpg")
    result = handle_save_reference("project-1", updated, paths)

    assert result["ok"] is True
    listed = handle_list_references("project-1", paths)
    assert [item["file_name"] for item in listed["references"]] == ["updated.jpg"]


def test_invalid_or_duplicate_targets_are_rejected(tmp_path):
    paths = _paths(tmp_path)
    _saved_project(paths)

    missing = handle_save_reference("project-1", _reference(assignments=[{
        "scope": "individual", "target_id": "missing",
    }]), paths)
    duplicate = handle_save_reference("project-1", _reference(assignments=[
        {"scope": "project"}, {"scope": "project"},
    ]), paths)

    assert missing["ok"] is False
    assert "unknown individual unit" in missing["error"]
    assert duplicate["ok"] is False
    assert "repeat the same assignment" in duplicate["error"]
    assert handle_list_references("project-1", paths)["references"] == []


def test_source_path_cannot_escape_library(tmp_path):
    paths = _paths(tmp_path)
    _saved_project(paths)

    result = handle_save_reference(
        "project-1",
        _reference(source_item_id="", source_path="../../outside.jpg"),
        paths,
    )

    assert result["ok"] is False
    assert "portable" in result["error"]


def test_video_cannot_use_shop_completed_source(tmp_path):
    paths = _paths(tmp_path)
    _saved_project(paths)

    result = handle_save_reference(
        "project-1", _reference(file_name="walkaround.mov", media_type="video"), paths,
    )

    assert result["ok"] is False
    assert "cannot contain reference videos" in result["error"]


def test_delete_removes_metadata_but_reports_no_source_mutation(tmp_path):
    paths = _paths(tmp_path)
    _saved_project(paths)
    handle_save_reference("project-1", _reference(), paths)

    result = handle_delete_reference("project-1", "photo-1", paths)

    assert result == {"ok": True}
    assert handle_list_references("project-1", paths)["references"] == []


def test_gallery_photos_import_unassigned_without_copying_local_paths(tmp_path):
    from dtm_buildsheet.app.services.photo_gallery_service import decorate_photo_items

    paths = _paths(tmp_path)
    source = new_project(project_id="source-project")
    source.customer.agency = "Other Agency"
    source.project_status = "completed"
    save_project(source, paths)
    target = _saved_project(paths)
    token = decorate_photo_items(source.project_id, [{
        "file_name": "finished.jpg",
        "source_kind": "shop_completed",
        "source_drive_id": "shop-drive",
        "source_item_id": "finished-item",
        "source_path": "Shop Project Database/Other Agency/2024/Completed Build Photos/finished.jpg",
        "source_web_url": "https://tenant.sharepoint.com/finished.jpg",
        "local_path": str(tmp_path / "private-cache.jpg"),
    }], paths)[0]["photo_token"]

    first = handle_import_gallery_references(target.project_id, {
        "source_project_id": source.project_id,
        "photo_tokens": [token],
    }, paths)
    second = handle_import_gallery_references(target.project_id, {
        "source_project_id": source.project_id,
        "photo_tokens": [token],
    }, paths)

    assert first["added"] == 1
    assert second["already_in_project"] == 1
    reference = handle_list_references(target.project_id, paths)["references"][0]
    assert reference["assignments"] == []
    assert reference["source_item_id"] == "finished-item"
    assert "local_path" not in reference


def test_gallery_photos_can_import_directly_to_optional_unit_group(tmp_path):
    from dtm_buildsheet.app.services.photo_gallery_service import decorate_photo_items

    paths = _paths(tmp_path)
    target = _saved_project(paths)
    token = decorate_photo_items("source-project", [{
        "file_name": "finished.jpg",
        "source_kind": "shop_completed",
        "source_path": "Shop/Completed Build Photos/finished.jpg",
    }], paths)[0]["photo_token"]

    result = handle_import_gallery_references(target.project_id, {
        "source_project_id": "source-project",
        "photo_tokens": [token],
        "target_unit_id": "group-1",
    }, paths)

    assert result["added"] == 1
    reference = handle_list_references(target.project_id, paths)["references"][0]
    assert reference["assignments"] == [{
        "scope": "unit_group", "target_id": "group-1", "note": "", "sort_order": 0,
    }]


def test_gallery_import_rejects_unknown_destination_unit_group(tmp_path):
    paths = _paths(tmp_path)
    target = _saved_project(paths)

    result = handle_import_gallery_references(target.project_id, {
        "source_project_id": "source-project",
        "photo_tokens": ["token"],
        "target_unit_id": "missing",
    }, paths)

    assert result["ok"] is False
    assert "no longer exists" in result["error"]


def test_remove_selected_gallery_references_only_removes_metadata(tmp_path):
    from dtm_buildsheet.app.services.photo_gallery_service import decorate_photo_items

    paths = _paths(tmp_path)
    target = _saved_project(paths)
    handle_save_reference(target.project_id, _reference(), paths)
    token = decorate_photo_items(target.project_id, [{
        "file_name": "console.jpg",
        "source_kind": "shop_completed",
        "source_drive_id": "shop-drive",
        "source_item_id": "item-1",
        "source_path": "Agency/2025/Completed Build Photos/console.jpg",
    }], paths)[0]["photo_token"]

    result = handle_remove_gallery_references(target.project_id, {
        "photo_tokens": [token],
    }, paths)

    assert result == {
        "ok": True, "removed": 1, "project_id": target.project_id, "target_unit_id": "",
    }
    assert handle_list_references(target.project_id, paths)["references"] == []


def test_remove_selected_group_reference_leaves_asset_unassigned(tmp_path):
    from dtm_buildsheet.app.services.photo_gallery_service import decorate_photo_items

    paths = _paths(tmp_path)
    target = _saved_project(paths)
    handle_save_reference(target.project_id, _reference(assignments=[{
        "scope": "unit_group", "target_id": "group-1", "note": "Copy this", "sort_order": 0,
    }]), paths)
    token = decorate_photo_items(target.project_id, [{
        "file_name": "console.jpg",
        "source_kind": "shop_completed",
        "source_drive_id": "shop-drive",
        "source_item_id": "item-1",
        "source_path": "Agency/2025/Completed Build Photos/console.jpg",
    }], paths)[0]["photo_token"]

    result = handle_remove_gallery_references(target.project_id, {
        "photo_tokens": [token], "target_unit_id": "group-1",
    }, paths)

    assert result["removed"] == 1
    reference = handle_list_references(target.project_id, paths)["references"][0]
    assert reference["assignments"] == []


def test_gallery_import_rejects_token_from_another_source_project(tmp_path):
    from dtm_buildsheet.app.services.photo_gallery_service import decorate_photo_items

    paths = _paths(tmp_path)
    target = _saved_project(paths)
    token = decorate_photo_items("different-source", [{
        "file_name": "finished.jpg",
        "source_kind": "shop_completed",
        "source_path": "Shop/Completed Build Photos/finished.jpg",
    }], paths)[0]["photo_token"]

    result = handle_import_gallery_references(target.project_id, {
        "source_project_id": "claimed-source",
        "photo_tokens": [token],
    }, paths)

    assert result["ok"] is False
    assert "expired" in result["error"]
