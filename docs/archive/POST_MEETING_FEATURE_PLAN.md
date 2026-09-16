# Post-meeting feature plan

**Date:** 2026-09-10. **Status:** feature direction accepted by the owner, with the full shared HTML app and explicit Estimate statuses clarified below. Azure is the preferred pilot candidate if affordable; production host selection remains open. No deployment or production repair has been performed.

This extends the unreleased [Calendar](CALENDAR.md), production Operations, per-vehicle
documents, and guarded [QuickBooks workflows](QUICKBOOKS.md). It does not replace them.

## Recommended delivery order

| Batch | Result | Relative effort / dependency |
|---|---|---|
| 1. Immediate fixes | Honest Estimate status; visible unsupported photos; expanding vehicle notes; project notes in creation review; retire preference notes safely | Small to medium; independently useful |
| 2. Complete photo workflow | Vehicle reference folders, automatic group assignment, reliable discovery/order, independent Company/Shop access, HEIC previews | Medium; file identity and publication rules first |
| 3. Project types | Build, Service, Off-Site Service in Projects, Operations, Calendar and documents | Medium; additive schema and type-aware readiness |
| 4. Find and connect Estimates | Estimate browser and number lookup using the same verified connection flow | Medium; shared status semantics from batch 1 |
| 5. Import Estimate parts | Reviewed optional import with existing placement picker and unresolved-item handling | Medium to large; batch 4 and existing SKU identity |
| 6. Standard vehicle selection | Cached year/make/model choices and common quick picks; preserve artwork and historical identity | Medium to large; mapping before migration |
| Shared web/mobile foundation | Full Builder HTML app on desktop, iPhone and Android with responsive/touch layouts | Start the hosting/authentication design before new features harden desktop-only assumptions; deliver parity in tested stages |

These are relative sizes, not delivery-date commitments. The next session starts the shared
web/mobile foundation under [AZURE_PILOT_PLAN.md](AZURE_PILOT_PLAN.md). Calendar remains unreleased
work to preserve and stabilize alongside these batches. Do not hold useful fixes until the entire
mobile rollout is finished.

## One shared workflow

- Projects owns the job, agency, vehicles, project type, scope and notes.
- Operations owns acceptance, readiness, progress, actual start/finish and delivery commitments.
- Calendar owns planned bookings and team capacity, publishing through the existing Operations
  schedule service. A project type does not create another scheduler or another status history.
- Company Files and Shop Documents provide complete role-appropriate working packages for the
  same durable project, group and vehicle IDs. Staff should not need the other team's library.
- QBO remains the financial Estimate source. Connecting reads it; importing explicitly changes
  a Builder draft; Update Estimate remains a separate, warned and compared QBO write.

Keep sales scheduling restrictions, shop production controls, and manager scheduling controls.
Validate server permissions as well as visible controls. Sharing files does not grant financial
editing rights or expose unapproved draft instructions to the shop.

## 1. Immediate fixes

### Estimate status

Confirmed: `ui/js/projects/list_view.js` and `ui/js/operations.js` use **Estimate Sent** as a
fallback for missing Operations data or unaccepted vehicles. It is not evidence of sending.

Use one shared status interpretation in both views. Separate connection, sending and acceptance:
an unlinked estimate is unknown to Builder, a linked Pending estimate is not necessarily sent,
and QBO creation time is not a sent date. Use verified QBO email/delivery evidence where available;
first inspect the current API fields and representative read-only records. Do not promise that
QBO exposes a historical sent timestamp for every delivery method. Support an audited manual sent
date for estimates sent outside QBO or missing history. Never fabricate a date from observation time.

Owner-approved labels:

- **No Estimate Connected**: initial state with no linked Estimate. This does not claim no Estimate
  exists elsewhere in QBO.
- **Estimate Created**: Builder created or verified a connected Estimate, with no confirmed later
  milestone. This records existence, not proof it has never been sent; show unknown send history
  in details where applicable.
- **Estimate Sent**: supported by verified QBO evidence or an audited manual sent record.
- **Accepted**: verified or explicitly recorded acceptance; retain Declined/Closed where applicable.

