# Next Feature Plan — Vehicle Workflow and Picker Improvements

**Planning date:** 2026-08-18; status refreshed 2026-08-26

**Status:** v3.4.0 shipped Phases 1, 2, 4, the Phase 3B naming change, and the core Phase 5 workflow.
Phase 3A is deferred and excluded from production. Phase 3C/3D plus the Phase 5 cloud
publication/retry boundary remain follow-up work.

**Rule:** preserve `individual_id` as the durable vehicle identity. Unit numbers, generated labels,
QuickBooks Project names, and SharePoint folder names are mutable display data and must never be the
only link between a vehicle and its draft, outputs, Estimate, or finalization state.

## Goals in this plan

1. Make guided-system component choices explicitly optional where the relationship permits it.
2. Replace New/Used/Reused with New or Customer supplied, with Customer supplied subdivided into
   New and Used and a required source for Used.
3. Add multi-location quantity allocation for 3-inch round lights.
4. Remove the agency prefix from generated QBO Project names and migrate stored names safely.
5. Visually identify siren speakers mounted behind a grille or OEM bumper.
6. Assign the correct alternating/side assets to grouped custom DUO placements.
7. Add vehicle finalization, collaborator-visible status, guarded reopening, and an extensible
   warning-only final-check engine.
8. Move generated files into per-vehicle SharePoint folders beneath a newly created
   `Vehicle Project Database` root, provision an empty `Reference Photos & Videos` folder, and
   publish a PDF-only copy to the Shop Documents library while the vehicle is finalized.
9. *(Deferred; not on the active production roadmap.)* Replace per-workstation QuickBooks
   authorization with one owner-authorized company connection in a protected backend, while
   employees authenticate only with their Microsoft 365 identities.

## Cross-cutting design decisions

- Additive schema migrations come before UI changes. Old drafts/projects must continue to load.
- Picker state describes user intent; `ProjectInput` and `BuildPlan` carry normalized meaning;
  preview and PowerPoint consume the same plan instead of independently inferring behavior.
- Product-specific picker capability is authored in `parts_db.json` and validated by the config
  schema. Do not detect a feature by matching a product name in JavaScript.
- Final-check rules live in the domain/rules layer with stable rule IDs. Event handlers and
  renderers only present their results.
- Cloud migrations are explicit, idempotent, dry-runnable, collision-aware, and produce a report.
  They must not be silently mixed into application startup.
- SharePoint work must be tested intentionally with cloud enabled; normal development remains
  cloud-off so the settings mirror cannot replace local catalog edits.

## Phase 0 — protected baseline (completed before v3.4.0)

The release work used this baseline sequence:

1. Reviewed and committed quantity-aware custom placement as an isolated change.
2. Preserved unrelated documentation and scratch-work changes already in the worktree.
3. Ran the targeted planner/routes tests and 28-flow UI smoke suite, then recorded the commit
   and verification baseline in `CURRENT_STATE.md`.
4. Updated golden masters only for intentional, reviewed plan/render changes with focused coverage.

## Phase 1 — data vocabulary and low-risk picker behavior

### 1A. Optional guided-system components

**Shipped in v3.4.0.** The guided-step contract now distinguishes
an explicit optional choice (`required: false`) from a dependency-controlled step
(`required_when`). The audit kept core radio components required, retained camera's explicit
component multi-select, and confirmed the console flow already exposes clear None choices and
dependency checks. Radar is the relationship that was genuinely over-constrained: its rear antenna
can now be deliberately saved as **Not included** for a front-only system, and the rear-bracket step
then does not apply. Browser coverage verifies included and omitted paths, edit round-trip, manifest
components, and absence of a phantom draft/Estimate line.

The existing guided framework already supports optional console choices in places, but requiredness
is inconsistent and sometimes implicit. Add an explicit step contract:

- `required: false` means the step offers a clear **None / Not included** choice.
- `required_when` expresses real dependencies, such as a pedestal being required only after a
  pedestal motion choice.
