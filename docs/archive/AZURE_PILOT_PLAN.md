# Azure Builder pilot and next-session handoff

**Updated:** 2026-09-10. **Status:** Stage 1 native, ARM64 Linux and emulated AMD64 Linux
export proofs passed; the local runtime gate is complete. At the owner's request Stage 2
local boundary contracts are now implemented/tested; provider integration and full hosted UI are
disabled. Separate hosted image, cleanup/restore safeguards and safe logging now pass locally.
The [resource/cost review](AZURE_RESOURCE_REVIEW.md) is prepared: sole user and alert recipient
seth@dtmfleet.com; Central US proposed; tenant/subscription and deployment authorization unresolved.
No Azure activation/deployment. See [AZURE_PILOT_RESULTS.md](AZURE_PILOT_RESULTS.md)
and [HOSTED_BOUNDARY.md](HOSTED_BOUNDARY.md) for actual outcomes and limits.

## Decision and starting point

Build toward the **full shared HTML Builder** on desktop, iPhone and Android, with M365 sign-in
and existing role permissions. Azure Container Apps Consumption is the preferred trial candidate
if measured costs are acceptable; OVHcloud is the lower-cost fallback. No final hosting purchase
or production cutover has been chosen. This plan owns execution order;
[HOSTING_COMPARISON.md](HOSTING_COMPARISON.md) owns pricing assumptions and provider alternatives.

The owner confirmed **no current subscription and a $200 trial credit offer**. Accept this
without re-checking eligibility or portal status. Seth handles activation; keep progressing local
engineering. [Deployment templates](../packaging/hosted/azure/README.md) now compile locally.
Account IDs become deployment inputs after activation; no trial or deployment has occurred.

Target **$25–35/month after credits** for a small warm app plus separate jobs. This is an illustrative
budget, not a measured forecast or authorized spending cap. A larger warm app was estimated at
$40–50; continuously active 1 vCPU/2 GiB compute plus modest extras at about $85–90. Reassess OVHcloud
if measured Azure cost exceeds roughly $50 without a worthwhile benefit. Preserve source-linked
assumptions in the comparison; do not restart a broad provider search without new evidence.

## Read first and preserve

1. Read root `AGENTS.md`, [GOTCHAS.md](GOTCHAS.md), [CURRENT_STATE.md](CURRENT_STATE.md), then this plan.
2. Inspect Git status. Current branch at handoff is `main`, with substantial tracked and untracked
   Calendar/Operations/phone-foundation work. Preserve the entire working state. A worktree created
   from HEAD alone would omit that work; do not switch to a clean checkout and silently lose it.
3. Production **v3.7.0** remains live. Calendar is implemented locally but unreleased. The pre-pilot
   Calendar gate was **477 focused tests and 4 selected browser flows**. Stage 1 native proof now
   passed **517 tests, 1 skipped and 4 selected browser flows**. After Stage 2 and the AMD64
   operational preparation, the latest gate is **663 tests, 1 skipped and 4/4 browser flows**; see results.
4. Leave user-owned `output/` and `tmp/` untouched. Use a dedicated disposable directory outside
   the checkout for pilot data, builds and measurements. Do not mount personal keychains, synced
   OneDrive folders, the real app workspace, or the entire checkout into a hosted container.
5. Local work starts cloud-off (`DTM_CLOUD=0`) with synthetic fixtures. Also explicitly disable
   provider workers and reject unexpected outbound Graph/QBO calls; a cloud flag alone is not
   proof that every legacy background service is inert.
6. Keep the Power Automate processor **Off**. No Canvas app exists; do not create one. Its existing
   connection's actual permission identity is `seth@dtmfleet.com`, despite a historical Sales label.

Read [ARCHITECTURE.md](ARCHITECTURE.md) and [DEVELOPMENT.md](DEVELOPMENT.md) for local runtime work.
Read [EXTERNAL_CONNECTION_SECURITY.md](EXTERNAL_CONNECTION_SECURITY.md) before hosted auth/storage
design, and [QUICKBOOKS.md](QUICKBOOKS.md) before QBO work. Read feature docs only as their modules
are touched; the phone resource IDs remain in [POWER_APP_PHONE_CLIENT.md](POWER_APP_PHONE_CLIENT.md).

