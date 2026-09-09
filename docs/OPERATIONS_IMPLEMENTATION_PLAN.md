# Operations Implementation Plan

**Status:** Active plan
**Last updated:** 2026-09-08

This plan delivers the production-operations system in small, independently verifiable slices.

## Current checkpoint

Phase 0's documents and Phase 1's pure backend foundation are drafted and covered by cloud-off
tests. The existing project model now understands Inactive lifecycle history. The owner approved
direct creation of the empty final SharePoint lists instead of a separate test site. An exact
offline schema manifest, read-only inspector, and confirmation-gated provisioner now exist. The
two empty production lists were created, fully revalidated, and their GUIDs saved locally on
2026-09-04. The five-column additive recovery upgrade was then applied and independently inspected;
both empty lists exactly match the executable schema. The GUID-addressed SharePoint repository now
passes the same basic behavior contract as
the in-memory repository plus mocked ETag-race, retry, partial-write recovery, and cloud-isolation
tests. Its two-stage commit records a pending event with the intended current snapshot, applies the
current row conditionally, then marks the event applied. Phase 2's schema and repository gates are
complete. Phase 3's first slice now reads validated Entra ID-token role claims, exposes a
server-authorized access description and compact vehicle query, and renders a role-gated
Operations workspace with local filtering. Its repository list method is proven not to repair or
write during that query. The approved Entra roles are declared, the owner is directly assigned
`AppAdmin`, and the resulting trusted ID-token claim was verified on 2026-09-07. A second read-only
inspection confirmed both live lists still exactly match the schema. The Builder projection now has
a narrow value object, a tested create/refresh mutation service, and an authorized read-only preview
that compares every individual Builder vehicle with the Operations list by opaque vehicle ID. The
preview displays the full VIN and exact new/update mapping in the desktop UI. Its narrowly scoped
POST route can create one explicitly selected new vehicle after a native confirmation. The route
re-derives the complete projection from current server-side Builder data, requires `projects.edit`,
uses a one-use request ID, and cannot update an existing Operations record. Read and write Graph
tokens remain separate: routine reads use `Sites.Read.All`, while the foreground confirmed action
requests `Sites.ReadWrite.All` interactively. The cloud-off browser smoke test exercises the entire
flow against the shared in-memory repository without network access. The owner then confirmed the
first production pilot creation on 2026-09-07 for one Granite Falls vehicle. A direct read-only
verification found exactly one current row at revision 0 and exactly one matching `record_created`
event with `CommitStatus=applied`; the current row's `LastEventId`, opaque vehicle ID, project ID,
full VIN, actor, and timestamp all match the event. No duplicate row was created. No Power App has
been created. The Operations header now keeps an authorized **Add Builder vehicle** action available
after rows exist; it loads candidates only on demand and retains the same create-only, full-VIN
confirmation for every vehicle. A cloud-off browser test proves the first add leaves exactly the
next candidate available. The reviewed bulk extension now offers one **Add all** confirmation for
new Active and Completed Builder vehicles, then calls the same create-only endpoint sequentially
with a separate request ID per vehicle. It displays progress, stops at the first failure, and leaves
completed writes valid so a fresh preview can retry only the remainder. Completed project records
are stored with `ProjectState=completed`; historical workstream dates/statuses are not fabricated.
The Builder finalization timestamp is canonicalized to Graph's UTC whole-second representation, so
the verified pilot is current instead of reporting a false microsecond-only change. The owner then
completed the reviewed import. Read-only verification found 78 current vehicle rows across 44
projects (30 Active, 48 Completed) and 78 unique applied `record_created` events, with no duplicate
vehicle, event, or request IDs. The desktop backlog is now grouped by project by default. Expanding
a project shows its individual vehicles for exceptions. Capability-gated status-step buttons apply
ordinary forward changes with one click to every vehicle in a project; individual override controls
use the same behavior inside each vehicle card. Project updates deliberately
orchestrate the existing one-vehicle route sequentially, and each vehicle receives its own revision
and history event. Normal forward changes are quick, while skipped/reversed changes retain the
existing manager-permission and correction-reason modal. Project saves now create missing Operations
rows and refresh existing Builder-owned projection fields without changing Operations-owned status,
schedule, or history. Lifecycle changes mirror by opaque project ID; inactive rows stay stored but
hidden, and project deletion cascades exact Operations rows/events before removing the Builder
record. Each expanded vehicle now has
a complete newest-first history view showing status values, automatic entry time, optional effective
date, actor/technician, revision, and correction note. History uses only applied events through a
strictly read-only repository query, so opening it cannot request write consent or repair SharePoint
state. Capability-gated project and individual schedule editors patch only the date fields the user
actually changed through one-vehicle revision-checked commands. Every field is optional and may be
entered before acceptance; no Monday or cross-field dependency is enforced. Acceptance plus a
Scheduled Week still controls the derived queue. The effective **Must Deliver On** date normally uses
the 60-day calculation, but an optional separately stored manual override supports imported or
manually maintained vehicles. Clearing the override restores the automatic date. Status surfaces
use white for unstarted/not-ready, light yellow for intermediate, and green for the completed state.
At DTM completes Vehicle Availability; Delivered is the last Final Finish step and automatically
completes the project only after every exact project vehicle reaches it. Active project rows derive
one limited workflow badge. The schema-v4 live choice upgrade was applied and both lists revalidated
on 2026-09-08. The next working-tree slice replaces the short-lived Invoice reference action with a
verified, read-only existing-Estimate connection and shared status/freshness observation. The next
gate is a production status/schedule pilot, followed by duration summaries.

