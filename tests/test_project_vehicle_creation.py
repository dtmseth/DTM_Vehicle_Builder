"""Project-picker creation of artwork-pending vehicle layouts."""
from __future__ import annotations

from copy import deepcopy

from dtm_buildsheet.app.routes import config as config_routes


def _fake_config_store(monkeypatch, initial: dict) -> tuple[dict, list[dict]]:
    store = deepcopy(initial)
    saves: list[dict] = []

    def load_config_file(filename, paths):
        assert filename == "vehicle_layouts.json"
        return deepcopy(store)

    def save_config_file(filename, data, paths):
        assert filename == "vehicle_layouts.json"
        store.clear()
        store.update(deepcopy(data))
        saves.append(deepcopy(data))
        return {"ok": True, "schema_version": data.get("schema_version", 1)}

    monkeypatch.setattr(config_routes, "load_config_file", load_config_file)
    monkeypatch.setattr(config_routes, "save_config_file", save_config_file)
    return store, saves


def test_project_picker_creates_artwork_pending_vehicle(monkeypatch):
    store, saves = _fake_config_store(
        monkeypatch,
        {"schema_version": 1, "vehicles": {}},
    )

    result = config_routes.post_create_placeholder_vehicle(
        {"make": " Rivian ", "model": " R1T "},
        object(),
    )

    assert result["ok"] is True
    assert result["created"] is True
    assert result["vehicle_id"] == "R1T"
    assert len(saves) == 1
    vehicle = store["vehicles"]["R1T"]
    assert vehicle["make"] == "Rivian"
    assert vehicle["model"] == "R1T"
    assert vehicle["placeholder"] is True
    assert vehicle["fixtures"] == {}
    assert list(vehicle["views"]) == [
        "front", "side", "top", "rear",
        "internal.console", "internal.cargo", "internal.rear_seat",
    ]
    assert all(view["locations"] == {} for view in vehicle["views"].values())
    assert vehicle["views"]["side"]["logo_position"] == "bottom"
    assert vehicle["views"]["top"]["logo_position"] == "bottom"
    assert all("image" not in key.lower() for view in vehicle["views"].values() for key in view)


def test_project_picker_reuses_exact_make_and_model(monkeypatch):
    existing = {
        "make": "Ford",
        "model": "Explorer",
        "placeholder": True,
        "views": {},
    }
    _, saves = _fake_config_store(
        monkeypatch,
        {"vehicles": {"PIU": existing}},
    )

    result = config_routes.post_create_placeholder_vehicle(
        {"make": "ford", "model": " explorer "},
        object(),
    )

    assert result == {
        "ok": True,
        "created": False,
        "vehicle_id": "PIU",
        "vehicle": existing,
    }
    assert saves == []


def test_project_picker_uses_make_to_resolve_model_id_collision(monkeypatch):
    _fake_config_store(
        monkeypatch,
        {"vehicles": {"EXPLORER": {"make": "Other", "model": "Explorer"}}},
    )

    result = config_routes.post_create_placeholder_vehicle(
        {"make": "Ford", "model": "Explorer"},
        object(),
    )

    assert result["ok"] is True
    assert result["vehicle_id"] == "FORD EXPLORER"


def test_project_picker_requires_make_and_model(monkeypatch):
    _, saves = _fake_config_store(monkeypatch, {"vehicles": {}})

    result = config_routes.post_create_placeholder_vehicle(
        {"make": "Ford", "model": " "},
        object(),
    )

    assert result == {"ok": False, "error": "Make and model are required"}
    assert saves == []
