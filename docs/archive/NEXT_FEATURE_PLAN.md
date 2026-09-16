# Next Feature Plan — Vehicle Workflow and Picker Improvements

**Planning date:** 2026-08-18; status refreshed 2026-09-03

**Status:** v3.4.0 shipped Phases 1, 2, 4, the Phase 3B naming change, and the core Phase 5 workflow.
Phase 3A is deferred and excluded from production. Phase 3C/3D and the Phase 5 cloud boundary are
shipped in v3.5.0 behind independent explicit cutover flags after live SharePoint package
verification and folder flattening.

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
8. Move PDFs into per-vehicle SharePoint folders beneath a newly created
   `Vehicle Project Database` root, keep year-level **Reference Photos & Videos**, and publish a
   PDF-plus-reference-photo package under Shop Documents / **Shop Project Database** while finalized.
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

**Post-release correction:** base-console selection and bundle recommendation are now separate.
The exact base SKU is never replaced by feature choices; a better bundle is an explicit suggestion.
Likewise, physical presence and billing are separate: every selected console component remains a
build row, while `console_kit_included` prevents only a duplicate Estimate charge. Older saved
console snapshots remain valid evidence for final-design equipment checks.

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

**Shipped in v3.5.0, superseding the v3.4.0 formatter.** One canonical visible identity now drives
unit cards, folders, PDF filenames, and generated/copied QBO names. The dry-run audit/report is
implemented; the report must be reviewed and existing true QBO Projects renamed manually before
cutover.

The shared formatter now generates/copies names as:

- visible/card/folder: `2027 SCPD PIU - Patrol - Unit 12 - VIN 123456`;
- QBO: `2027 SCPD PIU | Patrol | Unit 12 | VIN 123456`.

Names use the short vehicle model without the make. Police Interceptor Utility is always `PIU`,
F-150 Lightning is `Lightning`, and other labels use recognizable model names such as `Durango`,
`F-150`, `Traverse`, and `Tahoe`.

Actual/new-vehicle unit number and VIN-last-six are both included when known; either one alone satisfies new vehicle
identity. A vehicle without either cannot export/finalize. Existing incomplete records receive a
stable `Pending ID` label derived from `individual_id` so folders/cards are unique, then the same
folder item is renamed in place when a VIN arrives. Existing/replaced-vehicle year, make, model,
build type, unit, and VIN remain editable display metadata for the dedicated Existing Vehicle card;
they are never current identity fallbacks.

Include the compact Agency Abbreviation even though QBO also presents the parent Customer so copied
names remain self-identifying in exports and external lists. Keep `individual_id`,
`qb_project_id`, Estimate IDs, and output paths unchanged when the display name changes.

The read-only migration report now scans every local/shared project snapshot and previews old/new
names, missing identifiers, legacy output/folder moves, same-agency/year duplicates, and exact
manual QBO renames. An owner-approved mutating migration remains follow-up work: it must back up
changed records, update only generated-format stored names, mirror deliberately to SharePoint, and
report custom or incomplete names it cannot safely rewrite.

Current API limitation: the app cannot list or rename real QBO Projects with its approved Accounting
scope. Therefore the migration can update Builder's stored/copied name, but existing QBO Project
display names must be renamed manually in QBO. The migration report must list their customer,
vehicle, QBO Project ID, old name, and desired name so that manual work is finite and auditable.

### 3C. SharePoint vehicle folders

**Shipped and activated in v3.5.0.** The two approved roots and all current project trees were
provisioned and reconciled in place to the abbreviation-qualified naming convention before
per-vehicle Company PDF publication was enabled. New PDFs now write exclusively to the per-vehicle
tree; there is no dual write to the legacy agency/year export root. The approved detailed product contract is
[BUILD_REFERENCE_PHOTOS.md](BUILD_REFERENCE_PHOTOS.md).

One project means one agency build year. Enforce `agency_id + normalized build_year` for new
records and open/extend the existing project instead of creating a duplicate. Existing duplicates
require a dry-run merge report; never guess across drafts, vehicles, notes, QuickBooks links, or
finalization state.

