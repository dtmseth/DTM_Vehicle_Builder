# Shared-user boundary (Stage 2)

**Status, 2026-09-10:** local security/storage contracts implemented; Azure, provider integration
and full hosted UI parity remain unverified/disabled. The owner explicitly advanced this work
while Stage 1's Linux measurement gate remained open. No trial, deployment or production access.

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
fenced logical job restore are implemented/tested locally; see [HOSTED_OPERATIONS.md](HOSTED_OPERATIONS.md).
Schedules, backup protection and worker timeout sizing still require deployment review. Provider writes
must be idempotent by event ID and use exact revision checks; a lease alone is insufficient.

Artifacts accept generated bytes only through the worker API, use random IDs and fixed PDF/PPTX
extensions, enforce owner/tenant/one-hour expiry and a 128 MiB cap, reject symlinks and verify size
and SHA-256 before download. The registry does not make local bytes durable across replicas.
Before multi-replica exports, add private object storage using the same ownership contract.

## Verification and remaining gates

The focused tests cover concurrent signed users, forged/invalid claims, stale shared edits,
role loss, session expiry/rotation/logout/restart, CSRF/Origin, unauthorized record and artifact
access, traversal/symlinks, idempotency, racing leases, interrupted workers and SDK conditional
writes. A real loopback Waitress request verifies the HTTP/session boundary. Existing focused
desktop tests and selected browser flows remain required by `tools/verify.py changed`.

The [review configuration](../packaging/hosted/README.md) contains no secrets/resource IDs and
has not been submitted to Azure. Stage 1 ARM64 and emulated AMD64 Linux proofs passed locally.
The separate AMD64 hosted image, cleanup/restore safeguards and fixed-schema telemetry now pass
local checks. Before Stage 3: review concrete resources/costs, operator ownership and the proposed
retention/alert settings; then test
platform OAuth/nonce/header behavior and actual Table access in an isolated deployment. The
full hosted Builder is not ready merely because these local boundary contracts pass.
