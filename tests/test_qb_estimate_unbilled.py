"""Estimate generation skips parts tagged ``unbilled`` (agency-supplied)."""
from __future__ import annotations

import json
from types import SimpleNamespace

from dtm_buildsheet.app.services import qb_estimate_service, parts_db_service
from dtm_buildsheet.paths import AppPaths


def _part(part_number, name="X", qty=1, include=True):
    return SimpleNamespace(part_number=part_number, name=name, quantity=qty, include=include)


_DB = {
    "schema_version": 2, "types": {}, "sections": {}, "zones": {}, "sub_zones": {},
    "build_attributes": {}, "tags": {"unbilled": {"label": "Unbilled"}}, "manufacturers": {},
    "products": {
        "axon_cam": {"manufacturer_id": "axon", "model": "Fleet Camera", "tag_ids": ["unbilled"],
                     "part_numbers": [{"part_number": "CAM-1"}]},          # no QB id on purpose
        "whelen_ion": {"manufacturer_id": "whelen", "model": "ION", "tag_ids": [],
                       "part_numbers": [{"part_number": "ION-RW", "qb_item_id": "847", "qb_unit_price": 199.0}]},
    },
    "part_types": {}, "placements": {}, "placement_zones": {}, "services": {},
    "preference_filters": {}, "color_palette": {},
}


def test_unbilled_parts_are_skipped(tmp_path):
    parts_db_service.reset_for_testing()
    try:
        (tmp_path / "parts_db.json").write_text(json.dumps(_DB), "utf-8")
        paths = AppPaths(workspace_config_dir=tmp_path)
        draft = SimpleNamespace(parts=[_part("CAM-1", "Camera"), _part("ION-RW", "Forward Warning 1")])
        lines, problems = qb_estimate_service.resolve_build_lines(paths, draft)
        # The camera is agency-supplied (unbilled): no billable line AND no blocking problem.
        assert all(l["part_number"] != "CAM-1" for l in lines)
        assert all(p["part_number"] != "CAM-1" for p in problems)
        # The billable, QB-linked light still resolves.
        assert any(l["part_number"] == "ION-RW" for l in lines)
    finally:
        parts_db_service.reset_for_testing()
