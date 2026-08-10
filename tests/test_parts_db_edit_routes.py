"""Granular Part Manager edit endpoints: /api/parts-db/edit/* (schema v2)."""
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
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, *_):
        pass

    def end_headers(self):
        pass

    def body(self) -> dict:
        return json.loads(self.wfile.getvalue().decode("utf-8"))


_DB = {
    "schema_version": 2,
    "types": {"lights": {"label": "Lights"}},
    "sections": {"exterior": {"label": "Exterior"}},
    "zones": {"front": {"label": "Front", "section": "exterior"}},
    "sub_zones": {}, "build_attributes": {},
    "tags": {"camera": {"label": "Camera"}},
    "manufacturers": {"whelen": {"label": "Whelen"}, "setina": {"label": "Setina"}},
    "products": {
        "whelen_ion": {
            "manufacturer_id": "whelen", "model": "ION",
            "fits_part_types": ["forward_warning"], "tag_ids": [],
            "part_numbers": [
                {"part_number": "IOND", "color": "red"},
                {"part_number": "IONLINK", "qb_item_id": "847", "qb_unit_price": 199.0},
            ],
        },
        "setina_pb400": {
            "manufacturer_id": "setina", "model": "PB400",
            "fits_part_types": [], "part_numbers": [],
        },
    },
    "part_types": {
        "forward_warning": {
            "label": "Forward Warning", "type_id": "lights",
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "workbook_label_pattern": "Forward Warning {n}",
        },
    },
    "placements": {}, "placement_zones": {}, "services": {},
    "preference_filters": {}, "color_palette": {},
    "accessory_categories": {"bracket_mount": {"label": "Bracket / Mount"}},
}


def _paths(tmp_path: Path) -> AppPaths:
    (tmp_path / "parts_db.json").write_text(json.dumps(_DB), "utf-8")
    return AppPaths(workspace_config_dir=tmp_path)


def _post(paths, sub, body):
    h = FakeHandler(f"/api/parts-db/edit/{sub}")
    route_parts_db(h, "POST", f"/api/parts-db/edit/{sub}", body, paths)
    return h


def _doc(paths) -> dict:
    h = FakeHandler("/api/parts-db")
    route_parts_db(h, "GET", "/api/parts-db", {}, paths)
    return h.body()


class TestProductEdits:
    def test_product_update(self, tmp_path):
        p = _paths(tmp_path)
        h = _post(p, "product-update", {"product_id": "whelen_ion", "fields": {"model": "ION T-Series", "description": "warning"}})
        assert h.body()["ok"]
        prod = _doc(p)["products"]["whelen_ion"]
        assert prod["model"] == "ION T-Series" and prod["description"] == "warning"

    def test_product_create_and_delete(self, tmp_path):
        p = _paths(tmp_path)
        h = _post(p, "product-create", {"model": "Vertex", "manufacturer_id": "whelen"})
        pid = h.body()["product_id"]
        assert pid in _doc(p)["products"]
        assert _post(p, "product-delete", {"product_id": pid}).body()["ok"]
        assert pid not in _doc(p)["products"]

    def test_product_create_requires_model(self, tmp_path):
        p = _paths(tmp_path)
        h = _post(p, "product-create", {"manufacturer_id": "whelen"})
        assert h.status == 400 and not h.body()["ok"]


class TestSkuEdits:
    def test_sku_update_persists(self, tmp_path):
        p = _paths(tmp_path)
        _post(p, "sku-update", {"product_id": "whelen_ion", "index": 0,
                                "fields": {"friendly_name": "ION Red/White", "lens_type": "smoked", "price_usd": 95.5}})
        pn = _doc(p)["products"]["whelen_ion"]["part_numbers"][0]
        assert pn["friendly_name"] == "ION Red/White" and pn["lens_type"] == "smoked" and pn["price_usd"] == 95.5

    def test_linked_sku_price_is_protected(self, tmp_path):
        p = _paths(tmp_path)
        _post(p, "sku-update", {"product_id": "whelen_ion", "index": 1, "fields": {"price_usd": 1.0}})
        pn = _doc(p)["products"]["whelen_ion"]["part_numbers"][1]
        assert "price_usd" not in pn and pn["qb_unit_price"] == 199.0   # QB owns the price

    def test_sku_add_and_delete(self, tmp_path):
        p = _paths(tmp_path)
        h = _post(p, "sku-add", {"product_id": "setina_pb400", "sku": {"part_number": "PB400-NEW"}})
        idx = h.body()["index"]
        assert _doc(p)["products"]["setina_pb400"]["part_numbers"][idx]["part_number"] == "PB400-NEW"
        _post(p, "sku-delete", {"product_id": "setina_pb400", "index": idx, "expect_part_number": "PB400-NEW"})
        assert _doc(p)["products"]["setina_pb400"]["part_numbers"] == []

    def test_sku_move(self, tmp_path):
        p = _paths(tmp_path)
        _post(p, "sku-move", {"from_product_id": "whelen_ion", "to_product_id": "setina_pb400",
                              "index": 0, "expect_part_number": "IOND"})
        doc = _doc(p)
        src = [x["part_number"] for x in doc["products"]["whelen_ion"]["part_numbers"]]
        dst = [x["part_number"] for x in doc["products"]["setina_pb400"]["part_numbers"]]
        assert "IOND" not in src and "IOND" in dst

    def test_sku_bulk_set_and_delete(self, tmp_path):
        p = _paths(tmp_path)
        targets = [{"product_id": "whelen_ion", "index": 0}, {"product_id": "whelen_ion", "index": 1}]
        _post(p, "sku-bulk", {"targets": targets, "op": "set", "fields": {"lens_type": "clear"}})
        pns = _doc(p)["products"]["whelen_ion"]["part_numbers"]
        assert pns[0]["lens_type"] == "clear"   # linked SKU's lens is editable (not a QB-owned field)
        _post(p, "sku-bulk", {"targets": [{"product_id": "whelen_ion", "index": 0}], "op": "delete"})
        assert all(x["part_number"] != "IOND" for x in _doc(p)["products"]["whelen_ion"]["part_numbers"])


