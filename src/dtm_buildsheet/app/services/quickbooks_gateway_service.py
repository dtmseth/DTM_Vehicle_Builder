"""Select the local compatibility or central QuickBooks gateway."""

from __future__ import annotations

from collections.abc import Callable

from ...paths import AppPaths
from ..adapters.quickbooks.builder_api_config import (
    BuilderApiConfigError,
    load_builder_api_config,
)
from ..adapters.quickbooks.builder_api_token import EntraBuilderApiTokenProvider
from ..adapters.quickbooks.central_client import (
    CentralQuickBooksClient,
    CentralQuickBooksClientError,
)
from ..adapters.quickbooks.gateway import (
    CentralQuickBooksGateway,
    LocalQuickBooksCompatibilityGateway,
    QuickBooksGatewayError,
)
from . import quickbooks_service


def central_mode_enabled(paths: AppPaths) -> bool:
    return load_builder_api_config(paths).enabled


def _central_gateway(paths: AppPaths) -> CentralQuickBooksGateway:
    config = load_builder_api_config(paths)
    config.validate()
    token_provider = EntraBuilderApiTokenProvider(config)
    return CentralQuickBooksGateway(
        CentralQuickBooksClient(config, token_provider=token_provider)
    )


def connection_health(paths: AppPaths) -> dict:
    """Return central health when enabled, with no local credential fallback."""
    config = load_builder_api_config(paths)
    if not config.enabled:
        health = LocalQuickBooksCompatibilityGateway(
            health_provider=lambda: quickbooks_service.get_status(paths),
            active_items_provider=lambda: [],
        ).connection_health()
        return {**health, "central_mode": False, "managed_by_dtm": False}
    try:
        health = _central_gateway(paths).connection_health()
        return {
            "ok": True,
            "configured": True,
            "connected": bool(health.get("connected")),
            "connection_status": health.get("connection_status", "unavailable"),
            "environment": health.get("environment", "production"),
            "managed_connection": True,
            "managed_by_dtm": True,
            "central_mode": True,
            "client_id": "",
            "redirect_uri": "",
            "has_client_secret": False,
            "last_sync_utc": quickbooks_service.get_last_sync(paths),
        }
    except (BuilderApiConfigError, CentralQuickBooksClientError) as error:
        code = getattr(error, "code", str(error))
        return {
            "ok": False,
            "error": code,
            "configured": True,
            "connected": False,
            "connection_status": "unavailable",
            "environment": "production",
            "managed_connection": True,
            "managed_by_dtm": True,
            "central_mode": True,
            "client_id": "",
            "redirect_uri": "",
            "has_client_secret": False,
        }


def fetch_active_items(
    paths: AppPaths,
    *,
    local_provider: Callable[[], list[dict]],
) -> list[dict]:
    """Read Items through exactly one selected adapter; never fall back."""
    config = load_builder_api_config(paths)
    try:
        if config.enabled:
            return _central_gateway(paths).fetch_active_items()
        return LocalQuickBooksCompatibilityGateway(
            health_provider=lambda: {},
            active_items_provider=local_provider,
        ).fetch_active_items()
    except QuickBooksGatewayError:
        raise
    except (BuilderApiConfigError, CentralQuickBooksClientError) as error:
        raise QuickBooksGatewayError(getattr(error, "code", str(error))) from None
