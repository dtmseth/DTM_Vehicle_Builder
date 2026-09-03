# Build Reference Photos and Vehicle Folders

Status: shipped in v3.5.0. Additive lifecycle provisioning, the reviewed
historical-photo copy, Company per-vehicle PDF publication, and finalized Shop package publication
are active after owner-approved live verification.

This document owns the product contract for reusable build-reference photos, per-vehicle Shop
folders, generated reference pages, and the related Project Overview/build-card cleanup. It refines
`NEXT_FEATURE_PLAN.md` Phase 3C/3D. The approved Company/Shop trees and verified historical-photo
copies are live; the legacy source remains untouched and the publication cutover is active behind
its explicit configuration gates.

## Product model

One app project represents one agency build year. New project creation must enforce the unique key
`agency_id + normalized build_year`; an existing project is opened and extended instead of creating
a duplicate. Existing duplicate records require a reviewable merge report because drafts, vehicle
IDs, notes, QuickBooks links, finalization state, and outputs cannot be combined safely by guessing.

Past vehicles that exist only as completed-build photos use ordinary projects for their actual
agency and build year. They may contain only vehicle model, optional build type/unit/VIN, notes, and
photos; no historical vehicle type, checkbox, label, or migration marker exists. The absence of a
draft, generated PDF, finalization, and QuickBooks data is simply the absence of that data. Once the
reviewed photos have been copied and verified, the project is marked completed and appears in
**Project Archives**. Completed is a reversible project lifecycle state, not a different schema.

Every reusable item is a **project photo**. A project photo may be **unassigned** or assigned to one
or more `BuildUnit` groups. Only a group's assigned photos appear in its build sheets and Shop
packages; unassigned project photos remain available for later use. Removing the last group
assignment makes the photo unassigned without removing it from the project.

New project-wide and individual-unit assignments are not created. Existing project/individual
assignments remain readable and publishable for backward compatibility, with explicit legacy labels
in the UI; the app does not silently rewrite or discard them.

There is no agency-level assignment, inheritance, or inbox. Instead, the reference picker may browse
organized photos from any build year, unit group, and unit under the same agency. It includes Company
Files **Reference Photos & Videos** and Shop Documents **Completed Build Photos**. Reusing a historical
photo never moves the source. The group assignment owns its shop note, and finalization copies
the effective photo into the current vehicle's Shop package.

Videos are Company Files only. The app may list/open them as design context, but never renders them
in the build sheet and never copies them to Shop Documents.

## Target filesystem

Company Files is the working/design record. Do not publish new PPTX files to it; the app project and
draft are the editable source, while a locally generated PPTX may remain an internal conversion
artifact.

```text
Company Files/
└── Vehicle Project Database/
    └── {Agency}/
        └── {Agency Abbreviation} - {Build Year}/
            ├── Reference Photos & Videos/
            │   └── Project reference photos and reusable source photos/videos
            └── {Vehicle Name}/
                └── {Vehicle Name}.pdf
```

Shop Documents uses the same agency/year navigation and adds one folder per physical vehicle:

```text
Shop Documents/
└── Shop Project Database/
    └── {Agency}/
        └── {Agency Abbreviation} - {Build Year}/
            └── {Vehicle Name}/
                ├── {Vehicle Name}.pdf
                ├── Build Reference Photos/
                │   └── Photos assigned to this vehicle for the build
                └── Completed Build Photos/
                    └── Photos taken after the build is completed
```

Every agency stores an editable **Agency Abbreviation**. The default uses the initials of meaningful
name words (`St. Cloud Police Department` → `SCPD`), uses only the county name for county sheriffs
(`Mille Lacs County Sheriff's Office` → `Mille Lacs`), honors a short uppercase acronym in
parentheses, and may be overridden for names such as `ICE` or `HSI`. Legacy projects derive the same
default until the agency is edited. `&` is valid on macOS, Windows, OneDrive, and SharePoint and is
preserved; only characters actually reserved by the supported targets are folded to spaces.

