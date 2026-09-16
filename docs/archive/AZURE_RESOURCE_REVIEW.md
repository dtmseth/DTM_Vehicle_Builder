# Azure pilot resource and cost review

**Prepared 2026-09-10; review only.** The owner selected **seth@dtmfleet.com** as the sole
pilot user and cost/error alert recipient. Central US is the proposed region. The owner subsequently confirmed no current subscription and a $200 trial offer; do not
re-check the offer. Tenant/object IDs, quota and resource-name availability are deployment inputs.
No trial, resources, emails, deployment, consent or production changes occurred.

## Proposed first deployment

Deploy the existing authenticated **boundary only**: sign-in, session and metadata safeguards.
It does not contain the Builder UI, mobile design, export workers or SharePoint/QBO integration.
Its purpose is to verify real platform authentication, scoped Table permissions and restart
behavior before adding those features. The Stage 1 UI server must remain local.

Use Container Apps Consumption, **0.5 vCPU / 1 GiB**, minimum zero and maximum one replica,
single active revision and HTTP concurrency target 10. This target is a scaling setting, not
a rate limit. Cold starts and disposable artifact loss on replacement are accepted for this
pilot. The local 0.5 CPU / 512 MiB proof is not an Azure resource combination; Azure requires
the corresponding [Consumption CPU/memory pair](https://learn.microsoft.com/en-us/azure/container-apps/containers).

| Resource | Proposed name / scope | Purpose |
|---|---|---|
| Resource group | `rg-dtm-builder-pilot-cus` | All pilot Azure resources and cost scope |
| Environment / app | `cae-dtm-builder-pilot-cus` / `ca-dtm-builder-pilot-cus` | Consumption profile, Azure HTTPS hostname, port 8080 |
| Registry | `acrdtmpilotcus0910`, Basic | Private image, admin credentials disabled; local builds |
| Runtime identity | `id-dtm-builder-pilot-cus` | Registry pull and Table access only |
| Metadata account / table | `stdtmmetacus0910` / `DtmPilotMetadata` | Standard LRS; default service-scoped encryption; managed identity |
| Auth token account / container | `stdtmtokencus0910` / `auth-tokens` | Separate private Hot LRS Blob container for platform tokens |
| Backup account / container | `stdtmbackupcus0910` / `job-snapshots` | Private Hot LRS logical job snapshots; 14-day retention |
| Logs | `law-dtm-builder-pilot-cus`, PAYG Analytics Logs | 30-day retention, initial 1 GB/month allowance |
| Alerts / budget | `ag-dtm-builder-pilot` / `budget-dtm-builder-pilot` | Email Seth; proposed $15/month budget |
| New Entra app | `DTM Builder Isolated Pilot` | Single tenant, individual assignment required |

Names are candidates, not reserved names. The exact review inputs are in
[resources.review.json](../packaging/hosted/resources.review.json); it deliberately has null
tenant/subscription/object IDs and is **not an ARM deployment template**. No custom domain,
dedicated compute, premium networking, paid database, cloud build tasks or worker is proposed.
Consumption environments can incur management charges when premium features such as private
endpoints/planned maintenance are selected; they are excluded from this estimate.
See [Container Apps billing](https://learn.microsoft.com/en-us/azure/container-apps/billing).

## Access, credentials and ownership

Resolve Seth's actual company-tenant object ID; an email address alone is not an authorization
claim. Create a separate pilot app registration and enterprise application, require assignment,
and allow only that object ID. Propose the existing `BuilderEditor` app role for the initial
session/boundary exercise; this grants no Azure administrator role. Test other app roles later
by reviewed reassignment. Do not modify the production desktop registration or import its tokens.

Set the exact HTTPS origin/audience after Azure assigns the hostname. Register only that
app's `/.auth/login/aad/callback`. Preserve the prepared
[auth configuration](../packaging/hosted/auth-config.review.json): signed tenant ID token,
platform nonce/state, 30-minute session, HTTPS, 401 for unauthenticated APIs, only `/healthz`
anonymous. Real signed-token injection, claim roles, header stripping and bypass denial still
need the isolated deployment tests. Provider routes continue to fail closed.

The runtime identity receives `AcrPull` at this registry and `Storage Table Data Contributor`
at this table only. Metadata/backup accounts disable Shared Key access. No CI identity,
production SharePoint, Graph business permissions or QBO credentials are used. Storage endpoints
are publicly reachable with authentication; private containers do not imply private networking.

The platform token store has its own encrypted private container and expiring read/write/delete
SAS, referenced through the protected Container Apps secret `pilot-token-store-sas`. The Entra
client secret uses `pilot-entra-client-secret`. Values never enter Git, review JSON, command logs
or chat. Proposed SAS/client-secret lifetimes are 30/90 days, subject to tenant policy; Seth is
the proposed rotation operator, with checks seven days and one day before expiry. The platform's
[token-store procedure](https://learn.microsoft.com/en-us/azure/container-apps/token-store) requires
a private Blob container and protected SAS reference. Exact SAS signing/expiry policy must be
settled at provisioning; no renewable credential was generated here.

Seth is also the proposed maintenance/recovery operator. The app cannot read backup blobs.
Grant the operator only the pilot data scopes needed for a reviewed backup/restore; do not infer
Azure subscription ownership from app access. Follow [HOSTED_OPERATIONS.md](HOSTED_OPERATIONS.md)
for dry-run expiry cleanup, quiesced daily/pre-change snapshots and fenced recovery. Scheduling,
backup protection, secret-expiry notifications and permissions are still deployment tasks.

## Monthly estimate, before trial credits

[cost-review.json](../packaging/hosted/cost-review.json) preserves selected Central US USD retail
meters, IDs, effective dates, quantities and formulas from the public
[Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices),
retrieved 2026-09-10. Re-query the recorded filters and follow pagination before provisioning;
compare with the actual subscription calculator. These are usage assumptions, not measured bills.

| First pilot: 730-hour month, 40 active app hours, 100,000 requests | USD |
|---|---:|
| App compute, before shared monthly grants | 2.16 |
| HTTP requests, before grants | 0.04 |
| Basic registry, $0.1666/day | 5.07 |
| 1 GB Table + 100,000 operations; 1 GB combined Blob + 10,000 reads/writes each | 0.12 |
| 1 GB Analytics Logs, conservatively ignoring its free allowance | 2.76 |
| One 5-minute and one 15-minute log alert, no dimension splitting | 2.00 |
| Transfer/notification/variation allowance, not a quoted tariff | 1.00 |
| **Total before free grants or credits** | **13.15** |
| **With full Container Apps compute/request grants available** | **10.95** |

Plan approximately **$11–15/month** for this limited pilot. The proposed $15 budget has little
room for unexpectedly active replicas or noisy logs. No trial credit, tax, paid support or
licensing change is included. Registry storage stays within Basic's allowance. The log estimate
uses the paid $2.76/GB tier, not the API's zero-price first tier or legacy $2.30 pricing.
[Monitor pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/) explains query-frequency
charges, extra alert dimensions, notification allowances and included retention.

The same worksheet illustrates the later cost decision; these are **not deployed configurations**:

| Later workload | With full compute/request grants* | Without grants |
|---|---:|---:|
| 0.5 CPU / 1 GiB warm: 176 active + 554 eligible idle hours; 20 worker hours at 1 CPU / 2 GiB | $26.19 | $31.63 |
| 0.5 CPU / 1 GiB continuously active | $44.97 | $50.41 |
| 1 CPU / 2 GiB continuously active | $84.39 | $89.83 |

*Grants are shared per subscription. The warm-row discount assumes grants offset active usage;
actual allocation across active/idle usage can yield a smaller discount. Idle pricing requires
minimum replicas above zero, no requests, CPU below 0.01 and received traffic below 1,000 B/s.
Min-zero replicas are charged active while running. Polling or checks can prevent scale-to-zero.
All rows reuse the pilot's small storage/log/traffic assumptions; growing features can exceed them.
The earlier $25–35 target remains plausible only under the warm/idle assumptions, not guaranteed.

## Monitoring and stop/review points

Propose actual-cost notifications at **$7.50, $12 and $15**, plus forecast above $15, sent only to
Seth. Budgets notify; they do not stop spending. Cost data/alerts are delayed, and a new subscription
can take up to 48 hours to expose Cost Management. Until available, review usage manually during
each pilot session. See [budget behavior and prerequisites](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).

Use two dimension-free log rules: (1) every five minutes, at least five 5xx responses and at least
5% errors in the last five minutes; (2) every 15 minutes, startup failure or over 0.1 GB pilot log
ingestion in 24 hours. Confirm actual Log Analytics tables and billable ingestion fields before
installing either query. Add platform service/resource-health notifications where supported and
verify replica/probe failures explicitly. Zero replicas is normal for this plan, not an outage.
Aggregate KQL is prepared; no alert or log destination has been installed or delivery tested.

Review after 30 days and seven days before the actual trial expiry. At a cost/credit warning,
investigate usage and stop the pilot if needed; do not auto-upgrade to pay-as-you-go. Removing
the app alone leaves registry, storage and logs billable. On abandonment, preserve only approved
evidence, then remove this pilot resource group and separately its Entra registration/assignments
after checking ownership. No production resource is part of that cleanup scope.

## Next action and remaining gates

The review and [compiled deployment files](../packaging/hosted/azure/README.md) are ready.
Seth handles trial activation; accept his confirmed $200 offer without another account check.
Actual subscription/tenant/object IDs become inputs when deployment is authorized.
Do not repeat the already answered staff/recipient question or ask for passwords/tokens.

After authorization, apply the prepared provisioning sequence and verify the image registry
manifest digest/signature (the local Docker image ID is not that digest), platform-supported
container restrictions, credentials, scopes, probes, budgets and alerts. Test negative auth and
real Table conditional writes before introducing synthetic records. Add providers/full shared UI
in the subsequent stages; no mobile parity or real Azure performance is claimed by this review.
