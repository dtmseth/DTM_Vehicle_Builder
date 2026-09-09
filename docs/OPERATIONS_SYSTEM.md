# DTM Production Operations System

**Status:** Active architecture contract
**Schema target:** v4
**Last updated:** 2026-09-08

This document defines the production-operations extension to DTM Vehicle Builder. It is the
source of truth for system boundaries and workflow meaning. Exact SharePoint names live in
`OPERATIONS_SCHEMA.md`; role permissions live in `OPERATIONS_ROLES.md`; delivery slices live in
`OPERATIONS_IMPLEMENTATION_PLAN.md`.

The production lists use the reviewed permanent machine names in `OPERATIONS_SCHEMA.md`.
SharePoint display labels can be changed later, but API-facing names remain permanent integration
contracts.

## 1. Purpose

The operations system follows each individual vehicle from an open Builder project through
acceptance, parts, shop work, tray work, programming and quality control, final cleaning/photos,
delivery readiness, and completion.

The system must:

- remain simple enough that shop users actually update it;
- record dates automatically instead of asking users to type them;
- preserve a trustworthy timeline after corrections or reopening;
- work from both the desktop Builder and a minimal phone interface;
- let non-QuickBooks users see the last known Estimate status and its age;
- prevent external QBO edits from silently changing Builder-owned work;
- prevent Builder edits from silently overwriting QBO;
- use durable opaque identities rather than names as relationships;
- keep business rules outside browser event handlers.

## 2. Runtime shape

```text
QuickBooks Online
    | read-only observation, except explicit warned publication
    v
DTM Vehicle Builder --------------------+
    | role-gated desktop workspaces      |
    |                                    v
    +----------------------------> SharePoint
                                  DTMVehicleOperations (current projection)
                                  DTMVehicleEvents     (append-only history)
                                           ^
                                           |
                                  minimal phone Power App
```

The desktop and phone experiences are two clients of one operations contract. They must not grow
separate status definitions or date rules. The phone client is a deliberately narrow transitional
interface; a future Windows shop workstation can use the role-gated desktop workspace without any
data migration.

## 3. Authority boundaries

| Data | Authority | Other copies |
|---|---|---|
| Project, agency/year grouping, vehicle facts, build design, draft and output identity | Builder `ProjectRecord` / draft JSON mirrored to SharePoint | Operations list carries display/search projections only |
| Current production status | `DTMVehicleOperations` | Client caches are non-authoritative |
| Status history and actor/time audit | `DTMVehicleEvents` | Current milestone dates are a query-friendly projection |
| Application role assignments | Microsoft Entra ID | A short-lived local session caches resolved capabilities |
| QBO Estimate contents and transaction status | QuickBooks Online | Builder stores a conflict baseline; operations stores a read-only observation |
| QBO access and refresh tokens | Local OS keychain only | Never SharePoint, logs, project JSON, or the browser |

An operations record is keyed by the existing `IndividualUnit.individual_id`. SharePoint's numeric
item ID is an adapter detail and must never become the cross-system vehicle identity.

## 4. Project lifecycle and acceptance

Project organization has three states:

- `active`: current quote, design, or production work;
- `inactive`: stale, declined, abandoned, or indefinitely deferred work;
- `completed`: finished work retained for reference.

Moving a project inactive is manual and reversible. Age, QBO status, or lack of activity must not
silently inactivate a project. Each transition records time, actor, and an optional reason.
The current lifecycle metadata and an append-only `project_lifecycle_history` live on the Builder
project record, because a project can exist before it has an individual vehicle operations row.
Inactive Operations rows and history are retained so reactivation restores prior work, but inactive
projects are hidden from the Operations workspace. Deleting a project explicitly cascades through
its Operations events and current rows before the Builder record is removed.

Acceptance is separate from project lifecycle. An active project may be not accepted, partially
accepted, or accepted. Acceptance is stored per individual vehicle and summarized on the active
project card:

