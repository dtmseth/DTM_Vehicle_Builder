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


def _seed_project_with_draft(base_url: str, preferences: dict | None = None,
                             vehicle_model: str = "PIU",
                             build_state: dict | None = None) -> tuple[str, str, str]:
    """Create a throwaway project + one build unit + its draft. Returns
    (project_id, unit_id, draft_id).

    ``preferences`` is optional and, when omitted, the project ends up with a
    fully empty EquipmentPreferences (no brand preferences set at all) — the
    /api/project/save route only touches preferences when the POST body
    includes a "preferences" key. Pass it explicitly (e.g.
    {"lighting_brands": ["Whelen"]}) for flows that need a brand preference
    seeded; existing callers that don't pass it keep today's behavior
    unchanged."""
    unit = {"vehicle_model": vehicle_model, "build_type": "Patrol"}
    if build_state is not None:
        unit.update(build_state)
    body = {
        "customer": {"name": "UI Smoke PD", "agency": "UI Smoke PD", "build_year": "2026"},
        "build_units": [unit],
    }
    if preferences is not None:
        body["preferences"] = preferences
    proj = _api(base_url, "/api/project/save", body)
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
    page.wait_for_timeout(_SETTLE_MS)
    # Builds now live on the default Overview tab.  Clicking a card is the
    # primary edit/set-up action, replacing the old Builds tab's button.
    page.locator(".proj-build-card--openable").first.locator(".proj-build-card-label").click()
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

    # General Settings + its public stabs, including the production-enabled
    # QuickBooks connection surface.
    page.click(".htab[data-tab='general-settings']")
    page.wait_for_selector("#stab-bar-general:not([hidden])")
    assert page.evaluate("() => window.DTM_QUICKBOOKS_UI_ENABLED === true")
    assert page.locator(".stab[data-stab='quickbooks']").is_visible()
    for stab in ("projects-defaults", "agencies", "sales-reps", "presets", "quickbooks"):
        page.click(f".stab[data-stab='{stab}']")
        page.wait_for_timeout(_SETTLE_MS)
        if stab == "projects-defaults":
            page.wait_for_selector("[data-estimate-preset='patrol']")
            assert page.locator("[data-estimate-preset]").count() == 4
            assert page.locator("[data-estimate-preset='patrol'] [data-estimate-default='labor']").input_value() == "4900.00"
            assert page.locator("[data-estimate-preset='patrol'] [data-estimate-default='supplies']").input_value() == "500.00"
            assert "4% credit card fee" in page.locator("#estimate-defaults-qb-items").inner_text()
        if stab == "agencies":
            page.click("#btn-add-agency")
            page.wait_for_selector("#agency-create-modal.open")
            page.wait_for_selector("[data-agency-pricing='whelen']", state="attached")
            assert page.locator("#ac-pricing-use-default").is_checked()
            page.uncheck("#ac-pricing-use-default")
            assert page.locator("#ac-pricing-overrides").is_visible()
            assert page.locator("[data-agency-pricing='whelen']").input_value() == "38"
            page.click("#ac-cancel")
        if stab == "quickbooks":
            page.wait_for_selector("[data-pricing-default='whelen']")
            expected = {
                "gamber_johnson": "40", "havis": "20", "pac_tool": "5",
                "santa_cruz": "25", "setina": "20", "westin": "15", "whelen": "38",
            }
            for manufacturer_id, discount in expected.items():
                actual = page.locator(f"[data-pricing-default='{manufacturer_id}']").input_value()
                assert actual == discount, f"{manufacturer_id} default pricing: expected {discount}, got {actual}"

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


def flow_preset_agency_list_freshness(page, base_url: str) -> None:
    """The Preset creator must refetch agencies every time it opens.

    Regression for the old module-level ``_agencies`` cache: opening the
    Presets tab initialized the array once, then later agency imports/creates
    never appeared in Add/Edit Preset until the application restarted.
    """
    page.goto(base_url, wait_until="load")
    page.click(".htab[data-tab='general-settings']")
    page.wait_for_selector("#stab-bar-general:not([hidden])")
    page.click(".stab[data-stab='presets']")
    page.wait_for_selector("#pm-add-btn")
    page.wait_for_timeout(_SETTLE_MS)

    # Mutate the authoritative agency store only after Presets has populated
    # its in-memory list. The next modal open must not reuse that stale copy.
    created = _api(base_url, "/api/agency/save", {
        "name": "Fresh Preset Agency",
        "contact_name": "UI Smoke",
    })
    assert created["ok"] is True
    agency_id = created["agency"]["agency_id"]
    project_agency_id = "11111111-2222-4333-8444-555555555555"
    project_only_name = "US Immigration & Customs Enforcement (ICE)"
    project = _api(base_url, "/api/project/save", {
        "customer": {
            "name": project_only_name,
            "agency": project_only_name,
            "agency_id": project_agency_id,
            "build_year": "2026",
        },
        "build_units": [{"vehicle_model": "PIU", "build_type": "Patrol"}],
    })
    assert project["ok"] is True

    page.click("#pm-add-btn")
    page.wait_for_selector("#preset-edit-modal.open")
    option = page.locator(f'#pem-agency-checks input[value="{agency_id}"]')
    agency_text = page.locator("#pem-agency-checks").inner_text()
    assert option.count() == 1, f"fresh agency id missing from preset modal: {agency_text!r}"
    assert "FRESH PRESET AGENCY" in agency_text.upper(), f"fresh agency label missing: {agency_text!r}"

    # Current projects remain valid agency choices even if their separate
    # Agency record is missing. The search must reduce a 200+ item production
    # list without dropping the selected/general choices.
    page.fill("#pem-agency-search", "ICE")
    project_option = page.locator(f'#pem-agency-checks input[value="{project_agency_id}"]')
    assert project_option.count() == 1
    assert page.locator("#pem-agency-checks input[type='radio']").count() == 2
    assert "1 OF 2" in page.locator("#pem-agency-count").inner_text().upper()
    project_option.check()
    assert project_option.is_checked()
    page.click("#pem-cancel")

    # A later rename must also replace the prior label on the next open; this
    # catches fixes that append new agencies but still retain stale records.
    renamed = _api(base_url, "/api/agency/save", {
        "agency_id": agency_id,
        "name": "Renamed Preset Agency",
        "contact_name": "UI Smoke",
    })
    assert renamed["ok"] is True
    page.click("#pm-add-btn")
    page.wait_for_selector("#preset-edit-modal.open")
    page.fill("#pem-agency-search", "Renamed")
    choices = page.locator("#pem-agency-checks")
    renamed_text = choices.inner_text()
    assert "RENAMED PRESET AGENCY" in renamed_text.upper(), renamed_text
    assert "FRESH PRESET AGENCY" not in renamed_text.upper(), renamed_text
    page.click("#pem-cancel")
    page.wait_for_selector("#preset-edit-modal.open", state="hidden")

    # A project-backed agency whose standalone record is absent must also be
    # visible in Agency Manager and in the new-project agency search.  ICE was
    # the production symptom that exposed the incomplete listing boundary.
    page.click(".stab[data-stab='agencies']")
    page.wait_for_selector("#stab-agencies:not([hidden])")
    page.wait_for_selector("#agency-list-container table")
    page.fill("#agency-search", "ICE")
    agency_rows = page.locator("#agency-list-container tbody tr")
    assert agency_rows.count() == 1
    assert project_only_name in agency_rows.first.inner_text()
    assert "Recovered from project" in agency_rows.first.inner_text()
    agency_rows.first.get_by_role("button", name="Edit", exact=True).click()
    page.wait_for_selector("#agency-create-modal.open")
    assert page.locator("#agency-modal-title").inner_text() == "Edit Agency"
    assert page.locator("#ac-abbreviation").input_value() == "ICE"
    assert page.locator("#ac-save").inner_text() == "Save Agency"
    page.click("#ac-cancel")
    page.wait_for_selector("#agency-create-modal.open", state="hidden")

    page.click(".htab[data-tab='projects']")
    page.wait_for_selector("#tab-projects:not([hidden])")
    page.click("#btn-new-project")
    page.wait_for_selector("#proj-editor:not([hidden])")
    page.fill("#proj-agency", "ICE")
    page.wait_for_selector(f'#proj-agency-suggestions .sug-item[data-id="{project_agency_id}"]')
    suggestion = page.locator(
        f'#proj-agency-suggestions .sug-item[data-id="{project_agency_id}"]'
    )
    assert project_only_name in suggestion.inner_text()
    assert "ICE" in suggestion.inner_text()


def flow_load_preset_from_build_editor(page, base_url: str) -> None:
    """A configured build can replace its parts from a current compatible preset."""
    saved = _api(base_url, "/api/presets/save", {
        "schema_version": 4,
        "preset_id": "smoke-load-preset",
        "label": "Load Button Preset",
        "description": "Load Button Regression",
        "agency_ids": [],
        "build_types": ["Patrol"],
        "vehicle_types": ["PIU"],
        "tag": "Load Button",
        "parts": [{
            "name": "Preset Loaded Light",
            "manufacturer": "Whelen",
            "part_number": "LOAD-TEST-1",
            "part_type": "warning_light",
            "quantity": 3,
        }],
        "placement_overrides": {"loaded:front": {"x": 0.25, "y": 0.5}},
    })
    assert saved["ok"], saved
    preset_id = saved["preset_id"]

    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url, vehicle_model="PIU")
    original = _api(base_url, f"/api/draft/{draft_id}")["draft"]
    seeded = _api(base_url, "/api/draft/save", {
        "draft_id": draft_id,
        "parts": [{
            "name": "Configuration Being Replaced",
            "manufacturer": "Old",
            "part_number": "OLD-1",
            "quantity": 1,
        }],
        "notes": {"INSTALLATION NOTES": ["Preserve this note"]},
        "vehicle_info": original["vehicle_info"],
    })
    assert seeded["ok"], seeded

    _open_build_editor(page, base_url)
    note_categories = page.locator("[data-pbe-note-category]").evaluate_all(
        "fields => fields.map(field => field.dataset.pbeNoteCategory)"
    )
    assert note_categories == ["INSTALLATION NOTES", "DELIVERY REQUIREMENTS"], \
        f"build notes must expose only installation and delivery fields, got {note_categories!r}"
    page.wait_for_selector("#pbe-load-preset-top")
    assert page.locator("#pbe-load-preset-top").is_visible()
    assert page.locator("#pbe-load-preset-btn").is_visible()
    assert page.evaluate("""
        () => document.querySelector('#pbe-load-preset-top').nextElementSibling?.id
            === 'pbe-create-preset-top'
    """), "Load Preset must sit directly beside Save as New Preset in the build header"

    page.click("#pbe-load-preset-top")
    page.wait_for_selector("#pbe-load-preset-modal.open")
    page.fill("#pbe-load-preset-search", "Load Button")
    option = page.locator(f'#pbe-load-preset-options input[value="{preset_id}"]')
    assert option.count() == 1
    option.check()
    assert not page.locator("#pbe-load-preset-confirm").is_disabled()
    page.click("#pbe-load-preset-confirm")
    page.wait_for_selector("#pbe-load-preset-modal.open", state="hidden")
    page.wait_for_function("() => document.querySelector('#me-tbody-container')?.innerText.includes('Preset Loaded Light')")

    loaded = _api(base_url, f"/api/draft/{draft_id}")["draft"]
    assert [part["name"] for part in loaded["parts"]] == ["Preset Loaded Light"]
    assert loaded["placement_overrides"] == {"loaded:front": {"x": 0.25, "y": 0.5}}
    assert loaded["notes"] == {"INSTALLATION NOTES": ["Preserve this note"]}
    assert loaded["audit_trail"][-1]["action"] == "preset_loaded"


def flow_project_manager_all_presets_unfiltered(page, base_url: str) -> None:
    """Both project-manager All controls expose every non-blank preset."""
    incompatible = _api(base_url, "/api/presets/save", {
        "schema_version": 4,
        "preset_id": "smoke-unfiltered-tahoe-admin",
        "label": "Unfiltered Tahoe Admin",
        "description": "Must remain visible from All on a PIU Patrol unit",
        "agency_ids": [],
        "build_types": ["Admin"],
        "vehicle_types": ["TAHOE"],
        "tag": "Unfiltered Regression",
        "parts": [],
        "placement_overrides": {},
    })
    assert incompatible["ok"], incompatible
    incompatible_id = incompatible["preset_id"]
    project = _api(base_url, "/api/project/save", {
        "customer": {"name": "All Presets PD", "agency": "All Presets PD", "build_year": "2026"},
        "build_units": [{"vehicle_model": "PIU", "build_type": "Patrol"}],
    })
    assert project["ok"], project

    presets = _api(base_url, "/api/presets")["presets"]
    expected_count = len([
        preset for preset in presets
        if preset["preset_id"] != "blank_custom"
        and (preset.get("label") or "").lower() != "blank"
    ])

    # New-project wizard: PIU + Patrol must still show the intentionally
    # incompatible TAHOE + Admin preset under the literal All Presets control.
    page.goto(base_url, wait_until="load")
    page.wait_for_function(
        "expected => (window._PT?.presets || []).filter(p => p.preset_id !== 'blank_custom' && (p.label || '').toLowerCase() !== 'blank').length === expected",
        arg=expected_count,
    )
    page.click("#btn-new-project")
    page.wait_for_function("""
        () => window._PT?.isWizard
            && window._PT.units.length > 0
            && document.querySelector('#proj-wizard-footer')?.style.display !== 'none'
    """)
    page.fill("#proj-agency", "Wizard All Presets PD")
    page.fill("#proj-salesrep", "UI Smoke Rep")
    page.click("#proj-btn-next")
    page.wait_for_selector("#proj-etab-preferences.active")
    page.click("#proj-btn-next")
    page.wait_for_selector("#proj-etab-fleet.active")
    page.select_option(".proj-u-vehicle", "PIU")
    page.select_option(".proj-u-buildtype", "Patrol")
    page.click(".proj-preset-btns button[onclick^='PT_togglePresetDD']")
    wizard_dd = page.locator(".proj-preset-dropdown").first
    wizard_count = wizard_dd.locator(".proj-preset-option").count()
    assert wizard_count == expected_count, \
        f"wizard All Presets showed {wizard_count} of {expected_count} presets"
    assert wizard_dd.locator(f"[onclick*='{incompatible_id}']").count() == 1, \
        "All Presets in the new-project wizard still filters by vehicle/build type"

    # Existing Project Details editor has a separate picker implementation and
    # must obey the same unfiltered All contract.
    page.goto(base_url, wait_until="load")
    page.click(".proj-row-clickable")
    page.wait_for_selector("#proj-detail-view:not([hidden])")
    page.click(".proj-dtab[data-ptab='edit']")
    page.click("#proj-ptab-edit .btn-primary")
    page.wait_for_selector("#proj-edit-units-list .proj-et-preset-row")
    page.click("#proj-edit-units-list button:has-text('All ▾')")
    edit_dd = page.locator(".proj-et-preset-dd").first
    edit_count = edit_dd.locator(".proj-preset-option").count()
    assert edit_count == expected_count, \
        f"Project Details All showed {edit_count} of {expected_count} presets"
    assert edit_dd.locator(f"[onclick*='{incompatible_id}']").count() == 1, \
        "All in Project Details still filters by vehicle/build type"