class TestEntityCreate:
    def test_manufacturer_create(self, tmp_path):
        p = _paths(tmp_path)
        mid = _post(p, "manufacturer-create", {"label": "SoundOff Signal", "website": "https://x"}).body()["manufacturer_id"]
        assert _doc(p)["manufacturers"][mid]["label"] == "SoundOff Signal"

    def test_tag_create(self, tmp_path):
        p = _paths(tmp_path)
        tid = _post(p, "tag-create", {"label": "siren"}).body()["tag_id"]
        assert _doc(p)["tags"][tid]["label"] == "siren"

    def test_part_type_create(self, tmp_path):
        p = _paths(tmp_path)
        ptid = _post(p, "part-type-create", {"label": "Side Warning", "type_id": "lights", "category": "warning"}).body()["part_type_id"]
        pt = _doc(p)["part_types"][ptid]
        assert pt["label"] == "Side Warning" and pt["type_id"] == "lights" and pt["category"] == "warning"

    def test_part_type_create_requires_type(self, tmp_path):
        p = _paths(tmp_path)
        assert _post(p, "part-type-create", {"label": "x"}).status == 400

    def test_part_type_location_fields_persist(self, tmp_path):
        p = _paths(tmp_path)
        h = _post(p, "part-type-update", {"part_type_id": "forward_warning", "fields": {
            "location_mode": "text",
            "location_options": ["  IN CONSOLE ", "on dash", "in console", ""],  # trim + de-dupe + drop blank
        }})
        assert h.body()["ok"]
        pt = _doc(p)["part_types"]["forward_warning"]
        assert pt["location_mode"] == "text"
        assert pt["location_options"] == ["IN CONSOLE", "on dash"]

    def test_part_type_bad_location_mode_rejected(self, tmp_path):
        p = _paths(tmp_path)
        h = _post(p, "part-type-update", {"part_type_id": "forward_warning",
                                          "fields": {"location_mode": "bogus"}})
        assert h.status == 400 and not h.body()["ok"]


class TestReviewAndBackfill:
    def test_reviewed_flag(self, tmp_path):
        p = _paths(tmp_path)
        assert _post(p, "product-update", {"product_id": "whelen_ion", "fields": {"reviewed": True}}).body()["ok"]
        assert _doc(p)["products"]["whelen_ion"]["reviewed"] is True

    def test_backfill_descriptions_fills_empty_linked(self, tmp_path):
        (tmp_path / "parts_db.json").write_text(json.dumps(_DB), "utf-8")
        (tmp_path / "quickbooks_items_cache.json").write_text(json.dumps({
            "item_count": 1,
            "items": [{"qb_item_id": "847", "name": "IONLINK", "sku": "",
                       "description": "ION RED/WHITE", "unit_price": 199.0, "type": "Inventory"}],
        }), "utf-8")
        p = AppPaths(workspace_config_dir=tmp_path, workspace_dir=tmp_path)
        res = _post(p, "backfill-descriptions", {}).body()
        assert res["ok"] and res["count"] == 1
        pns = _doc(p)["products"]["whelen_ion"]["part_numbers"]
        assert pns[1]["friendly_name"] == "ION RED/WHITE"        # linked + was empty → filled
        assert not pns[0].get("friendly_name")                   # unlinked (no qb_item_id) → untouched


class TestLightSeedAndAccessory:
    def test_seed_light_tags(self, tmp_path):
        p = _paths(tmp_path)
        res = _post(p, "seed-light-tags", {}).body()
        assert res["ok"] and res["count"] >= 1
        doc = _doc(p)
        lid = res["light_tag_id"]
        assert lid in doc["tags"]
        assert lid in doc["products"]["whelen_ion"]["tag_ids"]            # has a colored SKU (IOND/red)
        assert lid not in (doc["products"]["setina_pb400"].get("tag_ids") or [])   # no color, not a light category

    def test_accessory_child_side_resolves_on_parent(self, tmp_path):
        p = _paths(tmp_path)
        _post(p, "product-update", {"product_id": "setina_pb400",
              "fields": {"accessory_category": "bracket_mount", "accessory_of_products": ["whelen_ion"]}})
        h = FakeHandler("/api/parts-db/accessories?product_id=whelen_ion")
        route_parts_db(h, "GET", "/api/parts-db/accessories", {}, p)
        opt_ids = {o["product_id"] for g in h.body()["accessories"] for o in g["options"]}
        assert "setina_pb400" in opt_ids


def test_unknown_action_400(tmp_path):
    assert _post(_paths(tmp_path), "bogus", {}).status == 400
