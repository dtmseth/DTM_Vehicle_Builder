"""Desktop client for the narrow centralized Builder QuickBooks API."""

from __future__ import annotations

import uuid
from typing import Any

import requests

from ...quickbooks_central.contracts import CatalogItem
from .builder_api_config import BuilderApiConfig
from .builder_api_token import BuilderApiTokenProvider


class CentralQuickBooksClientError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_SAFE_REMOTE_CODES = {
    "unauthenticated",
    "invalid_token",
    "wrong_tenant",
    "wrong_audience",
    "expired_token",
    "missing_subject",
    "forbidden",
    "not_connected",
    "provider_unavailable",
    "service_capacity_exhausted",
    "central_service_limit_reached",
}

_NETLIFY_LIMIT_MARKERS = (
    "site not available",
    "site is paused",
    "usage limit",
    "credit limit",
)


def _netlify_limit_response(response: Any) -> bool:
    """Recognize Netlify's platform-owned paused-site response safely.

    Once a Free-plan credit limit is reached, the function itself cannot run,
    so it cannot return our normal JSON error contract.  Netlify serves a
    small HTML ``Site not available`` page instead.  Inspect only a bounded
    prefix and never include that untrusted body in an exception or log.
    """
    try:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        server = str(response.headers.get("Server") or "").casefold()
    except Exception:  # noqa: BLE001 - response doubles may omit headers
        content_type = ""
        server = ""
    try:
        body = str(response.text or "")[:4096].casefold()
    except Exception:  # noqa: BLE001 - response decoding is untrusted
        return False
    if "text/html" not in content_type and not body.lstrip().startswith(("<!doctype", "<html")):
        return False
    provider_owned = "netlify" in body or "netlify" in server
    return provider_owned and any(marker in body for marker in _NETLIFY_LIMIT_MARKERS)


class CentralQuickBooksClient:
    """No fallback: every enabled-mode request either succeeds centrally or fails."""

    def __init__(
        self,
        config: BuilderApiConfig,
        *,
        token_provider: BuilderApiTokenProvider,
        session=requests,
        timeout_seconds: float = 20.0,
    ) -> None:
        config.validate()
        self._base_url = config.base_url
        self._token_provider = token_provider
        self._session = session
        self._timeout = timeout_seconds

    def _get(self, endpoint: str) -> dict[str, Any]:
        correlation_id = uuid.uuid4().hex
        try:
            token = self._token_provider.get_token()
        except Exception:  # noqa: BLE001 - auth detail is never exposed
            raise CentralQuickBooksClientError("central_auth_unavailable") from None
        try:
            response = self._session.get(
                f"{self._base_url}{endpoint}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-Correlation-ID": correlation_id,
                },
                timeout=self._timeout,
            )
        except Exception:  # noqa: BLE001 - transport text may contain a URL/token
            raise CentralQuickBooksClientError("central_service_unavailable") from None

        if response.status_code != 200:
            if _netlify_limit_response(response):
                raise CentralQuickBooksClientError("central_service_limit_reached")
            code = ""
            try:
                error = response.json().get("error") or {}
                code = str(error.get("code") or "") if isinstance(error, dict) else ""
            except Exception:  # noqa: BLE001 - response is untrusted
                pass
            if code == "service_capacity_exhausted":
                code = "central_service_limit_reached"
            if code not in _SAFE_REMOTE_CODES:
                code = "central_request_rejected" if response.status_code < 500 else "central_service_unavailable"
            raise CentralQuickBooksClientError(code)
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            raise CentralQuickBooksClientError("central_invalid_response") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise CentralQuickBooksClientError("central_invalid_response")
        return payload

    def connection_health(self) -> dict[str, Any]:
        payload = self._get("/v1/quickbooks/health")
        return {
            "connected": bool(payload.get("connected")),
            "connection_status": str(payload.get("connection_status") or "unavailable"),
            "environment": str(payload.get("environment") or "production"),
            "managed_by_dtm": True,
        }

    def fetch_active_items(self) -> list[dict[str, Any]]:
        payload = self._get("/v1/quickbooks/items")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise CentralQuickBooksClientError("central_invalid_response")
        try:
            return [CatalogItem.from_mapping(item).to_dict() for item in raw_items if isinstance(item, dict)]
        except (TypeError, ValueError, OverflowError):
            raise CentralQuickBooksClientError("central_invalid_response") from None