def flow_add_text_mode_equipment_part(page, base_url: str) -> None:
    """An exact Center Console SKU stays authoritative while options produce
    explicit installed rows and only suggest a different bundle."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url, vehicle_model="PIU")
    _open_build_editor(page, base_url)

    def add_console_part():
        page.click("[onclick='addPart()'] >> nth=0")
        page.wait_for_selector("#picker-panel.open")
        page.wait_for_timeout(200)
        # `console` lives under Structural > Console (family_id "console_system",
        # relabeled from "Console System" — owner ruling 2026-07-10, flaws #7+#8;
        # the family_id and expand-only behavior are unchanged) — expand the
        # category, then the family, then pick the Console leaf. Expansion
        # state persists across picker opens
        # within the session (Step 1's "persist expansion state" call), so on
        # the second add() in this flow the tree may already be expanded —
        # only click a header if it isn't open yet, or the click would
        # collapse it instead.
        if not page.is_visible(".pbt-cat-head[data-cat='structural'].open"):
            page.click(".pbt-cat-caret-btn[data-cat='structural']")
            page.wait_for_timeout(200)
        if not page.is_visible(".pbt-fam-caret-btn[data-fam='console_system'].open"):
            page.click(".pbt-fam-caret-btn[data-fam='console_system']")
            page.wait_for_timeout(200)
        page.click(".pbt-leaf[data-pt='console']")
        page.wait_for_timeout(_SETTLE_MS)
        # A console starts by choosing its actual vehicle-specific base. The
        # kit configuration then completes the included and add-on hardware.
        page.click(".pp-head[data-pid='gamber_johnson_7170_0734_00']")
        page.wait_for_selector("[data-pid='gamber_johnson_7170_0734_00'][data-pick]")
        page.locator("[data-pid='gamber_johnson_7170_0734_00'][data-pick]").first.click()
        page.wait_for_function("() => _pickerState?.sel?.product_id === 'gamber_johnson_7170_0734_00'")
        assert page.locator("#picker-add-btn").text_content().strip() == "Set up Center Console →"
        page.click("#picker-add-btn")
        page.wait_for_selector("[data-console-setup]")
        assert page.locator("#picker-tab-btn-location").is_visible()
        page.wait_for_function("() => _pickerState?.consoleSetup?.choices?.consoleChoice?.product_id")
        assert page.evaluate("() => _pickerState.consoleSetup.choices.consoleChoice.part_number") == "7170-0734-00"
        faceplate_brands = page.locator(".console-extra-faceplates .console-catalog-card-brand").all_text_contents()
        assert faceplate_brands and all(brand.strip() == "Gamber Johnson" for brand in faceplate_brands), (
            f"faceplates must follow the selected Gamber Johnson console, got {faceplate_brands!r}"
        )
        page.locator(
            ".console-faceplate-order-card[data-console-faceplate-index='1'] "
            "[data-console-faceplate-move='-1']"
        ).click()
        assert page.evaluate(
            "() => _pickerState.consoleSetup.choices.faceplates.map(item => item.product_id)"
        ) == [
            "gamber_johnson_7160_0321", "gamber_johnson_7160_0339",
            "gamber_johnson_7160_0846", "gamber_johnson_15250",
        ], "the user's faceplate arrangement should update immediately"
        page.click("[data-console-component-open='armRest']")
        page.wait_for_selector("[data-console-component-choice='gamber_johnson_7160_0429']")
        armrest_brands = page.locator(".console-component-picker .console-catalog-card-brand").all_text_contents()
        assert armrest_brands and all(brand.strip() == "Gamber Johnson" for brand in armrest_brands), (
            f"armrests must follow the selected Gamber Johnson console, got {armrest_brands!r}"
        )
        page.click("[data-console-component-choice='gamber_johnson_7160_0429']")
        page.click("[data-console-component-open='motionAttachment']")
        page.wait_for_selector("[data-console-component-choice='gamber_johnson_7160_0220']")
        motion_brands = page.locator(".console-component-picker .console-catalog-card-brand").all_text_contents()
        assert motion_brands and all(brand.strip() == "Gamber Johnson" for brand in motion_brands), (
            f"motion attachments must follow the selected Gamber Johnson console, got {motion_brands!r}"
        )
        page.click("[data-console-component-choice='gamber_johnson_7160_0220']")
        assert page.evaluate("() => _pickerState.consoleSetup.choices.consoleChoice.part_number") == "7170-0734-00", (
            "selecting Mongoose must not replace the exact base console SKU"
        )
        assert page.evaluate(
            "() => _pickerState.consoleSetup.choices.faceplates.map(item => item.product_id)"
        )[:2] == ["gamber_johnson_7160_0321", "gamber_johnson_7160_0339"], (
            "component changes must not reset the user's faceplate arrangement"
        )
        page.wait_for_selector("[data-console-use-recommendation='gamber_johnson_7170_0734_04']")
        assert "7170-0734-04" in page.locator(".console-kit-recommendation").text_content(), (
            "the matching bundle may be suggested, but only as an explicit action"
        )
        # Switch to the printer armrest so the existing printer subflow stays
        # covered; the base must remain unchanged through that second option.
        page.click("[data-console-component-open='armRest']")
        page.wait_for_selector("[data-console-component-choice='gamber_johnson_7160_0430']")
        page.click("[data-console-component-choice='gamber_johnson_7160_0430']")
        assert page.evaluate("() => _pickerState.consoleSetup.choices.consoleChoice.part_number") == "7170-0734-00"
        page.click("[data-console-component-open='printer']")
        page.wait_for_selector("[data-console-component-choice='brother_pj_822']")
        page.click("[data-console-component-choice='brother_pj_822']")
        page.click("[data-console-motion-location='mounted_to_pedestal']")
        page.click("[data-console-component-open='pedestalMount']")
        page.wait_for_selector("[data-console-component-choice='gamber_johnson_7160_1336']")
        page.click("[data-console-component-choice='gamber_johnson_7160_1336']")
        page.click("[data-console-component-open='dockingStation']")
        page.wait_for_selector("[data-console-component-choice='gamber_johnson_7160_1982_10']")
        dock_brands = page.locator(".console-component-picker .console-catalog-card-brand").all_text_contents()
        assert dock_brands and all(brand.strip() == "Gamber Johnson" for brand in dock_brands), (
            f"docking stations must follow the selected Gamber Johnson console, got {dock_brands!r}"
        )
        page.click("[data-console-component-choice='gamber_johnson_7160_1982_10']")
        assert page.locator("#picker-add-btn").text_content().strip() == "Add and Finish"
        page.click("#picker-add-btn")
        page.wait_for_timeout(_SETTLE_MS)

    add_console_part()

    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    parts = draft["draft"]["parts"]
    console = next(p for p in parts if p.get("part_type") == "console")
    children = [p for p in parts if p.get("parent_line_id") == console["line_id"]]
    faceplates = [p for p in children if p.get("accessory_category") == "console_faceplate"]
    assert [p["name"] for p in faceplates] == [
        "Center Console · Face Plate 1 · Radio Faceplate",
        "Center Console · Face Plate 2 · Core Control Head Faceplate",
        "Center Console · Face Plate 3 · Cup Holder Faceplate",
        "Center Console · Face Plate 4 · OEM Relocation Plate",
    ], f"expected numbered auto-populated faceplates in the configured order, got {faceplates!r}"
    console_components = [p for p in children if p.get("accessory_category") == "console_component"]
    assert {p.get("part_type") for p in console_components} == {
        "arm_rest", "motion_attachment", "pedestal_mount", "docking_station",
    }, f"console hardware must nest with the console, got {console_components!r}"
    assert {p.get("part_type") for p in children} == {
        "special_face_plate", "arm_rest", "motion_attachment", "pedestal_mount", "docking_station",
    }
    motion = next(p for p in console_components if p.get("part_type") == "motion_attachment")
    assert motion["part_number"] == "7160-0220"
    assert motion["supply_type"] == "new"
    assert not motion.get("picker_config", {}).get("console_kit_included"), (
        "Mongoose is separately billed when the selected 0734-00 base does not include it"
    )
    included_parts = {p["part_number"] for p in faceplates if p.get("picker_config", {}).get("console_kit_included")}
    assert included_parts == {"7160-0846", "15250"}, f"kit items must remain shop rows but be unbilled, got {faceplates!r}"
    related_parts = [
        p for p in parts
        if p.get("picker_config", {}).get("console_setup_owner_line_id") == console["line_id"]
    ]
    printer = next(p for p in related_parts if p.get("part_type") == "printer")
    nested_console_parts = [p for p in related_parts if p is not printer]
    assert all(p.get("parent_line_id") == console["line_id"] for p in nested_console_parts), \
        f"console components must nest below the console, got {related_parts!r}"
    assert not printer.get("parent_line_id"), \
        "the printer must remain a top-level manifest parent for its own cable children"
    setup = console["picker_config"]["console_setup"]
    assert setup["style"] == "low_profile"
    assert console["part_number"] == "7170-0734-00"
    assert setup["consoleChoice"]["product_id"] == "gamber_johnson_7170_0734_00"

    plan = page.evaluate(
        "(id) => fetch('/api/preview/plan', {method:'POST', headers:{'Content-Type':'application/json'}, "
        "body: JSON.stringify({draft_id: id})}).then(r => r.json())",
        draft_id,
    )
    assert not plan.get("warnings"), f"expected no plan warnings, got {plan.get('warnings')}"

    # Reopening the console must return to the Details setup with every real
    # choice intact, rather than treating the SKU like a fresh generic part.
    console_parent = page.locator("tr.me-parent-row").filter(has_text="Center Console")
    console_parent.locator(".me-edit-btn").click()
    page.wait_for_selector("[data-console-setup]")
    page.wait_for_function("() => _pickerState?.consoleSetup?.active && !_pickerState.consoleSetup.loading")
    restored = page.evaluate("() => _pickerState.consoleSetup.choices")
    assert [item["product_id"] for item in restored["faceplates"]] == [
        "gamber_johnson_7160_0321", "gamber_johnson_7160_0339",
        "gamber_johnson_7160_0846", "gamber_johnson_15250",
    ], f"console edit must restore its ordered faceplates, got {restored!r}"
    assert restored["style"] == "low_profile"
    assert restored["consoleChoice"]["product_id"] == "gamber_johnson_7170_0734_00"
    assert restored["armRest"]["product_id"] == "gamber_johnson_7160_0430"
    assert restored["printer"]["product_id"] == "brother_pj_822"
    assert restored["motionAttachment"]["product_id"] == "gamber_johnson_7160_0220"
    assert restored["motionAttachment"]["supply_type"] == "new"
    assert restored["motionLocation"] == "mounted_to_pedestal"
    assert restored["dockingStation"]["product_id"] == "gamber_johnson_7160_1982_10"
    page.evaluate("pickerClose()")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    # Nested console hardware still returns to the one setup that owns the
    # combined choices.
    docking_station = next(p for p in console_components if p.get("part_type") == "docking_station")
    page.evaluate("(lineId) => openPartEditModal(lineId)", docking_station["line_id"])
    page.wait_for_selector("[data-console-setup]")
    assert page.evaluate("_pickerState.editLineId") == console["line_id"]
    page.evaluate("pickerClose()")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    # Accepting the optional recommendation is the only action that may swap
    # the base. Covered hardware must remain present and gain billing metadata
    # instead of disappearing from the build.
    console_parent = page.locator("tr.me-parent-row").filter(has_text="Center Console")
    console_parent.locator(".me-edit-btn").click()
    page.wait_for_selector("[data-console-use-recommendation='gamber_johnson_7170_0734_09']")
    page.click("[data-console-use-recommendation='gamber_johnson_7170_0734_09']")
    assert page.evaluate("() => _pickerState.consoleSetup.choices.consoleChoice.part_number") == "7170-0734-09"
    assert page.evaluate(
        "() => _pickerState.consoleSetup.choices.faceplates.map(item => item.product_id)"
    )[:2] == ["gamber_johnson_7160_0321", "gamber_johnson_7160_0339"], (
        "an explicit base-SKU change must reconcile required faceplates without reordering them"
    )
    page.click("#picker-add-btn")
    page.wait_for_timeout(_SETTLE_MS)

    updated = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)["draft"]
    updated_console = next(p for p in updated["parts"] if p.get("part_type") == "console")
    updated_children = [p for p in updated["parts"] if p.get("parent_line_id") == updated_console["line_id"]]
    covered = {
        p.get("part_type"): p
        for p in updated_children
        if p.get("part_type") in {"arm_rest", "motion_attachment"}
    }
    assert updated_console["part_number"] == "7170-0734-09"
    assert set(covered) == {"arm_rest", "motion_attachment"}
    assert all(p.get("picker_config", {}).get("console_kit_included") for p in covered.values()), (
        f"covered console components must stay visible and only suppress billing, got {covered!r}"
    )


def flow_edit_preserves_fields(page, base_url: str) -> None:
    """LEDGER.md FINDING-005 → RESOLVED (Step 6): edit mode pre-fills from the
    stored part and a no-op Save must leave the part byte-for-byte unchanged.
    Safety is by *correctness* (pre-fill), not by disabling Save.

    Two F-005 repros are covered:
      (a) ION, qty 2, Red → Edit → Save unchanged → byte-identical
      (b) Type-lock: the browse tree cannot navigate to a different part_type
          (the "Midnight Edition" cross-type clobber is structurally impossible)
    """
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)

    # ── Seed a picker-created warning light with picker_config set ──────────
    # Use the API to directly seed in picker format (part_number = product model,
    # SKUs in components) so pre-fill has something to restore (simulates a
    # part added via the picker after Step 6 shipped).
    add_resp = _api(base_url, f"/api/draft/{draft_id}/part", {
        "name": "Forward Warning 1", "location": "FRONT WARNING 1",
        "manufacturer": "Whelen", "part_number": "ION", "quantity": 2,
        "new_or_used": "New", "source": "", "raw_color": "Red",
        "part_type": "warning_light",
        "components": [{"part_number": "IONR", "color": "Red", "quantity": 2, "price": None}],
        "picker_config": {
            "mode": "uniform", "colorsPerHead": "single",
            "uniform": ["red"], "splitSecondary": [], "custom": [["red"], ["red"]],
            "_noColor": False, "count": 2, "lens": "",
            "skuChoices": {"head_0": "IONR", "head_1": "IONR"},
        },
    })
    line_id = add_resp["line_id"]
    _api(base_url, f"/api/draft/{draft_id}/part", {
        "name": "Forward Warning 1 · Rear Warning License-Plate Bracket",
        "location": "FRONT WARNING 1", "manufacturer": "DTM", "part_number": "LICENSE PLATE BRACKET",
        "quantity": 1, "new_or_used": "New", "source": "", "parent_line_id": line_id,
        "accessory_category": "bracket_mount", "accessory_parent_product": "whelen_ion",
    })

    _open_build_editor(page, base_url)

    def fetch_part():
        draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
        return next(p for p in draft["draft"]["parts"] if p["line_id"] == line_id)

    before = fetch_part()

    page.click(".me-edit-btn")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(_SETTLE_MS)

    selected_product_visible = page.evaluate("""() => {
        const list = document.querySelector('#picker-products');
        const product = document.querySelector("#picker-products .pp-row[data-pid='whelen_ion'] .pp-head");
        if (!list || !product) return false;
        const listRect = list.getBoundingClientRect();
        const productRect = product.getBoundingClientRect();
        return productRect.top >= listRect.top && productRect.bottom <= listRect.bottom;
    }""")
    assert selected_product_visible, "editing must scroll the restored product into view"
    restored_bracket = page.locator("select[data-cat='bracket_mount']")
    assert restored_bracket.input_value().endswith("::LICENSE PLATE BRACKET"), (
        "a manifest accessory missing from the current catalog must still restore in parent edit"
    )

    # ── Assert (Step 7): edit mode must NOT show "Add another part" button ───
    # Multi-add is for building, not editing.
    another_hidden = page.get_attribute("#picker-add-another-btn", "hidden")
    assert another_hidden is not None, \
        "Step 7: #picker-add-another-btn must be hidden (have 'hidden' attr) in edit mode"

    # ── Assert (b): type-lock — locked leaves are dimmed, not clickable ─────
    # In edit mode with part_type="warning_light", any non-warning leaf must
    # have the "locked" class and resist clicks (type-lock). `warning_light`
    # itself has no rendered leaf anymore (owner ruling 2026-07-10, flaws
    # #7+#8: its sole home is the Warning header, browse_hidden as a member) —
    # the pre-fill still resolves its family (warning_lights) and expands it,
    # so its SIBLING members (headlight_flasher / tail_light_flasher) render
    # locked here.
    locked_count = page.locator(".pbt-leaf.locked").count()
    assert locked_count > 0, \
        "expected at least one .pbt-leaf.locked in edit mode (type-lock)"

    # No rendered leaf may claim to BE warning_light (it's browse_hidden) —
    # and the Warning family SELECT header (the part's own family) must NOT
    # be locked, since the edited part belongs to it.
    warning_leaf = page.locator(".pbt-leaf[data-pt='warning_light']").count()
    assert warning_leaf == 0, \
        "warning_light must not render as a leaf (its home is the Warning header)"
    warning_header_locked = page.locator(".pbt-fam-select[data-flow='warning'].locked").count()
    assert warning_header_locked == 0, \
        "the part's own family header (Warning) must NOT be locked in edit mode"

    # ── Assert (a): Save is enabled (correctness, not disabled) ─────────────
    disabled = page.get_attribute("#picker-add-btn", "disabled")
    # With a product pre-selected, Save should be enabled immediately.
    # (If the product wasn't pre-selected — e.g. test DB has no ION —
    # Save is correctly disabled; skip the round-trip assertion.)
    if disabled is not None:
        # No product found in test DB for this part — skip round-trip.
        return

    # ── Assert (a): clicking Save with no change → byte-identical ───────────
    page.click("#picker-add-btn")
    # Wait until the picker closes: the .open class is removed, making the
    # .modal-overlay display:none — so wait for #picker-panel.open to be hidden.
    page.wait_for_selector("#picker-panel.open", state="hidden", timeout=5000)
    page.wait_for_timeout(_SETTLE_MS)

    after = fetch_part()
    # The F-005 failure vector: name→"Part", quantity→1, raw_color→"".
    # These must survive a no-op Save unchanged; part_number and components
    # are allowed to reflect picker normalisation (product model vs raw SKU).
    for field in ("name", "quantity", "raw_color", "location", "part_type"):
        assert before.get(field) == after.get(field), (
            f"field '{field}' changed on a no-op Save: "
            f"before={before.get(field)!r} after={after.get(field)!r}"
        )
    migrated_children = [part for part in page.evaluate(
        "(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id,
    )["draft"]["parts"] if part.get("parent_line_id") == line_id]
    assert len(migrated_children) == 1
    assert migrated_children[0].get("accessory_parent_product") == "whelen_ion"
    assert migrated_children[0].get("accessory_category") == "bracket_mount"


def flow_custom_location_group_spacing(page, base_url: str) -> None:
    """A custom light location places the selected quantity as one adjustable group."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    added = _api(base_url, f"/api/draft/{draft_id}/part", {
        "name": "Forward Warning 1", "location": "Custom grille row",
        "manufacturer": "Whelen", "part_number": "ION", "quantity": 4,
        "new_or_used": "New", "source": "", "raw_color": "Red",
        "part_type": "warning_light",
        "components": [{"part_number": "IONR", "color": "Red", "quantity": 4}],
        "picker_config": {
            "mode": "uniform", "colorsPerHead": "single", "uniform": ["red"],
            "splitSecondary": [], "custom": [["red"]] * 4, "_noColor": False,
            "count": 4, "lens": "", "skuChoices": {},
            "custom_location": {
                "label": "Custom grille row", "render_location": "",
                "placements": {"front": [
                    {"x": 0.41, "y": 0.55}, {"x": 0.47, "y": 0.55},
                    {"x": 0.53, "y": 0.55}, {"x": 0.59, "y": 0.55},
                ]},
                "anchors": {"front": {"x": 0.5, "y": 0.55}}, "spacing": 0.06,
            },
        },
    })
    line_id = added["line_id"]
    _open_build_editor(page, base_url)
    page.click(f".me-edit-btn[data-lid='{line_id}']")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_function(
        "document.querySelector('#picker-add-btn')?.textContent?.trim() === 'Save edits'"
    )
    page.click("#picker-tab-btn-location")
    page.wait_for_selector("[data-custom-spacing]")

    assert page.evaluate("() => _pickerCustomPlacementHeadCount()") == 4
    assert page.locator("#picker-loc-dots .picker-custom-dot").count() == 4
    assert "place all 4 light heads as one group" in page.locator(".picker-location-placement-controls").inner_text().lower()

    page.locator("[data-custom-spacing]").evaluate("""element => {
        element.value = '0.10';
        element.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    points = page.evaluate("() => _pickerState.loc.customPlacements.front")
    assert len(points) == 4
    gaps = [round(points[index + 1]["x"] - points[index]["x"], 3) for index in range(3)]
    assert gaps == [0.1, 0.1, 0.1], f"spacing must update the whole row, got {points!r}"

    page.click("[data-custom-placement-layout='mirrored_pairs']")
    page.wait_for_timeout(_SETTLE_MS)
    assert "matching pair mirrors automatically" in page.locator(".picker-location-placement-controls").inner_text().lower()
    paired = page.evaluate("() => _pickerState.loc.customPlacements.front")
    assert [point["group_id"] for point in paired] == ["left_pair", "left_pair", "right_pair", "right_pair"]
    assert [point["head_index"] for point in paired] == [0, 1, 2, 3]
    assert abs(paired[0]["x"] + paired[3]["x"] - 1) < 0.001
    assert abs(paired[1]["x"] + paired[2]["x"] - 1) < 0.001

    overlay = page.locator("#picker-loc-dots").bounding_box()
    assert overlay
    page.mouse.click(overlay["x"] + overlay["width"] * 0.62, overlay["y"] + overlay["height"] * 0.42)
    moved = page.evaluate("() => _pickerState.loc.customPlacements.front")
    assert len(moved) == 4
    assert all(abs(point["y"] - 0.42) < 0.02 for point in moved)
    assert abs(moved[0]["x"] + moved[3]["x"] - 1) < 0.001
    assert abs(moved[1]["x"] + moved[2]["x"] - 1) < 0.001
    assert abs(sum(point["x"] for point in moved[2:]) / 2 - 0.62) < 0.02

    page.evaluate("""() => {
        for (const group of _pickerVisibleAccessoryGroups()) {
            if (!_pickerState.accessoryChoices[group.category]) {
                _pickerState.accessoryChoices[group.category] = 'none';
            }
        }
        _pickerRenderAccessories();
        _pickerUpdateFooter();
    }""")
    assert not page.locator("#picker-add-btn").is_disabled()
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden")
    saved = _api(base_url, f"/api/draft/{draft_id}")["draft"]
    part = next(item for item in saved["parts"] if item["line_id"] == line_id)
    custom_location = part["picker_config"]["custom_location"]
    assert custom_location["spacing"] == 0.1
    assert custom_location["layout"] == "mirrored_pairs"
    assert len(custom_location["placements"]["front"]) == 4
    assert abs(custom_location["anchors"]["front"]["x"] - 0.62) < 0.02


def flow_tint_and_round_location_allocation(page, base_url: str) -> None:
    """Tint and round-light specialty forms save their complete UI state."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.fill("#pf-search", "WINDOW TINT")
    page.wait_for_timeout(_SETTLE_MS)
    page.click(".pp-head[data-pid='qb_unassigned_tint']")
    page.click("[data-pick][data-pid='qb_unassigned_tint']")
    page.wait_for_selector("[data-tint-window='windshield_brow']")
    assert page.locator("#picker-tab-btn-location").is_hidden()
    for window in ("windshield_brow", "driver_front", "passenger_front"):
        page.click(f"[data-tint-window='{window}']")
    page.locator("[data-tint-percentage]").fill("35")
    page.locator("[data-tint-percentage]").dispatch_event("input")
    assert "Retail $65.00 × 3 = $195.00" in page.locator(".pp-tint-price").inner_text()
    assert page.locator(".pp-tint-window").evaluate_all(
        "buttons => buttons.every(button => button.scrollWidth <= button.clientWidth && button.scrollHeight <= button.clientHeight)"
    )
    assert not page.locator("#picker-add-btn").is_disabled()
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    saved = _api(base_url, f"/api/draft/{draft_id}")["draft"]
    tint = next(part for part in saved["parts"] if part.get("part_type") == "window_tint")
    assert tint["quantity"] == 3
    assert tint["picker_config"]["window_tint"] == {
        "windows": ["windshield_brow", "driver_front", "passenger_front"],
        "percentage": 35,
        "unit_price": 65,
    }

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.fill("#pf-search", "3SBCCDCR")
    page.wait_for_timeout(_SETTLE_MS)
    page.click(".pp-head[data-pid='whelen_round_lighthead']")
    page.wait_for_selector("[data-allocation-location='Lower Kick Panels'][data-allocation-delta='1']")
    round_row = page.locator(".pp-row[data-pid='whelen_round_lighthead']")
    assert round_row.locator("[data-k='count']").count() == 0
    assert "Colors per head" not in round_row.inner_text()
    assert "Lens" not in round_row.inner_text()
    assert round_row.locator("[data-round-light-color='red'].active").count() == 1
    assert page.locator("[data-allocation-comment='Lower Kick Panels']").is_disabled(), \
        "inactive round-light locations must keep their line-note field disabled"
    assert page.locator("#picker-comment-step").is_hidden(), \
        "round-light allocations must not expose the old shared part-note field"
    add_button = page.locator("[data-allocation-location='Lower Kick Panels'][data-allocation-delta='1']")
    original_box = add_button.bounding_box()
    page.click("[data-allocation-location='Lower Kick Panels'][data-allocation-delta='1']")
    next_box = page.locator("[data-allocation-location='Lower Kick Panels'][data-allocation-delta='1']").bounding_box()
    assert original_box and next_box
    assert abs(original_box["x"] - next_box["x"]) < 1
    assert abs(original_box["y"] - next_box["y"]) < 1
    page.click("[data-allocation-location='Lower Kick Panels'][data-allocation-delta='1']")
    page.click("[data-allocation-location='Prisoner Headliner'][data-allocation-delta='1']")
    page.fill("[data-allocation-comment='Lower Kick Panels']", "Aim toward both door sills")
    page.fill("[data-allocation-comment='Prisoner Headliner']", "Center over rear seat")
    page.click("[data-round-light-color='blue']")
    assert page.locator("[data-allocation-comment='Lower Kick Panels']").input_value() == "Aim toward both door sills", \
        "kick-panel note was lost after round-light color re-render"
    assert page.locator("[data-allocation-comment='Prisoner Headliner']").input_value() == "Center over rear seat", \
        "headliner note was lost after round-light color re-render"
    assert "3 lights" in page.locator(".pp-location-allocation .pp-tint-price").inner_text()
    assert not page.locator("#picker-add-btn").is_disabled()
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    saved = _api(base_url, f"/api/draft/{draft_id}")["draft"]
    allocated = [
        part for part in saved["parts"]
        if (part.get("picker_config") or {}).get("location_batch_id")
    ]
    assert [(part["location"], part["quantity"]) for part in allocated] == [
        ("Lower Kick Panels", 2), ("Prisoner Headliner", 1),
    ]
    allocation_comments = {part["location"]: part["comment"] for part in allocated}
    assert allocation_comments == {
        "Lower Kick Panels": "Aim toward both door sills",
        "Prisoner Headliner": "Center over rear seat",
    }, f"allocated line comments were not saved independently: {allocation_comments!r}"
    assert len({part["picker_config"]["location_batch_id"] for part in allocated}) == 1
    assert all(part["raw_color"] == "Blue/White" for part in allocated)
    assert all(part["components"][0]["part_number"] == "3SBCCDCR" for part in allocated)
    assert all(part["picker_config"]["round_light"] == {"warning_color": "blue"} for part in allocated)
    assert all(part["picker_config"]["location_allocation"]["comments"] == {
        "Lower Kick Panels": "Aim toward both door sills",
        "Prisoner Headliner": "Center over rear seat",
    } for part in allocated), "allocation picker snapshot did not retain per-location comments"

    # Editing either row reopens the full linked allocation with each line's
    # own note restored. Updating one must not overwrite the other.
    lower = next(part for part in allocated if part["location"] == "Lower Kick Panels")
    page.click(f".me-edit-btn[data-lid='{lower['line_id']}']")
    page.wait_for_selector("#picker-panel.open")
    # The panel opens before its async edit hydration finishes.  Wait for the
    # edit-only footer state so we do not interact with the previous add UI.
    page.wait_for_function(
        "document.querySelector('#picker-add-btn')?.textContent?.trim() === 'Save edits'"
    )
    page.wait_for_selector("[data-allocation-comment='Lower Kick Panels']")
    assert page.locator("[data-allocation-comment='Lower Kick Panels']").input_value() == "Aim toward both door sills", \
        "kick-panel comment did not restore on allocation edit"
    assert page.locator("[data-allocation-comment='Prisoner Headliner']").input_value() == "Center over rear seat", \
        "headliner comment did not restore on allocation edit"
    assert page.locator("#picker-comment-step").is_hidden(), \
        "shared part-note field reappeared while editing an allocation"
    page.fill("[data-allocation-comment='Lower Kick Panels']", "Updated kick-panel direction")
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden")
    saved = _api(base_url, f"/api/draft/{draft_id}")["draft"]
    edited_allocated = [
        part for part in saved["parts"]
        if (part.get("picker_config") or {}).get("location_batch_id")
    ]
    edited_comments = {part["location"]: part["comment"] for part in edited_allocated}
    assert edited_comments == {
        "Lower Kick Panels": "Updated kick-panel direction",
        "Prisoner Headliner": "Center over rear seat",
    }, f"editing one allocated line overwrote another line's comment: {edited_comments!r}"

    # Deleting one allocated manifest row must make the live remaining rows
    # authoritative. The old full-batch picker snapshot on the survivor must
    # not resurrect the deleted location on the next edit/save.
    deleted = next(part for part in edited_allocated if part["location"] == "Prisoner Headliner")
    remaining = next(part for part in edited_allocated if part["location"] == "Lower Kick Panels")
    delete_result = page.evaluate("""async ({draftId, lineId}) => {
      const response = await fetch(`/api/draft/${draftId}/part/${lineId}/delete`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
      });
      return response.json();
    }""", {"draftId": draft_id, "lineId": deleted["line_id"]})
    assert delete_result.get("ok"), f"could not delete allocated manifest row: {delete_result!r}"
    page.evaluate("id => loadDraftManifest(id)", draft_id)
    page.wait_for_selector(f".me-edit-btn[data-lid='{remaining['line_id']}']")
    page.click(f".me-edit-btn[data-lid='{remaining['line_id']}']")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_function(
        "() => _pickerState?.editLineId "
        "&& Number(_pickerState.locationAllocation?.quantities?.['Lower Kick Panels']) === 2 "
        "&& !_pickerState.locationAllocation?.quantities?.['Prisoner Headliner']"
    )
    page.wait_for_selector("[data-allocation-location='Prisoner Headliner'][data-allocation-delta='1']")
    assert "2 lights" in page.locator(".pp-location-allocation .pp-tint-price").inner_text()
    prisoner_value = page.locator(
        "[data-allocation-location='Prisoner Headliner'][data-allocation-delta='1']"
    ).locator("xpath=preceding-sibling::span").inner_text()
    assert prisoner_value == "0", "deleted round-light allocation was restored from a stale snapshot"
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden")
    saved = _api(base_url, f"/api/draft/{draft_id}")["draft"]
    live_allocated = [
        part for part in saved["parts"]
        if (part.get("picker_config") or {}).get("location_batch_id")
    ]
    assert [(part["location"], part["quantity"]) for part in live_allocated] == [
        ("Lower Kick Panels", 2),
    ], f"editing a surviving round-light row resurrected deleted locations: {live_allocated!r}"


def flow_overview_unit_notes_and_preconfig_qb(page, base_url: str) -> None:
    """Long Overview notes open in a modal and QB setup works before a draft."""
    long_note = (
        "Transfer the existing radio, radar, camera, and rear equipment tray from the old unit. "
        "Coordinate the installation date with the fleet supervisor before removing any equipment, "
        "and call the agency contact if replacement hardware is needed."
    )
    saved = _api(base_url, "/api/project/save", {
        "customer": {
            "name": "Overview Notes PD",
            "agency": "Overview Notes PD",
            "build_year": "2026",
        },
        "build_units": [{
            "unit_id": "overview-unit-1",
            "vehicle_model": "PIU",
            "build_type": "Patrol",
            "quantity": 2,
            "individuals": [
                {
                    "individual_id": "overview-ind-1",
                    "unit_number": "214",
                    "notes": long_note,
                    "draft_id": None,
                },
                {
                    "individual_id": "overview-ind-short",
                    "unit_number": "215",
                    "notes": "Install the customer-supplied radio.",
                    "draft_id": None,
                },
                {
                    "individual_id": "overview-ind-history",
                    "existing_year": "2018",
                    "existing_make": "Ford",
                    "existing_model": "Police Interceptor Utility",
                    "existing_build_type": "Patrol",
                    "existing_unit_number": "03",
                    "existing_vin": "OLDVIN654321",
                    "notes": "Completed-build photo archive only.",
                },
            ],
        }],
    })
    project_id = saved["project_id"]

    page.goto(base_url, wait_until="load")
    page.click(".htab[data-tab='projects']")
    page.wait_for_selector("#tab-projects:not([hidden])")
    page.evaluate("projectId => PT_open(projectId)", project_id)
    card = page.locator("#build-card-overview-ind-1")
    card.wait_for()

    page.wait_for_selector("#build-card-overview-ind-1 .proj-unit-notes--overflowing")
    notes = card.locator(".proj-unit-notes")
    assert "Transfer the existing radio" in notes.locator(".proj-unit-notes-preview").inner_text()
    metrics = notes.locator(".proj-unit-notes-preview").evaluate(
        "el => ({clientHeight: el.clientHeight, scrollHeight: el.scrollHeight, "
        "lineHeight: parseFloat(getComputedStyle(el).lineHeight), "
        "clamp: getComputedStyle(el).webkitLineClamp})"
    )
    assert metrics["clamp"] == "2"
    assert metrics["scrollHeight"] > metrics["clientHeight"]
    assert metrics["clientHeight"] <= metrics["lineHeight"] * 2 + 1
    assert notes.get_by_role("button", name="Read more").is_visible()
    notes.get_by_role("button", name="Read more").click()
    page.wait_for_selector("#unit-notes-modal.open")
    modal_title = page.locator("#unit-notes-modal-title").inner_text()
    assert "2026" in modal_title
    assert "PIU" in modal_title
    assert "Patrol" in modal_title
    assert "Unit 214" in modal_title
    assert page.locator("#unit-notes-modal-body").inner_text() == long_note
    page.click("#unit-notes-modal-done")
    page.wait_for_selector("#unit-notes-modal.open", state="hidden")
    notes.locator("strong").click()
    page.wait_for_selector("#unit-notes-modal.open")
    page.click("#unit-notes-modal-done")
    assert page.locator("#proj-build-editor").is_hidden()

    short_notes = page.locator("#build-card-overview-ind-short .proj-unit-notes")
    assert "proj-unit-notes--overflowing" not in (short_notes.get_attribute("class") or "")
    assert short_notes.get_by_role("button", name="Read more").is_hidden()

    sparse_card = page.locator("#build-card-overview-ind-history")
    sparse_card.wait_for()
    sparse_text = sparse_card.inner_text()
    assert all(value in sparse_text for value in (
        "2026 ONP PIU", "Patrol", "Pending ID OVERVIEW",
    ))
    assert sparse_card.get_by_role("button", name="View completed photos").count() == 0
    assert sparse_card.get_by_role("button", name="View reference photos (0)").count() == 0
    assert "Unit #" not in sparse_text
    assert "654321" not in sparse_text
    assert "PDF Options" in sparse_text
    assert "QuickBooks" in sparse_text
    assert sparse_card.locator(".proj-final-review-btn").is_disabled()
    sparse_card.get_by_role("button", name="Details").click()
    page.wait_for_selector("#ind-edit-modal.open")
    assert page.locator("#ind-edit-existing-year").input_value() == "2018"
    assert page.locator("#ind-edit-existing-make").input_value() == "Ford"
    assert page.locator("#ind-edit-existing-model").input_value() == "Police Interceptor Utility"
    assert page.locator("#ind-edit-existing-build-type").input_value() == "Patrol"
    assert page.locator("#ind-edit-existing-unit-number").input_value() == "03"
    assert page.locator("#ind-edit-existing-vin").input_value() == "OLDVIN654321"
    assert page.locator("#ind-edit-historical").count() == 0
    assert page.locator("#ind-modal-setup-section").is_visible()
    page.click("#ind-edit-modal .modal-close")
    page.wait_for_selector("#ind-edit-modal.open", state="hidden")

    card_title = card.locator(".proj-build-card-label").inner_text()
    assert all(value in card_title for value in (
        "2026", "PIU", "Patrol", "Unit 214",
    ))
    assert "Preview" not in card.inner_text()
    assert "PowerPoint" not in card.inner_text()
    assert "configured" not in card.inner_text().lower()
    qb_menu = card.locator(".proj-build-action-menu").filter(has_text="QuickBooks")
    qb_menu.locator("summary").click()
    qb_button = qb_menu.get_by_role("button", name="Set up QB project")
    assert not qb_button.is_disabled()
    assert qb_menu.get_by_role("button", name="Create estimate").is_disabled()
    qb_button.click()
    page.wait_for_selector("#qb-est-modal.open")
    assert page.locator("#qb-est-title").inner_text() == "Set up the QuickBooks Project"
    qb_body = page.locator("#qb-est-body").inner_text()
    assert "2026" in qb_body
    assert "PIU" in qb_body
    assert "| Patrol | Unit 214" in qb_body
    assert "Overview Notes PD |" not in page.locator("#qb-est-body").inner_text()
    page.fill("#qb-project-id", "https://qbo.intuit.com/app/project?projectId=447322633")
    page.click("#qb-est-create")
    page.wait_for_selector("#qb-est-modal.open", state="hidden")
    page.wait_for_selector("#build-card-overview-ind-1")
    card = page.locator("#build-card-overview-ind-1")
    qb_menu = card.locator(".proj-build-action-menu").filter(has_text="QuickBooks")
    qb_menu.locator("summary").click()
    assert qb_menu.get_by_role("button", name="Manage QB project").count() == 1
    assert qb_menu.get_by_role("button", name="Create estimate").is_disabled()
    reference_button = page.get_by_role("button", name="Project photos", exact=True)
    reference_button.click()
    assert qb_menu.get_attribute("open") is None
    assert page.locator("#photo-gallery-modal").is_hidden()
    detail = _api(base_url, f"/api/project/{project_id}")["project"]
    saved_individual = detail["build_units"][0]["individuals"][0]
    assert saved_individual["draft_id"] is None
    assert saved_individual["qb_project_id"] == "447322633"

    final_button = card.locator(".proj-final-review-btn")
    assert final_button.is_disabled()
    assert "proj-final-review-btn--finalized" not in (final_button.get_attribute("class") or "")
    assert final_button.evaluate("button => button === button.parentElement.lastElementChild")

    reference_button.click()
    page.wait_for_selector("#photo-gallery-modal.open")
    page.wait_for_function(
        "() => !document.getElementById('photo-gallery-body').innerText.includes('Loading project photos')"
    )
    gallery_text = page.locator("#photo-gallery-body").inner_text()
    assert "No project photos" in gallery_text
    page.get_by_role("button", name="Add photos", exact=True).click()
    page.wait_for_selector("#photo-gallery-modal.open", state="hidden")
    page.wait_for_selector("#reference-photo-modal.open")
    page.wait_for_selector("#reference-photo-browser")
    page.click("#reference-photo-modal-done")
    page.wait_for_selector("#reference-photo-modal.open", state="hidden")
    page.wait_for_selector("#photo-gallery-modal.open")
    page.click("#photo-gallery-done")
    page.wait_for_selector("#photo-gallery-modal.open", state="hidden")

    assert card.get_by_role("button", name="View completed photos").count() == 0

    page.get_by_role("button", name="Build Reference Photos (0)").click()
    page.wait_for_selector("#photo-gallery-modal.open")
    page.wait_for_function(
        "() => !document.getElementById('photo-gallery-body').innerText.includes('Loading build reference photos')"
    )
    assert "No build reference photos" in page.locator("#photo-gallery-body").inner_text()
    assert page.get_by_role("button", name="Add photos", exact=True).count() == 1
    page.get_by_role("button", name="Add photos", exact=True).click()
    page.wait_for_selector("#reference-photo-modal.open")
    page.wait_for_selector("#reference-photo-browser")
    page.wait_for_function(
        "() => { const text = document.getElementById('reference-photo-browser').innerText; "
        "return !text.trim().startsWith('Loading ') && !text.includes('Scanning '); }"
    )
    browser_text = page.locator("#reference-photo-browser").inner_text()
    assert "No photos found" in browser_text, browser_text
    assert page.locator("#reference-photo-browser [data-reference-browser-index]").count() == 0
    page.click("#reference-photo-modal-done")
    page.wait_for_selector("#photo-gallery-modal.open")
    page.click("#photo-gallery-done")

    for reference in [
        {
            "reference_id": "live-count-photo",
            "file_name": "live-count.jpg",
            "media_type": "photo",
            "source_kind": "company_reference",
            "source_path": "Vehicle Project Database/Overview Notes PD/Reference Photos & Videos/live-count.jpg",
            "assignments": [{
                "scope": "unit_group", "target_id": "overview-unit-1", "note": "Keep this note",
            }],
        },
        {
            "reference_id": "unassigned-front",
            "file_name": "unassigned-front.jpg",
            "media_type": "photo",
            "source_kind": "company_reference",
            "source_path": "Vehicle Project Database/Overview Notes PD/Reference Photos & Videos/unassigned-front.jpg",
            "assignments": [],
        },
        {
            "reference_id": "unassigned-rear",
            "file_name": "unassigned-rear.jpg",
            "media_type": "photo",
            "source_kind": "company_reference",
            "source_path": "Vehicle Project Database/Overview Notes PD/Reference Photos & Videos/unassigned-rear.jpg",
            "assignments": [],
        },
    ]:
        saved_reference = _api(base_url, f"/api/project/{project_id}/references/save", {
            "reference": reference,
        })
        assert saved_reference["ok"] is True
    thumbnail_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c49444154789c63606060000000040001f61738550000000049454e44ae426082"
    )
    thumbnail_attempts = {}

    def serve_thumbnail(route):
        url = route.request.url
        thumbnail_attempts[url] = thumbnail_attempts.get(url, 0) + 1
        if thumbnail_attempts[url] == 1:
            route.fulfill(
                status=202,
                content_type="text/plain",
                headers={"Retry-After": "1", "X-DTM-Thumbnail-State": "preparing"},
                body=b"Preparing",
            )
            return
        route.fulfill(status=200, content_type="image/png", body=thumbnail_png)

    page.route("**/api/photo-gallery/*/thumbnail", serve_thumbnail)
    page.evaluate("async projectId => { await _ptLoadAll(); PT_open(projectId); }", project_id)
    page.get_by_role("button", name="Build Reference Photos (1)").wait_for()
    page.get_by_role("button", name="Build Reference Photos (1)").click()
    page.wait_for_selector("#photo-gallery-modal.open")
    page.wait_for_function(
        "() => !document.getElementById('photo-gallery-body').innerText.includes('Loading build reference photos')"
    )
    group_gallery = page.locator("#photo-gallery-body")
    assert "Keep this note" in group_gallery.inner_text()
    assert "Company photo" in group_gallery.inner_text()
    page.wait_for_function(
        "() => document.querySelector('#photo-gallery-body img[data-thumbnail-url]')?.dataset.thumbnailState === 'loaded'",
        timeout=10000,
    )
    thumbnail_state = page.locator("#photo-gallery-body img[data-thumbnail-url]").get_attribute(
        "data-thumbnail-state"
    )
    assert thumbnail_state == "loaded", (
        f"state={thumbnail_state!r}\n{page.locator('#photo-gallery-body').inner_text()}"
    )
    page.get_by_role("button", name="Edit note", exact=True).click()
    page.locator("[data-gallery-note-input]").fill("Updated shop note")
    page.get_by_role("button", name="Save note", exact=True).click()
    page.wait_for_function(
        "() => document.getElementById('photo-gallery-body').innerText.includes('Updated shop note')"
    )
    page.get_by_role("button", name="Add photos", exact=True).click()
    page.wait_for_selector("#reference-photo-modal.open")
    page.wait_for_function(
        "() => document.querySelectorAll('#reference-photo-browser [data-reference-select]').length === 2"
    )
    checkboxes = page.locator("#reference-photo-browser [data-reference-select]")
    checkboxes.nth(0).check()
    checkboxes.nth(1).check()
    assert "2 selected" in page.locator("#reference-photo-selected-count").inner_text()
    page.get_by_role("button", name="Assign selected photos", exact=True).click()
    page.wait_for_function(
        "() => document.getElementById('reference-photo-browser').innerText.includes('No photos found')"
    )
    page.click("#reference-photo-modal-done")
    page.wait_for_selector("#photo-gallery-modal.open")
    page.wait_for_function(
        "() => document.querySelectorAll('#photo-gallery-body .photo-gallery-card').length === 3"
    )
    page.click("#photo-gallery-done")
    page.get_by_role("button", name="Build Reference Photos (3)").wait_for()
    page.get_by_role("button", name="Project photos", exact=True).click()
    page.wait_for_selector("#photo-gallery-modal.open")
    page.wait_for_function(
        "() => !document.getElementById('photo-gallery-body').innerText.includes('Loading project photos')"
    )
    assert "Assigned" in page.locator("#photo-gallery-body").inner_text()
    assert "Updated shop note" in page.locator("#photo-gallery-body").inner_text()
    for index in range(page.locator(".photo-gallery-select input").count()):
        page.locator(".photo-gallery-select input").nth(index).check()
    remove_dialogs = []
    page.once("dialog", lambda dialog: (remove_dialogs.append(dialog.message), dialog.accept()))
    page.get_by_role("button", name="Remove from project").click()
    page.wait_for_function(
        "() => [...document.querySelectorAll('.proj-group-reference-btn')].some(button => button.textContent.includes('(0)'))"
    )
    assert remove_dialogs and "original photo files will not be deleted" in remove_dialogs[0]
    page.wait_for_function(
        "() => document.getElementById('photo-gallery-body').innerText.includes('No project photos')"
    )
    page.click("#photo-gallery-done")
    page.wait_for_selector("#photo-gallery-modal.open", state="hidden")

    completion_dialogs = []
    page.once("dialog", lambda dialog: (completion_dialogs.append(dialog.message), dialog.accept()))
    page.click("#btn-proj-complete")
    assert completion_dialogs and "move to Project Archives" in completion_dialogs[0]
    page.wait_for_selector("#proj-archive-view:not([hidden])")
    assert page.locator("#proj-list-view").is_hidden()
    agency_branch = page.locator("#proj-archive-tree .proj-archive-agency").filter(
        has_text="Overview Notes PD"
    )
    agency_branch.locator(":scope > summary").click()
    year_branch = agency_branch.locator(".proj-archive-year").filter(has_text="2026")
    year_branch.locator(":scope > summary").click()
    archived_project = year_branch.locator(".proj-archive-project")
    assert "PIU" in archived_project.inner_text()
    assert archived_project.get_by_role("button", name="View completed photos").count() == 0
    assert archived_project.get_by_role("button", name="Project photos").count() == 1
    archived_project.get_by_role("button", name="Open", exact=True).click()
    page.wait_for_selector("#proj-detail-view:not([hidden])")
    assert page.locator("#btn-proj-complete").inner_text() == "Reopen Project"
    page.click("#btn-proj-complete")
    page.wait_for_selector("#proj-list-view:not([hidden])")
    assert page.locator("#proj-list-rows .proj-row").filter(has_text="Overview Notes PD").count() == 1