- Identity/core selections that are necessary to resolve a real SKU may remain required.
- Audit every radio, radar, camera, and console step; do not make all steps optional wholesale.
- Console kit resolution receives only selected components that affect what DTM must order. A
  missing optional motion attachment must not block completion.

Acceptance: every optional step can be deliberately cleared, saved, reopened, and estimated without
a phantom component; dependency-driven required steps still prevent an invalid SKU resolution.

### 1B. Canonical part-supply model

**Shipped in v3.4.0.** The
canonical fields now flow through drafts, inputs, presets (schema v4), Excel compatibility,
picker/guided editors, planning, manifests, PowerPoint, and Estimate preparation. Legacy records
normalize on read without forcing a startup write; source-less legacy Used/Reused records remain
readable as **Source needed** but cannot be edited again without a source. Parent and component
supply states round-trip independently, including inherited guided-component state. Catalog review
confirmed that Gamber-Johnson `console_kit.included` lists items DTM must order rather than physical
fit geometry, so both Customer supplied / New and Customer supplied / Used components are excluded
from main-console bundle resolution. A PDF-scale review shows the new red callouts cleanly. The
intentional PowerPoint golden changes were reviewed, re-recorded, and pass with focused renderer
coverage.

Add structured fields to draft/input component records while retaining legacy read compatibility:

```text
supply_type:          "new" | "customer_supplied"
customer_condition:   "" | "new" | "used"
customer_source:      string
```

Rules:

- **New** means supplied/billed by DTM and is included on the quote.
- **Customer supplied / New** and **Customer supplied / Used** are not quoted.
- Customer supplied / Used requires `customer_source` before the picker/guided editor can save.
- The condition is available on a parent part and on every individually selectable guided
  component. For center-console resolution, Customer supplied / Used replaces the old Reused
  behavior and does not influence the ordered main-console SKU. Customer supplied / New is still an
  installed component and may need to influence fit/cutout selection even though it is not quoted;
  confirm that resolver rule against the actual Gamber-Johnson SKU logic during implementation.
- Keep `comment` as the user-authored part note. Do not render machine-oriented `notes` as a user
  note. In the UI and PPTX manifest, comments and customer-used source callouts use a red-highlighted,
  slightly larger treatment. The visual build sheet part annotation should use the same callout
  treatment where notes are shown.

Migration mapping for existing records:

| Legacy value | New value |
|---|---|
| New or blank | New |
| Used | Customer supplied / Used |
| Reused | Customer supplied / Used |

Preserve the legacy `source` as `customer_source`. Records migrated from Used/Reused without a
source remain readable and visibly flagged **Source needed**; require the source only on their next
edit, not merely on application startup. Write the new structured fields and, during one compatibility
window, continue emitting legacy values for old consumers and spreadsheet imports.

Acceptance: UI round-trip, draft migration, Excel adapter compatibility, manifest/PPTX visibility,
Estimate exclusion, preset round-trip, guided child conditions, and console SKU resolution all have
tests. A rendered review artifact must verify red callouts at normal print/PDF scale.

## Phase 2 — picker efficiency and grouped light rendering

### 2A. Multi-location allocation for 3-inch round lights

**Shipped in v3.4.0.** The data capability, multi-location quantity UI, atomic batch replace
endpoint, non-3-inch product split, per-location notes, safe deletion/edit round-trip, and focused
service/browser coverage are live.

Add a validated product capability such as `picker_location_allocation: true` to the actual 3-inch
round-light product family. First separate any non-3-inch SKU currently grouped under that product.

The picker shows a location multi-select. Each selected location gets the existing quantity control;
the sum is the total being added. Saving creates one normal `DraftPart` parent per location, sharing
a stable `picker_config.location_batch_id`. This avoids a list-valued `location` field and lets the
planner, renderer, manifest, and Estimate path keep their existing one-line/one-location semantics.
Editing any member reopens the batch, updates all allocations atomically, and deletes zero-quantity
members.

Acceptance: allocate 5 heads across 3 locations, edit the allocation, save/reopen, render all five,
and quote the correct total without requiring three full picker runs.

