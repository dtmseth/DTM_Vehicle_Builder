# Scheduling revamp — booking model and interaction proposal

2026-09-14. Owner-reviewed design and implementation notes, based on `SCHEDULING_REVAMP_SESSION_PROMPT.md`.
Implemented locally; no production schedule has been published. See `CALENDAR.md` for current behavior.

## Further owner follow-up — direct confirmation and project scheduling

Booking now uses **Confirm booking** directly in the modal, with live calculated dates and inline
validation. The default-checked project checkbox includes accepted, unscheduled siblings. Calendar
has no Shop actions. Project removal clears planning dates/assignments through existing audited
Operations writes and keeps a durable release marker for interrupted publication. Month drops
choose an available team; busy options have red dots and require a named overlap confirmation.
Explicitly confirmed overlaps are now allowed, superseding the earlier hard-overlap rule below;
invalid dates and stale/unauthorized writes remain blocked. See `CALENDAR.md`.

## September 14 owner follow-up — current interaction

The owner subsequently removed second-team scheduling, separate agreed dates, and remaining-hours
entry. Current booking UI focuses on one assigned team and scheduled start/ready dates. Acceptance
and delivery deadline are contextual information, with correction controls under Advanced.
Cards use parts/vehicle badges and clean identity labels; the sidebar scrolls independently.
Full day areas accept pointer drops, saved bookings can be dragged, and Week/Month mark today.
Editors are compact modal bubbles. This decision supersedes the promise/joint-team/remaining-hours
proposal below; legacy stored data stays readable. See `CALENDAR.md` for current behavior.

## Owner decisions and implementation status

The owner answered the design questions on 2026-09-14:

- There are **no previously proposed spots**. Projects go onto the schedule only after acceptance,
  using the nearest available opening. No proposal/hold state will be implemented.
- Preserve **agreed start and ready dates**, independently from forecasts and Operations deadlines.
- Team choice stays with schedulers as required by the source prompt. Choosing the team stages
  the nearest opening for explicit review/save; acceptance reads do not write reservations.

Implementation is now in the Calendar-owned files, dedicated `ui/calendar.css`, a narrow optional
Operations schedule-event reason, and Calendar sections of the shared browser smoke flow. The
photo task explicitly confirmed those flow sections were free to edit. Current behavior and schema
are documented in `CALENDAR.md`; the design material below records rationale and future scope.

## Findings from the current implementation

- `plan_calendar()` reconstructs the schedule on every read, anchors it to today, assigns teams
  automatically, and defers blocked work. Saved `last_plan` snapshots preserve historical displays
  but do not stabilize ordinary active bookings.
- A synthetic saved booking starts at 08:00 September 14 when read on September 14 and at 08:00
  September 15 when read the next day, without an edit or save.
- Fixed starts are lower bounds after the team's previous cursor. Two synthetic fixed bookings
  requested for September 14 on David's Team show September 14 and September 15 respectively;
  the second gets a warning but its displayed start has already moved.
- `CalendarService.save()` saves every calculated job. Thus saving one edited vehicle can also
  turn unrelated automatic suggestions into saved plans and publish their dates.
- `save_settings()` writes immediately without reviewing booking impacts. Team absences, closures,
  people and buffer changes can alter the next calculation.
- Review shows proposed dates but lacks complete old/new dates, an explanation requirement, and
  a user-facing Calendar change history. Local storage snapshots are useful recovery evidence,
  not a readable shared history. Operations schedule events currently receive an empty reason.
- The existing infrastructure is valuable: conditional Calendar writes, content-bound preview,
  per-vehicle revisions/events, silent background authentication, durable save progress, and
  stop-on-conflict publication. Preserve these boundaries.

Baseline check: all 48 tests in `tests/test_calendar.py` passed. Synthetic domain-only probes used
in-memory records and did not open the app, call providers, or publish dates.

## Proposed interaction

Calendar's main board shows saved reservations in team/date lanes. A sidebar shows **Accepted,
unscheduled**, grouped by exact project ID, ordered by earliest known acceptance among its
unscheduled vehicles; each vehicle retains its own date and acceptance source. Expand a project
to see each unit/VIN, date, readiness, and reservation state. Stable IDs break date ties. Put
missing-date vehicles in a clearly separate **Acceptance date needed** group; do not assign them
an invented position among dated acceptances. A project can have both reserved and queued vehicles.

