from __future__ import annotations

import pytest

from dtm_buildsheet.app.adapters.quickbooks import oauth_client


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_broker_exchanges_code_without_local_client_secret(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return _Response(payload={"access_token": "access", "refresh_token": "refresh"})

    monkeypatch.setattr(oauth_client.requests, "post", post)
    client = oauth_client.QuickBooksOAuthClient(
        "public-id", token_broker_url="https://example.test/qb-token"
    )

    result = client.exchange_code(code="one-time-code", redirect_uri="https://example.test/callback")

    assert result["access_token"] == "access"
    assert captured["json"] == {
        "action": "exchange",
        "code": "one-time-code",
        "redirect_uri": "https://example.test/callback",
    }
    assert "Authorization" not in captured["headers"]


def test_broker_refresh_and_revoke_use_stateless_actions(monkeypatch):
    payloads = []
    monkeypatch.setattr(
        oauth_client.requests,
        "post",
        lambda _url, **kwargs: payloads.append(kwargs["json"]) or _Response(payload={"ok": True}),
    )
    client = oauth_client.QuickBooksOAuthClient(
        "public-id", token_broker_url="https://example.test/qb-token"
    )

    client.refresh(refresh_token="refresh")
    assert client.revoke(token="refresh") is True
    assert payloads == [
        {"action": "refresh", "refresh_token": "refresh"},
        {"action": "revoke", "token": "refresh"},
    ]


def test_broker_rejects_non_https_url(monkeypatch):
    client = oauth_client.QuickBooksOAuthClient(
        "public-id", token_broker_url="http://example.test/qb-token"
    )
    with pytest.raises(oauth_client.QuickBooksOAuthError, match="invalid_token_broker"):
        client.refresh(refresh_token="refresh")


def test_broker_surfaces_only_sanitized_error_code(monkeypatch):
    monkeypatch.setattr(
        oauth_client.requests,
        "post",
        lambda *_args, **_kwargs: _Response(400, {"error": "invalid_grant", "detail": "secret"}),
    )
    client = oauth_client.QuickBooksOAuthClient(
        "public-id", token_broker_url="https://example.test/qb-token"
    )
    with pytest.raises(oauth_client.QuickBooksOAuthError) as exc_info:
        client.refresh(refresh_token="refresh")
    assert str(exc_info.value) == "invalid_grant"