### 2B. DUO assets in grouped custom placement

**Shipped in v3.4.0.** Equal rows and the four-head **Two per side (mirrored)** mode
persist ordered indices/group IDs and resolve DUO/custom colors per head. Browser smoke covers pair
symmetry, spacing, movement, persistence, and edit round-trip.

Persist each generated custom anchor's `head_index` (and group ID) instead of treating every point as
an unrelated neutral-center placement. The planner resolves slot role from ordered index and group
size using the shared geometry/role functions. For a standard red/blue split, left/driver heads use
the red-side asset and right/passenger heads use the blue-side asset. Per-head custom configurations
use the asset selected for that index.

Old custom points without an index retain the v3.3.5 neutral fallback. Add planner tests for two- and
four-head DUO groups plus a browser smoke that verifies the preview asset sequence and edit round trip.

## Phase 3 — shared identity, centralized QuickBooks, names, and cloud folders

These changes share the durable vehicle identity boundary: `individual_id` identifies the vehicle,
while unit numbers, generated labels, QBO names, and folder names remain mutable display data.
Microsoft Entra ID identifies the employee for collaboration. Production QBO authorization remains
per-workstation with tokens in that user's OS keychain; the server-held company connection below is
a deferred alternative, not the deployed architecture.

### 3A. Centralized QuickBooks company connection

**Deferred by owner (2026-08-20).** Keep the local implementation default-off and do not register,
configure, deploy, authorize, migrate tokens, or continue the cutover until the owner explicitly
resumes this phase. The existing production per-user/keychain QuickBooks path remains active. The
complete but excluded experiment is preserved only on local branch
`codex/central-qb-backend-wip` at `f5ac223`; do not merge or delete it without that explicit decision.

Replace the current per-workstation QBO refresh-token model with an authenticated backend. The owner
authorizes the DTM QuickBooks company once using the existing Intuit production app and an admin QBO
account. The backend stores that company's latest rotating refresh token in an encrypted server-side
secret store and makes all QBO API calls. No desktop receives the Intuit client secret, access token,
or refresh token.

Employees sign in only through the existing Microsoft 365/Entra tenant. The desktop obtains an access
token whose audience is the new Builder API, and the backend validates signature, audience, tenant,
expiry, and employee authorization. A Microsoft Graph token must not be reused as a Builder-API token.
Use Entra groups/app roles, initially:

- **Builder User:** catalog reads, validation, Estimate preparation/creation, and normal project
  binding operations exposed by the app.
- **Builder Admin:** everything above plus QBO reconnect/disconnect, connection health details,
  migrations, catalog-link governance, and other sensitive maintenance operations.

Only the owner/admin completes Intuit consent or reconnection. Normal users see **QuickBooks managed
by DTM** and connection health; they never see a Connect button or an Intuit login prompt.

This removes employee QBO login from operations performed inside Vehicle Builder. It does not grant
the current Accounting API permission to create or rename true QBO Projects. Until the app gains the
restricted Projects API scope, those manual QBO UI tasks still require an employee's own QBO account
or must be assigned to the owner/admin.

The backend must expose narrow task endpoints, not an arbitrary QBO proxy. Move the existing item and
customer reads, reconciliation, Customer writes, Estimate validation/create/update, PDF attachment,
and connection health behind those endpoints. Preserve the existing rule that Estimates are
non-posting and that Estimate creation and attachment are separate writes.

Token refresh is single-writer and concurrency-safe. Intuit periodically rotates refresh-token values,
so the service must lock per realm, persist the newest token atomically before releasing the lock,
retry an API request at most once after refresh, and never let two desktop clients refresh independent
copies. Encrypt credentials at rest with a managed key service; never store them in SharePoint,
desktop config, logs, or the application database as plaintext.

Because QBO attributes third-party API writes generically, keep an append-only Builder audit record
for every sensitive operation: Microsoft tenant/user object ID, app action, project/vehicle ID, QBO
entity type/ID, timestamp, outcome, and correlation ID—never tokens or raw customer payloads.

