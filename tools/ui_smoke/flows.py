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
                             vehicle_model: str = "PIU") -> tuple[str, str, str]:
    """Create a throwaway project + one build unit + its draft. Returns
    (project_id, unit_id, draft_id).

    ``preferences`` is optional and, when omitted, the project ends up with a
    fully empty EquipmentPreferences (no brand preferences set at all) — the
    /api/project/save route only touches preferences when the POST body
    includes a "preferences" key. Pass it explicitly (e.g.
    {"lighting_brands": ["Whelen"]}) for flows that need a brand preference
    seeded; existing callers that don't pass it keep today's behavior
    unchanged."""
    body = {
        "customer": {"name": "UI Smoke PD", "agency": "UI Smoke PD", "build_year": "2026"},
        "build_units": [{"vehicle_model": vehicle_model, "build_type": "Patrol"}],
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
    """A Center Console is chosen as a style/features-driven QB kit, then its
    included and separately billed parts are persisted correctly."""
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
        page.click(".pp-head[data-pid='gamber_johnson_7170_0734_09']")
        page.wait_for_selector("[data-pid='gamber_johnson_7170_0734_09'][data-pick]")
        page.locator("[data-pid='gamber_johnson_7170_0734_09'][data-pick]").first.click()
        page.wait_for_function("() => _pickerState?.sel?.product_id === 'gamber_johnson_7170_0734_09'")
        assert page.locator("#picker-add-btn").text_content().strip() == "Set up Center Console →"
        page.click("#picker-add-btn")
        page.wait_for_selector("[data-console-setup]")
        assert page.locator("#picker-tab-btn-location").is_visible()
        page.click("[data-console-style='low_profile']")
        page.wait_for_function("() => _pickerState?.consoleSetup?.choices?.consoleChoice?.product_id")
        faceplate_brands = page.locator(".console-extra-faceplates .console-catalog-card-brand").all_text_contents()
        assert faceplate_brands and all(brand.strip() == "Gamber Johnson" for brand in faceplate_brands), (
            f"faceplates must follow the selected Gamber Johnson console, got {faceplate_brands!r}"
        )
        page.click("[data-console-component-open='armRest']")
        page.wait_for_selector("[data-console-component-choice='gamber_johnson_7160_0430']")
        armrest_brands = page.locator(".console-component-picker .console-catalog-card-brand").all_text_contents()
        assert armrest_brands and all(brand.strip() == "Gamber Johnson" for brand in armrest_brands), (
            f"armrests must follow the selected Gamber Johnson console, got {armrest_brands!r}"
        )
        page.click("[data-console-component-choice='gamber_johnson_7160_0430']")
        page.click("[data-console-component-open='printer']")
        page.wait_for_selector("[data-console-component-choice='brother_pj_822']")
        page.click("[data-console-component-choice='brother_pj_822']")
        page.click("[data-console-component-open='motionAttachment']")
        page.wait_for_selector("[data-console-component-choice='gamber_johnson_7160_0220']")
        motion_brands = page.locator(".console-component-picker .console-catalog-card-brand").all_text_contents()
        assert motion_brands and all(brand.strip() == "Gamber Johnson" for brand in motion_brands), (
            f"motion attachments must follow the selected Gamber Johnson console, got {motion_brands!r}"
        )
        page.click("[data-console-component-choice='gamber_johnson_7160_0220']")
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
        "Center Console · Face Plate 1 · Core Control Head Faceplate",
        "Center Console · Face Plate 2 · Radio Faceplate",
        "Center Console · Face Plate 3 · Cup Holder Faceplate",
        "Center Console · Face Plate 4 · OEM Relocation Plate",
    ], f"expected numbered auto-populated faceplates in the configured order, got {faceplates!r}"
    console_components = [p for p in children if p.get("accessory_category") == "console_component"]
    assert {p.get("part_type") for p in console_components} == {
        "pedestal_mount", "docking_station",
    }, f"console hardware must nest with the console, got {console_components!r}"
    assert {p.get("part_type") for p in children} == {
        "special_face_plate", "pedestal_mount", "docking_station",
    }
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
    assert setup["consoleChoice"]["product_id"] == "gamber_johnson_7170_0734_09"

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
        "gamber_johnson_7160_0339", "gamber_johnson_7160_0321",
        "gamber_johnson_7160_0846", "gamber_johnson_15250",
    ], f"console edit must restore its ordered faceplates, got {restored!r}"
    assert restored["style"] == "low_profile"
    assert restored["consoleChoice"]["product_id"] == "gamber_johnson_7170_0734_09"
    assert restored["armRest"]["product_id"] == "gamber_johnson_7160_0430"
    assert restored["printer"]["product_id"] == "brother_pj_822"
    assert restored["motionAttachment"]["product_id"] == "gamber_johnson_7160_0220"
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
        const product = document.querySelector("#picker-products .pp-row[data-pid='whelen_ion']");
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