`{Vehicle Name}` is the readable canonical identity surfaced on the unit card and used for its
folder and PDF:
`{build year} {agency abbreviation} {short vehicle model} - {build type} - Unit {number} - VIN {last six}`. The model is
the model only—not make plus model—and Police Interceptor Utility is always abbreviated `PIU`;
other examples include `Durango`, `F-150`, and `Traverse`. Omit only the identifier segment that is
unavailable; for example, `2027 SCPD PIU - Patrol - VIN 123456` is valid when the unit number is not
known. Existing records without either identifier receive a stable folder/card suffix derived from
their durable vehicle ID, such as `2027 SCPD PIU - Patrol - Pending ID 8A9743C8`. This placeholder is not
an inferred VIN or unit number. New vehicles must still capture a unit number or VIN before export
or finalization. If a VIN later arrives, the stored SharePoint folder item is renamed/relocated to
the real canonical name by item ID, so its **Completed Build Photos** remain attached. Ambiguous
historical source-photo mappings remain in migration review rather than being guessed.

Folder provisioning follows the data lifecycle instead of waiting for finalization:

1. saving an agency/year project creates/reconciles its Company and Shop agency roots plus the
   year and combined reference-media folder;
2. every known individual receives a vehicle folder directly under the year; records missing unit/VIN data use their stable
   `Pending ID` suffix;
3. when a real unit number or VIN is added, the existing folder moves by stored item ID rather than
   creating a second vehicle folder;
4. reviewed past-photo imports receive their exact Shop destination during the migration copy step;
   lifecycle placeholders never guess which ambiguous source-photo folder belongs to a vehicle.

Standalone Agency Manager records—including Customers imported from QBO—never create vehicle-tree
folders. An agency found only in the legacy **Build Photos** tree becomes eligible by receiving an
ordinary completed agency/year project during the reviewed historical-photo migration.

Agency, year, build type, model, unit number, or VIN changes move the stored vehicle folder item by ID. Durable
`pending`/`error` state is written before the background worker starts, so an interrupted save is
retried during cloud sync instead of silently losing the rename. Reconciliation first asks Graph for
the durable vehicle item's current parent/path. If a user moved the folder in SharePoint after the
last save, the app adopts that live parent and refreshes its locators rather than recreating or
moving the obsolete saved path.

Agency list/search surfaces merge normal agency records with the durable agency identity retained by
projects. A missing standalone record therefore remains visible in Agency Manager and the project
wizard, where editing it materializes the record with the same `agency_id`. An agency referenced by
any project cannot be deleted.

## Source identity and assignments

A project reference record stores stable asset identity and assignment metadata, not image bytes or
an absolute workstation path. It includes:

- stable reference ID;
- media type (`photo` or `video`);
- source library/kind, SharePoint drive/item IDs, display name, and portable compatibility path;
- zero assignments for an unassigned project photo, or one or more unit-group assignments with target ID and shop
  instruction note. The stored display-order field remains for backward compatibility but is
  assigned automatically and is not a user-facing number control;
- optional source fingerprint/size and last-resolved metadata for change detection.

The year-level Company Files **Reference Photos & Videos** folder is also the project's physical
photo inbox. When the project opens, a bounded background check reconciles supported JPG/PNG files
from that exact folder into `reference_assets` with zero assignments. This makes photos dropped
through OneDrive or SharePoint appear as unassigned Project Photos without a second import step.
Videos remain Company-only browsing material and are not auto-attached or published. Removing an
auto-discovered photo from the app records its stable source identity in
`reference_source_exclusions`; the source file is not deleted and may be explicitly added again.

Resolution for one vehicle uses its unit-group assignments. The resolver continues to combine and
de-duplicate legacy project/group/individual assignments so existing projects and PDFs do not lose
references. Missing sources produce a visible warning and block a supposedly complete reference
package from silently publishing without the photo.

## User interface

### Project Overview

Add a full-width **Project Photos** card. It reports total, assigned, unassigned, and preserved legacy
photo counts and has one **Project photos** action plus the conditional **View completed photos**
action. The selectable project-photo gallery shows assignment state and notes, adds more photos,
assigns selected photos to a unit group, and removes selected project metadata without deleting the
source. Company, project-photo, and Shop folder buttons live separately in the Overview. The source browser
filters by year, filename, make, model, and build type. It defaults to the current agency plus the
selected vehicle make/model and build type, but can browse every app agency.

