gotchas : {}}

# Gotchas

Every footgun discovered the hard way. Before editing anything, scan this list for the module
you're touching. New gotchas get appended to the bottom with a date.

---

## Package & naming

1. **Python package name is `dtm_buildsheet`** (underscore). PyPI name is `dtm-buildsheet` (hyphen).
   App name is "DTM Vehicle Builder". Don't rename `src/dtm_buildsheet/` without updating all imports.
2. **Compatibility shims** (`gui_server.py`, `config_loader.py`, `input_reader.py`, `models.py`,
   `planner.py`) are thin re-exports. New code imports from `app`, `domain`, `planning`, `inputs`
   directly.

---

## macOS / pywebview

3. **pywebview owns the main thread** on macOS — the HTTP server must run in a daemon thread. Don't
   move `webview.start()` off the main thread.
4. **ICNS must be real ICNS** — the source icon was a PNG renamed to `.icns`. It was converted
   properly via `iconutil`. Don't replace it with a raw PNG or PyInstaller silently falls back to
   the Python rocket icon.
5. **Port 7655 conflict** = old instance still running. `lsof -ti :7655 | xargs kill` clears it.

---

## Workspace & paths

6. **Workspace vs bundled**: `paths.py` detects dev mode via presence of `pyproject.toml`.
   - Dev: workspace = `{repo}/workspace/`, config/assets written to `src/dtm_buildsheet/resources/`
   - Bundled app: workspace = `~/Library/Application Support/DTM Vehicle Builder` (Mac) or
     `%APPDATA%\DTM Vehicle Builder` (Windows)
7. **Config files in `workspace/config/`** are editable JSON. Config saves go through
   `save_config_file()` which triggers template auto-regen for template-feeding files
   (`TEMPLATE_REGEN_FILES` in `config_service.py`).

---

## Template & config

8. **`template_builder.py`** reads 3 files: `workbook_rules.json`, `parts_library.json`,
   `vehicle_layouts.json`. Adding a new template-feeding config file → add its filename to
   `TEMPLATE_REGEN_FILES` in `config_service.py`.
9. **Config is a contract** — every config file must be documented in `CONFIG_SCHEMA.md`,
   validated in `config/schemas.py`, migrated in `config/migrations.py` when fields change,
   and covered by tests.

---

## Cloud & SharePoint

10. **Cloud is source of truth** for agencies, sales reps, presets, projects, and drafts (v2.2.9+).
    Saves direct-mirror to SharePoint via `save_setting_to_cloud_in_background`;
    deletes go through `delete_setting_from_cloud`. The dtm-shared-settings repo is audit-only.
11. **Migration script** (`tools/migrate_workbook_to_parts_db.py`): always use
    `--write --push-to-cloud`. Without `--push-to-cloud`, SharePoint sync silently overwrites
    the migration with its older copy on the next 60s cycle.

---

## QuickBooks

12. **QuickBooks user tokens never touch disk or cloud** — access/refresh tokens and realm binding
    live ONLY in the OS keychain via `adapters/quickbooks/credential_store.py`. The shared Intuit
    app secret is not shipped; it lives only in Netlify's protected environment for the stateless
    token broker. `quickbooks_config.json` holds non-secret metadata
    and is deliberately NOT in any cloud-mirror set.
13. **QuickBooks OAuth callback** (`routes/quickbooks.py`) MUST stay 302-only — never echo the
    code/token as HTML. All `/api/quickbooks/*` responses set `Cache-Control: no-store`.
---

## Testing

14. **Tests must NEVER write to the real workspace queue**. `tests/conftest.py` blocks real cloud
    I/O, and `wiring.save_via_proposal` refuses to enqueue when `PYTEST_CURRENT_TEST` is set.
    Bypassing these guards reintroduces the abc.json resurrection bug.
15. **Placement math is single-source**: `domain/geometry.py`. If you change it, update the
    preview canvas JS too.

---

## CI & packaging

