#!/usr/bin/env python3
"""Inspect or create the exact DTM operations SharePoint lists.

With no flags this command is fully offline and prints the reviewed manifest.
``--inspect`` performs read-only Graph validation. Creation and every bounded
schema upgrade are separate write modes with exact confirmations.
"""
from __future__ import annotations

import argparse
import json

from dtm_buildsheet.app.adapters.cloud.config import (
    CloudConfigMissing,
    load_cloud_config_from_env,
    save_operations_request_list_id,
    save_operations_list_ids,
)
from dtm_buildsheet.app.adapters.cloud.msal_client import CloudAuthError, MsalClient
from dtm_buildsheet.app.adapters.cloud.operations_list_provisioner import (
    OperationsListProvisioner,
    OperationsListProvisioningError,
)
from dtm_buildsheet.app.adapters.cloud.operations_list_schema import (
    DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION,
    FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION,
    OPERATIONS_LIST_INSPECTION_SCOPES,
    OPERATIONS_LIST_PROVISIONING_SCOPES,
    OPERATIONS_LIST_RUNTIME_SCOPES,
    OPERATIONS_LIST_SPECS,
    OPERATIONS_REQUESTS_LIST,
    PARTS_ORDERED_SCHEMA_CONFIRMATION,
    PROVISION_CONFIRMATION,
    PHONE_REQUESTS_PROVISION_CONFIRMATION,
    RECOVERY_SCHEMA_CONFIRMATION,
)


