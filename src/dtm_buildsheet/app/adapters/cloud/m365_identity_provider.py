from __future__ import annotations

import logging

import requests

from ..interfaces import IdentityProvider, UserIdentity
from .config import GRAPH_ENDPOINT
from .msal_client import CloudAuthError, MsalClient

logger = logging.getLogger(__name__)

_GRAPH_ME_URL = f"{GRAPH_ENDPOINT}/me"
_GRAPH_ME_PHOTO_URL = f"{GRAPH_ENDPOINT}/me/photo/$value"


class M365IdentityProvider(IdentityProvider):
    """IdentityProvider backed by Microsoft Identity Platform via MSAL.

    On first launch (or after sign-out) the user is prompted through the
    MSAL client's interactive / device-code flow. Subsequent launches use the
    cached refresh token from the OS keychain.
    """

    def __init__(self, msal_client: MsalClient, *, http_timeout: float = 15.0) -> None:
        self._msal = msal_client
        self._http_timeout = http_timeout
        self._cached_identity: UserIdentity | None = None

    def signin(self, *, force_account_picker: bool = False) -> UserIdentity:
        """Run the interactive OAuth flow and return the user identity.

        ``force_account_picker=True`` makes the OAuth endpoint show the
        account chooser even if the browser is already signed into a
        Microsoft account. The Switch User modal action passes this so a
        cached browser session can't silently win. Routine sign-in
        (first-launch / re-sign-in after explicit signout) leaves it
        False so the picker doesn't appear when only one account is
        plausibly the right answer.
        """
        token = self._msal.acquire_token(
            interactive_ok=True,
            force_account_picker=force_account_picker,
        )
        identity = self._fetch_identity(token)
        self._cached_identity = identity
        return identity

    def current_user(self) -> UserIdentity | None:
        if self._cached_identity is not None:
            return self._cached_identity
        if not self._msal.has_cached_account():
            return None
        try:
            token = self._msal.acquire_token(interactive_ok=False)
        except CloudAuthError:
            return None
        identity = self._fetch_identity(token)
        self._cached_identity = identity
        return identity

    def signout(self) -> None:
        self._msal.signout()
        self._cached_identity = None

    def is_signed_in(self) -> bool:
        return self.current_user() is not None

    def fetch_user_photo(self) -> bytes | None:
        """Return the signed-in user's Microsoft Graph profile photo as bytes.

        Returns ``None`` if the user hasn't set a photo (Graph 404), if no
        cached account is available, or if the request fails. Callers should
        cache the bytes — the photo rarely changes.
        """
        try:
            token = self._msal.acquire_token(interactive_ok=False)
        except CloudAuthError:
            return None
        try:
            response = requests.get(
                _GRAPH_ME_PHOTO_URL,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._http_timeout,
            )
        except requests.RequestException:
            logger.exception("Failed to fetch user photo from Graph")
            return None
        if response.status_code == 404:
            return None  # User has no profile photo set — that's fine.
        if not response.ok:
            logger.warning(
                "Graph returned %d for user photo; treating as unavailable",
                response.status_code,
            )
            return None
        return response.content

    # ── Internal ──────────────────────────────────────────────────────────

    def _fetch_identity(self, token: str) -> UserIdentity:
        response = requests.get(
            _GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self._http_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return UserIdentity(
            user_id=str(payload.get("id", "")),
            display_name=str(
                payload.get("displayName") or payload.get("userPrincipalName") or ""
            ),
            email=str(
                payload.get("mail") or payload.get("userPrincipalName") or ""
            ),
            provider="m365",
            extra={
                k: str(v)
                for k, v in payload.items()
                if k in ("givenName", "surname", "jobTitle") and v
            },
        )