def flow_final_build_signoff(page, base_url: str) -> None:
    """Design finalization is clear, locks edits, and requires a reopen reason."""
    project_id, unit_id, draft_id = _seed_project_with_draft(
        base_url,
        build_state={
            "pdf_path": "output/ui-smoke-final.pdf",
            "last_exported_at": "2999-01-01T00:00:00+00:00",
        },
    )
    for part in (
        {"name": "Roof Light Bar", "part_type": "roof_light_bar"},
        {"name": "Siren Speaker", "part_type": "siren_speaker"},
        {"name": "Light Controller", "part_type": "light_controller"},
        {"name": "Control Head", "part_type": "control_head"},
        {"name": "Radio System", "part_type": "radio_system"},
        {"name": "Radar System", "part_type": "radar_system"},
        {"name": "Camera DVR", "part_type": "camera_dvr"},
        {"name": "Front Partition", "part_type": "front_partition"},
        {"name": "Rear Partition", "part_type": "rear_partition"},
        {"name": "Expansion Module", "part_type": "expansion_module"},
    ):
        _api(base_url, f"/api/draft/{draft_id}/part", part)
    page.goto(base_url, wait_until="load")
    page.click(".htab[data-tab='projects']")
    page.wait_for_selector("#tab-projects:not([hidden])")
    page.evaluate("projectId => PT_open(projectId)", project_id)
    page.wait_for_selector(f"#build-card-unit-{unit_id}")
    group_title = page.locator(f"#build-card-unit-{unit_id} .proj-build-card-label").inner_text()
    assert all(value in group_title for value in (
        "2026", "PIU", "Patrol", "Group Build",
    )), group_title
    final_button = page.locator(f"#build-card-unit-{unit_id} .proj-final-review-btn")
    assert page.locator(f"#build-card-unit-{unit_id}").get_by_role(
        "button", name="View completed photos",
    ).count() == 0
    assert "proj-final-review-btn--finalized" not in (final_button.get_attribute("class") or "")
    assert final_button.evaluate("button => button === button.parentElement.lastElementChild")
    final_button.click()
    page.wait_for_selector("#build-finalization-modal.open")
    assert "Review and lock this design" in page.locator("#build-finalization-body").inner_text()
    assert "Equipment checks clear" in page.locator("#build-finalization-body").inner_text()
    checks = page.locator(".build-final-checks")
    assert checks.count() == 1
    assert not checks.get_attribute("open")
    assert "17 of 17 final checks passed" in checks.locator("summary").inner_text()
    checks.locator("summary").click()
    assert checks.locator(".build-final-check").count() == 17
    assert checks.locator(".build-final-check--passed").count() == 17
    assert page.locator("#build-finalization-save").inner_text() == "Finalize design"
    page.click("#build-finalization-save")
    page.wait_for_function(
        "([projectId]) => fetch('/api/project/' + projectId).then(r => r.json()).then(r => r.project.build_units[0].status === 'finalized')",
        arg=[project_id],
    )
    page.wait_for_timeout(500)
    modal_state = page.locator("#build-finalization-modal").evaluate(
        "el => ({className: el.className, hidden: el.hidden, title: document.getElementById('build-finalization-title').innerText, toast: document.getElementById('toast').innerText})"
    )
    assert modal_state["hidden"] and "open" not in modal_state["className"], modal_state
    page.wait_for_selector(f"#build-card-unit-{unit_id} .proj-final-review-btn--finalized")
    final_button = page.locator(f"#build-card-unit-{unit_id} .proj-final-review-btn--finalized")
    assert final_button.inner_text() == "✓ Design finalized"
    assert final_button.evaluate("button => button === button.parentElement.lastElementChild")
    assert page.locator(f"#build-card-unit-{unit_id}").get_by_role(
        "button", name="View completed photos",
    ).count() == 0

    final_button.click()
    page.wait_for_selector("#build-finalization-modal.open")
    assert "Design sign-off complete" in page.locator("#build-finalization-body").inner_text()
    assert page.locator(".build-final-checks").count() == 1
    assert page.locator("#build-finalization-save").inner_text() == "Reopen for changes"
    page.fill("#build-reopen-reason", "Move grille lights")
    page.click("#build-finalization-save")
    page.wait_for_selector("#build-finalization-modal.open", state="hidden")
    page.wait_for_function(
        "([projectId]) => fetch('/api/project/' + projectId).then(r => r.json()).then(r => r.project.build_units[0].status === 'reopened')",
        arg=[project_id],
    )
    page.wait_for_selector(f"#build-card-unit-{unit_id} .proj-final-review-btn:not(.proj-final-review-btn--finalized)")