Selecting **Schedule project** stages only the explicitly selected, currently accepted vehicles.
The review names every included vehicle; already reserved vehicles remain untouched unless selected
for an explicit change. For split teams, show the proposed per-vehicle allocation before saving.
Joint work reserves the same working intervals on each participating team.

Drag a project or vehicle onto a team/day to stage its placement. It opens the same form as the
keyboard-accessible **Schedule…** button with team and start-date fields. Neither interaction
persists anything. Stage calculations show labor hours, team size, buffer, working duration, final
checks, readiness, delivery risk, and exact conflicting vehicles. The scheduler can pick another
opening or explicitly select affected bookings for rescheduling. There is no cascade move.

**Find opening** takes job type, labor estimate/default, team(s), vehicle count, and earliest date.
It returns a start, build finish, and ready date with the assumptions that produced them. Label it
**Calculated opening — not reserved**. Use the same capacity algorithm as placement review; find
gaps between fixed intervals rather than only appending after a team's latest booking. Joint work
requires simultaneous free intervals on both teams. Acceptance priority remains visible but does
not silently consume capacity or assign a team.

The opening calculator retains no proposal or hold. Accepted vehicles with known dates enter the
sidebar. The scheduler chooses team(s), reviews the nearest opening, and saves the reservation.
Missing acceptance dates require review. Sales retains existing read/acceptance permissions; no
automatic customer notification or QBO write is introduced.

Review displays each selected vehicle's old/new teams, reserved interval, working forecast,
customer promise, and delivery deadline, plus conflicts with named vehicles. Require an explanation
for changing an existing reservation, changing a promise, or overriding a readiness/risk
warning. Hard resource overlaps block saving until the scheduler resolves them in the explicit
change set. Do not offer an unexplained force-save that double-books a team.

## Durable model

Use a versioned Calendar document with validated, separately identified concepts:

| Concept | Meaning | When it changes |
| --- | --- | --- |
| Reservation | Stable team IDs and booked work intervals, approved labor assumptions | Explicit reviewed booking/change |
| Customer commitment | Owner-selected promised dates and agreement record | Explicit explained promise change |
| Forecast | Current expected work/ready dates and evidence of risk | Read-only recalculation for warnings; publication requires review |
| Operations deadline | Existing computed 60-day date or manual override | Existing Operations workflow only |

Reservations store interval segments, not just a start date. This preserves fractional-day
capacity, joint-team occupancy, and the originally approved end when assumptions change.
Store frozen labor/defaults separately from explicitly entered manual hours. Renaming a team
keeps identity; retiring a booked team generates a review item without assigning another team.

Keep `last_plan` compatibility during an explicit migration, but do not interpret old calculated
dates as evidence of customer agreement. Import existing saved plans as protected legacy bookings
with **Customer promise unconfirmed**. Where only Operations dates exist and team identity is
unknown, require team reconciliation; do not guess a team and report that capacity as free.
Unresolved imports must prevent the opening calculator from presenting a definitive quoteable
opening for the affected horizon. Overlapping legacy bookings remain visible at their recorded
dates with conflicts until reviewed. Unaccepted historical/manual bookings must not disappear or
release capacity merely because they fall outside the new acceptance queue.

Use a new document schema version so older clients reject incompatible scheduling data instead
of automatically re-saving it. Migration must be explicit, revision-checked and recoverable;
reads do not migrate storage or publish anything. Schema validation and documentation changes
require coordination with sessions using shared configuration files.

## Changes in the shop

| Trigger | Display and choices | Protected behavior |
| --- | --- | --- |
| Work runs long | Enter/review remaining labor; show threatened bookings and proposed alternatives | No progress inference from elapsed calendar time; no automatic displacement |
| Early completion | Record actual finish with Shop's existing action; show newly available capacity | Later reservations and customer promises keep their dates |
| Parts/vehicle/design delay | Keep reserved slot, mark readiness risk; offer keep or move with reason; release workflow deferred | No yielding to another queue item on refresh |
| Absence/closure/capacity change | Review affected bookings and forecast risks alongside settings change | Capacity facts may change; reservations remain fixed and conflicts stay visible |
| Team change | Recalculate the selected vehicle on the requested team at its booked start | Preserve promise; show any infeasible finish before approval |
| Promise renegotiated | Capture new agreed dates and explanation in the booking history | Neither automatic 60-day date nor manual deadline override follows it |

