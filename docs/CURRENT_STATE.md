# DTM Vehicle Builder — Current State

**Last updated:** 2026-09-10

**Current release:** [v3.7.0](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/tag/v3.7.0)

This is the short operational handoff for the repository. It replaces dated session handoffs and
release checklists. Long-lived design and behavior remain documented in `ROADMAP.md`,
`FEATURE_INVENTORY.md`, `PARTS_DB_AND_PICKER.md`, and `QUICKBOOKS.md`.

## Current local work — Azure Stages 1–2 (unreleased)

The cloud-off headless runtime and synthetic UI/export proof are implemented. Native macOS
verification produced byte-verified PPTX/PDF downloads for typical (8 pages) and photo-heavy
(20 pages) builds, with no external requests. Focused gate: **517 passed, 1 skipped, 4 selected
browser flows passed**. Colima/Docker are installed in a dedicated local profile. See
[AZURE_PILOT_RESULTS.md](AZURE_PILOT_RESULTS.md) for commands, measurements and remaining gates.
Stage 1 now has an ARM64 Linux run: the staged 396,900,402-byte image
passed UI edit/save, restart persistence, typical/dense exports, cgroup limits, no-OOM, fonts,
full 28-page Poppler review and blocked external connections. The subsequent AMD64 image
(400,900,598 bytes) also passed through Rosetta, including all four downloads, restart persistence,
28-page rendered review, no OOM and blocked egress. Peak combined export memory was 602.19 MiB
by the kernel counter. Stage 1's local gate is **complete**; no Azure performance claim is made.
The owner then explicitly advanced Stage 2 locally: the new
request/session/job/artifact boundary uses signed tenant identities, existing capabilities,
exact revisions and owner-bound downloads. It includes an Azure Table adapter, synthetic durable
tests, a loopback Waitress proof and review-only auth configuration. See
[HOSTED_BOUNDARY.md](HOSTED_BOUNDARY.md). Real provider adapters/full hosted UI remain closed;
latest focused gate: **663 passed, 1 skipped, 4/4 browser flows**, including 53 boundary tests.
The AMD64 run exposed and fixed a Projects refresh race that could dismiss an opened draft;
a delayed-refresh browser regression covers it. No trial, deployment or live-data
connection occurred. Existing uncommitted feature work and user `output/`/`tmp/` remain intact.

## Next session — deployment files ready; owner handles activation

Start with [AZURE_PILOT_PLAN.md](AZURE_PILOT_PLAN.md), the results log and hosted boundary doc.
Stage 1's local Linux gate is complete. The separate hosted AMD64 image (103,678,174 bytes),
bounded expiry cleanup, fenced job recovery and safe telemetry are implemented and verified
locally. The real factory passed startup/negative HTTP/restart checks with networking disabled;
it contains no full Builder UI or provider integration. [HOSTED_OPERATIONS.md](HOSTED_OPERATIONS.md)
records procedures, proposed retention and actual limits. The concrete
[AZURE_RESOURCE_REVIEW.md](AZURE_RESOURCE_REVIEW.md) now records Central US candidate resources,
sole pilot user/alert recipient **seth@dtmfleet.com**, proposed operator duties and a $15 alert
budget. At 40 active boundary hours/month, retail assumptions total **$13.15 before grants** or
**$10.95 with full Container Apps compute/request grants**, excluding trial credits. This is not
a quote or spending authorization. The owner confirmed **no current Azure subscription and a
$200 trial offer**; do not re-check that offer or repeat portal/account discovery. Reproducible
[deployment files](../packaging/hosted/azure/README.md) now compile locally: foundation, private-by-default
app/auth, and opt-in monitoring/budget. Seth handles trial activation. Supply the resulting
subscription/tenant IDs when deploying; no activation or deployment has been authorized yet.
The local Colima profile is stopped; synthetic evidence and image/volume caches are retained.
The Stage 2 proof is a security/storage boundary, not full hosted feature parity. Provider
integration and central Calendar/QBO polling remain disabled for the later isolated stage.
Preserve all tracked/untracked Calendar and phone-foundation work on `main`,
and leave user-owned `output/`
and `tmp/` untouched. The plan includes a copyable next-session prompt.

Azure Container Apps is preferred if affordable; OVHcloud remains the cost fallback. The owner
confirmed the $200 trial offer and no current subscription. Account setup is owner-handled;
do not re-verify the offer. No subscription purchase, hosted deployment, production
cutover or token migration has occurred. [HOSTING_COMPARISON.md](HOSTING_COMPARISON.md) records the
illustrative $25–35/month target, higher-cost scenarios, provider prices and unverified assumptions.
The target is not an approved spending cap or a measured forecast.

No mobile UI design or interactive mobile prototype has been created yet. Phone workflow
requirements exist; the responsive full Builder UI remains planned work.
The accepted full shared HTML app includes desktop/iPhone/Android feature parity with role-specific
access, M365 login and a planned central QBO connection. Local production still uses the existing
per-user QBO keychains/Netlify broker. The old central branch was inspected read-only and is not a
complete hosted implementation. No Canvas app exists; the unfinished phone processor remains Off.

## Accepted post-meeting feature backlog

[POST_MEETING_FEATURE_PLAN.md](POST_MEETING_FEATURE_PLAN.md) owns the coordinated requirements for
photo folders/access/HEIC/uploads, truthful **No Estimate Connected / Estimate Created / Estimate
Sent / Accepted** states, Estimate discovery/import, project types, notes and standardized vehicle
selection. Preserve these requirements alongside Calendar; use the hosted seams as new work lands.
The feature plan also records the read-only Edina/photo audit. The September 14 Company per-unit
reference-folder batch is now implemented locally, separately from Azure; see
[PHOTO_FOLDER_IMPLEMENTATION.md](PHOTO_FOLDER_IMPLEMENTATION.md) for its backfill evidence and
remaining photo scope. Other feature batches remain planned and unshipped; the local runtime proof
above does not implement that backlog.

## Current desktop work — Calendar (unreleased)

The working tree now includes a top-level Calendar with Monday–Friday Week and Sunday–Saturday
Month views, team assignments and labor-capacity planning, and **General Settings → Teams &
Calendar**. Initial teams are David's Team, Josh's Team, and Michelle. Accepted Operations
vehicles enter the acceptance queue; reviewed saves reuse the existing Operations schedule-event path.
Operations edits the delivery deadline and shared accepted date, and links to Calendar for scheduling. The
60-day promise is unchanged. Development previews use isolated data; the separately authorized
live schedule reset is recorded below. Production flows are unchanged. Details and current limits
are in [CALENDAR.md](CALENDAR.md). Team scheduling is now current work; bay tracking remains
later roadmap work.

