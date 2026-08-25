"""Typed, deliberately narrow contracts for the central QuickBooks API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


BUILDER_USER_ROLE = "Builder.User"
BUILDER_ADMIN_ROLE = "Builder.Admin"


@dataclass(frozen=True)
class Principal:
    """Validated Entra identity used for authorization and audit attribution."""

    tenant_id: str
    subject: str
    object_id: str
    roles: frozenset[str]


@dataclass(frozen=True)
class ServerCredentials:
    """Latest server-held QBO credential generation.

    Secret fields are excluded from ``repr`` to reduce accidental disclosure
    during debugging.  A production adapter must encrypt these values at rest.
    """

    realm_id: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_expires_at: float
    version: int = 0


@dataclass(frozen=True)
class RefreshResult:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_expires_at: float


@dataclass(frozen=True)
class CatalogItem:
    """Only the normalized QBO Item fields the desktop catalog needs."""

    qb_item_id: str
    name: str
    sku: str = ""
    description: str = ""
    unit_price: float | None = None
    type: str = ""
    active: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CatalogItem":
        item_id = str(value.get("qb_item_id") or "").strip()
        if not item_id:
            raise ValueError("catalog_item_missing_id")
        price = value.get("unit_price")
        if price is not None:
            price = float(price)
        return cls(
            qb_item_id=item_id[:128],
            name=str(value.get("name") or "").strip()[:500],
            sku=str(value.get("sku") or "").strip()[:256],
            description=str(value.get("description") or "").strip()[:4000],
            unit_price=price,
            type=str(value.get("type") or "").strip()[:100],
            active=bool(value.get("active", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "qb_item_id": self.qb_item_id,
            "name": self.name,
            "sku": self.sku,
            "description": self.description,
            "unit_price": self.unit_price,
            "type": self.type,
            "active": self.active,
        }


@dataclass(frozen=True)
class AuditRecord:
    """Append-only Builder attribution record; never contains payloads/tokens."""

    occurred_at: str
    tenant_id: str
    user_object_id: str
    action: str
    outcome: str
    correlation_id: str
    entity_type: str = ""
    entity_id: str = ""
    project_id: str = ""
    vehicle_id: str = ""
    error_code: str = ""


@dataclass(frozen=True)
class EndpointResult:
    """Framework-neutral HTTP-shaped result for a thin deployment adapter."""

    status_code: int
    body: dict[str, Any]
