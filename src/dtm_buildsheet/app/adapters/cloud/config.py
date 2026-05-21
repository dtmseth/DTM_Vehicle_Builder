from __future__ import annotations

import os
from dataclasses import dataclass


# Microsoft Graph scopes for delegated SharePoint access.
#
# `Files.ReadWrite.All` covers OneDrive + every SharePoint file the user has
# access to. Without the `.All` suffix the scope is limited to the user's
# personal OneDrive — writes to SharePoint return 403. `Sites.Read.All`
# stays in the request so site metadata lookups (drive lists, item children)
# work even when the per-item ACL would block a file read.
GRAPH_SCOPES: tuple[str, ...] = ("Files.ReadWrite.All", "Sites.Read.All")

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"


@dataclass(frozen=True)
class CloudConfig:
    """Non-secret identifiers needed to talk to the team's M365 tenant.

    None of these are credentials — they're public-ish references baked into
    a public-client app registration. Sourced from env at process start to
    keep the desktop bundle portable across dev / CI / future variants.
    """

    tenant_id: str
    client_id: str
    sharepoint_site_id: str
    sharepoint_drive_id: str

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"


class CloudConfigMissing(RuntimeError):
    """Raised when the cloud bundle is requested but its env config is unset."""


def load_cloud_config_from_env() -> CloudConfig:
    """Read the four required identifiers from environment variables.

    Variables: DTM_AZURE_TENANT_ID, DTM_AZURE_CLIENT_ID,
    DTM_SHAREPOINT_SITE_ID, DTM_SHAREPOINT_DRIVE_ID.

    Raises CloudConfigMissing if any are absent; callers in the wiring layer
    are expected to fall back to the local bundle in that case.
    """
    required = {
        "tenant_id": "DTM_AZURE_TENANT_ID",
        "client_id": "DTM_AZURE_CLIENT_ID",
        "sharepoint_site_id": "DTM_SHAREPOINT_SITE_ID",
        "sharepoint_drive_id": "DTM_SHAREPOINT_DRIVE_ID",
    }
    values: dict[str, str] = {}
    missing: list[str] = []
    for field_name, env_name in required.items():
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            missing.append(env_name)
        else:
            values[field_name] = raw
    if missing:
        raise CloudConfigMissing(
            "Cloud bundle requested but these env vars are unset: "
            + ", ".join(sorted(missing))
        )
    return CloudConfig(**values)
