"""Stateless HTTP client for Intuit's OAuth 2.0 endpoints.

Uses the OpenID Connect discovery document to resolve the current
authorization, token, and revocation endpoints (per Intuit's guidance)
rather than hard-coding them, with a static fallback if the well-known
document is briefly unreachable.

This client never logs token values or response bodies. Error responses
surface Intuit's error code (e.g. ``invalid_grant``) as the exception
message so the service layer can react without exposing secrets.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

_DISCOVERY_URLS = {
    "production": "https://developer.api.intuit.com/.well-known/openid_configuration",
    "sandbox": "https://developer.api.intuit.com/.well-known/openid_sandbox_configuration",
}

# Used only if the discovery document can't be fetched. Intuit's OAuth
# endpoints have been stable; discovery is still preferred.
_FALLBACK_ENDPOINTS = {
    "authorization_endpoint": "https://appcenter.intuit.com/connect/oauth2",
    "token_endpoint": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
    "revocation_endpoint": "https://developer.api.intuit.com/v2/oauth2/tokens/revoke",
}

# Single scope covers Items, Customers, and Projects (Customer w/ Job flag).
OAUTH_SCOPE = "com.intuit.quickbooks.accounting"

_HTTP_TIMEOUT = 10

# Discovery documents are stable; cache them per-environment across all client
# instances so a fresh QuickBooksOAuthClient (created per service call) doesn't
# re-fetch the well-known document on every operation.
_DISCOVERY_CACHE: dict[str, dict] = {}


class QuickBooksOAuthError(RuntimeError):
    """Raised when a token request fails. Message is Intuit's error code."""


class QuickBooksOAuthClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        environment: str = "production",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._environment = environment if environment in _DISCOVERY_URLS else "production"
        self._endpoints: dict | None = None

    # ── endpoint discovery ──────────────────────────────────────────────────

    def _discover(self) -> dict:
        if self._endpoints is not None:
            return self._endpoints
        cached = _DISCOVERY_CACHE.get(self._environment)
        if cached is not None:
            self._endpoints = cached
            return cached
        url = _DISCOVERY_URLS[self._environment]
        try:
            resp = requests.get(url, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            doc = resp.json()
            self._endpoints = {
                "authorization_endpoint": doc["authorization_endpoint"],
                "token_endpoint": doc["token_endpoint"],
                "revocation_endpoint": doc.get(
                    "revocation_endpoint", _FALLBACK_ENDPOINTS["revocation_endpoint"]
                ),
            }
            # Only successful discovery is cached process-wide; a fallback stays
            # local so a transient outage doesn't pin us to static endpoints.
            _DISCOVERY_CACHE[self._environment] = self._endpoints
        except Exception:  # noqa: BLE001 — network / shape errors both fall back
            logger.warning(
                "QuickBooks discovery document unavailable; using fallback endpoints"
            )
            self._endpoints = dict(_FALLBACK_ENDPOINTS)
        return self._endpoints

    # ── public API ──────────────────────────────────────────────────────────

    def build_authorization_url(self, *, redirect_uri: str, state: str) -> str:
        endpoint = self._discover()["authorization_endpoint"]
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{endpoint}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> dict:
        return self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        )

    def refresh(self, *, refresh_token: str) -> dict:
        return self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    def revoke(self, *, token: str) -> bool:
        endpoint = self._discover()["revocation_endpoint"]
        headers = {
            "Authorization": self._basic_auth(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(endpoint, headers=headers, json={"token": token}, timeout=_HTTP_TIMEOUT)
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            logger.warning("QuickBooks token revocation request failed")
            return False

    # ── internal ────────────────────────────────────────────────────────────

    def _basic_auth(self) -> str:
        raw = f"{self._client_id}:{self._client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _token_request(self, data: dict) -> dict:
        endpoint = self._discover()["token_endpoint"]
        headers = {
            "Authorization": self._basic_auth(),
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            resp = requests.post(endpoint, headers=headers, data=data, timeout=_HTTP_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            raise QuickBooksOAuthError(f"token_request_failed: {exc}") from exc
        if resp.status_code != 200:
            # Surface Intuit's error code without logging tokens or bodies.
            try:
                err = resp.json().get("error", "")
            except Exception:  # noqa: BLE001
                err = ""
            raise QuickBooksOAuthError(err or f"http_{resp.status_code}")
        return resp.json()
