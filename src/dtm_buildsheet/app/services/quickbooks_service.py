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

Secrets (``client_secret``, ``access_token``, ``refresh_token``,
``realm_id``) live ONLY in the keychain. This module never logs them.

See ``docs/QUICKBOOKS_INTEGRATION.md``.
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

_CONFIG_FILENAME = "quickbooks_config.json"
_ACCESS_TOKEN_SKEW_SECONDS = 300        # refresh 5 minutes before expiry
_DEFAULT_ACCESS_TTL = 3600              # 1 hour, per Intuit
_DEFAULT_REFRESH_TTL = 8726400         # ~101 days, per Intuit
_HARD_EXPIRY_DAYS = 5 * 365             # Intuit's 5-year hard cap

# In-process CSRF state for the one-time OAuth handshake. Set when the auth
# URL is generated, consumed once on callback. A module global is sufficient
# for a single-process desktop app.
_pending_state: str | None = None


# ── config metadata (non-secret) ───────────────────────────────────────────


def _config_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / _CONFIG_FILENAME


def _default_config() -> dict:
    return {
        "client_id": "",
        "environment": "production",
        "redirect_uri": "",
        "token_expiry_utc": "",
        "refresh_expiry_utc": "",
        "hard_expiry_utc": "",
        "last_sync_utc": None,
        "connection_status": "disconnected",
    }


def _load_config(paths: AppPaths) -> dict:
    path = _config_path(paths)
    merged = _default_config()
    if not path.exists():
        return merged
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        logger.warning("quickbooks_config.json unreadable; using defaults")
        return merged
    if isinstance(data, dict):
        for key in merged:
            if key in data:
                merged[key] = data[key]
    return merged


def _save_config(paths: AppPaths, config: dict) -> None:
    path = _config_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _store() -> QuickBooksCredentialStore:
    return QuickBooksCredentialStore()


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
) -> dict:
    """Persist the app-registration details entered by the owner.

    ``client_secret`` goes to the keychain; everything else is non-secret
    metadata. An empty ``client_secret`` leaves any existing one untouched
    so re-saving other fields doesn't wipe it.
    """
    config = _load_config(paths)
    config["client_id"] = (client_id or "").strip()
    config["environment"] = environment if environment in ("production", "sandbox") else "production"
    config["redirect_uri"] = (redirect_uri or "").strip()
    _save_config(paths, config)

    secret = (client_secret or "").strip()
    if secret:
        store = _store()
        blob = store.load()
        blob["client_secret"] = secret
        store.save(blob)

    return get_status(paths)


# ── OAuth handshake ─────────────────────────────────────────────────────────


def generate_auth_url(paths: AppPaths) -> dict:
    """Create a CSRF state value and return the Intuit authorization URL."""
    global _pending_state
    config = _load_config(paths)
    secret = _store().load().get("client_secret", "")
    if not config["client_id"] or not secret:
        return {"ok": False, "error": "Set your QuickBooks Client ID and Client Secret first."}
    if not config["redirect_uri"]:
        return {"ok": False, "error": "Set the redirect URI first."}

    _pending_state = _secrets.token_urlsafe(32)
    client = QuickBooksOAuthClient(config["client_id"], secret, environment=config["environment"])
    url = client.build_authorization_url(redirect_uri=config["redirect_uri"], state=_pending_state)
    return {"ok": True, "url": url}


def validate_state(state: str) -> bool:
    """Constant-time, single-use validation of the OAuth state parameter."""
    global _pending_state
    expected = _pending_state
    _pending_state = None  # consume once regardless of outcome
    if not expected or not state:
        return False
    return _secrets.compare_digest(expected, state)


