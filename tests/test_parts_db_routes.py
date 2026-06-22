"""Phase 3 (schema v2): HTTP route coverage for /api/parts-db/*."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.routes.parts_db import route_parts_db
from dtm_buildsheet.app.services import parts_db_service
from dtm_buildsheet.paths import AppPaths


@pytest.fixture(autouse=True)
def _reset_singleton():
    parts_db_service.reset_for_testing()
    yield
    parts_db_service.reset_for_testing()


class FakeHandler:
    def __init__(self, path: str):
        self.path = path
        self.status: int | None = None
        self.headers_sent: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.headers_sent.append((key, value))

    def end_headers(self) -> None:
        pass

    def body_json(self) -> dict:
        return json.loads(self.wfile.getvalue().decode("utf-8"))


_SYNTHETIC_DB = {
    "schema_version": 2,
    "types": {"lights": {"label": "Lights"}, "structural": {"label": "Structural"}},
    "sections": {"exterior": {"label": "Exterior"}},
    "zones": {"front": {"label": "Front", "section": "exterior"}},
    "sub_zones": {},
    "build_attributes": {},
    "tags": {"camera": {"label": "Camera"}},
    "manufacturers": {"whelen": {"label": "Whelen"}, "setina": {"label": "Setina"}},
    "products": {
        "whelen_ion_t": {
            "manufacturer_id": "whelen", "model": "ION T",
            "fits_part_types": ["forward_warning"],
            "tag_ids": [],
            "part_numbers": [{"part_number": "ION-T-RW"}],
        },
        "setina_pb400": {
            "manufacturer_id": "setina", "model": "PB400",
            "fits_part_types": ["push_bumper"],
        },
        "whelen_cam": {
            "manufacturer_id": "whelen", "model": "Cam",
            "fits_part_types": ["front_camera"],
            "tag_ids": ["camera"],
        },
    },
    "part_types": {
        "forward_warning": {
            "label": "Forward Warning", "type_id": "lights",
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "workbook_label_pattern": "Forward Warning {n}",
        },
        "push_bumper": {
            "label": "Push Bumper", "type_id": "structural",
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "workbook_label_pattern": "Push Bumper",
        },
        "front_camera": {
            "label": "Front Camera", "type_id": "lights",   # using lights to keep fixture minimal
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "tag_ids": ["camera"],
            "workbook_label_pattern": "Front Camera",
        },
    },
    "placements": {"GRILL": {"placement_zone": "primary_front"}},
    "placement_zones": {"primary_front": {"label": "Primary Front"}},
    "services": {},
    "preference_filters": {},
    "color_palette": {},
}


def _paths(tmp_path: Path, db: dict | None = _SYNTHETIC_DB) -> AppPaths:
    if db is not None:
        (tmp_path / "parts_db.json").write_text(json.dumps(db), "utf-8")
    return AppPaths(workspace_config_dir=tmp_path)


# ── Top-level taxonomies ────────────────────────────────────────────────────


class TestTopLevelEndpoints:
    def test_full_doc(self, tmp_path):
        h = FakeHandler("/api/parts-db")
        route_parts_db(h, "GET", "/api/parts-db", {}, _paths(tmp_path))
        assert h.status == 200
        assert "whelen_ion_t" in h.body_json()["products"]

    def test_types(self, tmp_path):
        h = FakeHandler("/api/parts-db/types")
        route_parts_db(h, "GET", "/api/parts-db/types", {}, _paths(tmp_path))
        ids = {t["type_id"] for t in h.body_json()["types"]}
        assert ids == {"lights", "structural"}

    def test_sections(self, tmp_path):
        h = FakeHandler("/api/parts-db/sections")
        route_parts_db(h, "GET", "/api/parts-db/sections", {}, _paths(tmp_path))
        assert {s["section_id"] for s in h.body_json()["sections"]} == {"exterior"}

    def test_zones_unfiltered(self, tmp_path):
        h = FakeHandler("/api/parts-db/zones")
        route_parts_db(h, "GET", "/api/parts-db/zones", {}, _paths(tmp_path))
        assert {z["zone_id"] for z in h.body_json()["zones"]} == {"front"}

    def test_zones_filtered(self, tmp_path):
        h = FakeHandler("/api/parts-db/zones?section=exterior")
        route_parts_db(h, "GET", "/api/parts-db/zones", {}, _paths(tmp_path))
        assert len(h.body_json()["zones"]) == 1

    def test_tags(self, tmp_path):
        h = FakeHandler("/api/parts-db/tags")
        route_parts_db(h, "GET", "/api/parts-db/tags", {}, _paths(tmp_path))
        assert {t["tag_id"] for t in h.body_json()["tags"]} == {"camera"}

    def test_manufacturers(self, tmp_path):
        h = FakeHandler("/api/parts-db/manufacturers")
        route_parts_db(h, "GET", "/api/parts-db/manufacturers", {}, _paths(tmp_path))
        ids = {m["manufacturer_id"] for m in h.body_json()["manufacturers"]}
        assert ids == {"whelen", "setina"}


# ── Part types ──────────────────────────────────────────────────────────────


class TestPartTypeEndpoints:
    def test_all(self, tmp_path):
        h = FakeHandler("/api/parts-db/part-types")
        route_parts_db(h, "GET", "/api/parts-db/part-types", {}, _paths(tmp_path))
        ids = {pt["part_type_id"] for pt in h.body_json()["part_types"]}
        assert ids == {"forward_warning", "push_bumper", "front_camera"}

    def test_filter_by_type(self, tmp_path):
        h = FakeHandler("/api/parts-db/part-types?type=lights")
        route_parts_db(h, "GET", "/api/parts-db/part-types", {}, _paths(tmp_path))
        ids = {pt["part_type_id"] for pt in h.body_json()["part_types"]}
        # fixture has front_camera labelled type_id=lights too
        assert ids == {"forward_warning", "front_camera"}

    def test_filter_by_tag(self, tmp_path):
        h = FakeHandler("/api/parts-db/part-types?tag=camera")
        route_parts_db(h, "GET", "/api/parts-db/part-types", {}, _paths(tmp_path))
        ids = {pt["part_type_id"] for pt in h.body_json()["part_types"]}
        assert ids == {"front_camera"}

    def test_single(self, tmp_path):
        h = FakeHandler("/api/parts-db/part-types/forward_warning")
        route_parts_db(h, "GET", "/api/parts-db/part-types/forward_warning", {}, _paths(tmp_path))
        assert h.status == 200
        assert h.body_json()["label"] == "Forward Warning"

    def test_404_unknown(self, tmp_path):
        h = FakeHandler("/api/parts-db/part-types/nope")
        route_parts_db(h, "GET", "/api/parts-db/part-types/nope", {}, _paths(tmp_path))
        assert h.status == 404

    def test_products_for_part_type(self, tmp_path):
        h = FakeHandler("/api/parts-db/part-types/forward_warning/products")
        route_parts_db(h, "GET", "/api/parts-db/part-types/forward_warning/products", {}, _paths(tmp_path))
        ids = {p["product_id"] for p in h.body_json()["products"]}
        assert ids == {"whelen_ion_t"}


# ── Products ────────────────────────────────────────────────────────────────


class TestProductEndpoints:
    def test_all(self, tmp_path):
        h = FakeHandler("/api/parts-db/products")
        route_parts_db(h, "GET", "/api/parts-db/products", {}, _paths(tmp_path))
        assert len(h.body_json()["products"]) == 3

    def test_filter_by_tag(self, tmp_path):
        h = FakeHandler("/api/parts-db/products?tag=camera")
        route_parts_db(h, "GET", "/api/parts-db/products", {}, _paths(tmp_path))
        ids = {p["product_id"] for p in h.body_json()["products"]}
        assert ids == {"whelen_cam"}

    def test_single(self, tmp_path):
        h = FakeHandler("/api/parts-db/products/whelen_ion_t")
        route_parts_db(h, "GET", "/api/parts-db/products/whelen_ion_t", {}, _paths(tmp_path))
        assert h.status == 200
        assert h.body_json()["model"] == "ION T"

    def test_part_numbers(self, tmp_path):
        h = FakeHandler("/api/parts-db/products/whelen_ion_t/part-numbers")
        route_parts_db(h, "GET", "/api/parts-db/products/whelen_ion_t/part-numbers", {}, _paths(tmp_path))
        assert [pn["part_number"] for pn in h.body_json()["part_numbers"]] == ["ION-T-RW"]


# ── Validation endpoint ────────────────────────────────────────────────────


class TestValidatePlacement:
    def test_valid_triple(self, tmp_path):
        h = FakeHandler("/api/parts-db/validate-placement")
        body = {"part_type_id": "forward_warning",
                "product_id": "whelen_ion_t",
                "location_id": "GRILL"}
        route_parts_db(h, "POST", "/api/parts-db/validate-placement", body, _paths(tmp_path))
        assert h.body_json()["valid"] is True

    def test_invalid_product_for_part_type(self, tmp_path):
        h = FakeHandler("/api/parts-db/validate-placement")
        body = {"part_type_id": "forward_warning",
                "product_id": "setina_pb400",
                "location_id": "GRILL"}
        route_parts_db(h, "POST", "/api/parts-db/validate-placement", body, _paths(tmp_path))
        assert h.body_json()["valid"] is False


# ── Save ────────────────────────────────────────────────────────────────────


class TestSave:
    def test_save_succeeds(self, tmp_path):
        h = FakeHandler("/api/parts-db")
        paths = AppPaths(workspace_config_dir=tmp_path)
        route_parts_db(h, "POST", "/api/parts-db", dict(_SYNTHETIC_DB), paths)
        assert h.status == 200
        assert h.body_json()["ok"] is True


class _FakeAccSvc:
    """Minimal svc stub exposing raw_doc() for _resolve_accessories."""
    def __init__(self, doc): self._doc = doc
    def raw_doc(self): return self._doc


def test_resolve_accessories_product_and_part_type_level():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories
    doc = {
        "accessory_categories": {"lighthead": {"label": "Lighthead"},
                                  "bracket_mount": {"label": "Bracket / Mount"}},
        "manufacturers": {"whelen": {"label": "Whelen"}},
        "part_types": {
            "forward_warning": {"label": "Forward Warning", "type_id": "lights"},
            "fw_bracket": {"label": "FW Bracket", "type_id": "lights",
                           "accessory_of": "forward_warning",
                           "accessory_category": "bracket_mount"},
            "lighthead": {"label": "Lighthead", "type_id": "lights",
                          "accessory_category": "lighthead"},
        },
        "products": {
            "whelen_fst": {"manufacturer_id": "whelen", "model": "Inner Edge FST",
                           "fits_part_types": ["forward_warning"],
                           "accessories": [{"category": "lighthead",
                                            "product_id": "whelen_ie_lighthead",
                                            "required": True}]},
            "whelen_ie_lighthead": {"manufacturer_id": "whelen", "model": "IE Lighthead",
                                    "fits_part_types": ["lighthead"],
                                    "part_numbers": [{"part_number": "ISDD", "qb_item_id": "9",
                                                      "qb_unit_price": 63.0}]},
            "dtm_bracket": {"manufacturer_id": "whelen", "model": "L Bracket",
                            "fits_part_types": ["fw_bracket"],
                            "part_numbers": [{"part_number": "LBR", "qb_unit_price": 12.0}]},
        },
    }
    out = _resolve_accessories(_FakeAccSvc(doc), "whelen_fst")
    cats = {g["category"]: g for g in out}
    # product-level lighthead, required, with its SKU
    assert cats["lighthead"]["required"] is True
    assert cats["lighthead"]["options"][0]["product_id"] == "whelen_ie_lighthead"
    assert cats["lighthead"]["options"][0]["skus"][0]["part_number"] == "ISDD"
    # part_type-level bracket pulled in via accessory_of, not required
    assert cats["bracket_mount"]["required"] is False
    assert cats["bracket_mount"]["options"][0]["product_id"] == "dtm_bracket"
    # vocabulary order: lighthead before bracket_mount
    assert [g["category"] for g in out] == ["lighthead", "bracket_mount"]


def test_resolve_accessories_none_for_plain_product():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories
    doc = {"accessory_categories": {}, "manufacturers": {}, "part_types": {},
           "products": {"p": {"manufacturer_id": "m", "model": "P", "fits_part_types": []}}}
    assert _resolve_accessories(_FakeAccSvc(doc), "p") == []