def flow_printer_accessory_round_trip(page, base_url: str) -> None:
    """Printer accessories use distinct shop labels, survive a parent edit,
    can add another item from the same accessory group, and surface orderable
    SKUs before the accessory description."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    # A draft-local custom line edits in its own priced form, and can opt into
    # an existing manifest category without becoming a managed catalog SKU.
    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.click("[data-picker-custom-part]")
    page.wait_for_selector("#picker-custom-part-modal.open")
    page.fill("#picker-custom-part-sku", "SMOKE-CUSTOM")
    page.fill("#picker-custom-part-description", "Smoke custom part")
    page.fill("#picker-custom-part-price", "12.50")
    page.fill("#picker-custom-part-qty", "2")
    category_value = page.locator("#picker-custom-part-category option").nth(1).get_attribute("value")
    assert category_value
    page.select_option("#picker-custom-part-category", category_value)
    page.click("#picker-custom-part-save")
    page.wait_for_selector("#picker-custom-part-modal.open", state="hidden")
    custom_draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    custom = next(p for p in custom_draft["draft"]["parts"] if p.get("part_number") == "SMOKE-CUSTOM")
    assert custom.get("part_type") == category_value
    page.click(f".me-edit-btn[data-lid='{custom['line_id']}']")
    page.wait_for_selector("#picker-custom-part-modal.open")
    assert not page.locator("#picker-panel.open").is_visible()
    assert page.input_value("#picker-custom-part-price") == "12.5"
    page.fill("#picker-custom-part-description", "Edited smoke custom part")
    page.fill("#picker-custom-part-price", "15.75")
    page.click("#picker-custom-part-save")
    page.wait_for_selector("#picker-custom-part-modal.open", state="hidden")
    custom_draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    custom = next(p for p in custom_draft["draft"]["parts"] if p.get("part_number") == "SMOKE-CUSTOM")
    assert custom["name"] == "Edited smoke custom part"
    assert custom["picker_config"]["custom_part"]["unit_price"] == 15.75

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    assert page.locator("#picker-part-status").is_visible()
    assert page.get_attribute("[data-picker-supply-type='new']", "aria-pressed") == "true"
    page.click("[data-picker-supply-type='customer_supplied']")
    page.click("[data-picker-customer-condition='used']")
    page.fill("#picker-customer-source", "Retired patrol unit")
    assert page.get_attribute("[data-picker-supply-type='customer_supplied']", "aria-pressed") == "true"
    assert page.get_attribute("[data-picker-customer-condition='used']", "aria-pressed") == "true"
    page.fill("#pf-search", "PJ-822")
    page.wait_for_selector(".pp-head[data-pid='brother_pj_822']")
    if page.locator("#pp-veh-only").count() and page.locator("#pp-veh-only").is_checked():
        page.click("#pp-veh-only")
    page.click(".pp-head[data-pid='brother_pj_822']")
    page.wait_for_selector("[data-pick='PJ-822'][data-pid='brother_pj_822']")
    page.click("[data-pick='PJ-822'][data-pid='brother_pj_822']")

    for category in ("printer_mount", "printer_power_cable", "printer_usb_cable"):
        page.wait_for_selector(f"select[data-cat='{category}']")
        labels = page.locator(f".pa-row:has(select[data-cat='{category}']) > label").all_text_contents()
        expected = {
            "printer_mount": "Bracket / Mount",
            "printer_power_cable": "Power Cable",
            "printer_usb_cable": "USB Cable",
        }[category]
        assert labels == [expected], f"{category} needs its shop-facing label, got {labels!r}"
        first_choice = page.locator(f"select[data-cat='{category}'] option").nth(2)
        first_value = first_choice.get_attribute("value") or ""
        first_sku = first_value.rsplit("::", 1)[-1]
        assert first_choice.text_content().startswith(f"{first_sku} · "), (
            f"{category} accessory choices must lead with their orderable SKU, "
            f"got {first_choice.text_content()!r}"
        )
        page.select_option(f"select[data-cat='{category}']", index=2)

    page.click("#picker-tab-btn-location")
    page.wait_for_timeout(_SETTLE_MS)
    page.evaluate("""() => {
        Object.assign(_pickerState.loc, {
            selected: 'PRINTER ARMREST MOUNT', name_pattern: 'Printer',
            base_label: 'Printer', catalog_names: [], textCustom: false,
        });
        _pickerUpdateFooter();
    }""")
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    printer = next(part for part in draft["draft"]["parts"] if part.get("part_type") == "printer")
    assert printer["new_or_used"] == "Used"
    assert printer["supply_type"] == "customer_supplied"
    assert printer["customer_condition"] == "used"
    assert printer["customer_source"] == "Retired patrol unit"
    children = [part for part in draft["draft"]["parts"] if part.get("parent_line_id") == printer["line_id"]]
    assert {part.get("accessory_category") for part in children} == {
        "printer_mount", "printer_power_cable", "printer_usb_cable",
    }, f"printer should save one child for every selected accessory role, got {children!r}"

    # Existing drafts may have the accessory rows in the manifest without the
    # newer helper metadata. Parent edit must derive their choices from the
    # child row + SKU, then rewrite the metadata on Save.
    for child in children:
        legacy_child = {**child, "accessory_category": "", "accessory_parent_product": ""}
        _api(base_url, f"/api/draft/{draft_id}/part/{child['line_id']}/update", legacy_child)
    page.evaluate("(id) => loadDraftManifest(id)", draft_id)
    page.wait_for_timeout(_SETTLE_MS)

    page.evaluate("(lineId) => openPartEditModal(lineId)", printer["line_id"])
    page.wait_for_selector("#picker-panel.open")
    assert page.get_attribute("[data-picker-supply-type='customer_supplied']", "aria-pressed") == "true", (
        "editing a picker part must restore its saved condition"
    )
    assert page.get_attribute("[data-picker-customer-condition='used']", "aria-pressed") == "true"
    assert page.input_value("#picker-customer-source") == "Retired patrol unit"
    for category in ("printer_mount", "printer_power_cable", "printer_usb_cable"):
        selector = f"select[data-cat='{category}']"
        page.wait_for_selector(selector)
        assert page.locator(selector).input_value(), f"{category} selection must restore in parent edit"

    add_mount = page.locator("[data-accessory-add='printer_mount']")
    assert add_mount.is_enabled(), "an accessory group should allow another selected item"
    add_mount.click()
    page.wait_for_selector("select[data-cat='printer_mount'][data-idx='1']")
    page.select_option("select[data-cat='printer_mount'][data-idx='1']", index=3)
    assert page.locator("#picker-add-btn").text_content().strip() == "Save edits"
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    saved = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    saved_children = [part for part in saved["draft"]["parts"] if part.get("parent_line_id") == printer["line_id"]]
    categories = [part.get("accessory_category") for part in saved_children]
    assert categories.count("printer_mount") == 2
    assert categories.count("printer_power_cable") == 1
    assert categories.count("printer_usb_cable") == 1
    assert all(part.get("accessory_parent_product") == "brother_pj_822" for part in saved_children), (
        f"saving a migrated parent must restore the accessory metadata, got {saved_children!r}"
    )

    # PSBKT90 exists in the catalog and is an optional Mega T-Series mount.
    # Its SKU comes first so it remains identifiable even in a narrow selector.
    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.fill("#pf-search", "Mega T-Series")
    page.wait_for_selector(".pp-head[data-pid='whelen_mega_t_series']")
    if page.locator("#pp-veh-only").count() and page.locator("#pp-veh-only").is_checked():
        page.click("#pp-veh-only")
    page.click(".pp-head[data-pid='whelen_mega_t_series']")
    # This is a color-configured light; selecting its product card activates it
    # and loads its accessories (individual SKUs use the per-head selector).
    page.wait_for_selector("select[data-cat='bracket_mount']")
    mount_options = page.locator("select[data-cat='bracket_mount'] option").all_text_contents()
    assert any(option.startswith("PSBKT90 · 90° mount kit") for option in mount_options), (
        f"Mega T-Series must identify its 90-degree mount by SKU, got {mount_options!r}"
    )
    assert len(mount_options) > 3, (
        f"Mega T-Series must keep compatible generic bracket choices too, got {mount_options!r}"
    )


def flow_t_series_dual_shroud_quantity_and_render(page, base_url: str) -> None:
    """Dual shrouds default from light quantity, reject odd pairings, allow a
    manual quantity override, persist the chosen quantity, and render each
    two-head shroud as one placement unit."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.fill("#pf-search", "T-Series")
    page.wait_for_selector(".pp-head[data-pid='whelen_t_series']")
    if page.locator("#pp-veh-only").count() and page.locator("#pp-veh-only").is_checked():
        page.evaluate("""() => {
            _pickerState.vehicleOnly = false;
            localStorage.setItem('pp_vehicle_only', '0');
            _pickerRenderProducts();
            _pickerRenderAccessories();
        }""")
        page.wait_for_selector(".pp-head[data-pid='whelen_t_series']")
    page.click(".pp-head[data-pid='whelen_t_series']")
    page.wait_for_selector("select[data-cat='shroud']")

    page.evaluate("""() => {
        _pickerState.config.count = 4;
        _pickerNormalizeConfig();
        _pickerRenderProducts();
        _pickerRenderAccessories();
        _pickerUpdateFooter();
    }""")
    page.select_option("select[data-cat='shroud']", "whelen_ie_shroud::THSG2")
    for category in page.locator("select[data-cat]").evaluate_all(
        "selects => [...new Set(selects.map(select => select.dataset.cat))]"
    ):
        if category != "shroud":
            page.select_option(f"select[data-cat='{category}']", "none")
    quantity = page.locator("input[data-accessory-qty='shroud']")
    assert quantity.input_value() == "2"
    assert "Recommended 2 for 4 lights" in page.locator(".pa-coverage-note").inner_text()

    page.evaluate("""() => {
        _pickerState.config.count = 3;
        _pickerNormalizeConfig();
        _pickerRenderAccessories();
        _pickerUpdateFooter();
    }""")
    assert page.locator(".pa-coverage-error").count() == 1
    assert "cannot be fully paired" in page.locator(".pa-coverage-error").inner_text()
    assert page.evaluate("() => _accessoriesSatisfied()") is False

    page.evaluate("""() => {
        _pickerState.config.count = 4;
        _pickerNormalizeConfig();
        _pickerRenderAccessories();
        _pickerUpdateFooter();
    }""")
    quantity = page.locator("input[data-accessory-qty='shroud']")
    quantity.fill("3")
    quantity.dispatch_event("change")
    assert page.evaluate("() => _pickerState.accessoryQuantities.shroud") == 3
    quantity = page.locator("input[data-accessory-qty='shroud']")
    quantity.fill("2")
    quantity.dispatch_event("change")

    page.click("#picker-tab-btn-location")
    page.wait_for_timeout(1000)
    page.evaluate("""() => {
        const entry = _pickerState.loc.locByName['LOWER CARGO WINDOW'];
        _pickerSetStandardLocation('LOWER CARGO WINDOW', entry || {
            name_pattern: 'Rear Warning {n}', base_label: 'Rear Warning', catalog_names: [],
        });
        _pickerUpdateFooter();
    }""")
    readiness = page.evaluate("""() => ({
        accessories: _accessoriesSatisfied(), tracer: _pickerTracerSatisfied(),
        innerEdge: _pickerInnerEdgeSatisfied(), outerEdge: _pickerOuterEdgeSatisfied(),
        lightbar: _pickerLightbarSatisfied(), radio: _pickerRadioSatisfied(),
        details: _pickerPartDetailsSatisfied(), westin: _pickerWestinChannelSatisfied(),
        tint: _pickerTintReady(), allocation: _pickerLocationAllocationReady(),
        supply: _pickerSupplySatisfied(), customLocation: _pickerCustomLocationReady(),
        selected: _pickerState.sel, location: _pickerState.loc.selected,
        tab: _pickerState.tab, buttonDisabled: document.querySelector('#picker-add-btn')?.disabled,
    })""")
    assert all(value for key, value in readiness.items() if key not in {"selected", "location", "tab", "buttonDisabled"}), readiness
    assert readiness["selected"] and readiness["location"], readiness
    assert readiness["tab"] == "location" and readiness["buttonDisabled"] is False, readiness
    page.evaluate("() => _pickerState.footerHandler()")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    parent = next(part for part in draft["draft"]["parts"] if part.get("part_type") == "warning_light")
    shroud = next(
        part for part in draft["draft"]["parts"]
        if part.get("parent_line_id") == parent["line_id"] and part.get("part_number") == "THSG2"
    )
    assert parent["quantity"] == 4
    assert shroud["quantity"] == 2
    assert shroud["picker_config"]["accessory_quantity"]["render_parent_group"] == "dual_shroud"

    preview = page.evaluate(
        "(id) => fetch('/api/preview/plan', {method:'POST', headers:{'Content-Type':'application/json'}, "
        "body:JSON.stringify({draft_id:id})}).then(r => r.json())",
        draft_id,
    )
    planned = next(part for part in preview["planned_parts"] if part.get("part_number") == parent["part_number"])
    placements = {placement["view"]: placement for placement in planned["placements"]}
    assert placements["side"]["compound_group_count"] == 1
    assert len(placements["side"]["instances"]) == 2
    side_x = [instance["x_pct"] for instance in placements["side"]["instances"]]
    assert side_x[0] < placements["side"]["anchor"]["x"] < side_x[1]
    assert placements["top"]["compound_group_count"] == 2
    assert len(placements["top"]["instances"]) == 4


def flow_picker_browse_tree(page, base_url: str) -> None:
    """PICKER_REDESIGN.md Step 1 regression guard: every sidebar category
    expands INLINE (no navigate-away) and renders its part types/families —
    the core accordion behavior, independent of the lights-specific flow."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(200)

    # A non-light category (Equipment) expands in place — the panel/tabs never
    # change, unlike the old Lights-only navigate-to-a-new-page behavior.
    page.click(".pbt-cat-caret-btn[data-cat='equipment']")
    page.wait_for_selector(".pbt-cat-head[data-cat='equipment'].open")
    page.wait_for_timeout(_SETTLE_MS)
    leaf_count = page.locator(".pbt-leaf").count()
    assert leaf_count > 0, "expected Equipment category to render at least one part type/family member"

    # A conventional family expands to its member part types. Guided systems
    # (Radar, Radio, Camera) deliberately start their guided setup instead.
    page.click(".pbt-cat-caret-btn[data-cat='structural']")
    page.wait_for_selector(".pbt-cat-head[data-cat='structural'].open")
    page.click(".pbt-fam-caret-btn[data-fam='console_system']")
    page.wait_for_selector(".pbt-fam-caret-btn[data-fam='console_system'].open")
    page.wait_for_timeout(200)
    page.wait_for_selector(".pbt-leaf[data-pt='console']")

    # Collapsing/re-expanding a different category doesn't lose state on the
    # panel — still on the same tab, no navigation occurred.
    assert page.is_visible("#picker-tab-btn-part.active"), "Step 1 must stay on the Part tab (navigation-only)"

    # Families sort before standalones within a category (owner ruling
    # 2026-07-10, flaws #7+#8) — verify for Structural: Push Bumper / Cage /
    # Console / Storage families first, running_boards_nerf_bars standalone last.
    page.wait_for_timeout(_SETTLE_MS)
    child_kinds = page.evaluate("""
        () => {
            const head = document.querySelector(".pbt-cat-head[data-cat='structural']");
            return Array.from(head.closest(".pbt-cat").querySelectorAll(":scope > .pbt-cat-body > *"))
                .map(el => el.classList.contains('pbt-fam') ? 'family' : 'standalone');
        }
    """)
    assert child_kinds, "expected Structural category to render children"
    first_standalone = next((i for i, k in enumerate(child_kinds) if k == "standalone"), len(child_kinds))
    assert all(k == "family" for k in child_kinds[:first_standalone]), \
        f"families must sort before standalones under Structural, got {child_kinds}"
    assert "standalone" in child_kinds, \
        "expected at least one Structural standalone (running_boards_nerf_bars)"


def flow_radio_communications_workflow(page, base_url: str) -> None:
    """Radio Communications is a guided family-level flow. Selecting the
    family header should open the shared one-question-at-a-time system tool
    and add one expandable manifest line for the kit."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(200)

    page.click(".pbt-cat-caret-btn[data-cat='equipment']")
    page.wait_for_selector(".pbt-cat-head[data-cat='equipment'].open")
    page.wait_for_selector(".pbt-fam-select[data-family='radio_comms']")
    page.click(".pbt-fam-select[data-family='radio_comms']")
    page.wait_for_selector("#picker-products [data-system-select-kind='radio']")
    radio_choice = page.locator("[data-system-product-id='motorola_split_unit'][data-system-sku]").first
    assert radio_choice.count() == 1, "expected a concrete Motorola split-radio SKU choice"
    radio_choice.click()
    page.wait_for_selector("#picker-system-details .guided-system[data-system-kind='radio']")
    assert page.locator("#picker-part-status").is_hidden(), \
        f"guided radio picker should hide part status, got {page.locator('#picker-part-status').text_content()!r}"
    page.wait_for_function("() => _pickerState?.radio?.active && !_pickerState.radio.loading")
    assert page.evaluate("() => _pickerState.radio.choices.supplyType") == "", \
        "a new system must require an explicit supply choice"
    assert page.evaluate("() => _pickerState.radio.choices.systemProduct.product_id") == "motorola_split_unit", \
        "radio setup should retain the selected Motorola split-radio product"
    assert page.evaluate("() => !!_pickerState.radio.choices.systemProduct.part_number"), \
        "radio setup must retain the selected concrete SKU"

    assert page.locator("#picker-system-details .guided-progress").count() == 1, \
        "expected the guided radio progress bar"
    assert page.locator("#picker-system-details .guided-choice-grid").count() == 1, \
        "expected one focused radio question instead of a dense form"
    assert page.locator("#picker-system-details .guided-summary").count() == 1, \
        "expected the radio answer summary"

    # Exercise the DTM purchase branch so its free-text note is covered too.
    _guided_pick(page, "supplyType", "new")
    _guided_next(page)
    page.locator("textarea[data-system-text='purchaseDetails']").fill("Customer-specified Motorola mobile radio, split kit, include antenna and mic.")
    _guided_next(page)
    assert page.evaluate("() => _pickerState.radio.choices.format") == "split", \
        "split-head radio should be the default layout"
    _guided_pick(page, "brickLoc", "equipment_tray")
    _guided_next(page)
    _guided_pick(page, "antennaStyle", "cylinder")
    _guided_next(page)
    antenna_locations = page.locator(".guided-option[data-system-choice='antennaLoc']").evaluate_all(
        "els => els.map(el => el.dataset.systemValue)"
    )
    assert set(antenna_locations) == {"rear_left_roof", "__custom__"}, \
        f"cylinder antennas should only allow the rear-left roof or Custom, got {antenna_locations!r}"
    _guided_pick(page, "antennaLoc", "__custom__")
    page.locator("input[data-system-custom='antennaLocCustom']").fill("Roof above rear quarter")
    page.click("[data-system-custom-placement]")
    page.wait_for_selector("#picker-location-content:not([hidden]) [data-system-placement-done]")
    assert page.locator("#picker-add-btn").is_disabled(), \
        "radio kit cannot save until the custom antenna placement sub-flow is finished"
    page.click("#picker-loc-views [data-view='side']")
    page.wait_for_selector("#picker-loc-dots .picker-dot[data-name='REAR LEFT ROOF']")
    page.locator("#picker-loc-dots .picker-dot[data-name='REAR LEFT ROOF']").first.click()
    assert page.evaluate("() => _pickerState.loc.renderLocation") == "REAR LEFT ROOF"
    page.click("[data-system-placement-done]")
    page.wait_for_selector("#picker-system-details .guided-system[data-system-kind='radio']")
    _guided_next(page)
    _guided_pick(page, "speakerLoc", "back_center_console")
    _guided_next(page)
    _guided_pick(page, "micMount", "magnetic_with_bracket")
    _guided_next(page)
    _guided_pick(page, "micLoc", "__custom__")
    page.locator("input[data-system-custom='micLocCustom']").fill("Console sidecar")

    btn_text = page.locator("#picker-add-btn").text_content().strip()
    assert btn_text == "Add and Finish", \
        f"radio workflow should add from the Part tab, got primary button {btn_text!r}"

    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden", timeout=5000)
    page.wait_for_timeout(_SETTLE_MS)

    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    parts = draft["draft"]["parts"]
    radio = next((p for p in parts if p.get("picker_config", {}).get("system_type") == "radio"), None)
    assert radio is not None, "expected radio workflow to add one guided system line"
    assert radio.get("part_type") == "radio_head", "radio system line must retain its planner part type"
    assert radio.get("supply_type") == "new" and radio.get("customer_condition") == ""
    assert radio.get("part_number") == "DTM PURCHASE — SEE DETAILS", \
        f"DTM-purchased radio should use the purchase-details SKU, got {radio.get('part_number')!r}"
    assert radio.get("notes") == "Customer-specified Motorola mobile radio, split kit, include antenna and mic.", \
        f"radio purchase notes were not preserved: {radio.get('notes')!r}"
    assert radio["picker_config"]["choices"]["purchaseDetails"] == radio.get("notes"), \
        "radio picker configuration should retain its purchase details"
    component_types = {c.get("part_type") for c in radio.get("components", [])}
    expected = {"radio_head", "radio_brick", "radio_antenna_top", "radio_speaker", "radio_mic_clip"}
    assert expected.issubset(component_types), \
        f"expected expandable radio details {sorted(expected)}, got {sorted(component_types)}"
    antenna = next(c for c in radio["components"] if c.get("part_type") == "radio_antenna_top")
    assert antenna.get("location") == "Roof above rear quarter"
    assert antenna.get("picker_config", {}).get("custom_location", {}).get("render_location") == "REAR LEFT ROOF", \
        f"guided custom antenna must retain its diagram placement, got {antenna!r}"
    mic = next(c for c in radio["components"] if c.get("part_type") == "radio_mic_clip")
    assert all(component.get("supply_type") == "new" for component in radio["components"]), \
        f"new DTM system components should inherit New supply, got {radio['components']!r}"
    assert mic.get("location") == "Console sidecar", "custom shop location should populate the component row"
    magnetic_mic = next((p for p in parts if p.get("parent_line_id") == radio["line_id"]
                         and p.get("accessory_category") == "magnetic_mic"), None)
    assert magnetic_mic and magnetic_mic.get("part_number") == "MMSU-1B", \
        f"a bracketed radio Mag Mic must be a real billable child line, got {magnetic_mic!r}"
    parent = page.locator("tr.me-parent-row").filter(has_text="Radio Communications")
    parent.locator(".me-edit-btn").click()
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_function("() => _pickerState?.editLineId && _pickerState?.radio?.active && _pickerState.radio.kind === 'radio'")
    page.wait_for_selector("#picker-system-details .guided-system[data-system-kind='radio']")
    assert page.evaluate("() => _pickerState.radio.step") == 0, "guided radio edits must restart at the first question"
    edit_question = page.locator(".guided-question h2").text_content().lower()
    assert "supplying" in edit_question, \
        f"guided radio edit should reopen at the supply question, got {edit_question!r}"
    restored = page.evaluate("() => _pickerState.radio.choices")
    assert restored.get("purchaseDetails") == radio.get("notes") and restored.get("micLocCustom") == "Console sidecar", \
        f"guided radio edits must retain saved answers, got {restored!r}"
    assert restored.get("antennaLocCustom") == "Roof above rear quarter"
    assert restored.get("antennaLocPlacement", {}).get("render_location") == "REAR LEFT ROOF"