Calendar saves now acknowledge a durable local replica/outbox before background publication. Rapid
edits stay available during uploads; pending snapshots resume after restart with fresh authorization
and conflict checks. Disjoint shared edits merge; material conflicts require explicit review. Accepted dates are shared between Operations and Calendar. Connected
Builder clients poll linked active Estimates every five minutes, using QBO AcceptedDate rather
than observation time. Manual dates remain protected. Calendar uses stable reviewed reservations
and an independently scrolling acceptance queue.
September 14 owner feedback simplified it to one assigned team and scheduled start/ready dates:
no second-team, agreed-date or remaining-hours controls. Parts/vehicle badges replace noisy card
metadata; compact modal bubbles replace the below-board editor, full day areas accept pointer
drops, saved bookings can be moved, and Week/Month mark today. The owner also requested a backed-up
live reset of all 13 bookings/assignments to try scheduling from scratch. See `CALENDAR.md`.
The next owner refinement changes booking to one **Confirm booking** action with live date overview
and inline errors. The project checkbox defaults on, current projects can be removed, and Calendar
has no Shop actions. Month drops prefer an available team; busy dropdown options are marked red
and allow overlapping work only after a named confirmation. Removal retains durable clearing
markers and publishes only the three planning-date fields through Operations.
The toolbar now replaces Find opening/Add job with a read-only next-opening summary. Title and
navigation sit above the grid. Successful save banners are hidden; progress/failure stays inside
Calendar. Retry date update appears only for actual pending Operations date differences.
Toolbar verification: **771 tests passed, 1 skipped**; Calendar and six other selected browser
flows passed. The Projects vehicle-model flow was intermittent (two timeouts, then a passing
diagnostic rerun with unchanged assertions). The preceding 770-test gate passed all eight flows.
See `CALENDAR.md` for details; no unrelated source was changed to investigate the timeout.
The next Calendar correction removes hidden forecast occupancy and stops restarting full labor
from today. Only saved work intervals mark teams busy. Confirm refreshes Operations while
preserving form edits, requires another confirmation if the displayed dates/vehicle set changes,
and still rejects concurrent Calendar edits. Latest changed gate: **773 passed, 1 skipped;
8/8 selected browser flows**, including 73 Calendar tests. No live bookings were modified.
The running desktop process needs restarting to load the Python availability change.
The next owner pass reuses rows for non-overlapping work, allows date-only bookings to use
remaining hours on their requested day, and displays handoff times. Stripes now mean parts or
vehicle unavailable; active builds have a yellow bar; fixed-start/deadline symbols are removed.
Week/Month switches sit below the title, the grid flows with the page, and only the queue scrolls
internally. All-accepted scheduled cards are pale green and cannot be dragged from the queue.
The 10% usable-capacity buffer and partial-day precision remain unchanged. Latest gate:
**776 passed, 1 skipped; 8/8 browser flows**, plus isolated desktop/narrow calendar visual QA.
No live bookings were modified. Restart the app for the date-only handoff change.
The following refinement matches the sidebar to Calendar height, moves Confirm to the bottom
right beside booking history, and uses an in-progress badge without forecast prose. Calendar
and open-modal data refresh every 15 seconds and on app focus while preserving edited fields.
Scheduling-evidence fingerprints ignore harmless polling/revision changes; material changes and
per-vehicle date writes remain guarded. Current-project changes show saved details inline and
allow confirmation without reopening. Verification: **784 passed, 1 skipped; 8/8 browser flows**,
plus an isolated timed-refresh/visual proof. Restart the app once to load these local changes.

The owner's requested live acceptance backfill is complete: 10 vehicles use verified QBO dates;
Walsh's two vehicles preserve the manually supplied 2026-01-12 date. Camp Ripley is unchanged
because its linked Estimate is Pending without AcceptedDate. Read-back verified all original
90 vehicles' scheduling and delivery-deadline fields were unchanged. No release was published.

Calendar verification after direct confirmation and project removal: `tools/verify.py changed` passed
**768 focused tests, 1 skipped, and 8/8 selected browser flows**, including 68 Calendar tests.
Full-cell drops, direct booking, the default project checkbox, month auto-team selection, busy-team
warning/cancellation and removal have browser regression coverage. A separate isolated end-to-end
check verified real project date clearing, rebooking and explicitly confirmed overlapping saves. A separate isolated
26-vehicle check verified scrolling, badges, Week/Month today markers, month drops, modal layout,
and no writes from dragging. The hosted HTTP test loop uses poll to avoid select's descriptor limit
in the combined suite; its auth/HTTP assertions are unchanged. Existing golden masters were unchanged.

September 15 Calendar saves now use a durable local replica and coalescing sync queue. The real
browser regression books, removes and rebooks while date publication is deliberately stalled;
pending edits survive restart and old uploads cannot restore newer local removals. Shared conflicts
have an explicit review path; transient failures retry without locking Calendar. Next opening is
above the grid on the right. Latest changed gate: **798 passed, 1 skipped; 8/8 browser flows**,
including 14 outbox tests. The full release gate was attempted and stopped on the pre-existing
`test_parts_db_contract[root_doc]` catalog/snapshot mismatch; no catalog or golden snapshot was
changed. No release or live-data mutation occurred. Restart the app to load the Python changes.

## Current desktop work — project types (unreleased)

Build / Service / Off-Site Service are implemented in project creation/editing and the Projects type
filter. Existing projects default to Build. Accepted service vehicles use an explicit per-vehicle labor
estimate, optional manual deadline, and selected strip/finishing requirements. Off-site travel occupies
team capacity, and its location/contact are required. All types remain visible in Calendar regardless
of the Projects filter. Operations reads type/requirements from Builder metadata without a shared-list
schema migration; non-applicable workstreams retain their statuses and show N/A.

Service worksheets omit vehicle diagrams by default and show service scope instead of Build equipment
summary tiles. Their final checks do not require warning-light coverage. Independent visits receive
separate file names/folders. The optional Previous Build Design link searches VIN/unit number and stores
reference IDs only; it opens a read-only parts/locations/notes view plus the prior PDF when available.
No source parts, Estimate links, statuses or folder IDs are copied into service work. Further historical
inventory/version tracking is deferred. Final changed gate: **914 passed, 1 skipped; 10/10 browser
flows**, with a visually reviewed service PDF. The release gate remains blocked by the existing parts
catalog contract mismatch. See `POST_MEETING_FEATURE_PLAN.md` for details and verification.

