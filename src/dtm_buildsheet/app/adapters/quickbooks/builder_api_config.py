"""Non-secret desktop configuration for the optional central Builder API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from ....paths import AppPaths


class BuilderApiConfigError(RuntimeError):
    """Raised when central mode is enabled without a complete safe config."""


_ENV = {
    "enabled": "DTM_QB_CENTRAL_ENABLED",
    "base_url": "DTM_BUILDER_API_BASE_URL",
    "tenant_id": "DTM_BUILDER_API_TENANT_ID",
    "audience": "DTM_BUILDER_API_AUDIENCE",
    "delegated_scope": "DTM_BUILDER_API_SCOPE",
}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BuilderApiConfig:
    """Public identifiers only; no Intuit or Entra secret is accepted here."""

    enabled: bool = False
    base_url: str = ""
    tenant_id: str = ""
    audience: str = ""
    delegated_scope: str = ""

    def validate(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name in ("base_url", "tenant_id", "audience", "delegated_scope")
            if not getattr(self, name)
        ]
        if missing:
            raise BuilderApiConfigError("central_qbo_configuration_incomplete")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise BuilderApiConfigError("central_qbo_base_url_must_be_https")
        if parsed.query or parsed.fragment:
            raise BuilderApiConfigError("central_qbo_base_url_must_not_have_query")
        if not self.delegated_scope.startswith("api://"):
            raise BuilderApiConfigError("central_qbo_scope_must_target_builder_api")
        if not self.delegated_scope.startswith(f"api://{self.audience}/"):
            raise BuilderApiConfigError("central_qbo_scope_audience_mismatch")


def load_builder_api_config(paths: AppPaths) -> BuilderApiConfig:
    """Load env-over-file central settings from ``quickbooks_config.json``.

    Environment variables override the matching ``central_qbo`` JSON keys.
    The file is already local-only and excluded from SharePoint mirroring.
    """
    values: dict[str, object] = {}
    path = paths.workspace_dir / "quickbooks_config.json"
    if path.exists():
        try:
            document = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            document = {}
        central = document.get("central_qbo") if isinstance(document, dict) else {}
        if isinstance(central, dict):
            values.update(central)

    for field_name, env_name in _ENV.items():
        if env_name in os.environ:
            values[field_name] = os.environ[env_name]

    return BuilderApiConfig(
        enabled=_truthy(values.get("enabled")),
        base_url=str(values.get("base_url") or "").strip().rstrip("/"),
        tenant_id=str(values.get("tenant_id") or "").strip(),
        audience=str(values.get("audience") or "").strip(),
        delegated_scope=str(values.get("delegated_scope") or "").strip(),
    )
