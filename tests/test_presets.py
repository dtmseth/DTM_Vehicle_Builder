"""Tests for the preset service (Phase 2)."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from dtm_buildsheet.app.services.preset_service import (
    find_duplicate,
    list_presets,
    load_preset,
    load_preset_dict,
    save_preset,
    validate_preset_payload,
)
from dtm_buildsheet.domain.input_models import PartInput
from dtm_buildsheet.paths import AppPaths, BUNDLED_PRESETS_DIR


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_paths(tmp_path: Path, bundled_dir: Path | None = None) -> AppPaths:
    ws_presets = tmp_path / "workspace_presets"
    ws_presets.mkdir(parents=True, exist_ok=True)
    return AppPaths(
        workspace_presets_dir=ws_presets,
        bundled_presets_dir=bundled_dir or BUNDLED_PRESETS_DIR,
    )


def _write_preset(directory: Path, preset: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{preset['preset_id']}.json").write_text(
        json.dumps(preset), encoding="utf-8"
    )


_MINIMAL_PRESET = {
    "schema_version": 1,
    "preset_id": "test-preset",
    "label": "Test Preset",
    "description": "A test preset",
    "vehicle_types": ["Sedan"],
    "parts": [],
}


# ── validate_preset_payload ────────────────────────────────────────────────────

class TestValidatePresetPayload:
    def test_valid_minimal_accepted(self):
        result = validate_preset_payload(_MINIMAL_PRESET)
        assert result["preset_id"] == "test-preset"
        assert result["label"] == "Test Preset"
        assert result["parts"] == []

    def test_non_dict_rejected(self):
        with pytest.raises(ValueError):
            validate_preset_payload([])  # type: ignore

    def test_empty_preset_id_rejected(self):
        bad = {**_MINIMAL_PRESET, "preset_id": ""}
        with pytest.raises(ValueError, match="empty"):
            validate_preset_payload(bad)

    def test_slash_in_preset_id_rejected(self):
        bad = {**_MINIMAL_PRESET, "preset_id": "a/b"}
        with pytest.raises(ValueError, match="path separator"):
            validate_preset_payload(bad)

    def test_traversal_preset_id_rejected(self):
        bad = {**_MINIMAL_PRESET, "preset_id": ".."}
        with pytest.raises(ValueError, match="reserved"):
            validate_preset_payload(bad)

    def test_empty_label_rejected(self):
        bad = {**_MINIMAL_PRESET, "label": "  "}
        with pytest.raises(ValueError, match="label"):
            validate_preset_payload(bad)

    def test_parts_not_list_rejected(self):
        bad = {**_MINIMAL_PRESET, "parts": "not a list"}
        with pytest.raises(ValueError, match="list"):
            validate_preset_payload(bad)

    def test_part_without_name_rejected(self):
        bad = {**_MINIMAL_PRESET, "parts": [{"quantity": 1}]}
        with pytest.raises(ValueError, match="name"):
            validate_preset_payload(bad)

    def test_part_defaults_filled_in(self):
        preset = {**_MINIMAL_PRESET, "parts": [{"name": "Roof Light Bar"}]}
        result = validate_preset_payload(preset)
        part = result["parts"][0]
        assert part["name"] == "Roof Light Bar"
        assert part["include"] is True
        assert part["quantity"] == 0
        assert part["raw_color"] == ""

    def test_schema_version_normalised(self):
        result = validate_preset_payload(_MINIMAL_PRESET)
        assert result["schema_version"] == 1

    def test_vehicle_types_preserved(self):
        result = validate_preset_payload(_MINIMAL_PRESET)
        assert result["vehicle_types"] == ["Sedan"]


# ── list_presets ───────────────────────────────────────────────────────────────

class TestListPresets:
    def test_bundled_blank_custom_present(self, tmp_path):
        """The real bundled presets directory contains blank_custom."""
        paths = _make_paths(tmp_path)
        presets = list_presets(paths)
        ids = [p["preset_id"] for p in presets]
        assert "blank_custom" in ids

    def test_bundled_patrol_piu_standard_present(self, tmp_path):
        paths = _make_paths(tmp_path)
        presets = list_presets(paths)
        ids = [p["preset_id"] for p in presets]
        assert "patrol_piu_standard" in ids

    def test_response_shape(self, tmp_path):
        paths = _make_paths(tmp_path)
        presets = list_presets(paths)
        for p in presets:
            assert "preset_id" in p
            assert "label" in p
            assert "description" in p
            assert "vehicle_types" in p
            assert "source" in p

    def test_workspace_overrides_bundled(self, tmp_path):
        bundled_dir = tmp_path / "bundled"
        _write_preset(bundled_dir, {**_MINIMAL_PRESET, "label": "Bundled Version"})
        workspace_dir = tmp_path / "workspace_presets"
        _write_preset(workspace_dir, {**_MINIMAL_PRESET, "label": "Workspace Override"})

        paths = AppPaths(
            bundled_presets_dir=bundled_dir,
            workspace_presets_dir=workspace_dir,
        )
        presets = list_presets(paths)
        assert len(presets) == 1
        assert presets[0]["label"] == "Workspace Override"
        assert presets[0]["source"] == "workspace"

    def test_workspace_source_label(self, tmp_path):
        bundled_dir = tmp_path / "bundled"
        workspace_dir = tmp_path / "workspace_presets"
        _write_preset(workspace_dir, _MINIMAL_PRESET)

        paths = AppPaths(
            bundled_presets_dir=bundled_dir,
            workspace_presets_dir=workspace_dir,
        )
        presets = list_presets(paths)
        assert presets[0]["source"] == "workspace"

    def test_bundled_source_label(self, tmp_path):
        bundled_dir = tmp_path / "bundled"
        workspace_dir = tmp_path / "workspace_presets"
        workspace_dir.mkdir()
        _write_preset(bundled_dir, _MINIMAL_PRESET)

        paths = AppPaths(
            bundled_presets_dir=bundled_dir,
            workspace_presets_dir=workspace_dir,
        )
        presets = list_presets(paths)
        assert presets[0]["source"] == "bundled"

    def test_corrupt_preset_skipped(self, tmp_path):
        bundled_dir = tmp_path / "bundled"
        bundled_dir.mkdir()
        (bundled_dir / "bad.json").write_text("not json{{{", encoding="utf-8")
        workspace_dir = tmp_path / "workspace_presets"
        workspace_dir.mkdir()

        paths = AppPaths(bundled_presets_dir=bundled_dir, workspace_presets_dir=workspace_dir)
        presets = list_presets(paths)
        assert presets == []

    def test_sorted_by_label(self, tmp_path):
        bundled_dir = tmp_path / "bundled"
        for pid, lbl in [("z_preset", "Zebra"), ("a_preset", "Apple")]:
            _write_preset(bundled_dir, {**_MINIMAL_PRESET, "preset_id": pid, "label": lbl})
        workspace_dir = tmp_path / "workspace_presets"
        workspace_dir.mkdir()

        paths = AppPaths(bundled_presets_dir=bundled_dir, workspace_presets_dir=workspace_dir)
        presets = list_presets(paths)
        labels = [p["label"] for p in presets]
        assert labels == sorted(labels, key=str.lower)

    def test_missing_directories_return_empty(self, tmp_path):
        paths = AppPaths(
            bundled_presets_dir=tmp_path / "no_bundled",
            workspace_presets_dir=tmp_path / "no_workspace",
        )
        assert list_presets(paths) == []


# ── load_preset ────────────────────────────────────────────────────────────────

class TestLoadPreset:
    def test_loads_blank_custom(self, tmp_path):
        paths = _make_paths(tmp_path)
        parts = load_preset("blank_custom", paths)
        assert parts == []

    def test_loads_patrol_piu_standard(self, tmp_path):
        paths = _make_paths(tmp_path)
        parts = load_preset("patrol_piu_standard", paths)
        assert len(parts) > 0
        assert all(isinstance(p, PartInput) for p in parts)

    def test_part_names_are_strings(self, tmp_path):
        paths = _make_paths(tmp_path)
        parts = load_preset("patrol_piu_standard", paths)
        assert all(isinstance(p.name, str) and p.name for p in parts)

    def test_parts_are_partinput_instances(self, tmp_path):
        bundled_dir = tmp_path / "bundled"
        preset = {
            **_MINIMAL_PRESET,
            "parts": [{
                "name": "Roof Light Bar",
                "include": True,
                "quantity": 2,
                "raw_color": "Red/Blue",
                "location": "Roof",
                "new_or_used": "New",
                "source": "",
                "manufacturer": "Whelen",
                "part_number": "LFL",
                "lens": "",
                "notes": "",
                "explicit_color_profile": "",
                "driver_color": "",
                "passenger_color": "",
                "center_color": "",
            }],
        }
        _write_preset(bundled_dir, preset)
        paths = AppPaths(
            bundled_presets_dir=bundled_dir,
            workspace_presets_dir=tmp_path / "workspace_presets",
        )
        parts = load_preset("test-preset", paths)
        assert len(parts) == 1
        p = parts[0]
        assert isinstance(p, PartInput)
        assert p.name == "Roof Light Bar"
        assert p.quantity == 2
        assert p.raw_color == "Red/Blue"
        assert p.manufacturer == "Whelen"

    def test_workspace_overrides_bundled_on_load(self, tmp_path):
        bundled_dir = tmp_path / "bundled"
        workspace_dir = tmp_path / "workspace_presets"
        _write_preset(bundled_dir, {**_MINIMAL_PRESET, "parts": [{"name": "Bundled Part"}]})
        _write_preset(workspace_dir, {**_MINIMAL_PRESET, "parts": [{"name": "Workspace Part"}]})

        paths = AppPaths(bundled_presets_dir=bundled_dir, workspace_presets_dir=workspace_dir)
        parts = load_preset("test-preset", paths)
        assert parts[0].name == "Workspace Part"

    def test_missing_preset_raises_file_not_found(self, tmp_path):
        paths = AppPaths(
            bundled_presets_dir=tmp_path / "no_bundled",
            workspace_presets_dir=tmp_path / "no_workspace",
        )
        with pytest.raises(FileNotFoundError, match="not found"):
            load_preset("nonexistent", paths)

    def test_unsafe_id_rejected(self, tmp_path):
        paths = _make_paths(tmp_path)
        with pytest.raises(ValueError):
            load_preset("../escape", paths)

    def test_slash_id_rejected(self, tmp_path):
        paths = _make_paths(tmp_path)
        with pytest.raises(ValueError):
            load_preset("foo/bar", paths)

    def test_empty_id_rejected(self, tmp_path):
        paths = _make_paths(tmp_path)
        with pytest.raises(ValueError):
            load_preset("", paths)

    def test_malformed_preset_raises_value_error(self, tmp_path):
        bundled_dir = tmp_path / "bundled"
        bundled_dir.mkdir()
        (bundled_dir / "bad_preset.json").write_text(
            json.dumps({"preset_id": "bad_preset", "label": "", "parts": []}),
            encoding="utf-8",
        )
        paths = AppPaths(
            bundled_presets_dir=bundled_dir,
            workspace_presets_dir=tmp_path / "workspace_presets",
        )
        with pytest.raises(ValueError):
            load_preset("bad_preset", paths)


# ── validate_preset_payload — placement_overrides ─────────────────────────────

class TestValidatePlacementOverrides:
    def test_missing_defaults_to_empty_dict(self):
        result = validate_preset_payload(_MINIMAL_PRESET)
        assert result["placement_overrides"] == {}

    def test_valid_dict_preserved(self):
        preset = {**_MINIMAL_PRESET, "placement_overrides": {"some_key": {"dx": 0.1}}}
        result = validate_preset_payload(preset)
        assert result["placement_overrides"] == {"some_key": {"dx": 0.1}}

    def test_non_dict_becomes_empty(self):
        preset = {**_MINIMAL_PRESET, "placement_overrides": "bad"}
        result = validate_preset_payload(preset)
        assert result["placement_overrides"] == {}


# ── auto naming + tag rules ────────────────────────────────────────────────────

class TestAutoNaming:
    def _paths(self, tmp_path: Path) -> AppPaths:
        ws = tmp_path / "ws"
        bd = tmp_path / "bd"
        ws.mkdir(); bd.mkdir()
        return AppPaths(workspace_presets_dir=ws, bundled_presets_dir=bd)

    def test_general_with_no_agency(self, tmp_path):
        paths = self._paths(tmp_path)
        res = save_preset(
            {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"],
             "tag": "", "parts": []},
            paths,
        )
        assert res["ok"]
        assert res["label"].startswith("General")

    def test_general_with_tag(self, tmp_path):
        paths = self._paths(tmp_path)
        res = save_preset(
            {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"],
             "tag": "Canine", "parts": []},
            paths,
        )
        assert res["ok"]
        assert "Canine" in res["label"]

    def test_tag_not_shown_for_agency_presets(self, tmp_path):
        """Tag must not appear in agency preset labels — tag is General-only."""
        ws = tmp_path / "ws"; bd = tmp_path / "bd"
        ws.mkdir(); bd.mkdir()
        # Write a fake agency so the auto-namer can resolve the name
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        agencies_file = ws_dir / "agencies.json"
        agencies_file.write_text(
            '{"schema_version":1,"agencies":[{"agency_id":"ag1","name":"Metro PD","address":"","city":"","state":"","zip":"","phone":"","email":"","notes":""}]}',
            encoding="utf-8",
        )
        paths = AppPaths(
            workspace_presets_dir=ws,
            bundled_presets_dir=bd,
            workspace_dir=ws_dir,
        )
        res = save_preset(
            {"agency_ids": ["ag1"], "build_types": ["Patrol"], "vehicle_types": ["PIU"],
             "tag": "ShouldBeIgnored", "parts": []},
            paths,
        )
        assert res["ok"]
        assert "ShouldBeIgnored" not in res["label"]

    def test_single_build_type_included(self, tmp_path):
        paths = self._paths(tmp_path)
        res = save_preset(
            {"agency_ids": [], "build_types": ["Admin"], "vehicle_types": [],
             "tag": "", "parts": []},
            paths,
        )
        assert res["ok"]
        assert "Admin" in res["label"]

    def test_multiple_build_types_not_in_label(self, tmp_path):
        """Multiple build types produce no build-type token in the label."""
        paths = self._paths(tmp_path)
        res = save_preset(
            {"agency_ids": [], "build_types": ["Patrol", "Admin"],
             "vehicle_types": ["PIU"], "tag": "Multi", "parts": []},
            paths,
        )
        assert res["ok"]
        assert "Patrol" not in res["label"]
        assert "Admin"  not in res["label"]


# ── find_duplicate ─────────────────────────────────────────────────────────────

def _paths_empty(tmp_path: Path) -> AppPaths:
    ws = tmp_path / "ws"; bd = tmp_path / "bd"
    ws.mkdir(); bd.mkdir()
    return AppPaths(workspace_presets_dir=ws, bundled_presets_dir=bd)


def _write_ws_preset(paths: AppPaths, preset: dict) -> None:
    paths.workspace_presets_dir.mkdir(parents=True, exist_ok=True)
    pid = preset["preset_id"]
    (paths.workspace_presets_dir / f"{pid}.json").write_text(
        json.dumps(preset), encoding="utf-8"
    )


_COMBO = {
    "preset_id": "existing_preset",
    "label": "Existing",
    "agency_ids": [],
    "build_types": ["Patrol"],
    "vehicle_types": ["PIU"],
    "tag": "",
    "parts": [],
}


class TestFindDuplicate:
    def test_finds_matching_workspace_preset(self, tmp_path):
        paths = _paths_empty(tmp_path)
        _write_ws_preset(paths, _COMBO)
        payload = {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"], "tag": ""}
        dup = find_duplicate(payload, paths)
        assert dup is not None
        assert dup["preset_id"] == "existing_preset"

    def test_no_match_returns_none(self, tmp_path):
        paths = _paths_empty(tmp_path)
        _write_ws_preset(paths, _COMBO)
        payload = {"agency_ids": [], "build_types": ["Admin"], "vehicle_types": ["PIU"], "tag": ""}
        assert find_duplicate(payload, paths) is None

    def test_excludes_by_id(self, tmp_path):
        paths = _paths_empty(tmp_path)
        _write_ws_preset(paths, _COMBO)
        payload = {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"], "tag": ""}
        assert find_duplicate(payload, paths, exclude_id="existing_preset") is None

    def test_order_of_lists_does_not_matter(self, tmp_path):
        paths = _paths_empty(tmp_path)
        multi = {**_COMBO, "preset_id": "multi", "label": "Multi",
                 "agency_ids": ["a1", "a2"], "build_types": ["Patrol", "Admin"], "vehicle_types": ["PIU", "SUV"]}
        _write_ws_preset(paths, multi)
        payload = {"agency_ids": ["a2", "a1"], "build_types": ["Admin", "Patrol"], "vehicle_types": ["SUV", "PIU"], "tag": ""}
        assert find_duplicate(payload, paths) is not None

    def test_tag_matters(self, tmp_path):
        paths = _paths_empty(tmp_path)
        tagged = {**_COMBO, "preset_id": "tagged", "label": "Tagged", "tag": "K9"}
        _write_ws_preset(paths, tagged)
        no_tag  = {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"], "tag": ""}
        with_tag = {**no_tag, "tag": "K9"}
        assert find_duplicate(no_tag, paths) is None
        assert find_duplicate(with_tag, paths) is not None

    def test_bundled_preset_ignored(self, tmp_path):
        bd = tmp_path / "bd"; ws = tmp_path / "ws"
        bd.mkdir(); ws.mkdir()
        _write_preset(bd, _COMBO)  # write to bundled, not workspace
        paths = AppPaths(bundled_presets_dir=bd, workspace_presets_dir=ws)
        payload = {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"], "tag": ""}
        assert find_duplicate(payload, paths) is None  # bundled not considered


# ── save_preset — duplicate enforcement ───────────────────────────────────────

class TestSavePresetDuplicates:
    def test_new_preset_saved_ok(self, tmp_path):
        paths = _paths_empty(tmp_path)
        res = save_preset(
            {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"],
             "tag": "", "parts": []},
            paths,
        )
        assert res["ok"] is True
        assert res["preset_id"]

    def test_duplicate_returns_conflict(self, tmp_path):
        paths = _paths_empty(tmp_path)
        _write_ws_preset(paths, _COMBO)
        res = save_preset(
            {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"],
             "tag": "", "parts": []},
            paths,
        )
        assert res["ok"] is False
        assert res.get("conflict") is True
        assert res["duplicate_preset_id"] == "existing_preset"

    def test_overwrite_replaces_existing(self, tmp_path):
        paths = _paths_empty(tmp_path)
        _write_ws_preset(paths, _COMBO)
        res = save_preset(
            {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"],
             "tag": "", "parts": [{"name": "New Part"}]},
            paths,
            overwrite=True,
        )
        assert res["ok"] is True
        assert res["preset_id"] == "existing_preset"
        parts = load_preset("existing_preset", paths)
        assert parts[0].name == "New Part"

    def test_targeting_existing_id_not_conflict(self, tmp_path):
        """If the payload already carries the duplicate's preset_id, no conflict."""
        paths = _paths_empty(tmp_path)
        _write_ws_preset(paths, _COMBO)
        res = save_preset(
            {"preset_id": "existing_preset",
             "agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["PIU"],
             "tag": "", "parts": []},
            paths,
        )
        assert res["ok"] is True

    def test_placement_overrides_saved_and_loaded(self, tmp_path):
        paths = _paths_empty(tmp_path)
        res = save_preset(
            {"agency_ids": [], "build_types": ["Patrol"], "vehicle_types": ["Sedan"],
             "tag": "", "parts": [],
             "placement_overrides": {"key1": {"dx": 0.05, "dy": -0.1}}},
            paths,
        )
        assert res["ok"]
        full = load_preset_dict(res["preset_id"], paths)
        assert full["placement_overrides"] == {"key1": {"dx": 0.05, "dy": -0.1}}