### Unit group

Add **Build Reference Photos** to the unit-group header. It opens the same thumbnail-card gallery
used elsewhere, with source/state tags and each assignment's shop note. Users can edit a note inline,
remove selected photos from the group, or open **Add photos** and multi-select project/reusable photos
for the whole group. Ordering is automatic.

### Individual builder

Add **Build Reference Photos** to the Build Notes card at the bottom of the builder. It shows the
effective group set with clear legacy labels where necessary. Its manage action opens the enclosing
unit group's reference editor; individual vehicles do not have their own reference assignment UI.

### Vehicle build cards

Remove the user-facing PowerPoint action and the `configured`, `not set up`, `custom build`, and
PPTX/PDF timeline/status clutter. Keep vehicle identity, useful parts/lights counts, unit notes, and
the operational finalization state. Consolidate actions into:

- **PDF Options** - export/update, view, and last-export details;
- **QuickBooks** - Project setup/manage and Estimate actions/status;
- direct **View completed photos** when its exact completed-photo folder contains supported images;
- **Folder options** - exact Company/Shop folder navigation;
- **Finalize design** - remains separate because it locks the approved design and publishes its
  initial package. Re-exporting afterward asks before replacing the existing app-owned Shop PDF.

Individual vehicle cards do not expose reference-photo viewing or assignment controls. Reference
photos belong to the unit group and are managed from the **Build Reference Photos** action in that
group's header. The Project Photos card remains the place to view all assigned and unassigned photos.

The completed-photo action is conditional: a background presence scan must find at least one
supported image in the exact vehicle **Completed Build Photos** folder. The last authoritative
presence result is cached locally and applied on the first project paint while a refresh continues,
so a known action does not wait several seconds for SharePoint. Completing a project,
finalizing its design, or provisioning an empty destination folder does not reveal the action. If an action menu is open,
the first click outside it only dismisses the menu; the second click may activate the underlying
card/button. Choosing an action inside the open menu closes it immediately.

Card activation continues to open or set up the build in the app. Replace project-level **Generate
All** with **Export/Update All PDFs**.

The project photo card and every completed-project row expose completed/reference thumbnail
galleries at the top level. Each vehicle's **Folder options** opens its exact Shop **Build Reference
Photos** and **Completed Build Photos** folders. A locally synced OneDrive folder is preferred; the
app falls back to the folder's SharePoint URL.

Gallery discovery must not block the app's local HTTP request queue. Assigned reference galleries
come directly from saved project metadata. Opening a project checks only its exact year-level
**Reference Photos & Videos** inbox and persists newly found photos as unassigned metadata.
Completed galleries scan only the exact stored vehicle
folder paths in a bounded background worker. Same-agency reusable-media discovery keeps a local
inventory cache and refreshes it in the background. Small display previews use local source bytes or
Microsoft's generated Graph thumbnail and are cached by stable source identity/eTag. Only a visible
card's follow-up upgrade hydrates the exact source image and normalizes it to a bounded JPEG. The normalized JPEG is also stored in the app-managed Company Files
`Settings/_DTM Photo Thumbnail Cache/v2` area. A second workstation downloads that small shared
file instead of hydrating the original; failures fall back to local generation and never block the
gallery. Graph thumbnails are the preferred first display for remote photos, not an exact-source substitute.
Thumbnail preparation uses four low-priority preview workers, six foreground preview workers, and
three separate on-demand exact workers.
The first visible cards start immediately; opening or scrolling a card promotes its queued work ahead
of cache preparation. Startup compares a persisted fingerprint of saved photo metadata and does no
work at all when that catalog is unchanged; it never recursively scans all completed-photo folders.
External folder changes are checked only for the project being viewed. Server waits are bounded and return a retryable `preparing` state, while the
browser applies its own timeout/retry budget and always ends at either a rendered image or an explicit
**Retry** action—never an endless spinner. While a first-pass batch is active, the connection pill shows
`Preparing photos ready/total` and explains that large libraries can take several minutes once, after
which the small cached files are reused. Full-resolution media downloads only when opened, runs on a
dedicated high-priority worker, and is retained in the app's local exact-media cache after a successful
first load. New thumbnail network work yields while that original is active. The viewer and connection
pill identify the download, the media endpoint returns a retryable preparing response instead of holding
one browser request open, and bounded failure ends at an explicit Retry action. A failed preview completes the batch with a retry count
rather than leaving the progress bar stuck. App shutdown cancels queued photo work and uses short
network-stage bounds for any already-running item. Users may mark the Shop Project Database **Always keep on this device** for instant
full-size Explorer access, but that setting is optional and is not the app's storage contract.
Portrait thumbnails preserve the entire image with side letterboxing; the v2 thumbnail cache
invalidates older Microsoft previews that contained baked-in top whitespace. Completed galleries
support multi-select from the thumbnail grid through one disabled-until-selected **Use as Reference
Photo(s)** action. Its compact dialog requires a destination project and optionally accepts a unit
group: project-only adds an unassigned project photo, while a selected group assigns directly. The
full-resolution viewer is view-only. The existing-photo browser overlays **Completed** on Shop
completed-build images, uses the canonical vehicle name as the main label, and keeps only the
filename and relevant note beneath it. Project galleries show assigned/unassigned state and notes,
with **Add photos**, **Assign to unit group**, and **Remove from project** actions. Empty galleries
show only the centered **Add photos** action.

