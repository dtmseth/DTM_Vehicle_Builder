# Gotchas

Only when debugging unexpected errors in specific modules. These are ongoing runtime and
framework hazards; feature contracts belong in their focused docs. Verification policy lives
in root [AGENTS.md](../AGENTS.md).

## Runtime and paths

1. **pywebview owns the macOS main thread.** Keep `webview.start()` on that thread and run
   the HTTP server in a daemon thread. Use DOM modals for input; native `prompt()` is unreliable
   across pywebview hosts.
2. **The local HTTP server must remain concurrent.** Provider calls and installer transfers
   can block until timeout. Keep `/api/cloud/status` local-only, and never launch interactive
   OAuth from background startup or polling; explicit sign-in actions own prompts.
3. **Workspace paths differ between development and installed apps.** `paths.py` detects
   development via `pyproject.toml`: work lives in `{repo}/workspace/`, while editable config/assets
   use `src/dtm_buildsheet/resources/`. Installed apps use Application Support on macOS or
   `%APPDATA%\DTM Vehicle Builder` on Windows. Resolve paths through the shared helpers.
4. **Pilot isolation must happen before any application-path import.** Use the lazy
   `dtm_buildsheet.headless` entrypoint and `DTM_WORKSPACE_DIR`; renderer helpers may call
   `ensure_workspace()` indirectly. The pilot initializer must not copy real desktop defaults,
   presets, agencies, reps, or cloud configuration.

## Config, cloud, and rendering

5. **Config saves must use `save_config_file()`.** It preserves validation, proposal/mirror
   behavior, and template regeneration. Shared `parts_db.json` writes must reach the cloud mirror;
   a direct local JSON write can be overwritten by the next SharePoint sync. Register new
   template-feeding files in `TEMPLATE_REGEN_FILES`; do not bypass the normal save path.
6. **SharePoint is authoritative for shared settings and work.** Agencies, sales reps, presets,
   projects, and drafts use direct mirroring. Saves use `save_setting_to_cloud_in_background`
   and deletes use `delete_setting_from_cloud`; the settings Git repository is audit-only.
   `DTM_CLOUD=0` disables SharePoint mirroring, but does not disable a connected QBO poller.
7. **Parts consumers are only partly migrated.** The picker, parts routes, manifest grouping,
   and some planner/render rules read `parts_db.json`; other generator/template consumers still
   read workbook-era configuration. Trace each consumer before removing a legacy field. See
   [PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md).
8. **Geometry and placement math have one canonical source: `domain/geometry.py`.** Keep
   preview/canvas JavaScript aligned with it; do not introduce an independent placement formula.
   Text `location_options` alone do not supply coordinates: rendered locations must resolve to
   an exact layout key or a deliberate resolver/alias.
9. **Saved presets need the rich `DraftPart` shape.** Preserve `part_type`, concrete SKU
   `components`, `picker_config`, accessory relationships, and placement metadata. Reducing a
   preset to workbook columns loses renderer identity, picker round-tripping, and billable SKUs.
10. **Remote export identity differs from local filenames.** Replace uses
    `exports_upload_service.canonical_export_filename()`; Keep both retains timestamps. Use shared
    path helpers for PDFs and internal PPTX sources, preserve legacy folder fallback, and serialize
    remote upload/delete so a delayed retry cannot resurrect a replaced artifact.

## Identity and provider writes

11. **QuickBooks tokens and realm binding stay in the OS keychain.** Access/refresh tokens and
    realm data use `adapters/quickbooks/credential_store.py`, never disk files, SharePoint, logs,
    project JSON, or browser storage. `quickbooks_config.json` contains non-secret metadata and
    never joins a cloud-mirror set. The shared Intuit secret stays in the protected Netlify broker
    environment and is never shipped to desktops. See [QUICKBOOKS.md](QUICKBOOKS.md).
12. **One refresh token needs one active profile owner.** Copying a promoted token while leaving
    both profiles connected creates rotation races. Remove the old profile binding without
    revoking the token now owned by the new profile. QBO Customer IDs are company-local; never
    carry sandbox identifiers into production as trusted matches.
13. **OAuth callbacks and Estimate retries have strict boundaries.** QBO callbacks stay
    302-only and never echo codes/tokens; `/api/quickbooks/*` responses are `no-store`. Estimate
    creation and PDF attachment are separate writes: an attachment failure must not retry a
    successful Estimate creation. Existing Estimates require an explicit update/new choice.
14. **DTM roles come from validated ID-token claims, not Graph access tokens.** On cache hits,
    recover the validated ID token through MSAL's encrypted cache. Unknown roles or failed role
    resolution grant nothing. Hidden UI controls do not authorize requests: each route must be
    classified and capability-checked before dispatch. See [OPERATIONS.md](OPERATIONS.md).
15. **Operations projections and reads must not erase or mutate independent state.** Merge only
    `BuilderVehicleProjection` fields by opaque vehicle ID. Read-only history queries return
    applied events without repairing pending writes. Mutation retries use exact revisions/ETags,
    one request ID and immutable event per vehicle, including project-wide actions. Never turn
    a conflict into an unconditional overwrite.

## UI and background work

16. **DOM ownership survives asynchronous refresh.** `#card-preview` and `#card-manifest` are
    singletons inside `#proj-build-editor`; each modal save button has one owning IIFE. A completed
    Projects refresh may update list content but must not navigate away from a newly opened editor.
17. **Calendar's replica and outbox are one atomic journal.** Acknowledge local durable saves
    before background publication, and never replace newer edits with an older upload response.
    Resume with fresh silent authorization, Operations revisions, and conditional shared ETags;
    pause real conflicts. Calendar's shared plan never enters the ordinary settings mirror.
    Planned dates never move the 60-day commitment. See [CALENDAR.md](CALENDAR.md).
18. **Hosted context cannot make desktop routes/caches safe for multiple users.** Hosted
    workers have no inherited identity and cannot fall back to `_active_bundle` or local AppAdmin.
    Expose only reviewed hosted routes, with resource ACLs and exact ETags; never reuse raw path
    inputs, shared desktop caches, or forwarded identity headers as authorization.
19. **Expired leases and restored backups cannot authorize replay.** A remote write may have
    succeeded before interruption. Reconcile provider events first, preserve terminal archives
    and retry keys, and retain the restore `recovery` fence even for IDs missing from the snapshot.
    Session/artifact cleanup must not scan job history. See
    [HOSTED_ARCHITECTURE.md](HOSTED_ARCHITECTURE.md#job-recovery-snapshot-and-restore).
20. **Hosted SDK warnings can expose credentials.** The hosted logging handler emits fixed
    source/severity categories and server-generated correlation IDs, without formatting raw
    messages, arguments, tracebacks, URLs, claims, or payloads. Configure it only in the hosted
    entrypoint; desktop logging has its own policy.
