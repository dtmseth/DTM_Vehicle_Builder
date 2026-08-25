"""Acquire an Entra token specifically scoped to the Builder API."""

from __future__ import annotations

from typing import Protocol

from ..cloud.config import load_cloud_config_from_env
from ..cloud.msal_client import MsalClient
from .builder_api_config import BuilderApiConfig


class BuilderApiTokenError(RuntimeError):
    pass


class BuilderApiTokenProvider(Protocol):
    def get_token(self) -> str: ...


class EntraBuilderApiTokenProvider:
    """Use the signed-in M365 account, but request the Builder API scope.

    This intentionally never calls the Graph-scoped ``acquire_token`` method;
    a Graph access token has the wrong audience and must not be reused.
    """

    def __init__(self, config: BuilderApiConfig, *, msal_client: MsalClient | None = None) -> None:
        config.validate()
        self._config = config
        self._msal = msal_client

    def get_token(self) -> str:
        try:
            if self._msal is None:
                cloud_config = load_cloud_config_from_env()
                if cloud_config.tenant_id != self._config.tenant_id:
                    raise BuilderApiTokenError("builder_api_tenant_mismatch")
                self._msal = MsalClient(cloud_config)
            return self._msal.acquire_token_for_scopes(
                (self._config.delegated_scope,),
                interactive_ok=False,
            )
        except BuilderApiTokenError:
            raise
        except Exception:  # noqa: BLE001 - MSAL text can contain tenant/account detail
            raise BuilderApiTokenError("builder_api_token_unavailable") from None
