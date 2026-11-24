from pathlib import Path


UI_ROOT = Path(__file__).parents[1] / "src" / "dtm_buildsheet" / "ui"


def test_settings_use_one_icon_only_header_action_beside_profile_badge():
    html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
    styles = (UI_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'class="header-actions"' in html
    assert 'id="settings-header-tab" data-tab="settings"' in html
    assert 'title="Settings" aria-label="Settings"' in html
    assert 'id="general-settings-header-tab"' not in html
    assert 'id="advanced-settings-header-tab"' not in html
    assert html.index('id="settings-header-tab"') < html.index('id="cloud-status"')
    assert ".header-settings-button" in styles
    assert ".header-settings-button[hidden]{display:none}" in styles


def test_settings_workspace_exposes_both_capability_gated_groups():
    html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
    tabs = (UI_ROOT / "js" / "tabs.js").read_text(encoding="utf-8")

    assert 'id="settings-nav-general"' in html
    assert 'id="settings-nav-advanced"' in html
    assert 'id="stab-bar-general"' in html
    assert 'id="stab-bar-advanced"' in html
    assert 'settings: "settings-header-tab"' in tabs
    assert 'if (tab === "settings")' in tabs
    assert 'appHasCapability("settings.advanced.manage")' in tabs
    assert 'generalGroup.hidden = !(' in tabs
    assert "advancedGroup.hidden = !canManageAdvanced" in tabs
    assert '$("tab-settings").hidden = t !== "settings"' in tabs
    assert '$("stab-bar-general").hidden' not in tabs
    assert '$("stab-bar-advanced").hidden' not in tabs


def test_quickbooks_returns_to_combined_settings_workspace():
    sources = [
        UI_ROOT / "js" / "api.js",
        UI_ROOT / "js" / "settings" / "quickbooks.js",
        UI_ROOT / "js" / "settings" / "quickbooks_production_preview.js",
    ]

    for source in sources:
        script = source.read_text(encoding="utf-8")
        assert 'switchTab("settings")' in script
        assert 'switchTab("general-settings")' not in script
        assert 'switchTab("advanced-settings")' not in script
