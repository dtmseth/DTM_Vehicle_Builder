"""QuickBooks gateway boundary used by desktop-facing services."""

from __future__ import annotations

from typing import Callable, Protocol

from .central_client import CentralQuickBooksClient


class QuickBooksGatewayError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class QuickBooksGateway(Protocol):
    def connection_health(self) -> dict: ...

    def fetch_active_items(self) -> list[dict]: ...


class LocalQuickBooksCompatibilityGateway:
    """Temporary adapter preserving the current keychain/direct-QBO path."""

    def __init__(
        self,
        *,
        health_provider: Callable[[], dict],
        active_items_provider: Callable[[], list[dict]],
    ) -> None:
        self._health_provider = health_provider
        self._active_items_provider = active_items_provider

    def connection_health(self) -> dict:
        return self._health_provider()

    def fetch_active_items(self) -> list[dict]:
        return self._active_items_provider()


class CentralQuickBooksGateway:
    def __init__(self, client: CentralQuickBooksClient) -> None:
        self._client = client

    def connection_health(self) -> dict:
        return self._client.connection_health()

    def fetch_active_items(self) -> list[dict]:
        return self._client.fetch_active_items()