## What is live

- **Desktop distribution:** signed-in team use on macOS and Windows, with CI-built installers,
  GitHub releases, SharePoint release staging, and in-app update detection/download/restart flow.
  Startup and status polling are concurrent and do not freeze the UI behind Microsoft or installer
  network timeouts.
- **Shared team workspace:** SharePoint is the source of truth for agencies, sales reps, presets,
  projects, and drafts. Generated PPTX/PDF files are uploaded by agency/year and can be hydrated on
  another workstation. Export detects prior files for the same vehicle and defaults to replacing
  them after user confirmation.
- **Part Picker and rendering:** the SKU-level Part Picker, guided radio/radar/camera/console flows,
  siren/Howler behavior, custom locations, rich preset round-tripping, manifest grouping, preview,
  PowerPoint, and PDF output are in production use.
- **Parts catalog:** `parts_db.json` currently contains 773 products, 1,339 SKUs, 1,224 QB-linked
  SKUs, 120 part types, and 63 manufacturers. Forty-three products still have no part-type home and
  remain an explicit curation queue.
- **QuickBooks production:** managed OAuth uses the Netlify token broker; the shared Intuit secret
  stays on Netlify and each user's company tokens stay in the OS keychain. Production catalog
  reconciliation runs at startup and every 30 minutes when connected. All 214 Builder agencies were
  migrated to reviewed production Customers.
- **Estimates:** per-vehicle and batch non-posting Estimate creation is live. Creation refreshes
  current Item prices, applies Retail pricing by default, supports temporary Custom pricing,
  allocates Estimate numbers, prevents accidental duplicates, requires or creates the current build
  PDF before attachment, and surfaces actionable failures. Vehicles without unit numbers use a
  stable per-build fallback label such as `Patrol #1`. True QBO Projects are still created manually
  and linked by URL/ID; the batch checklist returns from each setup and revalidates readiness before
  creation.

## Changes shipped after v3.3.2

- **v3.3.3 — build configuration and Estimate workflows:** repaired agency-default preference
  saving; added the second-control-head/microphone and Gamber-Johnson bracket choice behavior;
  automatically adds `LCPHOTO` with an interior light bar instead of offering it on CenCom Core;
  added the Estimate PDF readiness/export flow; and made missing unit numbers non-blocking through
  deterministic, vehicle-stable fallback labels.
- **v3.3.3 — picker search:** a child SKU can make its parent product match, but search results stay
  collapsed. Opening a matched product shows its complete SKU list rather than a filtered fragment.
- **v3.3.4 — guided conditions and light rendering:** guided components can carry their own
  New/Used/Reused status; Used/Reused lines are excluded from Estimates; reused console components
  do not affect the ordered console kit; `UCVDMLTAL00` is a direct single-SKU product without the
  warning-color matcher; DUO RST rear roles render red on the driver/left and blue on the
  passenger/right; and custom-location asset resolution was hardened.
- **v3.3.5 — split assets at custom points:** a neutral custom anchor now falls back to an available
  driver/passenger asset instead of rendering only a red placement dot.

## v3.4.0 release scope

- Quantity-aware custom placement lets the Details tab expose spacing for a
  selected light-head count, and one preview click places or moves the whole horizontal group. A
  four-head group can instead be arranged as two mirrored pairs. Head index and pair identity are
  persisted, so equal-row and paired DUO lights keep the correct driver/passenger asset sequence.
  Older single-point custom locations remain compatible.
- The current picker/output polish set ensures editing a parent no longer lets an
  automatic recommendation replace its restored accessory; 3-inch round lights allocate quantity
  across several locations in one atomic edit, with an independent manifest note for every location;
  Window Tint selects multiple windows and a percentage
  without a vehicle placement and quotes at $65 per window through MISC PART; Gamber-Johnson Core
  and Motorola specialty faceplates quote at $0, OEM plates are omitted, and later faceplates bill
  normally. Picker-facing prices are labeled and calculated as Retail rather than exposing raw QBO
  list values. Agency/project lighting setup defaults can be DUO or TRIO without restricting picker
  choices. DUO component rows combine only in the shop manifest, preserving separate QBO line items;
  color/lens details and row spacing are compacted. Manifest body text is at least 9 pt, the source
  column gives customer-supplied condition/source a deliberate two-line label instead of inflating
  the row, and supporting text on vehicle-render cards is black for higher contrast. Long agency
  titles and dense manifests paginate safely in PDF output. Manifest categories now flow across
  pages instead of forcing one category per page; high-contrast orange section bars separate them,
  repeat on continuation pages, and never render without at least one item beneath them. Concealed
  speakers render faded with a draggable red mounting callout whose saved leader line points to the
  nearest speaker.
  Export order is cover, vehicle views, reference-photo pages when present, manifest, then build
  notes. Customer output omits internal
  QB-import provenance, tint pricing, stale allocation recipes, Install Type, and Other Orders.
  Build notes contain only project notes, installation notes, and delivery requirements.
- The first vehicle-finalization slice includes a focused review modal, current-PDF
  requirement, an expandable passed/warning/blocked checklist, equipment relationship/coverage
  warnings (including Core interface, photo eye, docking motion, radio/camera/expansion, Patrol
  radar/partitions, and front/side/rear warning) and acknowledgement notes, durable
  collaborator-visible status/audit fields, server-side edit locks,
  and reasoned reopening. Shop Documents publication/withdrawal and durable retry are now active;
  re-exporting an already-finalized vehicle prompts before replacing its existing app-owned Shop
  PDF, and declining leaves the prior Shop package untouched;
  explicit concurrent stale-finalization rejection remains Phase 5 follow-up.
- Existing linked QBO Estimates now store a narrow post-write baseline. A changed QBO form raises a
  loud pre-write conflict with readable differences and requires an explicit overwrite-or-create-new
  choice; the service repeats the gate immediately before update so the UI cannot bypass it.
- QuickBooks estimate review now has **Additional charges** after materials: shared
  Patrol/Undercover/Admin/Custom labor and install-supplies presets, per-vehicle overrides, optional
  delivery, and an automatic non-compounding 4% card fee. Exact active QBO Service items are
  resolved from the refreshed cache; missing items or unset required amounts block before write.
- Project Overview cards now surface each individual unit's notes in a prominent shop-note panel;
  notes are clamped to two rendered lines, and only visually overflowing notes become clickable with
  a **Read more** action that opens the complete note in a focused modal. The manual QuickBooks Project setup/link
  walkthrough is available before the unit has a configured draft, while Estimate actions remain
  correctly disabled until configuration. **Finalize design** is always the last card action and changes
  from light green to solid green after design finalization. Generated/copied QBO Project names omit the
  redundant agency and use `Unit {number} | Build {year}` (or the stable build label first when the
  unit number is unknown).