The primary card title is the canonical identity above, so users see vehicle model, build type, and
unit number and/or VIN last six without opening Details. The same formatter drives Company/Shop
folders, PDF filenames, and copied QuickBooks Project names; these surfaces must not drift. Model-
only references shorten F-150 Lightning to `Lightning`.

## Generated output

The effective photos for a unit render in **Build Reference Photos** pages immediately after the
vehicle visual renders and before the parts manifest, using an adaptive orientation-aware layout.
A portrait always receives a full-height column; one portrait may pair
with up to two stacked landscapes, two portraits share one page, and landscapes use one-up, two-up,
or 2x2 layouts. Three landscapes intentionally leave the fourth 2x2 cell empty rather than shrinking
or cropping an image. Preserve aspect ratio without cropping, keep the concise title/note tight to
the image, and omit the appendix when no photos apply. The title and 10-point shop note use a
translucent dark overlay at the bottom of the photo so text stays readable on any image while the
photo reclaims the old external-caption space. Downsample the embedded display image so phone photos
do not make the PDF unnecessarily large; the full-resolution source is copied beside the PDF.

After PDF conversion, each image receives a link over the same adaptive cell geometry. When the
source has a SharePoint web URL, use a standard HTTPS annotation that works in Apple Preview and
browser PDF viewers. Otherwise use a sanitized relative-file fallback such as
`Build Reference Photos/example.jpg`. Never write an absolute username/workstation path. Some PDF
viewers block relative launch actions, so exact folder navigation remains the dependable local-file
fallback.

## Finalization and ownership

Finalization creates the Shop vehicle folder, publishes the current PDF, creates both photo
subfolders, and copies the effective reference-photo set. It never copies videos. Publication is
idempotent and stores exact Shop item IDs/content fingerprints plus durable pending/retry state.

The app owns only its PDF and the files it publishes into **Build Reference Photos**. It must never
delete, replace, move, rename, or treat **Completed Build Photos** as disposable. Reopening may
withdraw/replace the PDF and refresh app-owned reference copies while preserving the unit folder and
all completed photos.

## Migration and rollout

The reviewed live source mapping and per-folder sparse translations are maintained in
[`BUILD_PHOTOS_MIGRATION_PLAN.md`](BUILD_PHOTOS_MIGRATION_PLAN.md).

1. Enforce uniqueness for new projects and report existing agency/year duplicates.
2. Ship backward-compatible reference persistence, sparse past-project support, completion state,
   Project Archives, and cloud-off UI/output behavior.
3. Add lifecycle folder provisioning and Company/Shop drive-item operations; verify the approved
   live skeleton without enabling PDF publication.
4. Inventory the existing Shop **Build Photos** tree read-only. Map each reviewed folder to an
   ordinary project for its agency/build year, creating sparse model/build-type/unit entries only
   from known data. Consolidate multiple build folders for the same agency/year into that single
   project, and mark imported projects completed so they open in Project Archives. Never infer an
   agency, year, vehicle model, build type, unit, or VIN from an ambiguous folder name.
