#!/usr/bin/env python3
"""Plan/apply only missing Company per-vehicle Build Reference Photos folders."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dtm_buildsheet.app.adapters.cloud.config import load_cloud_config_from_env
from dtm_buildsheet.app.adapters.cloud.graph_drive_gateway import GraphDriveGateway
from dtm_buildsheet.app.adapters.cloud.msal_client import MsalClient
from dtm_buildsheet.app.services.company_reference_folder_backfill import (
    apply_reference_folders, plan_reference_folders,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "apply"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--exclude-project", action="append", default=[],
                        help="Exact project ID to leave untouched and record as excluded in the plan")
    args = parser.parse_args()
    if args.phase == "apply" and (not args.report or args.report.resolve() == args.plan.resolve()):
        parser.error("apply requires a separate --report path")
    config = load_cloud_config_from_env()
    token = MsalClient(config).acquire_token(interactive_ok=False)
    company_id = GraphDriveGateway.resolve_drive_id(
        token=token, site_id=config.sharepoint_site_id,
        library_names=(config.company_library_name, config.company_library_internal_name),
    )
    if not company_id:
        raise RuntimeError("Company Files could not be resolved")
    records = GraphDriveGateway(token=token, drive_id=config.sharepoint_drive_id)
    company = GraphDriveGateway(token=token, drive_id=company_id)

    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.replace(path)

    if args.phase == "plan":
        result = plan_reference_folders(
            records, company, root=config.company_vehicle_root,
            exclude_project_ids=args.exclude_project,
            progress=lambda projects, targets: print(f"Reviewed {projects} projects / {targets} units", flush=True)
            if projects and projects % 10 == 0 else None,
        )
        write(args.plan, result)
        print(json.dumps({"projects": len(result["projects"]), "units": len(result["targets"]),
                          "missing": sum(t["action"] == "create" for t in result["targets"]),
                          "blockers": result["blockers"], "plan": str(args.plan)}, indent=2))
        return 1 if result["blockers"] else 0
    result = apply_reference_folders(
        json.loads(args.plan.read_text()), records, company,
        checkpoint=lambda report: write(args.report, report),
    )
    print(json.dumps({k: v for k, v in result.items() if k != "targets"}, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