- `not_accepted`: no applicable vehicles are accepted;
- `partially_accepted`: at least one but not all applicable vehicles are accepted;
- `accepted`: every applicable vehicle is accepted.

An unlinked or never-checked QBO estimate is shown separately as "not checked"; it is not described
as rejected. The existing `IndividualUnit.confirmed` flag means design review/production readiness
and must not be reused for customer acceptance.

Acceptance is latched when an authorized user confirms it or a connected Builder observes an
accepted QBO Estimate. A later QBO status such as Closed must not erase the accepted date. Reversing
acceptance is an audited correction requiring a reason.

## 5. Vehicle availability and the 60-day commitment

Physical vehicle availability is independent of Parts and production progress. V1 uses one
location/action status instead of separate location and availability fields:

- `awaiting_details` (Awaiting Details);
- `waiting_on_dealer` (Waiting on Dealer);
- `waiting_on_agency` (Waiting on Agency);
- `ready_for_pickup` (Ready for Pickup);
- `at_dtm` (At DTM).

`in_production` and `ready_for_delivery` are deliberately not repeated here. Build / Shop and
Final Finish already answer those questions. This status says where the customer vehicle is or
what must happen to get it to DTM. More specific circumstances belong in a future focused
issue/comment workflow rather than expanding this frequently updated status.

Legacy rows/events that used availability=`delivered` remain readable and correctable, but new UI
actions record delivery in Final Finish instead.

The business-effective dates are separate from the audit time of the button press:

- Vehicle Available Date: the day the vehicle first became available to DTM, even if DTM learned
  or recorded it later;
- Vehicle At DTM Date: the day it physically arrived;
- Delivered Date: the day it left DTM for the customer.

The first date may therefore be entered/backdated by an authorized user. The immutable event still
records when and by whom the entry was made.

The customer commitment is derived, never moved by an internal delay:

```text
Commitment Start Date = later of Vehicle Available Date and Parts Received Date
Must Deliver By Date   = Commitment Start Date + 60 calendar days
```

`received` is the Parts Complete/available milestone for this calculation. `parts_ready` is the
later human verification/staging milestone and implies Received; when an imported/current vehicle
jumps directly to Parts Ready, a missing Received timestamp is backfilled from that action. No
automatic Must Deliver On date is shown until both required dates are known. A correction to either
input recalculates the current projection while history remains in events. A separately stored
manual override may replace the displayed deadline for imported or manually maintained work; it is
never confused with the calculation and can be cleared to restore the automatic date.

## 6. Scheduling

Scheduling remains simple and human-directed in v1. It does not add a subjective Ready to Schedule
field. Dates can be captured independently, in any order, before or after acceptance. The schedule
bucket is still derived:

- an unaccepted vehicle is Prospective and stays outside the accepted scheduling queue;
- an accepted vehicle without `ScheduledWeekOf` is Unscheduled and appears on Tyler's radar;
- setting `ScheduledWeekOf` changes the derived display to Scheduled.

The Active Operations tab provides **All / Unscheduled / Scheduled** subfilters. Scheduled projects
sort by Scheduled Week first; projects with any unscheduled vehicle remain in Unscheduled so a
partially scheduled project cannot disappear from Tyler's queue.

The shared row stores:

- optional Scheduled Week Of (the normal long-range planning unit);
- optional Planned Start Date;
- optional Target Finish Date;
- optional manual Must Deliver On override;
- derived Commitment Start and effective Must Deliver On dates.

The editor is patch-based: changing one date preserves every field the user did not touch. There is
no Monday, date-order, or cross-field requirement. Project-wide edits remain sequential one-vehicle
commands so every vehicle keeps its own revision and immutable history.

Ready to Build is a separate derived readiness summary using vehicle At DTM, Parts Ready, and
build-finalization information. An authorized manager can apply a visible, reasoned override when
work intentionally proceeds without all inputs. V1 does not cascade dates, optimize bays, assign
labor, or invent long-range day-level precision.

