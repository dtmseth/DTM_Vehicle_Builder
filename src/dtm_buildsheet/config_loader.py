# Compatibility shim — internal code should import from .config directly.
from .config.loader import ConfigBundle as ConfigBundle, load_configs as load_configs  # noqa: PLC0414
