"""Smoke-flow implementations (§8.1 Step 1c).

Each flow is a function ``flow(page, base_url)`` that drives one §3.1 flow
end to end and raises on any step failure. Console/network/netguard
assertions are made by the runner, not here — a flow only navigates and
interacts.

Feasibility-prototype status: only ``tab_load`` is implemented. The other
five flows are specified at step-and-selector level in
docs/audit/UI_SMOKE_SPEC.md §5 and land in the implementation session.
"""

from __future__ import annotations

# Give slow panels (SKU grid renders ~900 products) time to fetch + render
# after a tab click before we move on. The implementation session should
# replace the fixed settle with per-panel readiness waits where flakiness
# appears; the prototype keeps it simple.
_SETTLE_MS = 400


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


FLOWS = {
    "tab_load": flow_tab_load,
    # Implementation session (UI_SMOKE_SPEC.md §5):
    # "part_picker": flow_part_picker,
    # "manifest_add_remove": flow_manifest_add_remove,
    # "sku_grid_roundtrip": flow_sku_grid_roundtrip,
    # "project_open_edit_save": flow_project_open_edit_save,
    # "cloud_status_offline": flow_cloud_status_offline,
}