### Later scheduling and shop-capacity additions

Two planned additions should build on this same vehicle timeline after the day-to-day scheduling
flow has been piloted:

- **Bay tracking:** assign a vehicle to a durable bay ID, show current bay occupancy, and retain
  assignment/move timestamps so the current floor view and historical bay usage do not depend on a
  renamed display label. Do not model automatic bay optimization until the actual shop process is
  established.
- **Team assignments:** allow a project-level default team with an optional per-vehicle override.
  The first version may use a small administratively managed roster of names, but assignments must
  point at durable neutral IDs rather than storing the team/person name as identity. Later, a roster
  entry may link to an Entra object ID as individual shop accounts become available without
  rewriting historical assignments.

Both changes need dated assignment events, correction history, and clear unassigned states. They
are intentionally kept out of the v1 SharePoint columns until the owner has established the real
bay list and initial team structure; this avoids permanent internal names for guessed concepts.

## 7. Production workstreams

The following fields are independent. There is no extra manually maintained master Production
Status.

| Workstream | Stored states | UI labels |
|---|---|---|
| Parts | blank, `ordered`, `partially_received`, `received`, `parts_ready` | Ordered, Partially Received, Received, Parts Ready |
| Build / Shop | blank, `in_progress`, `complete` | Start Build / In Progress, Complete |
| Tray | `not_ready`, `ready`, `complete` | Not Ready, Ready, Complete |
| Programming & QC | `not_ready`, `ready`, `complete` | Not Ready, Ready, Complete |
| Final Finish | `not_ready`, `ready_for_wash_clean_photos`, `ready_for_delivery`, `delivered` | Not Ready, Ready for Wash/Clean/Photos, Ready for Delivery, Delivered |

There is no palletization field. `parts_ready` means all required parts are received and staged for
the shop; any palletization is implied.

`ordered` is a dated purchasing milestone. Existing/imported work may still move directly to a
known receiving state; skipped milestones stay blank instead of inventing a historical order date.

There are no Paused or Blocked production states. A future focused issue/comment workflow can hold
context that genuinely needs attribution or discussion; v1 has no general operations-note field.

The workstreams intentionally overlap:

- Tray can become ready and complete while Build / Shop remains in progress.
- Build / Shop may continue after Tray completes.
- Programming & QC can become ready before Build / Shop completes.
- Programming & QC normally begins after Build / Shop completes, but the backend does not impose a
  false hard dependency.

Within one workstream, normal forward transitions are validated. Forward skips are allowed only
where operationally legitimate (for example, Parts can go directly from blank to Received when one
complete shipment arrives). A regression, correction, or unusual skip requires the correction
capability and a reason. Cross-workstream order produces guidance at most, never a hard failure.

Ready for Delivery and Delivered are distinct consecutive Final Finish states. Physical delivery
stamps Delivered Date and advances Final Finish to `delivered`; Vehicle Availability remains
`at_dtm`, its completed state. A separate closeout workflow is deferred until real use demonstrates
what it needs.

## 8. Dates, events, and durations

Users change a status; the system records the date. Users never type routine milestone dates.

Every accepted mutation creates one immutable event containing:

- event ID and idempotency/request ID;
- vehicle and project IDs;
- workstream and event type;
- previous and new values;
- UTC occurrence time;
- optional business-effective date when it differs from the entry time;
- Entra object ID and display name;
- optional technician name selected in the shared-account phone experience;
- source client and app version when available;
- correction reason when applicable;
- resulting current-record revision.

The current operations row also stores commonly filtered milestone dates. The event history remains
authoritative when a status is corrected or reopened. Current milestone fields describe the most
recent valid cycle; a regression clears downstream current-cycle dates without deleting history.

Initial reporting durations include:

- accepted to Shop started;
- Shop started to Shop complete;
- Tray ready to Tray complete;
- Programming & QC ready to complete;
- Parts received to Parts ready;
- Final Finish ready to Ready for Delivery;
- accepted to Ready for Delivery;
- Ready for Delivery to Delivered;
- accepted to Delivered.

