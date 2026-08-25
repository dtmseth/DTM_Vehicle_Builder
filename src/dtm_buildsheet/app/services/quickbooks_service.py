"""QuickBooks Online connection orchestration (Phase 1: OAuth + tokens).

Responsibilities:
- Manage non-secret connection metadata in ``quickbooks_config.json``
  (kept in the workspace root, deliberately outside the config-store /
  SharePoint-mirror machinery so it is never synced off the machine).
- Drive the one-time OAuth handshake with CSRF ``state`` protection.
- Exchange the authorization code for tokens and store secrets in the OS
  keychain via ``QuickBooksCredentialStore``.
- Hand out a valid access token, refreshing automatically and saving the
  rotated refresh token on every refresh.

Per-user secrets (``access_token``, ``refresh_token``, ``realm_id``) live ONLY
in the keychain. Managed Production installs use a stateless HTTPS broker whose
Intuit app secret exists only in the hosted environment. This module never logs
any secret.

See ``docs/QUICKBOOKS.md``.
"""

from __future__ import annotations

import json
import logging
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...paths import AppPaths
from ..adapters.quickbooks.credential_store import QuickBooksCredentialStore
from ..adapters.quickbooks.oauth_client import QuickBooksOAuthClient, QuickBooksOAuthError

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE = "default"
PRODUCTION_PREVIEW_PROFILE = "production_preview"
PRODUCTION_CLIENT_ID = "ABxAw3sNZdGuVr4twlYRJ9oCp0AtlllPTOupxGKdaoya7in6ga"
PRODUCTION_REDIRECT_URI = "https://dtmvehiclebuilder.netlify.app/.netlify/functions/qb-callback"
PRODUCTION_TOKEN_BROKER_URL = "https://dtmvehiclebuilder.netlify.app/.netlify/functions/qb-token"
_PROFILE_FILES = {
    _DEFAULT_PROFILE: {
        "config": "quickbooks_config.json",
        "credentials": "quickbooks_credentials.bin",
    },
    PRODUCTION_PREVIEW_PROFILE: {
        "config": "quickbooks_production_preview_config.json",
        "credentials": "quickbooks_production_preview_credentials.bin",
    },
}
_ACCESS_TOKEN_SKEW_SECONDS = 300        # refresh 5 minutes before expiry
_DEFAULT_ACCESS_TTL = 3600              # 1 hour, per Intuit
_DEFAULT_REFRESH_TTL = 8726400         # ~101 days, per Intuit
_HARD_EXPIRY_DAYS = 5 * 365             # Intuit's 5-year hard cap

# In-process CSRF state for the one-time OAuth handshake. Set when the auth
# URL is generated, consumed once on callback. A module global is sufficient
# for a single-process desktop app.
_pending_state: str | None = None
_pending_states: dict[str, str] = {}


# ── config metadata (non-secret) ───────────────────────────────────────────


def _profile_name(profile: str) -> str:
    if profile in _PROFILE_FILES:
        return profile
    raise ValueError("unknown_quickbooks_profile")


def _config_path(paths: AppPaths, profile: str = _DEFAULT_PROFILE) -> Path:
    return paths.workspace_dir / _PROFILE_FILES[_profile_name(profile)]["config"]


def _default_config(profile: str = _DEFAULT_PROFILE) -> dict:
    managed = profile == _DEFAULT_PROFILE
    return {
        "client_id": PRODUCTION_CLIENT_ID if managed else "",
        "environment": "production",
        "redirect_uri": PRODUCTION_REDIRECT_URI if managed else "",
        "token_broker_url": PRODUCTION_TOKEN_BROKER_URL if managed else "",
        "token_expiry_utc": "",
        "refresh_expiry_utc": "",
        "hard_expiry_utc": "",
        "last_sync_utc": None,
        "connection_status": "disconnected",
        "central_qbo": {
            "enabled": False,
            "base_url": "",
            "tenant_id": "",
            "audience": "",
            "delegated_scope": "",
        },
    }


