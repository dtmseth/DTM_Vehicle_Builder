# Hosted Architecture

**Status:** local security/storage boundary and container preparation. No Azure resources,
trial, deployment, live backup, or production access have been created by this work.
Provider integration, the full hosted Builder UI, and central Calendar/QBO polling remain
disabled. Local checks do not establish deployment readiness.

This document owns request security, state/job/artifact ownership, container operation,
cleanup, recovery, and safe telemetry. Existing [Operations capabilities](OPERATIONS.md#roles-and-capabilities)
remain the role policy; [EXTERNAL_CONNECTION_SECURITY.md](EXTERNAL_CONNECTION_SECURITY.md)
owns the credential contract.

## Request identity and serving

`app/hosted/application.py` is a bounded WSGI surface, served by Waitress in a loopback integration
test. It does not adapt the desktop HTTP handler by forwarding arbitrary requests. Accepted
requests bind an immutable `RequestContext` using `ContextVar`; `get_active_bundle()` resolves
that context first. Hosted processes cannot construct, set or fall back to the desktop's global
local-admin bundle, including worker threads without an explicit context. Desktop selection and
the Stage 1 UI remain unchanged. Existing Operations capabilities are the only role policy.

Entra verification accepts RS256 ID tokens only from the configured tenant/issuer/client, with
required timestamps, tenant/object IDs and known roles. JWKS lookup has a fixed Microsoft tenant
URL and a bounded cache/timeout; token-supplied key URLs and unsigned principal headers are ignored.
The app checks a current signed token on every request, plus a revocable owner-bound session.
Platform authentication owns OAuth state/nonce and its provider cookies. Local tests do not prove
the platform flow or immediate Entra role revocation: token claims may remain valid until expiry.
The application session lasts at most 30 minutes or the ID token's earlier expiry. Jobs require
an independent current authorization callback before every write; cached roles cannot authorize
unattended work. See [the credential contract](EXTERNAL_CONNECTION_SECURITY.md).

Origin is configured, never derived from client proxy headers. Mutations require exact Origin,
JSON, a bounded body and the session's CSRF token. Bootstrap also requires the verified identity
and exact Origin, rotates any previous session, and never accepts a client-selected cookie.
Sign-out revokes the app session then returns the fixed platform logout path. Responses contain
no tokens, exception details or paths; all are no-store. Only minimal `/healthz` is anonymous.

## Route audit / deliberate exposure

| Surface | Hosted decision |
|---|---|
| `GET /healthz` | Anonymous minimal liveness, no provider status or records |
| `POST/GET /api/hosted/session`, `POST /api/hosted/logout` | Verified tenant identity, owner-bound session; mutation origin/CSRF rules above |
| `GET/PUT /api/hosted/documents/{id}` | Existing project view/edit capabilities, adapter resource ACL/schema checks, exact revision for writes |
| `POST /api/hosted/jobs`, `GET /api/hosted/jobs/{id}` | Kind-specific capability; server-reviewed snapshot; opaque idempotency key; only owner reads progress |
| `GET /api/hosted/artifacts/{id}` | Project view capability, same tenant/user owner, expiry/integrity checks; no client filename/path |
| Desktop root/UI/assets/status/config/template routes | Closed in this boundary; Stage 1 still serves the existing UI locally |
| Projects/drafts/builds/presets/agencies/reps/parts/preview/validation/generation/photos | All legacy routes closed until each provider/ownership integration is covered |
| Operations/Calendar/cloud/QuickBooks/update and callbacks | Closed even where desktop has its own route guard; no exemption inherits a desktop identity |
| Native Open, Show Folder, Pick Folder, parse/export/delete-old | Closed; no arbitrary-path adapter or native action |
| Other paths/methods, encoded traversal, future unclassified routes | Fail closed before any desktop dispatch |

The new document endpoint is an integration port, **not a replacement record schema**. Local
tests supply a notes-only synthetic document with an explicit staff ACL. Production has no
document adapter and returns `503 provider_not_enabled`; no metadata fallback stores real
projects. Connecting the existing services requires provider ETags, ACLs, validation/finalization
rules and safe cache paths. Reuse the existing UI/services during that integration; do not wire
all legacy routes through this boundary in one pass.

## State ownership and durability

| State | Owner / persistence / restart behavior |
|---|---|
| Projects, drafts, Calendar plans, Operations rows/events, documents | SharePoint authority; delegated interactive access and provider-level ETags |
| Sessions | Azure Tables; cookie/CSRF digests, owner and absolute expiry; no raw tokens |
| Jobs and their transition audit | Azure Tables; atomic bounded queue entity with exact ETags |
| Entra platform token store | Separate private Blob container/protected secret, platform-managed; not app metadata |
| Future QBO credentials | Separate reviewed protected server store; not implemented or connected |
| Caches | Rebuildable, tenant/user/resource/revision keyed; no shared desktop cache is exposed |
| Generated artifacts | Disposable private directory, random filenames, durable owner/expiry/hash registry; missing bytes report 410 |
| Local proof metadata | SQLite in an external temporary directory, test-only and excluded from deployed inputs |

Azure Tables uses create-only inserts and `IfNotModified`/exact ETags for replacements, with a
60,000-byte UTF-16 payload ceiling. No blind upsert or wildcard write exists. A dedicated managed
identity is selected explicitly; there is no developer credential-chain fallback. SDK preconditions
are tested against a fake SDK client; real Azure consistency/permissions/restore are Stage 3 gates.
Resource IDs are server-selected opaque references. SharePoint Company and Shop destinations
must remain separately configured and role checked, even if an independent job identity can
reach both. CI's service principal is never a runtime credential.

## Jobs, Calendar and polling

The web boundary only enqueues and reads progress. `Jobs.claim/advance` is a separate worker port,
with one active tenant lease enforced by CAS across replicas. Each job retains owner, immutable
kind/resource/revision/snapshot intent, a 15-minute maximum authorization deadline, step count
and transition audit. Idempotency retries with the same intent return the original job; changing
intent with the same key conflicts. Workers get a deterministic event ID for each step and must
check both the reviewed snapshot and per-record provider revision at the write itself.

The worker rechecks authorization before each bounded step. A conflict/revocation/failure stops
the job. A worker disappearing after a remote write leaves an uncertain outcome: an expired
lease becomes `interrupted` and is never automatically replayed. The next reviewed operation
must reconcile provider events first. Existing desktop Calendar's reviewed-snapshot and recovery
behavior is unchanged. This port is ready for its provider adapter; it does **not** start the
desktop Calendar thread, five-minute QBO poller or per-user SharePoint loops in a hosted process.
Central periodic polling and external workers remain disabled until Stage 4.

The proof queue holds at most **four active jobs per tenant**, with at most **64 steps/job** and
120-second leases. Capacity exhaustion is explicit (429). Terminal jobs copy into immutable
archive rows before removal from the active queue; a crash between those writes retains the
retry key. Progress reads and idempotency checks include the archive. Archive rows are retained
for the pilot's lifetime; it never evicts an idempotency key. Bounded session/artifact cleanup and
fenced logical job restore are implemented/tested locally; see [expiry cleanup](#expiry-cleanup) and [job recovery](#job-recovery-snapshot-and-restore).
Schedules, backup protection and worker timeout sizing still require deployment review. Provider writes
must be idempotent by event ID and use exact revision checks; a lease alone is insufficient.

Artifacts accept generated bytes only through the worker API, use random IDs and fixed PDF/PPTX
extensions, enforce owner/tenant/one-hour expiry and a 128 MiB cap, reject symlinks and verify size
and SHA-256 before download. The registry does not make local bytes durable across replicas.
Before multi-replica exports, add private object storage using the same ownership contract.

## Image and startup

`tools/pilot/hosted_build_context.py` stages current Python code, package metadata and the
separate hosted dependency lock in a new external directory. It excludes desktop workspace
records, all resources/UI assets, Stage 1 headless/fixture modules, test adapters, credentials
and Git metadata. Desktop dependencies remain in the common package contract; they are not
invoked. There is no LibreOffice or export worker in this boundary image. Add a separate worker
image when actual provider/export integration is implemented.

```bash
export DOCKER_CONFIG=/private/tmp/dtm-pilot-docker-config
export DOCKER_HOST=unix:///Users/skreev/.colima/dtm-pilot/docker.sock
.venv/bin/python tools/pilot/hosted_build_context.py /private/tmp/dtm-hosted-context-new
docker buildx build --platform linux/amd64 --load -t dtm-hosted-boundary:local \
  /private/tmp/dtm-hosted-context-new
.venv/bin/python tools/pilot/hosted_image_proof.py --docker-host "$DOCKER_HOST" \
  --results /private/tmp/dtm-hosted-image-results-new
```

Use the dedicated no-mount Colima profile described in `packaging/pilot/README.md`; stop it
after verification. The image binds its internal port 8080 only through the explicit
`--host 0.0.0.0` entrypoint argument. Standalone Python defaults to loopback. Configuration is
mandatory: exact HTTPS origin, tenant/client UUIDs, dedicated managed identity, Table destination,
cloud-off and absolute artifact directory. No default developer credential chain, local identity
switch, provider worker or legacy route is enabled. In the local proof, synthetic identifiers
configure the real factory while Docker disables networking; nothing is provisioned or contacted.

Run as UID 10001 with read-only root, bounded `/tmp`, dropped capabilities, no-new-privileges,
explicit CPU/memory/process limits and no host mounts. The proof publishes no ports. Future
ingress must go through Entra/platform authentication; never publish the Stage 1 server.
Liveness is minimal `/healthz`; it does not prove Table connectivity or identity readiness.
Platform health probes must supply the configured Host header. Verify probe/auth exclusions
in the isolated deployment; do not relax authentication to make a probe pass.

## Expiry cleanup

`app.hosted.maintenance.cleanup_page(store, artifacts, tenant, kind, ...)` is an explicit
operator function, not an HTTP endpoint or automatically started loop. It accepts only
`session` and `artifact`, an exact tenant, a RowKey cursor and a bounded page (100 default,
1,000 maximum). It returns aggregate counts plus the next cursor; it never returns row values.
`apply=False` is the default. Run a dry pass first, then explicitly apply. Continue until a
page is empty; restart from the beginning on the next sweep so conflicts/failures are revisited.
Advance the cursor even when an early page contains unexpired records.

- Sessions expire after at most 30 minutes; cleanup deletes only expired rows using their
  exact ETag. A concurrent change becomes a counted conflict, not an unconditional delete.
- Artifacts expire after one hour. Cleanup first claims the expired registry row with an
  exact ETag and `cleanup_pending`, removes only its fixed-format file through a pinned directory
  descriptor, then deletes that registry row conditionally. A missing file is safe to finish;
  a symlink, file error or crash leaves the marker for retry. A publication metadata failure
  removes its just-created file. A process crash between file creation and registration can
  still leave an orphan until the disposable volume is replaced.
- Never scan/delete job queues, archives, retry keys, business records or other tenants through
  this path. Invalid rows are counted and preserved for investigation. A cleanup error never
  grants download access; expired/missing artifacts remain unavailable.

For the isolated pilot, propose a bounded cleanup pass every 15 minutes, with a cursor per
tenant/kind and one operator. No scheduler is installed here. Keep the single-replica artifact
constraint. Replacing ephemeral storage intentionally discards exports; regenerate them through
a newly authorized request. Multi-replica artifacts need private object storage first.

## Job recovery snapshot and restore

These are **logical application snapshots**, not Azure point-in-time recovery. Only job queue
and immutable job archive rows are included. Sessions, CSRF/cookie digests, artifact registries,
business documents, platform token stores and QBO credentials are excluded. SharePoint remains
the source of truth for business data and needs its separate reviewed recovery procedure.

Before a snapshot, stop ingress mutations, all workers, pollers and maintenance writers for
that tenant and verify they have stopped. The explicit `writers_stopped=True` argument is an
operator assertion, not a distributed lock. Azure queries do not create an atomic table snapshot.
Call `snapshot_jobs(store, tenant, writers_stopped=True)`. It validates job schemas and limits
the complete snapshot to 2,001 rows / 16 MiB; capacity failure yields no partial backup. Store
the result in a private encrypted backup location with a separate restore identity. Keep its
SHA-256 in an independently controlled inventory. The embedded checksum detects corruption,
not an attacker replacing the snapshot and checksum together. Never paste backup contents in
logs, Git or chat: owner IDs and reviewed resource references are operational data.

Proposed pilot policy: a daily quiesced snapshot and one before image/configuration changes,
14-day backup retention, immutable job archives/retry keys retained for the entire pilot.
This is not a promise of zero data loss. Record the last successful snapshot time and the
actual backup gap; do not delete older retry history just to recover storage capacity.

Restore procedure:

1. Keep all writers stopped and the destination isolated. Select a new empty tenant partition
   in a separately provisioned pilot metadata table. Confirm the tenant, independent checksum,
   snapshot time and last known operation. Do not restore over existing records.
2. Call `restore_jobs(destination, snapshot, tenant, writers_stopped=True)`. Before copying
   any jobs it writes a durable `recovery` fence. Copies use create-only writes; an interrupted
   restore resumes only against the same snapshot and identical existing copied rows.
3. Immutable terminal history stays terminal. Every restored queued/running job becomes
   `interrupted` with its lease cleared. No session is restored; staff sign in again.
4. Verify row counts, interrupted jobs, archive contents and the fence from a fresh store
   instance. Check both known retry keys and a key absent from the snapshot: enqueue, claim
   and advance must all fail with `recovery_review_required`. No provider callback may run.
5. Reconcile the entire backup gap against authoritative provider events before resuming any
   writes. The fence deliberately has **no automatic release operation**. Stage 4 must implement
   and review provider reconciliation before introducing workers or a fence-release tool.
   Read-only job history remains available while fenced. If reconciliation is incomplete,
   preserve the fence and rebuild reviewed intents individually after the missing history is known.

The local drill proves safe restore and interruption behavior using synthetic durable SQLite.
It does not verify real Azure permissions, storage protection, provider reconciliation or
end-to-end recovery time. Those are required isolated-deployment checks before unattended use.

## Monitoring without sensitive payloads

The hosted entrypoint installs a dedicated logging policy. HTTP events contain only UTC epoch,
event name, a fixed route category, an allowlisted method, server-generated correlation ID,
status and elapsed milliseconds. No URL/path values, query strings, headers, cookies, actor IDs,
claims, bodies, filenames or response data are logged. Successful health probes are omitted.
SDK/Waitress warnings retain only an allowlisted source and severity; their messages/arguments
and exception tracebacks are never formatted. Startup failures emit a fixed event and exit 1.
Desktop logging is unaffected. These logs diagnose error rate/timing; they are not business audit.

`packaging/hosted/monitoring.review.kql` prepares aggregate queries for the documented Container
Apps Log Analytics destination. Select the actual pilot app/table schema before submission.
No queries, alerts or log sink have been installed. Proposed review items: a 30-day log retention
limit, ingestion monitoring, owner-selected notification recipient, startup failure/replica-unready
alerts, sustained 5xx rate, and cleanup conflicts/file errors. Provider worker metrics wait until
workers exist. Liveness alone does not detect broken metadata access. Configure budget alerts
alongside replica limits; alerts are not hard spending caps.

References: [Table SDK conditional deletes and queries](https://learn.microsoft.com/en-us/python/api/azure-data-tables/azure.data.tables.tableclient?view=azure-python),
[Waitress logging](https://docs.pylonsproject.org/projects/waitress/en/stable/logging.html),
[Container Apps Log Analytics](https://learn.microsoft.com/en-us/azure/container-apps/log-monitoring).


## Deployment review gates

Before an isolated deployment, review concrete resources/costs, operator ownership,
retention, alerts, worker timeouts, and backup protection. Validate platform OAuth state/nonce,
header and cookie behavior, health-probe exclusions, actual Table permissions/consistency,
and restore protection. Local fake-SDK and synthetic recovery checks do not prove these.
The [hosted review configuration](../packaging/hosted/README.md) and
[deployment files](../packaging/hosted/azure/README.md) are preparation only. Real provider
adapters must enforce ACLs, ETags, finalization, and safe caches before exposing more routes.
Unattended workers and recovery-fence release require reviewed provider reconciliation.
Verification scope follows root [AGENTS.md](../AGENTS.md).