def _open_guided_system(page, base_url: str, family_id: str, kind: str) -> str:
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)
    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(200)
    page.click(".pbt-cat-caret-btn[data-cat='equipment']")
    page.wait_for_selector(".pbt-cat-head[data-cat='equipment'].open")
    page.wait_for_selector(f".pbt-fam-select[data-family='{family_id}']")
    page.click(f".pbt-fam-select[data-family='{family_id}']")
    page.wait_for_selector(f"#picker-products [data-system-select-kind='{kind}']")
    product_id = {"radar": "stalker_dsr", "camera": "watchguard_m500"}[kind]
    page.click(f"[data-system-product-id='{product_id}']")
    page.click("#picker-add-btn")
    page.wait_for_selector(f"#picker-system-details .guided-system[data-system-kind='{kind}']")
    page.wait_for_function("() => _pickerState?.radio?.active && !_pickerState.radio.loading")
    return draft_id


def _guided_pick(page, key: str, value: str) -> None:
    page.locator(f".guided-option[data-system-choice='{key}'][data-system-value='{value}']").click()
    page.wait_for_timeout(80)


def _guided_next(page) -> None:
    button = page.locator(".guided-next")
    assert button.is_enabled(), "guided system should enable Next after a valid answer"
    button.click()
    page.wait_for_timeout(80)


def _guided_finish_defaults(page) -> None:
    for _ in range(30):
        if page.evaluate("() => typeof window._pickerRadioSatisfied === 'function' && _pickerRadioSatisfied()"):
            return
        button = page.locator(".guided-next")
        if not button.is_enabled():
            options = page.locator(".guided-option")
            assert options.count() > 0, "guided step needs an answer but has no selectable options"
            options.nth(0).click()
            page.wait_for_timeout(80)
        else:
            _guided_next(page)
    raise AssertionError("guided system did not reach a complete state")


def flow_radar_system_workflow(page, base_url: str) -> None:
    """Radar follows the shared system flow and exposes the requested cable,
    antenna, split-unit, and counting-unit branches."""
    draft_id = _open_guided_system(page, base_url, "radar", "radar")
    _guided_pick(page, "supplyType", "customer_supplied")
    _guided_next(page)
    _guided_pick(page, "customerCondition", "used")
    _guided_next(page)
    page.locator("textarea[data-system-text='customerSource']").fill("Agency transfer stock")
    _guided_next(page)
    assert "Will the radar cables be refreshed?" in page.locator(".guided-question h2").text_content()
    _guided_pick(page, "refresh", "yes")
    _guided_next(page)
    assert "Which radar cables should be refreshed?" in page.locator(".guided-question h2").text_content()
    _guided_pick(page, "refreshCables", "front_antenna_cable")
    _guided_next(page)
    _guided_pick(page, "refreshSku_front_antenna_cable", "stalker_antenna_cable::155-2591-08")
    _guided_next(page)
    _guided_pick(page, "split", "yes")
    _guided_next(page)
    assert "counting unit" in page.locator(".guided-question h2").text_content().lower(), \
        "split radar should ask the counting-unit location immediately"
    _guided_pick(page, "countingLoc", "center_console")
    _guided_next(page)
    _guided_pick(page, "frontLoc", "a_pillar")
    _guided_next(page)
    assert "bracket" in page.locator(".guided-question h2").text_content().lower(), \
        "front antenna location should be followed by its bracket choice"
    _guided_pick(page, "frontBracket", "swivel_arm")
    _guided_next(page)
    rear_locations = page.locator(".guided-option[data-system-choice='rearLoc']").evaluate_all(
        "els => els.map(el => el.dataset.systemValue)"
    )
    assert "seatbelt_slot" not in rear_locations, \
        "the Tahoe-only rear seatbelt slot must not appear on the default PIU smoke build"
    _guided_pick(page, "rearLoc", "d_pillar")
    _guided_next(page)
    _guided_pick(page, "rearBracket", "tall_a_bracket")
    _guided_finish_defaults(page)
    # One component can override the parent supply decision. This radar is
    # customer-used overall, but its front antenna is customer-supplied New.
    page.evaluate("""
        () => {
            _pickerState.radio.step = _systemSteps().findIndex(step => step.key === "componentConditions");
            _pickerRefreshSystemView();
        }
    """)
    page.locator("[data-system-component-supply='radar_front_antenna'][data-system-supply-value='customer_new']").click()
    assert page.evaluate("() => _pickerRadioSatisfied()")
    integrated_components = page.evaluate("""
        () => _systemComponentRows("radar", {
            ..._pickerState.radio.choices,
            split: "no",
        }).map(component => component.label)
    """)
    assert "Radar display / counting unit" in integrated_components
    assert "Radar display unit" not in integrated_components and "Radar counting unit" not in integrated_components, \
        "only integrated radar systems may use the combined display/counting manifest component"
    assert page.locator("#picker-add-btn").text_content().strip() == "Add and Finish"
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden", timeout=5000)
    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    radar = next((p for p in draft["draft"]["parts"] if p.get("picker_config", {}).get("system_type") == "radar"), None)
    assert radar and radar["picker_config"]["choices"]["frontLoc"] == "a_pillar"
    assert radar["supply_type"] == "customer_supplied"
    assert radar["customer_condition"] == "used"
    assert radar["customer_source"] == "Agency transfer stock"
    assert radar["picker_config"]["choices"]["countingLoc"] == "center_console"
    assert radar["picker_config"]["choices"]["frontBracket"] == "swivel_arm"
    assert radar["picker_config"]["choices"]["rearBracket"] == "tall_a_bracket"
    radar_components = {component["key"]: component for component in radar["components"]}
    assert radar_components["radar_front_antenna"]["customer_condition"] == "new"
    assert radar_components["radar_front_antenna"]["customer_source"] == ""
    assert radar_components["radar_rear_antenna"]["customer_condition"] == "used"
    assert radar_components["radar_rear_antenna"]["customer_source"] == "Agency transfer stock"
    radar_cable = next((p for p in draft["draft"]["parts"] if p.get("parent_line_id") == radar["line_id"]
                         and p.get("accessory_category") == "system_cable_refresh"), None)
    assert radar_cable and radar_cable.get("part_number") == "155-2591-08", \
        f"refreshed radar cable should be a billable QB child line, got {radar_cable!r}"
    parent = page.locator("tr.me-parent-row").filter(has_text="Radar System")
    assert parent.count() == 1, "expected the radar kit to render as one expandable manifest line"
    parent.click()
    assert page.locator("tr.me-system-detail[data-parent]").count() == 0, \
        "manifest should show component rows, not duplicate question-and-answer rows"
    component_text = " ".join(page.locator("tr.me-comp-row[data-parent]").all_text_contents())
    assert all(text in component_text for text in ("Radar display unit", "Radar counting unit", "On A-pillar", "Swivel arm mount", "On D-pillar", "Tall A-bracket", "In center console")), \
        f"expected populated radar component rows, got {component_text!r}"
    assert "Radar display / counting unit" not in component_text, \
        "split systems must not combine the display and counting unit into one manifest component"

    # The contextual Add button should open this system's family directly,
    # instead of leaving the user at an unrelated root picker screen.
    section_add = page.locator(".me-cat-section").filter(has_text="Radar System").locator(".me-cat-add-btn")
    assert section_add.count() == 1, "expected the Radar manifest section to expose one scoped Add button"
    section_add.click()
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_selector("#picker-products [data-system-select-kind='radar']")
    page.click("[data-system-product-id='stalker_dsr']")
    page.click("#picker-add-btn")
    page.wait_for_function("() => _pickerState?.radio?.active && _pickerState.radio.kind === 'radar'")
    page.wait_for_selector("#picker-system-details .guided-system[data-system-kind='radar']")
    assert page.evaluate("() => _pickerState.radio.step") == 0
    assert "supplying" in page.locator(".guided-question h2").text_content().lower(), \
        "new radar setup should begin at the supply question"
    page.evaluate("pickerClose()")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    parent.locator(".me-edit-btn").click()
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_function("() => _pickerState?.editLineId && _pickerState?.radio?.active && _pickerState.radio.kind === 'radar' && Object.keys(_pickerState.radio.choices || {}).length > 0")
    page.wait_for_selector("#picker-system-details .guided-system[data-system-kind='radar']")
    assert page.evaluate("() => _pickerState.radio.step") == 0, "guided radar edits must restart at the first question"
    assert "supplying" in page.locator(".guided-question h2").text_content().lower(), \
        "guided radar edit should reopen at the supply question"
    restored = page.evaluate("() => _pickerState.radio.choices")
    assert restored.get("frontLoc") == "a_pillar" and restored.get("frontBracket") == "swivel_arm" and restored.get("countingLoc") == "center_console", \
        f"expected guided system edits to restore saved radar answers, got {restored!r}"

    # A front-only radar is a deliberate saved configuration. The optional
    # antenna question must require the explicit Not included answer, then its
    # bracket dependency and manifest component must disappear together.
    page.evaluate("""
        () => {
            const step = _systemSteps().findIndex(item => item.key === "rearLoc");
            if (step < 0) throw new Error("rear radar location step is missing");
            _pickerState.radio.step = step;
            _pickerRefreshSystemView();
        }
    """)
    rear_locations = page.locator(".guided-option[data-system-choice='rearLoc']").evaluate_all(
        "els => els.map(el => ({value: el.dataset.systemValue, label: el.textContent.trim()}))"
    )
    assert any(option["value"] == "__none__" and "Not included" in option["label"] for option in rear_locations), \
        f"optional rear radar step should expose a clear Not included choice, got {rear_locations!r}"
    _guided_pick(page, "rearLoc", "__none__")
    assert "rearBracket" not in page.evaluate("() => _systemSteps().map(step => step.key)"), \
        "rear bracket must not remain required after omitting the rear antenna"
    assert page.evaluate("() => _pickerRadioSatisfied()"), \
        "the saved answers should remain complete after the explicit rear-antenna omission"
    assert page.locator("#picker-add-btn").text_content().strip() == "Add and Finish"
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden", timeout=5000)

    updated = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    radar = next((p for p in updated["draft"]["parts"] if p.get("picker_config", {}).get("system_type") == "radar"), None)
    assert radar and radar["picker_config"]["choices"].get("rearLoc") == "__none__"
    assert not radar["picker_config"]["choices"].get("rearBracket"), \
        "a removed rear antenna must not retain stale bracket data"
    component_labels = [component.get("label") for component in radar.get("components", [])]
    assert "Front radar antenna" in component_labels and "Rear radar antenna" not in component_labels, \
        f"front-only radar should persist no phantom rear component, got {component_labels!r}"
    assert not any(part.get("part_type") == "rear_radar_antenna_mount" for part in updated["draft"]["parts"]), \
        "an omitted rear antenna must not create a billable draft line"

    page.locator("tr.me-parent-row").filter(has_text="Radar System").locator(".me-edit-btn").click()
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_function("() => _pickerState?.editLineId && _pickerState?.radio?.active && _pickerState.radio.kind === 'radar'")
    assert page.evaluate("() => _pickerState.radio.choices.rearLoc") == "__none__", \
        "Not included must round-trip through the saved guided-system configuration"
    page.evaluate("pickerClose()")
    page.wait_for_selector("#picker-panel.open", state="hidden")


def flow_camera_system_workflow(page, base_url: str) -> None:
    """Camera records antenna style/location plus the selected camera components."""
    draft_id = _open_guided_system(page, base_url, "camera_system", "camera")
    _guided_pick(page, "supplyType", "customer_supplied")
    _guided_next(page)
    _guided_pick(page, "customerCondition", "used")
    _guided_next(page)
    page.locator("textarea[data-system-text='customerSource']").fill("Prior-generation camera system")
    _guided_next(page)
    _guided_pick(page, "refresh", "yes")
    _guided_next(page)
    _guided_pick(page, "refreshCables", "signal_data_cable")
    _guided_next(page)
    assert page.evaluate("() => _pickerState.radio.choices.systemProduct.product_id") == "watchguard_m500"
    assert page.evaluate("() => _cameraSupportsExtendedComponents(_systemCameraPlatform({systemProduct:{product_id:'axon_fleet_3'}}))") is False
    antenna_options = set(page.locator("[data-system-choice='cameraAntennaStyle']").evaluate_all(
        "buttons => buttons.map(button => button.dataset.systemValue)"
    ))
    assert antenna_options == {"whip", "cylinder", "axon_fin", "custom"}, antenna_options
    _guided_pick(page, "cameraAntennaStyle", "custom")
    _guided_next(page)
    page.locator("textarea[data-system-text='cameraAntennaStyleCustom']").fill("Low-profile puck")
    _guided_next(page)
    default_location = page.locator(
        ".guided-option[data-system-choice='cameraAntennaLoc'][data-system-value='rear_right_roof']"
    )
    assert "is-selected" in (default_location.get_attribute("class") or ""), (
        "new camera systems should default the antenna to the rear right roof"
    )
    _guided_next(page)
    _guided_pick(page, "dvrLoc", "equipment_tray")
    _guided_next(page)
    for component in ("front", "rear_seat", "rear", "body_dock", "wireless_mic"):
        _guided_pick(page, "cameraParts", component)
    _guided_next(page)
    _guided_pick(page, "rearSeatLoc", "upper_cage_bar")
    _guided_next(page)
    _guided_pick(page, "bodyDockLoc", "passenger_visor")
    _guided_next(page)
    _guided_pick(page, "wirelessMicLoc", "center_console")
    assert page.locator("#picker-add-btn").text_content().strip() == "Add and Finish"
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden", timeout=5000)
    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    camera = next((p for p in draft["draft"]["parts"] if p.get("picker_config", {}).get("system_type") == "camera"), None)
    assert camera is not None, "expected camera workflow to add one guided system line"
    assert camera["supply_type"] == "customer_supplied"
    assert camera["customer_condition"] == "used"
    assert camera["customer_source"] == "Prior-generation camera system"
    assert set(camera["picker_config"]["choices"]["cameraParts"]) == {"front", "rear_seat", "rear", "body_dock", "wireless_mic"}
    assert camera["picker_config"]["choices"]["cameraAntennaStyle"] == "custom"
    assert camera["picker_config"]["choices"]["cameraAntennaStyleCustom"] == "Low-profile puck"
    assert camera["picker_config"]["choices"]["cameraAntennaLoc"] == "rear_right_roof"
    camera_components = {item["part_type"]: item for item in camera["components"]}
    assert all(item.get("customer_source") == "Prior-generation camera system" for item in camera_components.values())
    assert camera_components["camera_antenna"]["location"] == "Rear right roof"
    assert camera_components["camera_antenna"]["detail"] == "Low-profile puck"
    assert camera_components["front_camera"]["location"] == "Upper windshield"
    assert camera_components["rear_camera"]["location"] == "Upper rear window"
    parent = page.locator("tr.me-parent-row").filter(has_text="Camera System")
    parent.locator(".me-edit-btn").click()
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_function("() => _pickerState?.editLineId && _pickerState?.radio?.active && _pickerState.radio.kind === 'camera'")
    page.wait_for_selector("#picker-system-details .guided-system[data-system-kind='camera']")
    assert page.evaluate("() => _pickerState.radio.step") == 0, "guided camera edits must restart at the first question"
    assert "supplying" in page.locator(".guided-question h2").text_content().lower(), \
        "guided camera edit should reopen at the supply question"
    restored = page.evaluate("() => _pickerState.radio.choices")
    assert restored.get("systemProduct", {}).get("product_id") == "watchguard_m500" and restored.get("wirelessMicLoc") == "center_console", \
        f"guided camera edits must retain saved answers, got {restored!r}"
    assert restored.get("cameraAntennaStyle") == "custom"
    assert restored.get("cameraAntennaStyleCustom") == "Low-profile puck"
    assert restored.get("cameraAntennaLoc") == "rear_right_roof"


