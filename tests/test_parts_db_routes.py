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
    "families": {
        "front_system": {
            "label": "Front System",
            "category": "structural",
            "members": ["push_bumper", "front_camera"],
        }
    },
}


def _paths(tmp_path: Path, db: dict | None = _SYNTHETIC_DB, catalog: dict | None = None) -> AppPaths:
    if db is not None:
        (tmp_path / "parts_db.json").write_text(json.dumps(db), "utf-8")
        (tmp_path / "part_catalog.json").write_text(json.dumps(catalog or {"parts": []}), "utf-8")
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

    def test_exact_sku_lookup_finds_catalog_part_case_insensitively(self, tmp_path):
        h = FakeHandler("/api/parts-db/sku-lookup?sku=ion-t-rw")
        route_parts_db(h, "GET", "/api/parts-db/sku-lookup", {}, _paths(tmp_path))
        body = h.body_json()
        assert h.status == 200
        assert body["found"] is True
        assert body["part"]["product_id"] == "whelen_ion_t"
        assert body["part"]["manufacturer_label"] == "Whelen"


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


def test_resolve_accessories_product_specific_category_overrides_generic_fallback():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    doc = {
        "accessory_categories": {"bracket_mount": {"label": "Bracket / Mount"}},
        "manufacturers": {"whelen": {"label": "Whelen"}},
        "part_types": {
            "warning_light": {"label": "Warning Light", "type_id": "lights"},
            "mirror_warning_bracket": {
                "label": "Mirror Warning Bracket",
                "type_id": "lights",
                "accessory_of": "warning_light",
                "accessory_category": "bracket_mount",
            },
        },
        "products": {
            "whelen_u_series": {
                "manufacturer_id": "whelen",
                "model": "U-Series",
                "fits_part_types": ["warning_light"],
                "accessories": [
                    {
                        "category": "bracket_mount",
                        "product_id": "whelen_u_mirror_mount",
                        "required": True,
                    }
                ],
            },
            "whelen_u_mirror_mount": {
                "manufacturer_id": "whelen",
                "model": "U-Series Under-Mirror Warning Bracket",
                "fits_part_types": ["mirror_warning_bracket"],
                "part_numbers": [{"part_number": "U18050", "vehicle_tags": ["PIU"]}],
            },
            "generic_warning_bracket": {
                "manufacturer_id": "whelen",
                "model": "Generic Warning Bracket",
                "fits_part_types": ["mirror_warning_bracket"],
                "part_numbers": [{"part_number": "GEN"}],
            },
        },
    }

    out = _resolve_accessories(_FakeAccSvc(doc), "whelen_u_series")

    assert len(out) == 1
    assert out[0]["category"] == "bracket_mount"
    assert out[0]["required"] is True
    assert [option["product_id"] for option in out[0]["options"]] == ["whelen_u_mirror_mount"]
    assert out[0]["options"][0]["skus"][0]["part_number"] == "U18050"


def test_resolve_accessories_can_keep_generic_choices_with_product_specific_one():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    doc = {
        "accessory_categories": {"bracket_mount": {"label": "Bracket / Mount"}},
        "manufacturers": {"whelen": {"label": "Whelen"}},
        "part_types": {
            "warning_light": {"label": "Warning Light", "type_id": "lights"},
            "warning_bracket": {
                "label": "Warning Bracket", "type_id": "lights",
                "accessory_of": "warning_light", "accessory_category": "bracket_mount",
            },
        },
        "products": {
            "mega_t": {
                "manufacturer_id": "whelen", "model": "Mega T-Series",
                "fits_part_types": ["warning_light"],
                "accessories": [{
                    "category": "bracket_mount", "product_id": "psbkt90",
                    "include_generic": True,
                }],
            },
            "psbkt90": {
                "manufacturer_id": "whelen", "model": "90-Degree Mount Kit",
                "part_numbers": [{"part_number": "PSBKT90"}],
            },
            "generic_mount": {
                "manufacturer_id": "whelen", "model": "Generic Warning Mount",
                "fits_part_types": ["warning_bracket"],
                "part_numbers": [{"part_number": "GEN-BRACKET"}],
            },
            "u_series": {
                "manufacturer_id": "whelen", "model": "U-Series",
                "fits_part_types": ["warning_light"],
                "accessories": [{
                    "category": "bracket_mount", "product_id": "u_only_mount",
                }],
            },
            "u_only_mount": {
                "manufacturer_id": "whelen", "model": "U-Series Mount",
                "fits_part_types": ["warning_bracket"],
                "part_numbers": [{"part_number": "U-ONLY"}],
            },
            "not_a_universal_mount": {
                "manufacturer_id": "whelen", "model": "Push Bumper Light Channel",
                "fits_part_types": ["warning_bracket"],
                "include_in_generic_accessory_options": False,
                "part_numbers": [{"part_number": "CHANNEL"}],
            },
        },
    }

    out = _resolve_accessories(_FakeAccSvc(doc), "mega_t")
    assert [option["product_id"] for option in out[0]["options"]] == ["psbkt90", "generic_mount"]


def test_child_side_specific_bracket_does_not_hide_explicit_generic_choices():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    doc = {
        "accessory_categories": {"bracket_mount": {"label": "Bracket / Mount"}},
        "manufacturers": {"whelen": {"label": "Whelen"}},
        "part_types": {
            "warning_light": {"label": "Warning Light", "type_id": "lights"},
            "warning_bracket": {
                "label": "Warning Bracket", "type_id": "lights",
                "accessory_of": "warning_light", "accessory_category": "bracket_mount",
            },
        },
        "products": {
            "ion": {
                "manufacturer_id": "whelen", "model": "ION",
                "fits_part_types": ["warning_light"],
                "accessories": [{
                    "category": "bracket_mount", "product_id": "ion_mount",
                    "include_generic": True,
                }],
            },
            "ion_mount": {
                "manufacturer_id": "whelen", "model": "ION Mount",
                "part_numbers": [{"part_number": "ION-MOUNT"}],
            },
            "generic_mount": {
                "manufacturer_id": "whelen", "model": "Universal Mount",
                "fits_part_types": ["warning_bracket"],
                "part_numbers": [{"part_number": "GEN-MOUNT"}],
            },
            "legacy_specific_mount": {
                "manufacturer_id": "whelen", "model": "Legacy ION Mount",
                "accessory_category": "bracket_mount",
                "accessory_of_products": ["ion"],
                "part_numbers": [{"part_number": "LEGACY-MOUNT"}],
            },
        },
    }

    out = _resolve_accessories(_FakeAccSvc(doc), "ion")
    assert [option["product_id"] for option in out[0]["options"]] == [
        "ion_mount", "generic_mount", "legacy_specific_mount",
    ]


