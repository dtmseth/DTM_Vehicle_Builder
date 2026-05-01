"""Phase 11 tests: config-driven view metadata and internal view support."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dtm_buildsheet.app.services.preview_service import _view_metadata, _FALLBACK_VIEW_ORDER
from dtm_buildsheet.config.schemas import validate_config_payload
from dtm_buildsheet.config_loader import load_configs
from dtm_buildsheet.paths import ensure_workspace


# ── view metadata helper ──────────────────────────────────────────────────────

def test_view_metadata_from_config():
    vehicle_config = {
        "view_order": ["front", "side", "internal.console"],
        "views": {
            "front":            {"label": "Front", "category": "external"},
            "side":             {"label": "Side",  "category": "external"},
            "internal.console": {"label": "Console", "category": "internal"},
        },
    }
    order, meta = _view_metadata(vehicle_config)
    assert order == ["front", "side", "internal.console"]
    assert meta["front"]["label"]    == "Front"
    assert meta["front"]["category"] == "external"
    assert meta["internal.console"]["label"]    == "Console"
    assert meta["internal.console"]["category"] == "internal"


def test_view_metadata_fallback_when_no_view_order():
    vehicle_config = {
        "views": {
            "front": {"label": "Front", "category": "external"},
        }
    }
    order, meta = _view_metadata(vehicle_config)
    assert order == _FALLBACK_VIEW_ORDER


def test_view_metadata_label_from_key_when_missing():
    vehicle_config = {
        "view_order": ["internal.cargo"],
        "views": {
            "internal.cargo": {"category": "internal"},
        },
    }
    _, meta = _view_metadata(vehicle_config)
    # dot replaced, title-cased
    assert meta["internal.cargo"]["label"] == "Internal Cargo"


def test_view_metadata_empty_vehicle_config():
    order, meta = _view_metadata({})
    assert order == _FALLBACK_VIEW_ORDER
    # fallback produces default entries for each view in the fallback order
    for v in _FALLBACK_VIEW_ORDER:
        assert v in meta
        assert meta[v]["category"] == "external"  # default when key absent from view_map


# ── vehicle_layouts.json schema validation ────────────────────────────────────

class TestVehicleLayoutsSchema:
    BASE = {
        "schema_version": 5,
        "vehicles": {
            "TEST": {
                "view_order": ["front", "internal.console"],
                "views": {
                    "front": {
                        "label":         "Front",
                        "category":      "external",
                        "legend_layout": "standard",
                        "logo_position": "top-right",
                        "coord_space":   "relative_image",
                        "locations":     {},
                    },
                    "internal.console": {
                        "label":         "Console",
                        "category":      "internal",
                        "legend_layout": "standard",
                        "logo_position": "top-right",
                        "coord_space":   "relative_image",
                        "locations":     {},
                    },
                },
            }
        },
    }

    def _validate(self, data: dict) -> dict:
        return validate_config_payload("vehicle_layouts.json", data)

    def test_valid_passes(self):
        result = self._validate(self.BASE)
        assert "vehicles" in result

    def test_invalid_category_raises(self):
        bad = json.loads(json.dumps(self.BASE))
        bad["vehicles"]["TEST"]["views"]["front"]["category"] = "bogus"
        with pytest.raises(ValueError, match="category"):
            self._validate(bad)

    def test_invalid_legend_layout_raises(self):
        bad = json.loads(json.dumps(self.BASE))
        bad["vehicles"]["TEST"]["views"]["front"]["legend_layout"] = "columns"
        with pytest.raises(ValueError, match="legend_layout"):
            self._validate(bad)

    def test_invalid_logo_position_raises(self):
        bad = json.loads(json.dumps(self.BASE))
        bad["vehicles"]["TEST"]["views"]["front"]["logo_position"] = "center"
        with pytest.raises(ValueError, match="logo_position"):
            self._validate(bad)

    def test_view_order_unknown_view_raises(self):
        bad = json.loads(json.dumps(self.BASE))
        bad["vehicles"]["TEST"]["view_order"].append("nonexistent")
        with pytest.raises(ValueError, match="view_order"):
            self._validate(bad)

    def test_view_order_non_list_raises(self):
        bad = json.loads(json.dumps(self.BASE))
        bad["vehicles"]["TEST"]["view_order"] = "front"
        with pytest.raises(ValueError, match="view_order"):
            self._validate(bad)

    def test_optional_fields_not_required(self):
        minimal = {
            "schema_version": 5,
            "vehicles": {
                "BARE": {
                    "views": {
                        "front": {
                            "coord_space": "relative_image",
                            "locations":   {},
                        }
                    }
                }
            },
        }
        result = self._validate(minimal)
        assert "vehicles" in result


# ── bundled vehicle_layouts.json has correct new fields ───────────────────────

class TestBundledVehicleLayouts:
    @pytest.fixture(autouse=True)
    def _load(self, config):
        self.layouts = config.vehicle_layouts

    def test_all_vehicles_have_view_order(self):
        for vtype, vehicle in self.layouts["vehicles"].items():
            assert "view_order" in vehicle, f"{vtype} missing view_order"

    def test_external_views_have_category(self):
        for vtype, vehicle in self.layouts["vehicles"].items():
            for vname in ["front", "side", "top", "rear"]:
                view = vehicle["views"].get(vname, {})
                assert view.get("category") == "external", (
                    f"{vtype}/{vname} should have category=external"
                )

    def test_external_views_have_label(self):
        for vtype, vehicle in self.layouts["vehicles"].items():
            for vname in ["front", "side", "top", "rear"]:
                view = vehicle["views"].get(vname, {})
                assert view.get("label"), f"{vtype}/{vname} missing label"

    def test_internal_view_stubs_present(self):
        for vtype, vehicle in self.layouts["vehicles"].items():
            for iv in ["internal.console", "internal.cargo", "internal.rear_seat"]:
                assert iv in vehicle["views"], f"{vtype} missing stub for {iv}"
                view = vehicle["views"][iv]
                assert view.get("category") == "internal"

    def test_side_top_have_grid_legend_layout(self):
        for vtype, vehicle in self.layouts["vehicles"].items():
            for vname in ["side", "top"]:
                view = vehicle["views"].get(vname, {})
                assert view.get("legend_layout") == "grid", (
                    f"{vtype}/{vname} should have legend_layout=grid"
                )

    def test_front_rear_have_standard_legend_layout(self):
        for vtype, vehicle in self.layouts["vehicles"].items():
            for vname in ["front", "rear"]:
                view = vehicle["views"].get(vname, {})
                assert view.get("legend_layout") == "standard", (
                    f"{vtype}/{vname} should have legend_layout=standard"
                )

    def test_side_top_have_logo_position_bottom(self):
        for vtype, vehicle in self.layouts["vehicles"].items():
            for vname in ["side", "top"]:
                view = vehicle["views"].get(vname, {})
                assert view.get("logo_position") == "bottom", (
                    f"{vtype}/{vname} should have logo_position=bottom"
                )

    def test_view_order_contains_all_external_views(self):
        external = {"front", "side", "top", "rear"}
        for vtype, vehicle in self.layouts["vehicles"].items():
            view_order = vehicle.get("view_order", [])
            assert external.issubset(set(view_order)), (
                f"{vtype} view_order missing some external views"
            )

    def test_view_order_contains_internal_stubs(self):
        internal = {"internal.console", "internal.cargo", "internal.rear_seat"}
        for vtype, vehicle in self.layouts["vehicles"].items():
            view_order = vehicle.get("view_order", [])
            assert internal.issubset(set(view_order)), (
                f"{vtype} view_order missing some internal views"
            )

    def test_external_views_precede_internal_in_order(self):
        """External views should all come before internal views in view_order."""
        for vtype, vehicle in self.layouts["vehicles"].items():
            view_order = vehicle.get("view_order", [])
            view_map = vehicle.get("views", {})
            categories = [view_map.get(v, {}).get("category", "external") for v in view_order]
            # Once we see "internal", we should not see "external" again
            seen_internal = False
            for cat in categories:
                if cat == "internal":
                    seen_internal = True
                elif seen_internal:
                    pytest.fail(f"{vtype}: external view after internal in view_order")


# ── render_ppt uses config-driven view list ───────────────────────────────────

def test_load_vehicle_view_config_returns_external_only(tmp_path):
    from dtm_buildsheet.render_ppt import _load_vehicle_view_config

    cfg = {
        "schema_version": 5,
        "vehicles": {
            "PIU": {
                "view_order": ["front", "side", "internal.console"],
                "views": {
                    "front":            {"category": "external", "locations": {}},
                    "side":             {"category": "external", "locations": {}},
                    "internal.console": {"category": "internal", "locations": {}},
                },
            }
        },
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "vehicle_layouts.json").write_text(json.dumps(cfg), encoding="utf-8")

    paths = SimpleNamespace(workspace_config_dir=config_dir)
    external, view_map = _load_vehicle_view_config("PIU", paths)

    assert external == ["front", "side"], "should only return external views"
    assert "internal.console" not in external
    assert "internal.console" in view_map


def test_load_vehicle_view_config_fallback_on_missing_file(tmp_path):
    from dtm_buildsheet.render_ppt import _load_vehicle_view_config, _LEGACY_VIEWS

    paths = SimpleNamespace(workspace_config_dir=tmp_path)  # no file
    external, view_map = _load_vehicle_view_config("PIU", paths)

    assert external == list(_LEGACY_VIEWS)
    assert view_map == {}


def test_load_vehicle_view_config_fallback_on_unknown_vehicle(tmp_path):
    from dtm_buildsheet.render_ppt import _load_vehicle_view_config, _LEGACY_VIEWS

    cfg = {"schema_version": 5, "vehicles": {}}
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "vehicle_layouts.json").write_text(json.dumps(cfg), encoding="utf-8")

    paths = SimpleNamespace(workspace_config_dir=config_dir)
    external, view_map = _load_vehicle_view_config("UNKNOWN", paths)

    assert external == list(_LEGACY_VIEWS)
