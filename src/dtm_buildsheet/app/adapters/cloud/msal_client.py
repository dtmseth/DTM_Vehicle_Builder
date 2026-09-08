from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

import msal
from msal.oauth2cli.oidc import decode_id_token

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
        self._last_id_token_claims: dict[str, Any] = {}
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
        scopes: Sequence[str] | None = None,
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

        ``scopes`` is reserved for explicit foreground workflows such as the
        one-time operations-list provisioner. Omitting it preserves the
        ordinary least-privilege file/read scopes used by app startup.
        """
        requested_scopes = tuple(scopes) if scopes is not None else GRAPH_SCOPES
        if not requested_scopes or any(
            not str(scope or "").strip() for scope in requested_scopes
        ):
            raise ValueError("At least one non-empty Microsoft Graph scope is required")
        if not force_account_picker:
            token = self._acquire_silent(requested_scopes)
            if token:
                return token
        if not interactive_ok:
            raise CloudAuthError("No cached account and interactive sign-in disabled")
        return self._acquire_interactive_or_devicecode(
            force_account_picker=force_account_picker,
            scopes=requested_scopes,
        )

    def has_cached_account(self) -> bool:
        return bool(self._app.get_accounts())

    def signout(self) -> None:
        """Remove every cached account from MSAL's local store.

        Does not revoke the token server-side — only this machine forgets it.
        """
        for account in list(self._app.get_accounts()):
            self._app.remove_account(account)
        self._last_id_token_claims = {}

    def get_active_account(self) -> dict | None:
        accounts = self._app.get_accounts()
        return accounts[0] if accounts else None

    def get_app_roles(self) -> frozenset[str]:
        """Return app-role values from the most recent trusted ID-token claims.

        This deliberately does not decode the Microsoft Graph access token:
        that token is issued for Graph, not for this desktop application's
        audience. MSAL validates the ID token during acquisition and exposes
        its claims in the result we retain only in memory.
        """

        raw = getattr(self, "_last_id_token_claims", {}).get("roles", ())
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return frozenset()
        return frozenset(
            str(value).strip()
            for value in raw
            if str(value or "").strip()
        )

    # ── Internal ──────────────────────────────────────────────────────────

    def _acquire_silent(self, scopes: Sequence[str]) -> str | None:
        accounts = self._app.get_accounts()
        if not accounts:
            return None
        result = self._app.acquire_token_silent(
            scopes=list(scopes),
            account=accounts[0],
        )
        if result and "access_token" in result:
            self._remember_id_token_claims(result)
            if not self._last_id_token_claims:
                self._remember_cached_id_token_claims()
            return result["access_token"]
        return None

    def _acquire_interactive_or_devicecode(
        self,
        *,
        force_account_picker: bool = False,
        scopes: Sequence[str],
    ) -> str:
        # prompt="select_account" forces the OAuth endpoint to show the
        # account chooser even when the browser already has a Microsoft
        # session — without it, MSAL silently reuses that session and the
        # Switch User flow has no visible effect.
        interactive_kwargs: dict = {"scopes": list(scopes)}
        if force_account_picker:
            interactive_kwargs["prompt"] = "select_account"
        try:
            result = self._app.acquire_token_interactive(**interactive_kwargs)
            if result and "access_token" in result:
                self._remember_id_token_claims(result)
                return result["access_token"]
        except Exception:  # noqa: BLE001 — fall through to device-code
            logger.info("Interactive auth unavailable; falling back to device code")

        flow = self._app.initiate_device_flow(scopes=list(scopes))
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
        self._remember_id_token_claims(result)
        return result["access_token"]

    def _remember_id_token_claims(self, result: dict) -> None:
        claims = result.get("id_token_claims")
        if isinstance(claims, dict):
            self._last_id_token_claims = dict(claims)

    def _remember_cached_id_token_claims(self) -> None:
        """Recover claims when MSAL returns a still-valid cached access token.

        MSAL stores the validated ID token in the same encrypted cache, but a
        fast access-token cache hit does not include ``id_token_claims`` in
        its result. Re-validating that cached ID token keeps role resolution
        stable across app restarts without persisting a second copy.
        """

        cache = getattr(self, "_cache", None)
        config = getattr(self, "_config", None)
        account = self.get_active_account()
        if cache is None or config is None or not account:
            return
        query = {
            "home_account_id": account.get("home_account_id"),
            "environment": account.get("environment"),
            "realm": account.get("realm"),
            "client_id": config.client_id,
        }
        query = {key: value for key, value in query.items() if value}
        try:
            entries = cache.search(cache.CredentialType.ID_TOKEN, query=query)
            for entry in entries:
                secret = str(entry.get("secret") or "")
                if not secret:
                    continue
                claims = decode_id_token(secret, client_id=config.client_id)
                if isinstance(claims, dict):
                    self._last_id_token_claims = dict(claims)
                    return
        except Exception:
            logger.info("Cached ID-token claims unavailable; app roles fail closed")