## Stage 1 — local runtime and export proof (first implementation session)

**Goal:** run the existing UI and real document generator inside a disposable Linux container,
without production connections or a GUI window. Do this before activating a trial.

Inspect these seams before proposing the smallest implementation batch:

| Area | Existing implementation / concern |
|---|---|
| Startup and routes | `src/dtm_buildsheet/app/server.py`: `main()` binds localhost, starts background services and opens pywebview/browser. Extract reusable startup without changing desktop defaults. |
| Authentication | `app/adapters/wiring.py`: process-wide `_active_bundle`; `app/services/request_access_service.py` derives permissions from that bundle. A headless launch is not a multi-user authorization solution. |
| Workspace | `src/dtm_buildsheet/paths.py`: dev paths can write bundled source resources. Inject an isolated pilot workspace before loading fixtures. |
| Exports | `app/services/generation_service.py`, `export_service.py`: reuse existing generation, Linux LibreOffice paths and fonts. Inspect arbitrary-path handling and per-job LibreOffice profiles before hosted exposure. |
| Fixtures | `tools/ui_smoke/hermetic.py` and existing focused tests: reuse safe setup patterns, without importing test bypasses into a public runtime. |

Deliver:

- A separate headless entry point with explicit host/port/workspace settings, graceful shutdown,
  minimal health reporting, and no desktop sign-in dialogs or native Open/Show Folder actions.
  For this stage it is a local-only prototype. Select a production HTTP serving arrangement in
  Stage 2; do not expose the desktop `ThreadingHTTPServer` unchanged to the internet.
- A reproducible Linux container build with explicit dependencies, LibreOffice, needed fonts and
  assets, a non-root runtime and a narrowly scoped build context. Exclude real records, credentials,
  Git metadata and user directories. Preserve desktop packaging; separate GUI dependencies only
  as needed. Colima/Docker are now installed in the isolated local `dtm-pilot` profile; use its
  explicit socket and no host-directory mounts. See `packaging/pilot/README.md`.
- Synthetic projects covering a typical build and a dense photo-heavy multi-page export. Load
  Projects and a real draft, edit/save the fixture, generate PPTX/PDF and download the output.
  Render and inspect representative output for missing fonts/images, clipping and pagination.
- Record cold/warm startup, idle memory/CPU, peak export memory, export duration and container
  image size. Test 0.5 vCPU/1 GiB for interactive work and 1 vCPU/2 GiB for exports as experiments,
  increasing only when evidence requires it. Apple Silicon emulation timings are not Azure timings;
  record architecture and confirm intended Azure architecture before claiming a result transfers.
- Document exact local commands and actual outcomes in a short pilot results log created during
  implementation. Mark unsupported capabilities explicitly. Do not call this full hosted parity.

**Exit:** real UI and document output work locally; workspace and credentials remain isolated;
desktop behavior remains intact; focused verification passes. If no container runtime is available,
finish useful code/fixture preparation and record that the Linux measurement gate is still open.

## Stage 2 — shared-user boundary before any public deployment

Local implementation: [HOSTED_BOUNDARY.md](HOSTED_BOUNDARY.md) records the request/session/storage
contracts, route audit, synthetic concurrency/restart proof and review-only infrastructure inputs.
This work proceeded by explicit owner instruction while the Stage 1 Linux gate remained open.
It does not expose legacy routes or connect providers, and does not authorize Stage 3.

**Goal:** two users cannot inherit each other's identity, files, permissions or edits.

- Define a request-scoped user/context seam and an explicit local versus hosted mode. Retain shared
  business services and UI; avoid a parallel mobile application or a wholesale framework rewrite.
- Select Entra tenant-specific authentication (Container Apps built-in auth is the first candidate),
  assigned employees and existing capabilities. Validate trusted identity claims at the server;
  reject client-forged identity headers and bypass paths. Local fake identities must be unavailable
  in a deployed build. Audit every route, including routes currently relying on separate guards.
- Define secure sessions, expiry/sign-out, OAuth state/nonce, CSRF and origin protection, and
  authorized downloads. Native filesystem paths become server-owned artifact IDs; clients cannot
  choose arbitrary server paths. Cache and temporary-file boundaries follow actual ownership.