Programming & QC `ready -> complete` is queue/cycle time, not hands-on labor. An extra Start action
will not be added solely for metrics unless real usage proves it valuable.

Audit timestamps use UTC ISO 8601. Business dates such as Vehicle Available, Scheduled Week,
Target Finish, Must Deliver By, and Delivered use ISO `YYYY-MM-DD` values so timezone conversion cannot
move them to a different calendar day. Clients render timestamps in the user's local timezone. The
SharePoint Created/Modified audit fields are retained as an independent platform audit.

## 9. QBO observation and publication

QBO integration is deliberately asymmetric.

### Observation

A connected Builder may refresh and share only:

- Estimate ID and number;
- QBO transaction status and accepted date;
- QBO last-modified time when available;
- time and user of the successful check;
- whether QBO differs from the saved Builder baseline.

Refreshing never imports QBO customer details, lines, quantities, prices, notes, or options into the
Builder project or draft. Operations users see the observation timestamp, and the UI warns after 24
hours without a successful refresh.

### Link existing Estimate

An authorized user can search or enter an existing QBO Estimate, inspect likely matches, and choose
one explicitly. The service refuses to attach one Estimate to two Builder vehicles without a
deliberate correction. Linking captures a narrow baseline and publishes the shared observation.

If the vehicle was already marked accepted manually, connecting an Estimate never clears or
rewrites that acceptance. An accepted QBO Estimate adds separate confirmation evidence. A linked
Estimate that is not accepted produces a visible mismatch warning; it does not silently revoke the
manual acceptance. Correcting acceptance remains an explicit, reasoned action.

### Publication safeguards

Builder edits only mark the linked Estimate as differing. They never write QBO automatically.
Updating an existing Estimate requires an explicit action, a fresh QBO read, a readable difference
review, and an overwrite warning. If both QBO and Builder changed, publication is a hard conflict.
Creating a new Estimate remains available but secondary and discouraged. Replaced Estimate links
remain in history instead of being discarded.

## 10. Client behavior

### Desktop Builder

The existing installer gains role-gated workspaces. Users only see navigation and actions granted
by their resolved capabilities. Users with multiple roles may switch workspaces. Hiding controls is
not authorization; every mutating local API route enforces the same capability.

### Phone client

The initial phone Power App is limited to a searchable active-vehicle list, vehicle detail, large
status actions, the timeline, and links to published shop documents/photos. The shared shop
Microsoft account receives only the Shop role. When individual attribution matters,
the event can also capture an optionally selected technician name. The phone UI prominently offers
that selection when marking Final Finish Delivered and on future issue/comment entries,
but it remains optional. Future individual accounts remove the extra step without changing the schema.
The phone app does not edit projects or builds,
connect to QBO, administer roles, or maintain the parts catalog.

The SharePoint connector does not provide a supported offline-first phone path. When SharePoint is
unavailable, the phone UI may show cached/read-only context but must not pretend an edit succeeded.

### Shared mutation contract

Every client sends a stable request ID with a transition. Duplicate delivery is idempotent. Current
row writes use an expected revision/eTag; a stale client receives a conflict and refreshes instead
of overwriting a teammate. The exact Power App write mechanism (direct paired update versus an
append-only request processed by a standard SharePoint flow) must be proven against a test list
before the production schema is provisioned.

## 11. No-additional-license client strategy

The phone client uses the SharePoint connector, which Microsoft currently classifies as a Standard
Power Apps connector. Existing tenant entitlements still need to be confirmed before rollout, but
v1 must not use Dataverse, a custom connector, a premium flow, or an on-premises gateway.

There is no Microsoft-listed Power Apps connector for QBO accounting data; the similarly named
QuickBooks Time connector is a different product and is classified Premium. QBO observation
therefore stays in the existing Builder integration: a user who can connect refreshes a narrow
snapshot into SharePoint for everyone else. The phone app never connects to QBO.

