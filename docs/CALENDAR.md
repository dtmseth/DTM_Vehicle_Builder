# Calendar and stable team reservations

Unreleased scheduling revamp, 2026-09-14. Supersedes the earlier automatic-replanning behavior.
Owner decisions: **no proposed spots or pre-acceptance reservations**; accepted projects use the
nearest available opening on the scheduler's selected team. The September 14 follow-up simplifies
the booking to **one team, scheduled start and calculated ready date**. There are no separate agreed
date or remaining-hours controls.

## Acceptance queue and booking

Calendar reads active accepted Operations vehicles. The independently scrolling sidebar groups
unscheduled vehicles by exact project ID in earliest acceptance order; **All accepted** also includes
reserved vehicles with a pale green background. Those entries open the existing booking on click
and cannot be dragged from the queue; project headings drag only when unscheduled vehicles remain.
Cards show a readable vehicle/unit label, parts and vehicle-availability badges,
and acceptance date. They omit source-system labels, missing-unit placeholders and repeated VINs.
Missing acceptance dates appear under review, never at a guessed date. Manual acceptance and QBO
AcceptedDate semantics are unchanged.

Select a card to open a compact modal bubble. Assigned team and scheduled start are the primary
controls; the ready date and included vehicle dates update in the same modal as details change. Job type and labor estimate are under
**Advanced**, alongside acceptance/deadline edit actions and a known VIN. Accepted date and delivery
deadline are visible context outside that disclosure. There are no agreed-date inputs, remaining
hours, fixed-start checkbox, or second-team selectors. Shop Start/Finish actions are available only in Operations.

A blank start finds the nearest free working-time opening on the chosen team. A specified date
uses the first full-duration opening starting on that day, including remaining hours after another
build ends. If no such gap starts that day, it retains the requested day and exposes conflicts
instead of silently moving to a later date. Unchanged saved starts retain their exact time. The modal
and card tooltip show times for partial-day handoffs. Saved reservations
stay fixed. A **Schedule the rest of this project** checkbox is checked by default. It includes the selected
vehicle plus accepted, unscheduled siblings, placed sequentially on the selected team. The modal
shows every included vehicle and its dates. Unchecking books only the selected vehicle; already
booked siblings keep their dates.

Pointer dragging supports unscheduled sidebar vehicles, project headings with unscheduled vehicles,
and saved bookings on the grid. The entire Week
day cell accepts drops, including the area over a booking, rather than only its plus control.
Month drops keep the preferred team when it is available, or select the next available active
team. Availability checks the full proposed work duration against the visible booked work intervals.
Busy teams show a red dot and Busy label in the dropdown. Choosing a busy team opens a warning
naming the overlapping project(s); cancellation restores the previous selection. Every drag
opens the booking modal without saving. Click/keyboard forms
remain available. Dialogs support Escape, outside-click dismissal and contained keyboard focus.
Both views mark today's date. Calendar uses the available desktop width. Only the queue
scrolls internally; its desktop height tracks the full Calendar column through a ResizeObserver.
The entire grid flows with the page. On narrow stacked layouts, the queue stays bounded to 280px.
Bookings on the same team reuse a row when their displayed work intervals do not overlap.
Month also displays partial-day widths and keeps team rows consistent across its weeks.
Actual overlaps occupy additional rows; a handoff prefers the row whose previous build just ended.

The standalone **Find opening** and **Add job** buttons are removed. A **Next opening · team · date**
summary shows the earliest full standard strip-and-build opening among active teams, or for the
selected team filter. Its tooltip identifies that duration assumption. It is calculated read-only
from today's capacity and existing reservations; unresolved legacy dates show an
unavailable explanation. Existing custom bookings remain readable/editable/removable.

The month/week title, adjacent arrows and Today button sit directly above the calendar grid in its
own column. Week/Month buttons sit on the next line below the title. Save progress and failures are scoped to Calendar. Successful/idle saved-status banners
are hidden, including when reopening the app. **Retry date update** appears only when saved Calendar
and Operations planning dates differ, and is hidden during an active save. Ordinary saves publish
those dates automatically; this is recovery for interrupted/failed publication.