- Decide how SharePoint access will work: user-delegated access for interactive actions versus
  narrowly scoped application access for independent jobs. Document consent, library scope and
  the role checks needed when a service identity has wider access than a staff member. Do not reuse
  the CI service principal as an all-purpose runtime credential. Keep Company/Shop separation.
- Classify state explicitly: SharePoint authoritative records/documents; durable job/session/audit
  metadata; encrypted credentials; rebuildable caches; disposable exports. Choose the smallest
  durable store that supports conditional writes and worker leases; do not put SQLite or secrets
  on ephemeral storage and assume restarts are safe. Avoid introducing a new database for all
  business records merely to host the app.
- Make jobs durable, bounded and revision-aware. Move periodic polling out of per-user/process
  loops; preserve Calendar's reviewed snapshot, conflict stop and recovery semantics. Single-worker
  limits are a pilot sizing choice, not a substitute for duplicate prevention on retries/redeploys.
- Test concurrent distinct users, stale writes, denied roles, expired sessions, job ownership,
  path traversal and restart behavior with synthetic adapters. Unauthenticated access fails closed.

**Exit:** security/storage decisions are recorded and tested locally; infrastructure configuration
is reviewable. Extend the security documentation explicitly before implementing hosted credential
storage. Production desktop keychain requirements remain in force.

## Stage 3 — activate Azure trial and deploy an isolated pilot

The owner handles activating the confirmed $200 offer. Do not re-check eligibility or walk
through portal tasks unless asked. Once activated and deployment is authorized, use the actual
subscription/tenant IDs and the prepared resource/cost review. Keep secrets out of chat/docs;
do not ask again about the already-selected staff member or alert recipient.

Use [AZURE_RESOURCE_REVIEW.md](AZURE_RESOURCE_REVIEW.md) and the nondeployable
`packaging/hosted/resources.review.json` / `cost-review.json` as the review inputs. The owner
selected only seth@dtmfleet.com for access and notifications; do not ask for the staff list again.
Activation and explicit deployment authorization remain open. The initial boundary-only estimate is
$10.95–13.15/month under the recorded grant/usage assumptions, with a proposed $15 alert budget.

The compiled templates in `packaging/hosted/azure/` prepare the boundary resources below.
Apply them only after activation and authorization:

- Container Apps Consumption, initially one bounded app instance; separate job execution where
  Stage 1 measurements justify it. Use an Azure HTTPS hostname for the pilot.
- Private container image storage, selected durable metadata storage and protected secrets;
  managed identities where supported. Explicit Entra access for pilot staff only.
- Health checks, job/error monitoring, limited log retention, backup/restore and cost reporting.
  Set budget alerts and replica/job limits. Budgets notify; they are not hard spending caps.
- Disposable SharePoint test resources, scoped independently of Company/Shop production, when
  integration testing is ready. Keep local fixtures until those resources are explicitly identified.

Do not configure paid premium networking, dedicated compute or an always-on database by default.
Do not disable authentication to fix a failed health check; expose only minimal non-sensitive
health information. Verify public/unauthorized requests are denied before introducing test records.

**Exit:** authorized users can use the isolated pilot; redeployment/restart preserves intended
state; record actual resource inventory, region, expiry and cleanup steps. No production DNS or
live data changes are part of this stage.

## Stage 4 — SharePoint, jobs and shared QBO sandbox

- Exercise photos, uploads/retries, export publication, Calendar saves and acceptance polling using
  test resources. Verify Sales/Shop/Manager/Admin paths and complete role-appropriate documents.
- QBO: inspect `codex/central-qb-backend-wip` read-only for reusable auth, token rotation and audit
  groundwork. It has initial Items support, not complete Customers/Estimates/attachments. Reconcile
  its older roles; no wholesale merge, live connection or transfer of desktop tokens.
- After the hosted credential contract is implemented, use fresh admin consent to an Intuit sandbox.
  Store credentials only server-side, serialize refresh per company, audit each acting employee,
  and test reconnect/revocation and job retry. Do not request raw tokens from the owner.
- Cover customer refresh, Estimate discovery/linking, creation/attachments and guarded updates.
  Preserve read-only linking, explicit comparisons before writes, real QBO AcceptedDate, protected
  manual dates and truthful Created/Sent/Accepted semantics. Missing remote data must stay unknown.