- The build editor now exposes **Load Preset** directly beside **Save as New Preset** in both action
  areas. Its searchable picker refreshes current compatible presets and atomically replaces only the
  active build's parts and placements, preserving vehicle identity and build/project notes.
- Project Manager **All Presets** menus are now literal, unfiltered lists in both new-project and
  Project Details flows; vehicle/build compatibility no longer silently hides choices there.
- Guided-system optionality now covers the relationship that was actually
  over-constrained. A front-only radar can explicitly save its rear antenna as **Not included**;
  this removes the dependent rear-bracket question and rear component while preserving edit
  round-trip. Core radio choices remain required, camera keeps its explicit component selection,
  and console's existing None/dependency behavior is unchanged.
- Guided radio Custom antenna locations now reuse the normal optional vehicle-placement flow, so
  the shop-facing location label remains independent from a saved vehicle dot or free point and
  the synthesized antenna renders on the build sheet. Shared exports now keep customer PDFs in the
  visible agency/year tree while moving editable PPTX sources under
  `_DTM Internal PowerPoint Sources`; the build card opens only the PDF folder. Normal Replace
  exports use deterministic SharePoint filenames, legacy timestamp/folder variants remain
  readable and cleanable, and upload/delete serialization prevents a delayed retry from restoring
  an obsolete ICE-style duplicate. Explicit Keep both exports remain timestamped.
- The canonical part-supply model is included. Drafts, presets, Excel input, picker and
  guided-system components now normalize to **New** or **Customer supplied**, with customer-supplied
  condition New/Used and a required source for newly edited Used records. Legacy New/Used/Reused
  data remains readable; source-less legacy records are visibly flagged until their next edit.
  Customer-supplied lines are excluded from Estimates, console bundle resolution excludes both
  customer-supplied conditions, and manifest/build-sheet comments and used-source callouts are red.
  Intentional PowerPoint golden-image changes are recorded and pass with focused renderer coverage.
- Centralized QuickBooks remains deferred and is excluded from this release. The existing
  per-user OS-keychain connection and stateless OAuth broker remain the only production path; no
  central service is deployed and no production token is moved.

## Current verification baseline

- The v3.4.0 Python suite passes **2,077 passed, 1 skipped, 1 sandbox-only deselected**. The deselected
  macOS updater test writes to Downloads, which this verification sandbox cannot access. Contract
  snapshots and all six PowerPoint render goldens pass.
- The hermetic browser smoke suite passes **28/28**, including tint/round-light allocation, custom
  DUO grouping, accessory quantity and dual-shroud rendering, Overview notes/pre-configuration
  QuickBooks Project setup, finalization, and Estimate review workflows. Round-light coverage includes
  deleting one allocated manifest row and editing the survivor without resurrecting removed lights.
  It reports no console
  errors, external browser requests, or network-guard violations.
- PR checks: import boundaries, dependency audit, high-severity security scan, and test/coverage
  floor are enforced.
- Release v3.4.0 was the protected production baseline for the v3.5.0 work below.

## v3.5.0 release scope

- One app project is now enforced per agency/build year for new and edited records. Existing
  duplicates are reported for review rather than merged by guessing.
- Agencies now carry an editable **Agency Abbreviation**. Defaults use meaningful name initials,
  the county name for county sheriffs, or a short explicit acronym; custom values support cases such
  as ICE and HSI. Agency Manager and new-project search match the abbreviation and recover durable
  project-backed identities when a standalone agency record is absent. In-use agencies cannot be
  deleted, and contact fields remain optional.
- A shared canonical vehicle identity drives the unit-card title, Company/Shop folder and PDF name,
  and generated/copied QBO Project name. Example:
  `2027 SCPD PIU - Patrol - Unit 12 - VIN 123456` (QBO uses pipes). The year folder is
  `SCPD - 2027`; each canonical vehicle folder sits directly below it, without a filesystem
  unit-group layer. Names use the model only, without the
  make; Police Interceptor Utility is abbreviated `PIU`, and F-150 Lightning is shortened to
  `Lightning` in model-only labels. Existing vehicles missing both identifiers
  receive a stable `Pending ID` folder/card suffix derived from `individual_id`; a later VIN renames
  the same stored folder item in place. New individual vehicles still require a unit number or VIN
  before PDF export/finalization. The read-only
  naming migration report includes missing identifiers, legacy outputs, folder changes, duplicate
  projects, and exact manual QBO renames.
- Individual-unit notes are refreshed from the project record into every linked draft/export and
  render in a dedicated **Unit Notes** panel on the cover. The cover's **Light Heads** total now
  counts physical heads across direct/DUO rows, quantity-aware custom locations, Tracer housings,
  Inner/Outer Edge fixtures, and planning-only lights included with pre-lit bumpers. The Granite
  Falls PB450L6 build therefore reports 17 rather than the former incomplete 11.
- Build-reference persistence now presents project photos as assigned or unassigned, with
  unit-group assignment/editing. Removing the last group assignment leaves the photo unassigned in
  the project. New project-wide and individual assignments are not created, while
  existing records at those scopes remain resolvable/publishable with explicit legacy labels.
  The source browser defaults to the current agency, selected make/model, and build type, while
  explicit agency and vehicle/build filters make every app agency's organized Company **Reference
  Photos & Videos** and Shop **Completed Build Photos** reusable without moving sources. Videos
  remain Company-only. The exact year-level Company **Reference Photos & Videos** folder is now the
  physical unassigned-photo inbox: opening a project reconciles direct OneDrive/SharePoint JPG/PNG
  uploads into Project Photos. The Overview has a direct folder action. Removing an auto-discovered
  photo keeps its source file but records an exclusion until the user explicitly adds it again.
  Effective photos render in adaptive, aspect-preserving appendix layouts:
  portraits receive a full-height column, two portraits share a page, and landscapes use one-up,
  two-up, or 2x2 arrangements. PDF photo links prefer the source SharePoint HTTPS URL for Apple
  Preview/browser compatibility and retain a sanitized relative-file fallback. Reference titles and
  10-point notes sit in a translucent dark overlay on the image, reclaiming the former caption strip
  so the aspect-preserved photo can use more of its cell.
