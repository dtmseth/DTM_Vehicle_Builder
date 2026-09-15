"""Future production factory. No cloud calls occur merely by importing it.

No fake-user switch, filesystem business-record fallback or background loops.
Do not invoke until the Stage 3 configuration and costs have been approved.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def create_app():
    from azure.data.tables import TableServiceClient
    from azure.identity import ManagedIdentityCredential
    from .application import Application
    from .artifacts import Artifacts
    from .auth import EntraTokens
    from .jobs import Jobs
    from .metadata import AzureTableMetadata

    if os.environ.get("DTM_RUNTIME_MODE") != "hosted":
        raise RuntimeError("Explicit hosted configuration required")
    if os.environ.get("DTM_CLOUD") != "0" or os.environ.get("DTM_LOCAL_PILOT"):
        raise RuntimeError("Desktop cloud bootstrap and local pilot must be disabled")
    account, table = os.environ["DTM_METADATA_ACCOUNT"], os.environ["DTM_METADATA_TABLE"]
    if not re.fullmatch(r"[a-z0-9]{3,24}", account) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{2,62}", table):
        raise ValueError("Invalid metadata destination")
    # Managed identity only: never DefaultAzureCredential's developer/CLI fallback.
    credential = ManagedIdentityCredential(client_id=os.environ["DTM_METADATA_IDENTITY_CLIENT_ID"])
    client = TableServiceClient(f"https://{account}.table.core.windows.net", credential=credential)
    store = AzureTableMetadata(client.get_table_client(table))
    root = Path(os.environ["DTM_ARTIFACT_ROOT"])
    if not root.is_absolute():
        raise ValueError("Absolute disposable artifact root required")
    return Application(
        mode="hosted", origin=os.environ["DTM_HOSTED_ORIGIN"],
        tokens=EntraTokens(os.environ["DTM_HOSTED_TENANT_ID"], os.environ["DTM_HOSTED_CLIENT_ID"]),
        store=store, artifacts=Artifacts(store, root), jobs=Jobs(store),
    )


def main():
    import argparse
    from waitress import serve
    from .telemetry import configure_logging, lifecycle_event
    parser = argparse.ArgumentParser(description="Explicit hosted boundary; no desktop/provider workers")
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    args = parser.parse_args()
    configure_logging()
    try:
        app = create_app()
        lifecycle_event("starting")
        serve(app, host=args.host, port=8080, threads=4,
              max_request_body_size=65536, max_request_header_size=32768,
              channel_timeout=30, connection_limit=32, clear_untrusted_proxy_headers=True,
              expose_tracebacks=False)
    except Exception:
        lifecycle_event("startup_failed")
        raise SystemExit(1) from None
    finally:
        lifecycle_event("stopped")


if __name__ == "__main__":
    main()
