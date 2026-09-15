"""Signed tenant-specific Entra identity plus revocable application sessions."""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from uuid import UUID

import jwt

from ...domain.operations_policy import AppRole
from ..adapters.interfaces import IdentityProvider, UserIdentity
from .metadata import Conflict, MetadataStore


class Denied(Exception):
    def __init__(self, status=403, code="forbidden"):
        self.status, self.code = status, code
        super().__init__(code)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    tenant: str
    user: UserIdentity
    expires: int

    @property
    def owner(self):
        return f"{self.tenant}:{self.user.user_id}"


class EntraTokens:
    def __init__(self, tenant: str, client: str, key_client=None):
        self.tenant, self.client = str(UUID(tenant)), str(UUID(client))
        self.issuer = f"https://login.microsoftonline.com/{self.tenant}/v2.0"
        self.keys = key_client or jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{self.tenant}/discovery/v2.0/keys",
            cache_keys=False, lifespan=300, timeout=5,
        )

    def verify(self, token: str) -> Principal:
        if not token or len(token) > 16384:
            raise Denied(401, "sign_in_required")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError("Invalid algorithm/key")
            # The configured JWKS URL is fixed. Token-supplied jku/x5u are ignored.
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"], audience=self.client, issuer=self.issuer,
                options={"require": ["exp", "iat", "nbf", "iss", "aud", "tid", "oid", "sub"],
                         "strict_aud": True},
            )
            if claims["tid"] != self.tenant or claims.get("ver") != "2.0":
                raise ValueError("Wrong tenant/token version")
            oid = str(UUID(claims["oid"]))
            if not isinstance(claims["sub"], str) or not claims["sub"]:
                raise ValueError("Subject required")
            assigned = claims.get("roles", [])
            if not isinstance(assigned, list) or any(not isinstance(x, str) for x in assigned):
                raise ValueError("Invalid roles")
            roles = frozenset(assigned) & frozenset(role.value for role in AppRole)
            if not roles:
                raise Denied(403, "role_assignment_required")
            return Principal(self.tenant, UserIdentity(
                user_id=oid, display_name=str(claims.get("name", ""))[:200],
                email=str(claims.get("preferred_username", ""))[:254], provider="m365", roles=roles,
            ), int(claims["exp"]))
        except Denied:
            raise
        except Exception:
            # Provider exceptions can contain tokens/URLs. Never forward them.
            raise Denied(401, "identity_unavailable") from None


class RequestIdentity(IdentityProvider):
    def __init__(self, user):
        self.user = user

    def current_user(self):
        return self.user

    def is_signed_in(self):
        return True

    def signin(self, *, force_account_picker=False):
        raise RuntimeError("Use platform sign-in")

    def signout(self):
        raise RuntimeError("Use session revocation and platform sign-out")


class Sessions:
    def __init__(self, store: MetadataStore, *, clock=time.time):
        self.store, self.clock = store, clock

    def create(self, principal):
        cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires = min(int(self.clock()) + 1800, principal.expires)
        if expires <= self.clock():
            raise Denied(401, "session_expired")
        self.store.write(principal.tenant, "session-" + digest(cookie), {
            "owner": principal.owner, "expires": expires, "csrf": digest(csrf), "revoked": False,
        }, expected=None)
        return cookie, csrf, expires

    def check(self, principal, cookie, csrf=None):
        if not cookie or len(cookie) > 128:
            raise Denied(401, "session_required")
        row = self.store.read(principal.tenant, "session-" + digest(cookie))
        if (row is None or row.value["revoked"] or row.value["owner"] != principal.owner
                or row.value["expires"] <= self.clock() or principal.expires <= self.clock()):
            raise Denied(401, "session_expired")
        if csrf is not None and not secrets.compare_digest(row.value["csrf"], digest(csrf)):
            raise Denied(403, "csrf_required")
        return row

    def revoke(self, principal, cookie):
        # Concurrent logout is idempotent; never resurrect a revoked session.
        for _ in range(4):
            row = self.store.read(principal.tenant, "session-" + digest(cookie))
            if row is None or row.value["owner"] != principal.owner or row.value["revoked"]:
                return
            try:
                self.store.write(principal.tenant, "session-" + digest(cookie),
                                 {**row.value, "revoked": True}, expected=row.etag)
                return
            except Conflict:
                continue
        raise Conflict("Session revocation contention")
