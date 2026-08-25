"""Ports required by the provider-neutral central QuickBooks core."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Mapping, Protocol

from .contracts import AuditRecord, RefreshResult, ServerCredentials


class SignatureVerifier(Protocol):
    """Cryptographically verify an Entra JWT before returning its claims."""

    def verify(self, token: str) -> Mapping[str, Any]: ...


class CredentialStore(Protocol):
    """Encrypted durable store with compare-and-swap replacement semantics."""

    def load(self, realm_key: str) -> ServerCredentials | None: ...

    def replace(
        self,
        realm_key: str,
        *,
        expected_version: int,
        credentials: ServerCredentials,
    ) -> bool: ...


class LockProvider(Protocol):
    """Return a durable, exclusive lock scoped to one QBO realm."""

    def acquire(self, realm_key: str) -> AbstractContextManager[None]: ...


class AuditStore(Protocol):
    def append(self, record: AuditRecord) -> None: ...


class QboProvider(Protocol):
    """Server-side QBO transport. Provider tokens never cross this port."""

    def refresh(self, refresh_token: str) -> RefreshResult: ...

    def connection_health(self, *, access_token: str, realm_id: str) -> Mapping[str, Any]: ...

    def fetch_active_items(self, *, access_token: str, realm_id: str) -> list[Mapping[str, Any]]: ...