Store connection and milestones independently. A manual acceptance can exist without a QBO link;
retain that acceptance and show missing connection separately. Do not regress Sent/Accepted on a
refresh just because a field is unavailable. Use partial counts for multi-vehicle projects where useful.
Keep Started/Active membership based on acceptance, not sending. Preserve the existing actual
QBO AcceptedDate polling, protected manual dates and accepted-order Calendar forecast.

### Notes

- Replace the individual vehicle's single-line notes input with a growing multiline field and
  a convenient full-size editor for very long notes; preserve line breaks on save/readback.
- Show editable project-wide notes during creation and display them on its final Review step.
- Remove the **preference notes** field from creation/editing. Keep manufacturer/lighting
  preferences. Inventory existing nonempty preference notes and preserve their text in project
  notes through an idempotent migration; retain legacy read compatibility and review conflicts.

### File visibility

Unsupported or corrupt media must appear with its filename and an honest **Preview unavailable**
state, plus an Open/download action when permitted. Distinguish empty folder, loading, permission
failure and incomplete sync. Do not treat unsupported files as absent or claim export success if
an assigned image could not be included.

## 2. Photos, folders and access

**September 14 implementation update:** Company per-unit reference-folder provisioning,
gallery discovery/group assignment, exact unit-folder actions, and finalized-reference publication
review are implemented locally. See [PHOTO_FOLDER_IMPLEMENTATION.md](PHOTO_FOLDER_IMPLEMENTATION.md)
for backfill evidence, the older Rice 2026 record exception, verification and the remaining photo
batches. The September 10 findings below describe the baseline before this change.

### Current evidence

Read-only code inspection found:

- Project discovery scans the Company year-level `Reference Photos & Videos`, not per-vehicle
  reference folders. Newly discovered files there enter the unassigned project library.
- Discovery, completed galleries and reference-library scans filter to JPG/JPEG/PNG.
- Galleries sort by path/filename rather than capture time.
- Completed galleries read Shop locations. An existing local synced folder takes priority even
  if empty; this needs verification against incomplete local synchronization.
- The shared thumbnail cache is under Company Files. Copying photos alone will not establish
  independent shop access; discovery, previews, reuse and cache reads must follow the user's library.

The read-only live audit on September 10 found **50 completed photos in Edina 2025 Shop folders**
(7 Blazer EV, 24 PIU K-9, 19 Lightning) and **25 in Cohasset's sampled Shop project**. The Shop
database is therefore not globally empty. Root cause of the reported empty screen remains to be
reproduced under the affected user's permissions/sync state; do not claim it repaired.

Both Edina agency roots contain only their registered 2025 and 2026 year folders. All four 2025
vehicles and the one 2026 vehicle match their saved folder identities/names in both libraries.
The second, empty 2025 Blazer is also registered in the app. No unregistered vehicle folders were
found in these trees, so none were deleted. This does not audit untouched historical source libraries.
If the duplicate Blazer itself is unwanted, correct the project record explicitly before retiring
its exact folders. Never infer deletion from a similar name or from an empty folder alone.

Audit artifacts on this workstation:
`/Users/skreev/.codex/visualizations/2026/09/09/01a087b2-627e-7fe2-a873-03767ed35f6c/post-meeting-plan/`.

### Proposed visible layout

Keep the existing Agency / Build Year / Vehicle structure and durable folder IDs.

| Within each vehicle folder | Company Files | Shop Documents |
|---|---|---|
| Build PDF / service work sheet | Office working output | Approved published version |
| Build Reference Photos | Sales upload location and assigned reference originals | Complete published reference set |
| Completed Build Photos | Automatic copy for office use | Shop upload location and originals |

The Company year-level `Reference Photos & Videos` remains the optional unassigned inbox.
Create vehicle reference folders as part of provisioning after project save, including vehicles
added later; report pending/retry state without blocking project creation. Backfill missing folders
additively for existing projects after an exact-ID plan.

A photo dropped into a vehicle's Company reference folder automatically assigns to its **unit
group**, as requested. Publish that group's references to each applicable vehicle package. Preserve
the actual source vehicle and file identity so filenames, renames, duplicate uploads and sync retries
do not create repeated attachments. Explicit removals/exclusions must not reappear on the next scan.