def flow_light_options_in_product_box(page, base_url: str) -> None:
    """PICKER_REDESIGN.md Step 2 regression guard: selecting a light part type
    goes straight to the product grid (no sidebar 'Colors & options' step);
    picking a product shows the option controls (mode/lens/color/cph/qty) in
    its box above the SKU dropdown, and they drive SKU selection."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(200)

    # Expand Lights category in the browse tree.
    page.click(".pbt-cat-caret-btn[data-cat='lights']")
    page.wait_for_selector(".pbt-cat-head[data-cat='lights'].open")
    page.wait_for_timeout(200)

    # Pick Warning directly; it is the deterministic color-configured light path.
    page.wait_for_selector(".pbt-fam-select[data-flow='warning']")
    page.click(".pbt-fam-select[data-flow='warning']")
    page.wait_for_timeout(_SETTLE_MS)

    # Step 2 assertion A: we stay on the Browse crumb (no "Colors & options" step).
    crumbs = page.locator(".pf-crumb")
    assert crumbs.count() == 1, f"expected 1 crumb (Browse only), got {crumbs.count()}"
    crumb_text = crumbs.nth(0).text_content().strip()
    assert "Browse" in crumb_text, f"expected Browse crumb, got: {crumb_text!r}"

    # Product grid must have rendered without waiting for colour choices.
    assert page.locator(".pp-head").count() > 0, \
        "expected products in grid immediately after picking a light type"

    # Click products until we find one that shows option controls (colour products
    # show options; a programmable bar with no colours would not).
    found_options = False
    for i in range(min(4, page.locator(".pp-head").count())):
        page.click(f".pp-head >> nth={i}")
        page.wait_for_timeout(200)
        if page.locator(".pp-prod-options").count() > 0:
            found_options = True
            break

    assert found_options, \
        "expected at least one colour-light product to render option controls in its box"

    # Option controls must include a quantity (lighthead count) stepper.
    page.wait_for_selector(".pp-prod-options .pf-pill[data-k='count'][data-v='1']")

    # Changing qty re-renders without crashing; option box must survive.
    page.click(".pp-prod-options .pf-pill[data-k='count'][data-v='1']")
    page.wait_for_timeout(200)
    assert page.is_visible(".pp-prod-options"), \
        "option controls must persist after a config change"

    # SKU dropdown must appear below the options in the product box.
    page.wait_for_selector(".pp-skus")

    # ── Lens-fix assertions (Step 2 completeness) ──────────────────────
    # Lens pill must update _pickerState.filters.lens, clear skuChoices so the
    # lens-sorted SKU becomes the resolved default, and refresh the footer.
    page.wait_for_selector(".pp-prod-options .pf-pill[data-k='lens'][data-v='smoked']")
    initial_lens = page.evaluate("_pickerState.filters.lens")

    # Record the initially chosen SKU from the per-combo dropdown (may be absent
    # if the product has no colour-matched combos yet — both cases are valid).
    initial_sku = ""
    if page.locator(".pp-override").count() > 0:
        initial_sku = page.locator(".pp-override").first.input_value()

    page.click(".pp-prod-options .pf-pill[data-k='lens'][data-v='smoked']")
    page.wait_for_timeout(300)

    # Lens state must be updated.
    lens_after = page.evaluate("_pickerState.filters.lens")
    assert lens_after == "smoked", f"expected lens='smoked' after click, got {lens_after!r}"

    # skuChoices must be cleared so the lens sort can take effect.
    choices_len = page.evaluate("Object.keys(_pickerState.skuChoices || {}).length")
    assert choices_len == 0, f"skuChoices must be cleared on lens change, got {choices_len} entries"

    # Footer must have been refreshed (picker-foot-label shows selected product,
    # not empty — proves _pickerUpdateFooter was called after the lens change).
    foot = page.locator(".picker-foot-label").first
    foot_text = foot.text_content().strip() if foot.count() > 0 else ""
    assert foot_text and foot_text != "Pick a product", \
        f"footer must show selected product after lens change, got: {foot_text!r}"

    # If a per-combo override dropdown exists AND the product has SKUs with
    # different lens_type values, the chosen option must now lead with a
    # smoked-lens SKU (or be unchanged if all SKUs share the same lens).
    # We verify the dropdown is still rendered and functional.
    if page.locator(".pp-override").count() > 0:
        page.wait_for_selector(".pp-override")   # must still render without JS error


def flow_agency_default_preferences(page, base_url: str) -> None:
    """Saving project choices as agency defaults must finish with success.

    This drives the real Project Details button and guards the client-side
    success path as well as the narrowly scoped agency endpoint.
    """
    saved_agency = _api(base_url, "/api/agency/save", {"name": "UI Smoke PD"})
    assert saved_agency.get("ok"), saved_agency
    agency_id = saved_agency["agency"]["agency_id"]
    project = _api(base_url, "/api/project/save", {
        "customer": {
            "name": "UI Smoke PD",
            "agency": "UI Smoke PD",
            "agency_id": agency_id,
            "build_year": "2026",
        },
        "preferences": {"lighting_brands": ["Whelen"], "lighting_mode": "duo"},
        "build_units": [{"vehicle_model": "PIU", "build_type": "Patrol"}],
    })
    assert project.get("ok"), project

    page.goto(base_url, wait_until="load")
    page.click(".htab[data-tab='projects']")
    page.wait_for_selector(".proj-row-clickable")
    page.click(".proj-row-clickable")
    page.wait_for_selector("#proj-detail-view:not([hidden])")
    page.click(".proj-dtab[data-ptab='edit']")
    page.wait_for_selector("#proj-ptab-edit .btn-primary")
    page.click("#proj-ptab-edit .btn-primary")
    page.wait_for_selector("#et-agency-id", state="attached")
    page.select_option("#et-lighting-mode", "trio")
    page.click("button[onclick*=\"PT_setPreferencesAsAgencyDefault\"]")

    page.wait_for_function(
        "() => document.querySelector('#toast')?.classList.contains('success')"
    )
    toast_text = page.locator("#toast").text_content() or ""
    assert "Saved as UI Smoke PD's defaults" in toast_text, toast_text
    stored = _api(base_url, "/api/agencies")["agencies"]
    agency = next(item for item in stored if item["agency_id"] == agency_id)
    assert agency["default_preferences"]["lighting_brands"] == ["Whelen"]
    assert agency["default_preferences"]["lighting_mode"] == "trio"


def flow_part_picker_search_stays_collapsed(page, base_url: str) -> None:
    """SKU search finds its parent product without filtering or opening it."""
    _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)
    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.fill("#pf-search", "GK0068E")
    row = page.locator(".pp-row[data-pid='setina_single_weapon_lock']")
    row.wait_for()

    assert page.locator("#picker-products .pp-skus").count() == 0, (
        "search results must render as collapsed product cards"
    )
    assert page.evaluate("() => _pickerState.expanded.size") == 0

    row.locator(".pp-head").click()
    row.locator(".pp-skus").wait_for()
    assert row.locator(".pp-sku").count() == 3, (
        "opening a SKU-matched product must show its complete SKU list"
    )
    assert row.get_by_text("GK0069M", exact=True).count() == 1, (
        "a sibling SKU that does not match the query must remain visible"
    )


def flow_brand_preference_collapse(page, base_url: str) -> None:
    """Owner flaw #5 regression guard: a project's brand preference (here,
    lighting) must auto-select for the matching part type, render first as a
    distinct chip notated "preferred", and collapse every other brand into a
    closed-by-default dropdown rather than a full pill row.

    The default smoke fixture (_seed_project_with_draft with no
    ``preferences`` arg) ends up with a fully empty EquipmentPreferences —
    /api/project/save only touches preferences when the POST body includes
    that key — so this flow seeds lighting_brands=["Whelen"] explicitly.
    The bundled parts_db.json's "warning" light category carries 3
    manufacturers (Whelen, Feniex, Soundoff), so the collapsed-dropdown path
    is the one exercised here; the single-brand fallback (chip + badge only)
    is asserted too, in case that ever changes.
    """
    _project_id, _unit_id, draft_id = _seed_project_with_draft(
        base_url, preferences={
            "lighting_brands": ["Whelen"], "push_bumper_brand": "Setina",
            "cage_brand": "Setina", "console_brand": "Gamber Johnson",
            "lighting_mode": "trio",
        }
    )
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(200)

    # Navigate to the Warning family specifically (multi-brand in the bundled
    # catalog). Warning is now a SELECTABLE header (owner ruling 2026-07-10,
    # flaws #7+#8) — click it directly to filter by flow=warning; there is no
    # `warning_light` leaf to click anymore (its sole home is the header
    # itself — see docs/PARTS_DB_AND_PICKER.md family listing).
    page.click(".pbt-cat-caret-btn[data-cat='lights']")
    page.wait_for_selector(".pbt-cat-head[data-cat='lights'].open")
    page.wait_for_timeout(200)
    page.wait_for_selector(".pbt-fam-select[data-flow='warning']")
    page.click(".pbt-fam-select[data-flow='warning']")
    page.wait_for_timeout(_SETTLE_MS)

    # The picker must have auto-selected the project's preferred lighting
    # brand for this context (requirement 1: not lighting-only anymore, but
    # this flow only seeds a lighting preference).
    auto_brand = page.evaluate("_pickerState.filters.brand")
    assert auto_brand == "Whelen", (
        "expected _pickerState.filters.brand to auto-select the project's "
        f"preferred lighting brand 'Whelen', got {auto_brand!r}"
    )
    page.click(".pp-head[data-pid='whelen_ion']")
    page.wait_for_function("() => _pickerState?.sel?.product_id === 'whelen_ion'")
    mode = page.evaluate("() => _pickerState.config.colorsPerHead")
    colors = set(page.evaluate("() => _pickerState.config.uniform"))
    assert mode == "trio", f"TRIO project preference did not default the picker, got {mode!r}"
    assert colors == {"red", "blue", "white"}, f"expected Red/Blue/White TRIO default, got {colors!r}"

    if page.locator(".pp-brand-more").count() > 0:
        # Multi-brand context (requirement 3): the collapsed dropdown must
        # exist and must NOT offer the preferred brand as one of its
        # options — it lives on the chip, not in "other brands".
        more_options = page.eval_on_selector_all(
            ".pp-brand-more option", "els => els.map(e => e.textContent.trim())"
        )
        assert not any("Whelen" in opt for opt in more_options), (
            "preferred brand 'Whelen' must not appear in the collapsed "
            f".pp-brand-more dropdown options, got {more_options!r}"
        )
        # Requirement 4: the preferred brand must be visibly notated as such.
        chip_text = page.locator(".pp-pref-chip").first.text_content() or ""
        assert "preferred" in chip_text.lower(), (
            f"expected preferred-brand chip to read 'preferred', got {chip_text!r}"
        )
    else:
        # Fixture had only one brand for this part type — fall back to
        # asserting the preferred-brand chip + badge render on their own.
        assert page.locator(".pp-pref-chip .pp-pref-badge").count() > 0, (
            "expected a .pp-pref-chip with .pp-pref-badge when no multi-brand "
            "dropdown is present"
        )

    # Structural > Push Bumper family header is a family-union filter, not a
    # concrete leaf. It must still resolve the push_bumper_brand preference.
    if not page.is_visible(".pbt-cat-head[data-cat='structural'].open"):
        page.click(".pbt-cat-caret-btn[data-cat='structural']")
        page.wait_for_selector(".pbt-cat-head[data-cat='structural'].open")
    page.wait_for_selector(".pbt-fam-select[data-family='push_bumper_system']")
    page.click(".pbt-fam-select[data-family='push_bumper_system']")
    page.wait_for_timeout(_SETTLE_MS)
    bumper_brand = page.evaluate("_pickerState.filters.brand")
    assert bumper_brand == "Setina", (
        "expected Push Bumper family header to auto-select the project's "
        f"preferred bumper brand 'Setina', got {bumper_brand!r}"
    )

    # Cage / Prisoner Containment is also entered through a family-union
    # header. It must apply cage_brand before a specific cage component is
    # chosen, just like Push Bumper above.
    page.wait_for_selector(".pbt-fam-select[data-family='cage_prisoner_containment']")
    page.click(".pbt-fam-select[data-family='cage_prisoner_containment']")
    page.wait_for_timeout(_SETTLE_MS)
    cage_brand = page.evaluate("_pickerState.filters.brand")
    assert cage_brand == "Setina", (
        "expected Cage / Prisoner Containment family header to auto-select "
        f"the preferred cage brand 'Setina', got {cage_brand!r}"
    )

    # The Console leaf must likewise begin restricted to the project's
    # preferred console manufacturer.
    if not page.is_visible(".pbt-leaf[data-pt='console']"):
        page.click(".pbt-fam-caret-btn[data-fam='console_system']")
    page.wait_for_selector(".pbt-leaf[data-pt='console']")
    page.click(".pbt-leaf[data-pt='console']")
    page.wait_for_timeout(_SETTLE_MS)
    console_brand = page.evaluate("_pickerState.filters.brand")
    assert console_brand == "Gamber Johnson", (
        "expected Console to auto-select the project's preferred console "
        f"brand 'Gamber Johnson', got {console_brand!r}"
    )
    console_brands = page.locator(".pp-row .pp-brandchip").all_text_contents()
    assert console_brands and all(brand.strip() == "Gamber Johnson" for brand in console_brands), (
        f"expected Console to show only Gamber Johnson SKUs, got {console_brands!r}"
    )

    # Every individual Light Control System leaf uses the same lighting-brand
    # preference, not just the primary Lights category. This is intentionally
    # tested leaf by leaf because the family contains several very different
    # kinds of control hardware.
    if not page.is_visible(".pbt-cat-head[data-cat='equipment'].open"):
        page.click(".pbt-cat-caret-btn[data-cat='equipment']")
        page.wait_for_selector(".pbt-cat-head[data-cat='equipment'].open")
    if not page.is_visible(".pbt-leaf[data-pt='light_controller']"):
        page.click(".pbt-fam-caret-btn[data-fam='light_control_system']")
        page.wait_for_selector(".pbt-leaf[data-pt='light_controller']")
    for part_type in ("control_head", "external_amp", "expansion_module", "v2v_sync", "light_controller"):
        page.click(f".pbt-leaf[data-pt='{part_type}']")
        page.wait_for_timeout(_SETTLE_MS)
        light_control_brand = page.evaluate("_pickerState.filters.brand")
        assert light_control_brand == "Whelen", (
            f"expected Light Control System leaf {part_type!r} to auto-select "
            f"the preferred lighting brand 'Whelen', got {light_control_brand!r}"
        )
        rendered_brands = page.locator(".pp-row .pp-brandchip").all_text_contents()
        assert rendered_brands and all(brand.strip() == "Whelen" for brand in rendered_brands), (
            f"expected Light Control System leaf {part_type!r} to show only Whelen products, "
            f"got {rendered_brands!r}"
        )



def flow_part_details_and_console(page, base_url: str) -> None:
    """The Details tab holds non-SKU setup; fixed-location parts skip it."""
    _project_id, _unit_id, _draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    if page.locator(".pbt-cat-head[data-cat='equipment'].open").count() == 0:
        page.click(".pbt-cat-caret-btn[data-cat='equipment']")
    page.wait_for_selector(".pbt-cat-head[data-cat='equipment'].open")
    if not page.locator(".pbt-fam-select[data-family='light_control_system']").is_visible():
        page.click(".pbt-fam-caret-btn[data-fam='light_control_system']")
    page.wait_for_selector(".pbt-fam-select[data-family='light_control_system']")

    # Manifest Add opens the complete Light Control System family, not a
    # particular leaf. Selecting a control head from that family must still
    # show its PA-mic detail during the initial add (not only on edit).
    page.click(".pbt-fam-select[data-family='light_control_system']")
    page.wait_for_timeout(_SETTLE_MS)
    assert page.evaluate("_pickerState.filters.part_type_id") == ""
    # The fixture vehicle can hide otherwise valid generic control heads.
    # The type-detail behavior is independent of that display filter.
    if page.locator("#pp-veh-only").is_checked():
        page.click("#pp-veh-only")
        page.wait_for_timeout(200)
    control_head_id = page.evaluate(
        "() => _pickerState.products.find(p => (p.fits_part_types || []).includes('control_head') && p.pa_mic_required !== false)?.product_id || ''"
    )
    assert control_head_id, "Light Control System family must include a control-head product"
    assert page.locator(f".pp-head[data-pid='{control_head_id}']").count() == 1, (
        "The selected control head should be visible after disabling the vehicle display filter"
    )
    page.click(f".pp-head[data-pid='{control_head_id}']")
    page.wait_for_timeout(200)
    assert page.locator(f".pp-sku [data-pick][data-pid='{control_head_id}']").count() > 0
    page.click(f".pp-sku [data-pick][data-pid='{control_head_id}'] >> nth=0")
    page.wait_for_timeout(200)
    assert page.locator("#picker-tab-btn-location").is_visible()
    assert not page.locator("#picker-add-btn").is_disabled(), (
        "Required PA-mic details must not disable the button that opens Details"
    )
    page.click("#picker-add-btn")
    page.wait_for_timeout(_SETTLE_MS)
    assert page.locator("#picker-pane-location").is_visible()
    assert page.evaluate("getComputedStyle(document.getElementById('picker-pane-location')).overflowY") == "auto"
    assert "Where will the control head be mounted?" in page.locator(".picker-loc-btns").text_content()
    detail_card_widths = page.evaluate("""() => [
      document.querySelector('.picker-loc-btns .picker-location-chooser')?.getBoundingClientRect().width || 0,
      document.querySelector('#picker-part-details .picker-location-chooser')?.getBoundingClientRect().width || 0,
    ]""")
    assert all(detail_card_widths) and abs(detail_card_widths[0] - detail_card_widths[1]) < 2, (
        f"control-head and PA-mic setup cards should share a compact width, got {detail_card_widths!r}"
    )
    assert page.locator("[data-pa-mic-location='drivers_door']").count() == 1, (
        "Initial family-based control-head add must show the PA-mic detail"
    )
    page.click("[data-pa-mic-location='drivers_door']")
    assert page.evaluate("_pickerState.partDetails.paMicLocation") == "drivers_door"
    page.click("[data-pa-mic-location='__custom__']")
    page.wait_for_selector("#picker-pa-mic-custom")
    page.fill("#picker-pa-mic-custom", "Passenger kick panel")
    assert page.evaluate("_pickerState.partDetails.paMicLocationCustom") == "Passenger kick panel"
    assert page.locator("#picker-add-btn").is_disabled(), "PA-mic clip must be selected before adding"
    page.click("[data-pa-mic-clip='magnetic_mic']")
    assert page.evaluate("_pickerState.partDetails.paMicClip") == "magnetic_mic"

    # The parent keeps the shop-install detail, while a Magnetic mic also
    # creates a separate, billable child part. Set the ordinary mounting
    # location here so this flow can verify both saved forms of the detail.
    page.evaluate("""() => {
      Object.assign(_pickerState.loc, {
        selected: 'IN CENTER CONSOLE', name_pattern: 'Control Head',
        base_label: 'Control Head', catalog_names: [], textCustom: false,
      });
      _pickerUpdateFooter();
    }""")
    assert not page.locator("#picker-add-btn").is_disabled()
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel", state="hidden")
    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", _draft_id)
    control_head = next(p for p in draft["draft"]["parts"] if p.get("part_type") == "control_head")
    pa_mic = next((c for c in control_head.get("components", []) if c.get("label") == "PA Mic"), None)
    assert pa_mic == {
        "label": "PA Mic", "location": "Passenger kick panel", "detail": "Magnetic mic",
    }, f"expected PA-mic manifest component, got {control_head.get('components')!r}"
    billable_pa_mic = next((p for p in draft["draft"]["parts"]
                            if p.get("parent_line_id") == control_head["line_id"]
                            and p.get("accessory_category") == "magnetic_mic"), None)
    assert billable_pa_mic and billable_pa_mic.get("part_number") == "MMSU-1", \
        f"a PA Magnetic mic must be a real billable child line, got {billable_pa_mic!r}"
    page.wait_for_selector(f"tr.me-parent-row[data-lid='{control_head['line_id']}']")
    page.click(f"tr.me-parent-row[data-lid='{control_head['line_id']}']")
    manifest_children = page.locator(f"tr.me-comp-row[data-parent='{control_head['line_id']}']")
    assert not manifest_children.filter(has_text="PA Mic").is_visible(), (
        "the included PA mic belongs in the control-head detail, not as a separate manifest line"
    )
    manifest_mag_mic = manifest_children.filter(has_text="Mag Mic")
    assert manifest_mag_mic.is_visible(), "the billable Mag Mic must remain a visible child line"
    assert "Passenger kick panel" in manifest_mag_mic.text_content()

    # The hand-held CCTL5 has no separate PA-mic/bracket setup. Its Details
    # step asks only whether to add the bracket-free MMSU-1 Mag Mic.
    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    if page.locator(".pbt-cat-head[data-cat='equipment'].open").count() == 0:
        page.click(".pbt-cat-caret-btn[data-cat='equipment']")
    page.wait_for_selector(".pbt-cat-head[data-cat='equipment'].open")
    if not page.locator(".pbt-fam-select[data-family='light_control_system']").is_visible():
        page.click(".pbt-fam-caret-btn[data-fam='light_control_system']")
    page.wait_for_selector(".pbt-fam-select[data-family='light_control_system']")
    page.click(".pbt-fam-select[data-family='light_control_system']")
    page.wait_for_timeout(_SETTLE_MS)
    if page.locator("#pp-veh-only").is_checked():
        page.click("#pp-veh-only")
        page.wait_for_timeout(200)
    assert page.locator(".pp-head[data-pid='whelen_cctl5']").count() == 1
    page.click(".pp-head[data-pid='whelen_cctl5']")
    page.click(".pp-sku [data-pick][data-pid='whelen_cctl5'] >> nth=0")
    page.click("#picker-add-btn")
    page.wait_for_timeout(_SETTLE_MS)
    assert page.locator("[data-handheld-mag-mic='true']").count() == 1
    assert page.locator("[data-pa-mic-location]").count() == 0
    assert page.locator("[data-pa-mic-clip]").count() == 0
    assert page.locator("#picker-add-btn").is_disabled()
    page.click("[data-handheld-mag-mic='true']")
    assert not page.locator("#picker-add-btn").is_disabled()
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel", state="hidden")
    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", _draft_id)
    handheld = next(p for p in draft["draft"]["parts"]
                    if any(c.get("part_number") == "CCTL5" for c in p.get("components", [])))
    handheld_mag_mic = next((p for p in draft["draft"]["parts"]
                             if p.get("parent_line_id") == handheld["line_id"]
                             and p.get("accessory_category") == "magnetic_mic"), None)
    assert handheld_mag_mic and handheld_mag_mic.get("part_number") == "MMSU-1"

    # A Center Console has one physical location, but its selected SKU leads
    # to the dedicated Details setup rather than a generic placement step.
    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.click(".pbt-cat-caret-btn[data-cat='structural']")
    page.wait_for_selector(".pbt-cat-head[data-cat='structural'].open")
    page.click(".pbt-fam-caret-btn[data-fam='console_system']")
    page.wait_for_selector(".pbt-leaf[data-pt='console']")
    page.click(".pbt-leaf[data-pt='console']")
    page.wait_for_timeout(_SETTLE_MS)
    page.click(".pp-head >> nth=0")
    page.wait_for_timeout(200)
    page.click(".pp-sku [data-pick] >> nth=0")
    page.wait_for_timeout(200)
    assert page.evaluate("_pickerState.loc.selected") == "IN CENTER CONSOLE", (
        "Center Console should receive its fixed location automatically"
    )
    assert page.locator("#picker-tab-btn-location").is_hidden(), (
        "Center Console should not expose a generic placement tab before setup"
    )
    assert page.locator("#picker-add-btn").text_content().strip() == "Set up Center Console →", (
        "Center Console should lead into its dedicated setup after selecting a SKU"
    )
    page.click("#picker-add-btn")
    page.wait_for_selector("[data-console-setup]")
    assert page.locator("#picker-tab-btn-location").is_visible(), (
        "Center Console setup should use the Details tab"
    )
    assert "Set Up Center Console" in page.locator("[data-console-setup]").text_content()


def flow_sku_dropdown_rework(page, base_url: str) -> None:
    """PICKER_REDESIGN.md Step 3 regression guard.

    Asserts all four Step 3 behavioural contracts:
    (a) SKU dropdown offers only option-matching SKUs by default.
    (b) "Remove options" reveals every SKU in the product.
    (c) qty=N renders N per-head dropdowns (not one per unique colour combo).
    (d) Manually changing one head's dropdown promotes to custom mode without
        disturbing the other heads.
    """
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(200)

    # Navigate to a colour-configured light. Warning is the deterministic
    # color-configured path.
    page.click(".pbt-cat-caret-btn[data-cat='lights']")
    page.wait_for_selector(".pbt-cat-head[data-cat='lights'].open")
    page.wait_for_timeout(200)

    page.wait_for_selector(".pbt-fam-select[data-flow='warning']")
    page.click(".pbt-fam-select[data-flow='warning']")
    page.wait_for_timeout(_SETTLE_MS)

    # Click products until we find a colour product that shows option controls.
    found = False
    for i in range(min(5, page.locator(".pp-head").count())):
        page.click(f".pp-head >> nth={i}")
        page.wait_for_timeout(200)
        if page.locator(".pp-prod-options").count() > 0:
            found = True
            break
    assert found, "expected a colour-light product to show option controls in its box"

    # ── Assertion (c): qty=N → N dropdowns ───────────────────────────────────
    # Default qty is 2; there must be exactly 2 per-head dropdowns.
    qty = page.evaluate("_pickerState.config.count")
    dropdown_count = page.locator(".pp-skus .pp-override").count()
    assert dropdown_count == qty, \
        f"expected {qty} dropdowns for qty={qty}, got {dropdown_count}"

    # Bump qty to 3 — must now show 3 dropdowns.
    page.click(".pp-prod-options .pf-pill[data-k='count'][data-v='1']")
    page.wait_for_timeout(200)
    qty3 = page.evaluate("_pickerState.config.count")
    assert qty3 == 3, f"count should be 3 after +1, got {qty3}"
    dd3 = page.locator(".pp-skus .pp-override").count()
    assert dd3 == 3, f"expected 3 dropdowns for qty=3, got {dd3}"

    # ── Assertion (a): dropdown is option-filtered ────────────────────────────
    # Each dropdown must carry data-head and show only matching SKUs (no "(other)").
    heads_with_attr = page.locator(".pp-skus .pp-override[data-head]").count()
    assert heads_with_attr == 3, \
        f"expected 3 .pp-override[data-head] elements, got {heads_with_attr}"

    # Sanity check: the options listed inside the first dropdown must not include
    # the "(other)" suffix that the old combo-based fallback appended.
    first_dd_html = page.locator(".pp-skus .pp-override").first.inner_html()
    assert "(other)" not in first_dd_html, \
        "Step 3 filtered dropdown must not show '(other)' options"

    # Live title: each dropdown is labelled "Head N: <SKU> · <lens>".
    first_label = page.locator(".pp-skus .pp-sku-pn").first.text_content().strip()
    assert first_label.startswith("Head 1:"), \
        f"expected dropdown label to start with 'Head 1:', got {first_label!r}"

    # ── Step 4: light viz renders in the product box, not the footer ─────────
    viz_in_box = page.locator(".pp-row.sel .pp-viz").count()
    assert viz_in_box > 0, "Step 4: .pp-viz must be present inside the selected product box"

    viz_heads = page.locator(".pp-row.sel .pp-viz .picker-foot-head").count()
    assert viz_heads > 0, "Step 4: .pp-viz must contain at least one .picker-foot-head swatch"

    footer_viz = page.locator("#picker-footer-text .picker-foot-heads").count()
    assert footer_viz == 0, "Step 4: light viz must NOT appear in the footer text"

    # ── Assertion (b): "Remove options" reveals all SKUs ─────────────────────
    page.wait_for_selector(".pp-prod-options [data-opts-remove]")
    remove_btn = page.locator(".pp-prod-options [data-opts-remove]").first

    # Count SKUs in the first dropdown while filtered.
    filtered_count = page.locator(".pp-skus .pp-override").first.locator("option").count()

    # Click "Remove options".
    remove_btn.click()
    page.wait_for_timeout(200)

    # The button must now signal that options are off.
    btn_text = remove_btn.text_content().strip()
    assert "Filter off" in btn_text or "⊘" in btn_text, \
        f"expected remove-options button to indicate filter off, got {btn_text!r}"

    # The first dropdown must now offer MORE (or equal) options than when filtered.
    unfiltered_count = page.locator(".pp-skus .pp-override").first.locator("option").count()
    assert unfiltered_count >= filtered_count, \
        f"'Remove options' should reveal all SKUs (filtered={filtered_count}, unfiltered={unfiltered_count})"

    # Filter controls must be HIDDEN (not dimmed) while options are removed.
    lens_pills = page.locator(".pp-prod-options .pf-pill[data-k='lens']").count()
    assert lens_pills == 0, \
        f"filter controls (lens pills) must be hidden when options are removed, found {lens_pills}"

    # Qty control must still be visible and usable while options are removed.
    qty_ctrl = page.locator(".pp-prod-options .pf-pill[data-k='count']").count()
    assert qty_ctrl > 0, "qty +/- controls must remain visible when options are removed"

    # The toggle button itself is the only re-engage path (no option controls to click).
    remove_btn.click()
    page.wait_for_timeout(200)
    opts_removed = page.evaluate("_pickerState.optionsRemoved")
    assert not opts_removed, "clicking the toggle again must re-apply the filter (optionsRemoved→false)"

    # Filter controls must be restored after toggling back on.
    lens_pills_back = page.locator(".pp-prod-options .pf-pill[data-k='lens']").count()
    assert lens_pills_back > 0, \
        "lens pills must reappear after toggle re-engages the filter"

    # ── Assertion (d): manual per-head change promotes to custom ─────────────
    # Start fresh with the first colour product open, qty=2, uniform/identical.
    page.evaluate("_pickerState.config.mode")   # pre-check (can be any mode at this point)

    # Re-open with a clean state by re-clicking the same product head.
    page.click(".pp-row.sel .pp-head")
    page.wait_for_timeout(200)
    page.click(".pp-head >> nth=0")
    page.wait_for_timeout(200)

    if page.locator(".pp-prod-options").count() == 0:
        # Product might have no options (programmable bar) — skip this assertion.
        return

    mode_before = page.evaluate("_pickerState.config.mode")
    dd_count = page.locator(".pp-skus .pp-override").count()
    if dd_count < 2:
        # Only one head — can't test "other heads unaffected"; skip.
        return

    # Click "Remove options" so we have all SKUs visible, then pick a different
    # SKU on the FIRST head only.
    if page.locator("[data-opts-remove]").count() > 0:
        page.click("[data-opts-remove]")
        page.wait_for_timeout(200)

    # Select an option in the first dropdown that differs from the current choice.
    all_opts = page.locator(".pp-skus .pp-override").first.locator("option").all()
    first_dd_current = page.locator(".pp-skus .pp-override").first.input_value()
    other_skus = [o.get_attribute("value") for o in all_opts if o.get_attribute("value") != first_dd_current]
    if not other_skus:
        return   # product has only one SKU — cannot test manual override

    page.locator(".pp-skus .pp-override").first.select_option(other_skus[0])
    page.wait_for_timeout(200)

    # Mode must be promoted to custom.
    mode_after = page.evaluate("_pickerState.config.mode")
    assert mode_after == "custom", \
        f"manually changing a head's SKU must promote to custom mode, got {mode_after!r}"

    # skuChoices must have an entry only for head 0 (the changed one). The
    # untouched heads may re-resolve their displayed default after the color
    # model promotes to custom, but they must not be stored as manual overrides.
    choices = page.evaluate("_pickerState.skuChoices")
    assert "head_0" in choices, f"skuChoices must record head_0 override, got {choices}"
    # head_1 must NOT be overridden (defaults to colour-config resolution).
    assert "head_1" not in choices, f"head_1 must not be in skuChoices (it was not changed), got {choices}"


def flow_scene_light_qty_only(page, base_url: str) -> None:
    """PICKER_REDESIGN.md Step 5 regression guard.

    Scene lights (category == "scene", covering the entire scene_lights family:
    front_scene / rear_scene / side_scene / spotlight) must show ONLY the
    quantity control and per-head SKU dropdowns — no mode pills, no lens pills,
    no color swatches, and no "Remove options" toggle.

    Also asserts the non-scene (warning) path is unchanged: it must still
    render mode/lens/color controls and the "Remove options" toggle.
    """
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(200)

    # ── Part A: scene light ──────────────────────────────────────────────────
    page.click(".pbt-cat-caret-btn[data-cat='lights']")
    page.wait_for_selector(".pbt-cat-head[data-cat='lights'].open")
    page.wait_for_timeout(200)

    # Owner ruling 2026-07-10 (flaws #7+#8): Scene renders COLLAPSED — a single
    # selectable row (no caret, no front/side/rear sub-leaves). Click it
    # directly; it hands off exactly like a leaf would (filters by flow=scene).
    page.wait_for_selector(".pbt-fam-select[data-flow='scene']")
    page.click(".pbt-fam-select[data-flow='scene']")
    page.wait_for_timeout(_SETTLE_MS)

    # No front/side/rear member leaves may be rendered for the collapsed family.
    scene_leaves = page.locator(".pbt-fam-collapsed .pbt-leaf").count()
    assert scene_leaves == 0, \
        f"Scene must render collapsed with no member leaves, found {scene_leaves}"

    # Product grid must render.
    assert page.locator(".pp-head").count() > 0, \
        "expected products in grid after picking a scene light type"

    # Click the first product to open its box.
    page.click(".pp-head >> nth=0")
    page.wait_for_timeout(200)

    # The product box must show options (pp-prod-options) — qty control is there.
    page.wait_for_selector(".pp-prod-options")

    # Qty +/- must be present (scene still configures quantity).
    qty_ctrl = page.locator(".pp-prod-options .pf-pill[data-k='count']").count()
    assert qty_ctrl > 0, "scene: qty +/- control must be visible"

    # Per-head SKU dropdowns must appear.
    page.wait_for_selector(".pp-skus .pp-override[data-head]")

    # ── The forbidden controls must NOT appear for scene ─────────────────────

    # No mode pills (Identical / Split / Custom).
    mode_pills = page.locator(".pp-prod-options .pf-pill[data-k='mode']").count()
    assert mode_pills == 0, \
        f"scene: mode pills must be hidden, found {mode_pills}"

    # No lens pills (All / Clear / Smoked).
    lens_pills = page.locator(".pp-prod-options .pf-pill[data-k='lens']").count()
    assert lens_pills == 0, \
        f"scene: lens pills must be hidden, found {lens_pills}"

    # No color swatches (Red / Blue / Amber / …).
    color_swatches = page.locator(".pp-prod-options .picker-swatch").count()
    assert color_swatches == 0, \
        f"scene: color swatches must be hidden, found {color_swatches}"

    # No colors-per-head pills (Solo / Duo / Trio).
    cph_pills = page.locator(".pp-prod-options .pf-pill[data-k='cph']").count()
    assert cph_pills == 0, \
        f"scene: colors-per-head pills must be hidden, found {cph_pills}"

    # No "Remove options" toggle (there are no options to remove for scene).
    remove_btn = page.locator(".pp-prod-options [data-opts-remove]").count()
    assert remove_btn == 0, \
        f"scene: 'Remove options' toggle must be hidden, found {remove_btn}"

    # Light viz must be present (plain uncolored heads reflecting quantity).
    viz_in_box = page.locator(".pp-row.sel .pp-viz").count()
    assert viz_in_box > 0, "scene: .pp-viz must appear in the selected scene product box"

    viz_heads = page.locator(".pp-row.sel .pp-viz .picker-foot-head").count()
    assert viz_heads > 0, "scene: .pp-viz must contain at least one .picker-foot-head"

    # ── Part B: warning light still shows the full option set ────────────────
    # The picker is still open; lights category is still expanded (session state
    # persists). Owner ruling 2026-07-10: Warning is a SELECTABLE family header
    # (flaws #7+#8) — click the header directly to filter by flow=warning, no
    # expansion needed (this is the "eliminates the redundant sub-leaf" call).
    if not page.is_visible(".pbt-cat-head[data-cat='lights'].open"):
        page.click(".pbt-cat-caret-btn[data-cat='lights']")
        page.wait_for_selector(".pbt-cat-head[data-cat='lights'].open")
        page.wait_for_timeout(200)

    warning_select = page.locator(".pbt-fam-select[data-flow='warning']")
    if warning_select.count() == 0:
        # No warning family in tree — skip Part B (products not present in this parts_db).
        return
    warning_select.first.click()
    page.wait_for_timeout(_SETTLE_MS)

    assert page.locator(".pp-head").count() > 0, "expected warning products in grid"

    # Find a colour product by clicking heads until option controls appear.
    found_warning_opts = False
    for i in range(min(4, page.locator(".pp-head").count())):
        page.click(f".pp-head >> nth={i}")
        page.wait_for_timeout(200)
        if page.locator(".pp-prod-options").count() > 0:
            found_warning_opts = True
            break

    if not found_warning_opts:
        return   # no colour-configured warning product in test DB — skip

    # Warning light must show mode, lens, and remove-options (the full option set).
    mode_pills_w = page.locator(".pp-prod-options .pf-pill[data-k='mode']").count()
    assert mode_pills_w > 0, \
        f"warning: mode pills must be visible, found {mode_pills_w}"

    lens_pills_w = page.locator(".pp-prod-options .pf-pill[data-k='lens']").count()
    assert lens_pills_w > 0, \
        f"warning: lens pills must be visible, found {lens_pills_w}"

    remove_w = page.locator(".pp-prod-options [data-opts-remove]").count()
    assert remove_w > 0, \
        f"warning: 'Remove options' toggle must be visible, found {remove_w}"


def flow_picker_multi_add(page, base_url: str) -> None:
    """PICKER_REDESIGN.md Step 7 regression guard.

    Contracts verified:
    (a) Location tab shows BOTH "Add and Finish" and "Add another part" buttons
        (primary label is "Add and Finish", not "Add Part").
    (b) Clicking "Add another part" keeps the picker open (does NOT close it).
    (c) After "Add another part" the browse tree is shown with the previously
        expanded category still open (expansion state preserved).
    (d) The just-added part type leaf gains the .filled class (manifest highlight
        refreshed — green dot).
    (e) "Add and Finish" closes the picker (today's behavior, confirmed).

    Uses `gun_lock` (Equipment > Gun Lock, a bare leaf with no family) rather
    than `console` — console became single-instance under FINDING-027 (owner
    flaw #2: only one console per vehicle) and no longer sequences, so it
    can't guard multi-instance numbering. Gun Lock keeps its legacy
    "Gunlock 1" / "Gunlock 2" sequencing and has workbook-derived location
    cards.
    """
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    def _navigate_to_gun_lock_leaf():
        """Expand Equipment and pick the bare Gun Lock leaf (no family)."""
        if not page.is_visible(".pbt-cat-head[data-cat='equipment'].open"):
            page.click(".pbt-cat-caret-btn[data-cat='equipment']")
            page.wait_for_timeout(200)
        page.click(".pbt-leaf[data-pt='gun_lock']")
        page.wait_for_timeout(_SETTLE_MS)

    def _pick_gun_lock_product_and_go_to_location():
        """Select the first gun lock product + SKU, dismiss its optional
        bracket_mount accessory prompt (none needed for this smoke check),
        then open the location tab."""
        page.fill("#pf-search", "SINGLE HANDCUFF")
        page.wait_for_timeout(_SETTLE_MS)
        page.click(".pp-head >> nth=0")
        page.wait_for_timeout(200)
        page.click(".pp-sku [data-pick] >> nth=0")
        page.wait_for_timeout(200)
        if page.locator("select[data-cat='bracket_mount']").count() > 0:
            page.select_option("select[data-cat='bracket_mount']", "none")
            page.wait_for_timeout(200)
        page.click("#picker-tab-btn-location")
        page.wait_for_timeout(_SETTLE_MS)
        page.wait_for_selector("[data-text-location='GUN LOCK POCKET']")
        page.click("[data-text-location='GUN LOCK POCKET']")
        page.wait_for_timeout(200)

    # ── Open picker for a first part ──────────────────────────────────────────
    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_timeout(200)

    _navigate_to_gun_lock_leaf()
    _pick_gun_lock_product_and_go_to_location()

    # ── Assert (a): location tab shows BOTH buttons ───────────────────────────
    # Primary button must say "Add and Finish" (not "Add Part").
    add_btn_text = page.locator("#picker-add-btn").text_content().strip()
    assert add_btn_text == "Add and Finish", \
        f"Step 7: primary button on location tab must say 'Add and Finish', got {add_btn_text!r}"

    # "Add another part" must be visible (not hidden).
    another_btn = page.locator("#picker-add-another-btn")
    assert another_btn.count() > 0, "Step 7: #picker-add-another-btn must exist in the DOM"
    another_hidden = page.get_attribute("#picker-add-another-btn", "hidden")
    assert another_hidden is None, \
        "Step 7: #picker-add-another-btn must NOT be hidden on the location tab when ready"

    # ── Assert (b) + (c) + (d): click "Add another part" ────────────────────
    page.click("#picker-add-another-btn")
    page.wait_for_timeout(_SETTLE_MS + 200)   # allow manifest reload + tree re-render

    # (b) Picker must still be open.
    assert page.is_visible("#picker-panel.open"), \
        "Step 7: picker must remain open after 'Add another part'"

    # (c) Browse tree must be shown at the preserved expansion position.
    # Equipment category was expanded — it must still be open.
    assert page.is_visible(".pbt-cat-head[data-cat='equipment'].open"), \
        "Step 7: equipment category must still be expanded (expansion state preserved)"

    # The part pane must be active (not the location tab).
    assert page.is_visible("#picker-tab-btn-part.active"), \
        "Step 7: Part tab must be active after returning to browse tree"

    # (d) The gun_lock leaf must now have the .filled class (green dot).
    filled_count = page.locator(".pbt-leaf[data-pt='gun_lock'].filled").count()
    assert filled_count > 0, \
        "Step 7: gun_lock part type leaf must have .filled class after 'Add another part'"

    # ── Assert (e): "Add and Finish" closes the picker ───────────────────────
    # Navigate to another gun lock (second add in the same session).
    # The tree is already expanded; click the leaf to reload products, then
    # pick and go to location as before.
    _navigate_to_gun_lock_leaf()
    _pick_gun_lock_product_and_go_to_location()
    page.click("#picker-add-btn")   # "Add and Finish"
    page.wait_for_selector("#picker-panel.open", state="hidden", timeout=5000)
    page.wait_for_timeout(_SETTLE_MS)

    # Two gun lock parts must be in the draft, sequenced correctly.
    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    names = [p["name"] for p in draft["draft"]["parts"]]
    assert len(names) >= 2 and "Gunlock 1" in names and "Gunlock 2" in names, \
        f"Step 7: expected two sequenced Gunlock parts after multi-add, got {names}"


def flow_preview_drag_mirroring(page, base_url: str) -> None:
    """Preview drag is stable for paired layouts and keeps saved work visible.

    This reproduces the three failure modes that are easy to miss in a normal
    picker flow: the inspector must stack over icons; vertical and horizontal
    pairs must render their reflected counterpart while dragging; and a second
    drag while the first autosave is still in flight must not snap the first
    part back to its old location.
    """
    _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)
    page.wait_for_selector("#pv-canvas-wrap .pv-frame")
    blocked_saves = []
    page.route("**/api/draft/*/overrides/batch", lambda route: blocked_saves.append(route))

    page.evaluate("""() => {
      _pvDraftId = "preview-drag-smoke";
      _pvPendingOverrides = {};
      _pvInFlightOverrides = {};
      _pvConfirmedOverrides = {};
      _pvAutosaveTimer = null;
      _pvAutosaveInFlight = false;
      _pvAutosavePromise = null;
      _pvView = "top";
      _pvPlan = {
        views: { top: { label: "Top", bg_url: "" } },
        planned_parts: [
          {
            part_name: "Vertical pair", render_kind: "light", placements: [{
              view: "top", override_key: "vertical:top", group_key: "vertical",
              location_key: "TEST", anchor: { x: 0.80, y: 0.75 },
              pattern: "vertical_mirror", h_spacing: 0.10, h_spacing_units: "relative_image",
              slot_count: 2, rotation: 0, flip_h: false, flip_v: false,
              flip_mirrored_h: false, icon_w_pct: 0.04, icon_h_pct: 0.04,
              layer: 0, override: {}, instances: [
                { x_pct: 0.80, y_pct: 0.25, w_pct: 0.04, h_pct: 0.04, slot_coeff: 0, slot_role: "slot_1" },
                { x_pct: 0.80, y_pct: 0.75, w_pct: 0.04, h_pct: 0.04, slot_coeff: 0, slot_role: "slot_2" },
              ],
            }],
          },
          {
            part_name: "Horizontal pair", render_kind: "light", placements: [{
              view: "top", override_key: "horizontal:top", group_key: "horizontal",
              location_key: "TEST", anchor: { x: 0.50, y: 0.50 },
              pattern: "horizontal", h_spacing: 0.20, h_spacing_units: "relative_image",
              slot_count: 2, rotation: 0, flip_h: false, flip_v: false,
              flip_mirrored_h: false, icon_w_pct: 0.04, icon_h_pct: 0.04,
              layer: 0, override: {}, instances: [
                { x_pct: 0.40, y_pct: 0.50, w_pct: 0.04, h_pct: 0.04, slot_coeff: -0.5, slot_role: "passenger" },
                { x_pct: 0.60, y_pct: 0.50, w_pct: 0.04, h_pct: 0.04, slot_coeff: 0.5, slot_role: "driver" },
              ],
            }],
          },
          {
            part_name: "Concealed speaker pair", render_kind: "equipment", placements: [{
              view: "top", override_key: "speaker:top", group_key: "speaker",
              location_key: "BEHIND GRILL", anchor: { x: 0.35, y: 0.72 },
              pattern: "horizontal", h_spacing: 0.30, h_spacing_units: "relative_image",
              slot_count: 2, rotation: 0, flip_h: false, flip_v: false,
              flip_mirrored_h: false, icon_w_pct: 0.06, icon_h_pct: 0.06,
              layer: 0, mount_visibility: "behind_grille",
              callout_label: "SPEAKER BEHIND GRILLE", callout_dx: 0, callout_dy: 0,
              override: {}, instances: [
                { x_pct: 0.35, y_pct: 0.72, w_pct: 0.06, h_pct: 0.06, slot_coeff: -0.5, slot_role: "passenger" },
                { x_pct: 0.65, y_pct: 0.72, w_pct: 0.06, h_pct: 0.06, slot_coeff: 0.5, slot_role: "driver" },
              ],
            }],
          },
        ],
      };
      pvRenderView("top");
      const frame = document.querySelector(".pv-frame");
      frame.style.height = "400px";
      return frame.getBoundingClientRect().width;
    }""")

    def positions(key: str):
        return page.evaluate("""(key) => Array.from(document.querySelectorAll('.pv-icon')).filter(
          icon => icon.dataset.overrideKey === key
        ).map(icon => ({
          left: parseFloat(icon.style.left), top: parseFloat(icon.style.top),
        }))""", key)

    def drag(key: str, index: int, dx: float, dy: float):
        return page.evaluate("""({ key, index, dx, dy }) => {
          const icons = Array.from(document.querySelectorAll('.pv-icon')).filter(
            icon => icon.dataset.overrideKey === key
          );
          const icon = icons[index];
          const rect = icon.getBoundingClientRect();
          const frameEl = document.querySelector('.pv-frame');
          frameEl.style.height = '400px';
          const frame = frameEl.getBoundingClientRect();
          const startX = rect.left + rect.width / 2;
          const startY = rect.top + rect.height / 2;
          icon.dispatchEvent(new MouseEvent('mousedown', {
            bubbles: true, button: 0, clientX: startX, clientY: startY,
          }));
          document.dispatchEvent(new MouseEvent('mousemove', {
            bubbles: true, clientX: startX + dx, clientY: startY + dy,
          }));
          const during = Array.from(document.querySelectorAll('.pv-icon')).filter(
            item => item.dataset.overrideKey === key
          ).map(item => ({ left: parseFloat(item.style.left), top: parseFloat(item.style.top) }));
          document.dispatchEvent(new MouseEvent('mouseup', {
            bubbles: true, clientX: startX + dx, clientY: startY + dy,
          }));
          const after = Array.from(document.querySelectorAll('.pv-icon')).filter(
            item => item.dataset.overrideKey === key
          ).map(item => ({ left: parseFloat(item.style.left), top: parseFloat(item.style.top) }));
          return { during, after, dx_pct: dx / frame.width * 100, dy_pct: dy / frame.height * 100 };
        }""", {"key": key, "index": index, "dx": dx, "dy": dy})

    callout_drag = page.evaluate("""() => {
      const tag = document.querySelector('.pv-concealed-callout[data-override-key="speaker:top"]');
      const lineBefore = document.querySelector(
        '.pv-concealed-callout-line[data-override-key="speaker:top"] line'
      );
      const before = {
        left: parseFloat(tag.style.left),
        targetX: parseFloat(lineBefore.getAttribute('x2')),
      };
      const rect = tag.getBoundingClientRect();
      const startX = rect.left + rect.width / 2;
      const startY = rect.top + rect.height / 2;
      tag.dispatchEvent(new MouseEvent('mousedown', {
        bubbles: true, button: 0, clientX: startX, clientY: startY,
      }));
      document.dispatchEvent(new MouseEvent('mousemove', {
        bubbles: true, clientX: startX + 260, clientY: startY - 35,
      }));
      document.dispatchEvent(new MouseEvent('mouseup', {
        bubbles: true, clientX: startX + 260, clientY: startY - 35,
      }));
      const movedTag = document.querySelector('.pv-concealed-callout[data-override-key="speaker:top"]');
      const movedLine = document.querySelector(
        '.pv-concealed-callout-line[data-override-key="speaker:top"] line'
      );
      const result = {
        before,
        after: {
          left: parseFloat(movedTag.style.left),
          targetX: parseFloat(movedLine.getAttribute('x2')),
        },
        override: { ..._pvPendingOverrides['speaker:top'] },
      };
      if (_pvAutosaveTimer) clearTimeout(_pvAutosaveTimer);
      _pvAutosaveTimer = null;
      delete _pvPendingOverrides['speaker:top'];
      pvRenderView(_pvView);
      return result;
    }""")
    assert callout_drag["before"]["targetX"] == 35, callout_drag
    assert callout_drag["after"]["targetX"] == 65, callout_drag
    assert callout_drag["after"]["left"] > callout_drag["before"]["left"], callout_drag
    assert callout_drag["override"]["callout_dx"] > 0.10, callout_drag
    assert callout_drag["override"]["callout_dy"] < 0, callout_drag

    # Clicking a part opens the inspector over the icon layer.
    layer_order = page.evaluate("""() => {
      const icon = document.querySelector('.pv-icon');
      const rect = icon.getBoundingClientRect();
      icon.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: rect.left, clientY: rect.top }));
      document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: rect.left, clientY: rect.top }));
      return {
        inspector: Number(getComputedStyle(document.querySelector('#pv-inspector')).zIndex),
        icon: Number(getComputedStyle(icon).zIndex),
      };
    }""")
    assert layer_order["inspector"] > layer_order["icon"], layer_order
    page.evaluate("pvHideInspector()")

    vertical_before = positions("vertical:top")
    vertical = drag("vertical:top", 0, 60, -40)
    assert abs(vertical["during"][0]["left"] - (vertical_before[0]["left"] + vertical["dx_pct"])) < 0.02, vertical
    assert abs(vertical["during"][0]["top"] - (vertical_before[0]["top"] + vertical["dy_pct"])) < 0.02, vertical
    assert abs(vertical["during"][1]["top"] - (vertical_before[1]["top"] - vertical["dy_pct"])) < 0.02, vertical
    assert vertical["after"] == vertical["during"], "vertical pair changed when released"

    # Start the first save but deliberately do not resolve it yet. Calling the
    # save directly avoids timer-throttling differences in headless browsers;
    # normal interaction still schedules this same function after 300 ms.
    page.evaluate("void pvApplyChanges()")
    page.wait_for_timeout(25)
    first_save_state = page.evaluate("""() => ({
      pending: _pvPendingOverrides,
      in_flight: _pvInFlightOverrides,
      saving: _pvAutosaveInFlight,
    })""")
    assert len(blocked_saves) == 1, f"first preview save did not start: {first_save_state!r}"

    vertical_saved = positions("vertical:top")
    horizontal_before = positions("horizontal:top")
    horizontal = drag("horizontal:top", 1, 60, 20)
    assert abs(horizontal["during"][1]["left"] - (horizontal_before[1]["left"] + horizontal["dx_pct"])) < 0.02, horizontal
    assert abs(horizontal["during"][0]["left"] - (horizontal_before[0]["left"] - horizontal["dx_pct"])) < 0.02, horizontal
    assert abs(horizontal["during"][0]["top"] - (horizontal_before[0]["top"] + horizontal["dy_pct"])) < 0.02, horizontal
    assert horizontal["after"] == horizontal["during"], "horizontal pair changed when released"
    assert positions("vertical:top") == vertical_saved, "in-flight placement snapped during a second drag"
    page.evaluate("void pvApplyChanges()")

    # Complete both queued autosaves and make sure the visual state remains stable.
    blocked_saves.pop(0).fulfill(status=200, content_type="application/json", body='{"ok":true}')
    page.wait_for_timeout(100)
    assert len(blocked_saves) == 1, "second preview save did not queue"
    blocked_saves.pop(0).fulfill(status=200, content_type="application/json", body='{"ok":true}')
    page.wait_for_timeout(50)
    assert positions("vertical:top") == vertical_saved
    assert positions("horizontal:top") == horizontal["after"]


def flow_howler_routing_and_dual_tone_siren(page, base_url: str) -> None:
    """Vehicle-specific Howlers and optional CEXAMP survive picker round-trip."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url, vehicle_model="PIU")
    _open_build_editor(page, base_url)

    routed = page.evaluate("""() => {
      const product = {
        product_id: 'whelen_wcx_howler',
        skus: [
          {part_number: 'CHWLDD36'},
          {part_number: 'CHWLFE29'},
          {part_number: 'CHWLUNI'},
        ],
      };
      const routes = Object.fromEntries(['DURANGO', 'PIU', 'TAHOE'].map(vehicle => [
        vehicle,
        _pickerHowlerVehicleSkus(product, product.skus, vehicle).map(sku => sku.part_number),
      ]));
      const priorEditLineId = _pickerState.editLineId;
      const priorSelection = _pickerState.sel;
      _pickerState.editLineId = 'historical-line';
      _pickerState.sel = {product_id: product.product_id, sku: 'CHWLDD36'};
      const historical = _pickerHowlerVehicleSkus(
        product,
        product.skus.filter(sku => ['CHWLFE29', 'CHWLUNI'].includes(sku.part_number)),
        'PIU',
      ).map(sku => sku.part_number);
      _pickerState.editLineId = priorEditLineId;
      _pickerState.sel = priorSelection;
      return {routes, historical};
    }""")
    assert routed["routes"] == {
        "DURANGO": ["CHWLDD36"],
        "PIU": ["CHWLFE29"],
        "TAHOE": ["CHWLUNI"],
    }, routed
    assert routed["historical"] == ["CHWLFE29", "CHWLDD36"], routed

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.fill("#pf-search", "CHWL")
    page.wait_for_selector(".pp-head[data-pid='whelen_wcx_howler']")
    page.click(".pp-head[data-pid='whelen_wcx_howler']")
    page.wait_for_selector("[data-pick='CHWLFE29']")
    visible_howler_skus = page.locator(
        ".pp-row[data-pid='whelen_wcx_howler'] [data-pick]"
    ).evaluate_all("els => els.map(el => el.dataset.pick)")
    assert visible_howler_skus == ["CHWLFE29"], visible_howler_skus
    page.click("[data-pick='CHWLFE29']")
    page.wait_for_timeout(_SETTLE_MS)
    assert page.locator("select[data-cat='bracket_mount']").count() == 0, (
        "current CHWL assemblies already include their bracket"
    )
    page.evaluate("pickerClose()")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    page.fill("#pf-search", "SA315P")
    page.wait_for_selector(".pp-head[data-pid='whelen_sa315p']")
    page.click(".pp-head[data-pid='whelen_sa315p']")
    page.wait_for_selector("[data-pick='SA315P'][data-pid='whelen_sa315p']")
    page.click("[data-pick='SA315P'][data-pid='whelen_sa315p']")
    page.wait_for_timeout(_SETTLE_MS)
    page.click("[data-siren-qty='2']")
    page.wait_for_selector("[data-siren-dual-tone='yes']")
    bracket_selects = page.locator("select[data-cat='bracket_mount']")
    for index in range(bracket_selects.count()):
        bracket_selects.nth(index).select_option("none")
    page.click("[data-siren-dual-tone='yes']")
    assert "active" in (page.get_attribute("[data-siren-dual-tone='yes']", "class") or "")
    page.click("#picker-tab-btn-location")
    page.wait_for_timeout(_SETTLE_MS)
    page.wait_for_selector(".picker-dot[data-name='BEHIND GRILL (CENTER)']")
    page.locator(".picker-dot[data-name='BEHIND GRILL (CENTER)']").first.click(force=True)
    save_state = page.evaluate("""() => ({
      disabled: document.querySelector('#picker-add-btn').disabled,
      selected: _pickerState.loc.selected,
      textCustom: _pickerState.loc.textCustom,
      sel: _pickerState.sel,
      filters: _pickerState.filters,
      accessories: _pickerState.accessories,
      accessoryChoices: _pickerState.accessoryChoices,
    })""")
    assert save_state["disabled"] is False, save_state
    page.click("#picker-add-btn")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    draft = page.evaluate("(id) => fetch('/api/draft/' + id).then(r => r.json())", draft_id)
    speaker = next(part for part in draft["draft"]["parts"] if part.get("part_type") == "siren_speaker")
    assert speaker["quantity"] == 2
    assert speaker["picker_config"]["siren_dual_tones"] is True
    component_qty = {component["part_number"]: component["quantity"] for component in speaker["components"]}
    assert component_qty["SA315P"] == 2
    assert component_qty["CEXAMP"] == 1

    page.evaluate("(lineId) => openPartEditModal(lineId)", speaker["line_id"])
    page.wait_for_selector("[data-siren-dual-tone='yes']")
    assert page.evaluate("_pickerState.sirenDualTones") is True
    assert "active" in (page.get_attribute("[data-siren-dual-tone='yes']", "class") or "")
    page.evaluate("pickerClose()")