To minimize Canvas work, the phone app should be one responsive screen plus one reusable vehicle
detail component. A filtered gallery opens an inline/detail container rather than navigating to a
stack of screens, eliminating routine back-button wiring. Status controls are generated from one
small mapping table and call one shared mutation formula/component. Power Apps code view can copy
and paste generated control YAML, but Microsoft does not support editing the extracted app YAML as
a general external-code workflow without Power Platform Git Integration. AI assistance should
therefore generate the component tree, formulas, and pasteable controls while final assembly and
testing remain in Power Apps Studio.

Official references:

- [SharePoint connector classification](https://learn.microsoft.com/en-us/connectors/sharepointonline/)
- [Power Platform licensing FAQ](https://learn.microsoft.com/en-us/power-platform/admin/powerapps-flow-licensing-faq)
- [Power Apps connector catalog](https://learn.microsoft.com/en-us/connectors/connector-reference/connector-reference-powerapps-connectors)
- [Canvas control code view](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/code-view)
- [Canvas app source-code limitations](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/power-apps-yaml)

## 12. Reliability and safety rules

- Cloud calls never block the local UI request queue.
- A stale write never wins silently.
- A retry never creates a duplicate event.
- An unauthorized route returns a denial even if the UI control was manually exposed.
- External strings are treated as untrusted at every UI boundary.
- App logs contain operation names and safe identifiers, never OAuth tokens or raw QBO responses.
- Tests use in-memory/local repositories; automated tests never reach production SharePoint.
- Operations schema changes are versioned and backward compatible before deployment.
- A failed current-row/event paired write is recoverable through request ID and reconciliation.

## 13. Deliberately deferred

- labor timeclock or technician punch tracking;
- automated production scheduling and capacity optimization;
- bay occupancy and movement tracking (planned after the scheduling pilot);
- project/vehicle team assignment (planned after the initial team structure exists);
- offline SharePoint edits;
- a hosted custom mobile web application;
- QBO-to-Builder line import;
- unattended QBO token storage in the cloud;
- automatic project inactivation;
- predictive status changes;
- custom technician time tracking before QBO/Workforce;
- closeout workflow and detailed closeout checklist;
- a general operations-note field; use a focused issue/comment workflow if later needed;
- expanded photo management beyond the existing published-photo links.

## 14. Decision register

### Accepted for v1

- One system with desktop and minimal phone clients.
- One operations row per individual vehicle.
- Separate append-only event history.
- Independent Parts, Build / Shop, Tray, Programming & QC, and Final Finish workstreams.
- Automatic dates for every accepted transition.
- Independent vehicle availability plus business-effective dates.
- Derived Unscheduled/Scheduled buckets with optional planned dates and no subjective readiness status.
- A derived 60-day Must Deliver By date.
- Ready for Delivery and Delivered kept distinct within Final Finish; `at_dtm` completes Vehicle
  Availability; closeout deferred.
- Started / Active / Completed organization in Operations, with inactive projects hidden and Started
  derived from missing acceptance rather than stored as a fourth lifecycle state. Projects retains
  all four Started / Active / Inactive / Completed tabs.
- Separate acceptance badge on Active projects.
- Optional Inactive reason and optional Delivery Method.
- Final Finish editable by both Shop and Programming & QC.
- QBO observation warning after 24 hours and safe reconciliation after manual acceptance.
- No general operations-note field in v1.
- Full VIN projected for operations search; opaque Builder vehicle ID remains the relationship key.
- Full immutable vehicle-event history retained indefinitely.
- Entra roles mapped to backend capabilities.
- QBO observation only, except an explicit warned publication action.
- SharePoint Standard connector only for the phone client; QBO is refreshed by Builder.

### Must be validated before SharePoint production provisioning

- Exact production site and list location.
- Whether Entra group assignment is licensed or users will receive direct app-role assignments.
- Phone mutation mechanism and failure recovery.