5. Back up the source inventory and project records, then **copy** the reviewed photo set into the
   newly provisioned **Completed Build Photos** destinations. Do not move or delete source photos.
6. Verify item counts, byte sizes/hashes where available, destination paths, and app browse/open
   behavior. Produce collision, duplicate, unmatched, and failed-copy reports.
7. Only after every verification gate passes, enable the app's new Company/Shop PDF paths and test
   export, finalization, reference reuse, and folder-opening on the copied tree.
8. Removing or archiving old locations is a separate final approval after the app cutover is proven.
   Stop new PPTX cloud uploads at cutover; historical PPTX cleanup remains a separate decision.

Steps 1-6 are complete for the approved legacy Build Photos scope. The initial live provisioning run
created and verified both roots and all nine current project trees, including stable placeholders
for 23 vehicles without a unit number or VIN. No PDFs, PPTX, or videos were copied. The later agency-
abbreviation migration restored the missing ICE,
HSI, and Fergus County agency records under their original durable IDs, adopted their existing
agency roots by item ID, and renamed/reverified all nine current project trees to the abbreviation-
qualified year/group/vehicle convention. The legacy source inventory contains 28 agency-level
folders, 46 build/photo groups, and 1,043 files. Forty-five dated groups consolidate to 34 ordinary
completed agency/year projects across 27 confidently matched saved agencies; the approved joint
`Benton-Stearns Negotiator Van` (`BSNV`) 2025 project brings the total to 35. All 1,043 photos were
copied into the new Completed Build Photos destinations and verified by relative path and byte size;
both sides total 11,934,028,588 bytes. The legacy source remains unchanged.

The first provisioning pass incorrectly treated all Agency Manager/QBO Customer records as project
agencies and created 219 agency roots in each new database. The corrected runtime is project-scoped.
A read-only audit found 184 unwanted roots in each database; every one was rechecked empty and
deleted by exact item ID after approval. The corresponding state on all 184 standalone agency
records was cleared and directly re-mirrored. The final Company and Shop databases each contain the
same 36 approved agency roots: saved current-project agencies, the 27 mapped Build Photos agencies,
and `BSNV`.

Provisioning and publication/cutover remain four independent configuration flags. All four are now
enabled after the initial live skeleton and first finalized package were verified. Adding library
names alone still cannot activate a write path. Before changing a publication/cutover target, review
`GET /api/projects/naming-migration-report`; it lists every desired vehicle/folder/export/QBO name,
missing identifiers, legacy export stems, and same-agency/year
duplicate project groups without writing anything.

Existing true QuickBooks Projects must be renamed manually in the QBO UI using the report's exact
`rename_to` values, then verified to retain the same Project ID. The approved Accounting API cannot
list or rename QBO Projects. Existing output files change to the canonical name on their next
generated export. Historical Company/Shop moves and duplicate-project merges remain explicit,
reviewed migrations; never guess across drafts, completed photos, reference assignments,
finalization state, Estimates, or linked QBO IDs.

## Acceptance coverage

- Legacy projects without reference fields round-trip unchanged.
- Duplicate agency/year creation is rejected server-side and redirects users to the existing project.
- Completed projects leave the active list, appear under Agency → Build Year in Project Archives,
  and return to the active list when reopened.
- Assigned/unassigned project-photo round trips and legacy project/group/unit de-duplication are tested.
- Historical Company reference and Shop completed photos are reusable without moving their source.
- Sparse past projects retain only the build and photo data actually known; no synthetic historical
  type or label is persisted.
- Videos never reach generated reference pages or Shop publication.
- 1, 4, and 5-photo outputs render correctly; phone rotation and supported formats are verified.
- PDF link annotations contain only sanitized relative child paths and remain optional/fail-safe.
- Retry/reopen flows never alter Completed Build Photos.
- Focused behavioral tests, representative PPTX/PDF visual review, full goldens/contracts, and all
  browser smoke flows pass without re-recording unrelated goldens.

The cloud-off acceptance set passes, and the additive live folder skeleton has been verified. The
multi-workstation publication and migration paths remain cutover gates and must be exercised
intentionally before either PDF publication/cutover flag is enabled.
