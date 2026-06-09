"""Phase 3: HTTP route coverage for /api/parts-db/*.

Bypasses the actual HTTP server — the route function `route_parts_db` accepts a
handler-like object whose only requirement is `send_json`-compatible plumbing
(`send_response`, `send_header`, `end_headers`, and `wfile.write`). A tiny
FakeHandler captures the response so assertions stay readable.
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
    """Implements just enough of BaseHTTPRequestHandler for `send_json`.

    `route_parts_db` reads `self.path` to parse the querystring and writes
    its response through `send_response`/`send_header`/`end_headers`/`wfile`
    — those four members are all that needs faking.
    """
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
    "part_categories": {"lights": {"label": "Lights"}, "radar": {"label": "Radar"}},
    "location_zones": {"primary_front": {"label": "Primary Front"}},
    "locations": {"GRILL": {"label": "Grill", "zone": "primary_front"}},
    "build_sections": {"front": {"label": "Front", "order": 1}},
    "manufacturers": {"whelen": {"label": "Whelen"}},
    "color_palette": {"red": {"label": "Red", "hex": "#E10600", "naming_token": "R"}},
    "parts": {
        "whelen_ion_t": {
            "friendly_name": "Whelen ION T",
            "category": "lights",
            "manufacturer_id": "whelen",
            "models": [{"model_id": "wh_ion_t_1", "model_number": "ION-T-1"}],
            "compatible_locations_by_vehicle": {"TAHOE": ["GRILL"]},
        },
    },
    "naming_rules": {},
}


def _paths_with_db(tmp_path: Path, db: dict | None = _SYNTHETIC_DB) -> AppPaths:
    if db is not None:
        (tmp_path / "parts_db.json").write_text(json.dumps(db), "utf-8")
    return AppPaths(workspace_config_dir=tmp_path)


# ── GET endpoints ────────────────────────────────────────────────────────────


class TestGetFullDoc:
    def test_returns_doc(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        h = FakeHandler("/api/parts-db")
        assert route_parts_db(h, "GET", "/api/parts-db", {}, paths) is True
        assert h.status == 200
        assert h.body_json()["parts"]["whelen_ion_t"]["friendly_name"] == "Whelen ION T"

    def test_returns_empty_when_missing(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        h = FakeHandler("/api/parts-db")
        assert route_parts_db(h, "GET", "/api/parts-db", {}, paths) is True
        assert h.body_json()["parts"] == {}


class TestGetParts:
    def test_filters_by_category(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        h = FakeHandler("/api/parts-db/parts?category=lights")
        assert route_parts_db(h, "GET", "/api/parts-db/parts", {}, paths) is True
        body = h.body_json()
        assert len(body["parts"]) == 1
        assert body["parts"][0]["part_id"] == "whelen_ion_t"

    def test_no_filter_returns_all(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        h = FakeHandler("/api/parts-db/parts")
        assert route_parts_db(h, "GET", "/api/parts-db/parts", {}, paths) is True
        assert len(h.body_json()["parts"]) >= 1


class TestGetSinglePart:
    def test_returns_part(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        h = FakeHandler("/api/parts-db/parts/whelen_ion_t")
        ok = route_parts_db(h, "GET", "/api/parts-db/parts/whelen_ion_t", {}, paths)
        assert ok is True
        assert h.status == 200
        assert h.body_json()["part_id"] == "whelen_ion_t"

    def test_404_when_unknown(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        h = FakeHandler("/api/parts-db/parts/nope")
        assert route_parts_db(h, "GET", "/api/parts-db/parts/nope", {}, paths) is True
        assert h.status == 404


class TestGetPartLocations:
    def test_returns_locations_for_vehicle(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        h = FakeHandler("/api/parts-db/parts/whelen_ion_t/locations?vehicle=TAHOE")
        ok = route_parts_db(
            h, "GET", "/api/parts-db/parts/whelen_ion_t/locations", {}, paths
        )
        assert ok is True
        assert h.status == 200
        ids = [loc["location_id"] for loc in h.body_json()["locations"]]
        assert ids == ["GRILL"]

    def test_missing_vehicle_returns_400(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        h = FakeHandler("/api/parts-db/parts/whelen_ion_t/locations")
        ok = route_parts_db(
            h, "GET", "/api/parts-db/parts/whelen_ion_t/locations", {}, paths
        )
        assert ok is True
        assert h.status == 400


# ── POST endpoint ────────────────────────────────────────────────────────────


class TestPostSave:
    def test_saves_and_invalidates_cache(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        body = dict(_SYNTHETIC_DB)
        h = FakeHandler("/api/parts-db")
        assert route_parts_db(h, "POST", "/api/parts-db", body, paths) is True
        assert h.status == 200
        assert h.body_json()["ok"] is True
        # File written
        on_disk = json.loads((tmp_path / "parts_db.json").read_text("utf-8"))
        assert "whelen_ion_t" in on_disk["parts"]
        # Service cache picks up the change on next read
        h2 = FakeHandler("/api/parts-db")
        route_parts_db(h2, "GET", "/api/parts-db", {}, paths)
        assert "whelen_ion_t" in h2.body_json()["parts"]

    def test_rejects_invalid_payload(self, tmp_path):
        paths = AppPaths(workspace_config_dir=tmp_path)
        # Missing required field on a part → validator raises → save handler
        # returns {"ok": False, "error": ...}
        bad = {
            "schema_version": 1,
            "parts": {
                "broken": {"category": "lights"},  # no friendly_name
            },
        }
        h = FakeHandler("/api/parts-db")
        route_parts_db(h, "POST", "/api/parts-db", bad, paths)
        body = h.body_json()
        assert body["ok"] is False
        assert "friendly_name" in body["error"]