Booking stripes mean parts are not received/ready or the vehicle is not at DTM; an unfinalized
design alone does not produce stripes. Ready vehicles have solid team-colored cards. Active
builds have a yellow bottom bar; warnings no longer add a red bar to every affected booking.
Historical/completed work does not become striped merely because the vehicle has left.
Fixed-start symbols are removed, and deadlines use the word **Deadline**.

## Capacity and warnings

Initial teams remain David's Team (two people, 60 build / 6 strip labor hours), Josh's Team (same),
and Michelle (one person, 40 build / 6 strip hours). Defaults are 8 hours/person/weekday with a 10%
buffer. The buffer reduces usable daily labor capacity: two people × eight hours × 90% gives
14.4 schedulable labor hours per day. Partial days remain available; estimates are not rounded
to whole days. This setting is unchanged pending the owner’s decision about whole-day rounding.
Labor is summed across the selected team's people. A saved manual estimate survives reassignment.

The interval search fills gaps before later reservations and retains partial-day capacity. Weekends,
shop closures and team days off consume no capacity. Four default working hours of final checks
use the existing unlimited shared finishing group, without occupying a build team. This remains a
modeling assumption, not a new QC staffing model.

Saved dates/segments do not move on refresh, new acceptance, readiness changes, day rollover,
absences, capacity settings or completion of other work. Current capacity assumptions calculate a
separate working forecast. Warnings identify late delivery deadlines,
missing parts/vehicle/design, retired teams, closed reserved days, and conflicts with named jobs.
Only saved work intervals reserve team capacity. Forecasts are advisory: they never add hidden busy days.
Without an explicit legacy remaining-hour correction, a forecast starts at the saved start; it does
not restart the entire labor estimate each day.

Operations retains Start build / Finish build. Completed build work releases build capacity without
moving later reservations; final completion retains the saved historical display. In-progress work
uses the saved estimate anchored to the saved start; elapsed time is not
measured work. There is no hours-worked or remaining-hours entry in Calendar. Existing stored
remaining-hour corrections remain readable for compatibility.

## Review, save and recovery

**Confirm booking** validates and saves directly from the booking modal. There is no second review
screen or required typed explanation for ordinary bookings; history records the confirmed action.
Server-calculated availability and the included-vehicle overview are already visible. Validation
errors remain in the modal. Confirm sits at the bottom right, with expandable booking history on
the left. Build in progress is an amber badge, and forecast prose is omitted from Calendar dialogs.
The visible Calendar refreshes every 15 seconds and when the app regains focus, including while
a booking is open. Readiness, deadlines and availability update; untouched booking fields follow
new saved values while edited fields retain user input.
Confirm fetches current Operations data while preserving typed edits;
unrelated status/QBO refreshes no longer require closing the modal. If refreshed data changes the
proposed dates or included vehicles, the updated overview requires another Confirm. An unrelated Calendar edit is refreshed automatically. A change to the current project’s booking
or team settings displays the currently saved details and keeps typed entries, requiring another
Confirm without closing/reopening. Preview/save tickets protect scheduling evidence; per-vehicle
publication still uses exact Operations revisions. Busy-team overlaps require a named warning confirmation; this opt-in
is bound to the exact proposal ticket and recorded in history. It permits intentional overlapping
work without moving existing bookings. Invalid/nonworking dates, unresolved legacy imports, stale
revisions and permission failures still block saving. Settings and pending-publication recovery
retain their separate impact/sync view.

**Remove project from schedule** confirms the number of affected current bookings, releases them,
and clears their team assignments. Accepted vehicles return to the queue. It clears only planned
start, Scheduled Week and target finish via the existing revision-checked Operations commands;
acceptance, deadlines and actual Shop progress remain intact. Released entries persist as markers
so an interrupted date-clearing publication can be resumed from a fresh snapshot. Historical
completed projects are excluded. Standalone custom jobs have the same removal action.