Finishing retains the current shared-group assumption and four-hour default. Display that
assumption explicitly; do not imply a newly constrained QC roster. Individual dated worker absence
management and optimization remain deferred; whole-team days off and existing capacity settings
can produce the necessary first-version warnings.

## Save, publication and history

1. A preview accepts an explicit set of vehicle/job IDs and edits, the Calendar revision,
   Operations fingerprint, and explanation. Compute the full conflict context server-side but
   never add unrelated bookings to the mutation set.
2. The review ticket binds selected changes, promise actions, explanations, assumptions, source
   revisions, and the calculated impacts. Revalidate availability and authorization on save.
3. Conditionally persist the reservations and append their history in the same Calendar write.
   History includes actor ID/name, timestamp, request/change-set ID, exact vehicle IDs, reason,
   and before/after teams, reservation dates, promises and estimates. Show it in booking details.
4. Preserve the durable background worker. Publish only the explicitly saved date changes through
   `OperationsService.change_schedule`, one revision-checked event per vehicle. Extend its narrow
   reason parameter after coordinating Operations edits; no raw project-row PATCH.
5. Keep planned start / Monday Scheduled Week / target finish meanings explicit. They reflect the
   last reviewed working plan, while customer commitments remain distinct Calendar fields. Read-only
   forecast changes never trigger Operations writes.
6. On partial failure, reservations remain held and completed Operations events remain valid.
   Mark pending publication visibly. A fresh review publishes remaining discrepancies against the
   same saved reservations; it must not recalculate a replacement schedule or replay a stale request.

Existing Shop Start/Finish permissions, manual acceptance protections, true QBO AcceptedDate
semantics, manual labor overrides, exact revisions and silent worker authentication remain intact.

## Implementation and verification scope

- Work was confined to Calendar/Operations files in the existing checkout, with the photo task
  explicitly clearing Calendar smoke edits. Before implementation, the current Calendar source
  baseline and hashes were retained under `/private/tmp/dtm-scheduling-revamp-baseline-20260914`.
  User output/tmp and unrelated source changes were preserved.
- Implement the interval/capacity domain, explicit booking validation, acceptance queue, and opening
  queries with synthetic tests. Replace automatic-yield tests with stable-booking expectations.
- Implement schema/migration review, selected-change persistence, history, stale conflict checks,
  and background publication recovery. Test same-spot racing reservations and repeat requests.
- Build queue, click/keyboard placement, opening calculation, before/after review and history;
  add drag/drop as a convenience over the same validated edit path.
- Use Calendar-owned files. Coordinate before changing shared CSS/index, config schema, Operations
  service, route authorization or browser-flow registration. Do not touch photo/folder services.
- Verify invariance across next-day reads, readiness changes, new acceptance, completion, holidays,
  team retirement, joint bookings, split projects and edited labor. Verify new overlaps are rejected,
  late promises remain visible, no customer promise is inferred during migration, and saved booking
  recovery never moves dates. Cover Shop/Sales authorization and manual/QBO acceptance regressions.
- Run `tools/verify.py changed` after meaningful implementation batches and report compact results.
  Preview only in an isolated cloud-off workspace on an unused port, with provider access blocked.
  No production schedule publication, commit, merge, release, or Azure deployment is part of this task.

## Verification completed 2026-09-14

- The mandatory `tools/verify.py changed` gate passed **758 tests, 1 skipped, and 8/8 selected
  browser flows** after the implementation and remaining-labor correction.
- A final narrow acceptance-loss safeguard was then covered by `tests/test_calendar.py`:
  **59 Calendar tests passed**. Lost acceptance now raises a review item, preserves the held
  interval, and excludes its pending dates from publication.
- The Calendar browser flow covers acceptance editing, read-only multi-vehicle opening queries,
  drag/drop staging without persistence, exact per-vehicle booking, explicit scheduling of the
  remaining project vehicles, stable prior dates, settings review, explained cancellation, and
  existing Shop/Sales permissions. No browser console errors or external requests were recorded.
- Desktop, narrow Calendar layout and blocked-conflict dialog were rendered with synthetic
  records in a temporary cloud-off workspace and an OS-assigned loopback port. Calendar layout
  checks passed; no page errors or provider egress occurred. The app's existing global header
  is outside this Calendar layout change.
- `git diff --check` passed. No release gate, commit, merge, production schedule publication or
  deployment occurred. The photo task confirmed Calendar-only smoke-file coordination.