# ── load_preset_dict ──────────────────────────────────────────────────────────

class TestLoadPresetDict:
    def test_returns_full_dict_with_placement_overrides(self, tmp_path):
        paths = _paths_empty(tmp_path)
        res = save_preset(
            {"agency_ids": [], "build_types": [], "vehicle_types": [],
             "tag": "Test", "parts": [],
             "placement_overrides": {"x": 1}},
            paths,
        )
        assert res["ok"]
        full = load_preset_dict(res["preset_id"], paths)
        assert "placement_overrides" in full
        assert full["placement_overrides"] == {"x": 1}

    def test_missing_raises_file_not_found(self, tmp_path):
        paths = _paths_empty(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_preset_dict("nonexistent", paths)


# ── bundled preset sanity ──────────────────────────────────────────────────────

class TestBundledPresetSanity:
    """Every bundled preset that is not blank_custom must have at least one part.

    This regression test prevents silently shipping presets with empty parts
    arrays that would produce empty build editors when users set up a project.
    """

    def test_non_blank_bundled_presets_have_parts(self, tmp_path):
        paths = _make_paths(tmp_path)
        presets = list_presets(paths)
        empty_non_blank = []
        for p in presets:
            if p["preset_id"] == "blank_custom":
                continue
            parts = load_preset(p["preset_id"], paths)
            if len(parts) == 0:
                empty_non_blank.append(p["preset_id"])
        assert empty_non_blank == [], (
            f"Bundled presets with no parts (should have parts or be blank_custom): "
            f"{empty_non_blank}"
        )

    def test_blank_custom_is_intentionally_empty(self, tmp_path):
        paths = _make_paths(tmp_path)
        parts = load_preset("blank_custom", paths)
        assert parts == []