Folder provisioning is independently gated from PDF cutover. With
`company_folder_provisioning_enabled` / `shop_folder_provisioning_enabled`, project save creates the
two agency roots plus its year/reference folders, and every known vehicle
creates its durable item-ID subtree. Missing identifiers use a stable `Pending ID` suffix until a
unit number or VIN arrives. This allows additive construction and migration copying
before the app's active Company/Shop PDF paths are switched.

Agency Manager and QBO Customer import are not provisioning boundaries. Only a saved vehicle
project can create/retry roots. Legacy Build Photos agencies enter this scope through ordinary
completed agency/year projects created by the reviewed migration.

Create a completely new `Vehicle Project Database` folder item. Do not rename the existing
`Vehicle Builder Projects` folder: a fresh item prevents the active app path from inheriting the
old folder's identity or rename history.

Target hierarchy:

```text
Vehicle Project Database/
  {Agency}/
    {Agency Abbreviation} - {Build Year}/
      Reference Photos & Videos/
      {Canonical Vehicle Name}/
        {Canonical Vehicle Name}.pdf
```

Do not upload new PPTX files after cutover. The app project/draft is the editable source and PPTX is
an internal local conversion artifact. Videos remain Company Files only.

Persist the SharePoint vehicle folder item ID (and current display name) on `IndividualUnit` once
provisioned. The item ID, not a reconstructed unit-number path, is the durable locator. Provision
folders asynchronously when vehicles are created and retry on first export; expose provisioning
status without freezing the UI. Reconciliation resolves that ID to its current Graph parent/path
before moving it directly beneath the canonical year, so an out-of-band SharePoint move or a model
edit cannot strand photos behind a stale saved path.

Update upload, hydrate, replace/version cleanup, delete, list, PDF attachment, and **Show in
SharePoint** paths together. After cutover, normal app reads and writes use only the new root; the old
folder must not remain as a hidden runtime fallback that could split files between structures.

Past Shop photo archives map to ordinary projects for their actual agency/build year, with only the
known vehicle model, optional build type/unit/VIN, and photos—no invented draft, PDF, finalization,
QBO state, record kind, or label. After the copied photos are verified, the project is marked
completed and becomes browseable in Project Archives. Ambiguous source folders remain unmatched for
manual review rather than receiving an invented name.

The completed live migration inventory is 28 agency folders, 46 source build/photo groups, and
1,043 files. Forty-five dated groups consolidate to 34 projects across 27 confidently matched saved
agencies. The approved **Benton-Stearns Negotiator Van** (`BSNV`) 2025 project brings the total to
35 completed projects. All 1,043 files were copied into their normal Completed Build Photos
destinations and independently verified by relative path and size; source and destination both
total 11,934,028,588 bytes. The legacy source remains untouched.

The migration first performs a dry-run, creates the new root, then **copies** uniquely matched
historical PDFs and photos into new per-vehicle folders. PPTX files stay out of the new visible
trees. Copying creates clean destination items rather
than carrying the old folder identity forward. It validates destination hashes/sizes, updates project
records to the new file items, detects collisions, and reports unmatched/orphan files. Never guess
when two vehicles could claim the same historical filename.
Keep the old root untouched and outside the active app path until the owner reviews the migration
report and new structure; archiving or deleting it is a separate, explicitly approved cleanup.
Existing Shop build photos use the same copy-first rule: inventory, reviewed historical-record
mapping, copy, count/size/hash validation, app-path cutover, app verification, and only then a
separately approved old-location archive/delete. No migration step moves the source in place.

### 3D. Finalized PDF publication for the shop

**Shipped and activated in v3.5.0.** Publication/withdrawal, exact owned-item IDs, retry
state, folder relocation, and Completed Build Photos preservation are active behind the explicit
`shop_publication_enabled` gate. The first live package was uploaded and hash-verified before the
gate was recorded as the production default.

