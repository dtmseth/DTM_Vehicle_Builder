"""Identity-to-capability resolution for role-gated DTM workspaces."""
from __future__ import annotations

from typing import Any

from ...domain.operations_models import OperationsActor
from ...domain.operations_policy import AppRole, Capability, capabilities_for_roles
from ..adapters.wiring import AdapterBundle, get_active_bundle


def describe_access_session(
    *,
    bundle: AdapterBundle | None = None,
    cloud_enabled: bool,
) -> dict[str, Any]:
    """Return a browser-safe description of the current app authorization.

    Production operations access trusts only an M365 identity. Cloud-off
    development uses the synthetic local AppAdmin identity so UI and route
    behavior can be exercised without SharePoint. Unknown Entra role values
    are discarded and therefore grant no capability.
    """

    active = bundle or get_active_bundle()
    try:
        user = active.identity.current_user()
    except Exception:
        return _empty_session(
            operations_ready=active.operations is not None,
            reason="identity_unavailable",
        )
    if user is None:
        return _empty_session(
            operations_ready=active.operations is not None,
            reason="sign_in_required",
        )

    from ..request_context import current_request
    context = current_request()
    if context is not None:
        trusted_provider = (
            active is context.bundle and user.provider == "m365"
            and user.user_id == context.user_id
        )
    else:
        trusted_provider = user.provider == "m365" if cloud_enabled else user.provider == "local"
    if not trusted_provider:
        return _empty_session(
            operations_ready=active.operations is not None,
            reason="identity_unavailable",
        )

    known_values = {role.value for role in AppRole}
    roles = frozenset(role for role in user.roles if role in known_values)
    capabilities = capabilities_for_roles(roles)
    default_workspace = (
        "projects"
        if Capability.PROJECTS_EDIT in capabilities
        else "operations"
        if Capability.OPERATIONS_VIEW in capabilities
        else ""
    )
    return {
        "ok": True,
        "authenticated": True,
        "user": {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "email": user.email,
        },
        "roles": sorted(roles),
        "capabilities": sorted(capability.value for capability in capabilities),
        "has_recognized_roles": bool(roles),
        "default_workspace": default_workspace,
        "operations_ready": active.operations is not None,
        "operations_write_ready": active.operations_writer is not None,
        "reason": "" if roles else "role_assignment_required",
    }


def actor_from_access_session(session: dict[str, Any]) -> OperationsActor | None:
    if not session.get("authenticated"):
        return None
    user = session.get("user")
    if not isinstance(user, dict):
        return None
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        return None
    return OperationsActor(
        user_id=user_id,
        display_name=str(user.get("display_name") or ""),
        roles=frozenset(str(role) for role in session.get("roles", ())),
    )


def _empty_session(*, operations_ready: bool, reason: str) -> dict[str, Any]:
    return {
        "ok": True,
        "authenticated": False,
        "user": None,
        "roles": [],
        "capabilities": [],
        "has_recognized_roles": False,
        "default_workspace": "",
        "operations_ready": operations_ready,
        "operations_write_ready": False,
        "reason": reason,
    }
