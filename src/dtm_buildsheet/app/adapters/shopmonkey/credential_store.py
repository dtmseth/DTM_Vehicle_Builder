"""OS-keychain-backed storage for the Shopmonkey API key.

The API key is never written to workspace configuration or application logs.
When the platform keychain is unavailable, credentials live only for the
current process so the app fails secure instead of creating a plaintext file.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_CREDENTIAL_FILENAME = "shopmonkey_credentials.bin"
_memory_store: dict[str, str] = {}
_lock = threading.RLock()


def _app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        return Path.home() / "AppData" / "Roaming" / "DTM Vehicle Builder"
    if sys.platform.startswith("darwin"):
        return Path.home() / "Library" / "Application Support" / "DTM Vehicle Builder"
    return Path.home() / ".config" / "DTM Vehicle Builder"


class ShopmonkeyCredentialStore:
    """Read and write one encrypted Shopmonkey credential blob."""

    def __init__(self, location: Path | None = None) -> None:
        if os.environ.get("DTM_LOCAL_PILOT") == "1":
            raise RuntimeError("Shopmonkey credentials are unavailable in the local pilot")
        self._location = str(location or (_app_data_dir() / _CREDENTIAL_FILENAME))

    def _persistence(self):
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
            except Exception:  # noqa: BLE001 - platform keychain errors vary
                logger.warning(
                    "Shopmonkey keychain persistence unavailable; holding the API key "
                    "in memory for this session only"
                )
                _memory_store[self._location] = blob

    def load(self) -> dict:
        with _lock:
            try:
                blob = self._persistence().load()
            except Exception:  # noqa: BLE001 - absent backend or credential
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
            except Exception:  # noqa: BLE001 - best-effort keychain deletion
                pass
            try:
                Path(self._location).unlink()
            except OSError:
                pass
