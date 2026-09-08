"""Central role-to-capability policy for Builder and operations workspaces."""
from __future__ import annotations

from enum import StrEnum
from typing import Iterable


class AppRole(StrEnum):
    APP_ADMIN = "AppAdmin"
    BUILDER_EDITOR = "BuilderEditor"
    OPERATIONS_MANAGER = "OperationsManager"
    PARTS_EDITOR = "PartsEditor"
    SHOP_EDITOR = "ShopEditor"
    PROGRAMMING_QC_EDITOR = "ProgrammingQcEditor"
    OPERATIONS_VIEWER = "OperationsViewer"


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
    PROJECTS_EDIT = "projects.edit"
    PROJECTS_LIFECYCLE_UPDATE = "projects.lifecycle.update"
    ESTIMATES_MANAGE = "estimates.manage"
    SETTINGS_GENERAL_MANAGE = "settings.general.manage"
    SETTINGS_ADVANCED_MANAGE = "settings.advanced.manage"
    ROLES_INSPECT = "roles.inspect"


ALL_CAPABILITIES = frozenset(Capability)


ROLE_CAPABILITIES: dict[AppRole, frozenset[Capability]] = {
    AppRole.APP_ADMIN: ALL_CAPABILITIES,
    AppRole.BUILDER_EDITOR: frozenset({
        Capability.OPERATIONS_VIEW,
        Capability.OPERATIONS_AVAILABILITY_UPDATE,
        Capability.OPERATIONS_QBO_OBSERVE,
        Capability.PROJECTS_EDIT,
        Capability.PROJECTS_LIFECYCLE_UPDATE,
        Capability.ESTIMATES_MANAGE,
    }),
    AppRole.OPERATIONS_MANAGER: frozenset({
        Capability.OPERATIONS_VIEW,
        Capability.OPERATIONS_AVAILABILITY_UPDATE,
        Capability.OPERATIONS_SCHEDULE_UPDATE,
        Capability.OPERATIONS_PARTS_UPDATE,
        Capability.OPERATIONS_SHOP_UPDATE,
        Capability.OPERATIONS_TRAY_UPDATE,
        Capability.OPERATIONS_PROGRAMMING_QC_UPDATE,
        Capability.OPERATIONS_FINAL_FINISH_UPDATE,
        Capability.OPERATIONS_DELIVERY_UPDATE,
        Capability.OPERATIONS_CORRECT,
        Capability.OPERATIONS_QBO_OBSERVE,
        Capability.PROJECTS_LIFECYCLE_UPDATE,
    }),
    AppRole.PARTS_EDITOR: frozenset({
        Capability.OPERATIONS_VIEW,
        Capability.OPERATIONS_PARTS_UPDATE,
    }),
    AppRole.SHOP_EDITOR: frozenset({
        Capability.OPERATIONS_VIEW,
        Capability.OPERATIONS_SHOP_UPDATE,
        Capability.OPERATIONS_TRAY_UPDATE,
        Capability.OPERATIONS_FINAL_FINISH_UPDATE,
    }),
    AppRole.PROGRAMMING_QC_EDITOR: frozenset({
        Capability.OPERATIONS_VIEW,
        Capability.OPERATIONS_PROGRAMMING_QC_UPDATE,
        Capability.OPERATIONS_FINAL_FINISH_UPDATE,
    }),
    AppRole.OPERATIONS_VIEWER: frozenset({Capability.OPERATIONS_VIEW}),
}


def capabilities_for_roles(roles: Iterable[AppRole | str]) -> frozenset[Capability]:
    capabilities: set[Capability] = set()
    for value in roles:
        try:
            role = value if isinstance(value, AppRole) else AppRole(str(value))
        except ValueError:
            continue
        capabilities.update(ROLE_CAPABILITIES[role])
    return frozenset(capabilities)


def has_capability(roles: Iterable[AppRole | str], capability: Capability | str) -> bool:
    try:
        wanted = capability if isinstance(capability, Capability) else Capability(str(capability))
    except ValueError:
        return False
    return wanted in capabilities_for_roles(roles)
