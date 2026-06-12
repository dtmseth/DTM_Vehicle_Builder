"""Phase 3 (schema v2): PartsDbService typed-query coverage.

Tree-based hierarchy + intersection rules. Drives every public query off a
small synthetic parts_db.json that exercises the shapes described in the
quiet-vaulting-quail plan §1.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from dtm_buildsheet.app.services import parts_db_service
from dtm_buildsheet.app.services.parts_db_service import (
    PartsDbService,
    get_parts_db_service,
)
from dtm_buildsheet.paths import AppPaths


@pytest.fixture(autouse=True)
def _reset_singleton():
    parts_db_service.reset_for_testing()
    yield
    parts_db_service.reset_for_testing()


_SYNTHETIC_DB = {
    "schema_version": 2,
    "types": {
        "extras":     {"label": "Extras"},
        "structural": {"label": "Structural"},
        "lights":     {"label": "Lights"},
        "k9":         {"label": "K-9", "requires_attribute": "has_k9"},
    },
    "sections": {
        "exterior": {"label": "Exterior"},
        "interior": {"label": "Interior"},
    },
    "zones": {
        "front":            {"label": "Front", "section": "exterior"},
        "roof":             {"label": "Roof",  "section": "exterior"},
        "forward_of_cage":  {"label": "Forward of Cage", "section": "interior"},
        "prisoner_area":    {"label": "Prisoner Area", "section": "interior",
                             "requires_attribute": "has_prisoner_compartment"},
    },
    "sub_zones": {
        "console": {"label": "Console", "zone": "forward_of_cage"},
    },
    "build_attributes": {
        "has_k9":                   {"label": "K-9 Vehicle"},
        "has_prisoner_compartment": {"label": "Has Prisoner Compartment"},
    },
    "tags": {
        "camera": {"label": "Camera"},
        "siren":  {"label": "Siren"},
    },
    "manufacturers": {
        "whelen": {"label": "Whelen"},
        "setina": {"label": "Setina"},
        "factory_brand": {"label": "Factory"},
        "arges":  {"label": "Arges"},
    },
    "products": {
        "whelen_ion_t": {
            "manufacturer_id": "whelen",
            "model": "ION T-Series",
            "fits_part_types": ["forward_warning", "side_warning"],
            "tag_ids": [],
            "part_numbers": [
                {"part_number": "ION-T-RW"},
                {"part_number": "ION-T-RB"},
            ],
        },
        "setina_pb400": {
            "manufacturer_id": "setina",
            "model": "PB400",
            "fits_part_types": ["push_bumper"],
            "part_numbers": [{"part_number": "PB400-TAHOE"}],
        },
        "factory_brand_factory_spotlight": {
            "manufacturer_id": "factory_brand",
            "model": "Factory",
            "fits_part_types": ["spotlight"],
        },
        "arges_arges_spotlight": {
            "manufacturer_id": "arges",
            "model": "Arges",
            "fits_part_types": ["spotlight"],
        },
        "feniex_cam": {
            "manufacturer_id": "whelen",  # using whelen as proxy mfg for fixture
            "model": "Cam",
            "fits_part_types": ["front_camera"],
            "tag_ids": ["camera"],
        },
    },
    "part_types": {
        "forward_warning": {
            "label": "Forward Warning",
            "type_id": "lights",
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "workbook_label_pattern": "Forward Warning {n}",
            "sequence_scope": "global",
        },
        "side_warning": {
            "label": "Side Warning",
            "type_id": "lights",
            "tree_positions": [
                {"section": "exterior", "zone": "front"},
                {"section": "interior", "zone": "prisoner_area"},
            ],
            "workbook_label_pattern": "Side Warning {n}",
            "sequence_scope": "global",
        },
        "push_bumper": {
            "label": "Push Bumper",
            "type_id": "structural",
            "tree_positions": [{"section": "exterior", "zone": "front"}],
            "accessories": ["wire_covers"],
            "workbook_label_pattern": "Push Bumper",
            "sequence_scope": "global",
        },
        "wire_covers": {
            "label": "Wire Covers",
            "type_id": "structural",
            "tree_positions": [],
            "accessory_of": "push_bumper",
            "workbook_label_pattern": "Wire Covers",
            "sequence_scope": "global",
        },
        "spotlight": {
            "label": "Spotlight",
            "type_id": "lights",
            "tree_positions": [
                {"section": "exterior", "zone": "front"},
                {"section": "exterior", "zone": "roof"},
            ],
            "allowed_products": ["factory_brand_factory_spotlight", "arges_arges_spotlight"],
            "allowed_placements": ["A_PILLAR_DRIVER", "LIGHTBAR_MOUNT"],
            "workbook_label_pattern": "Spotlight",
            "sequence_scope": "global",
        },
        "front_camera": {
            "label": "Front Camera",
            "type_id": "equipment",
            "tree_positions": [{"section": "interior", "zone": "forward_of_cage"}],
            "tag_ids": ["camera"],
            "workbook_label_pattern": "Front Camera",
            "sequence_scope": "global",
        },
        "k9_kennel": {
            "label": "K-9 Kennel",
            "type_id": "k9",
            "tree_positions": [{"section": "interior", "zone": "prisoner_area"}],
            "workbook_label_pattern": "K-9 Kennel",
            "sequence_scope": "global",
        },
    },
    "placements": {
        "GRILL":          {"placement_zone": "primary_front"},
        "A_PILLAR_DRIVER": {"placement_zone": "front_corner"},
        "LIGHTBAR_MOUNT": {"placement_zone": "roof",
                           "allowed_products": ["arges_arges_spotlight"]},
        "HEADLIGHT_TWIST_LOCK": {"placement_zone": "primary_front",
                                  "allowed_products": ["whelen_vxe"]},
    },
    "placement_zones": {
        "primary_front": {"label": "Primary Front"},
        "front_corner":  {"label": "Front Corner"},
        "roof":          {"label": "Roof"},
    },
    "services": {
        "graphics": {"label": "Graphics / Decals"},
    },
    "preference_filters": {
        "lighting_brand": {
            "preference_field": "preferences.lighting",
            "filter_scope_kind": "type_id",
            "filter_scope_values": ["lights"],
            "filter_action": "restrict_to_manufacturer",
        },
    },
    "color_palette": {
        "red":  {"label": "Red",  "hex": "#E10600", "naming_token": "R"},
        "blue": {"label": "Blue", "hex": "#003DA5", "naming_token": "B"},
    },
}


def _paths_with_db(tmp_path: Path, db: dict | None = _SYNTHETIC_DB) -> AppPaths:
    if db is not None:
        (tmp_path / "parts_db.json").write_text(json.dumps(db), "utf-8")
    return AppPaths(workspace_config_dir=tmp_path)


# ── Top-level taxonomies ─────────────────────────────────────────────────────


class TestTopLevelTaxonomies:
    def test_list_types(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {t.type_id for t in svc.list_types()}
        assert ids == {"extras", "structural", "lights", "k9"}

    def test_k9_carries_required_attribute(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        k9 = next(t for t in svc.list_types() if t.type_id == "k9")
        assert k9.requires_attribute == "has_k9"

    def test_list_sections(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert {s.section_id for s in svc.list_sections()} == {"exterior", "interior"}

    def test_list_zones_unfiltered(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert len(svc.list_zones()) == 4

    def test_list_zones_filtered_by_section(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {z.zone_id for z in svc.list_zones(section="interior")}
        assert ids == {"forward_of_cage", "prisoner_area"}

    def test_list_sub_zones_filtered(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert [s.sub_zone_id for s in svc.list_sub_zones(zone="forward_of_cage")] == ["console"]

    def test_list_build_attributes(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {a.attribute_id for a in svc.list_build_attributes()}
        assert ids == {"has_k9", "has_prisoner_compartment"}

    def test_list_tags(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert {t.tag_id for t in svc.list_tags()} == {"camera", "siren"}

    def test_list_services(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert {s.service_id for s in svc.list_services()} == {"graphics"}

    def test_list_preference_filters(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        prefs = svc.list_preference_filters()
        assert len(prefs) == 1
        assert prefs[0].preference_field == "preferences.lighting"
        assert prefs[0].filter_scope_kind == "type_id"


# ── Part types ───────────────────────────────────────────────────────────────


class TestPartTypeQueries:
    def test_list_all(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {pt.part_type_id for pt in svc.list_part_types()}
        assert "forward_warning" in ids
        assert "spotlight" in ids
        assert "wire_covers" in ids

    def test_list_at_type(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {pt.part_type_id for pt in svc.list_part_types_at(type_id="lights")}
        assert "forward_warning" in ids
        assert "spotlight" in ids
        assert "push_bumper" not in ids

    def test_list_at_section_and_zone(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {pt.part_type_id for pt in
               svc.list_part_types_at(section="exterior", zone="front")}
        assert "forward_warning" in ids
        assert "side_warning" in ids        # appears at multiple tree positions, this is one
        assert "push_bumper" in ids
        assert "spotlight" in ids
        assert "front_camera" not in ids

    def test_list_at_sub_zone(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        # Filter for sub_zone="" matches only positions without a sub_zone
        assert svc.list_part_types_at(sub_zone="console") == []

    def test_side_warning_appears_at_both_positions(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        sw = next(pt for pt in svc.list_part_types() if pt.part_type_id == "side_warning")
        assert len(sw.tree_positions) == 2
        assert {pos.zone for pos in sw.tree_positions} == {"front", "prisoner_area"}

    def test_list_with_tag(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {pt.part_type_id for pt in svc.list_part_types_with_tag("camera")}
        assert ids == {"front_camera"}

    def test_list_accessories_of(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = [pt.part_type_id for pt in svc.list_accessories_of("push_bumper")]
        assert ids == ["wire_covers"]

    def test_get_part_type(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        pt = svc.get_part_type("forward_warning")
        assert pt is not None
        assert pt.workbook_label_pattern == "Forward Warning {n}"


# ── Products ────────────────────────────────────────────────────────────────


class TestProductQueries:
    def test_list_all(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        assert len(svc.list_products()) == 5

    def test_list_for_part_type_uses_fits(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {p.product_id for p in svc.list_products_for_part_type("forward_warning")}
        assert ids == {"whelen_ion_t"}

    def test_list_for_part_type_intersects_allowed_products(self, tmp_path):
        # Spotlight has allowed_products=[factory, arges]; both products fit
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {p.product_id for p in svc.list_products_for_part_type("spotlight")}
        assert ids == {"factory_brand_factory_spotlight", "arges_arges_spotlight"}

    def test_list_with_tag(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {p.product_id for p in svc.list_products_with_tag("camera")}
        assert ids == {"feniex_cam"}

    def test_get_product(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        p = svc.get_product("whelen_ion_t")
        assert p is not None
        assert p.model == "ION T-Series"

    def test_list_part_numbers(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        pns = svc.list_part_numbers("whelen_ion_t")
        assert [pn.part_number for pn in pns] == ["ION-T-RW", "ION-T-RB"]


# ── Placements & placement zones ────────────────────────────────────────────


class TestPlacements:
    def test_get_placement_with_restriction(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        pl = svc.get_placement("LIGHTBAR_MOUNT")
        assert pl.placement_zone == "roof"
        assert pl.allowed_products == ["arges_arges_spotlight"]

    def test_get_placement_unknown_returns_empty(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        pl = svc.get_placement("NOWHERE")
        assert pl.placement_zone == ""
        assert pl.allowed_products == []

    def test_list_placement_zones(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        ids = {z.placement_zone_id for z in svc.list_placement_zones()}
        assert ids == {"primary_front", "front_corner", "roof"}


# ── Lifecycle ───────────────────────────────────────────────────────────────


class TestCaching:
    def test_singleton_per_paths(self, tmp_path):
        paths = _paths_with_db(tmp_path)
        assert get_parts_db_service(paths) is get_parts_db_service(paths)

    def test_invalidate_drops_cache(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        svc.raw_doc()
        assert svc._cache is not None
        svc.invalidate()
        assert svc._cache is None


class TestMissingFile:
    def test_empty_doc_when_missing(self, tmp_path):
        svc = PartsDbService(AppPaths(workspace_config_dir=tmp_path))
        assert svc.raw_doc()["products"] == {}
        assert svc.list_part_types() == []
        assert svc.list_types() == []


# ── Perf guardrail ──────────────────────────────────────────────────────────


class TestLookupPerf:
    def test_thousand_get_product_under_100ms(self, tmp_path):
        svc = PartsDbService(_paths_with_db(tmp_path))
        svc.raw_doc()
        start = time.perf_counter()
        for _ in range(1000):
            svc.get_product("whelen_ion_t")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 100, f"1000 lookups took {elapsed_ms:.0f}ms"