16. **PyInstaller cannot cross-compile** — Mac builds must run on Mac, Windows builds must run on
    Windows (CI handles both).
17. **Auto-update** uses `update_check_service._expected_installer_suffix()` — don't hard-code
    `sys.platform.startswith("win")` in update-state code. That's how the Mac
    "platform_unsupported" bug shipped.

---

## UI

18. **`#card-preview` and `#card-manifest` are singletons** — they exist only inside
    `#proj-build-editor`. The standalone workbook-upload generator does not render them.
19. **Modal ownership** — each modal's save button is owned by exactly one IIFE. Never attach a
    second listener from another file.
20. **Inline style policy** — `display:none` in initial HTML is acceptable for JS-toggled elements.
    All other inline styles (colors, spacing, fonts, layouts) belong in `styles.css` as named classes.

---

## Data migrations

21. **`parts_db.json` is no longer just seed data, but it is not the only source of truth yet.**
    The Part Picker, parts-db routes, manifest grouping, some planner hydration, and several
    render image/size rules now consume it directly. The generator/template stack still also reads
    `workbook_rules.json` / `parts_library.json` / `vehicle_layouts.json` / `part_catalog.json`.
    Before moving a rule or deleting a legacy field, trace the specific consumer path.
22. **`agencies.json` / `sales_reps.json` flat files** are legacy migration sources only.
    Current storage is per-record (`workspace/agencies/{id}.json`, `workspace/sales_reps/{id}.json`)
    with SharePoint direct-mirror.
23. **Text location options do not create render coordinates.** A part_type with
    `location_mode:"text"` and `location_options` only gives the picker/dropdown a friendly list.
    If the selected location is expected to render, the exact location key must exist in
    `vehicle_layouts.json` or be mapped through a resolver/alias.
24. **Smoke flow count is currently 28.** Older docs and ledger entries may mention smaller counts;
    the current command is still `.venv/bin/python tools/ui_smoke/run_smoke.py`, and expected
    success is 28/28.

---

## 2026-08-10 QuickBooks production-preview follow-up

25. **Production QuickBooks is preview-only until separately approved.** Use the isolated
    `production_preview` profile and its separate cache; it must never call the normal reconcile
    path or the 30-minute poller. Production comparison writes reports/plans only, never
    `parts_db.json`.
26. **Confirm the QBO identifier column before bulk mapping.** The current sandbox stores vendor
    part numbers in QBO `Name` while `Sku` is often blank. Compare both fields against Builder
    `part_number`; only an owner-confirmed, unambiguous exact-match field can prepare a mapping
    plan. Known baseline exclusions remain excluded.
27. **Cloud-off does not disable the existing sandbox QuickBooks item poll.** `DTM_CLOUD=0` prevents
    SharePoint mirroring, but the normal connected sandbox profile can still issue read-only QBO
    Item queries and reconcile its local workspace cache. The isolated production-preview profile
    is never included in that startup/polling path.
28. **Production may contain both `SKU` and `SKU (deleted)` Items.** Historical migration matching
    must prefer the literal active/raw Name before treating the deleted-name suffix as lineage.
    Description-only normalization can make the current and retired records look identical while
    their Item IDs, active state, and prices differ.
29. **A promoted OAuth refresh token must have one active profile owner.** Copying the production
    preview token into the standard profile and leaving both profiles connected creates a refresh-
    token rotation race. Promotion removes access/refresh/realm data from the preview store without
    revoking it; revocation would also invalidate the newly promoted standard connection.
30. **QuickBooks Customer IDs are company-local and can collide across sandbox/production.** Never
    carry agency `qb_customer_id` values across companies or run the normal ID-first import before a
    reviewed migration. The 2026 production transition found 108 sandbox IDs pointing at different
    production Customers. Migration matches unique normalized names first and permanently filters
    owner-rejected duplicate production Customer IDs from future imports.
