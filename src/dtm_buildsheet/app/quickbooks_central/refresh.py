"""Single-writer refresh-token rotation coordinator."""

from __future__ import annotations

import time

from .contracts import ServerCredentials
from .errors import CentralServiceError
from .interfaces import CredentialStore, LockProvider, QboProvider


class RefreshCoordinator:
    """Serialize refresh per realm and atomically retain the newest token."""

    def __init__(
        self,
        *,
        credentials: CredentialStore,
        locks: LockProvider,
        qbo: QboProvider,
        refresh_skew_seconds: float = 300.0,
        now: callable = time.time,
    ) -> None:
        self._credentials = credentials
        self._locks = locks
        self._qbo = qbo
        self._skew = refresh_skew_seconds
        self._now = now

    def _fresh(self, credentials: ServerCredentials) -> bool:
        return credentials.access_expires_at > float(self._now()) + self._skew

    def get(self, realm_key: str) -> ServerCredentials:
        current = self._credentials.load(realm_key)
        if current is None:
            raise CentralServiceError("not_connected", status_code=503)
        if self._fresh(current):
            return current

        with self._locks.acquire(realm_key):
            # Another caller may have rotated while this caller waited.
            current = self._credentials.load(realm_key)
            if current is None:
                raise CentralServiceError("not_connected", status_code=503)
            if self._fresh(current):
                return current
            try:
                refreshed = self._qbo.refresh(current.refresh_token)
            except Exception:  # noqa: BLE001 - provider text may contain secrets/URLs
                raise CentralServiceError("provider_unavailable", status_code=503) from None
            if not refreshed.access_token or not refreshed.refresh_token:
                raise CentralServiceError("invalid_provider_data", status_code=502)
            replacement = ServerCredentials(
                realm_id=current.realm_id,
                access_token=refreshed.access_token,
                refresh_token=refreshed.refresh_token,
                access_expires_at=refreshed.access_expires_at,
                version=current.version + 1,
            )
            if self._credentials.replace(
                realm_key,
                expected_version=current.version,
                credentials=replacement,
            ):
                return replacement

            # A durable distributed lock can expire or be lost. Never overwrite
            # the winner's rotating refresh token; use its latest generation.
            latest = self._credentials.load(realm_key)
            if latest is not None and self._fresh(latest):
                return latest
            raise CentralServiceError("credential_conflict", status_code=409)