def test_warning_bracket_options_are_scoped_to_their_light_family():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    doc = json.loads(
        (Path(__file__).parents[1] / "src/dtm_buildsheet/resources/config/parts_db.json").read_text("utf-8")
    )

    def bracket_ids(product_id: str) -> list[str]:
        groups = _resolve_accessories(_FakeAccSvc(doc), product_id)
        group = next(group for group in groups if group["category"] == "bracket_mount")
        return [option["product_id"] for option in group["options"]]

    mega_t_mounts = bracket_ids("whelen_mega_t_series")
    assert "whelen_strip_lite_mount" in mega_t_mounts
    assert not {
        "whelen_u_mirror_mount",
        "whelen_fender_mount",
        "whelen_tracer_l_brackets_x2_per",
        "westin_westin_2_light_tube",
        "westin_westin_4_light_tube",
        "dtm_twist_lock_adaptor",
    } & set(mega_t_mounts)
    assert bracket_ids("whelen_u_series") == ["whelen_u_mirror_mount"]
    assert "whelen_fender_mount" in bracket_ids("whelen_pro_focus")
    assert "dtm_twist_lock_adaptor" in bracket_ids("whelen_vxe")
    assert "dtm_twist_lock_adaptor" in bracket_ids("whelen_vertex")


def test_warning_light_brackets_have_part_numbers_and_correct_ion_scope():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    doc = json.loads(
        (Path(__file__).parents[1] / "src/dtm_buildsheet/resources/config/parts_db.json").read_text("utf-8")
    )

    def bracket_options(product_id: str) -> list[dict]:
        groups = _resolve_accessories(_FakeAccSvc(doc), product_id)
        return next(group for group in groups if group["category"] == "bracket_mount")["options"]

    generic = {
        "dtm_universal_grill_bracket",
        "dtm_l_bracket",
        "dtm_angle_bracket",
        "dtm_dtm_extended_cargo_window_bracket",
        "dtm_grommet_mount",
    }
    option_sets = {
        product_id: bracket_options(product_id)
        for product_id in (
            "whelen_mega_t_series",
            "whelen_t_series",
            "whelen_ion",
            "whelen_surface_mount_ion",
        )
    }
    for options in option_sets.values():
        assert generic <= {option["product_id"] for option in options}
        assert all(sku["part_number"] for option in options for sku in option["skus"])

    ion_ids = {option["product_id"] for option in option_sets["whelen_ion"]}
    surface_ion_ids = {option["product_id"] for option in option_sets["whelen_surface_mount_ion"]}
    assert {"whelen_ion_lp_bracket", "whelen_ion_grille_mount", "5_0_fab_dtm_bm6wfpiu"} <= ion_ids
    assert "whelen_ion_lp_bracket" not in surface_ion_ids
    assert all("dtm_license_plate_bracket" not in {
        option["product_id"] for option in options
    } for options in option_sets.values())
    assert doc["products"]["whelen_ion"]["model"] == "ION"

    ion_lp = doc["products"]["whelen_ion_lp_bracket"]["part_numbers"][0]
    assert ion_lp["part_number"] == "IONBKT1"
    assert ion_lp["qb_item_id"] == "281"

    pj = doc["products"]["brother_pj_822"]["part_numbers"][0]
    assert pj["part_number"] == "PJ-822"
    assert pj["qb_item_id"] == "868"
    assert pj["qb_unit_price"] == 387.59


def test_tiger_tough_seat_covers_offer_custom_patch_embroidery_only():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    doc = json.loads(
        (Path(__file__).parents[1] / "src/dtm_buildsheet/resources/config/parts_db.json").read_text("utf-8")
    )
    groups = _resolve_accessories(_FakeAccSvc(doc), "tiger_tough_w0523028_iw_blk")
    custom_patch = next(group for group in groups if group["category"] == "custom_patch")

    assert custom_patch["label"] == "Custom Patch"
    assert [option["product_id"] for option in custom_patch["options"]] == ["tiger_tough_embroidery"]
    assert custom_patch["options"][0]["model"] == "Custom Patch Embroidery"
    assert custom_patch["options"][0]["skus"][0]["price"] == 39.19
    assert all("digit" not in option["product_id"] for option in custom_patch["options"])


def test_resolve_accessories_keeps_printer_mount_and_cables_separate():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    doc = {
        "accessory_categories": {
            "printer_mount": {"label": "Bracket / Mount"},
            "printer_power_cable": {"label": "Power Cable"},
            "printer_usb_cable": {"label": "USB Cable"},
        },
        "manufacturers": {"brother": {"label": "Brother"}},
        "part_types": {
            "printer": {"label": "Printer", "type_id": "equipment"},
            "printer_mount": {"accessory_of": "printer", "accessory_category": "printer_mount"},
            "printer_power": {"accessory_of": "printer", "accessory_category": "printer_power_cable"},
            "printer_usb": {"accessory_of": "printer", "accessory_category": "printer_usb_cable"},
        },
        "products": {
            "printer": {"manufacturer_id": "brother", "model": "PocketJet", "fits_part_types": ["printer"]},
            "mount": {"manufacturer_id": "brother", "model": "Printer Mount", "fits_part_types": ["printer_mount"],
                      "part_numbers": [{"part_number": "MOUNT"}]},
            "power": {"manufacturer_id": "brother", "model": "Power Cable", "fits_part_types": ["printer_power"],
                      "part_numbers": [{"part_number": "POWER"}], "accessory_category": "printer_power_cable",
                      "accessory_of_products": ["printer"]},
            "usb": {"manufacturer_id": "brother", "model": "USB Cable", "fits_part_types": ["printer_usb"],
                    "part_numbers": [{"part_number": "USB"}], "accessory_category": "printer_usb_cable",
                    "accessory_of_products": ["printer"]},
        },
    }

    out = _resolve_accessories(_FakeAccSvc(doc), "printer")
    assert [(group["category"], group["label"]) for group in out] == [
        ("printer_mount", "Bracket / Mount"),
        ("printer_power_cable", "Power Cable"),
        ("printer_usb_cable", "USB Cable"),
    ]
    assert [[option["product_id"] for option in group["options"]] for group in out] == [
        ["mount"], ["power"], ["usb"],
    ]