def _load_config(paths: AppPaths, profile: str = _DEFAULT_PROFILE) -> dict:
    path = _config_path(paths, profile)
    merged = _default_config(profile)
    if not path.exists():
        return merged
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        logger.warning("QuickBooks connection metadata unreadable; using defaults")
        return merged
    if isinstance(data, dict):
        for key in merged:
            if key in data:
                merged[key] = data[key]
    return merged


def _save_config(paths: AppPaths, config: dict, profile: str = _DEFAULT_PROFILE) -> None:
    path = _config_path(paths, profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _store(profile: str = _DEFAULT_PROFILE) -> QuickBooksCredentialStore:
    """Return the profile's isolated OS-keychain store."""
    return QuickBooksCredentialStore(filename=_PROFILE_FILES[_profile_name(profile)]["credentials"])


def _profile_store(profile: str) -> QuickBooksCredentialStore:
    """Preserve the default store call shape for existing integrations/tests."""
    return _store() if profile == _DEFAULT_PROFILE else _store(profile)


def _set_pending_state(profile: str, state: str) -> None:
    global _pending_state
    if profile == _DEFAULT_PROFILE:
        _pending_state = state
    else:
        _pending_states[profile] = state


def _take_pending_state(profile: str) -> str | None:
    global _pending_state
    if profile == _DEFAULT_PROFILE:
        expected = _pending_state
        _pending_state = None
        return expected
    return _pending_states.pop(profile, None)


def _profile_for_pending_state(state: str) -> str:
    if state and _pending_state and _secrets.compare_digest(state, _pending_state):
        return _DEFAULT_PROFILE
    for profile, expected in _pending_states.items():
        if state and _secrets.compare_digest(state, expected):
            return profile
    return _DEFAULT_PROFILE


# ── time helpers ────────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_expiring(expiry_iso: str) -> bool:
    if not expiry_iso:
        return True
    try:
        expiry = datetime.strptime(expiry_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) >= expiry - timedelta(seconds=_ACCESS_TOKEN_SKEW_SECONDS)


# ── settings (app registration credentials) ─────────────────────────────────


def save_settings(
    paths: AppPaths,
    *,
    client_id: str = "",
    client_secret: str = "",
    environment: str = "production",
    redirect_uri: str = "",
    token_broker_url: str | None = None,
    profile: str = _DEFAULT_PROFILE,
) -> dict:
    """Persist the app-registration details entered by the owner.

    ``client_secret`` goes to the keychain; everything else is non-secret
    metadata. An empty ``client_secret`` leaves any existing one untouched
    so re-saving other fields doesn't wipe it.
    """
    profile = _profile_name(profile)
    if profile == PRODUCTION_PREVIEW_PROFILE and environment != "production":
        return {"ok": False, "error": "Production catalog preview only accepts production credentials."}

    config = _load_config(paths, profile)
    config["client_id"] = (client_id or "").strip()
    config["environment"] = environment if environment in ("production", "sandbox") else "production"
    config["redirect_uri"] = (redirect_uri or "").strip()
    if token_broker_url is not None:
        config["token_broker_url"] = str(token_broker_url or "").strip()
    elif config["environment"] == "sandbox":
        # The managed broker is registered only for the production callback.
        config["token_broker_url"] = ""
    _save_config(paths, config, profile)

    secret = (client_secret or "").strip()
    if secret:
        store = _profile_store(profile)
        blob = store.load()
        blob["client_secret"] = secret
        store.save(blob)

    return get_status(paths, profile=profile)


# ── OAuth handshake ─────────────────────────────────────────────────────────


def generate_auth_url(paths: AppPaths, *, profile: str = _DEFAULT_PROFILE) -> dict:
    """Create a CSRF state value and return the Intuit authorization URL."""
    profile = _profile_name(profile)
    config = _load_config(paths, profile)
    secret = _profile_store(profile).load().get("client_secret", "")
    if not config["client_id"] or not (secret or config.get("token_broker_url")):
        return {"ok": False, "error": "Set your QuickBooks Client ID and Client Secret first."}
    if not config["redirect_uri"]:
        return {"ok": False, "error": "Set the redirect URI first."}

    state = _secrets.token_urlsafe(32)
    _set_pending_state(profile, state)
    client = QuickBooksOAuthClient(
        config["client_id"], secret,
        environment=config["environment"],
        token_broker_url=config.get("token_broker_url", ""),
    )
    url = client.build_authorization_url(redirect_uri=config["redirect_uri"], state=state)
    return {"ok": True, "url": url}


def validate_state(state: str, *, profile: str = _DEFAULT_PROFILE) -> bool:
    """Constant-time, single-use validation of the OAuth state parameter."""
    expected = _take_pending_state(_profile_name(profile))
    if not expected or not state:
        return False
    return _secrets.compare_digest(expected, state)


def complete_authorization(
    paths: AppPaths,
    *,
    code: str,
    realm_id: str,
    state: str,
    profile: str | None = None,
) -> dict:
    """Validate state, exchange the code for tokens, and store them."""
    profile = _profile_name(profile or _profile_for_pending_state(state))
    if not validate_state(state, profile=profile):
        return {"ok": False, "error": "Invalid OAuth state — authorization rejected."}
    if not code:
        return {"ok": False, "error": "Missing authorization code."}

    config = _load_config(paths, profile)
    store = _profile_store(profile)
    secret = store.load().get("client_secret", "")
    client = QuickBooksOAuthClient(
        config["client_id"], secret,
        environment=config["environment"],
        token_broker_url=config.get("token_broker_url", ""),
    )
    try:
        token = client.exchange_code(code=code, redirect_uri=config["redirect_uri"])
    except QuickBooksOAuthError as exc:
        logger.warning("QuickBooks code exchange failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    _store_token(paths, store, token, realm_id=realm_id, fresh=True, profile=profile)
    logger.info("QuickBooks connected: profile=%s", profile)
    return {"ok": True, "profile": profile}


def _store_token(
    paths: AppPaths,
    store: QuickBooksCredentialStore,
    token: dict,
    *,
    realm_id: str | None = None,
    fresh: bool = False,
    profile: str = _DEFAULT_PROFILE,
) -> None:
    """Persist a token response. Rotates the refresh token every time."""
    now = datetime.now(timezone.utc)
    blob = store.load()
    blob["access_token"] = token["access_token"]
    blob["refresh_token"] = token["refresh_token"]
    if realm_id:
        blob["realm_id"] = realm_id
    store.save(blob)

    config = _load_config(paths, profile)
    access_ttl = int(token.get("expires_in", _DEFAULT_ACCESS_TTL))
    refresh_ttl = int(token.get("x_refresh_token_expires_in", _DEFAULT_REFRESH_TTL))
    config["token_expiry_utc"] = _iso(now + timedelta(seconds=access_ttl))
    config["refresh_expiry_utc"] = _iso(now + timedelta(seconds=refresh_ttl))
    if fresh or not config.get("hard_expiry_utc"):
        config["hard_expiry_utc"] = _iso(now + timedelta(days=_HARD_EXPIRY_DAYS))
    config["connection_status"] = "connected"
    _save_config(paths, config, profile)


def ensure_access_token(paths: AppPaths, *, profile: str = _DEFAULT_PROFILE) -> str:
    """Return a valid access token, refreshing (and rotating) if needed.

    Raises ``QuickBooksOAuthError`` when not connected or when the refresh
    token is dead; the connection is marked disconnected on invalid_grant
    so the UI can prompt a reconnect.
    """
    profile = _profile_name(profile)
    config = _load_config(paths, profile)
    store = _profile_store(profile)
    blob = store.load()
    access = blob.get("access_token")
    refresh = blob.get("refresh_token")
    if not refresh:
        raise QuickBooksOAuthError("not_connected")

    if access and not _is_expiring(config.get("token_expiry_utc", "")):
        return access

    client = QuickBooksOAuthClient(
        config["client_id"], blob.get("client_secret", ""),
        environment=config["environment"],
        token_broker_url=config.get("token_broker_url", ""),
    )
    try:
        token = client.refresh(refresh_token=refresh)
    except QuickBooksOAuthError as exc:
        if "invalid_grant" in str(exc).lower():
            _mark_disconnected(paths, profile=profile)
        raise
    _store_token(paths, store, token, profile=profile)
    return token["access_token"]


def get_realm_id(paths: AppPaths, *, profile: str = _DEFAULT_PROFILE) -> str:
    """Return the connected company's realm ID (empty if not connected)."""
    profile = _profile_name(profile)
    return _profile_store(profile).load().get("realm_id", "")


def set_last_sync(paths: AppPaths, when_iso: str, *, profile: str = _DEFAULT_PROFILE) -> None:
    """Record the timestamp of the most recent successful data sync."""
    config = _load_config(paths, profile)
    config["last_sync_utc"] = when_iso
    _save_config(paths, config, profile)


def get_last_sync(paths: AppPaths, *, profile: str = _DEFAULT_PROFILE) -> str | None:
    """Read non-secret sync metadata without opening any credential store."""
    return _load_config(paths, profile).get("last_sync_utc")


# ── disconnect / status ─────────────────────────────────────────────────────


def _mark_disconnected(paths: AppPaths, *, profile: str = _DEFAULT_PROFILE) -> None:
    config = _load_config(paths, profile)
    config["connection_status"] = "disconnected"
    config["token_expiry_utc"] = ""
    config["refresh_expiry_utc"] = ""
    _save_config(paths, config, profile)


def disconnect(paths: AppPaths, *, profile: str = _DEFAULT_PROFILE) -> dict:
    """Revoke the refresh token and clear stored user tokens.

    Keeps the app-registration credentials (client_id / client_secret) so
    reconnecting is a single click; only the per-user tokens and realm are
    cleared.
    """
    profile = _profile_name(profile)
    config = _load_config(paths, profile)
    store = _profile_store(profile)
    blob = store.load()
    refresh = blob.get("refresh_token")
    if refresh and config.get("client_id"):
        try:
            QuickBooksOAuthClient(
                config["client_id"], blob.get("client_secret", ""),
                environment=config["environment"],
                token_broker_url=config.get("token_broker_url", ""),
            ).revoke(token=refresh)
        except Exception:  # noqa: BLE001 — best effort; local clear still proceeds
            logger.warning("QuickBooks revoke failed during disconnect")

    for key in ("access_token", "refresh_token", "realm_id"):
        blob.pop(key, None)
    store.save(blob)

    config["token_expiry_utc"] = ""
    config["refresh_expiry_utc"] = ""
    config["hard_expiry_utc"] = ""
    config["connection_status"] = "disconnected"
    _save_config(paths, config, profile)
    logger.info("QuickBooks disconnected: profile=%s", profile)
    return {"ok": True, "profile": profile}


def get_status(paths: AppPaths, *, profile: str = _DEFAULT_PROFILE) -> dict:
    """Connection state for the Settings UI. Never includes secret values."""
    profile = _profile_name(profile)
    config = _load_config(paths, profile)
    blob = _profile_store(profile).load()
    has_secret = bool(blob.get("client_secret"))
    managed_connection = bool(config.get("token_broker_url"))
    connected = config.get("connection_status") == "connected" and bool(blob.get("refresh_token"))
    return {
        "ok": True,
        "configured": bool(config.get("client_id")) and (has_secret or managed_connection),
        "connected": connected,
        "connection_status": config.get("connection_status", "disconnected"),
        "client_id": config.get("client_id", ""),
        "environment": config.get("environment", "production"),
        "redirect_uri": config.get("redirect_uri", ""),
        "has_client_secret": has_secret,
        "managed_connection": managed_connection,
        "token_expiry_utc": config.get("token_expiry_utc", ""),
        "refresh_expiry_utc": config.get("refresh_expiry_utc", ""),
        "hard_expiry_utc": config.get("hard_expiry_utc", ""),
        "last_sync_utc": config.get("last_sync_utc"),
        "profile": profile,
        "preview_only": profile == PRODUCTION_PREVIEW_PROFILE,
        "central_mode": False,
        "managed_by_dtm": False,
    }