The owner selected a narrow Entra-protected API on the existing DTM Netlify site, avoiding another
provider and an Azure consumption resource. The default-off adapter must provide the same security
properties: Entra token validation, application-encrypted durable token storage, atomic refresh
locking, audit retention, backup/recovery, monitoring, and access controls. The currently deployed
stateless `qb-token` relay remains insufficient by itself. Netlify Free-plan exhaustion is a hard
availability stop, so the desktop must recognize the platform pause response and give explicit
Admin recovery guidance without echoing the response body.

Cutover sequence:

1. Register the Builder API audience, user/admin roles, redirect URI, and production secrets.
2. Deploy read-only connection health and catalog endpoints; complete owner QBO authorization once.
3. Run old-vs-new read-only comparison for company, Items, Customers, prices, and prepared Estimate
   payloads without creating transactions.
4. Enable one guarded production Estimate through the backend and review it in QBO.
5. Switch all desktop QBO routes to the backend, then remove non-admin connection controls.
6. After every supported workstation is upgraded and central health is verified, delete obsolete
   local QBO token blobs. Do not have each workstation call Intuit revoke, because revocation could
   disconnect the shared company authorization.
7. Retain an owner-only emergency reconnect flow and documented recovery procedure for token expiry,
   owner revocation, backend outage, and key-store recovery.

Acceptance: two or more employees can concurrently use QBO-backed features using only M365 sign-in;
no refresh race or admin prompt occurs; unauthorized tenant/users receive 401/403; roles are enforced
server-side; each Estimate is attributable in the Builder audit; secrets never reach the desktop or
logs; and backend unavailability fails closed without falling back to stale local credentials.

### 3B. Generated QuickBooks Project names

**Generated/copied naming shipped in v3.4.0.** The stored-name audit/migration and manual QBO rename
checklist below remain open.

The shared formatter now generates/copies names as:

- `Unit {unit number} | Build {year}` when known.
- `{build type} #{ordinal} | Build {year}` when unknown.

Do not include agency because QBO already presents the parent Customer. Keep `individual_id`,
`qb_project_id`, Estimate IDs, and output paths unchanged when the display name changes.

The guarded migration command/service remains follow-up work. It should scan every shared project, preview old/new names,
backs up changed records, updates only generated-format `qb_project_name` values, mirrors changes to
SharePoint, and reports custom or incomplete names it cannot safely rewrite.

Current API limitation: the app cannot list or rename real QBO Projects with its approved Accounting
scope. Therefore the migration can update Builder's stored/copied name, but existing QBO Project
display names must be renamed manually in QBO. The migration report must list their customer,
vehicle, QBO Project ID, old name, and desired name so that manual work is finite and auditable.

### 3C. SharePoint vehicle folders

**Not yet implemented.** v3.4.0 keeps customer PDFs in the visible agency/year tree and editable
PPTX sources under `_DTM Internal PowerPoint Sources`, with deterministic Replace filenames and
legacy duplicate cleanup. That shipped split is the current runtime behavior; the per-vehicle
hierarchy below is the next migration target and must begin with a dry run.

Create a completely new `Vehicle Project Database` folder item. Do not rename the existing
`Vehicle Builder Projects` folder: a fresh item prevents the active app path from inheriting the
old folder's identity or rename history.

Target hierarchy:

```text
Vehicle Project Database/
  {Agency}/
    {Build Year}/
      {Vehicle folder}/
        {vehicle}.pptx
        {vehicle}.pdf
        Reference Photos & Videos/
```

Use **Reference Photos & Videos** as the final single folder name.

Persist the SharePoint vehicle folder item ID (and current display name) on `IndividualUnit` once
provisioned. The item ID, not a reconstructed unit-number path, is the durable locator. Provision
folders asynchronously when vehicles are created and retry on first export; expose provisioning
status without freezing the UI.

Update upload, hydrate, replace/version cleanup, delete, list, PDF attachment, and **Show in
SharePoint** paths together. After cutover, normal app reads and writes use only the new root; the old
folder must not remain as a hidden runtime fallback that could split files between structures.