31. **QBO Item prices are list prices; estimate prices are calculated separately.** Never reconcile
    Retail/Custom discounts into `qb_unit_price` or the Item cache. Apply the shared
    `customer_pricing.default_rule`, then sparse `AgencyRecord.pricing_overrides`, only to resolved
    estimate lines and send the reviewed unit price explicitly. The Estimate form's **Discounts and
    fees → Bank transfer — 1% per transaction, max $20** switch is separate from the Invoice-only
    `AllowOnlineACHPayment` field and is not exposed by the Estimate API. Do not invent a field;
    require the explicit QBO follow-up after creation.
32. **Saved presets must retain the rich `DraftPart` shape.** `part_type`, concrete SKU
    `components`, `picker_config`, accessory relationships, and placement metadata drive rendering,
    picker edit round-tripping, and QuickBooks estimate resolution. Reducing a saved build to the
    legacy workbook columns makes a newly created vehicle look similar in the manifest while losing
    its renderer identity and billable SKUs.
33. **Estimate creation and PDF attachment are separate QBO writes.** A successful Estimate must
    remain successful if its later Attachable upload fails. Never automatically retry the Estimate
    write after an attachment error; doing so creates duplicate financial forms. Existing vehicle
    estimates require an explicit update-vs-create-new choice before any Estimate write.
34. **The local UI server must remain concurrent and status polling must remain local-only.**
    Microsoft identity, SharePoint, QuickBooks, and installer transfers can block until a network
    timeout. Serving them through a single-threaded `HTTPServer`, or adding a remote provider call
    to `/api/cloud/status`, freezes every UI request behind the slow call. Background startup sync
    must never launch interactive OAuth; only the explicit Sign In / Force Sync actions may prompt.
35. **An available update is not necessarily downloading.** Only
    `update_check_service.is_download_in_progress()` may produce the `downloading` UI state.
    Remote availability without an active transfer is `available`; a failed transfer backs off
    before retrying and keeps the manual Download action visible.
36. **Preset agency choices must not reuse Settings-tab initialization state.** Agencies can change
    through the Agencies tab, project wizard, QuickBooks import, or background SharePoint sync while
    the Presets tab remains mounted. Refetch `/api/agencies/choices` immediately before every preset
    modal open and preserve the `dtm:agencies-changed` refresh path for already-open preset UI.
37. **Project-manager “All Presets” is not a compatibility view.** Both the new-project wizard and
    Project Details editor must render `_ptVisiblePresets()` for All. Vehicle/build filtering belongs
    only to narrower convenience views; do not reuse `_ptCompatiblePresets()` under an All label.
38. **Round-light allocations own comments per location.** The 3-inch round-light picker creates one
    manifest row per nonzero location, so it must read/write `locationAllocation.comments[location]`
    and each row's `comment`. Do not route this flow through the shared footer comment or one note
    will overwrite every allocated line.
39. **SharePoint export identity usually differs from the local filename.** Local PPTX/PDF files
    retain a render timestamp; the normal Replace path writes the stable filename from
    `exports_upload_service.canonical_export_filename()`, while explicit Keep both uploads retain
    their timestamp. PDFs stay in the visible agency/year tree;
    PPTX sources live under `_DTM Internal PowerPoint Sources`. Hydration and cleanup must use the
    shared path helpers and preserve the legacy combined-folder fallback. Remote upload/delete is
    serialized so an outbound retry cannot resurrect a replaced artifact.
40. **Creating a SharePoint list needs a different delegated scope than using it.** The one-time
    operations provisioner requests `Sites.Manage.All`; the read-only rollout uses the existing
    `Sites.Read.All` consent, and the future write pilot must explicitly acquire
    `Sites.ReadWrite.All`. Asking silently for the future write scope makes MSAL fail even though the
    signed-in user and list access are healthy. Never add `Sites.Manage.All` to ordinary startup
    token acquisition. Create permanent machine names of at most 32 characters, validate all
    columns, and address the lists by GUID afterward. Graph may preserve a longer display name while
    silently truncating the internal field name.
