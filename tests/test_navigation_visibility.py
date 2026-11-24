from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.routes import config as config_routes
from dtm_buildsheet.app.services import config_service
from dtm_buildsheet.app.services.request_access_service import required_capabilities
from dtm_buildsheet.config.schemas import REQUIRED_CONFIG_FILES, validate_config_payload
from dtm_buildsheet.domain.operations_policy import Capability


ROOT = Path(__file__).parents[1]
UI_ROOT = ROOT / "src" / "dtm_buildsheet" / "ui"
CONFIG_ROOT = ROOT / "src" / "dtm_buildsheet" / "resources" / "config"


def test_navigation_settings_are_shared_and_exposed_through_admin_routes():
    assert "navigation_settings.json" in REQUIRED_CONFIG_FILES
    assert config_routes.GET_ROUTES["/api/navigation-settings"] == "navigation_settings.json"
    assert config_routes.POST_ROUTES["/api/navigation-settings/save"] == "navigation_settings.json"
    assert config_service.CONFIG_PROPOSAL_CATEGORY["navigation_settings.json"] == "general"
    assert "navigation_settings.json" in config_service._DIRECT_MIRROR_FILES  # noqa: SLF001
    assert required_capabilities("POST", "/api/navigation-settings/save") == frozenset({
        Capability.SETTINGS_ADVANCED_MANAGE,
    })


def test_navigation_settings_validate_known_tabs_and_keep_canonical_order():
    result = validate_config_payload("navigation_settings.json", {
        "schema_version": 1,
        "hidden_tabs": ["pricing", "forms", "pricing"],
    })
    assert result["hidden_tabs"] == ["forms", "pricing"]

    with pytest.raises(ValueError, match="unknown tab"):
        validate_config_payload("navigation_settings.json", {"hidden_tabs": ["settings"]})


def test_navigation_settings_default_and_ui_keep_features_reversible():
    bundled = json.loads((CONFIG_ROOT / "navigation_settings.json").read_text(encoding="utf-8"))
    html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
    tabs = (UI_ROOT / "js" / "tabs.js").read_text(encoding="utf-8")
    api_script = (UI_ROOT / "js" / "api.js").read_text(encoding="utf-8")

    assert bundled["schema_version"] == 1
    assert set(bundled["hidden_tabs"]) <= {
        "projects", "forms", "vehicle-sales", "calendar", "operations", "pricing",
    }
    assert 'data-stab="navigation"' in html
    assert 'id="stab-navigation"' in html
    assert 'data-navigation-tab="projects"' in html
    assert 'data-navigation-tab="pricing"' in html
    assert 'data-navigation-tab="settings"' not in html
    assert 'tab === "settings" ||' in tabs
    assert 'if (!_appTabConfiguredVisible(tab)) return false' in tabs
    assert 'api("/api/navigation-settings")' in tabs
    assert 'apiSave("/api/navigation-settings/save", next)' in tabs
    assert 'loadNavigationSettings().catch' in api_script
    assert "Hiding a workspace does not remove its feature or data" in html