def test_resolve_accessories_none_for_plain_product():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories
    doc = {"accessory_categories": {}, "manufacturers": {}, "part_types": {},
           "products": {"p": {"manufacturer_id": "m", "model": "P", "fits_part_types": []}}}
    assert _resolve_accessories(_FakeAccSvc(doc), "p") == []


def test_resolve_accessories_can_be_disabled_per_product():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories
    doc = {
        "accessory_categories": {"bracket_mount": {"label": "Bracket / Mount"}},
        "manufacturers": {},
        "part_types": {"bracket": {"accessory_of": "light", "accessory_category": "bracket_mount"}},
        "products": {
            "light": {"manufacturer_id": "m", "model": "Light", "fits_part_types": ["light"],
                      "accessories_disabled": True},
            "mount": {"manufacturer_id": "m", "model": "Mount", "fits_part_types": ["bracket"]},
        },
    }
    assert _resolve_accessories(_FakeAccSvc(doc), "light") == []


def test_siren_speaker_locations_use_curated_parts_db_allowed_placements():
    paths = AppPaths()
    h = FakeHandler(
        "/api/parts-db/category-locations?type=equipment&product=whelen_sa315p&vehicle=PIU"
    )
    route_parts_db(h, "GET", "/api/parts-db/category-locations", {}, paths)
    assert h.status == 200
    assert {row["location"] for row in h.body_json()["locations"]} == {
        "TOP OF PUSH BUMPER",
        "UNDER PUSH BUMPER",
        "BEHIND GRILL (CENTER)",
        "BEHIND OEM BUMPER",
    }


def test_scene_products_offer_center_plate_of_pb_as_a_front_scene_location():
    """Center Plate of PB is a shared Front Scene option, not a product exception."""
    for product_id in (
        "whelen_pioneer_slimline", "whelen_par46", "whelen_par32", "whelen_wing_plow_light",
    ):
        h = FakeHandler(
            "/api/parts-db/category-locations?type=lights&category=scene"
            f"&product={product_id}&vehicle=PIU"
        )
        route_parts_db(h, "GET", "/api/parts-db/category-locations", {}, AppPaths())

        locations = {row["location"]: row for row in h.body_json()["locations"]}
        assert locations["CENTER PLATE OF PB"]["part_type_id"] == "front_scene"
        assert locations["TOP OF PUSH BUMPER"]["part_type_id"] == "front_scene"


def test_selected_scene_product_uses_only_its_scene_light_locations():
    """The standard Scene step is product-scoped; custom mode owns all dots."""
    h = FakeHandler(
        "/api/parts-db/category-locations?type=lights&category=scene"
        "&product=whelen_pioneer_slimline&vehicle=PIU"
    )
    route_parts_db(h, "GET", "/api/parts-db/category-locations", {}, AppPaths())

    rows = h.body_json()["locations"]
    assert {row["location"] for row in rows} == {
        "TOP OF PUSH BUMPER", "CENTER PLATE OF PB", "UNDER TAILGATE",
    }
    assert {row["part_type_id"] for row in rows} == {"front_scene", "rear_scene"}
    assert "FRONT CORNER OF BUMPER" not in {row["location"] for row in rows}


def test_westin_push_bumpers_expose_only_bases_and_their_exact_accessories():
    """Westin channels/covers belong to a bumper; they are not alternate bumpers."""
    h = FakeHandler(
        "/api/parts-db/category-skus?type=structural&family=push_bumper_system"
    )
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    products = {row["product_id"]: row for row in h.body_json()["products"]}
    assert products["westin_36_2125"]["skus"][0]["vehicle_tags"] == ["PIU"]
    assert products["westin_36_52135"]["skus"][0]["vehicle_tags"] == ["CHEVY-1500"]
    assert {
        "westin_36_2125wc", "westin_36_4045wc", "westin_36_4075wc",
        "westin_36_52065wc", "westin_36_52135wc", "westin_36_6005",
        "westin_36_6005s4", "westin_36_6005smp2", "westin_36_6005w2",
        "westin_36_6005w4", "westin_36_6015", "westin_36_6015w2",
        "westin_36_6015w4",
    }.isdisjoint(products)
    pit_skus = {sku["part_number"]: sku for sku in products["westin_pit_bars"]["skus"]}
    assert pit_skus["36-4075PB"]["vehicle_tags"] == ["DURANGO"]

    expected = {
        "westin_36_2125": {
            "westin_wire_cover": {"westin_36_2125wc"},
            "westin_light_channel": {
                "westin_36_6005", "westin_36_6005s4", "westin_36_6005smp2",
                "westin_36_6005w2", "westin_36_6005w4",
            },
        },
        "westin_36_4045": {
            "westin_wire_cover": {"westin_36_4045wc"},
            "westin_light_channel": {"westin_36_6015w2", "westin_36_6015w4"},
        },
        "westin_36_4075": {
            "westin_wire_cover": {"westin_36_4075wc"},
            "westin_light_channel": {
                "westin_36_6005", "westin_36_6005s4", "westin_36_6005smp2",
                "westin_36_6005w2", "westin_36_6005w4",
            },
        },
        "westin_36_54085": {
            "westin_wire_cover": {"westin_36_52065wc"},
            "westin_light_channel": {"westin_36_6015", "westin_36_6015w2", "westin_36_6015w4"},
        },
        "westin_36_52135": {
            "westin_wire_cover": {"westin_36_52135wc"},
            "westin_light_channel": {"westin_36_6015", "westin_36_6015w2", "westin_36_6015w4"},
        },
    }
    for bumper_id, groups_expected in expected.items():
        h = FakeHandler(f"/api/parts-db/accessories?product_id={bumper_id}")
        route_parts_db(h, "GET", "/api/parts-db/accessories", {}, AppPaths())
        actual = {
            group["category"]: {option["product_id"] for option in group["options"]}
            for group in h.body_json()["accessories"]
            if group["category"].startswith("westin_")
        }
        assert actual == groups_expected