## Working method

- Freeze contracts before creating hard-to-rename SharePoint objects.
- Put workflow meaning in domain/service code, not UI handlers.
- Keep tests cloud-off and use an in-memory operations repository first.
- Complete one vertical slice before cloning it across workstreams.
- Add interfaces role by role behind capability checks.
- Treat AI-generated code like any other code: small diffs, explicit tests, reviewable behavior.
- Preserve existing Builder, finalization, QBO, SharePoint file, and render baselines.

## Phase 0 — Architecture contract

### Deliverables

- `OPERATIONS_SYSTEM.md`
- `OPERATIONS_SCHEMA.md`
- `OPERATIONS_ROLES.md`
- this implementation plan

### Exit criteria

- Status values and meanings are reviewed.
- Authority boundaries are explicit.
- Internal SharePoint names are reviewed before production creation.
- Open decisions are visible rather than silently guessed.

## Phase 1 — Pure operations backend

### Deliverables

- `VehicleOperations` current-state model.
- `OperationsEvent` append-only event model.
- Stable enums for status, workstream, event, source, acceptance, role, and capability.
- Pure role-to-capability resolver.
- Transition service with validation, automatic UTC dates, idempotency, revision checks, and
  correction reasons.
- Vehicle availability model with optional business-effective date and authenticated entry time.
- Derived Commitment Start and Must Deliver By calculation from vehicle availability and Parts Received.
- Scheduling, delivery, Builder-projection, document-link, and QBO-observation fields
  defined in the shared model even when their mutation slices ship later.
- In-memory repository adapter.
- Project lifecycle model extended to `inactive` with audit metadata.
- Focused unit and codec tests.

### Exit criteria

- Normal workstream transitions set the expected current status and milestone date.
- Identical state is a no-op.
- Duplicate request IDs cannot create duplicate events.
- Stale revisions are rejected.
- Invalid, unauthorized, and backward transitions fail safely.
- Authorized correction records a reason and preserves history.
- Acceptance aggregation returns Not Accepted, Partially Accepted, or Accepted correctly.
- The 60-day commitment uses the later prerequisite and is blank until both are known.
- A shared-account event can retain authenticated actor and optional selected technician separately.
- Existing active/completed project JSON remains backward compatible.
- Full existing tests remain green.