Add a second configured SharePoint destination for the **Shop Documents** library. Resolve and store
the library drive ID during setup instead of assuming its display name is its internal Graph name.
Create a **Shop Project Database** root and add a folder for every physical vehicle. The existing
**Build Photos** tree remains the read-only migration source until copied data and app cutover are
verified:

```text
Shop Documents library/
  Shop Project Database/
    {Agency}/
      {Agency Abbreviation} - {Build Year}/
        {Canonical Vehicle Name}/
          {Canonical Vehicle Name}.pdf
          Build Reference Photos/
          Completed Build Photos/
```

Do not place PPTX files or videos in Shop Documents. Finalization publishes the PDF and the effective
unit-group reference photos, while continuing to honor legacy project/individual assignments. The app owns its PDF and published **Build Reference
Photos**, but must never modify or delete **Completed Build Photos**.

The post-migration browser now treats photos as galleries rather than filenames. Reference galleries
are populated immediately from saved project assignments. The exact year-level Company **Reference
Photos & Videos** folder is the project's physical unassigned-photo inbox: when that project opens,
JPG/PNG files added through OneDrive or SharePoint are reconciled into project metadata. Videos stay
Company-only. Completed galleries enumerate only the
project's exact stored vehicle folders on a background worker, prefer an exact locally synced
OneDrive folder when available, and otherwise use Graph. Normalized thumbnails are cached locally
and in Company Files `Settings/_DTM Photo Thumbnail Cache/v2` by source identity/eTag, so another
workstation can download the small shared JPEG; the full-resolution file is hydrated only when the user
opens it and is then retained in the app's local exact-media cache. Project Overview and Project Archives expose project reference/completed galleries;
unit-group headers own reference controls, while vehicle cards expose only conditional completed-
photo viewing plus exact-folder navigation. The direct completed-gallery action is shown only after
a scan finds a supported image in the applicable exact completed-photo folder. The last authoritative
presence result is cached locally for immediate project rendering while a background refresh checks
the folder; completed and
design-finalized states alone do not reveal it. The broad same-agency reuse browser also
uses a persistent inventory cache and background refresh instead of blocking the local server on a
full recursive walk.

Thumbnail work uses two tiers. Four background workers prepare persistent small display previews,
and six foreground workers promote the photos currently on screen; three separate workers perform
exact-source normalization and shared-cache publication only after a visible card requests its
upgrade. App startup compares a persisted fingerprint of saved project-photo metadata and skips
preparation entirely when unchanged; it never recursively scans every completed-photo folder. The
project currently being viewed receives the external-folder refresh, and the upper-right connection pill
shows checking or display-ready progress with a progress bar. A cache miss therefore becomes a fast
preview, `Preparing`, or an explicit Retry state—never a permanent spinner. Exact, source-versioned
thumbnails replace previews when available. Failed previews complete the batch and retry on demand;
closing the app cancels queued work rather than waiting for the whole inventory. Full-resolution
viewing uses a separate high-priority job: new thumbnail network work yields, the viewer and connection
pill report the active download, the browser polls a short preparing response, and success persists the
exact original locally. Its backend wait is bounded at 18 seconds and its viewer budget at 22 seconds.

Portrait thumbnails preserve the full image with side letterboxing and regenerate from exact source
bytes in a versioned cache. Completed galleries use thumbnail multi-select plus one disabled-until-
selected **Use as Reference Photo(s)** action. Its compact dialog chooses a destination project and
optional unit group; project-only reuse creates an unassigned project photo and a group selection
assigns directly. The full-resolution viewer is view-only. One selectable **Project photos** gallery
shows assigned/unassigned state and notes, adds more photos, assigns selected photos to a unit group,
and removes selected metadata without deleting source media. The source browser overlays
**Completed** on Shop photos, uses the canonical vehicle name instead of folder paths, and can browse
every app agency while defaulting to the current agency, vehicle make/model, and build type. Empty
galleries show one centered Add action.
Project completion now presents a confirmation warning before archive placement.