- Completed/reference photo viewing now uses responsive thumbnail galleries instead of filename-only
  lists. Exact completed-photo folders are enumerated in a background worker, assigned references
  open immediately from project metadata, and small source previews are cached on disk before any
  exact-source work begins. Exact normalized thumbnails are created only for cards the user is
  viewing. Full-resolution content downloads only when opened and is then retained in the app's
  local exact-media cache for subsequent opens. Normalized thumbnails are shared through
  the app-managed Company Files `Settings/_DTM Photo Thumbnail Cache/v2` area, keyed by source item
  and eTag, so another workstation downloads the small JPEG instead of rebuilding it from the
  original. Shared-cache failures remain a local-generation fallback. A locally synced OneDrive folder is used
  first when present; **Always keep on this device** is an optional full-size accelerator, not a
  prerequisite. Project Overview and archived-project rows expose project reference galleries;
  unit-group headers own reference management, while vehicle cards expose only their applicable
  **View completed photos** action plus exact folder navigation.
  **View completed photos** appears only after a scan confirms at least one supported image in
  the applicable exact **Completed Build Photos** folder. The last authoritative presence result is
  cached locally, so subsequent project paints show the action immediately while the folder refreshes
  in the background; a transient cloud failure does not erase known presence. Project completion and design finalization
  do not imply that shop photography has happened. Hovering thumbnail cards does not transform the card layer, avoiding native-webview
  backdrop compositing flashes. Portrait thumbnails use side letterboxing instead of cropping; a
  versioned cache now regenerates them from original image bytes instead of retaining Graph previews
  with baked-in top whitespace. Startup now compares a persisted fingerprint of saved photo metadata;
  an unchanged catalog performs no preparation and no longer recursively scans all 45 completed-photo
  projects. External media is refreshed only for the project being viewed. Four small-preview workers and six visible-preview
  workers make display-ready files first; three separate exact workers normalize/upload only the
  visible cards that request an upgrade. Startup no longer queues all original photos. The connection pill shows a real discovery/preparation progress
  bar, while any visible gallery photo is promoted ahead of queued work. Completed galleries expose one disabled-until-selected **Use as
  Reference Photo(s)** action, followed by a compact destination-project and optional-unit-group
  dialog. Project-only reuse adds an unassigned project photo; choosing a group assigns directly. The full-size
  viewer is view-only. **Project photos** is now the single project-level surface: its selectable
  thumbnails show assigned/unassigned state and notes and offer Add, Assign to unit group, and
  Remove from project. The source browser overlays **Completed** on Shop photos, uses the canonical
  vehicle name as the primary label, and omits folder-path clutter. Active galleries remove only
  metadata, and empty galleries show one centered Add action. Project completion requires a
  confirmation dialog before moving the record into the Projects **Completed** tab.
- Unit-group **Build Reference Photos** now uses the thumbnail-card gallery rather than the legacy
  filename-row editor. It supports inline shop-note editing, multi-select removal, and an **Add photos**
  picker that keeps multi-select assignment. Project and group counts refresh immediately after edits.
- Thumbnail loading prioritizes four background preview workers and six foreground preview workers
  over the three on-demand exact workers. The first visible cards start immediately and can promote queued work; server waits return
  a retryable preparing response after 2.5 seconds, browser requests have bounded retries, and every
  card ends in an image or an explicit Retry state instead of spinning forever. First-pass progress is
  shown in the connection pill as `Preparing photos ready/total`; failed previews finish the batch and
  report that they will retry when opened instead of leaving progress permanently active. Closing the
  app cancels queued scans/previews/exact work, and thumbnail network stages have short bounds so the
  interpreter cannot drain a thousand-item queue after the window closes. Full-resolution gallery
  loads now run as explicit high-priority background jobs: new thumbnail network work yields, the
  viewer says that the original is downloading and being saved locally, and the connection pill shows
  the active filename. The HTTP request returns a retryable state instead of remaining open for the
  whole download; the backend source wait is capped at 18 seconds and the viewer reaches Retry after
  22 seconds. The shared Company Files JPEG cache remains the cross-workstation thumbnail accelerator;
  full originals are not copied into that shared cache.
- The photo-gallery loading ring is now a reusable app loading indicator and is also used for build
  setup/generation, PDF rendering/export, batch PDF work, estimate PDF preparation, estimate
  creation, reference discovery, and reference-note saves. PDF export keeps the visible spinner through
  PowerPoint generation and conversion until the same completion response that triggers the toast.
- Center-console setup now keeps the exact base SKU the user selected. Adding an armrest, Mongoose,
  or other hardware may show a better-bundled SKU as an optional recommendation, but never changes
  the base without an explicit click. Every selected physical console component persists as its own
  nested manifest/build-sheet row. `console_kit_included` affects Estimate billing only, so a
  covered component stays visible without being billed twice; a `7170-0734-00` base plus selected
  `7160-0220` Mongoose remains those two exact SKUs. Final-design checks also recognize component
  choices retained in older console setup snapshots. Console faceplate synchronization now preserves
  the user's arranged order across hardware changes, explicit base-kit changes, save, and edit.
- Guided Camera System setup now records antenna style (**Whip**, **Cylinder**, **Axon fin**, or
  **Custom**) and antenna location. New setups default to **Rear right roof**; other roof corners and
  an exact custom location are available. The antenna persists as a nested physical component with
  the system's supply status. Older saved camera systems remain complete with an explicit legacy
  not-recorded state until edited.
- Only the actual vehicle `unit_number` and `vin` can become current UI/card identity,
  folder/file/export names, or QBO Project names. Optional replaced-vehicle year, make, model, build
  type, unit, and VIN now have explicit editor fields and render only in the dedicated Existing
  Vehicle card. The cover separates **Build Type** from **Unit #**, refreshes both VINs from the
  current project, and leaves an unknown actual unit blank. Project saves now preserve durable nested
  Company/Shop folder IDs, publication state, QBO links, outputs, and finalization state on the
  backend, while omitted replaced-vehicle keys from older clients are preserved and explicit edits
  or clears are accepted. This prevents a partial browser edit from orphaning an owned folder or
  silently erasing existing-vehicle metadata. All six PowerPoint goldens were intentionally updated
  after focused actual-vs-existing regression coverage and a 13-page Granite Falls PDF review.
- Concealed-speaker callouts now say **Speaker behind grille/bumper**, use a text-sized translucent
  red tag, and retain opaque white text. Quantity-aware custom points still draw every configured
  head but contribute only one per-line legend card, preventing a six-head grille row from being
  listed six times with `Qty 6` on the same view.