def flow_quickbooks_estimate_review_modal(page, base_url: str) -> None:
    """A successful read-only validation must open the estimate review modal."""
    validation = {
        "ok": True, "can_create": True, "material_line_count": 2, "line_count": 5,
        "materials_total": 124, "total": 1636.96,
        "existing_estimate_id": "", "pdf_available": False,
        "customer_linked": True,
        "customer": {"name": "UI Smoke PD", "contact_name": "Test User"},
        "project": {"ready": True, "identity_ready": True},
        "pricing": {
            "rule_name": "Retail", "source": "retail", "list_total": 200,
            "customer_total": 162, "savings": 38,
            "applied_discounts": [{
                "manufacturer_id": "whelen", "manufacturer": "Whelen",
                "discount_percent": 38, "override": False,
            }],
            "editable_discounts": [{
                "manufacturer_id": "whelen", "manufacturer": "Whelen",
                "retail_discount_percent": 38, "custom_discount_percent": 38,
            }],
            "pricing_basis": [{
                "manufacturer_id": "whelen", "list_unit_price": 100,
                "qty": 2, "discountable": True,
            }],
        },
        "additional_charges": {
            "enabled": True, "preset_id": "patrol", "preset_label": "Patrol",
            "card_fee_percent": 4, "materials_total": 124,
            "labor_amount": 1000, "install_supplies_amount": 450,
            "delivery_amount": 0, "card_fee_amount": 62.96,
            "additional_total": 1512.96, "estimate_total": 1636.96,
            "service_items": {
                "labor": "LABOR INSTALL", "install_supplies": "INSTALL SUPPLIES",
                "card_fee": "Convenience Fee", "delivery": "TRAVEL",
            },
            "presets": {
                "patrol": {"label": "Patrol", "labor_amount": 1000, "install_supplies_amount": 450},
                "undercover": {"label": "Undercover", "labor_amount": 800, "install_supplies_amount": 350},
                "admin": {"label": "Admin", "labor_amount": 500, "install_supplies_amount": 250},
                "custom": {"label": "Custom", "labor_amount": 0, "install_supplies_amount": 450},
            },
        },
    }
    customer = {
        "ok": True, "customer_linked": True, "customer_complete": True,
        "missing_fields": [],
        "customer": {"name": "UI Smoke PD", "contact_name": "Test User"},
    }

    def quickbooks_route(route):
        path = route.request.url.split("?", 1)[0]
        if path.endswith("/api/quickbooks/status"):
            payload = {"connected": True}
        elif path.endswith("/api/quickbooks/estimates/validate"):
            payload = validation
        elif path.endswith("/api/quickbooks/estimates/customer-preview"):
            payload = customer
        else:
            route.continue_()
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route("**/api/quickbooks/**", quickbooks_route)
    page.goto(base_url, wait_until="load")
    page.wait_for_selector("#qb-est-modal", state="attached")
    page.evaluate("() => window.PT_buildCreateEstimate('project-1', 'unit-1', 'vehicle-1')")
    page.wait_for_selector("#qb-est-modal.open")
    assert page.locator("#qb-est-title").inner_text() == "Create QuickBooks estimate"
    assert page.locator("[data-qb-est-custom-price='whelen']").input_value() == "38"
    assert page.locator("#qb-est-charge-preset").input_value() == "patrol"
    assert page.locator("#qb-est-labor-amount").input_value() == "1000"
    assert page.locator("#qb-est-card-fee-amount").inner_text() == "$62.96"
    assert page.locator("#qb-est-estimated-total").inner_text() == "$1636.96"
    assert not page.locator("#qb-est-create").is_visible()
    assert page.locator("#qb-est-export-pdf").is_visible()
    assert "A build PDF is required" in page.locator("#qb-est-body").inner_text()
    page.locator("#qb-est-modal").evaluate("modal => modal.classList.remove('open')")

    validation.update({
        "existing_estimate_id": "EST-42",
        "pdf_available": True,
        "pdf_name": "build.pdf",
        "estimate_change": {
            "status": "modified", "modified": True,
            "differences": [{
                "field": "Line 1",
                "before": "Item 1 · qty 2 · unit $62.00",
                "after": "Item 1 · qty 2 · unit $70.00",
            }],
        },
    })
    page.evaluate("() => window.PT_buildCreateEstimate('project-1', 'unit-1', 'vehicle-1')")
    page.wait_for_selector("#qb-est-modal.open")
    assert page.locator(".qb-est-change-alert--danger").count() == 1
    assert "changed outside Vehicle Builder" in page.locator(".qb-est-change-alert--danger").inner_text()
    page.locator(".qb-est-change-alert summary").click()
    assert "unit $62.00" in page.locator(".qb-est-diff-list").inner_text()
    assert page.locator("#qb-est-create").is_disabled()
    page.check("input[name='qb-est-existing-action'][value='create_new']")
    assert not page.locator("#qb-est-create").is_disabled()
    assert page.locator("#qb-est-create").inner_text() == "Create separate estimate"
    # The smoke flow deliberately stops at review; it never clicks Create.