def test_gun_lock_locations_recover_the_legacy_workbook_choices():
    h = FakeHandler(
        "/api/parts-db/category-locations?type=equipment&product=pro_gard_single_handcuff&vehicle=PIU"
    )
    route_parts_db(h, "GET", "/api/parts-db/category-locations", {}, AppPaths())

    assert h.status == 200
    assert {row["location"] for row in h.body_json()["locations"]} == {
        "OVERHEAD ON FRONT PARTITION",
        "GUN LOCK POCKET",
        "LEFT GUN LOCK POCKET",
        "RIGHT GUN LOCK POCKET",
        "OVERHEAD IN REAR",
        "CARGO AREA MOUNT",
        "REAR SEAT MOUNT",
        "SINGLE PRISONER FACING FORWARD",
    }


def test_interior_lighting_is_one_collapsed_picker_leaf():
    h = FakeHandler("/api/parts-db/browse-tree")
    route_parts_db(h, "GET", "/api/parts-db/browse-tree", {}, AppPaths())

    lights = next(category for category in h.body_json()["categories"] if category["type_id"] == "lights")
    interior = next(child for child in lights["children"] if child.get("family_id") == "interior_lighting")
    assert interior["browse_collapsed"] is True
    assert interior["picker_part_label"] == "Interior Lights"
    assert {member["part_type_id"] for member in interior["members"]} == {
        "cargo_lighting", "front_dome_light", "rear_seat_cargo_lights", "rear_seat_lights",
    }


def test_light_bars_have_one_interior_leaf_with_front_and_rear_products():
    paths = AppPaths()
    h = FakeHandler("/api/parts-db/browse-tree")
    route_parts_db(h, "GET", "/api/parts-db/browse-tree", {}, paths)

    lights = next(category for category in h.body_json()["categories"] if category["type_id"] == "lights")
    light_bars = next(child for child in lights["children"] if child.get("family_id") == "light_bars")
    visible_interior_leaves = [
        member for member in light_bars["members"]
        if member["label"] == "Interior Light Bar" and not member["browse_hidden"]
    ]
    assert len(visible_interior_leaves) == 1
    assert visible_interior_leaves[0]["browse_part_type_ids"] == [
        "front_interior_light_bar", "rear_interior_light_bar",
    ]

    h = FakeHandler(
        "/api/parts-db/category-skus?type=lights&category=interior_bar"
        "&part_types=front_interior_light_bar,rear_interior_light_bar"
    )
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, paths)
    products = {product["product_id"]: product for product in h.body_json()["products"]}

    assert {"whelen_fst", "whelen_rst", "whelen_outer_edge", "whelen_xlp"} <= set(products)
    assert "whelen_t_series" not in products
    assert products["whelen_fst"]["fixture_catalog_id"] == "interior_light_bar_front"
    assert products["whelen_rst"]["fixture_catalog_id"] == "rear_interior_light_bar"


def test_inner_edge_shrouds_are_not_offered_but_t_series_shrouds_are():
    """THSG shrouds fit stud-mount T-Series heads, not FST/RST bars."""
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    svc = parts_db_service.get_parts_db_service(AppPaths())
    for product_id in ("whelen_fst", "whelen_rst"):
        categories = {row["category"] for row in _resolve_accessories(svc, product_id)}
        assert "shroud" not in categories

    groups = {row["category"]: row for row in _resolve_accessories(svc, "whelen_t_series")}
    assert {option["product_id"] for option in groups["shroud"]["options"]} == {
        "whelen_ie_shroud"
    }


@pytest.mark.parametrize(("product_id", "expected_locations"), [
    ("whelen_round_lighthead", {"LOWER KICK PANELS", "PRISONER HEADLINER", "LIFTGATE MOUNTED"}),
    ("soundoff_soundoff_dome_light_2", {"CARGO AREA HEADLINER", "DRIVER AREA HEADLINER"}),
])
def test_interior_light_product_locations_override_shared_part_type_locations(product_id, expected_locations):
    h = FakeHandler(
        f"/api/parts-db/category-locations?type=lights&category=interior&product={product_id}&vehicle=PIU"
    )
    route_parts_db(h, "GET", "/api/parts-db/category-locations", {}, AppPaths())

    assert h.status == 200
    assert {row["location"] for row in h.body_json()["locations"]} == expected_locations


def test_50_fab_equipment_tray_declares_its_fixed_rear_partition_location():
    h = FakeHandler("/api/parts-db/category-skus?type=equipment&part_type=equipment_tray")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    products = {row["product_id"]: row for row in h.body_json()["products"]}
    assert products["5_0_fab_dtm_ets20fpiu"]["fixed_location"] == "ON REAR PARTITION"


