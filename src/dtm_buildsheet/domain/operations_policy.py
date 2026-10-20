"""Central role-to-capability policy for Builder and operations workspaces."""
from __future__ import annotations

from enum import StrEnum
from typing import Iterable


class AppRole(StrEnum):
    ADMIN = "Admin"
    STAFF = "Staff"
    SHOP = "Shop"

    # Source-compatible aliases for internal callers while Entra assignments
    # move to the three public role values above.
    APP_ADMIN = "Admin"
    BUILDER_EDITOR = "Staff"
    OPERATIONS_MANAGER = "Staff"
    PARTS_EDITOR = "Staff"
    SHOP_EDITOR = "Shop"
    PROGRAMMING_QC_EDITOR = "Shop"


class Capability(StrEnum):
    OPERATIONS_VIEW = "operations.view"
    OPERATIONS_AVAILABILITY_UPDATE = "operations.availability.update"
    OPERATIONS_SCHEDULE_UPDATE = "operations.schedule.update"
    OPERATIONS_PARTS_UPDATE = "operations.parts.update"
    OPERATIONS_SHOP_UPDATE = "operations.shop.update"
    OPERATIONS_TRAY_UPDATE = "operations.tray.update"
    OPERATIONS_PROGRAMMING_QC_UPDATE = "operations.programming_qc.update"
    OPERATIONS_FINAL_FINISH_UPDATE = "operations.final_finish.update"
    OPERATIONS_DELIVERY_UPDATE = "operations.delivery.update"
    OPERATIONS_CORRECT = "operations.correct"
    OPERATIONS_QBO_OBSERVE = "operations.qbo.observe"
    PROJECTS_VIEW = "projects.view"
    PROJECTS_EDIT = "projects.edit"
    PROJECTS_LIFECYCLE_UPDATE = "projects.lifecycle.update"
    PROJECT_MEDIA_UPLOAD = "project_media.upload"
    COMPLETED_MEDIA_UPLOAD = "completed_media.upload"
    ESTIMATES_MANAGE = "estimates.manage"
    SETTINGS_GENERAL_MANAGE = "settings.general.manage"
    SETTINGS_ADVANCED_MANAGE = "settings.advanced.manage"
    ROLES_INSPECT = "roles.inspect"


ALL_CAPABILITIES = frozenset(
    capability
    for capability in Capability
    if capability is not Capability.OPERATIONS_TRAY_UPDATE
)


LEGACY_ROLE_ALIASES: dict[str, AppRole] = {
    "AppAdmin": AppRole.ADMIN,
    "BuilderEditor": AppRole.STAFF,
    "OperationsManager": AppRole.STAFF,
    "PartsEditor": AppRole.STAFF,
    "ShopEditor": AppRole.SHOP,
    "ProgrammingQcEditor": AppRole.SHOP,
}


def normalize_app_role(value: AppRole | str) -> AppRole | None:
    if isinstance(value, AppRole):
        return AppRole(value.value)
    raw = str(value or "").strip()
    try:
        return AppRole(raw)
    except ValueError:
        return LEGACY_ROLE_ALIASES.get(raw)


ROLE_CAPABILITIES: dict[AppRole, frozenset[Capability]] = {
    AppRole.ADMIN: ALL_CAPABILITIES,
    AppRole.STAFF: ALL_CAPABILITIES - frozenset({Capability.SETTINGS_ADVANCED_MANAGE}),
    AppRole.SHOP: frozenset({
        Capability.OPERATIONS_VIEW,
        Capability.OPERATIONS_SHOP_UPDATE,
        Capability.OPERATIONS_PROGRAMMING_QC_UPDATE,
        Capability.OPERATIONS_FINAL_FINISH_UPDATE,
        Capability.PROJECTS_VIEW,
        Capability.COMPLETED_MEDIA_UPLOAD,
    }),
}


def capabilities_for_roles(roles: Iterable[AppRole | str]) -> frozenset[Capability]:
    capabilities: set[Capability] = set()
    for value in roles:
        role = normalize_app_role(value)
        if role is None:
            continue
        capabilities.update(ROLE_CAPABILITIES[role])
    return frozenset(capabilities)


def has_capability(roles: Iterable[AppRole | str], capability: Capability | str) -> bool:
    try:
        wanted = capability if isinstance(capability, Capability) else Capability(str(capability))
    except ValueError:
        return False
    return wanted in capabilities_for_roles(roles)
