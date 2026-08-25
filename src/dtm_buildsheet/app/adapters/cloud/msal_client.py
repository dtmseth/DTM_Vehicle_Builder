from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

import msal

from .config import GRAPH_SCOPES, CloudConfig

logger = logging.getLogger(__name__)


class CloudAuthError(RuntimeError):
    """Raised when the user cannot complete sign-in or the cached token expired
    and no interactive flow is available (e.g. headless run)."""


def _default_cache_path() -> Path:
    """Return the file path used as the signal/sentinel for the persisted cache.

    The actual secret material lives in the OS keychain on Mac (Keychain),
    Windows (DPAPI), or Linux (libsecret) — the path here is just a stable
    handle the persistence layer needs.
    """
    if sys.platform.startswith("win"):
        base = Path.home() / "AppData" / "Roaming" / "DTM Vehicle Builder"
    elif sys.platform.startswith("darwin"):
        base = Path.home() / "Library" / "Application Support" / "DTM Vehicle Builder"
    else:
        base = Path.home() / ".config" / "DTM Vehicle Builder"
    return base / "msal_token_cache.bin"


def _build_token_cache(cache_path: Path):
    """Construct an MSAL token cache backed by the OS keychain/DPAPI/libsecret.

    Falls back to an in-memory cache when msal-extensions can't initialize
    (e.g. headless CI Linux without libsecret). The fallback is logged so the
    user sees why they're being prompted to sign in every launch.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from msal_extensions import (  # type: ignore[import-not-found]
            PersistedTokenCache,
            build_encrypted_persistence,
        )

        persistence = build_encrypted_persistence(str(cache_path))
        return PersistedTokenCache(persistence)
    except Exception:  # noqa: BLE001 — msal_extensions surfaces many platform errors
        logger.exception(
            "msal-extensions persisted cache unavailable; falling back to in-memory cache"
        )
        return msal.SerializableTokenCache()


PromptHandler = Callable[[dict], None]
"""Called with the MSAL device-flow payload so a UI layer can show the
user_code + verification_uri. Signature mirrors `msal`'s flow dict."""


class MsalClient:
    """Wraps `msal.PublicClientApplication` with cached token acquisition.

    Acquisition order:
      1. Silent (refresh) using the cached account, if one is present.
      2. Interactive (browser-based) when running with a usable display.
      3. Device-code (prints a URL + code) as the last-resort fallback.

    The interactive path is preferred because it lands the user back in the
    app without a context switch; device-code is the headless fallback.
    """

    def __init__(
        self,
        config: CloudConfig,
        *,
        cache_path: Path | None = None,
        prompt_handler: PromptHandler | None = None,
    ) -> None:
        self._config = config
        self._cache_path = cache_path or _default_cache_path()
        self._prompt_handler = prompt_handler or (lambda flow: print(flow["message"]))
        self._cache = _build_token_cache(self._cache_path)
        self._app = msal.PublicClientApplication(
            client_id=config.client_id,
            authority=config.authority,
            token_cache=self._cache,
        )

    # ── Public API ────────────────────────────────────────────────────────

    def acquire_token(
        self,
        *,
        interactive_ok: bool = True,
        force_account_picker: bool = False,
    ) -> str:
        """Return a valid Graph access token, prompting the user if needed.

        Set `interactive_ok=False` to forbid any UI — useful for background
        refresh paths that should fail loudly rather than pop a window.

        Set `force_account_picker=True` to bypass the cached MSAL account
        AND tell the OAuth endpoint to show the account picker even if the
        browser has a Microsoft session cookie. Used by Switch User in the
        cloud-status modal: without this, MSAL silently reuses whichever
        account the browser is signed into and the user can't actually
        switch. Always implies interactive — silent acquisition skips the
        picker step entirely.
        """
        if not force_account_picker:
            token = self._acquire_silent()
            if token:
                return token
        if not interactive_ok:
            raise CloudAuthError("No cached account and interactive sign-in disabled")
        return self._acquire_interactive_or_devicecode(
            force_account_picker=force_account_picker,
        )

    def has_cached_account(self) -> bool:
        return bool(self._app.get_accounts())

    def signout(self) -> None:
        """Remove every cached account from MSAL's local store.

        Does not revoke the token server-side — only this machine forgets it.
        """
        for account in list(self._app.get_accounts()):
            self._app.remove_account(account)

    def get_active_account(self) -> dict | None:
        accounts = self._app.get_accounts()
        return accounts[0] if accounts else None

    # ── Internal ──────────────────────────────────────────────────────────

    def _acquire_silent(self) -> str | None:
        accounts = self._app.get_accounts()
        if not accounts:
            return None
        result = self._app.acquire_token_silent(
            scopes=list(GRAPH_SCOPES),
            account=accounts[0],
        )
        if result and "access_token" in result:
            return result["access_token"]
        return None

    def _acquire_interactive_or_devicecode(self, *, force_account_picker: bool = False) -> str:
        # prompt="select_account" forces the OAuth endpoint to show the
        # account chooser even when the browser already has a Microsoft
        # session — without it, MSAL silently reuses that session and the
        # Switch User flow has no visible effect.
        interactive_kwargs: dict = {"scopes": list(GRAPH_SCOPES)}
        if force_account_picker:
            interactive_kwargs["prompt"] = "select_account"
        try:
            result = self._app.acquire_token_interactive(**interactive_kwargs)
            if result and "access_token" in result:
                return result["access_token"]
        except Exception:  # noqa: BLE001 — fall through to device-code
            logger.info("Interactive auth unavailable; falling back to device code")

        flow = self._app.initiate_device_flow(scopes=list(GRAPH_SCOPES))
        if "user_code" not in flow:
            raise CloudAuthError(
                f"Could not start device-code flow: {flow.get('error_description', flow)}"
            )
        self._prompt_handler(flow)
        result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise CloudAuthError(
                f"Sign-in failed: {result.get('error_description', result)}"
            )
        return result["access_token"]
