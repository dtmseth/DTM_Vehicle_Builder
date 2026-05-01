"""Compatibility shim — import from domain package instead."""
from .domain import (  # noqa: F401
    BuildPlan,
    PartInput,
    PlannedPart,
    PlannedPlacement,
    ProjectInput,
    RenderInstance,
)
