# Hosted pilot operations — local preparation only

**2026-09-10:** the functions, image and synthetic checks below are local preparation. No
Azure resources, schedules, alerts, identity grants, trial or live backup were created.
This is the small authenticated boundary, not full hosted Builder or mobile parity.

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
