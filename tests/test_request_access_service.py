from __future__ import annotations

from dataclasses import replace

from dtm_buildsheet.app.adapters import wiring
from dtm_buildsheet.app.adapters.interfaces import UserIdentity
from dtm_buildsheet.app.adapters.wiring import build_local_bundle, set_active_bundle
from dtm_buildsheet.app.services.request_access_service import (
    authorize_request,
    required_capabilities,
)
from dtm_buildsheet.domain.operations_policy import Capability


class _Identity:
    def __init__(self, *roles: str) -> None:
        self.user = UserIdentity(
            user_id="entra-user",
            display_name="Role Test",
            email="role@example.invalid",
            provider="m365",
            roles=frozenset(roles),
        )

    def current_user(self):
        return self.user

    def is_signed_in(self):
        return True

    def signin(self, *, force_account_picker=False):
        del force_account_picker
        return self.user

    def signout(self):
        self.user = None


def _set_role(monkeypatch, *roles: str) -> None:
    set_active_bundle(replace(build_local_bundle(), identity=_Identity(*roles)))
    monkeypatch.setattr(wiring, "_cloud_flag_enabled", lambda: True)


def test_request_capability_map_separates_read_edit_lifecycle_and_admin():
    assert required_capabilities("GET", "/api/projects") == frozenset({Capability.PROJECTS_VIEW})
    assert required_capabilities("POST", "/api/project/save") == frozenset({Capability.PROJECTS_EDIT})
    assert required_capabilities(
        "POST", "/api/project/p1/lifecycle"
    ) == frozenset({Capability.PROJECTS_LIFECYCLE_UPDATE})
    assert required_capabilities(
        "POST", "/api/build/show-folder"
    ) == frozenset({Capability.PROJECTS_VIEW})
    assert required_capabilities(
        "POST", "/api/quickbooks/estimates/bind"
    ) == frozenset({Capability.ESTIMATES_MANAGE, Capability.SETTINGS_ADVANCED_MANAGE})
    assert required_capabilities(
        "POST", "/api/quickbooks/link-item"
    ) == frozenset({Capability.SETTINGS_ADVANCED_MANAGE})
    assert required_capabilities("POST", "/api/operations/status") == frozenset()


def test_shop_can_read_builder_data_but_cannot_mutate_projects(monkeypatch):
    _set_role(monkeypatch, "ShopEditor")

    assert authorize_request("GET", "/api/projects").allowed is True
    assert authorize_request("POST", "/api/build/show-folder").allowed is True
    denied = authorize_request("POST", "/api/project/save")
    assert (denied.allowed, denied.status) == (False, 403)
    assert authorize_request("POST", "/api/draft/save").allowed is False
    assert authorize_request("POST", "/api/quickbooks/estimates/bind").allowed is False


def test_builder_can_edit_projects_estimates_vehicle_availability_and_parts(monkeypatch):
    _set_role(monkeypatch, "BuilderEditor")

    assert authorize_request("POST", "/api/project/save").allowed is True
    assert authorize_request("POST", "/api/project/p1/lifecycle").allowed is True
    assert authorize_request("POST", "/api/quickbooks/estimates/bind").allowed is True
    assert authorize_request("POST", "/api/catalog/save").allowed is False


def test_parts_editor_can_connect_quickbooks_and_manage_estimate_connections(monkeypatch):
    _set_role(monkeypatch, "PartsEditor")

    assert authorize_request("GET", "/api/quickbooks/auth-url").allowed is True
    assert authorize_request("POST", "/api/quickbooks/estimates/search").allowed is True
    assert authorize_request("POST", "/api/quickbooks/estimates/bind").allowed is True
    assert authorize_request("POST", "/api/project/save").allowed is False
    assert authorize_request("POST", "/api/quickbooks/link-item").allowed is False


def test_app_admin_retains_advanced_mutation_access(monkeypatch):
    _set_role(monkeypatch, "AppAdmin")

    assert authorize_request("POST", "/api/catalog/save").allowed is True
    assert authorize_request("DELETE", "/api/agency/a1").allowed is True
