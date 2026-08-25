"""Hermetic development/test adapters for the central QuickBooks core.

Every adapter here refuses ``environment="production"``.  These classes are
for deterministic tests and local API prototyping only; they are not an
acceptable credential, lock, identity, audit, or QBO implementation for a
deployed service.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Mapping

from .contracts import AuditRecord, RefreshResult, ServerCredentials


def _require_hermetic(environment: str) -> None:
    if environment not in {"test", "development"}:
        raise RuntimeError("hermetic_adapter_refuses_production")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class HermeticSignatureVerifier:
    """Small HMAC token verifier for tests; never an Entra production adapter."""

    def __init__(self, secret: bytes, *, environment: str = "test") -> None:
        _require_hermetic(environment)
        if not secret:
            raise ValueError("test_secret_required")
        self._secret = secret

    def mint(self, claims: Mapping[str, Any]) -> str:
        payload = _b64url(json.dumps(dict(claims), separators=(",", ":")).encode())
        signature = _b64url(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest())
        return f"{payload}.{signature}"

    def verify(self, token: str) -> Mapping[str, Any]:
        payload, separator, signature = token.partition(".")
        if not separator:
            raise ValueError("invalid_test_token")
        expected = _b64url(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise ValueError("invalid_test_signature")
        value = json.loads(_b64decode(payload))
        if not isinstance(value, dict):
            raise ValueError("invalid_test_claims")
        return value


class InMemoryCredentialStore:
    def __init__(self, *, environment: str = "test") -> None:
        _require_hermetic(environment)
        self._values: dict[str, ServerCredentials] = {}
        self._lock = threading.RLock()

    def seed(self, realm_key: str, credentials: ServerCredentials) -> None:
        with self._lock:
            self._values[realm_key] = credentials

    def load(self, realm_key: str) -> ServerCredentials | None:
        with self._lock:
            value = self._values.get(realm_key)
            return replace(value) if value is not None else None

    def replace(
        self,
        realm_key: str,
        *,
        expected_version: int,
        credentials: ServerCredentials,
    ) -> bool:
        with self._lock:
            current = self._values.get(realm_key)
            if current is None or current.version != expected_version:
                return False
            self._values[realm_key] = credentials
            return True


class InMemoryLockProvider:
    def __init__(self, *, environment: str = "test") -> None:
        _require_hermetic(environment)
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    @contextmanager
    def acquire(self, realm_key: str):
        with self._guard:
            lock = self._locks.setdefault(realm_key, threading.RLock())
        with lock:
            yield


class InMemoryAuditStore:
    def __init__(self, *, environment: str = "test") -> None:
        _require_hermetic(environment)
        self.records: list[AuditRecord] = []
        self._lock = threading.Lock()

    def append(self, record: AuditRecord) -> None:
        with self._lock:
            self.records.append(record)


class HermeticQboProvider:
    def __init__(
        self,
        *,
        items: list[Mapping[str, Any]] | None = None,
        connected: bool = True,
        environment: str = "test",
        now: callable = time.time,
    ) -> None:
        _require_hermetic(environment)
        self.items = [dict(item) for item in (items or [])]
        self.connected = connected
        self.refresh_count = 0
        self.refresh_tokens_seen: list[str] = []
        self._lock = threading.Lock()
        self._now = now

    def refresh(self, refresh_token: str) -> RefreshResult:
        with self._lock:
            self.refresh_count += 1
            self.refresh_tokens_seen.append(refresh_token)
            generation = self.refresh_count
        return RefreshResult(
            access_token=f"hermetic-access-{generation}",
            refresh_token=f"hermetic-refresh-{generation}",
            access_expires_at=float(self._now()) + 3600,
        )

    def connection_health(self, *, access_token: str, realm_id: str) -> Mapping[str, Any]:
        del access_token, realm_id
        return {"connected": self.connected, "environment": "production"}

    def fetch_active_items(self, *, access_token: str, realm_id: str) -> list[Mapping[str, Any]]:
        del access_token, realm_id
        return [dict(item) for item in self.items]