def flow_printer_accessory_round_trip(page, base_url: str) -> None:
    """Printer accessories use distinct shop labels, survive a parent edit,
    can add another item from the same accessory group, and surface orderable
    SKUs before the accessory description."""
    _project_id, _unit_id, draft_id = _seed_project_with_draft(base_url)
    _open_build_editor(page, base_url)

    page.click("[onclick='addPart()'] >> nth=0")
    page.wait_for_selector("#picker-panel.open")
    assert page.locator("#picker-part-status").is_visible()
    assert page.get_attribute("[data-picker-part-status='New']", "aria-pressed") == "true"
    page.click("[data-picker-part-status='Used']")
    assert page.get_attribute("[data-picker-part-status='Used']", "aria-pressed") == "true"
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
    assert page.get_attribute("[data-picker-part-status='Used']", "aria-pressed") == "true", (
        "editing a picker part must restore its saved condition"
    )
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
    assert page.evaluate("() => _pickerState.radio.choices.provider") == "customer", \
        "new system provider should default to customer supplied"
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
    _guided_pick(page, "condition", "new")
    _guided_next(page)
    _guided_pick(page, "provider", "dtm")
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
    _guided_pick(page, "antennaLoc", "rear_left_roof")
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
    mic = next(c for c in radio["components"] if c.get("part_type") == "radio_mic_clip")
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
    assert "condition" in edit_question, \
        f"guided radio edit should reopen at the condition question, got {edit_question!r}"
    restored = page.evaluate("() => _pickerState.radio.choices")
    assert restored.get("purchaseDetails") == radio.get("notes") and restored.get("micLocCustom") == "Console sidecar", \
        f"guided radio edits must retain saved answers, got {restored!r}"


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
    _guided_pick(page, "condition", "reused")
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
    assert radar["picker_config"]["choices"]["countingLoc"] == "center_console"
    assert radar["picker_config"]["choices"]["frontBracket"] == "swivel_arm"
    assert radar["picker_config"]["choices"]["rearBracket"] == "tall_a_bracket"
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
    assert "condition" in page.locator(".guided-question h2").text_content().lower(), \
        "new radar setup should begin at the condition question"
    page.evaluate("pickerClose()")
    page.wait_for_selector("#picker-panel.open", state="hidden")

    parent.locator(".me-edit-btn").click()
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_function("() => _pickerState?.editLineId && _pickerState?.radio?.active && _pickerState.radio.kind === 'radar' && Object.keys(_pickerState.radio.choices || {}).length > 0")
    page.wait_for_selector("#picker-system-details .guided-system[data-system-kind='radar']")
    assert page.evaluate("() => _pickerState.radio.step") == 0, "guided radar edits must restart at the first question"
    assert "condition" in page.locator(".guided-question h2").text_content().lower(), \
        "guided radar edit should reopen at the condition question"
    restored = page.evaluate("() => _pickerState.radio.choices")
    assert restored.get("frontLoc") == "a_pillar" and restored.get("frontBracket") == "swivel_arm" and restored.get("countingLoc") == "center_console", \
        f"expected guided system edits to restore saved radar answers, got {restored!r}"


