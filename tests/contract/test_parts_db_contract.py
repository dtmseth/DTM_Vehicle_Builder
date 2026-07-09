"""HTTP contract snapshots for app/routes/parts_db.py (§8.1 Step 1b).

parts_db.py is first under the knife for the Step 4 repository extraction
(AUDIT_REFACTOR_ROADMAP.md §8.1 Step 4), so its route contract is pinned
first. One case per distinct GET route (including its query-param branches)
plus the three read-only POST endpoints (match-skus, resolve-selection,
validate-placement) — each recorded against a throwaway copy of the real
seeded parts_db.json (hermetic AppPaths, same corpus config the golden
masters use) so the snapshot reflects real data shapes, not a synthetic
fixture.

Deliberately NOT covered here: ``POST /api/parts-db`` (full-document save)
and ``POST /api/parts-db/edit/*`` (the ~350-LOC edit-command surface) —
both mutate parts_db.json, so a byte-snapshot contract doesn't fit them the
way it fits reads; they're covered by test_parts_db_edit_routes.py's
behavioral assertions instead. Add mutation-endpoint contracts in a later
Phase E session if drift there becomes a problem in practice.

Recording / re-recording:

    pytest tests/contract/test_parts_db_contract.py --contract-record

IDs baked into the case table below (e.g. ``setina_pb400``, ``whelen_ion``)
are real parts_db.json data verified present as of the 2026-07-08 curation
apply (13 plans, see git log) — if a future curation pass renames or
deletes one, this file's case table needs a one-line update alongside the
re-recorded snapshot, not a redesign.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.app.routes.parts_db import route_parts_db
from tests.contract.harness import call_route, canonical_dumps, hermetic_paths

EXPECTED_DIR = Path(__file__).resolve().parent / "expected" / "parts_db"

# (case_name, method, full_path, body)
CASES: list[tuple[str, str, str, dict]] = [
    ("root_doc", "GET", "/api/parts-db", {}),
    ("types", "GET", "/api/parts-db/types", {}),
    ("browse_tree", "GET", "/api/parts-db/browse-tree", {}),
    ("sections", "GET", "/api/parts-db/sections", {}),
    ("zones_all", "GET", "/api/parts-db/zones", {}),
    ("zones_by_section", "GET", "/api/parts-db/zones?section=exterior", {}),
    ("sub_zones", "GET", "/api/parts-db/sub-zones", {}),
    ("build_attributes", "GET", "/api/parts-db/build-attributes", {}),
    ("tags", "GET", "/api/parts-db/tags", {}),
    ("services", "GET", "/api/parts-db/services", {}),
    ("manufacturers", "GET", "/api/parts-db/manufacturers", {}),
    ("part_types_all", "GET", "/api/parts-db/part-types", {}),
    ("part_types_by_type", "GET", "/api/parts-db/part-types?type=lights", {}),
    ("part_type_one", "GET", "/api/parts-db/part-types/warning_light", {}),
    ("part_type_unknown", "GET", "/api/parts-db/part-types/does_not_exist", {}),
    ("part_type_products", "GET", "/api/parts-db/part-types/push_bumper/products", {}),
    ("products_all", "GET", "/api/parts-db/products", {}),
    ("product_one", "GET", "/api/parts-db/products/setina_pb400", {}),
    ("product_unknown", "GET", "/api/parts-db/products/does_not_exist", {}),
    ("product_part_numbers", "GET", "/api/parts-db/products/setina_pb400/part-numbers", {}),
    ("manifest_data", "GET", "/api/parts-db/manifest-data?part_type=Push Bumper", {}),
    ("manifest_data_missing_param", "GET", "/api/parts-db/manifest-data", {}),
    ("category_zones", "GET", "/api/parts-db/category-zones?type=lights&category=scene", {}),
    ("placements_non_lights", "GET", "/api/parts-db/placements?type=structural", {}),
    ("accessories", "GET", "/api/parts-db/accessories?product_id=setina_pb400", {}),
    ("accessories_missing_param", "GET", "/api/parts-db/accessories", {}),
    (
        "tracer_heads",
        "GET",
        "/api/parts-db/tracer-heads?product_id=whelen_2_lamp_tracer&mode=duo&secondary=white&lens=clear",
        {},
    ),
    ("category_skus", "GET", "/api/parts-db/category-skus?type=lights&category=scene", {}),
    (
        "category_skus_by_part_type",
        "GET",
        "/api/parts-db/category-skus?type=structural&part_type=console",
        {},
    ),
    ("category_locations_lights", "GET", "/api/parts-db/category-locations?type=lights&category=scene", {}),
    (
        "category_locations_non_lights",
        "GET",
        "/api/parts-db/category-locations?type=structural&product=setina_pb400",
        {},
    ),
    ("zone_products_by_type", "GET", "/api/parts-db/zone-products?type=structural", {}),
    ("zone_products_by_part_type", "GET", "/api/parts-db/zone-products?type=structural&part_type=push_bumper", {}),
    ("zone_products_grouped", "GET", "/api/parts-db/zone-products?type=lights&group=zone", {}),
    (
        "match_skus",
        "POST",
        "/api/parts-db/match-skus",
        {"product_id": "whelen_2_lamp_tracer", "heads": [], "lens": ""},
    ),
    (
        "resolve_selection",
        "POST",
        "/api/parts-db/resolve-selection",
        {
            "product_model": "PB400",
            "manufacturer_label": "Setina",
            "location": "Front",
            "base_name": "Push Bumper",
            "lens": "",
            "combos": [],
            "total_heads": 0,
        },
    ),
    (
        "validate_placement",
        "POST",
        "/api/parts-db/validate-placement",
        {"part_type_id": "push_bumper", "product_id": "setina_pb400", "location_id": ""},
    ),
]


@pytest.mark.parametrize("case_name,method,full_path,body", CASES, ids=[c[0] for c in CASES])
def test_parts_db_contract(case_name, method, full_path, body, tmp_path, request):
    paths = hermetic_paths(tmp_path)
    status, response_body, handled = call_route(route_parts_db, method, full_path, body, paths)

    recorded = canonical_dumps({"status": status, "handled": handled, "body": response_body})
    expected_path = EXPECTED_DIR / f"{case_name}.json"

    if request.config.getoption("--contract-record"):
        EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
        expected_path.write_text(recorded, "utf-8")
        pytest.skip(f"recorded {case_name}")

    assert expected_path.exists(), f"no recorded contract for {case_name} — run with --contract-record first"
    assert recorded == expected_path.read_text("utf-8"), (
        f"{case_name}: {method} {full_path} response contract changed — see the diff above"
    )
