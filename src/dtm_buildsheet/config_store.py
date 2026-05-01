# Compatibility shim — internal code should import from .config directly.
from .config.store import (  # noqa: PLC0414
    get_config_path as get_config_path,
    load_config as load_config,
    load_json_file as load_json_file,
    save_config as save_config,
)