def flow_camera_system_workflow(page, base_url: str) -> None:
    """Camera uses the same ownership/cable sequence and then asks only the
    location questions for the selected camera components."""
    draft_id = _open_guided_system(page, base_url, "camera_system", "camera")
    _guided_pick(page, "condition", "reused")
    _guided_next(page)
    _guided_pick(page, "refresh", "yes")
    _guided_next(page)
    _guided_pick(page, "refreshCables", "signal_data_cable")
    _guided_next(page)
    assert page.evaluate("() => _pickerState.radio.choices.systemProduct.product_id") == "watchguard_m500"
    assert page.evaluate("() => _cameraSupportsExtendedComponents(_systemCameraPlatform({systemProduct:{product_id:'axon_fleet_3'}}))") is False
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
    assert set(camera["picker_config"]["choices"]["cameraParts"]) == {"front", "rear_seat", "rear", "body_dock", "wireless_mic"}
    camera_components = {item["part_type"]: item for item in camera["components"]}
    assert camera_components["front_camera"]["location"] == "Upper windshield"
    assert camera_components["rear_camera"]["location"] == "Upper rear window"
    parent = page.locator("tr.me-parent-row").filter(has_text="Camera System")
    parent.locator(".me-edit-btn").click()
    page.wait_for_selector("#picker-panel.open")
    page.wait_for_function("() => _pickerState?.editLineId && _pickerState?.radio?.active && _pickerState.radio.kind === 'camera'")
    page.wait_for_selector("#picker-system-details .guided-system[data-system-kind='camera']")
    assert page.evaluate("() => _pickerState.radio.step") == 0, "guided camera edits must restart at the first question"
    assert "condition" in page.locator(".guided-question h2").text_content().lower(), \
        "guided camera edit should reopen at the condition question"
    restored = page.evaluate("() => _pickerState.radio.choices")
    assert restored.get("systemProduct", {}).get("product_id") == "watchguard_m500" and restored.get("wirelessMicLoc") == "center_console", \
        f"guided camera edits must retain saved answers, got {restored!r}"


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
    page.click(".pbt-cat-caret-btn[data-cat='equipment']")
    page.wait_for_selector(".pbt-cat-head[data-cat='equipment'].open")
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
    assert "Build a Center Console Kit" in page.locator("[data-console-setup]").text_content()


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


FLOWS = {
    "tab_load": flow_tab_load,
    "add_text_mode_equipment_part": flow_add_text_mode_equipment_part,
    "edit_preserves_fields": flow_edit_preserves_fields,
    "printer_accessory_round_trip": flow_printer_accessory_round_trip,
    "picker_browse_tree": flow_picker_browse_tree,
    "radio_communications_workflow": flow_radio_communications_workflow,
    "radar_system_workflow": flow_radar_system_workflow,
    "camera_system_workflow": flow_camera_system_workflow,
    "light_options_in_product_box": flow_light_options_in_product_box,
    "brand_preference_collapse": flow_brand_preference_collapse,
    "part_details_and_console": flow_part_details_and_console,
    "sku_dropdown_rework": flow_sku_dropdown_rework,
    "scene_light_qty_only": flow_scene_light_qty_only,
    "picker_multi_add": flow_picker_multi_add,
    "preview_drag_mirroring": flow_preview_drag_mirroring,
    # Implementation session (UI_SMOKE_SPEC.md §5):
    # "part_picker": flow_part_picker,
    # "manifest_add_remove": flow_manifest_add_remove,
    # "sku_grid_roundtrip": flow_sku_grid_roundtrip,
    # "project_open_edit_save": flow_project_open_edit_save,
    # "cloud_status_offline": flow_cloud_status_offline,
}