Team settings also use this preview/review path. Review displays affected reservations and forecast
risks; settings changes leave held dates intact. Rename teams freely and retire them instead of
removing stable identities.

Save validates the booking against the local replica, then atomically persists the visible Calendar
and its pending sync intent before acknowledging success. Further local edits remain available while
a single background worker conditionally publishes immutable snapshots and revision-checked Operations
date commands. Pending work coalesces to the latest desired state while retaining every booking history
entry. The initial cache load may require the provider; subsequent planning and saves use the local
replica. Calendar history records actor, time, explanation and before/after values; date events carry
the booking explanation. Team/settings-only changes remain in Calendar history.

Published fields retain their meanings: `planned_start_date` is the reviewed working start,
`scheduled_week_of` is its Monday, and `target_finish_date` is the reviewed ready date. Forecast
changes on read never publish anything. The existing computed/manual delivery deadline is separate.

A partial publication failure retains local changes and successful Operations events. Transient sync
failures are visible and retry automatically while the app is open; the durable outbox resumes after
restart. Retries recognize acknowledged shared snapshots and publish only outstanding dates.
Disjoint shared bookings merge automatically. Conflicting bookings, new occupied capacity, or material
Operations changes pause publication and offer **Review sync conflict**, showing shared versus local
bookings and requiring explicit overlap approval. Review tokens bind the current local/shared state.
Per-vehicle revisions, shared ETags, silent worker authentication and role revocation checks remain in
force. An old upload cannot restore a booking removed locally while it was running.

## Persistence and compatibility

Cloud location remains `Settings/calendar_plan.json` outside ordinary settings mirroring; cloud-off
location is `workspace/calendar/plan.json`, with prior local versions in `calendar/history/`.
The immediate local replica and durable pending queue share a single version-1 journal under
`workspace/calendar/outbox/`, keyed by cloud/local mode, owner and cloud configuration. Shared
publication adds a snapshot identifier for lost-acknowledgement recovery; it is excluded from the
visible local document and preview revision. The legacy `calendar_save_jobs.py` module remains
for compatibility tests; production Calendar routes use `calendar_workspace.py`.

The reservation document uses **schema version 2**. Settings retain their existing schema version 1.
Version 1 documents remain readable. Saved `last_plan` intervals become protected legacy bookings;
reads preserve those recorded dates without creating additional commitments.
A reviewed save displays the format upgrade and writes version 2; older Calendar clients reject
that version. Reads never migrate storage. Operations-only dated bookings without a known Calendar
team appear as reconciliation items and block new reservations/opening quotes until reconciled.
They are not silently assigned a team or treated as free capacity.

Each saved job retains team IDs, kind, original labor hours/manual flag, optional remaining labor,
start date, last approved display/segments, and
change reason. Legacy `promised_start`/`promised_ready` metadata stays readable but is no longer
automatically created, shown or used for scheduling warnings. Legacy joint-team bookings stay
readable and occupy both teams, but new booking, project and opening requests must select exactly
one team. The document's `history` holds explained booking and settings changes. Temporary
preview markers and reason-binding fields are removed before storage. The service validates date,
team, labor, acceptance, overlap, reason and stale-revision constraints; calculated dates are never
accepted directly from a client.

## Permissions and scope

Reads and opening queries use `operations.view`; all planning/settings/publication require
`operations.schedule.update`, enforced server-side. Existing Sales and Shop permissions remain.
The opening query uses the existing Calendar preview route with a read-only operation; it does not
introduce an unclassified route. No new SharePoint list, consent scope or production flow is used.

The owner separately requested and received a backed-up reset of 13 live bookings and team
assignments. This UI refinement does not publish scheduling changes, release, commit or deploy.
Date-specific individual-worker rostering, optimization, automatic customer notifications and
cross-project cascade editing remain outside this first version.