def test_printer_catalog_exposes_only_explicit_cable_parent_links():
    """The console printer flow must use authored, product-specific cables."""
    def products_for(part_type: str, *, include_accessory_links: bool = False) -> dict[str, dict]:
        suffix = "&include_accessory_links=1" if include_accessory_links else ""
        h = FakeHandler(f"/api/parts-db/category-skus?type=equipment&part_type={part_type}{suffix}")
        route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())
        assert h.status == 200
        return {row["product_id"]: row for row in h.body_json()["products"]}

    printer = products_for("printer")["brother_pj_822"]
    plain_power = products_for("printer_power")["brother_pocketjet_power_cable"]
    power = products_for("printer_power", include_accessory_links=True)["brother_pocketjet_power_cable"]
    usb = products_for("printer_usb", include_accessory_links=True)["brother_pocketjet_usb_cable"]

    assert printer["skus"][0]["part_number"] == "PJ-822"
    assert "accessory_of_products" not in plain_power
    assert power["accessory_of_products"] == ["brother_pj_822"]
    assert usb["accessory_of_products"] == ["brother_pj_822"]


def test_round_lighthead_has_no_accessories_and_defaults_to_red_white():
    from dtm_buildsheet.app.routes.parts_db import _resolve_accessories

    svc = parts_db_service.get_parts_db_service(AppPaths())
    h = FakeHandler("/api/parts-db/category-skus?type=lights&category=interior")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    products = {row["product_id"]: row for row in h.body_json()["products"]}
    assert products["whelen_round_lighthead"]["default_colors"] == ["red", "white"]
    assert _resolve_accessories(svc, "whelen_round_lighthead") == []


def test_preemption_locations_are_rendered_vehicle_placements():
    h = FakeHandler(
        "/api/parts-db/category-locations?type=equipment&product=nova_preemption_light_head&vehicle=PIU"
    )
    route_parts_db(h, "GET", "/api/parts-db/category-locations", {}, AppPaths())

    assert h.status == 200
    rows = h.body_json()["locations"]
    assert {row["location"] for row in rows} == {
        "IN LIGHT BAR",
        "UPPER WINDSHIELD",
        "CENTER OF DASH",
    }
    assert all(row["has_coords"] is True for row in rows)


def test_preemption_leaf_includes_nova_opticom_search_aliases():
    h = FakeHandler("/api/parts-db/category-skus?type=equipment&part_type=preemption")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    assert h.status == 200
    products = {row["product_id"]: row for row in h.body_json()["products"]}
    nova = products["nova_preemption_light_head"]
    assert nova["manufacturer_label"] == "Nova"
    assert nova["model"] == "Opticom Preemption Light Head"
    assert "Opticam" in nova["description"]
    assert any("Opticom/Opticam" in sku["friendly_name"] for sku in nova["skus"])


def test_radio_antenna_top_leaf_only_contains_radio_antenna_choices():
    h = FakeHandler("/api/parts-db/category-skus?type=equipment&part_type=radio_antenna_top")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    assert h.status == 200
    ids = {row["product_id"] for row in h.body_json()["products"]}
    assert ids == {
        "specify_cylinder_style",
        "qb_unassigned_ccas_sb_7_800",
        "laird_qwb800",
    }
    assert not any(pid.startswith("stalker_") for pid in ids)
    assert "ace_k_9_ha_rbm_27_rd" not in ids
    assert "watchguard_trab58003_wg1" not in ids
    assert "qb_unassigned_cell_antenna" not in ids
    labels = {row["product_id"]: row["model"] for row in h.body_json()["products"]}
    assert labels == {
        "specify_cylinder_style": "Cylinder-Style Radio Antenna",
        "qb_unassigned_ccas_sb_7_800": "Covert / Stinger-Style Radio Antenna",
        "laird_qwb800": "Whip-Style Radio Antenna",
    }
    assert {row["manufacturer_label"] for row in h.body_json()["products"]} == {"Shop Detail"}


def test_radio_location_rules_are_shop_facing_and_constrained():
    db_path = Path("src/dtm_buildsheet/resources/config/parts_db.json")
    part_types = json.loads(db_path.read_text("utf-8"))["part_types"]
    assert part_types["radio_head"]["location_options"] == [
        "CONSOLE POSITION 1 (TOP)",
        "CONSOLE POSITION 2",
        "CONSOLE POSITION 3",
        "CONSOLE POSITION 4",
        "REAR STORAGE AREA (SECONDARY RADIO)",
    ]
    assert "ON EQUIPMENT TRAY" not in part_types["radio_head"]["location_options"]
    assert part_types["radio_brick"]["location_options"] == ["ON EQUIPMENT TRAY", "FRONT OF PARTITION"]
    assert part_types["radio_antenna_top"]["location_options"] == [
        "REAR LEFT ROOF",
        "LEFT CARGO WINDOW",
        "RIGHT CARGO WINDOW",
    ]
    assert part_types["radio_speaker"]["location_options"] == [
        "BACK OF CENTER CONSOLE",
        "TOP OF CAGE - CENTER",
        "TOP OF CAGE - DRIVER SIDE",
        "TOP OF CAGE - PASSENGER SIDE",
        "UNDER DASH",
        "FRONT OF CONSOLE",
    ]


def test_radio_mic_leaf_uses_short_mag_mic_labels():
    h = FakeHandler("/api/parts-db/category-skus?type=equipment&part_type=radio_mic_clip")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    assert h.status == 200
    products = {row["product_id"]: row for row in h.body_json()["products"]}
    assert products["magnetic_mic_mmsu_1"]["model"] == "Mag Mic"
    assert products["magnetic_mic_mmsu_1b"]["model"] == "Mag Mic with Bracket"
    assert products["magnetic_mic_mmbp_25"]["model"] == "Mag Mic"


def test_radio_head_cable_accessories_include_no_new_and_supply_choices():
    h = FakeHandler("/api/parts-db/accessories?product_id=motorola_all_in_one_unit")
    route_parts_db(h, "GET", "/api/parts-db/accessories", {}, AppPaths())

    assert h.status == 200
    groups = {row["category"]: row for row in h.body_json()["accessories"]}
    cable_ids = {option["product_id"] for option in groups["cable"]["options"]}
    assert {
        "shop_no_radio_cables_needed",
        "qb_unassigned_radio_antenna",
        "motorola_radio_refresh_kit",
        "motorola_pmkn4033a",
    }.issubset(cable_ids)


