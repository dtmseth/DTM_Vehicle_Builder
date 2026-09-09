"""Capability checks for legacy Builder HTTP routes.

Operations routes already enforce their workstream capabilities internally.
This module protects the older project/settings surface at the server boundary
while it is incrementally migrated to route-local authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from ...domain.operations_policy import Capability
from ..adapters import wiring
from .operations_access_service import describe_access_session


@dataclass(frozen=True)
class RequestAccessDecision:
    allowed: bool
    status: int = 200
    error: str = ""


def required_capabilities(method: str, raw_path: str) -> frozenset[Capability]:
    """Return the alternative capabilities that may authorize one request."""

    method = str(method or "GET").upper()
    path = urlparse(str(raw_path or "")).path

    # Sign-in, app updates, and Operations have their own access boundaries.
    if (
        path.startswith("/api/cloud/")
        or path.startswith("/api/update/")
        or path.startswith("/api/operations/")
        or path == "/api/quickbooks/callback"
    ):
        return frozenset()

    if path.startswith("/api/quickbooks/"):
        return _quickbooks_capabilities(method, path)

    if method == "GET":
        if path.startswith("/api/"):
            return frozenset({Capability.PROJECTS_VIEW})
        return frozenset()

    if method == "POST":
        if path in {"/api/build/render-status", "/api/build/show-folder", "/open"}:
            return frozenset({Capability.PROJECTS_VIEW})
        if path in {"/api/validate", "/api/preview/plan", "/api/photo-gallery/cache-prepare"}:
            return frozenset({Capability.PROJECTS_VIEW})
        if path.startswith("/api/project/") and (
            path.endswith("/photo-gallery")
            or path.endswith("/references/discover")
            or path.endswith("/references/effective")
        ):
            return frozenset({Capability.PROJECTS_VIEW})
        if path.startswith("/api/project/") and (
            path.endswith("/lifecycle") or path.endswith("/completion")
        ):
            return frozenset({Capability.PROJECTS_LIFECYCLE_UPDATE})
        if (
            path == "/api/project/save"
            or path.startswith("/api/project/")
            or path.startswith("/api/draft/")
            or path in {"/parse", "/generate", "/api/export/pdf"}
            or path == "/api/layouts/vehicles/create"
            or path.startswith("/api/presets/")
            or path in {"/api/presets/save", "/api/presets/import-workbook"}
            or path in {"/api/agency/save", "/api/agency/default-preferences"}
        ):
            return frozenset({Capability.PROJECTS_EDIT})
        if path in {"/api/app-settings/save", "/api/estimate-charges/save", "/api/sales-rep/save"}:
            return frozenset({Capability.SETTINGS_GENERAL_MANAGE})
        if path.startswith("/api/"):
            return frozenset({Capability.SETTINGS_ADVANCED_MANAGE})
        return frozenset()

    if method == "DELETE":
        if path.startswith("/api/project/") or path.startswith("/api/draft/"):
            return frozenset({Capability.PROJECTS_EDIT})
        if path.startswith("/api/presets/"):
            return frozenset({Capability.PROJECTS_EDIT})
        if path.startswith("/api/agency/") or path.startswith("/api/sales-rep/"):
            return frozenset({Capability.SETTINGS_GENERAL_MANAGE})
        if path.startswith("/api/"):
            return frozenset({Capability.SETTINGS_ADVANCED_MANAGE})
    return frozenset()


def authorize_request(method: str, path: str) -> RequestAccessDecision:
    wanted = required_capabilities(method, path)
    if not wanted:
        return RequestAccessDecision(True)
    try:
        session = describe_access_session(
            bundle=wiring.get_active_bundle(),
            cloud_enabled=wiring._cloud_flag_enabled(),  # noqa: SLF001
        )
    except Exception:
        return RequestAccessDecision(
            False, 503, "Your app permissions could not be checked. Try again."
        )
    if not session.get("authenticated"):
        return RequestAccessDecision(False, 401, "Sign in with Microsoft 365 to use this feature.")
    granted = set(session.get("capabilities") or ())
    if any(capability.value in granted for capability in wanted):
        return RequestAccessDecision(True)
    return RequestAccessDecision(False, 403, "Your assigned app role does not allow this change.")


def _quickbooks_capabilities(method: str, path: str) -> frozenset[Capability]:
    advanced_paths = {
        "/api/quickbooks/settings",
        "/api/quickbooks/link-item",
        "/api/quickbooks/unlink-item",
        "/api/quickbooks/customer-pricing/default",
    }
    if path.startswith("/api/quickbooks/production-preview/") or path in advanced_paths:
        return frozenset({Capability.SETTINGS_ADVANCED_MANAGE})
    if path == "/api/quickbooks/status":
        return frozenset({Capability.PROJECTS_VIEW})
    # Estimate users may connect/disconnect their own keychain-backed QBO
    # session and refresh the read-only caches needed by estimate workflows.
    if method in {"GET", "POST"}:
        return frozenset({Capability.ESTIMATES_MANAGE, Capability.SETTINGS_ADVANCED_MANAGE})
    return frozenset({Capability.SETTINGS_ADVANCED_MANAGE})