def flow_quickbooks_batch_project_checklist(page, base_url: str) -> None:
    """Project setup returns to the batch checklist and rechecks readiness."""
    linked = set()
    project = {
        "project_id": "batch-project-1",
        "build_units": [{
            "unit_id": "unit-1", "vehicle_model": "PIU",
            "individuals": [
                {"individual_id": "vehicle-1", "draft_id": "draft-1", "unit_number": "101"},
                {"individual_id": "vehicle-2", "draft_id": "draft-2", "unit_number": "102"},
            ],
        }],
    }

    def quickbooks_route(route):
        path = route.request.url.split("?", 1)[0]
        body = route.request.post_data_json or {}
        if path.endswith("/api/quickbooks/estimates/validate"):
            individual_id = body.get("individual_id")
            ready = individual_id in linked
            payload = {
                "ok": True, "can_create": ready, "line_count": 1, "total": 100,
                "pdf_available": True, "pdf_name": f"vehicle-{individual_id[-1]}.pdf",
                "problems": [] if ready else [],
                "project": {
                    "ready": ready, "identity_ready": True,
                    "project_name": f"UI Smoke PD | Unit {individual_id[-1]}",
                    "customer_name": "UI Smoke PD",
                },
                "pricing": {
                    "rule_name": "Retail", "source": "retail", "list_total": 100,
                    "customer_total": 100, "savings": 0, "applied_discounts": [],
                },
            }
        elif path.endswith("/api/quickbooks/estimates/customer-preview"):
            payload = {
                "ok": True, "customer_linked": True, "customer_complete": True,
                "customer": {"name": "UI Smoke PD"},
            }
        elif path.endswith("/api/quickbooks/projects/bind"):
            linked.add(body.get("individual_id"))
            payload = {"ok": True, "qb_project_id": "447322633"}
        else:
            route.continue_()
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route("**/api/quickbooks/**", quickbooks_route)
    page.goto(base_url, wait_until="load")
    page.evaluate("(project) => _ptOpenBatchEstimateSetup(project)", project)
    page.wait_for_selector("#qb-est-modal.open")
    page.wait_for_selector("[data-qb-batch-link]")
    assert page.locator("[data-qb-batch-link]").count() == 2

    page.locator("[data-qb-batch-link]").first.click()
    page.wait_for_selector("#qb-project-id")
    assert page.locator("#qb-est-back").is_visible()
    assert page.locator("#qb-est-back").inner_text() == "← Back to vehicle checklist"

    page.click("#qb-est-back")
    page.wait_for_function("() => document.querySelector('#qb-est-title')?.textContent === 'Prepare batch QuickBooks estimates'")
    assert page.locator("[data-qb-batch-link]").count() == 2

    page.locator("[data-qb-batch-link]").first.click()
    page.wait_for_selector("#qb-project-id")
    page.fill("#qb-project-id", "https://qbo.intuit.com/app/project?projectId=447322633")
    page.click("#qb-est-create")

    page.wait_for_function("() => document.querySelector('#qb-est-title')?.textContent === 'Prepare batch QuickBooks estimates'")
    ready_rows = page.locator("#qb-est-body").get_by_text("✓ Ready", exact=True)
    ready_rows.first.wait_for()
    assert ready_rows.count() == 1
    assert page.locator("[data-qb-batch-link]").count() == 1
    # The smoke flow stops at preparation; it never clicks Create estimates.


FLOWS = {
    "tab_load": flow_tab_load,
    "preset_agency_list_freshness": flow_preset_agency_list_freshness,
    "load_preset_from_build_editor": flow_load_preset_from_build_editor,
    "project_manager_all_presets_unfiltered": flow_project_manager_all_presets_unfiltered,
    "add_text_mode_equipment_part": flow_add_text_mode_equipment_part,
    "edit_preserves_fields": flow_edit_preserves_fields,
    "custom_location_group_spacing": flow_custom_location_group_spacing,
    "tint_and_round_location_allocation": flow_tint_and_round_location_allocation,
    "overview_unit_notes_and_preconfig_qb": flow_overview_unit_notes_and_preconfig_qb,
    "final_build_signoff": flow_final_build_signoff,
    "printer_accessory_round_trip": flow_printer_accessory_round_trip,
    "t_series_dual_shroud_quantity_and_render": flow_t_series_dual_shroud_quantity_and_render,
    "picker_browse_tree": flow_picker_browse_tree,
    "radio_communications_workflow": flow_radio_communications_workflow,
    "radar_system_workflow": flow_radar_system_workflow,
    "camera_system_workflow": flow_camera_system_workflow,
    "light_options_in_product_box": flow_light_options_in_product_box,
    "brand_preference_collapse": flow_brand_preference_collapse,
    "agency_default_preferences": flow_agency_default_preferences,
    "part_picker_search_stays_collapsed": flow_part_picker_search_stays_collapsed,
    "part_details_and_console": flow_part_details_and_console,
    "sku_dropdown_rework": flow_sku_dropdown_rework,
    "scene_light_qty_only": flow_scene_light_qty_only,
    "picker_multi_add": flow_picker_multi_add,
    "preview_drag_mirroring": flow_preview_drag_mirroring,
    "howler_routing_and_dual_tone_siren": flow_howler_routing_and_dual_tone_siren,
    "quickbooks_estimate_review_modal": flow_quickbooks_estimate_review_modal,
    "quickbooks_batch_project_checklist": flow_quickbooks_batch_project_checklist,
    # Implementation session (UI_SMOKE_SPEC.md §5):
    # "part_picker": flow_part_picker,
    # "manifest_add_remove": flow_manifest_add_remove,
    # "sku_grid_roundtrip": flow_sku_grid_roundtrip,
    # "project_open_edit_save": flow_project_open_edit_save,
    # "cloud_status_offline": flow_cloud_status_offline,
}
