"""Phase 1 tests for the QuickBooks OAuth + token-management service.

Hermetic: the OS-keychain credential store and the Intuit HTTP client are
both replaced with in-process fakes, so these tests never touch the real
keychain, the network, or the user's home directory.
"""

from __future__ import annotations

import pytest

from dtm_buildsheet.app.services import quickbooks_service as svc
from dtm_buildsheet.app.adapters.quickbooks.oauth_client import QuickBooksOAuthError
from dtm_buildsheet.paths import AppPaths


class _MemStore:
    """In-memory stand-in for QuickBooksCredentialStore."""

    def __init__(self) -> None:
        self.data: dict = {}

    def load(self) -> dict:
        return dict(self.data)

    def save(self, secrets: dict) -> None:
        self.data = dict(secrets)

    def clear(self) -> None:
        self.data = {}


class _FakeClient:
    """Stand-in for QuickBooksOAuthClient."""

    def __init__(self, client_id, client_secret, *, environment="production"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.environment = environment

    def build_authorization_url(self, *, redirect_uri, state):
        return f"https://appcenter.example/connect?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, *, code, redirect_uri):
        if code != "AUTHCODE":
            raise QuickBooksOAuthError("invalid_grant")
        return {
            "access_token": "ACC1",
            "refresh_token": "REF1",
            "expires_in": 3600,
            "x_refresh_token_expires_in": 8726400,
        }

    def refresh(self, *, refresh_token):
        if refresh_token == "DEAD":
            raise QuickBooksOAuthError("invalid_grant")
        return {
            "access_token": "ACC2",
            "refresh_token": "REF2",
            "expires_in": 3600,
            "x_refresh_token_expires_in": 8726400,
        }

    def revoke(self, *, token):
        return True


@pytest.fixture
def paths(tmp_path):
    return AppPaths(workspace_dir=tmp_path)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    store = _MemStore()
    monkeypatch.setattr(svc, "_store", lambda: store)
    monkeypatch.setattr(svc, "QuickBooksOAuthClient", _FakeClient)
    monkeypatch.setattr(svc, "_pending_state", None, raising=False)
    return store


def _connect(paths):
    r = svc.generate_auth_url(paths)
    state = r["url"].split("state=")[1].split("&")[0]
    return svc.complete_authorization(paths, code="AUTHCODE", realm_id="R1", state=state)


# ── settings ────────────────────────────────────────────────────────────────


def test_initial_status_unconfigured(paths):
    st = svc.get_status(paths)
    assert st["configured"] is False
    assert st["connected"] is False
    assert st["connection_status"] == "disconnected"


def test_save_settings_splits_secret_from_metadata(paths, _fakes):
    svc.save_settings(
        paths, client_id="CID", client_secret="SEC",
        environment="sandbox", redirect_uri="https://r.example/cb",
    )
    config_text = (paths.workspace_dir / "quickbooks_config.json").read_text()
    assert "CID" in config_text
    assert "SEC" not in config_text            # secret never on disk
    assert _fakes.data["client_secret"] == "SEC"
    st = svc.get_status(paths)
    assert st["configured"] is True
    assert st["environment"] == "sandbox"


def test_save_settings_empty_secret_preserves_existing(paths, _fakes):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    svc.save_settings(paths, client_id="CID2", client_secret="", redirect_uri="https://r/cb")
    assert _fakes.data["client_secret"] == "SEC"
    assert svc.get_status(paths)["client_id"] == "CID2"


# ── OAuth handshake ───────────────────────────────────────────────────────────


def test_auth_url_requires_credentials(paths):
    assert svc.generate_auth_url(paths)["ok"] is False


def test_auth_url_sets_pending_state(paths):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    r = svc.generate_auth_url(paths)
    assert r["ok"] is True
    state = r["url"].split("state=")[1].split("&")[0]
    assert svc._pending_state == state


def test_state_validation_is_single_use(paths):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    r = svc.generate_auth_url(paths)
    state = r["url"].split("state=")[1].split("&")[0]
    assert svc.validate_state(state) is True
    assert svc.validate_state(state) is False   # consumed


def test_callback_rejects_bad_state(paths):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    svc.generate_auth_url(paths)
    res = svc.complete_authorization(paths, code="AUTHCODE", realm_id="R1", state="WRONG")
    assert res["ok"] is False
    assert svc._pending_state is None           # consumed even on failure


# ── connect / tokens ──────────────────────────────────────────────────────────


def test_full_connect_stores_secrets_off_disk(paths, _fakes):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    assert _connect(paths)["ok"] is True

    config_text = (paths.workspace_dir / "quickbooks_config.json").read_text()
    for secret in ("ACC1", "REF1", "R1"):
        assert secret not in config_text       # tokens + realm never on disk
    assert _fakes.data["realm_id"] == "R1"
    assert svc.get_realm_id(paths) == "R1"

    st = svc.get_status(paths)
    assert st["connected"] is True
    assert st["hard_expiry_utc"]


def test_access_token_cached_when_fresh(paths):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    _connect(paths)
    assert svc.ensure_access_token(paths) == "ACC1"


def test_refresh_rotates_refresh_token(paths, _fakes):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    _connect(paths)
    # Force the access token to look expired.
    cfg = svc._load_config(paths)
    cfg["token_expiry_utc"] = "2000-01-01T00:00:00Z"
    svc._save_config(paths, cfg)

    assert svc.ensure_access_token(paths) == "ACC2"
    assert _fakes.data["refresh_token"] == "REF2"   # rotated, not reused
    assert _fakes.data["access_token"] == "ACC2"


def test_invalid_grant_marks_disconnected(paths, _fakes):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    _connect(paths)
    _fakes.data["refresh_token"] = "DEAD"
    cfg = svc._load_config(paths)
    cfg["token_expiry_utc"] = "2000-01-01T00:00:00Z"
    svc._save_config(paths, cfg)

    with pytest.raises(QuickBooksOAuthError):
        svc.ensure_access_token(paths)
    assert svc.get_status(paths)["connection_status"] == "disconnected"


def test_ensure_access_token_when_not_connected(paths):
    with pytest.raises(QuickBooksOAuthError):
        svc.ensure_access_token(paths)


# ── disconnect ────────────────────────────────────────────────────────────────


def test_disconnect_clears_tokens_keeps_app_creds(paths, _fakes):
    svc.save_settings(paths, client_id="CID", client_secret="SEC", redirect_uri="https://r/cb")
    _connect(paths)
    assert svc.disconnect(paths)["ok"] is True

    st = svc.get_status(paths)
    assert st["connected"] is False
    assert st["configured"] is True             # app creds retained
    assert st["has_client_secret"] is True
    for key in ("access_token", "refresh_token", "realm_id"):
        assert key not in _fakes.data
    assert _fakes.data["client_secret"] == "SEC"
