# Compatibility shim — internal code should import from .config directly.
from .config.schemas import (  # noqa: PLC0414
    REQUIRED_CONFIG_FILES as REQUIRED_CONFIG_FILES,
    validate_config_payload as validate_config_payload,
)