def complete_authorization(paths: AppPaths, *, code: str, realm_id: str, state: str) -> dict:
    """Validate state, exchange the code for tokens, and store them."""
    if not validate_state(state):
        return {"ok": False, "error": "Invalid OAuth state — authorization rejected."}
    if not code:
        return {"ok": False, "error": "Missing authorization code."}

    config = _load_config(paths)
    store = _store()
    secret = store.load().get("client_secret", "")
    client = QuickBooksOAuthClient(config["client_id"], secret, environment=config["environment"])
    try:
        token = client.exchange_code(code=code, redirect_uri=config["redirect_uri"])
    except QuickBooksOAuthError as exc:
        logger.warning("QuickBooks code exchange failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    _store_token(paths, store, token, realm_id=realm_id, fresh=True)
    logger.info("QuickBooks connected")
    return {"ok": True}


def _store_token(
    paths: AppPaths,
    store: QuickBooksCredentialStore,
    token: dict,
    *,
    realm_id: str | None = None,
    fresh: bool = False,
) -> None:
    """Persist a token response. Rotates the refresh token every time."""
    now = datetime.now(timezone.utc)
    blob = store.load()
    blob["access_token"] = token["access_token"]
    blob["refresh_token"] = token["refresh_token"]
    if realm_id:
        blob["realm_id"] = realm_id
    store.save(blob)

    config = _load_config(paths)
    access_ttl = int(token.get("expires_in", _DEFAULT_ACCESS_TTL))
    refresh_ttl = int(token.get("x_refresh_token_expires_in", _DEFAULT_REFRESH_TTL))
    config["token_expiry_utc"] = _iso(now + timedelta(seconds=access_ttl))
    config["refresh_expiry_utc"] = _iso(now + timedelta(seconds=refresh_ttl))
    if fresh or not config.get("hard_expiry_utc"):
        config["hard_expiry_utc"] = _iso(now + timedelta(days=_HARD_EXPIRY_DAYS))
    config["connection_status"] = "connected"
    _save_config(paths, config)


def ensure_access_token(paths: AppPaths) -> str:
    """Return a valid access token, refreshing (and rotating) if needed.

    Raises ``QuickBooksOAuthError`` when not connected or when the refresh
    token is dead; the connection is marked disconnected on invalid_grant
    so the UI can prompt a reconnect.
    """
    config = _load_config(paths)
    store = _store()
    blob = store.load()
    access = blob.get("access_token")
    refresh = blob.get("refresh_token")
    if not refresh:
        raise QuickBooksOAuthError("not_connected")

    if access and not _is_expiring(config.get("token_expiry_utc", "")):
        return access

    client = QuickBooksOAuthClient(
        config["client_id"], blob.get("client_secret", ""), environment=config["environment"]
    )
    try:
        token = client.refresh(refresh_token=refresh)
    except QuickBooksOAuthError as exc:
        if "invalid_grant" in str(exc).lower():
            _mark_disconnected(paths)
        raise
    _store_token(paths, store, token)
    return token["access_token"]


def get_realm_id(paths: AppPaths) -> str:
    """Return the connected company's realm ID (empty if not connected)."""
    return _store().load().get("realm_id", "")


def set_last_sync(paths: AppPaths, when_iso: str) -> None:
    """Record the timestamp of the most recent successful data sync."""
    config = _load_config(paths)
    config["last_sync_utc"] = when_iso
    _save_config(paths, config)


# ── disconnect / status ─────────────────────────────────────────────────────


def _mark_disconnected(paths: AppPaths) -> None:
    config = _load_config(paths)
    config["connection_status"] = "disconnected"
    config["token_expiry_utc"] = ""
    config["refresh_expiry_utc"] = ""
    _save_config(paths, config)


def disconnect(paths: AppPaths) -> dict:
    """Revoke the refresh token and clear stored user tokens.

    Keeps the app-registration credentials (client_id / client_secret) so
    reconnecting is a single click; only the per-user tokens and realm are
    cleared.
    """
    config = _load_config(paths)
    store = _store()
    blob = store.load()
    refresh = blob.get("refresh_token")
    if refresh and config.get("client_id"):
        try:
            QuickBooksOAuthClient(
                config["client_id"], blob.get("client_secret", ""), environment=config["environment"]
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
    _save_config(paths, config)
    logger.info("QuickBooks disconnected")
    return {"ok": True}


def get_status(paths: AppPaths) -> dict:
    """Connection state for the Settings UI. Never includes secret values."""
    config = _load_config(paths)
    blob = _store().load()
    has_secret = bool(blob.get("client_secret"))
    connected = config.get("connection_status") == "connected" and bool(blob.get("refresh_token"))
    return {
        "ok": True,
        "configured": bool(config.get("client_id")) and has_secret,
        "connected": connected,
        "connection_status": config.get("connection_status", "disconnected"),
        "client_id": config.get("client_id", ""),
        "environment": config.get("environment", "production"),
        "redirect_uri": config.get("redirect_uri", ""),
        "has_client_secret": has_secret,
        "token_expiry_utc": config.get("token_expiry_utc", ""),
        "refresh_expiry_utc": config.get("refresh_expiry_utc", ""),
        "hard_expiry_utc": config.get("hard_expiry_utc", ""),
        "last_sync_utc": config.get("last_sync_utc"),
    }
