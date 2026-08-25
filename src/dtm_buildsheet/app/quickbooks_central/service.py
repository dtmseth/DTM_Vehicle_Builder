"""Narrow, backend-neutral endpoints for the central QuickBooks service."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Callable

from .auth import EntraTokenValidator
from .contracts import (
    BUILDER_ADMIN_ROLE,
    BUILDER_USER_ROLE,
    AuditRecord,
    CatalogItem,
    EndpointResult,
    Principal,
)
from .errors import CentralServiceError, safe_error_result
from .interfaces import AuditStore, QboProvider
from .refresh import RefreshCoordinator


class CentralQuickBooksService:
    """Core for health and read-only Item endpoints; never an arbitrary proxy."""

    def __init__(
        self,
        *,
        realm_key: str,
        identity: EntraTokenValidator,
        refresh: RefreshCoordinator,
        qbo: QboProvider,
        audit: AuditStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not realm_key:
            raise ValueError("realm_key_required")
        self._realm_key = realm_key
        self._identity = identity
        self._refresh = refresh
        self._qbo = qbo
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _bearer(authorization: str) -> str:
        scheme, separator, token = str(authorization or "").partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise CentralServiceError("unauthenticated", status_code=401)
        return token.strip()

    @staticmethod
    def _correlation_id(value: str) -> str:
        candidate = str(value or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate):
            return candidate
        return secrets.token_hex(16)

    def _audit_record(
        self,
        principal: Principal,
        *,
        action: str,
        outcome: str,
        correlation_id: str,
        entity_type: str,
        error_code: str = "",
    ) -> None:
        self._audit.append(
            AuditRecord(
                occurred_at=self._clock().astimezone(timezone.utc).isoformat(),
                tenant_id=principal.tenant_id,
                user_object_id=principal.object_id,
                action=action,
                outcome=outcome,
                correlation_id=correlation_id,
                entity_type=entity_type,
                error_code=error_code,
            )
        )

    def _audit_failure_best_effort(self, principal: Principal, **kwargs) -> None:
        """Keep the final error boundary safe even if durable audit is down."""
        try:
            self._audit_record(principal, **kwargs)
        except Exception:  # noqa: BLE001 - deployment adapter detail stays server-side
            pass

    def _authorized(
        self,
        authorization: str,
        *,
        required_role: str,
    ) -> Principal:
        return self._identity.authorize(self._bearer(authorization), required_role)

    def connection_health(
        self,
        authorization: str,
        *,
        correlation_id: str,
        admin_details: bool = False,
    ) -> EndpointResult:
        correlation_id = self._correlation_id(correlation_id)
        principal: Principal | None = None
        action = "quickbooks.connection_health.admin" if admin_details else "quickbooks.connection_health"
        try:
            principal = self._authorized(
                authorization,
                required_role=BUILDER_ADMIN_ROLE if admin_details else BUILDER_USER_ROLE,
            )
            credentials = self._refresh.get(self._realm_key)
            try:
                provider_health = self._qbo.connection_health(
                    access_token=credentials.access_token,
                    realm_id=credentials.realm_id,
                )
            except Exception:  # noqa: BLE001 - provider detail is never exposed
                raise CentralServiceError("provider_unavailable", status_code=503) from None
            connected = bool(provider_health.get("connected"))
            body = {
                "ok": True,
                "connected": connected,
                "connection_status": "connected" if connected else "unavailable",
                "managed_by_dtm": True,
                "environment": str(provider_health.get("environment") or "production"),
                "correlation_id": correlation_id,
            }
            if admin_details:
                body["admin"] = {
                    "realm_bound": bool(credentials.realm_id),
                    "credential_generation": credentials.version,
                }
            self._audit_record(
                principal,
                action=action,
                outcome="success",
                correlation_id=correlation_id,
                entity_type="QuickBooksConnection",
            )
            return EndpointResult(200, body)
        except CentralServiceError as error:
            if principal is not None:
                self._audit_failure_best_effort(
                    principal,
                    action=action,
                    outcome="failure",
                    correlation_id=correlation_id,
                    entity_type="QuickBooksConnection",
                    error_code=error.code,
                )
            return safe_error_result(error, correlation_id)
        except Exception:  # noqa: BLE001 - final redaction boundary
            if principal is not None:
                self._audit_failure_best_effort(
                    principal,
                    action=action,
                    outcome="failure",
                    correlation_id=correlation_id,
                    entity_type="QuickBooksConnection",
                    error_code="internal_error",
                )
            return safe_error_result(CentralServiceError("internal_error"), correlation_id)

    def active_items(self, authorization: str, *, correlation_id: str) -> EndpointResult:
        correlation_id = self._correlation_id(correlation_id)
        principal: Principal | None = None
        try:
            principal = self._authorized(authorization, required_role=BUILDER_USER_ROLE)
            credentials = self._refresh.get(self._realm_key)
            try:
                raw_items = self._qbo.fetch_active_items(
                    access_token=credentials.access_token,
                    realm_id=credentials.realm_id,
                )
                items = [CatalogItem.from_mapping(item).to_dict() for item in raw_items]
            except ValueError:
                raise CentralServiceError("invalid_provider_data", status_code=502) from None
            except Exception:  # noqa: BLE001 - provider detail is never exposed
                raise CentralServiceError("provider_unavailable", status_code=503) from None
            self._audit_record(
                principal,
                action="quickbooks.catalog.active_items.read",
                outcome="success",
                correlation_id=correlation_id,
                entity_type="ItemCatalog",
            )
            return EndpointResult(
                200,
                {
                    "ok": True,
                    "items": items,
                    "item_count": len(items),
                    "correlation_id": correlation_id,
                },
            )
        except CentralServiceError as error:
            if principal is not None:
                self._audit_failure_best_effort(
                    principal,
                    action="quickbooks.catalog.active_items.read",
                    outcome="failure",
                    correlation_id=correlation_id,
                    entity_type="ItemCatalog",
                    error_code=error.code,
                )
            return safe_error_result(error, correlation_id)
        except Exception:  # noqa: BLE001 - final redaction boundary
            if principal is not None:
                self._audit_failure_best_effort(
                    principal,
                    action="quickbooks.catalog.active_items.read",
                    outcome="failure",
                    correlation_id=correlation_id,
                    entity_type="ItemCatalog",
                    error_code="internal_error",
                )
            return safe_error_result(CentralServiceError("internal_error"), correlation_id)