The migration first performs a dry-run, creates the new root, then **copies** uniquely matched
historical PPTX/PDF files into new per-vehicle folders. Copying creates clean destination items rather
than carrying the old folder identity forward. It validates destination hashes/sizes, updates project
records to the new file items, creates the empty reference folder, detects collisions, and reports
unmatched/orphan files. Never guess when two vehicles could claim the same historical filename.
Keep the old root untouched and outside the active app path until the owner reviews the migration
report and new structure; archiving or deleting it is a separate, explicitly approved cleanup.

### 3D. Finalized PDF publication for the shop

Add a second configured SharePoint destination for the **Shop Documents** library. Resolve and store
the library drive ID during setup instead of assuming its display name is its internal Graph name.
Use a parallel, PDF-only hierarchy:

```text
Shop Documents library/
  Vehicle Project Database/
    {Agency}/
      {Build Year}/
        {Vehicle folder}/
          {vehicle}.pdf
```

Do not place PPTX files or the reference-media folder in Shop Documents. The normal Company Files
destination remains the complete working record and may contain draft outputs. The shop destination
is a publication surface and contains only the PDF for a currently finalized vehicle.

Prepare the library configuration and upload/delete service in this phase, but trigger publication
through vehicle finalization in Phase 5. Store `shop_pdf_item_id`, the published finalization/content
fingerprint, path, and timestamp on `IndividualUnit` so replacement and withdrawal are exact and
idempotent.

Acceptance: create a multi-vehicle project on one workstation, observe every Company Files vehicle
folder and empty reference folder, export/replace both formats, hydrate on a second instance, attach
the PDF to an Estimate, and open the correct SharePoint folder. The Shop Documents path must remain
empty before finalization. Migration rollback instructions and the unmatched file report are required
before production execution.

## Phase 4 — concealed siren-speaker rendering

**Shipped in v3.4.0.** Preview and PowerPoint both use normalized concealment fields,
reduced opacity, and a compact red callout. The generated review PDF includes a behind-grille case.

Model concealment as normalized placement data, not a renderer string check. Extend the planned
placement with a value such as `mount_visibility = behind_grille | behind_oem_bumper | normal` and
an optional callout label. Both preview and PowerPoint consume it.

For concealed siren speakers, render the asset at reduced opacity and place a compact red callout
(`BEHIND GRILLE` or `BEHIND OEM BUMPER`) adjacent to it. Preserve the existing `behind_vehicle`
z-order behavior, but do not rely on z-order alone because a fully hidden asset communicates nothing.
If PowerPoint opacity requires an XML alpha transform, isolate that implementation in one tested PPT
helper rather than spreading XML manipulation through the renderer.

Acceptance: visual review on each vehicle/view where those locations exist, preview/PPTX parity, and
no opacity change for normal speaker locations.

## Phase 5 — vehicle finalization MVP

**Core workflow shipped in v3.4.0.** Durable status/audit fields, current-PDF and
fingerprint checks, equipment relationship/coverage warnings with required acknowledgement notes,
a focused final-review UI with expandable passed checks, server-side edit locks, and reasoned
reopening are live. The SharePoint Shop Documents
publication/withdrawal and retry state described below remain follow-up before Phase 5 is complete;
so do automatic stale-draft reopening and explicit concurrent stale-finalization rejection.

### Durable state

Store finalization on each `IndividualUnit`, not on the fleet group or draft alone:

```text
status: draft | finalized | reopened
finalized_at / finalized_by
draft_revision or content fingerprint checked
check_version
acknowledgements: [{rule_id, note}]
reopened_at / reopened_by / reopen_reason
```

Every project card shows the shared status, user, and timestamp. If the draft changes after the saved
revision/fingerprint, the vehicle automatically becomes **Reopened** so another user never sees stale
"finished" state.

### Guarded editing