41. **DTM app roles come from the ID token, not the Microsoft Graph access token.** The Graph token's
    audience is Graph and its permissions are not DTM workspace roles. Use only MSAL-validated
    `id_token_claims`; on a fast access-token cache hit, recover the validated ID token from MSAL's
    encrypted cache. Unknown role values and cloud-enabled local-identity fallbacks grant no
    Operations capability.
42. **Builder projection must never replace an entire Operations record.** Map through the narrow
    `BuilderVehicleProjection`, merge only its explicit fields, and relate rows by the opaque
    `IndividualUnit.individual_id`. Names, unit numbers, and VINs can change. Projection preview
    must use `list_vehicles()` so inspecting candidates cannot trigger pending-event repair writes.
    Ordinary project saves now upsert this narrow projection automatically. The legacy pilot POST
    remains create-only and cannot be used to alter an existing row.
43. **The Operations pilot browser payload is not record data.** It contains only the opaque
    Builder vehicle ID, an exact confirmation token, and a one-use request ID. The server re-derives
    the complete `BuilderVehicleProjection` from current project records, repeats the
    `projects.edit` check, and calls the create-only service. Never accept identity, VIN, agency,
    lifecycle, or workstream fields from this browser request, and never reuse the pilot route to
    update an existing Operations row. Routine queries use the read repository; only the confirmed
    foreground action may invoke the separate writer that requests `Sites.ReadWrite.All`.
44. **Do not load Operations projection candidates on every populated-backlog view.** The normal
    vehicle endpoint already reads the complete current list. A second automatic preview query
    doubles Graph work and slows the tab as production grows. Auto-load candidates only for the
    empty first-run state; afterward the authorized header action loads them on demand. After each
    confirmed creation, discard the preview so the next click compares against fresh list state.
45. **Operations bulk seeding must not introduce a bulk mutation authority.** The UI may confirm a
    reviewed Active + Completed candidate set once, but it must call the existing create-only route
    sequentially with one request ID per vehicle. Stop on the first failure, retain completed pairs,
    and refresh the preview before retrying. Import Completed projects as
    `ProjectState=completed`; do not invent acceptance, delivery, workstream statuses, or historical
    milestone dates. Normalize Builder finalization timestamps to UTC whole seconds before compare
    or Graph's precision loss makes every finalized row look perpetually stale.
46. **Project-wide Operations status changes are still per-vehicle commands.** The project group is
    a UI convenience because its vehicles usually share a status; it must call the one-vehicle
    status route sequentially with each current revision and a separate request ID. Stop on the
    first failure, refresh the shared state, and retain one event per successfully changed vehicle.
    Keep the individual action available for exceptions, and never replace this with an unchecked
    project-row overwrite or one synthetic project event.
47. **Provisioned Operations list IDs must ship in the bundled cloud config.** The one-time
    provisioner writes validated GUIDs to the current development workspace only; that file is
    gitignored and is not packaged. Before releasing Operations, copy the two non-secret GUIDs into
    `resources/default_data/cloud_config.json`. Existing installs receive missing keys through the
    startup forward-merge. `test_bundled_cloud_config.py` treats both IDs as required release data.
47. **Operations history reads must not reconcile pending events.** The normal history UI uses the
    `Sites.Read.All` repository, so `list_events()` may query only applied event rows and must never
    patch a pending marker or current record. Recovery remains a writer-path concern through
    `get_vehicle()`, duplicate-request lookup, and mutation retries. Otherwise merely opening a
    timeline can fail for read-only users or unexpectedly ask them for write consent.
48. **Operations schedule edits are patches, and every date is independent.** Do not make users
    re-enter existing fields or enforce acceptance, Monday, ordering, or cross-field dependencies.
    Send only changed fields and issue one revision-checked command/event per vehicle. Continue to
    derive Prospective/Unscheduled/Scheduled from acceptance plus `ScheduledWeekOf`. Store a manual
    **Must Deliver On** date in `MustDeliverOverrideDate`; `MustDeliverByDate` is the effective
    projection and returns to its 60-day calculation when the override is cleared. `parts_ready`
    must also backfill a missing Parts Received milestone because that state logically implies all
    parts were received.
