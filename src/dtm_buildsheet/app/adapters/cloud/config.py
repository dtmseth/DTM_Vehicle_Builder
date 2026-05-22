from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from ....paths import WORKSPACE_DIR

logger = logging.getLogger(__name__)


# Microsoft Graph scopes for delegated SharePoint access.
#
# `Files.ReadWrite.All` covers OneDrive + every SharePoint file the user has
# access to. Without the `.All` suffix the scope is limited to the user's
# personal OneDrive — writes to SharePoint return 403. `Sites.Read.All`
# stays in the request so site metadata lookups (drive lists, item children)
# work even when the per-item ACL would block a file read.
GRAPH_SCOPES: tuple[str, ...] = ("Files.ReadWrite.All", "Sites.Read.All")

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"

# Optional on-disk fallback when env vars are unset. Lives under the
# workspace (gitignored in dev; per-user app data when bundled), so the user
# fills it in once and never has to re-paste exports into every new shell.
CLOUD_CONFIG_FILENAME = "cloud_config.json"


@dataclass(frozen=True)
class CloudConfig:
    """Non-secret identifiers needed to talk to the team's M365 tenant.

    None of these are credentials — they're public-ish references baked into
    a public-client app registration. Sourced from env or a workspace JSON
    file at process start to keep the desktop bundle portable across dev /
    CI / future variants.
    """

    tenant_id: str
    client_id: str
    sharepoint_site_id: str
    sharepoint_drive_id: str

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"


class CloudConfigMissing(RuntimeError):
    """Raised when the cloud bundle is requested but its config is unset."""


def cloud_config_path() -> Path:
    """Location the fallback JSON config lives at."""
    return Path(WORKSPACE_DIR) / CLOUD_CONFIG_FILENAME


def _load_cloud_config_file() -> dict:
    path = cloud_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.exception("cloud_config.json is malformed; ignoring it")
        return {}
    if not isinstance(data, dict):
        logger.warning("cloud_config.json must be a JSON object; ignoring")
        return {}
    return data


def cloud_enabled() -> bool:
    """True if the cloud bundle should be active.

    Env var ``DTM_CLOUD`` wins; a truthy ``enabled`` key in
    ``cloud_config.json`` is the fallback. Either makes cloud mode active.
    """
    raw = os.environ.get("DTM_CLOUD", "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on"}
    return bool(_load_cloud_config_file().get("enabled"))


def load_cloud_config_from_env() -> CloudConfig:
    """Build a ``CloudConfig`` from env vars, falling back to the JSON file.

    Env var names: DTM_AZURE_TENANT_ID, DTM_AZURE_CLIENT_ID,
    DTM_SHAREPOINT_SITE_ID, DTM_SHAREPOINT_DRIVE_ID. Any of those left unset
    are filled from the matching key in ``cloud_config.json`` (``tenant_id``,
    ``client_id``, ``sharepoint_site_id``, ``sharepoint_drive_id``).

    Raises CloudConfigMissing if a field is unresolvable from either source.
    """
    required = {
        "tenant_id": "DTM_AZURE_TENANT_ID",
        "client_id": "DTM_AZURE_CLIENT_ID",
        "sharepoint_site_id": "DTM_SHAREPOINT_SITE_ID",
        "sharepoint_drive_id": "DTM_SHAREPOINT_DRIVE_ID",
    }
    file_values = _load_cloud_config_file()
    values: dict[str, str] = {}
    missing: list[str] = []
    for field_name, env_name in required.items():
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            raw = str(file_values.get(field_name, "")).strip()
        if not raw:
            missing.append(env_name)
        else:
            values[field_name] = raw
    if missing:
        raise CloudConfigMissing(
            "Cloud bundle requested but these env vars / config keys are unset: "
            + ", ".join(sorted(missing))
            + f" (looked in env and {cloud_config_path()})"
        )
    return CloudConfig(**values)