- Document the desktop transition: existing desktop clients continue per-user QBO until they
  explicitly use the central backend. Website hosting alone does not remove those sign-ins.

**Exit:** sandbox results prove shared authorization, write guards and failure recovery. Production
continues using the existing Netlify broker and per-user keychains until a separate cutover.

## Stage 5 — full mobile parity and cost decision

Mobile UI design has not started. Existing phone workflow requirements are not a visual or
interactive design. Implement the responsive full Builder through the shared UI.

Maintain a visible parity checklist for Projects/creation, vehicle/build editing, parts/placement,
render/export, Estimates, Operations, Calendar/teams, photos and permitted Settings. Test desktop,
iPhone and Android with touch, rotation, long forms, camera/library uploads, interrupted connections,
downloads/sharing, sign-out and installed PWA navigation. A successful shop-only screen is not parity.
Full offline editing is not promised. Unsupported photos must remain visible, not silently disappear.

Use real measured resource activity for representative multi-user work, quiet nights/weekends,
scheduled checks and larger exports. Include storage, registry, logs, backups, transfer, idle time,
retries and extra replicas. Report post-credit cost and identify temporary free-tier discounts.
Test restore and a failed export/job; record recovery time and who receives actionable alerts.

**Exit:** owner reviews usability, explicit remaining gaps and cost against the Azure target.
Continue on Azure, resize, or evaluate the same portable app on OVHcloud based on evidence.

## Stage 6 — separate production rollout

Prepare exact production scope, role/consent mapping, backup and rollback, desktop compatibility,
job ownership during overlap, and prevention of duplicate QBO/Calendar actions. Only after review
connect the live QBO company and SharePoint resources, then configure the proposed
`builder.dtmfleet.com` and Employee Login website link. GoDaddy can remain the domain registrar.
Start with a small staff pilot, then expand to all 11 shop users. Track authorization for deployment,
production writes, DNS, pay-as-you-go upgrade and any release/push; none occurred in planning.
If the trial is abandoned, stop schedules, preserve approved results and remove only pilot resources.

## Verification and handoff discipline

Use `.venv/bin/python tools/verify.py changed` after each meaningful implementation batch; report
compact counts. Add focused tests for new boundaries and extend the selector for new areas as
needed. Do not run all tests/flows in the inner loop or alter golden masters to pass. A release gate
belongs at release/merge or a genuinely cross-cutting contract checkpoint, with its reason stated.

After each stage, update CURRENT_STATE and the pilot results log with commands, measured outcomes,
remaining risks, resource/trial status and the exact next batch. Keep feature requirements in
[POST_MEETING_FEATURE_PLAN.md](POST_MEETING_FEATURE_PLAN.md); they remain accepted backlog and should
share these new runtime seams. Calendar's 60-day promise and existing permissions remain intact.

## Paste into the next session

> Continue in `/Users/skreev/Desktop/DTM_BuildSheet_POC_v7`. Read AGENTS.md, docs/GOTCHAS.md,
> docs/CURRENT_STATE.md and docs/AZURE_PILOT_PLAN.md. Inspect and preserve all existing uncommitted
> work, including untracked Calendar files; leave output/ and tmp/ untouched. Read
> docs/AZURE_PILOT_RESULTS.md, docs/HOSTED_BOUNDARY.md and packaging/pilot/README.md. Stage 2's
> local boundary contracts are implemented, with real providers and legacy hosted routes closed.
> Stage 1's local Linux/AMD64 proof and Stage 2's separate hosted image, cleanup/restore safeguards
> and safe telemetry are complete locally. Read HOSTED_OPERATIONS.md and AZURE_RESOURCE_REVIEW.md.
> Resource/cost inputs are prepared; only seth@dtmfleet.com will have pilot access/alerts. The owner confirmed no current subscription and a $200 trial offer; do not re-check it.
> Read packaging/hosted/azure/README.md for the compiled deployment files. Seth handles activation;
> use the resulting account IDs for an authorized deployment. No deployment is authorized yet. Use the
> isolated Colima profile for further image checks. Use tools/verify.py changed after
> a meaningful implementation batch. Azure is preferred if affordable, but
> do not activate the trial, deploy, touch production data, or enable flows in this local stage.
> Record what actually works, resource measurements and the next step. Keep questions concise.