49. **Projects lifecycle tabs are one list surface, not separate storage or an archive route.**
    Filter the already loaded project records by the durable `project_status` values `active`,
    `inactive`, and `completed`. Preserve the selected tab when returning from detail. Completed
    projects keep the Agency → Build Year tree inside the Completed tab; inactive projects remain
    fully recoverable and may carry an optional reason. Lifecycle changes must continue through the
    existing server endpoint so timestamps and `project_lifecycle_history` are preserved. Mirror
    lifecycle to Operations by opaque project ID; inactive rows retain their history but are hidden
    from the Operations workspace until reactivated.
50. **Parts Ordered is a real schema-v3 milestone, not a UI alias.** `ordered` is a stable
    `PartsStatus` choice and writes `PartsOrderedAtUtc`. The live upgrade must both add that
    permanent column and extend the existing SharePoint choice list. Never infer an order date when
    imported work skips directly to Partially Received or Received.
51. **Project prompts must be app modals, and selector-created vehicles remain placeholders.** Native
    `prompt()` is not reliable inside every pywebview host, so lifecycle reasons and Make/Model entry
    use DOM modals. The project vehicle route must save through the ordinary validated
    `vehicle_layouts.json` service, create no artwork, reuse exact Make/Model matches, and refresh both
    project selectors immediately. Placeholder layouts still need all standard view stubs and the
    placement/fixture canvases must not request intentionally absent artwork. Keep
    Active/Inactive/Completed search text separate; a Completed
    search may expand matching groups but must not flatten or rewrite the stored project records.
    The config migration must continue forward-normalizing older user-created placeholders so
    workstations that cached the early four-view shape gain metadata-only internal stubs and bottom
    Side/Top logos without borrowing artwork or fixtures.
52. **Project deletion and delivery completion cross the Builder/Operations boundary.** Delete
    Operations events and current rows by the exact Builder project ID before removing the Builder
    record; if shared cleanup fails, leave the Builder project in place for a safe retry. Mark a
    project Completed only after every current `IndividualUnit.individual_id` has an Operations row
    whose Final Finish status is Delivered. Vehicle Availability ends at At DTM and should render
    green there. Keep legacy availability=`delivered` values readable, but never infer completion
    from them, a partial match, or a name-based match.
53. **Started is a derived Projects view, not a persisted lifecycle state.** Project records still
    store only `active`, `inactive`, or `completed`. Split durable-active records by the exact current
    Operations vehicle IDs: every vehicle must be accepted for the project to appear in Active;
    missing or partly accepted records stay in Started. Active ordering is project-wide: rows whose
    every vehicle has Parts Received/Parts Ready and is At DTM come first, then each group sorts by
    its earliest effective Must Deliver On date with undated projects last. Do not infer acceptance,
    arrival, or deadlines from names or badges.
54. **A failed Operations read must preserve the last good Projects classification snapshot.**
    Projects derives Started versus Active from Operations acceptance, but a rejected/temporary
    Operations request is not evidence that acceptance was cleared. Replace
    `operationsByProject` only after an explicit successful response; before the first successful
    snapshot, keep durable-active projects in the neutral Active view instead of inventing Started.
55. **Automatic QBO refresh includes Customers but must remain write-idempotent.** Connected startup,
    30-minute polling, and the post-OAuth wakeup refresh Items and Customers/Agencies. Customer
    down-sync remains additive and must not rewrite or SharePoint-mirror hundreds of unchanged
    agency records on each pass. The first QBO pass waits for the initial SharePoint settings sync;
    both sources touch the local agency collection and racing them can discard a valid update.