@pytest.mark.parametrize("system, vehicle, expected_ids", [
    ("radio", "PIU", {"antenna_cable", "power_cable", "blue_communication_cable"}),
    ("radar", "TAHOE", {"front_antenna_cable", "rear_antenna_cable", "display_counting_unit_cable", "vss_speed_cable"}),
    ("camera", "PIU", {"signal_data_cable"}),
])
def test_guided_system_cable_refreshes_are_live_qb_items(system, vehicle, expected_ids):
    h = FakeHandler(f"/api/parts-db/system-cable-refreshes?system={system}&vehicle={vehicle}")
    route_parts_db(h, "GET", "/api/parts-db/system-cable-refreshes", {}, AppPaths())

    assert h.status == 200
    refreshes = h.body_json()["refreshes"]
    assert {entry["id"] for entry in refreshes} == expected_ids
    assert all(option["qb_item_id"] and option["price"] is not None
               for entry in refreshes for option in entry["billing_options"])


def test_guided_system_cable_refreshes_hide_tahoe_only_vss_kit_elsewhere():
    h = FakeHandler("/api/parts-db/system-cable-refreshes?system=radar&vehicle=PIU")
    route_parts_db(h, "GET", "/api/parts-db/system-cable-refreshes", {}, AppPaths())

    vss = next(entry for entry in h.body_json()["refreshes"] if entry["id"] == "vss_speed_cable")
    assert {option["part_number"] for option in vss["billing_options"]} == {"200-0622-00"}


def test_category_skus_all_searches_all_categories_with_metadata():
    h = FakeHandler("/api/parts-db/category-skus?all=1")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    assert h.status == 200
    products = {row["product_id"]: row for row in h.body_json()["products"]}
    nova = products["nova_preemption_light_head"]
    assert nova["primary_part_type_id"] == "preemption"
    assert nova["primary_type_id"] == "equipment"
    search_text = nova["search_text"].lower()
    assert "nova" in search_text
    assert "opticam" in search_text
    assert "preemption" in search_text


def test_cctl5_skips_pa_mic_and_keeps_custom_location_alongside_console():
    h = FakeHandler("/api/parts-db/category-skus?type=equipment&part_type=control_head")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    assert h.status == 200
    product = next(row for row in h.body_json()["products"] if row["product_id"] == "whelen_cctl5")
    assert product["pa_mic_required"] is False
    assert product["handheld_mag_mic_prompt"] is True
    assert product["allow_custom_location"] is True


def test_cctlharn_is_selectable_as_a_pending_secondary_control_head_harness():
    h = FakeHandler(
        "/api/parts-db/category-skus?type=equipment&part_type=secondary_control_head_harness"
    )
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    assert h.status == 200
    product = next(
        row for row in h.body_json()["products"] if row["product_id"] == "whelen_cctlharn"
    )
    assert product["model"] == "CenCom Core Secondary Control Head Harness"
    assert product["primary_part_type_id"] == "secondary_control_head_harness"
    assert "Non-Primary Control Head" in product["description"]
    assert product["skus"] == [{
        "part_number": "CCTLHARN",
        "friendly_name": "WHELEN CENCOM CORE SECONDARY CONTROL HEAD HARNESS",
        "color": "",
        "secondary_color": "",
        "tertiary_color": "",
        "lens_type": "",
        "price": 10,
        "qb": False,
        "qb_pending": True,
        "vehicle_tags": ["any"],
    }]


def test_second_control_head_recommends_the_pending_harness_accessory():
    h = FakeHandler("/api/parts-db/accessories?product_id=whelen_cctl5")
    route_parts_db(h, "GET", "/api/parts-db/accessories", {}, AppPaths())

    assert h.status == 200
    group = next(row for row in h.body_json()["accessories"] if row["category"] == "control_head_harness")
    assert group["required"] is False
    assert group["recommendations"] == [{
        "product_id": "whelen_cctlharn",
        "when_existing_part_type": "control_head",
        "minimum_existing_count": 1,
        "message": "Recommended for a secondary control head",
    }]
    assert group["options"][0]["product_id"] == "whelen_cctlharn"
    assert group["options"][0]["skus"][0]["part_number"] == "CCTLHARN"
    assert group["options"][0]["skus"][0]["qb_pending"] is True


def test_lcphoto_is_automatic_for_interior_light_bars_and_not_cencom_core():
    core = FakeHandler("/api/parts-db/accessories?product_id=whelen_core")
    route_parts_db(core, "GET", "/api/parts-db/accessories", {}, AppPaths())
    assert all(
        option["product_id"] != "whelen_lcphoto"
        for group in core.body_json()["accessories"]
        for option in group["options"]
    )

    interior_products = {
        "whelen_fst", "whelen_xlp", "whelen_rst",
        "soundoff_enftc001bw", "soundoff_enfwb0005k", "soundoff_enfwb003mp",
        "soundoff_enfwbfs", "qb_unassigned_enfwbrf", "qb_unassigned_fn_1409",
    }
    for product_id in interior_products:
        handler = FakeHandler(f"/api/parts-db/accessories?product_id={product_id}")
        route_parts_db(handler, "GET", "/api/parts-db/accessories", {}, AppPaths())
        group = next(
            row for row in handler.body_json()["accessories"]
            if "whelen_lcphoto" in row.get("automatic_option_ids", [])
        )
        assert group["required"] is True
        assert group["automatic_option_ids"] == ["whelen_lcphoto"]
        lcphoto = next(option for option in group["options"] if option["product_id"] == "whelen_lcphoto")
        assert lcphoto["skus"][0]["part_number"] == "LCPHOTO"


@pytest.mark.parametrize("product_id", ["whelen_t_series", "whelen_mega_t_series"])
@pytest.mark.parametrize("route", [
    "/api/parts-db/category-skus?all=1",
    "/api/parts-db/category-skus?type=lights",
])
def test_t_series_uses_declared_warning_light_picker_flow_from_every_lights_entry(route, product_id):
    """T-Series is a warning light even when the user opens the broad Lights leaf."""
    h = FakeHandler(route)
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    products = {row["product_id"]: row for row in h.body_json()["products"]}
    product = products[product_id]
    assert product["primary_part_type_id"] == "warning_light"
    assert product["primary_category_id"] == "warning"