Opening an editor for a finalized vehicle displays a warning dialog. Continuing records who reopened
it and why, then changes the state to Reopened. Enforce this acknowledgement at the service/API layer
as well as the UI so a second client or stale tab cannot silently modify a finalized vehicle. The
feature is a collaboration guard, not an irreversible lock.

Reopening a finalized vehicle also withdraws its published Shop Documents PDF. The finalized state
changes server-side before the delete is attempted, so the UI cannot continue representing the shop
copy as current. If SharePoint is temporarily unavailable, record a `withdrawal_pending` publication
state, show the sync problem to the user, and retry; do not silently leave a stale PDF presented as a
finished design.

### Extensible checks

Extend the existing rules engine with a finalization ruleset and stable IDs. Each result includes
tier, warning text, evidence, suggested fix, and bypassability. Finalization evaluates the saved
draft server-side. Warnings never hard-block the design, but every bypassed warning requires a note
that is stored with the finalization record and shown to collaborators.

The shipped rule set now checks the controller/interface relationship (including ScanPort/CanPort
for Core), photo eye when there is no roof bar, docking-station motion attachment, radio, camera,
expansion module, Patrol radar and front/rear partitions, and front/side/rear warning coverage. It
also warns when both roof and interior light bars are absent. Keep adding relationship rules as
small, individually tested domain changes; finalization must always re-evaluate the completed design
because part-add accessory prompts only see an interim state.

After the user resolves or acknowledges the warnings, finalization ensures the working PDF matches
the exact finalized draft revision, visibly generates it when stale or missing, then uploads/replaces
the PDF in the Shop Documents vehicle folder. Mark finalization successful even if the design state
was saved but publication fails; expose a clear **Finalized — shop PDF pending** state and a retry
action rather than rolling back or duplicating the finalized record.

Acceptance: finalize clean build; finalize with acknowledged warnings and required notes; another
user sees status; a matching PDF appears in Shop Documents; edit requires acknowledgement; edit marks
Reopened and withdraws that PDF; refinalize runs the current rule version and republishes; concurrent
stale requests cannot overwrite the newer status. Publication failure/retry and withdrawal failure/
retry are required test cases.

## Delivery order and release gates

Current delivery state and next gates:

1. **Shipped in v3.4.0:** placement grouping/DUO roles, guided optionality, canonical supply,
   multi-location round lights, concealed speakers, generated QBO naming, and finalization core.
2. **Next:** complete the finalization cloud boundary—Shop Documents publication/withdrawal,
   durable retry states, and explicit stale concurrent-finalization rejection.
3. **Then:** dry-run and review the per-vehicle SharePoint folder migration before any production
   copy or cutover; follow with the stored-name audit/manual QBO rename checklist.
4. **Deferred/out of production:** centralized QuickBooks. Do not make it a release dependency
   unless the owner explicitly resumes Phase 3A.

Every release runs the relevant focused tests, full `pytest`, golden and contract safety pins, and the
UI smoke suite. Any render-affecting release also produces reviewed PPTX/PDF samples. SharePoint and
QuickBooks migrations require an owner-reviewed dry-run report and backup before the write step.

## Known manual work after the automated migrations

- Only if Phase 3A is explicitly resumed, the owner/admin must complete one QBO authorization when
  the centralized backend is commissioned,
  and again only if Intuit authorization is revoked or expires beyond automatic recovery. Employees
  use Microsoft 365 sign-in only for Vehicle Builder operations.
- Anyone assigned to manually create or rename true Projects in the QBO website still needs their own
  QBO access until the app is eligible for the restricted Projects API; alternatively keep those
  manual tasks with the owner/admin.
- Rename pre-existing real QBO Project display names in QuickBooks; the current approved API scope
  cannot do that. The app can generate the exact old-to-new checklist.
- File any SharePoint output that cannot be mapped uniquely to a project vehicle. The migration must
  list these files and leave them untouched in the legacy root.
- Resolve legacy Used/Reused parts that have no recorded source when those lines are next edited.
- After the new root is verified and the unmatched-file report is resolved, decide whether to archive
  or delete the inactive `Vehicle Builder Projects` root. That cleanup is intentionally not automatic.
