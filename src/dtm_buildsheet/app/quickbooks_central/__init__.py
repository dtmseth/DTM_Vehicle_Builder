"""Provider-neutral core for the centralized QuickBooks service.

This package contains no HTTP framework, cloud SDK, or production secret-store
implementation.  Platform adapters translate its narrow endpoint results into
Azure Functions/App Service (or an equivalent protected runtime) later.
"""

from .auth import EntraTokenValidator
from .contracts import (
    BUILDER_ADMIN_ROLE,
    BUILDER_USER_ROLE,
    AuditRecord,
    CatalogItem,
    EndpointResult,
    Principal,
    ServerCredentials,
)
from .refresh import RefreshCoordinator
from .service import CentralQuickBooksService

__all__ = [
    "BUILDER_ADMIN_ROLE",
    "BUILDER_USER_ROLE",
    "AuditRecord",
    "CatalogItem",
    "CentralQuickBooksService",
    "EndpointResult",
    "EntraTokenValidator",
    "Principal",
    "RefreshCoordinator",
    "ServerCredentials",
]