56. **Header visibility is not Builder authorization.** Legacy project, draft, settings, catalog,
    and QuickBooks routes are capability-checked in `request_access_service.py` before dispatch.
    Every new legacy route must be deliberately classified there; Shop read access uses
    `projects.view`, while all mutations retain narrower capabilities. QuickBooks estimate users may
    connect and refresh their own session, but catalog links, Retail-pricing defaults, and app
    registration settings remain administrative.
57. **The Scheduled Operations subfilter sorts by Scheduled Week before readiness.** The general
    Active view still puts fully arrived projects first and then uses Must Deliver On. Once the user
    explicitly chooses Scheduled, chronological week is the primary ordering so later arrived work
    cannot jump ahead of an earlier scheduled week.
58. **Keep iterative verification to one relevant test file.** Follow root `AGENTS.md`:
    `.venv/bin/python -m pytest tests/test_<target>.py --maxfail=1`. Never autonomously run
    browser smoke tests during ordinary edits or small feature additions. Run
    `tools/verify.py changed --skip-smoke` only when the owner explicitly requests a pre-commit
    verification pass; staging alone does not narrow its diff against `HEAD`. Full browser
    runs and `tools/verify.py release` are strictly pre-release checks. Report compact summaries.
    CI remains the authoritative full-suite and coverage gate.
59. **Builder lifecycle is authoritative for Operations visibility.** The Operations projection may
    contain a stale `project_state=active` row from an older client. The Operations vehicles API
    filters every Builder project currently marked Inactive before returning rows or counts; do not
    rely only on the projected state or a browser-side tab to hide inactive work.
60. **The optional Power App writes requests, never authoritative Operations rows.** Power Apps may create only a
    `pending` item in `DTMOperationsRequests` with a fresh UUID and the revision it displayed. The
    Power Automate trigger is concurrency one. The processor accepts only normal forward Shop, Tray,
    Programming & QC, or Final Finish transitions; corrections remain desktop-only. It must create
    the pending immutable event before its ETag-guarded current-row PATCH and mark the event applied
    afterward. A stale revision becomes `conflict`, never last-write-wins. The event's recovery
    snapshot may use canonical domain keys or exact SharePoint internal field names; the desktop
    codec normalizes both. Never grant that Power App a direct update path to either core list.
    This contract belongs to the optional Canvas client, not the planned full HTML mobile client,
    which will use the role-checked Builder backend. The existing processor remains Off.
61. **Calendar dates and the 60-day commitment are separate.** Calendar publishes only planned
    start, derived Scheduled Week, and estimated ready date through the existing one-vehicle
    schedule service. It must never move a deadline to hide a late forecast. Operations' date
    schedule-date editor now owns only the deadline override; its separate Accepted date action
    edits shared acceptance. Calendar reads/replans never mutate shared state (the local replica cache is durable); its
    shared plan uses conditional ETag saves and must never enter the ordinary settings mirror.
    During multi-vehicle publication, previously mirrored Operations dates must not alter queue
    ordering or become new fixed-start constraints. See `CALENDAR.md`.
62. **Calendar acknowledges durable local saves before background publication.** The owner/config-bound
    replica and outbox are one atomic journal; do not block editing on provider uploads or replace
    newer local edits with an older upload result. Resume queued snapshots after restart with fresh
    authorization, Operations checks and conditional shared ETags. Merge disjoint edits; pause real
    conflicts for explicit review. Keep per-vehicle revisions and immutable events, and do not reload
    the whole Operations list per vehicle. Worker auth must be silent; never reuse the foreground
    interactive token provider. A QBO observation time is not the original Accepted Date.

63. **Acceptance is a business date, and QBO observation is a timestamp.** Both Calendar and
    Operations edit the same accepted date via immutable Operations corrections. Preserve manual
    dates during polling. QBO AcceptedDate may round-trip through SharePoint as midnight UTC;
    strip its time before interpreting it. Missing QBO AcceptedDate stays missing, never the
    observation time. Shop can read acceptance and start/finish builds but cannot edit dates or
    schedules. Michelle's small-agency preference is soft; never idle another available team
    solely to enforce that preference.

