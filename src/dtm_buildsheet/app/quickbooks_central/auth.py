"""Entra claim validation and Builder role authorization."""

from __future__ import annotations

import time
from collections.abc import Mapping

from .contracts import BUILDER_ADMIN_ROLE, BUILDER_USER_ROLE, Principal
from .errors import CentralServiceError
from .interfaces import SignatureVerifier


class EntraTokenValidator:
    """Validate signature, audience, tenant, expiry, subject, and app role.

    The injected verifier owns Entra discovery/JWKS retrieval and MUST reject
    an invalid signature or algorithm before returning claims.  This split
    keeps the core deployment-neutral while making signature verification a
    mandatory constructor dependency rather than an optional check.
    """

    def __init__(
        self,
        *,
        verifier: SignatureVerifier,
        tenant_id: str,
        audience: str,
        role_group_map: Mapping[str, str] | None = None,
        now: callable = time.time,
    ) -> None:
        if not tenant_id or not audience:
            raise ValueError("tenant_id_and_audience_required")
        self._verifier = verifier
        self._tenant_id = tenant_id
        self._audience = audience
        self._role_group_map = dict(role_group_map or {})
        self._now = now

    def validate(self, token: str) -> Principal:
        if not token:
            raise CentralServiceError("unauthenticated", status_code=401)
        try:
            claims = self._verifier.verify(token)
        except Exception:  # noqa: BLE001 - verifier detail is never exposed
            raise CentralServiceError("invalid_token", status_code=401) from None

        if str(claims.get("tid") or "") != self._tenant_id:
            raise CentralServiceError("wrong_tenant", status_code=401)

        audience = claims.get("aud")
        audiences = {str(v) for v in audience} if isinstance(audience, list) else {str(audience or "")}
        if self._audience not in audiences:
            raise CentralServiceError("wrong_audience", status_code=401)

        try:
            expires_at = float(claims.get("exp"))
        except (TypeError, ValueError):
            raise CentralServiceError("expired_token", status_code=401) from None
        if expires_at <= float(self._now()):
            raise CentralServiceError("expired_token", status_code=401)

        token_subject = str(claims.get("sub") or "").strip()
        object_id = str(claims.get("oid") or "").strip()
        if not token_subject or not object_id:
            raise CentralServiceError("missing_subject", status_code=401)

        raw_roles = claims.get("roles") or []
        roles = {str(role) for role in raw_roles if role} if isinstance(raw_roles, list) else set()
        raw_groups = claims.get("groups") or []
        if isinstance(raw_groups, list):
            roles.update(
                self._role_group_map[group]
                for group in map(str, raw_groups)
                if group in self._role_group_map
            )
        return Principal(
            tenant_id=self._tenant_id,
            subject=token_subject,
            object_id=object_id,
            roles=frozenset(roles),
        )

    def authorize(self, token: str, required_role: str) -> Principal:
        principal = self.validate(token)
        allowed = required_role in principal.roles
        if required_role == BUILDER_USER_ROLE and BUILDER_ADMIN_ROLE in principal.roles:
            allowed = True
        if not allowed:
            raise CentralServiceError("forbidden", status_code=403)
        return principal