## September 14 refinement verification

`tools/verify.py changed`: **762 passed, 1 skipped; 8/8 browser flows**. Calendar's 62 tests include
single-team validation, queue status/deadline context and compatibility with legacy promise data.
Browser regressions cover full-height day drops, moving saved bookings, modal dismissal, absence
of removed controls, and no persistence before review. A separate isolated 26-vehicle visual check
verified sidebar scrolling, badges, Week/Month today markers, month drops and narrow layout, with
no browser errors or provider egress. The combined run exposed select's file-descriptor limit in
an unrelated hosted HTTP test; switching that test loop to poll preserved its assertions and passed.

## Direct confirmation and removal verification

`tools/verify.py changed`: **768 passed, 1 skipped; 8/8 browser flows**, including 68 Calendar tests.
New coverage checks full-duration team availability, explicitly confirmed overlap tickets, continued
blocking of invalid dates, sibling inclusion, project removal, protected Operations fields,
interrupted clearing recovery and rebooking. Browser coverage includes direct confirmation without
a second review, default checkbox behavior, month fallback to a free team, red busy options,
named warnings/cancellation and removal. A separate isolated end-to-end check also saved an actual
confirmed overlap, preserved the original booking, removed/rebooked a two-vehicle project and
verified its Operations planning dates. No provider egress or live schedule changes occurred.

## Toolbar and recovery visibility verification

The first changed gate passed **770 tests, 1 skipped, and 8/8 browser flows**. After the conditional
retry-button refinement, Python passed **771 tests, 1 skipped**; Calendar's browser flow passed.
The combined browser run was 7/8 because the unrelated Projects vehicle-model modal timed out.
Its first standalone retry also timed out, then a diagnostic rerun of the unchanged flow passed
(all assertions, no console errors or egress), so this remains an intermittent Projects flow.
No unrelated production/test source was changed for that investigation.

Calendar coverage checks the team-filtered next-opening summary, removed toolbar buttons, hidden
success status, local banner containment, and hidden retry action when dates match. Domain tests
verify standard-duration openings, legacy reconciliation blocking, and pending-date counts for
both booking and removal. An isolated visual/end-to-end run verified title/grid alignment,
neighboring navigation, banner behavior across tabs, and the prior booking/removal/overlap flows.


### September 14 — busy days and stale Operations form correction

Removed forecast intervals from both next-opening searches and busy-team conflict checks.
Forecasts without explicit legacy remaining-hour evidence no longer restart full labor at today.
Regression coverage verifies rollover, advisory overruns, shared final checks, and an exact
partial-day opening at the saved build end. Existing saved bookings are unchanged.

Confirm now reads fresh Operations data before creating the exact preview ticket. Browser
coverage changes another vehicle's Operations revision while editing and verifies direct save
with the typed date intact. A concurrent Calendar edit still blocks and preserves both the
new saved booking and unsaved form values. An additional isolated browser proof verifies that
a changed included-vehicle set updates the overview and requires another Confirm before writing.
Preview-to-save concurrency checks and audited per-vehicle date publication are unchanged.

Verification: `tools/verify.py changed` — **773 passed, 1 skipped; 8/8 browser flows**.
Focused Calendar tests: **73 passed**. The extra isolated browser proof passed with no page
errors or external requests. No production data/reset/migration/release was performed.
Restart the existing desktop process to load the Python change.


### September 14 — rows, handoffs, status styling and scheduled queue entries

Date-only placement now uses a partial-day opening when the entire proposed work duration fits
and starts on the requested day. A full day or later collision still exposes a conflict rather
than moving the requested date. Regression tests cover the exact handoff, unchanged prior work,
full-day busy behavior and buffered versus unbuffered partial-day capacity.

Week and Month pack adjacent team bookings onto the same row, using separate rows for genuine
overlaps. Month retains time-of-day widths and stable team rows. Styling follows readiness and
in-progress status, rather than treating all warnings as a red bar or unfinalized design as
missing materials. The scheduled queue entries are green, readable, and non-draggable.