64. **A headless Builder is not yet a hosted multi-user Builder.** `wiring._active_bundle`, local
    workspace paths and desktop credentials describe one workstation. Do not expose the desktop
    server publicly or trust forwarded identity headers without a verified auth boundary. Start
    with the isolated local prototype in `AZURE_PILOT_PLAN.md`; add request-scoped identities,
    durable jobs, authorized file access and concurrency checks before an external pilot. Keep
    local test identities unavailable in deployed mode and preserve desktop keychain rules.

65. **Pilot isolation must precede every application path import, including indirect renderer calls.**
    Launch with `python -m dtm_buildsheet.headless`; package initialization is deliberately lazy.
    `DTM_WORKSPACE_DIR` redirects mutable module constants as well as `AppPaths`, and the pilot
    branch of `ensure_workspace()` never copies desktop defaults. Render helpers invoke that
    initializer even when a caller supplies paths. Do not remove this guard or seed real presets,
    agencies, reps or cloud config into a pilot. See `AZURE_PILOT_RESULTS.md`.

66. **A request context does not make desktop routes or caches multi-user safe.** Hosted requests
    resolve their own bundle; background threads have no inherited user and may not fall back to
    `_active_bundle`. Only the explicit hosted route allowlist is exposed. Provider/resource
    adapters must enforce ACLs and exact ETags, and may not reuse shared desktop caches or raw path
    arguments. `DTM_CLOUD=0` does not mean a hosted request should become local AppAdmin.
67. **An expired worker lease is an uncertain outcome, not permission to replay.** Hosted jobs
    retain reviewed revisions, step event IDs and immutable terminal archives. Stop on conflict,
    revocation or interruption and reconcile before a new review. Copy archive data before removing
    the queue entry so retries cannot recreate a completed job. Do not delete retry keys to free
    capacity. See `HOSTED_BOUNDARY.md`; desktop Calendar semantics remain in `CALENDAR.md`.

68. **Local Linux architecture and cgroup measurements need explicit provenance (2026-09-10).**
    Build the pilot with an explicit platform and pass the same `--platform` to its proof runner;
    an ARM64 image passing locally does not verify AMD64 compatibility. Rosetta timings include
    emulation overhead and cannot predict Azure performance. `memory.peak` is bytes across the
    container lifetime, not a per-export MiB value; report its scope and convert by 1024 squared.
    Keep Builder on the internal network and expose only the fixed-destination localhost relay.
    UI assets must be present in both the staged context and installed wheel package data.
69. **Projects refresh completion must not navigate (2026-09-10).** `initProjectsTab()` selects
    the list before awaiting data, then only renders refreshed list content. A user can open a
    project or draft during that request; selecting the list again afterward silently closes
    their editor. The delayed-refresh browser regression preserves the open build editor.
70. **Restoring a job backup must not authorize replay (2026-09-10).** Metadata recovery is an
    offline operation into an empty partition. Preserve terminal retry keys, interrupt active
    jobs and retain the `recovery` fence even for request IDs absent from an old snapshot. The
    fence has no automatic release; provider reconciliation is a later integration requirement.
    Session/artifact cleanup never scans job history and must keep exact delete preconditions.
71. **Hosted SDK warnings can contain credentials (2026-09-10).** The dedicated hosted logging
    handler must not format messages, arguments or exception tracebacks. Emit fixed source/severity
    categories and server-generated request IDs only; never attach raw URLs, claims or payloads.
    Configure this policy only in the hosted entrypoint, leaving desktop logging unchanged.

72. **Project type is independent of vehicle/build type and lifecycle.** Missing values mean Build.
    Service visits keep distinct IDs and output names; never merge them by agency/year or copy prior
    parts through a previous-build reference. Calendar and Operations attach authoritative Builder
    work metadata at read time; service deadlines are optional/manual. N/A workstreams retain their
    existing statuses and history. Service estimates, travel and requirements must be included in
    Calendar preview/replay validation; no rendering is required to schedule service work.