def test_setina_rear_window_barriers_are_one_product_with_all_variants():
    h = FakeHandler("/api/parts-db/category-skus?type=structural&part_type=rear_window_bars")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    assert h.status == 200
    products = h.body_json()["products"]
    setina_products = [product for product in products if product["manufacturer_id"] == "setina"]
    assert len(setina_products) == 1
    barrier = setina_products[0]
    assert barrier["product_id"] == "setina_steel_vertical"
    assert barrier["model"] == "Window Barrier"
    assert barrier["fixed_location"] == "REAR WINDOWS"
    part_numbers = {sku["part_number"] for sku in barrier["skus"]}
    assert {
        "WK0514TAH21",   # steel vertical
        "WK0514TAH21H",  # steel horizontal
        "WK0595TAH21",   # polycarbonate
        "WK1491TAH21T",  # tinted polycarbonate
    }.issubset(part_numbers)


def test_cage_family_uses_a_fixed_prisoner_area_location_with_product_overrides():
    h = FakeHandler("/api/parts-db/category-skus?type=structural&family=cage_prisoner_containment")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, AppPaths())

    assert h.status == 200
    products = {product["product_id"]: product for product in h.body_json()["products"]}
    assert products["setina_full_partition"]["fixed_location"] == "PRISONER AREA"
    assert products["setina_steel_vertical"]["fixed_location"] == "REAR WINDOWS"


def test_category_skus_family_filter_uses_member_union(tmp_path):
    h = FakeHandler("/api/parts-db/category-skus?type=structural&family=front_system")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, _paths(tmp_path))

    assert h.status == 200
    ids = {p["product_id"] for p in h.body_json()["products"]}
    assert ids == {"setina_pb400", "whelen_cam"}


def test_category_skus_marks_fixture_products_for_location_skip(tmp_path):
    catalog = {
        "parts": [
            {
                "part_id": "push_bumper",
                "display_name": "Push Bumper",
                "category": "vehicle_system",
                "render_kind": "bar",
                "default_views": ["front"],
                "is_fixture": True,
            }
        ]
    }
    h = FakeHandler("/api/parts-db/category-skus?type=structural&part_type=push_bumper")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, _paths(tmp_path, catalog=catalog))

    assert h.status == 200
    product = h.body_json()["products"][0]
    assert product["product_id"] == "setina_pb400"
    assert product["is_fixture"] is True
    assert product["default_location"] == "Push Bumper"
    assert product["fixture_part_type_id"] == "push_bumper"
    assert product["fixture_catalog_id"] == "push_bumper"
    assert product["fixture_name_pattern"] == "Push Bumper"
    assert product["fixture_base_label"] == "Push Bumper"


def test_category_skus_fixture_alias_for_front_interior_lightbar():
    paths = AppPaths()
    h = FakeHandler("/api/parts-db/category-skus?type=lights&part_type=front_interior_light_bar")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, paths)

    assert h.status == 200
    products = h.body_json()["products"]
    assert products
    assert {p["fixture_catalog_id"] for p in products} == {"interior_light_bar_front"}
    assert {p["fixture_part_type_id"] for p in products} == {"front_interior_light_bar"}
    assert {p["default_location"] for p in products} == {"INTERIOR LIGHT BAR (FRONT)"}


@pytest.mark.parametrize(
    ("type_id", "part_type_id", "catalog_id"),
    [
        ("structural", "push_bumper", "push_bumper"),
        ("structural", "pit_bar", "pit_bar"),
        ("structural", "wing_wraps", "wing_wraps"),
        ("lights", "roof_light_bar", "roof_light_bar"),
        ("lights", "front_interior_light_bar", "interior_light_bar_front"),
        ("lights", "rear_interior_light_bar", "rear_interior_light_bar"),
    ],
)
def test_category_skus_marks_real_fixture_part_types(type_id, part_type_id, catalog_id):
    paths = AppPaths()
    h = FakeHandler(f"/api/parts-db/category-skus?type={type_id}&part_type={part_type_id}")
    route_parts_db(h, "GET", "/api/parts-db/category-skus", {}, paths)

    assert h.status == 200
    products = h.body_json()["products"]
    assert products
    assert all(p["is_fixture"] for p in products)
    assert {p["fixture_part_type_id"] for p in products} == {part_type_id}
    assert {p["fixture_catalog_id"] for p in products} == {catalog_id}


def test_manifest_groups_expose_sales_oriented_grouping():
    paths = AppPaths()
    h = FakeHandler("/api/parts-db/manifest-groups")
    route_parts_db(h, "GET", "/api/parts-db/manifest-groups", {}, paths)
    assert h.status == 200
    body = h.body_json()
    assert [g["label"] for g in body["groups"][:4]] == [
        "Front Exterior",
        "Lighting Systems",
        "Driver Area / Console",
        "Electronics / Communications",
    ]
    pmap = body["part_type_map"]
    assert pmap["siren_speaker"]["group_label"] == "Front Exterior"
    assert pmap["siren_speaker"]["section_label"] == "Siren / Speaker"
    assert pmap["console"]["group_label"] == "Driver Area / Console"
    assert pmap["console"]["section_label"] == "Console"
    assert pmap["rear_partition"]["group_label"] == "Prisoner Area"