def manifest_summary() -> dict:
    return {
        "network_access": False,
        "lists": [
            {
                "name": spec.name,
                "custom_column_count": len(spec.columns),
                "indexed_column_count": spec.indexed_column_count,
                "columns": [column.name for column in spec.columns],
            }
            for spec in (*OPERATIONS_LIST_SPECS, OPERATIONS_REQUESTS_LIST)
        ],
        "delegated_graph_permissions": {
            "read_only_inspection": list(OPERATIONS_LIST_INSPECTION_SCOPES),
            "one_time_creation": list(OPERATIONS_LIST_PROVISIONING_SCOPES),
            "normal_operations_runtime": list(OPERATIONS_LIST_RUNTIME_SCOPES),
        },
        "apply_confirmation": PROVISION_CONFIRMATION,
        "phone_requests_provision_confirmation": PHONE_REQUESTS_PROVISION_CONFIRMATION,
        "recovery_schema_confirmation": RECOVERY_SCHEMA_CONFIRMATION,
        "deadline_override_schema_confirmation": DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION,
        "parts_ordered_schema_confirmation": PARTS_ORDERED_SCHEMA_CONFIRMATION,
        "final_finish_delivered_schema_confirmation": (
            FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--inspect",
        action="store_true",
        help="read the configured site and validate any existing operations lists",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="create only missing lists, then validate them",
    )
    mode.add_argument(
        "--inspect-phone-requests",
        action="store_true",
        help="read and validate only the phone status-request list",
    )
    mode.add_argument(
        "--provision-phone-requests",
        action="store_true",
        help="create only the reviewed phone status-request list",
    )
    mode.add_argument(
        "--upgrade-recovery-schema",
        action="store_true",
        help="add only the reviewed recovery columns to both existing lists",
    )
    mode.add_argument(
        "--upgrade-deadline-override-schema",
        action="store_true",
        help="add only the reviewed manual deadline-override column",
    )
    mode.add_argument(
        "--upgrade-parts-ordered-schema",
        action="store_true",
        help="add the reviewed Parts Ordered milestone and choice",
    )
    mode.add_argument(
        "--upgrade-final-finish-delivered-schema",
        action="store_true",
        help="add the reviewed Delivered choice to Final Finish",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="exact confirmation phrase required with either write mode",
    )
    parser.add_argument(
        "--force-account-picker",
        action="store_true",
        help="show the Microsoft account picker instead of reusing the cached account",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not (
        args.inspect or args.apply or args.inspect_phone_requests
        or args.provision_phone_requests or args.upgrade_recovery_schema
        or args.upgrade_deadline_override_schema or args.upgrade_parts_ordered_schema
        or args.upgrade_final_finish_delivered_schema
    ):
        print(json.dumps(manifest_summary(), indent=2))
        return 0
    if args.apply and args.confirm != PROVISION_CONFIRMATION:
        _parser().error(
            f"--apply requires --confirm '{PROVISION_CONFIRMATION}'"
        )
    if (
        args.provision_phone_requests
        and args.confirm != PHONE_REQUESTS_PROVISION_CONFIRMATION
    ):
        _parser().error(
            "--provision-phone-requests requires "
            f"--confirm '{PHONE_REQUESTS_PROVISION_CONFIRMATION}'"
        )
    if (
        args.upgrade_recovery_schema
        and args.confirm != RECOVERY_SCHEMA_CONFIRMATION
    ):
        _parser().error(
            "--upgrade-recovery-schema requires "
            f"--confirm '{RECOVERY_SCHEMA_CONFIRMATION}'"
        )
    if (
        args.upgrade_deadline_override_schema
        and args.confirm != DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION
    ):
        _parser().error(
            "--upgrade-deadline-override-schema requires "
            f"--confirm '{DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION}'"
        )
    if (
        args.upgrade_parts_ordered_schema
        and args.confirm != PARTS_ORDERED_SCHEMA_CONFIRMATION
    ):
        _parser().error(
            "--upgrade-parts-ordered-schema requires "
            f"--confirm '{PARTS_ORDERED_SCHEMA_CONFIRMATION}'"
        )
    if (
        args.upgrade_final_finish_delivered_schema
        and args.confirm != FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION
    ):
        _parser().error(
            "--upgrade-final-finish-delivered-schema requires "
            f"--confirm '{FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION}'"
        )

    try:
        config = load_cloud_config_from_env()
        msal_client = MsalClient(config)
        scopes = (
            OPERATIONS_LIST_PROVISIONING_SCOPES
            if (
                args.apply or args.provision_phone_requests
                or args.upgrade_recovery_schema
                or args.upgrade_deadline_override_schema
                or args.upgrade_parts_ordered_schema
                or args.upgrade_final_finish_delivered_schema
            )
            else OPERATIONS_LIST_INSPECTION_SCOPES
        )
        token = msal_client.acquire_token(
            scopes=scopes,
            interactive_ok=True,
            force_account_picker=args.force_account_picker,
        )
        provisioner = OperationsListProvisioner(
            token=token,
            site_id=config.sharepoint_site_id,
        )
        if args.apply:
            report = provisioner.apply(confirmation=args.confirm)
        elif args.provision_phone_requests:
            report = provisioner.apply_phone_requests_list(
                confirmation=args.confirm,
            )
        elif args.inspect_phone_requests:
            report = provisioner.inspect_phone_requests()
        elif args.upgrade_recovery_schema:
            report = provisioner.apply_recovery_schema_upgrade(
                confirmation=args.confirm,
            )
        elif args.upgrade_deadline_override_schema:
            report = provisioner.apply_deadline_override_schema_upgrade(
                confirmation=args.confirm,
            )
        elif args.upgrade_parts_ordered_schema:
            report = provisioner.apply_parts_ordered_schema_upgrade(
                confirmation=args.confirm,
            )
        elif args.upgrade_final_finish_delivered_schema:
            report = provisioner.apply_final_finish_delivered_schema_upgrade(
                confirmation=args.confirm,
            )
        else:
            report = provisioner.inspect()
    except CloudConfigMissing as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    except (CloudAuthError, OperationsListProvisioningError) as exc:
        print(json.dumps({
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }, indent=2))
        return 1

    config_updated = False
    if (
        args.apply or args.provision_phone_requests or args.upgrade_recovery_schema
        or args.upgrade_deadline_override_schema or args.upgrade_parts_ordered_schema
        or args.upgrade_final_finish_delivered_schema
    ) and report.ready:
        try:
            ids = {item.name: item.list_id for item in report.lists}
            if args.provision_phone_requests:
                save_operations_request_list_id(
                    operations_requests_list_id=ids["DTMOperationsRequests"],
                )
            else:
                save_operations_list_ids(
                    operations_list_id=ids["DTMVehicleOperations"],
                    operations_events_list_id=ids["DTMVehicleEvents"],
                )
            config_updated = True
        except (KeyError, OSError, ValueError) as exc:
            print(json.dumps({
                "ok": False,
                "lists_ready": True,
                "config_updated": False,
                "error_type": type(exc).__name__,
                "error": "Lists validated, but their IDs could not be saved locally",
            }, indent=2))
            return 1

    print(json.dumps({
        "ok": (
            report.ready
            if (
                args.apply or args.upgrade_recovery_schema
                or args.upgrade_deadline_override_schema
                or args.upgrade_parts_ordered_schema
                or args.upgrade_final_finish_delivered_schema
            )
            else not report.has_mismatch
        ),
        "mode": (
            "apply" if args.apply
            else "provision_phone_requests" if args.provision_phone_requests
            else "inspect_phone_requests" if args.inspect_phone_requests
            else "upgrade_recovery_schema" if args.upgrade_recovery_schema
            else "upgrade_deadline_override_schema" if args.upgrade_deadline_override_schema
            else "upgrade_parts_ordered_schema" if args.upgrade_parts_ordered_schema
            else "upgrade_final_finish_delivered_schema"
            if args.upgrade_final_finish_delivered_schema
            else "inspect"
        ),
        "config_updated": config_updated,
        **report.to_dict(),
    }, indent=2))
    write_mode = (
        args.apply or args.provision_phone_requests or args.upgrade_recovery_schema
        or args.upgrade_deadline_override_schema or args.upgrade_parts_ordered_schema
        or args.upgrade_final_finish_delivered_schema
    )
    return 0 if (report.ready if write_mode else not report.has_mismatch) else 1


if __name__ == "__main__":
    raise SystemExit(main())
