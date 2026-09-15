# Isolated pilot deployment files

Prepared locally; **nothing deployed**. Seth confirmed no current Azure subscription and a
$200 trial offer. Accept that information; do not spend another session checking eligibility.
The owner handles trial activation. These files cover the authenticated boundary, not full UI.

## What is ready

- `foundation.bicep`: Consumption environment, Basic registry, managed identity, table-scoped
  metadata permission, separate private token/backup accounts and 30-day Log Analytics.
- `app.bicep`: verified image digest input, 0.5 CPU / 1 GiB, scale 0–1, cloud-off environment,
  health probes, single-employee Entra authentication and protected secret parameters.
  Public ingress defaults **off**, so app creation precedes authentication without public exposure.
- `monitoring.bicep`: Seth's email action group, two log alerts and $15 budget notifications.
  Alert rules and budget default off until their service/schema prerequisites are ready.

Offline check (does not use Azure credentials, make API requests or create output files):

```bash
.venv/bin/python tools/pilot/verify_azure_templates.py --bicep /path/to/bicep
```

Verified with Bicep **0.47.16**. The compiler was downloaded outside the checkout and its SHA-256
matched the official release asset: `68046a084c88503cf6bd11dacf2a1c4ffcb7e3ac9c6b310d295e024af21bbea4`
(macOS ARM64). No Azure CLI or subscription is required to compile.

## Execution order after activation and deployment authorization

1. Use the new trial's subscription/tenant IDs, create only `rg-dtm-builder-pilot-cus`, and run
   Azure validation/what-if before applying `foundation.bicep` in **Incremental** mode. If global
   names collide, override the name parameters consistently across all three templates.
   Keep the default Consumption profile and Central US region.
2. Publish the tested AMD64 boundary image to this registry, sign and verify the registry manifest,
   then use its digest. The local Docker image ID is not a registry manifest digest. Registry
   `AcrPull` uses ordinary registry RBAC; ABAC mode would invalidate that role. Allow assignment
   propagation before the app's first pull. No automated publication/signing is included here.
3. Create a new single-tenant pilot registration and enterprise application, require assignment,
   define `BuilderEditor` with `allowedMemberTypes: ["User"]`, assign only Seth's actual object ID,
   and enable ID tokens. Use the public callback
   `https://ca-dtm-builder-pilot-cus.<environment-default-domain>/.auth/login/aad/callback`.
   Do not request business Graph permissions or alter the existing desktop registration.
4. Create the Entra secret and token-container SAS via protected entry. Supply `entraClientSecret`
   and `tokenStoreSasUrl` as **secure deployment parameters**. Prefer the portal's secure input or
   protected deployment tooling; never put values in shell arguments/history, source files,
   generated parameter files, output logs or chat. The token account alone permits Shared Key
   for the container-scoped read/write/delete service SAS; metadata/backup accounts do not.
5. Apply `app.bicep` with `externalIngress=false`. Read back successful auth configuration and
   the individual assignment before reapplying with `externalIngress=true`. The latter updates
   origin/probe Host together. Confirm the reported FQDN matches the generated origin. Perform
   negative auth/header/nonce and real Table ETag tests before adding synthetic records. Do not
   assume the local no-network proof verified Azure. Liveness does not prove Table readiness.
6. Apply monitoring with actual monthly budget start/end dates (start on the first day of the
   current month). Enable budget when Cost Management is available; enable log alerts only after
   checking populated tables, `_BilledSize`/`_IsBillable` and query results. Test notification
   receipt. No alerts are sent by compiling these templates.

The app container still inherits its image's UID 10001. Container Apps does not expose all Docker
proof flags in this resource schema: read-only root, dropped capabilities, process/memory-backed
`/tmp` limits are not claimed by these templates. Verify platform isolation before use; the app
has no provider integration or real-data mounts. Do not quietly add privileged networking or
paid dedicated services to approximate local Docker flags.

Backup lifecycle expires live blobs after 14 days; seven-day soft delete can retain recoverable
copies longer. Runtime gets no backup role. Operator grants, quiesced snapshots, cleanup schedules,
credential-expiry reminders, platform health notifications and recovery drills remain required
before unattended use. These templates do not create an Entra app or scheduled workers.

References: [app resource schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/containerapps),
[environment schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/managedenvironments),
[alert schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.insights/scheduledqueryrules),
[registry RBAC modes](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-rbac-abac-repository-permissions).
