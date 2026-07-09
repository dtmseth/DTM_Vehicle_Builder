"""Smoke-flow implementations (§8.1 Step 1c).

Each flow is a function ``flow(page, base_url)`` that drives one §3.1 flow
end to end and raises on any step failure. Console/network/netguard
assertions are made by the runner, not here — a flow only navigates and
interacts.

Feasibility-prototype status: ``tab_load`` and ``add_text_mode_equipment_part``
are implemented. The remaining flows are specified at step-and-selector level
in docs/audit/UI_SMOKE_SPEC.md §5 and land in the implementation session.
"""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

# Give slow panels (SKU grid renders ~900 products) time to fetch + render
# after a tab click before we move on. The implementation session should
# replace the fixed settle with per-panel readiness waits where flakiness
# appears; the prototype keeps it simple.
_SETTLE_MS = 400


def _api(base_url: str, path: str, body: dict | None = None, method: str | None = None) -> dict:
    """Minimal JSON HTTP helper for seeding fixture state before driving the
    browser — loopback-only (base_url is always 127.0.0.1), so it doesn't
    trip the hermetic netguard."""
    url = base_url + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        method = method or "POST"
    req = Request(url, data=data, headers=headers, method=method or "GET")
    with urlopen(req) as r:
        return json.loads(r.read())


def _seed_project_with_draft(base_url: str) -> tuple[str, str, str]:
    """Create a throwaway project + one PIU build unit + its draft. Returns
    (project_id, unit_id, draft_id)."""
    proj = _api(base_url, "/api/project/save", {
        "customer": {"name": "UI Smoke PD", "agency": "UI Smoke PD", "build_year": "2026"},
        "build_units": [{"vehicle_model": "PIU", "build_type": "Patrol"}],
    })
    project_id = proj["project_id"]
    detail = _api(base_url, f"/api/project/{project_id}")
    unit_id = detail["project"]["build_units"][0]["unit_id"]
    draft_resp = _api(base_url, f"/api/project/{project_id}/unit/{unit_id}/create-draft", {}, method="POST")
    return project_id, unit_id, draft_resp["draft_id"]


def _open_build_editor(page, base_url: str) -> None:
    page.goto(base_url, wait_until="load")
    page.click(".htab[data-tab='projects']")
    page.wait_for_selector(".proj-row-clickable")
    page.click(".proj-row-clickable")
    page.wait_for_selector("#proj-detail-view:not([hidden])")
    page.click("[data-ptab='builds']")
    page.wait_for_timeout(_SETTLE_MS)
    page.click(".proj-start-btn")
    page.wait_for_selector("#proj-build-editor:not([hidden])")
    page.wait_for_timeout(_SETTLE_MS)


def flow_tab_load(page, base_url: str) -> None:
    """Flow 1 — every tab/stab/inner-stab activates with zero console errors."""
    page.goto(base_url, wait_until="load")
    page.wait_for_selector(".htab[data-tab='projects']")

    # Projects
    page.click(".htab[data-tab='projects']")
    page.wait_for_selector("#tab-projects:not([hidden])")
    page.wait_for_timeout(_SETTLE_MS)

    # General Settings + its stabs
    page.click(".htab[data-tab='general-settings']")
    page.wait_for_selector("#stab-bar-general:not([hidden])")
    for stab in ("projects-defaults", "agencies", "sales-reps", "presets", "quickbooks"):
        page.click(f".stab[data-stab='{stab}']")
        page.wait_for_timeout(_SETTLE_MS)

    # Advanced Settings + its stabs (+ inner stabs for the two grouped ones)
    page.click(".htab[data-tab='advanced-settings']")
    page.wait_for_selector("#stab-bar-advanced:not([hidden])")

    page.click(".stab[data-stab='placements']")
    page.wait_for_selector("#inner-stab-bar-placements:not([hidden])")
    for inner in ("placements", "fixtures"):
        page.click(f".inner-stab[data-inner-stab='{inner}']")
        page.wait_for_timeout(_SETTLE_MS)

    page.click(".stab[data-stab='sizes']")
    page.wait_for_timeout(_SETTLE_MS)

    page.click(".stab[data-stab='part-manager']")
    page.wait_for_selector("#inner-stab-bar-part-manager:not([hidden])")
    for inner in ("sku-grid", "parts-db", "catalog", "parts"):
        page.click(f".inner-stab[data-inner-stab='{inner}']")
        page.wait_for_timeout(_SETTLE_MS)

    page.click(".stab[data-stab='vehicles']")
    page.wait_for_timeout(_SETTLE_MS)
    page.click(".stab[data-stab='workbook-tools']")
    page.wait_for_timeout(_SETTLE_MS)

    # Let any in-flight fetches finish so their errors (if any) are captured.
    page.wait_for_load_state("networkidle")


def flow_add_text_mode_equipment_part(page, base_url: str) -> None:
    """LEDGER.md FINDING-004 regression guard: a part_type with zero curated
    location options (e.g. `console`) must get a real, sequenceable name from
    the picker's free-text location branch — never the literal "Part" (which
    the planner can't match to any part_type and reports as "Unmapped")."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    def add_console_part():
        page.click("[onclick='addPart()'] >> nth=0")
        page.wait_for_selector("#picker-panel.open")
        page.wait_for_timeout(200)
        page.click("button.pf-pill.pf-big:has-text('Equipment')")
        page.wait_for_timeout(_SETTLE_MS)
        # Gamber Johnson PIU low-profile console box — `console` part_type,
        # zero curated location_options (the exact FINDING-004 repro).
        page.fill("#pf-search", "7170-0734-00")
        page.wait_for_timeout(_SETTLE_MS)
        page.click(".pp-head >> nth=0")
        page.wait_for_timeout(200)
        page.click(".pp-sku [data-pick] >> nth=0")
        page.wait_for_timeout(200)
        page.click("#picker-tab-btn-location")
        page.wait_for_timeout(_SETTLE_MS)
        page.wait_for_selector("#picker-loc-text")
        page.fill("#picker-loc-text", "Front console mount")
        page.wait_for_timeout(200)
        page.click("#picker-add-btn")
        page.wait_for_timeout(_SETTLE_MS)

    add_console_part()
    add_console_part()   # second add must sequence ("Console 2"), not duplicate

    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    names = [p["name"] for p in draft["draft"]["parts"]]
    assert names == ["Console 1", "Console 2"], f"expected sequenced Console names, got {names}"

    plan = page.evaluate(
        "(id) => fetch('/api/preview/plan', {method:'POST', headers:{'Content-Type':'application/json'}, "
        "body: JSON.stringify({draft_id: id})}).then(r => r.json())",
        draft_id,
    )
    assert not plan.get("warnings"), f"expected no plan warnings, got {plan.get('warnings')}"


FLOWS = {
    "tab_load": flow_tab_load,
    "add_text_mode_equipment_part": flow_add_text_mode_equipment_part,
    # Implementation session (UI_SMOKE_SPEC.md §5):
    # "part_picker": flow_part_picker,
    # "manifest_add_remove": flow_manifest_add_remove,
    # "sku_grid_roundtrip": flow_sku_grid_roundtrip,
    # "project_open_edit_save": flow_project_open_edit_save,
    # "cloud_status_offline": flow_cloud_status_offline,
}