Use one authoritative source per asset and tracked copies, rather than unrestricted two-way sync.
Shop completion photos copy to Company; Company references publish to Shop. Track source item ID,
version, destination ID and copy status. Copies retry safely; do not propagate deletion automatically.
New references after finalization must surface for publication review instead of silently changing
approved shop instructions. Include supported videos as accessible files without promising video
pages in PDFs. Staff-facing notes, manifests and service instructions belong in the appropriate
package too; financial/admin internals do not belong in Shop Documents.

Reliable copying when all desktops are closed needs a narrowly scoped background identity with
access to both libraries. Evaluate a separate standard-SharePoint copy flow against the actual
licenses; desktop-only copying is a limited interim option, not always-on synchronization. Do not
reuse or enable the unfinished Operations processor as a shortcut. Test actual Office-only and
Shop-only accounts, including thumbnail and reusable-photo views, before permission cutover.

### Phone uploads and ordering

Keep OneDrive as the immediate upload tool while fixing app ordering. Prefer the photo's capture
timestamp, then a clearly identified upload-time fallback, with stable ties and a saved manual
order override. SharePoint/OneDrive for Business exposes `photo.takenDateTime` when available;
EXIF can supply another source. Missing metadata cannot reconstruct an unknown original sequence.
This fixes Builder ordering, not OneDrive's own sorting UI. [Microsoft Graph photo metadata](https://learn.microsoft.com/en-us/graph/api/resources/photo?view=graph-rest-1.0).

A focused **Add photos** control is practical. Select the vehicle once, choose Reference or
Completed according to role, select multiple photos, and show per-file progress/retry. Reuse Graph
uploads; add collision-safe creation, bounded file sizes, cancellation and duplicate protection.
Do not use the current overwrite-capable small-file upload helper without safeguards. Preserve
original bytes/metadata and sensible timestamp-based names where available. Test poor connectivity,
reopening, repeated taps, portrait orientation, full resolution and iPhone/Android multi-select.
Mobile operating systems can interrupt background work; never label queued files as uploaded.

### HEIC

