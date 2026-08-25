"""Desktop central-client selection, token audience, and fail-closed tests."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dtm_buildsheet.app.adapters.quickbooks.builder_api_config import (
    BuilderApiConfig,
    load_builder_api_config,
)
from dtm_buildsheet.app.adapters.quickbooks.builder_api_token import (
    EntraBuilderApiTokenProvider,
)
from dtm_buildsheet.app.adapters.quickbooks.central_client import (
    CentralQuickBooksClient,
    CentralQuickBooksClientError,
)
from dtm_buildsheet.app.adapters.quickbooks.gateway import QuickBooksGatewayError
from dtm_buildsheet.app.services import (
    qb_sync_service,
    quickbooks_gateway_service,
    quickbooks_service,
)
from dtm_buildsheet.app.routes.quickbooks import route_quickbooks
from dtm_buildsheet.paths import AppPaths


@pytest.fixture
def paths(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return AppPaths(workspace_dir=tmp_path, workspace_config_dir=config_dir)


def _central_config(paths, *, enabled=True):
    document = {
        "central_qbo": {
            "enabled": enabled,
            "base_url": "https://builder-api.example",
            "tenant_id": "tenant-id",
            "audience": "api-client-id",
            "delegated_scope": "api://api-client-id/Builder.Access",
            "client_secret": "ignored-even-if-supplied",
        }
    }
    (paths.workspace_dir / "quickbooks_config.json").write_text(json.dumps(document))


def test_central_configuration_contains_public_identifiers_only(paths):
    _central_config(paths)
    config = load_builder_api_config(paths)

    assert config == BuilderApiConfig(
        enabled=True,
        base_url="https://builder-api.example",
        tenant_id="tenant-id",
        audience="api-client-id",
        delegated_scope="api://api-client-id/Builder.Access",
    )
    assert not hasattr(config, "client_secret")
    config.validate()


def test_builder_token_provider_requests_api_scope_not_graph_token():
    class FakeMsal:
        def acquire_token(self, **kwargs):
            raise AssertionError("Graph token path must not be called")

        def acquire_token_for_scopes(self, scopes, *, interactive_ok):
            assert scopes == ("api://api-client-id/Builder.Access",)
            assert interactive_ok is False
            return "builder-api-token"

    config = BuilderApiConfig(
        enabled=True,
        base_url="https://builder-api.example",
        tenant_id="tenant-id",
        audience="api-client-id",
        delegated_scope="api://api-client-id/Builder.Access",
    )
    provider = EntraBuilderApiTokenProvider(config, msal_client=FakeMsal())
    assert provider.get_token() == "builder-api-token"


def test_central_client_uses_narrow_health_and_items_endpoints():
    session = MagicMock()
    health = MagicMock(status_code=200)
    health.json.return_value = {
        "ok": True,
        "connected": True,
        "connection_status": "connected",
        "environment": "production",
    }
    items = MagicMock(status_code=200)
    items.json.return_value = {
        "ok": True,
        "items": [{"qb_item_id": "1", "name": "Item", "active": True}],
    }
    session.get.side_effect = [health, items]
    config = BuilderApiConfig(
        enabled=True,
        base_url="https://builder-api.example",
        tenant_id="tenant-id",
        audience="api-client-id",
        delegated_scope="api://api-client-id/Builder.Access",
    )
    token_provider = MagicMock()
    token_provider.get_token.return_value = "builder-api-token"
    client = CentralQuickBooksClient(config, token_provider=token_provider, session=session)

    assert client.connection_health()["connected"] is True
    assert client.fetch_active_items()[0]["qb_item_id"] == "1"
    assert [call.args[0] for call in session.get.call_args_list] == [
        "https://builder-api.example/v1/quickbooks/health",
        "https://builder-api.example/v1/quickbooks/items",
    ]
    for call in session.get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "Bearer builder-api-token"


def test_central_client_transport_failure_never_exposes_url_or_token():
    session = MagicMock()
    session.get.side_effect = RuntimeError(
        "https://builder-api.example?sig=secret Bearer builder-api-token"
    )
    config = BuilderApiConfig(
        enabled=True,
        base_url="https://builder-api.example",
        tenant_id="tenant-id",
        audience="api-client-id",
        delegated_scope="api://api-client-id/Builder.Access",
    )
    token_provider = MagicMock()
    token_provider.get_token.return_value = "builder-api-token"
    client = CentralQuickBooksClient(config, token_provider=token_provider, session=session)

    with pytest.raises(CentralQuickBooksClientError) as raised:
        client.connection_health()
    assert str(raised.value) == "central_service_unavailable"


def _client_for_response(response):
    session = MagicMock()
    session.get.return_value = response
    config = BuilderApiConfig(
        enabled=True,
        base_url="https://builder-api.example",
        tenant_id="tenant-id",
        audience="api-client-id",
        delegated_scope="api://api-client-id/Builder.Access",
    )
    token_provider = MagicMock()
    token_provider.get_token.return_value = "builder-api-token"
    return CentralQuickBooksClient(config, token_provider=token_provider, session=session)


def test_central_client_recognizes_netlify_paused_site_without_exposing_body():
    response = MagicMock(status_code=503)
    response.headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Server": "Netlify",
    }
    response.text = """<!doctype html><html><title>Site not available</title>
        This site has been paused. private-customer server-token</html>"""
    client = _client_for_response(response)

    with pytest.raises(CentralQuickBooksClientError) as raised:
        client.connection_health()

    assert raised.value.code == "central_service_limit_reached"
    assert "private-customer" not in str(raised.value)
    assert "server-token" not in str(raised.value)


def test_central_client_maps_structured_capacity_error_to_limit_guidance():
    response = MagicMock(status_code=503)
    response.headers = {"Content-Type": "application/json"}
    response.text = ""
    response.json.return_value = {
        "ok": False,
        "error": {"code": "service_capacity_exhausted"},
    }
    client = _client_for_response(response)

    with pytest.raises(CentralQuickBooksClientError) as raised:
        client.connection_health()

    assert raised.value.code == "central_service_limit_reached"


def test_central_client_does_not_mislabel_an_ordinary_html_outage_as_a_limit():
    response = MagicMock(status_code=503)
    response.headers = {"Content-Type": "text/html"}
    response.text = "<!doctype html><html>Temporary upstream outage</html>"
    client = _client_for_response(response)

    with pytest.raises(CentralQuickBooksClientError) as raised:
        client.connection_health()

    assert raised.value.code == "central_service_unavailable"


def test_central_health_preserves_limit_code_for_the_user_interface(paths, monkeypatch):
    _central_config(paths)

    class LimitedCentral:
        def connection_health(self):
            raise CentralQuickBooksClientError("central_service_limit_reached")

    monkeypatch.setattr(quickbooks_gateway_service, "_central_gateway", lambda p: LimitedCentral())

    health = quickbooks_gateway_service.connection_health(paths)

    assert health["ok"] is False
    assert health["error"] == "central_service_limit_reached"
    assert health["central_mode"] is True


def test_estimate_limit_message_tells_user_the_build_is_safe_and_admin_action():
    source = (
        Path(__file__).parents[1]
        / "src/dtm_buildsheet/ui/js/projects/detail_builds.js"
    ).read_text("utf-8")

    message = source.split("central_service_limit_reached:", 1)[1].split("\n", 1)[0]
    assert "Estimate was not created" in message
    assert "Your build is safe" in message
    assert "Builder Admin" in message
    assert "Netlify → Usage & billing" in message


def test_central_failure_does_not_call_local_compatibility_provider(paths, monkeypatch):
    _central_config(paths)
    local_calls = []

    class FailingCentral:
        def fetch_active_items(self):
            raise CentralQuickBooksClientError("central_service_unavailable")

    monkeypatch.setattr(quickbooks_gateway_service, "_central_gateway", lambda p: FailingCentral())

    with pytest.raises(QuickBooksGatewayError, match="central_service_unavailable"):
        quickbooks_gateway_service.fetch_active_items(
            paths,
            local_provider=lambda: local_calls.append(True) or [],
        )
    assert local_calls == []


def test_central_mode_blocks_surviving_local_keychain_credentials(paths, monkeypatch):
    _central_config(paths)
    local_token_calls = []
    monkeypatch.setattr(
        quickbooks_service,
        "ensure_access_token",
        lambda p: local_token_calls.append(True) or "local-access",
    )

    client, error = qb_sync_service._build_client(paths)

    assert client is None
    assert error == {"ok": False, "error": "central_operation_not_migrated"}
    assert local_token_calls == []


def test_central_item_slice_updates_cache_but_not_parts_db(paths, monkeypatch):
    _central_config(paths)
    parts_path = paths.workspace_config_dir / "parts_db.json"
    before = '{"schema_version":2,"products":{"one":{"qb_item_id":"1"}}}'
    parts_path.write_text(before)

    class Central:
        def fetch_active_items(self):
            return [
                {
                    "qb_item_id": "1",
                    "name": "Current Item",
                    "sku": "SKU",
                    "description": "",
                    "unit_price": 99.0,
                    "type": "Inventory",
                    "active": True,
                }
            ]

    monkeypatch.setattr(quickbooks_gateway_service, "_central_gateway", lambda p: Central())

    result = qb_sync_service.run_full_sync(paths)

    assert result["ok"] is True
    assert result["reconciled"]["skipped"] == "central_read_only_slice"
    assert parts_path.read_text() == before
    cache = json.loads((paths.workspace_dir / "quickbooks_items_cache.json").read_text())
    assert cache["items"][0]["name"] == "Current Item"


def test_disabled_mode_preserves_local_gateway_behavior(paths, monkeypatch):
    calls = []
    monkeypatch.setattr(
        quickbooks_service,
        "get_status",
        lambda p: {"ok": True, "connected": True, "environment": "sandbox"},
    )

    health = quickbooks_gateway_service.connection_health(paths)
    items = quickbooks_gateway_service.fetch_active_items(
        paths,
        local_provider=lambda: calls.append("local") or [{"qb_item_id": "local"}],
    )

    assert health["connected"] is True
    assert health["central_mode"] is False
    assert items == [{"qb_item_id": "local"}]
    assert calls == ["local"]


def test_existing_save_preserves_central_configuration(paths, monkeypatch):
    _central_config(paths)
    store = MagicMock()
    store.load.return_value = {}
    monkeypatch.setattr(quickbooks_service, "_store", lambda profile="default": store)

    quickbooks_service.save_settings(
        paths,
        client_id="local-client",
        environment="production",
        redirect_uri="https://redirect.example/callback",
    )

    document = json.loads((paths.workspace_dir / "quickbooks_config.json").read_text())
    assert document["central_qbo"]["enabled"] is True
    assert document["central_qbo"]["base_url"] == "https://builder-api.example"


class _Handler:
    def __init__(self, path=""):
        self.path = path
        self.status = None
        self.headers = {}
        self.wfile = BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers[name] = value

    def end_headers(self):
        pass


def test_central_mode_never_starts_desktop_intuit_authorization(paths):
    _central_config(paths)
    handler = _Handler("/api/quickbooks/auth-url")

    assert route_quickbooks(
        handler,
        "GET",
        "/api/quickbooks/auth-url",
        {},
        paths,
    ) is True
    payload = json.loads(handler.wfile.getvalue())
    assert handler.status == 503
    assert payload["error"] == "central_operation_not_migrated"
    assert handler.headers["Cache-Control"] == "no-store"


def test_central_mode_oauth_callback_remains_redirect_only(paths):
    _central_config(paths)
    handler = _Handler("/api/quickbooks/callback?code=must-not-be-processed")

    assert route_quickbooks(
        handler,
        "GET",
        "/api/quickbooks/callback",
        {},
        paths,
    ) is True
    assert handler.status == 302
    assert handler.headers["Location"] == "/?qb=error"
    assert handler.wfile.getvalue() == b""