def test_tracer_heads_endpoint(tmp_path):
    """The tracer-heads endpoint wires query params → resolver → JSON."""
    db = json.loads(json.dumps(_SYNTHETIC_DB))   # deep copy (keeps required top-level keys)
    db["products"].update({
        "tracer5": {"manufacturer_id": "whelen", "model": "Tracer 5-Lamp",
                    "fits_part_types": [], "part_numbers": [{"part_number": "TCRWX5"}],
                    "accessories": [{"category": "lighthead", "product_id": "prim"},
                                    {"category": "lighthead", "product_id": "sec"}]},
        "prim": {"manufacturer_id": "whelen", "model": "Tracer WCX Primary Lighthead",
                 "fits_part_types": [], "part_numbers": [
                     {"part_number": "TCRWXPD", "color": "red", "secondary_color": "white", "lens_type": "clear"},
                     {"part_number": "TCRWXPE", "color": "blue", "secondary_color": "white", "lens_type": "clear"}]},
        "sec": {"manufacturer_id": "whelen", "model": "Tracer WCX Secondary Lighthead",
                "fits_part_types": [], "part_numbers": [
                    {"part_number": "TCRWXSD", "color": "red", "secondary_color": "white", "lens_type": "clear"},
                    {"part_number": "TCRWXSE", "color": "blue", "secondary_color": "white", "lens_type": "clear"}]},
    })
    h = FakeHandler("/api/parts-db/tracer-heads?product_id=tracer5&mode=duo&secondary=white")
    route_parts_db(h, "GET", "/api/parts-db/tracer-heads", {}, _paths(tmp_path, db))
    body = h.body_json()
    assert body["ok"] is True
    assert body["lamp_count"] == 5
    qty = {l["sku"]: l["qty"] for l in body["lines"]}
    assert qty == {"TCRWX5": 2, "TCRWXPD": 1, "TCRWXSD": 4, "TCRWXPE": 1, "TCRWXSE": 4}


def test_tracer_heads_endpoint_missing_product_id(tmp_path):
    h = FakeHandler("/api/parts-db/tracer-heads")
    route_parts_db(h, "GET", "/api/parts-db/tracer-heads", {}, _paths(tmp_path))
    assert h.status == 400


def test_inner_edge_heads_endpoint_uses_selected_housing_sku(tmp_path):
    db = json.loads(json.dumps(_SYNTHETIC_DB))
    db["products"].update({
        "fst": {
            "manufacturer_id": "whelen", "model": "Inner Edge FST",
            "fits_part_types": [],
            "part_numbers": [{"part_number": "FST10", "qb_sales_description": "FST 10-LT"}],
            "accessories": [{"category": "lighthead", "product_id": "ie_head"}],
        },
        "ie_head": {
            "manufacturer_id": "whelen", "model": "Inner Edge Lighthead", "fits_part_types": [],
            "part_numbers": [
                {"part_number": "IE-RW", "color": "red", "secondary_color": "white"},
                {"part_number": "IE-BW", "color": "blue", "secondary_color": "white"},
            ],
        },
    })
    # The route is deliberately restricted to production FST/RST identifiers;
    # use the real name here to verify its public API, not a looser heuristic.
    db["products"]["whelen_fst"] = db["products"].pop("fst")
    h = FakeHandler(
        "/api/parts-db/inner-edge-heads?product_id=whelen_fst&part_number=FST10&mode=duo&secondary=white"
    )
    route_parts_db(h, "GET", "/api/parts-db/inner-edge-heads", {}, _paths(tmp_path, db))
    body = h.body_json()
    assert body["ok"] is True
    assert {line["sku"]: line["qty"] for line in body["lines"]} == {
        "FST10": 1, "IE-RW": 5, "IE-BW": 5,
    }


def test_outer_edge_pillar_heads_endpoint_creates_the_six_required_ions(tmp_path):
    db = json.loads(json.dumps(_SYNTHETIC_DB))
    db["products"].update({
        "whelen_ion_rear_pillar": {
            "manufacturer_id": "whelen", "model": "Outer Edge Rear Pillar",
            "fits_part_types": [],
            "part_numbers": [
                {"part_number": "RPWD50", "friendly_name": "Outer Edge Rear Pillar Duo"},
                {"part_number": "RPWT50", "friendly_name": "Outer Edge Rear Pillar Trio"},
            ],
            "accessories": [{"category": "lighthead", "product_id": "outer_ion"}],
        },
        "outer_ion": {
            "manufacturer_id": "whelen", "model": "Outer Edge ION", "fits_part_types": [],
            "part_numbers": [
                {"part_number": "OEI2RW", "color": "red", "secondary_color": "white", "lens_type": "clear"},
                {"part_number": "OEI2BW", "color": "blue", "secondary_color": "white", "lens_type": "clear"},
                {"part_number": "OEI2RA", "color": "red", "secondary_color": "amber", "lens_type": "clear"},
                {"part_number": "OEI2BA", "color": "blue", "secondary_color": "amber", "lens_type": "clear"},
                {"part_number": "OEI3RBA", "color": "red", "secondary_color": "blue", "tertiary_color": "amber", "lens_type": "clear"},
            ],
        },
    })

    duo = FakeHandler(
        "/api/parts-db/outer-edge-pillar-heads?product_id=whelen_ion_rear_pillar&part_number=RPWD50&secondary=amber"
    )
    route_parts_db(duo, "GET", "/api/parts-db/outer-edge-pillar-heads", {}, _paths(tmp_path, db))
    duo_body = duo.body_json()
    assert duo_body["ok"] is True
    assert duo_body["mode"] == "duo"
    assert duo_body["lamp_count"] == 6
    assert {line["sku"]: line["qty"] for line in duo_body["lines"]} == {
        "RPWD50": 1, "OEI2RA": 3, "OEI2BA": 3,
    }

    trio = FakeHandler(
        "/api/parts-db/outer-edge-pillar-heads?product_id=whelen_ion_rear_pillar&part_number=RPWT50&secondary=white"
    )
    route_parts_db(trio, "GET", "/api/parts-db/outer-edge-pillar-heads", {}, _paths(tmp_path, db))
    trio_body = trio.body_json()
    assert trio_body["ok"] is True
    assert trio_body["mode"] == "trio"
    assert trio_body["secondary_color"] == "amber"
    assert {line["sku"]: line["qty"] for line in trio_body["lines"]} == {
        "RPWT50": 1, "OEI3RBA": 6,
    }