Current support is **no**. Add visibility first, then decode HEIC on the desktop into JPEG previews
and export images while preserving the original. `pillow-heif` provides a plausible macOS/Windows
route, but frozen-app packaging, orientation, color and malformed-image handling need validation.
Browser-native HEIC support should not be required. This is a bounded addition, not a photo-editor
rewrite. [Decoder installation](https://pillow-heif.readthedocs.io/en/latest/installation.html).

## 3. Project types and scheduling

Add `Build`, `Service`, and `Off-Site Service` as project types independent of vehicle/build type
and lifecycle. Missing legacy values resolve to Build. Keep existing project/group/vehicle IDs and
folder paths; changing type must not generate replacement folders or QBO links.

Projects gets one obvious filter: **Builds** (default), **All projects**, **Service**, **Off-Site
Service**, alongside existing Started/Active/Inactive/Completed tabs. Calendar continues to include
all scheduled job types by default so a Builds filter cannot hide occupied team capacity. Preserve
team colors; use a small type icon/label for service/off-site instead of competing color systems.

Service uses the same agency, vehicle, parts, notes, documents, Estimate links and progress model.
Vehicle renders are optional. Finalization must produce a useful service work sheet without forcing
warning-light coverage or artwork. Represent non-applicable workstreams explicitly, not as work
falsely completed. Off-site work needs a service location/contact and planned travel allowance that
consumes the assigned team's capacity.

Proposed defaults: Builds retain existing strip/build/team-hour and finishing rules. Service requires
an entered time estimate, with strip and finishing selected only when needed. Off-site travel is
explicit. Keep actual start/finish tracking and no hours-worked entry. Use the current one-team booking workflow; legacy joint-team reservations remain readable. Service parts/vehicle readiness must reflect the job location rather than force
**At DTM** for an off-site vehicle.

**Owner decision (September 15):** Service and Off-Site Service deadlines are optional and manually
chosen; Builds retain the existing 60-day calculation. Also make same-agency/year project
creation and completion/merge logic type-aware, so completing a service job cannot accidentally
merge it into an unrelated completed build project. An estimate-free service job needs explicit
manual approval/acceptance before joining the accepted scheduling queue.

## 4. Estimate browser and number lookup

Add **Find Estimate** to the current vehicle's QuickBooks actions. Type the visible Estimate number
or open a searchable browser showing number, agency, status, date and current Builder connection.
Show parts/amounts on selection, then confirm the target vehicle. Reuse the same flow from a broader
Estimate browser to choose an existing build; clearly identify vehicle 1/3, VIN and unit number.

Query exact DocNumber safely, paginate lists, handle duplicates/no matches, verify company/customer
and refresh the selected form before linking. Keep duplicate-link checks and protected manual
acceptance. Linking remains read-only in QBO and never imports parts automatically. Store only the
appropriate shared observations; a shop user does not need a personal QBO connection to view progress.

### Automatically creating a blank Estimate

Retain as an optional later experiment, not the default in this plan. Current Estimates are per
physical vehicle, and current creation expects a configured draft, PDF and QBO Project relationship.
One blank Estimate per Builder project would conflict with that contract for multi-vehicle jobs.

First verify whether QBO accepts a truly empty Estimate through the supported API, using official
documentation or a sandbox. Do not invent a fake charge/part. If feasible, consider a deliberate
**Create Estimate now** option per vehicle once its customer/link requirements are ready, with
idempotent creation and recovery if QBO succeeds before the Builder link saves. Abandoned projects
must not cause automated financial-document deletion. Number lookup removes most friction without
creating unfinished Estimates every time a project is started.

## 5. Optional Estimate-to-manifest import

Place **Import parts from Estimate** in the existing QuickBooks/more-actions menu. Present a staged
comparison before applying it to an editable draft. Reuse exact QBO Item IDs to map existing SKUs;
retain quantities, distinguish physical parts from labor/fees/discounts, and show unresolved lines.
Do not silently create catalog products or treat description matches as confirmed SKU identity.

Use the current Part Picker placement component and validation for each placement-required item.
Allow saving incomplete work, but block completing the import/finalizing that draft until required
placements and unresolved lines are addressed. Guided components may need reconstruction choices;
a flat QBO line list does not contain all Builder relationships, colors or render instructions.

Review additions/merges/replacements explicitly; preserve existing placements and notes unless the
reviewed operation changes them. Keep Estimate pricing/provenance separate from the parts catalog's
list prices and the guarded QBO update baseline. Import does not write to QBO. This helps the current
catalog-curation backlog without bypassing its review rules.

## 6. Vehicle catalog

Use a cached public year/make/model catalog such as [NHTSA vPIC](https://vpic.nhtsa.dot.gov/api/)
to drive familiar selectors. Add quick choices for PIU, Durango, Tahoe and F-150 with an editable
model year; treat PIU as a friendly fleet alias mapped deliberately to the right catalog model.
Retain a manual/custom fallback for missing, new, specialty and historical vehicles.

Catalog identity and Builder render profiles are different things: a model listing does not supply
DTM artwork, placement coordinates or equipment compatibility. Add external IDs/aliases to existing
vehicle records, retaining internal IDs and attached images/layouts. Map existing records explicitly
and review ambiguous matches before a migration; never replace by name alone. Keep project build
year distinct from actual vehicle model year. Historical PDFs, folder labels, presets and saved
drafts must not silently change because the external catalog updates.

Validate offline operation, year changes, alias matching and representative old renders before
cutover. This is feasible, but broader than swapping one dropdown and copying pictures.

## 7. Full shared HTML app: owner clarification

The target is the **full Builder application**, using the same HTML/CSS/JavaScript feature code
on desktop, iPhone and Android. Mobile differences concern layout, touch controls, accessibility
and platform file actions; role permissions still determine what each person may do. A reduced
shop-only Power App is not the intended final product. A simple Canvas app remains an optional
interim tool if explicitly resumed, not a prerequisite or a second permanent implementation.

Use an installable web app (PWA) with a home-screen icon and standalone window. Keep the desktop
wrapper as an optional shell over shared UI/services. The target includes Projects, build editing,
placement/render previews, parts, Estimates, Operations, Calendar, photos and permitted Settings.
Do not call an initial subset full parity; maintain a feature checklist through rollout. Large
placement canvases need touch pan/zoom and usable selection, not just smaller controls.
[Apple home-screen web apps](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios).

### What can be reused, and what must move

The app already serves HTML/CSS/JavaScript from Python and has service/domain/render layers that
can be reused. It is not currently a hosted multi-user application: `app/adapters/wiring.py` has
one active process-wide adapter bundle, request permissions derive from that local sign-in, and
QBO credentials are in the user's OS keychain. Simply exposing the local server would share the
wrong identity assumptions between users.

Proposed architecture:

1. Keep a shared UI and business-rule implementation, introducing deployment adapters rather than
   separate mobile feature logic. Use production HTTPS hosting for the Python API and assets.
2. Add request-scoped Microsoft sign-in, separate user sessions, read/write authorization and
   session/CSRF protection; retain every role restriction at the API boundary.
3. Continue using existing SharePoint records, libraries and IDs initially. Replace assumptions
   about a workstation's synced folders with provider access; make concurrent edits and background
   jobs revision-aware. Separate temporary files, caches and jobs by their real owner/record.
4. Run rendering/PPTX/PDF generation in bounded server jobs. The current PDF service already tries
   Linux LibreOffice paths, which is promising but not proof of hosted compatibility. Validate
   fonts, representative output, CPU/memory and concurrent jobs in a container. Keep identical
   business outcomes for downloads/sharing even when native file dialogs differ.
5. Design hosted QBO authorization and encrypted credential storage explicitly. Reuse guarded
   Estimate services, but do not copy desktop tokens to a host or silently adopt the abandoned
   centralized-QBO experiment. Full hosted QBO makes this an active design dependency; its old
   branch remains excluded until reviewed. Update the security contract before implementing a
   hosted credential model; desktop keychain rules remain unchanged meanwhile.
6. Make photo uploads and longer jobs durable and observable when a phone disconnects. Cache only
   suitable app assets for installation; full offline editing is not promised by the PWA label.
   Clear or isolate sensitive cached data across sign-out/accounts.

A hosted service could also run photo copying and acceptance checks when desktops are closed.
Review whether it can replace proposed copy flows and duplicated phone logic before building both.
Do not enable the existing unfinished Operations processor as part of this planning change.

### Hosted delivery plan and pricing

[AZURE_PILOT_PLAN.md](AZURE_PILOT_PLAN.md) is the execution plan and next-session handoff. Begin
with the local cloud-off runtime/export proof, then establish shared-user boundaries before an
isolated Azure trial. Continue through SharePoint/QBO sandbox integration, full mobile parity,
measured cost and a separately reviewed production rollout. Azure is preferred if affordable;
OVHcloud remains the cost fallback. Trial activation has not been reported.

[HOSTING_COMPARISON.md](HOSTING_COMPARISON.md) is the single pricing reference: current provider
comparisons, trial restrictions, Azure sizing assumptions and the illustrative $25–35 monthly
target. Hosting costs are shared, not multiplied by the eleven app users. Do not repeat older
Railway-first or DigitalOcean-first recommendations as the current direction.

The proposed website entry remains an **Employee Login** link to `builder.dtmfleet.com`, protected
by company-tenant M365 authentication and explicit employee roles. Keep existing SharePoint IDs
and role-appropriate libraries; hosting does not grant staff broader document or financial access.

A central QBO connection requires the backend migration in the pilot plan and
[QUICKBOOKS.md](QUICKBOOKS.md#centralization-phase-3a--planned-hosted-migration-not-in-production).
One authorized admin grants company consent; staff use their own M365 identities and audited
Builder permissions. Desktop clients lose individual Intuit prompts only once they use that
backend. Direct QuickBooks website use retains normal QBO account requirements. The old
`codex/central-qb-backend-wip` is incomplete reusable groundwork, not a ready deployment.

### Power Apps Code Apps and Dataverse

Code Apps supports code-first JavaScript web apps and Power Platform connectors; choosing it does
not require migrating all business records into Dataverse. Microsoft currently states that Code
Apps end users require **Power Apps Premium**, which is $20/user/month billed annually: **$220/month
for 11 users** before other costs. Do not apply the cheaper Canvas per-app comparison to Code Apps
without explicit Microsoft confirmation. Its hosting also does not move the existing Python
renderer into a JavaScript app automatically.
[Code Apps requirements](https://learn.microsoft.com/en-us/power-apps/developer/code-apps/overview),
[Premium pricing](https://www.microsoft.com/licensing/guidance/Power-Platform).

An independently hosted HTML app therefore fits the owner's full-feature and cost goals better.
No Dataverse migration is needed merely to use HTML. The existing Canvas/flow work remains optional;
no Canvas app exists, and the Operations processor remains **Off** until failure handling, recovery
and its controlled pilot are complete. Preserve the existing connection's actual permission identity.

## Verification and rollout

- Use cloud-off fixtures for each implementation batch and `tools/verify.py changed` after a
  meaningful batch. Preserve existing uncommitted work and golden masters.
- Focus photo checks on exact identity, duplicate-free retry, group assignment, missing permission,
  incomplete local sync, unsupported files, capture ordering, library isolation and publication.
- Focus project-type checks on legacy Build defaults, service readiness, capacity occupancy,
  completion/merge isolation and unchanged Build deadlines.
- Focus QBO checks on truthful status, exact-number selection, wrong-customer/duplicate rejection,
  incomplete import blocking and no remote mutation from connection/import.
- Before any production backfill, prepare the exact affected item list, source/destination rules,
  collision handling, read-back checks and recovery procedure. No broad folder cleanup by name.
- Update the staff workflow handout after behavior is agreed and released.

The existing parts-DB consumer migration, reviewed catalog-change queue and curation remain the
architectural backlog. Import and vehicle selection should use those seams, not force a wholesale
rewrite. Bay tracking, serial tracking and generalized light/view work remain later work. Hosted QBO
authorization is now a design dependency of full web parity; the old centralized-QBO experiment
is still excluded and no token migration or deployment is authorized by this document.

## September 15 project types — implemented locally

Build, Service and Off-Site Service are available in creation and Project Details, with Builds / All /
Service / Off-Site Service filtering across lifecycle tabs. Legacy projects default to Build. Service
visits have independent project/vehicle IDs and files even within the same agency/year. They never
merge automatically into a completed Build or another visit. Operations and Calendar derive type and
service requirements from the authoritative Builder project; no new SharePoint columns are required.

Service scheduling requires explicit acceptance and an entered labor estimate per vehicle. The
project checkbox applies that estimate to unscheduled siblings. Stripping and finishing default off;
off-site work requires a location/contact and includes its explicit travel labor in team capacity.
Parts, tray and programming/QC can be marked not applicable without setting false completed statuses.
For off-site work, the existing Ready for pickup availability value also represents availability on
site (Calendar labels it accordingly). Work stays in the shared calendar regardless of Projects filters.

Service drafts start independently, with vehicle rendering optional. Their worksheet retains cover,
parts, notes and reference photos and omits diagram pages by default. Finalization still requires a
current PDF and vehicle identity, but has no warning-light/vehicle-artwork requirement. Existing Build
rendering and checks remain in place. Change finalized requirements only after reopening the work.

A lightweight **Link previous build** action searches saved Build vehicles by VIN/unit number. The
service individual stores only project/group/vehicle reference IDs. **Previous Build Design** opens
a read-only parts/locations/notes view and the existing PDF when available. It never copies parts,
placements, Estimate links, statuses or folder identities into the service. Unmatched vehicles follow
the normal independent service workflow. This is a reference to the saved design, not an as-maintained
vehicle inventory; historical inventory/version tracking is deliberately deferred.

The full release gate was attempted for the project metadata/export change and stopped at the known
`test_parts_db_contract[root_doc]` mismatch in the pre-existing bundled catalog (`qb_inactive` differs
from its recorded contract). Neither catalog data nor golden/contract snapshots were changed.
A synthetic service worksheet was converted through LibreOffice to PDF and both pages visually
inspected: service cover/scope and instructions, with no diagram pages or Build equipment tiles.
Local QA artifacts: `/private/tmp/service-worksheet-qa/latest.pdf` and `latest-1.png` / `latest-2.png`.
No live project, Operations row or SharePoint file was changed for this work. Restart the desktop
app to load the new Python services.

Final changed gate: **914 passed, 1 skipped; 10/10 selected browser flows**. Coverage includes 10
project-type tests, the full service browser workflow, unchanged Build sign-off and golden rendering,
previous-build reference isolation, visit file separation, explicit labor/travel, service deadlines,
and optional lighting checks. Python/JavaScript syntax and `git diff --check` also passed.
