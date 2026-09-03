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

    Export-target fields (``exports_*``) describe the legacy company PDF
    mirror. Shop publication uses its own explicitly enabled ``shop_*`` target
    so installing an updated app cannot create or change Shop folders before
    the migration dry run and cutover are approved.
    """

    tenant_id: str
    client_id: str
    sharepoint_site_id: str
    sharepoint_drive_id: str
    # Export-target library lookup. The two names are tried in order
    # against /sites/{site_id}/drives.name — give the display name first;
    # the internal-name fallback covers libraries that were renamed in the
    # SharePoint UI but kept their backend name (SharePoint doesn't always
    # update the latter).
    exports_library_name: str = ""
    exports_library_internal_name: str = ""
    exports_base_folder: str = ""  # e.g. "Vehicle Builder Projects" inside the library
    company_library_name: str = ""
    company_library_internal_name: str = ""
    company_vehicle_root: str = "Vehicle Project Database"
    company_folder_provisioning_enabled: bool = False
    company_vehicle_folders_enabled: bool = False
    shop_folder_provisioning_enabled: bool = False
    shop_publication_enabled: bool = False
    shop_library_name: str = ""
    shop_library_internal_name: str = ""
    shop_build_photos_root: str = "Shop Project Database"

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @property
    def exports_enabled(self) -> bool:
        return bool(self.exports_library_name or self.exports_library_internal_name)

    @property
    def shop_target_configured(self) -> bool:
        return bool(
            self.shop_publication_enabled
            and (self.shop_library_name or self.shop_library_internal_name)
        )

    @property
    def company_target_configured(self) -> bool:
        return bool(
            self.company_vehicle_folders_enabled
            and (
                self.company_library_name
                or self.company_library_internal_name
                or self.exports_library_name
                or self.exports_library_internal_name
            )
        )

    @property
    def company_provisioning_target_configured(self) -> bool:
        return bool(
            self.company_folder_provisioning_enabled
            and (
                self.company_library_name
                or self.company_library_internal_name
                or self.exports_library_name
                or self.exports_library_internal_name
            )
        )

    @property
    def shop_provisioning_target_configured(self) -> bool:
        return bool(
            self.shop_folder_provisioning_enabled
            and (self.shop_library_name or self.shop_library_internal_name)
        )


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

    # Optional export-target fields. Absence just means auto-upload is off
    # for this install — no CloudConfigMissing.
    optional = {
        "exports_library_name": "DTM_EXPORTS_LIBRARY_NAME",
        "exports_library_internal_name": "DTM_EXPORTS_LIBRARY_INTERNAL_NAME",
        "exports_base_folder": "DTM_EXPORTS_BASE_FOLDER",
        "company_library_name": "DTM_COMPANY_LIBRARY_NAME",
        "company_library_internal_name": "DTM_COMPANY_LIBRARY_INTERNAL_NAME",
        "company_vehicle_root": "DTM_COMPANY_VEHICLE_ROOT",
        "shop_library_name": "DTM_SHOP_LIBRARY_NAME",
        "shop_library_internal_name": "DTM_SHOP_LIBRARY_INTERNAL_NAME",
        "shop_build_photos_root": "DTM_SHOP_BUILD_PHOTOS_ROOT",
    }
    for field_name, env_name in optional.items():
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            raw = str(file_values.get(field_name, "")).strip()
        if raw:
            values[field_name] = raw

    raw_shop_enabled = os.environ.get("DTM_SHOP_PUBLICATION_ENABLED", "").strip()
    if not raw_shop_enabled:
        raw_shop_enabled = str(file_values.get("shop_publication_enabled", "")).strip()
    if raw_shop_enabled:
        values["shop_publication_enabled"] = raw_shop_enabled.casefold() in {
            "1", "true", "yes", "on",
        }

    raw_company_enabled = os.environ.get("DTM_COMPANY_VEHICLE_FOLDERS_ENABLED", "").strip()
    if not raw_company_enabled:
        raw_company_enabled = str(file_values.get("company_vehicle_folders_enabled", "")).strip()
    if raw_company_enabled:
        values["company_vehicle_folders_enabled"] = raw_company_enabled.casefold() in {
            "1", "true", "yes", "on",
        }

    for field_name, env_name in (
        ("company_folder_provisioning_enabled", "DTM_COMPANY_FOLDER_PROVISIONING_ENABLED"),
        ("shop_folder_provisioning_enabled", "DTM_SHOP_FOLDER_PROVISIONING_ENABLED"),
    ):
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            raw = str(file_values.get(field_name, "")).strip()
        if raw:
            values[field_name] = raw.casefold() in {"1", "true", "yes", "on"}

    return CloudConfig(**values)