## Phase 2 — SharePoint provisioning and repository adapter

### Deliverables

- Exact executable schema manifest with permanent list and column names.
- Offline-tested, read-only schema inspection and confirmation-gated list creation.
- Automatic capture of validated list GUIDs in non-secret local configuration.
- Graph list repository behind the same operations port.
- `Sites.Read.All` for the read-only rollout, one-time `Sites.Manage.All` for provisioning, and
  explicit pilot-only `Sites.ReadWrite.All` validation before writes are enabled.
- GUID-based list configuration.
- eTag/revision concurrency enforcement.
- retry/idempotency and partial-write reconciliation.
- schema-inspection tool that reports missing, mistyped, or unexpectedly renamed columns.
- mocked Graph contract tests that cannot reach live SharePoint.

### Exit criteria

- In-memory and SharePoint repositories pass the same behavioral contract suite before client writes
  are enabled.
- A stale device cannot overwrite a newer change.
- A retried mutation produces one event.
- No automated test can reach production SharePoint.
- Actual empty production-list definitions match the executable manifest before data writes begin.

### Live-creation gate

Create the two empty final lists only after the owner approves the offline manifest, updates the
delegated permissions, and the read-only inspection confirms that neither permanent name is already
occupied. The provisioner records validated list GUIDs in non-secret cloud configuration. Client
writes remain feature-gated until repository and concurrency tests pass.

## Phase 3 — Vehicle record and active-backlog desktop slice

### Scope

1. Resolve Entra roles into capabilities.
2. Create/update one operations projection when a Builder individual vehicle is saved. The current
   implementation automatically upserts the narrow Builder-owned projection and preserves every
   Operations-owned field. Explicit single/sequential creation remains a legacy import fallback.
3. Add Started, Active, and Completed Operations tabs. Inactive projects retain Operations history
   but remain hidden until reactivated; their archive remains available in Projects.
4. Show Not Accepted / Partially Accepted / Accepted only on Active project cards.
5. Add authorized project/vehicle status entry, including vehicle availability and optional
   business-effective date. This is implemented; history display remains a later slice.
6. Show the derived Commitment Start and Must Deliver By dates.
7. Add the small scheduling fields and filtered backlog/week views. The schedule form and Active
   **All / Unscheduled / Scheduled** subfilters are implemented; Scheduled sorts by week and a
   dedicated week board remains optional.
8. Reject unauthorized or stale mutations.

Accepted vehicles without a scheduled week automatically appear as Unscheduled; setting a week
makes them Scheduled. Ready to Build is derived from existing facts and shown as a summary, with a
reasoned manager override. No automatic schedule cascading ships in this slice.

### Exit criteria

- Saving a vehicle updates the same operations row by opaque vehicle ID after names change.
- Deleting a project removes its exact Operations rows/history first; a failed cascade blocks the
  Builder deletion. Delivering every current vehicle automatically completes the project.
- Prospective vehicles remain visible in Builder without cluttering the accepted shop queue.
- Vehicle availability can be entered later with its true earlier effective date.
- The 60-day rule is reproducible and internal delays do not move Must Deliver By.
- The three project tabs and Active acceptance badges work without repurposing `confirmed`.
- Direct API calls cannot bypass role checks.
- UI remains responsive during slow/offline Graph calls.

## Phase 4 — Production workstreams

Start with one end-to-end Build / Shop vertical:

1. List accepted active vehicles in the allowed workspace.
2. Open one vehicle.
3. Start and complete Build / Shop.
4. Show actor/time history and duration. The full event timeline is implemented; derived duration
   summaries remain.
5. Prove the same action through the shared shop account with optional technician selection.

### Exit criteria

- The end-to-end flow works on two workstations against the test list.
- Direct API calls cannot bypass role checks.
- UI remains responsive during slow/offline Graph calls.
- Relevant route, service, and UI smoke coverage exists.

