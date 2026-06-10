"""Phase 3 (revised): HTTP route coverage for /api/parts-db/*.

Seven endpoints — full doc, categories, manufacturers (with category filter),
products (with category/manufacturer filters), single product, part-numbers
of a product, products compatible with a zone, plus POST save.
"""
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
    """Just enough BaseHTTPRequestHandler surface for `send_json`."""
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
    "schema_version": 1,
    "categories": {
        "lights":       {"label": "Lights",       "applies_to_zones": ["primary_front"]},
        "push_bumpers": {"label": "Push Bumpers", "applies_to_zones": ["primary_front"]},
    },
    "manufacturers": {
        "whelen":   {"label": "Whelen"},
        "setina":   {"label": "Setina"},
        "soundoff": {"label": "SoundOff Signal"},
    },
    "products": {
        "whelen_ion_t": {
            "manufacturer_id": "whelen",
            "category_id": "lights",
            "model": "ION T-Series",
            "part_numbers": [{"part_number": "ION-T-RW"}],
        },
        "soundoff_mpower": {
            "manufacturer_id": "soundoff",
            "category_id": "lights",
            "model": "mPOWER",
        },
        "setina_pb400": {
            "manufacturer_id": "setina",
            "category_id": "push_bumpers",
            "model": "PB400",
        },
    },
    "location_zones": {"primary_front": {"label": "Primary Front"}},
    "location_zone_map": {"GRILL": "primary_front"},
}


def _paths(tmp_path: Path, db: dict | None = _SYNTHETIC_DB) -> AppPaths:
    if db is not None:
        (tmp_path / "parts_db.json").write_text(json.dumps(db), "utf-8")
    return AppPaths(workspace_config_dir=tmp_path)


# ── GETs ─────────────────────────────────────────────────────────────────────


class TestGetFullDoc:
    def test_returns_doc(self, tmp_path):
        h = FakeHandler("/api/parts-db")
        assert route_parts_db(h, "GET", "/api/parts-db", {}, _paths(tmp_path)) is True
        assert h.status == 200
        assert "whelen_ion_t" in h.body_json()["products"]

    def test_returns_empty_when_missing(self, tmp_path):
        h = FakeHandler("/api/parts-db")
        paths = AppPaths(workspace_config_dir=tmp_path)
        assert route_parts_db(h, "GET", "/api/parts-db", {}, paths) is True
        assert h.body_json()["products"] == {}


class TestGetCategories:
    def test_returns_all(self, tmp_path):
        h = FakeHandler("/api/parts-db/categories")
        assert route_parts_db(h, "GET", "/api/parts-db/categories", {}, _paths(tmp_path)) is True
        ids = {c["category_id"] for c in h.body_json()["categories"]}
        assert ids == {"lights", "push_bumpers"}


class TestGetManufacturers:
    def test_all_when_no_filter(self, tmp_path):
        h = FakeHandler("/api/parts-db/manufacturers")
        route_parts_db(h, "GET", "/api/parts-db/manufacturers", {}, _paths(tmp_path))
        ids = {m["manufacturer_id"] for m in h.body_json()["manufacturers"]}
        assert ids == {"whelen", "setina", "soundoff"}

    def test_filtered_by_category(self, tmp_path):
        h = FakeHandler("/api/parts-db/manufacturers?category=lights")
        route_parts_db(h, "GET", "/api/parts-db/manufacturers", {}, _paths(tmp_path))
        ids = {m["manufacturer_id"] for m in h.body_json()["manufacturers"]}
        assert ids == {"whelen", "soundoff"}


class TestGetProducts:
    def test_all(self, tmp_path):
        h = FakeHandler("/api/parts-db/products")
        route_parts_db(h, "GET", "/api/parts-db/products", {}, _paths(tmp_path))
        assert len(h.body_json()["products"]) == 3

    def test_filter_by_category(self, tmp_path):
        h = FakeHandler("/api/parts-db/products?category=lights")
        route_parts_db(h, "GET", "/api/parts-db/products", {}, _paths(tmp_path))
        ids = {p["product_id"] for p in h.body_json()["products"]}
        assert ids == {"whelen_ion_t", "soundoff_mpower"}

    def test_filter_by_manufacturer(self, tmp_path):
        h = FakeHandler("/api/parts-db/products?manufacturer=whelen")
        route_parts_db(h, "GET", "/api/parts-db/products", {}, _paths(tmp_path))
        ids = {p["product_id"] for p in h.body_json()["products"]}
        assert ids == {"whelen_ion_t"}

    def test_filter_by_both(self, tmp_path):
        h = FakeHandler("/api/parts-db/products?category=lights&manufacturer=setina")
        route_parts_db(h, "GET", "/api/parts-db/products", {}, _paths(tmp_path))
        # Setina has no lights → empty
        assert h.body_json()["products"] == []


class TestGetSingleProduct:
    def test_returns_product(self, tmp_path):
        h = FakeHandler("/api/parts-db/products/whelen_ion_t")
        route_parts_db(h, "GET", "/api/parts-db/products/whelen_ion_t", {}, _paths(tmp_path))
        assert h.status == 200
        assert h.body_json()["model"] == "ION T-Series"

    def test_404_unknown(self, tmp_path):
        h = FakeHandler("/api/parts-db/products/nope")
        route_parts_db(h, "GET", "/api/parts-db/products/nope", {}, _paths(tmp_path))
        assert h.status == 404


class TestGetPartNumbers:
    def test_returns_part_numbers(self, tmp_path):
        h = FakeHandler("/api/parts-db/products/whelen_ion_t/part-numbers")
        route_parts_db(h, "GET", "/api/parts-db/products/whelen_ion_t/part-numbers", {}, _paths(tmp_path))
        assert h.status == 200
        pns = h.body_json()["part_numbers"]
        assert [pn["part_number"] for pn in pns] == ["ION-T-RW"]

    def test_404_unknown_product(self, tmp_path):
        h = FakeHandler("/api/parts-db/products/nope/part-numbers")
        route_parts_db(h, "GET", "/api/parts-db/products/nope/part-numbers", {}, _paths(tmp_path))
        assert h.status == 404


class TestGetZoneProducts:
    def test_returns_compatible_products(self, tmp_path):
        h = FakeHandler("/api/parts-db/zones/primary_front/products")
        route_parts_db(h, "GET", "/api/parts-db/zones/primary_front/products", {}, _paths(tmp_path))
        # Lights + push_bumpers both apply to primary_front
        ids = {p["product_id"] for p in h.body_json()["products"]}
        assert ids == {"whelen_ion_t", "soundoff_mpower", "setina_pb400"}


# ── POST ─────────────────────────────────────────────────────────────────────


class TestPostSave:
    def test_save_succeeds(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        h = FakeHandler("/api/parts-db")
        assert route_parts_db(h, "POST", "/api/parts-db", dict(_SYNTHETIC_DB), paths) is True
        assert h.status == 200
        assert h.body_json()["ok"] is True
        on_disk = json.loads((tmp_path / "parts_db.json").read_text("utf-8"))
        assert "whelen_ion_t" in on_disk["products"]

    def test_save_invalid_payload(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        bad = {
            "schema_version": 1,
            "products": {"broken": {"category_id": "lights"}},  # missing manufacturer_id + model
        }
        h = FakeHandler("/api/parts-db")
        route_parts_db(h, "POST", "/api/parts-db", bad, paths)
        body = h.body_json()
        assert body["ok"] is False
        assert "manufacturer_id" in body["error"] or "model" in body["error"]
