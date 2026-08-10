"""OS-keychain-backed store for QuickBooks OAuth secrets.

Persists a single encrypted JSON blob using the same msal-extensions
encrypted persistence the M365 token cache relies on (see
``adapters/cloud/msal_client.py``): Keychain on macOS, DPAPI on Windows,
libsecret on Linux. The plaintext secret material never touches the
filesystem.

Intuit's security policy requires the refresh token and realmID to be
encrypted at rest; routing every QuickBooks secret through this store
satisfies that requirement. See ``docs/EXTERNAL_CONNECTION_SECURITY.md``.

When the OS keychain backend is unavailable (e.g. headless Linux without
libsecret), the store falls back to a process-lifetime in-memory map.
That fallback is never written to disk — losing it on restart forces a
re-authorization, which is the correct secure behavior rather than a
plaintext-on-disk fallback.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_CREDENTIAL_FILENAME = "quickbooks_credentials.bin"

# Process-lifetime fallback, keyed by location. See module docstring.
_memory_store: dict[str, str] = {}
_lock = threading.RLock()


def _app_data_dir() -> Path:
    """Per-user application data dir, matching the M365 token-cache location."""
    if sys.platform.startswith("win"):
        return Path.home() / "AppData" / "Roaming" / "DTM Vehicle Builder"
    if sys.platform.startswith("darwin"):
        return Path.home() / "Library" / "Application Support" / "DTM Vehicle Builder"
    return Path.home() / ".config" / "DTM Vehicle Builder"


class QuickBooksCredentialStore:
    """Read/write the encrypted QuickBooks secret blob.

    Holds ``client_secret``, ``access_token``, ``refresh_token`` and
    ``realm_id``. Callers treat it as a small dict: ``load()`` returns the
    current blob (``{}`` when absent), ``save()`` replaces it, ``clear()``
    removes it.
    """

    def __init__(self, location: Path | None = None) -> None:
        self._location = str(location or (_app_data_dir() / _CREDENTIAL_FILENAME))

    def _persistence(self):
        # Imported lazily so the module loads in environments where
        # msal-extensions isn't installed (the in-memory fallback kicks in).
        from msal_extensions import build_encrypted_persistence

        Path(self._location).parent.mkdir(parents=True, exist_ok=True)
        return build_encrypted_persistence(self._location)

    def save(self, secrets: dict) -> None:
        blob = json.dumps(secrets)
        with _lock:
            try:
                self._persistence().save(blob)
                _memory_store.pop(self._location, None)
                return
            except Exception:  # noqa: BLE001 — many platform-specific errors
                logger.warning(
                    "QuickBooks keychain persistence unavailable; holding "
                    "credentials in memory for this session only"
                )
                _memory_store[self._location] = blob

    def load(self) -> dict:
        with _lock:
            blob: str | None
            try:
                blob = self._persistence().load()
            except Exception:  # noqa: BLE001 — absent file or missing backend
                blob = _memory_store.get(self._location)
            if not blob:
                return {}
            try:
                data = json.loads(blob)
            except (json.JSONDecodeError, TypeError):
                return {}
            return data if isinstance(data, dict) else {}

    def clear(self) -> None:
        with _lock:
            _memory_store.pop(self._location, None)
            try:
                self._persistence().save("{}")
            except Exception:  # noqa: BLE001
                pass
            try:
                Path(self._location).unlink()
            except OSError:
                pass