Verification: `tools/verify.py changed` — **776 passed, 1 skipped; 8/8 browser flows**, including
**76 Calendar tests**. Browser regression covers adjacent geometry, no internal grid scroll,
view-switch position, saved queue entries and moving an existing calendar booking.
An additional isolated 32-vehicle proof passed exact noon placement through drag/confirm,
overlap-row placement, readiness/yellow styling, deadline text, non-draggable queue behavior,
and grid dimensions at 1440px and 760px. Desktop Week/Month screenshots were inspected.
The app-wide header still exceeds 760px; the Calendar grid itself fits and has no internal scroll.
No live data was changed or release published; restart the running app to load Python changes.


### September 14 — matched sidebar, live modal and false stale-data conflicts

The Operations source fingerprint now covers planning inputs, identity, readiness, acceptance,
deadlines, progress and published planning dates. Revision-only, QBO polling-time and unrelated
metadata changes no longer invalidate a booking ticket. Save rereads Operations and publishes
with the resulting exact per-vehicle revisions. Material changes still invalidate the ticket;
Calendar ETags, permissions and explicit overlap approval remain enforced. Booking previews can
refresh Operations atomically so a GET-to-preview race does not require manual refresh.

The open modal preserves typed inputs during periodic/focus refresh, displays current status as
badges, removes forecast phrases, and has a final footer with history left and Confirm right.
The queue tracks the full Calendar height in side-by-side layouts. Real booking changes show
current saved details inline before allowing a second confirmation of retained edits.

Verification: **784 tests passed, 1 skipped; 8/8 selected browser flows**. Additional isolated
visual checks confirmed matched Week/Month heights, footer placement, the progress badge, absent
forecast copy, and the real 15-second modal refresh without loss of the date or checkbox choice.
Desktop screenshots were inspected. No live data or release was changed; restart the app once
to load the updated Python and browser code.

## September 15 — local save queue

Calendar routes now use `calendar_workspace.py` for the local replica and durable outbox. The journal
is bound to the signed-in owner and cloud configuration. Confirm and removal return the actual saved
local revision, and background refresh responses cannot replace a newer acknowledgement. Sync errors
are visible within Calendar; upload progress never locks the booking controls. The next-opening badge
sits at the right of the view controls, directly above the grid.

Regression coverage includes book → remove → rebook while a fake provider is stalled, restart recovery,
lost acknowledgements, duplicate requests, failed local persistence, concurrent shared work, explicit
conflict review, and revoked permissions. The real browser flow also stalls date publication while
performing those three actions. All fixtures are isolated; no live bookings are changed by these checks.

The full release gate was attempted once because persistence/replay is a core contract change. It
stopped at `tests/contract/test_parts_db_contract.py::test_parts_db_contract[root_doc]`: the existing
bundled parts catalog differs from its recorded snapshot (including `qb_inactive` for item 1586).
The catalog already had local edits before this work. Neither catalog data nor contract snapshots
were modified to make that gate pass. This remains a release blocker independent of Calendar.

Final changed gate: **798 passed, 1 skipped; 8/8 selected browser flows**, including **98 Calendar
tests** (84 service/planning tests and 14 replica/outbox tests). Python/JavaScript syntax checks
and `git diff --check` passed. Restart the desktop app once to activate the Python changes; no live
instance was restarted and no release or live-data mutation was performed for this change.

## September 15 — project types

Projects now supplies Build / Service / Off-Site Service metadata. All types occupy the same team
calendar. Accepted service vehicles require an explicit labor estimate per vehicle and have optional
manual deadlines. Service has no implicit strip/finishing time or design-finalization warning. Selected
service requirements add stripping/finishing when needed; off-site travel labor occupies team hours.
Service details and type participate in the scheduling fingerprint and background conflict checks.
The diagram-free worksheet and optional previous-build reference are documented in
`POST_MEETING_FEATURE_PLAN.md`.