Prepare the library configuration and upload/delete service in this phase, but trigger publication
through vehicle finalization in Phase 5. Store `shop_pdf_item_id`, the published finalization/content
fingerprint, path, and timestamp on `IndividualUnit` so replacement and withdrawal are exact and
idempotent.

Acceptance: create a multi-vehicle project on one workstation, add reusable project photos,
assign them to unit groups, export/replace the PDF, hydrate on a second instance, attach the PDF to
an Estimate, and open the correct SharePoint folder. Reopen/retry must preserve completed photos.
Migration rollback instructions and the unmatched-file report are required before production
execution.

## Phase 4 — concealed siren-speaker rendering

**Shipped in v3.4.0; presentation tuning shipped in v3.5.0.** Preview and
PowerPoint both use normalized concealment fields, 80% concealed-asset opacity, and a compact,
70%-opaque red `SPEAKER BEHIND ...` callout sized to its text. The generated review PDF includes a
behind-grille case. Post-release PDF legibility work also makes render-card support text black,
raises manifest body text to at least 9 pt while compacting customer-supplied status into two lines,
and moves 10-point reference-photo notes into a high-contrast overlay so the photos render larger.
The callout itself is now draggable in Build Preview, persists relative-image X/Y offsets, and draws
a red leader to the nearest speaker instance in preview and PDF. Manifest categories share pages
behind high-contrast section bars; a pagination guard carries a section to the next page when its
first item would not fit beneath the heading.

Model concealment as normalized placement data, not a renderer string check. Extend the planned
placement with a value such as `mount_visibility = behind_grille | behind_oem_bumper | normal` and
an optional callout label. Both preview and PowerPoint consume it.

For concealed siren speakers, render the asset at reduced opacity and place a compact red callout
(`SPEAKER BEHIND GRILLE` or `SPEAKER BEHIND OEM BUMPER`) adjacent to it. The callout can be moved
independently of the speaker placement; connect it to the nearest speaker with a red leader.
Preserve the existing `behind_vehicle` z-order behavior, but do not rely on z-order alone because a
fully hidden asset communicates nothing.
If PowerPoint opacity requires an XML alpha transform, isolate that implementation in one tested PPT
helper rather than spreading XML manipulation through the renderer.

Acceptance: visual review on each vehicle/view where those locations exist, preview/PPTX parity,
saved callout-position round trip, nearest-speaker leader selection, and no opacity change for normal
speaker locations.

## Phase 5 — vehicle finalization MVP

**Core workflow shipped in v3.4.0; cloud-boundary extension shipped in v3.5.0.** Durable status/audit fields, current-PDF and
fingerprint checks, equipment relationship/coverage warnings with required acknowledgement notes,
a focused final-review UI with expandable passed checks, server-side edit locks, and reasoned
reopening are live. v3.5.0 adds SharePoint Shop Documents
publication/withdrawal, exact owned-item IDs, durable retry state, and pre-cutover finalized-build
catch-up behind an explicit enabled flag. Automatic stale-draft reopening and explicit concurrent
stale-finalization rejection are still follow-up work.

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
2. **Shipped and activated in v3.5.0:** canonical unit-card/folder/PDF/QBO naming,
   reference-photo assignment/output, Company vehicle folders, and Shop publication/withdrawal with
   durable retry state. Progressive agency/project/vehicle provisioning, exact photo-folder open
   actions, sparse past projects, and the completed-project archive tree are also implemented.
   PDF publication/cutover remains independently controllable, but all four lifecycle/publication
   gates are enabled after the approved folder run and live package verification. Cloud-off tests
   and representative output review pass.
3. **Completed additive migration:** the historical-photo inventory, reviewed mapping, 35 completed
   projects, 46 folder trees, and all 1,043 photo copies are live and verified. The next cloud gate
   was the owner-approved Company PDF and Shop publication activation. Follow the manual QBO rename
   checklist before those accounting names are treated as complete.
   Explicit stale concurrent-finalization rejection remains a separate workflow hardening item.
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