- Concrete vehicle models found in the historical-photo import are now assignable configuration
  entries even before their vehicle artwork is supplied: Blazer EV, Expedition, F-150 Lightning,
  F-550, Harley, Jeep, Mach-E, Ram 1500, Silverado, Silverado 3500, and Van. They are visibly marked
  **artwork pending**, reuse an existing geometry only as a temporary layout source, and clear that
  marker after all four external images are added. Historical case variants resolve without a data
  rewrite. Ambiguous `Vehicle` and mixed `Tahoe & Silverado` records remain unresolved by design.
- Build cards surface the canonical identity and consolidate actions under **PDF Options**,
  **QuickBooks**, direct photo-gallery buttons, and **Folder options**. User-facing PowerPoint actions/status clutter is removed; PPTX is a
  local conversion artifact and new shared uploads reject it. When one of the compact action menus
  is open, the first click elsewhere closes the menu without activating the underlying card or
  button; selecting an action inside the menu closes it immediately.
- Company per-vehicle PDF folders and finalized Shop PDF/reference packages are active with
  durable item IDs, exact ownership, retry state, and item-ID folder relocation. Reopening withdraws
  only app-owned Shop items and never enumerates or changes **Completed Build Photos**.
- Independently gated lifecycle provisioning creates Company **Vehicle Project Database** and Shop **Shop
  Project Database** agency/year/combined-reference folders at project save, and creates each
  known individual's vehicle/photo folder directly under its project year, using stable placeholders when
  necessary. Folder metadata has
  durable pending/retry state, and photo menus can open exact Company or Shop folders locally or in
  SharePoint. Provisioning is independently gated from PDF cutover/publication by
  `company_folder_provisioning_enabled` and `shop_folder_provisioning_enabled`.
  Standalone Agency Manager and imported QBO Customer records are not provisioning targets. Before
  reconciling a renamed vehicle, the provisioner resolves it by durable Graph item ID; manual
  SharePoint moves therefore refresh saved paths instead of recreating a stale parent.
- Past-photo data uses ordinary sparse agency/year projects with only the real model/build-type/unit
  data and photos that are known—there is no historical vehicle marker or label. A reversible
  project-level completion state moves these projects out of the active list into a collapsible
  Projects **Completed** tab, retaining the collapsible Agency → Build Year grouping.
- Additive Company/Shop lifecycle provisioning is now enabled for the approved folder skeletons.
  The two roots and all nine current project trees were created and verified; 23 existing vehicles
  use stable placeholders. Fergus County Sheriffs Department, Homeland Security Investigations
  (HSI), and US Imigration & Customs Enforcement (ICE) were restored under their original durable
  agency IDs. Their older installed-app records were then recovered locally, preserving the original
  contact/address/default-preference data and production QBO Customer links (Fergus `433`, HSI
  `444`, ICE `446`) without calling or writing to QBO. The final enriched records were explicitly
  approved and successfully mirrored to shared settings. The reviewed naming migration adopted the existing
  agency/year/vehicle roots, renamed the same saved SharePoint items to the abbreviation-qualified tree,
  restored ICE's `&`, and reverified 78 saved Company/Shop year-or-vehicle item IDs. PDF
  publication/cutover is now enabled after the first live finalized package was hash-verified. The approved historical Completed Build Photos migration is now
  complete; legacy source cleanup remains a separate future decision.
- **Provisioning scope correction:** the first live pass incorrectly interpreted all 218 saved
  Agency Manager/QBO Customers as build-project agencies, producing 219 roots in each new database.
  A read-only item audit found 184 unwanted Company roots and 184 unwanted Shop roots; all 368 were
  rechecked empty and deleted by exact item ID after approval. Runtime provisioning and retry are
  now project-scoped, including a regression test that QBO import cannot schedule folders. The same
  184 standalone agency records had only their operational folder state cleared locally and in
  shared settings; final verification found 36 approved roots in each database.
- **Legacy Build Photos inventory:** the untouched source tree has 28 agency folders, 46 source
  build/photo groups, and 1,043 files. Forty-five groups explicitly name 2025/2026 and consolidate
  to 34 completed agency/year projects across 27 confidently mapped existing agencies. The 90-file
  `Benton-Stearns Negotiator Van` folder became the new joint `BSNV` agency and 2025 project,
  bringing the migration total to 35 completed projects containing 46 sparse build groups. All
  1,043 source files were copied into their normal **Completed Build Photos** destinations and
  verified by per-tree relative path and byte size; source and destination each total
  11,934,028,588 bytes. All 35 local/cloud project records match exactly. A comparison of all 1,120
  source items against the pre-migration manifest found zero ID/path/size/eTag changes. The legacy
  source tree therefore remains the rollback/reference copy until a later explicit cleanup decision.
- **Edina/Walsh enrichment repair (2026-08-28):** Walsh County's user-reviewed Tahoe and Silverado
  3500 split already matched its stored Company/Shop item IDs and needed no further write. Edina's
  user-reviewed Blazer EV Patrol, PIU K-9, and Lightning Unmarked folders were reattached by durable
  ID after out-of-band moves, and the Lightning subtree was renamed in place. Shop contents remained
  exactly 7 files / 48,834,978 bytes, 24 / 382,827,034, and 19 / 325,923,152 respectively. The new
  empty Blazer vehicle adopted its existing empty folder. Local and shared Edina project records
  match exactly. Seven sparse
  historical groups still use `Vehicle` pending owner-supplied models: City of Otsego 2026 Truck
  Rack; Pequot Lakes Fire 2025 Grass Rig; Cohasset Fire 2026 Truck; Sartell Fire 2026 Chief Truck;
  Stearns County Sheriff 2025 K-9; Little Falls Fire 2025 Grass Rig; and Foley Fire 2025 Grass Rig.
- **Manual QBO naming follow-up:** the Accounting API cannot rename true QBO Projects. Rename these
  five in the QBO UI, preserving each Project ID: `810619971` → `2026 ICE PIU | Patrol | VIN
  C43753`; `811152751` → `2026 ICE PIU | Admin | VIN C43847`; `810150700` → `2026 Fergus PIU |
  Patrol | Pending ID 737295F1`; `809850876` → `2026 Custer Durango | Patrol | Unit 123`; and
  `70995` → `2026 GFPD PIU | Patrol | VIN B76739`. The 23 pending IDs remain intentional until real
  unit/VIN data becomes available. Seven legacy export filenames adopt the new canonical stem on
  their next generated export; no old output file was renamed or deleted by the folder migration.
