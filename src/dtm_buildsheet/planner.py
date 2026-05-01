# Compatibility shim — internal code should import from .planning directly.
from .planning.planner import build_plan as build_plan  # noqa: PLC0414