Then add Parts, Tray, Programming & QC, Final Finish, and delivery one bounded slice at a time. Do
not add palletization, Paused/Blocked, a general operations note, or a manually maintained master
Production Status.

## Phase 5 — QBO observation and existing-Estimate link

Working-tree status: paste-ID/URL connection, one-Estimate-per-vehicle guard, shared observation,
24-hour stale display, accepted-state latch, manual-acceptance preservation, and the separate
guarded Update action are implemented. Search/selection and background refresh remain deferred.

### Deliverables

- Explicit Link Existing Estimate search/selection.
- Duplicate-link guard by Builder vehicle ID.
- Shared read-only observation fields and visible freshness.
- Acceptance latch from an observed accepted Estimate.
- Manual-acceptance reconciliation when an Estimate is linked later.
- preserved Estimate-link history when Create New is used.
- existing pre-write QBO difference gate extended, not replaced.

### Exit criteria

- QBO refresh cannot mutate Builder-authored project/draft fields.
- Non-QBO users see the last known status and check time from SharePoint.
- The UI warns when the shared observation is at least 24 hours old.
- Linking never overwrites manual acceptance; QBO adds confirmation or a visible mismatch.
- QBO and Builder concurrent changes block publication.
- No token or raw financial response is written to SharePoint.

## Phase 6 — Minimal phone client

### Scope

- searchable/filterable accepted active vehicles;
- vehicle detail;
- role-appropriate status actions;
- optional technician-name selection when the authenticated account is shared, prominently offered
  for the important Ready for Delivery action and future issue/comment entries;
- timeline and freshness;
- links to current shop PDF and photos;
- explicit offline/error feedback.

### Constraints

- SharePoint standard connector only; no Dataverse or premium connector.
- No QBO, project/build editing, catalog administration, or offline write queue.
- One simple responsive interaction model; avoid deep Canvas navigation.
- Prefer one responsive screen plus a reusable detail component, eliminating ordinary Back wiring.
- AI/code assistance may generate Power Fx and pasteable control YAML, but Power Apps Studio remains
  the supported assembly and verification surface.
- Prove paired current/event mutation or event-request projection before production rollout.

## Phase 7 — Reporting, pilot, and workflow guides

### Reports

- milestone timeline per vehicle;
- queue/cycle durations;
- stale QBO observation indicator;
- active accepted work by current step;
- aging Parts and Programming & QC queues.

### Workflow guides

Create illustrated, task-oriented references for:

- Builder/Sales;
- Parts;
- Shop;
- Programming & QC;
- Operations Manager;
- Administrator.

Write final guides after pilot feedback so they describe the shipped interface. Version them with
the app and retain one master lifecycle diagram.

## Phase 8 — Bay and team assignments (after the scheduling pilot)

- Add an owner-reviewed bay roster using durable neutral IDs, current vehicle occupancy, and dated
  move/reassignment events. Preserve historical labels when a bay is renamed.
- Add an owner-reviewed team/person roster using durable neutral IDs. Start with display-name data
  where workers do not yet have individual Microsoft accounts and allow a later optional Entra
  object-ID link without migrating assignment history.
- Support a project-level team assignment with a per-vehicle override and an explicit unassigned
  state. Project-wide changes remain one revision-checked vehicle event at a time.
- Do not create permanent SharePoint fields or lists until the real bay names and first team
  structure are known. Do not add automatic bay optimization or labor scheduling in this phase.

## Rollout and rollback

- Pilot against the empty final SharePoint lists with client writes limited to a small role-assigned
  group.
- Import no historical production data until schema and behavior pass.
- Keep Builder operations features behind an explicit configuration flag during pilot.
- Retain the SharePoint list UI as an administrative recovery surface.
- Rollback disables client writes without deleting current rows or events.
- Never destroy an event to correct history; append a correction.
- Retain the full event history indefinitely; any future archive must be lossless and readable.

## Current open decisions

1. Direct phone paired write versus append-only request + SharePoint flow projection.