- **Granite Falls folder reconciliation completed (2026-09-01):** there is one logical 2026 Patrol
  build. The current vehicle has actual VIN `…B76739` and no actual unit number; unit 03 / VIN
  `…B19177` belong to the replaced vehicle. The app-owned Company item
  `01YX7XC2M4ZVDCXPO26NA3CF6S53C5HDZK` and Shop item
  `01YX7XC2KCS2MJPTDEDFGI5QNOQJRRPAVW` were renamed in place to
  `2026 GFPD PIU - Patrol - VIN B76739`. Exact Graph enumeration proved the separate Unit 02
  Company/Shop folders contained no files (the Shop copy had only its two standard empty photo
  subfolders), so those two obsolete items were deleted to the SharePoint recycle bin. The linked draft was refreshed:
  its actual VIN and replaced-vehicle unit/VIN now render in their correct cards. Existing vehicle
  year, make, model, and build type remain blank until the user enters the known values. The stale
  project note suggesting the new unit might be 02 or 03 now states that its unit number is unassigned.
- **Company/Shop publication activated (2026-09-01):**
  `company_vehicle_folders_enabled` and `shop_publication_enabled` are true in the active and bundled
  cloud configuration. Retry sweeps catch pre-cutover exported/finalized records when their exact PDF
  exists locally. The finalized Granite Falls VIN `…B76739` package was published live: Company Files
  contains the canonical PDF; Shop Documents contains the same PDF plus all seven assigned unit-group
  reference photos. Both remote PDFs and all seven remote photos match the local sources by SHA-256,
  **Completed Build Photos** remains empty/untouched, and the published item IDs/status were mirrored
  into the shared project record.
- **Unit-group folder layer removed live (2026-09-02):** all 78 Company and all 78 Shop vehicle
  folders were moved by durable item ID directly beneath their agency/year folder. Before mutation,
  every one of the 114 persisted group folders was verified to contain only its expected vehicle
  items; immediate vehicle contents were snapshotted by item ID, size/hash, and nested photo count.
  The post-move comparison found zero vehicle-path, PDF/reference-path, content, or shared-record
  mismatches. All 114 now-empty persisted groups and six untracked empty pre-enrichment Edina groups
  were then removed to the SharePoint recycle bin. Final verification found 78/78 vehicle items in
  each library, zero `Build(s)` children beneath any project year, zero surviving deleted IDs, and
  exact local/cloud JSON equality for all 45 projects. The rollback/audit snapshot is in
  `/private/tmp/dtm-flat-folder-migration-BqfxjI` on the migration workstation.
- **Operations and lifecycle production expansion (v3.6.0, 2026-09-08):** the role-gated Operations tab
  uses the validated live SharePoint current-row/event lists for 78 vehicles. Project-wide and
  individual one-click statuses preserve per-vehicle history; scheduling accepts any subset of its
  four optional dates. Parts now includes a dated **Ordered** milestone before Partially Received,
  Received, and Parts Ready. Statuses are white when unstarted, light yellow while intermediate, and
  green at each workstream's finished state. Vehicle Availability now finishes at **At DTM**;
  **Delivered** is the final Final Finish step. The schema-v4 upgrade appended that choice to the
  live `FinalFinishStatus` column and revalidated both lists without renaming or adding a column.
  Marking every exact project vehicle Delivered automatically completes the project. Project saves
  create or refresh Operations projections, lifecycle changes mirror by opaque ID, inactive rows are
  hidden without losing history, and deletion cascades exact Operations records before deleting the
  Builder project. The Projects viewer is one count-aware **Active / Inactive / Completed** surface
  with per-tab search, a single derived Active workflow badge, and a three-dot lifecycle/delete menu.
  Inactive projects support an optional reason and reactivation, while Completed retains Agency →
  Build Year grouping and reversible reopening. Either project vehicle selector can create and immediately
  select a shared Make/Model vehicle with artwork pending.
- **Post-v3.6.0 working tree:** a completed project no longer blocks a new active project for the
  same agency/build year. Completing that later project stops at a side-by-side vehicle comparison
  with Cancel, Merge, or strongly confirmed Overwrite; merge keeps distinct stable vehicle IDs and
  Operations history. The QuickBooks menu now connects existing Estimates rather than Invoices.
  Connection is verified and read-only, writes the last-known status/check time to SharePoint
  Operations, preserves prior manual acceptance, and is visibly separate from the guarded Update
  Estimate action. The v3.6.0 package omission of the two non-secret Operations list GUIDs is also
  corrected; existing installations forward-merge them on first launch after the fix, restoring
  both the role-gated Operations tab and Operations-derived project workflow badges.
- **v3.6.2 — project workflow split and cleanup:** Projects now exposes Started / Active / Inactive / Completed. Started
  contains durable-active projects until every current Operations vehicle is accepted; Active is
  the fully accepted set. Active projects with all parts Received/Parts Ready and all vehicles At DTM
  sort first, then each group sorts by its earliest Must Deliver On date with undated projects last.
  Selected tabs use yellow/green/red/solid-green lifecycle tones, and Active rows display the deadline
  used for ordering. A live opaque-ID audit also removed the deleted Seth Test project's exact three
  Operations rows and three creation events; a fresh comparison found zero project or vehicle orphans.
  The release's first large-file SharePoint upload received a transient Graph 503 and succeeded on
  retry; the workflow now automatically retries temporary 429/5xx and network failures for future
  release-note and installer uploads.
- **v3.7.0 — Operations clarity and connected QBO refresh:** connected QuickBooks
  startup and 30-minute refresh now imports the full safe Customer profile into Agencies as well as
  reconciling Items; completing OAuth wakes that worker immediately, and unchanged agencies are not
  rewritten or re-mirrored. Operations now uses Started / Active / Completed while retaining and
  hiding inactive history until reactivation, with one compact workflow badge in each
  collapsed row instead of six status summaries. Project progress badges are gray before Ready to
  Build, blue at Ready to Build, yellow through Build, light green from Ready for QC, and solid green
  at Ready for Delivery. A failed Operations fetch now retains the last accepted project
  classification instead of temporarily moving all durable-active work to Started. Bay tracking and
  project/vehicle team assignments are documented as post-scheduling-pilot additions using durable
  neutral IDs and later optional Entra linkage.
- **v3.7.0 — role and scheduling gates:** every recognized operational role can
  read Builder project context. Sales (`BuilderEditor`) can edit Projects, Estimates, Acceptance,
  Vehicle Availability, and Parts but cannot schedule or change downstream production. Shop can
  edit only Build / Shop, Tray, and Final Finish. The browser hides disallowed controls and the
  local server rejects direct legacy Builder mutations that bypass the UI. Shop can inspect draft
  equipment and build notes in a read-only view. Active Operations now has All / Unscheduled /
  Scheduled subfilters; Scheduled is ordered by Scheduled Week.
- **Local verification policy (updated 2026-09-15):** iterative work runs only one relevant
  pytest file with `--maxfail=1`. Never autonomously run browser smoke tests during normal editing
  or small feature additions. `tools/verify.py changed --skip-smoke` requires an explicit owner
  request for pre-commit verification. Full browser runs and `tools/verify.py release` are strictly
  pre-release checks. Root `AGENTS.md` supersedes older verification guidance in plans and handoffs;
  CI continues to run the full suite and coverage floor on every PR and main push.
- **v3.7.0 — default work queue:** Projects and Operations now open on Active.
  The Operations read boundary also excludes projects whose authoritative Builder lifecycle is
  Inactive, even when an older Operations projection still incorrectly says Active.
- **Phone-client foundation:** the exact `DTMOperationsRequests` append-only queue was created and
  revalidated in the production DTM Fleet site on 2026-09-09. Its durable GUID is
  `3a821086-93b0-45ca-97fc-4b4a4caeb940` and ships in the bundled cloud defaults. Phone users will
  write only pending normal-forward requests; the standard SharePoint Power Automate processor owns
  current/event projection, revision conflicts, and terminal request results. The processor flow
  `DTM Process Operations Request` (`b882a0d9-0ad0-4d90-ac7a-b3b459954a51`) is assembled and saved
  Off. Flow checker reports zero errors and only the expected off-state warning. It remains pre-pilot
  pending terminal connector-failure handling, recovery confirmation, and the controlled validation
  matrix documented in `POWER_APP_PHONE_CLIENT.md`. No Power App has been created; start that work
  in a fresh session after the processor pilot gate.
- Cloud-off verification for this working tree passes **2,396 passed, 1 skipped**; the one skipped
  export is platform-dependent. The updater test that writes a fake installer to the user's
  Downloads folder also passed in its approved environment.
  Contract snapshots
  remain unchanged. All six PowerPoint goldens were intentionally re-recorded after focused tests and
  visual PDF review. Continuous manifest pagination changed the golden slide counts (admin draft,
  patrol draft, realistic workbook, full build, location sweep, Tuesday sample) from
  12/12/13/18/34/11 to 11/11/11/17/34/9; the unchanged 34-page location sweep remains row-density
  bound rather than category-bound.
  The full browser smoke suite passes **28/28** with no console, external-request, or network-guard
  errors; the preview drag flow also explicitly verifies callout-offset persistence and nearest-
  speaker leader selection. Focused tests cover adaptive mixed-orientation pagination and matching PDF link geometry;
  a representative twelve-photo wide-screen PPTX/PDF render was visually reviewed across
  portrait-plus-landscape, two-portrait, four-landscape, and three-landscape pages.
  A dense full-build manifest and a moved two-speaker callout were separately rendered to PDF and
  visually reviewed for category continuity, non-orphaned headings, line visibility, and target choice.
  The responsive completed-photo gallery, file-presence-driven completed-photo actions, fast-preview/exact-cache tiers,
  real-file portrait bounds, assigned/unassigned project-photo round
  trip, destination-project/optional-group dialog, full-resolution viewer, lifecycle-tab actions, and
  pending-image Vehicle Manager cards were also visually reviewed in the cloud-off local app.

## Roadmap position

| Area | Status | What remains |
|---|---|---|
| Phase 0 — foundation | Complete | Preserve the guardrails while retiring remaining shims deliberately. |
| Phase 1 — cloud readiness | Complete | No new foundation work required. |
| Phase 2/2.5 — cloud collaboration/distribution | Complete and live | Operational hardening only; monitor cross-instance sync/export behavior. |
| Phase 3 — canonical parts DB + intelligent picker | Substantially complete and live | Curate the 43 unhomed products, finish low-priority picker polish, and add a reviewed queue for future QBO catalog changes. |
| QuickBooks production track | Complete and live | Manual QBO Project creation remains; bank-transfer fee remains a documented QBO follow-up because the Accounting API cannot set it. |
| Phase 4 — remaining consumer migration | Next architectural milestone | Move the remaining workbook-era domain consumers to `parts_db`, then reduce `workbook_rules.json` to layout-only data. |
| Kit/component modeling | Partly expressed by guided builds, not generalized | After the parts-DB repository seam, define generic SKU-kit storage and Estimate expansion/billing behavior. |
| Phase 5 — generalized light model | Partially delivered through picker-specific flows | Consolidate remaining legacy light naming/color assumptions into canonical domain rules. |
| Phase 6 — arbitrary views | Open | Remove remaining four-view assumptions before adding more interior/top-down views. |
| Phase 6.5 — interior light bars | Open/high user value | Model driver/passenger halves and render configured lightheads instead of static bar images. |
| Phase 7 — free-form vehicle wizard | Partially realized by the current Part Picker | Complete only after canonical consumer/light/view work removes legacy dependencies. |
| Phase 8 — Parts Manager | Editing MVP live | Finish hierarchy/curation polish; decide a separate high-frequency inventory store before quantity tracking. |
| Phase 9 — serial tracking | Open | Add per-project serial numbers for parts marked serialized. |

## Recommended next sequence

1. **Use the activated per-vehicle Company PDF and finalized Shop package paths as the production
   baseline.** The first Granite Falls package, its seven assigned reference photos, and both PDF
   copies were byte-for-byte verified; the legacy Build Photos source remains untouched. Existing
   true QBO Project names still require the report's manual rename checklist before those naming
   changes are complete.
2. **Keep centralized QuickBooks Phase 3A deferred and out of production.** No cloud registration,
   deployment, authorization, or token migration is currently planned. The complete but excluded
   experiment is preserved only on local branch `codex/central-qb-backend-wip` at `f5ac223`; do not
   merge or delete it unless the owner explicitly resumes that design.
3. Preserve the longer-term parts-DB consumer migration, catalog governance, visible curation queue,
   interior-light-bar work, and generalized kit/light/view roadmap behind the approved feature plan.

## Safety rules that remain active

- Run development cloud-off unless deliberately testing SharePoint. Cloud sync can replace local
  configuration, including `parts_db.json`.
- Never store QuickBooks tokens or the Intuit client secret in the repository or SharePoint.
- Keep QuickBooks Estimate creation and later PDF attachment as separate writes; never retry an
  Estimate automatically because attachment failed.
- Do not move golden outputs merely to make tests green. Intentional renderer changes need focused
  behavioral coverage plus a representative export check; reserve owner review for ambiguous or
  high-impact visual redesigns rather than every digest update.
