# Operations

Active system boundary, SharePoint schema, and role/capability contract for desktop Builder
and the optional phone client. Current/events use schema **v5**; phone requests use **v1**.
Calendar scheduling behavior is documented in [CALENDAR.md](CALENDAR.md).

## System boundary and authority

Builder owns projects, vehicle facts, and designs. SharePoint holds the current operations
projection and event history. QuickBooks owns Estimate contents and transaction status;
Builder shares a narrow, timestamped observation without importing or overwriting Estimate
lines as a side effect. Publishing to QBO requires an explicit reviewed action.

Desktop and phone clients share status tokens, dates, and mutation rules. The optional Power
App creates pending requests only; a trusted Power Automate processor writes the current/event
pair. It has no direct core-list update path, QBO connection, or project/build editing authority.
The request list is live; the processor remains Off and pre-pilot, and no Canvas app exists.

### Authority

| Data | Authority | Other copies |
|---|---|---|
| Project, agency/year grouping, vehicle facts, build design, draft and output identity | Builder `ProjectRecord` / draft JSON mirrored to SharePoint | Operations list carries display/search projections only |
| Current production status | `DTMVehicleOperations` | Client caches are non-authoritative |
| Phone command/result transport | `DTMOperationsRequests` | Never authoritative current state or history |
| Status history and actor/time audit | `DTMVehicleEvents` | Current milestone dates are a query-friendly projection |
| Application role assignments | Microsoft Entra ID | A short-lived local session caches resolved capabilities |
| QBO Estimate contents and transaction status | QuickBooks Online | Builder stores a conflict baseline; operations stores a read-only observation |
| QBO access and refresh tokens | Local OS keychain only | Never SharePoint, logs, project JSON, or the browser |

An operations record is keyed by the existing `IndividualUnit.individual_id`. SharePoint's numeric
item ID is an adapter detail and must never become the cross-system vehicle identity.

### Authorization and mutation boundary

- Entra roles come from validated ID-token claims for the existing public-client app. Stable
  role Values are permanent; never rename or repurpose issued Values. Role assignment adds
  no client secret or application permission. Multiple roles grant the union of capabilities.
- Every backend mutation checks its capability. UI visibility is not authorization. Unknown
  roles, failed resolution, and unverified sessions grant no mutation authority. Cached roles
  expire and are invalidated on account switch/token refresh; synthetic admin identity is
  restricted to explicitly configured local development outside production bundles.
- Delegated Graph access intersects granted scopes with the user's SharePoint permissions.
  The core lists inherit site permissions; DTM roles do not prevent a user with direct list
  access from editing outside DTM. Builder project/draft libraries remain separately permissioned.
  Stronger isolation requires list permissions or a trusted service.
- Desktop events retain the authenticated Entra object ID and display name. A shared shop
  account has only `ShopEditor`; optional `PerformedByName` is attribution, never authentication.
  Phone v1 derives the actor from immutable SharePoint Created By, writes its display name,
  and leaves the object ID blank until a trusted lookup is implemented.
- Mutations carry a stable request ID and expected revision/ETag. Create the pending event
  and complete recovery snapshot before the conditional current-row write; finalize the event
  afterward. Stale revisions conflict, retries are idempotent, and corrections create new events.
  Ordinary history reads never repair pending events; recovery belongs to an authorized writer.
- The phone processor runs with trigger concurrency one, permits only normal forward Shop,
  Tray, Programming & QC, and Final Finish actions on active, accepted vehicles, and owns all
  result fields. It validates schema/status, treats identical states as unchanged, and rejects
  corrections/skips. It must not report success before an applied/unchanged result. Terminal
  failure handling and interrupted-write recovery still need pilot validation before enabling it.
- Read-only Graph uses `Sites.Read.All`; authorized foreground writes acquire
  `Sites.ReadWrite.All` interactively. `Sites.Manage.All` is confined to one-time provisioning.

## Core SharePoint schema

The executable schema contract is `app/adapters/cloud/operations_list_schema.py`.
The manifest and provisioner must match these names and types before live creation.

### Naming rules

- Create lists and columns initially with the exact ASCII internal name shown here.
- Keep every internal column name at 32 characters or fewer; SharePoint silently truncates longer
  names even when Graph preserves the full display name.
- Use the SharePoint list GUID in configuration after provisioning; never depend on the display
  title or list URL for identity.
- Use `BuilderVehicleId` (`IndividualUnit.individual_id`) as the durable vehicle key.
- Use `BuilderProjectId` (`ProjectRecord.project_id`) as the durable project key.
- Do not use SharePoint's numeric item ID outside the SharePoint adapter.
- Use UTC ISO 8601 date/time values and render locally in clients.
- Store stable machine tokens for statuses; clients own friendly labels.
- Additive schema changes increment `SchemaVersion`. Renames are implemented as add/copy/deprecate,
  never by pretending an internal name changed.

The Builder IDs are opaque UUID-style text, not descriptive names. They cannot become stale when an
agency, unit, or vehicle is renamed. SharePoint's numeric `ID` is safe only inside one list and one
site, so using it as the Builder/QBO relationship would make migrations and test-list promotion more
fragile, not less. Relationships therefore use the existing opaque Builder IDs and list GUIDs.

### List: `DTMVehicleOperations`

**Creation/display name:** `DTMVehicleOperations` (Builder label: DTM Vehicle Operations)
**Cardinality:** exactly one current item per Builder vehicle ID
**Authority:** current operations projection

#### Identity and display projection

| Internal name | Type | Required | Indexed/unique | Meaning |
|---|---|---:|---|---|
| `Title` | Single line text | yes | no | Current human-readable vehicle label; never identity |
| `SchemaVersion` | Number, integer | yes | no | Current operations schema version |
| `BuilderVehicleId` | Single line text | yes | indexed + unique | Existing opaque `individual_id` |
| `BuilderProjectId` | Single line text | yes | indexed | Existing opaque `project_id` |
| `AgencyId` | Single line text | no | indexed | Existing opaque agency ID |
| `AgencyName` | Single line text | no | no | Search/display projection from Builder |
| `BuildYear` | Single line text | no | indexed | Project build year; text avoids numeric formatting |
| `UnitNumber` | Single line text | no | no | Current unit number projection |
| `Vin` | Single line text | no | indexed | Full VIN projection for exact search; never the primary identity |
| `VehicleLabel` | Single line text | no | no | Year/make/model/build display label |
| `AssignedSalespersonId` | Single line text | no | no | Stable Builder/Entra identifier when available |
| `AssignedSalespersonName` | Single line text | no | no | Display projection; never identity |
| `BuildFinalized` | Yes/no | yes | no | Builder-owned technical-finalization projection |
| `BuildFinalizedAtUtc` | Date/time | no | no | Builder-owned finalization time projection |
| `ShopFolderUrl` | Single line text | no | no | Current vehicle Shop folder URL |
| `BuildSheetUrl` | Single line text | no | no | Current published shop build-sheet URL |
| `PartsListUrl` | Single line text | no | no | Current published parts-list URL when available |
| `ProjectState` | Choice | yes | indexed | `active`, `inactive`, `completed` |

Display projections are refreshed from Builder by stable ID. Renaming an agency, unit, or vehicle
never creates a new operations row.

#### Acceptance

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `AcceptanceStatus` | Choice | yes | yes | `not_accepted` or `accepted` per vehicle |
| `AcceptedAtUtc` | Date/time | no | no | First/latest valid acceptance for the current accepted cycle |
| `AcceptanceSource` | Choice | no | no | `qbo`, `manual`, or `migration` |
| `AcceptanceChangedAtUtc` | Date/time | no | no | Most recent acceptance correction/change |

`partially_accepted` is a project-card summary and is not stored on a vehicle row.

#### Vehicle availability

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `VehicleAvailabilityStatus` | Choice | yes | yes | `awaiting_details`, `waiting_on_dealer`, `waiting_on_agency`, `ready_for_pickup`, `at_dtm`; legacy `delivered` remains accepted for existing history |
| `VehicleAvailabilityStatusChanged` | Date/time | no | no | Audit time of latest availability-status change (stored in UTC) |
| `VehicleAvailableDate` | Date only | no | yes | Business-effective date vehicle became available to DTM |
| `VehicleAtDtmDate` | Date only | no | no | Business date vehicle physically arrived at DTM |

Build progress, Ready for Delivery, and new delivery actions are intentionally not duplicated in
the availability choice. At DTM is this workstream's completed state. The retained `delivered`
choice is compatibility-only and is no longer presented by the Builder UI.

#### Scheduling and commitment

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `ScheduledWeekOf` | Date only | no | yes | Planned production week; no Monday-only validation |
| `PlannedStartDate` | Date only | no | no | Optional near-term planned start |
| `TargetFinishDate` | Date only | no | yes | Internal target selected by scheduler |
| `ScheduleChangedAtUtc` | Date/time | no | no | Latest accepted schedule edit |
| `CommitmentStartDate` | Date only | no | no | Derived later of Vehicle Available and Parts Received dates |
| `MustDeliverOverrideDate` | Date only | no | no | Optional manually entered Must Deliver On date |
| `MustDeliverByDate` | Date only | no | yes | Effective display date: manual override, otherwise Commitment Start + 60 days |
| `ReadyToBuildOverride` | Yes/no | yes | no | False by default; reasoned manager exception to derived readiness |
| `ReadyToBuildOverrideReason` | Multiple lines text, plain | no | no | Required while override is true |
| `ReadyToBuildOverrideAtUtc` | Date/time | no | no | Latest override change time |
| `ReadyToBuildOverrideByEntraId` | Single line text | no | no | Opaque actor ID for current override |
| `ReadyToBuildOverrideByName` | Single line text | no | no | Display-only actor name |

There is no stored Ready to Schedule status. Unaccepted vehicles are derived as Prospective;
accepted vehicles without `ScheduledWeekOf` are Unscheduled; and accepted vehicles with a week are
Scheduled. Ready to Build is also derived from build finalized + Parts Ready + At DTM, except for a
visible reasoned override. Schedule fields are independent and may be edited one at a time, even
before acceptance. `MustDeliverByDate` is never pushed forward because pickup,
palletization/staging, or other internal work was delayed unless a user explicitly stores
`MustDeliverOverrideDate`; clearing that override immediately restores the derived date.

#### Parts

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `PartsStatus` | Choice | no | yes | blank, `ordered`, `partially_received`, `received`, `parts_ready` |
| `PartsStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `PartsOrderedAtUtc` | Date/time | no | no | Current-cycle ordering milestone |
| `PartsPartiallyReceivedAtUtc` | Date/time | no | no | Current-cycle milestone |
| `PartsReceivedAtUtc` | Date/time | no | no | Current-cycle milestone |
| `PartsReadyAtUtc` | Date/time | no | no | Current-cycle milestone; pallet/staging implied |

#### Build / Shop

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `ShopStatus` | Choice | no | yes | blank, `in_progress`, `complete` |
| `ShopStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `ShopStartedAtUtc` | Date/time | no | no | Current-cycle start |
| `ShopCompletedAtUtc` | Date/time | no | no | Current-cycle completion |

#### Tray

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `TrayStatus` | Choice | yes | yes | `not_ready`, `ready`, `complete` |
| `TrayStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `TrayReadyAtUtc` | Date/time | no | no | Current-cycle ready milestone |
| `TrayCompletedAtUtc` | Date/time | no | no | Current-cycle completion |

#### Programming & QC

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `ProgrammingQcStatus` | Choice | yes | yes | `not_ready`, `ready`, `complete` |
| `ProgrammingQcStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `ProgrammingQcReadyAtUtc` | Date/time | no | no | Current-cycle ready milestone |
| `ProgrammingQcCompletedAtUtc` | Date/time | no | no | Current-cycle completion |

#### Final Finish

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `FinalFinishStatus` | Choice | yes | yes | `not_ready`, `ready_for_wash_clean_photos`, `ready_for_delivery`, `delivered` |
| `FinalFinishStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `FinalFinishReadyAtUtc` | Date/time | no | no | Ready for wash/clean/photos |
| `ReadyForDeliveryAtUtc` | Date/time | no | no | Current-cycle delivery readiness |

#### Delivery

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `DeliveredDate` | Date only | no | yes | Business-effective delivery/customer-pickup date |
| `DeliveryMethod` | Choice | no | no | blank, `dtm_delivery`, or `customer_pickup` |

Ready for Delivery and Delivered are consecutive `FinalFinishStatus` values; entering Delivered
also stamps `DeliveredDate`. A separate closeout workflow is deferred.

#### QBO read-only observation

| Internal name | Type | Required | Meaning |
|---|---|---:|---|
| `QboProjectId` | Single line text | no | Known QBO Project ID projected from Builder |
| `QboProjectName` | Single line text | no | Last known QBO Project display name |
| `QboEstimateId` | Single line text | no | QBO internal Estimate ID |
| `QboEstimateNumber` | Single line text | no | User-facing QBO document number |
| `QboEstimateStatus` | Single line text | no | Raw normalized QBO transaction status |
| `QboEstimateSentStatus` | Single line text | no | `sent`, `not_confirmed`, or empty (unknown); historical evidence scoped to the linked Estimate |
| `QboEstimateSentAtUtc` | Date/time | no | QBO delivery time when supplied; never inferred from observation time |
| `QboEstimateAcceptedAtUtc` | Date/time | no | QBO acceptance evidence kept separate from manual acceptance |
| `QboEstimateLastModifiedAtUtc` | Date/time | no | QBO-provided last modification time when available |
| `QboCheckedAtUtc` | Date/time | no | Most recent successful observation |
| `QboCheckedByEntraId` | Single line text | no | Opaque Entra object ID of observer |
| `QboCheckedByName` | Single line text | no | Display-only observer name |
| `QboDiffStatus` | Choice | no | `not_linked`, `untracked`, `unchanged`, `modified`, `missing` |

No QBO token, customer payload, Estimate lines, quantities, prices, or raw response body belongs in
this list. A manually entered acceptance remains authoritative when an Estimate is linked later.
QBO acceptance confirms it without replacing its original timestamp/source; a non-accepted linked
Estimate creates a visible mismatch instead of silently undoing it. The UI warns when
`QboCheckedAtUtc` is at least 24 hours old.

#### Concurrency and audit projection

| Internal name | Type | Required | Indexed/unique | Meaning |
|---|---|---:|---|---|
| `Revision` | Number, integer | yes | no | Monotonic application revision, starts at 0 |
| `LastEventId` | Single line text | no | no | Event that produced current projection |
| `CreatedAtUtc` | Date/time | yes | no | Application creation time in UTC |
| `CreatedByEntraId` | Single line text | no | no | Opaque creator ID |
| `CreatedByName` | Single line text | no | no | Display-only creator name |
| `UpdatedAtUtc` | Date/time | yes | indexed | Last accepted application mutation |
| `UpdatedByEntraId` | Single line text | no | no | Opaque actor ID |
| `UpdatedByName` | Single line text | no | no | Display-only actor name |
| `SourceClient` | Choice | no | no | `builder_desktop`, `power_apps_mobile`, `migration`, `system` |

SharePoint's built-in `Created`, `Modified`, `Author`, and `Editor` remain enabled.

The table intentionally budgets 19 indexed columns, including the unique vehicle key and full VIN.
SharePoint supports at most 20 indexes per list, so one slot is reserved for a post-pilot query need.
Do not enable automatic/manual indexes on additional columns without reviewing this budget. See
[Microsoft's index guidance](https://support.microsoft.com/en-US/SharePoint/data-and-lists/add-an-index-to-a-list-or-library-column).

### List: `DTMVehicleEvents`

**Creation/display name:** `DTMVehicleEvents` (Builder label: DTM Vehicle Events)
**Cardinality:** append-only, one item per accepted mutation
**Authority:** audit timeline

| Internal name | Type | Required | Indexed/unique | Meaning |
|---|---|---:|---|---|
| `Title` | Single line text | yes | no | Display label, normally event type + vehicle label |
| `SchemaVersion` | Number, integer | yes | no | Event schema version |
| `EventId` | Single line text | yes | indexed + unique | Opaque UUID generated for this event |
| `RequestId` | Single line text | yes | indexed + unique | Client idempotency key |
| `BuilderVehicleId` | Single line text | yes | indexed | Vehicle relationship |
| `BuilderProjectId` | Single line text | yes | indexed | Project relationship |
| `Workstream` | Choice | yes | indexed | `record`, `acceptance`, `availability`, `schedule`, `parts`, `shop`, `tray`, `programming_qc`, `final_finish`, `delivery`, `qbo` |
| `EventType` | Choice | yes | indexed | `record_created`, `projection_refreshed`, `status_changed`, `acceptance_changed`, `availability_changed`, `schedule_changed`, `delivery_changed`, `qbo_observed` |
| `PreviousValue` | Multiple lines text, plain | no | no | Prior serialized value |
| `NewValue` | Multiple lines text, plain | no | no | New serialized value |
| `OccurredAtUtc` | Date/time | yes | indexed | Accepted mutation time in UTC |
| `EffectiveDate` | Date only | no | indexed | Business date when different from entry/audit time |
| `ActorEntraId` | Single line text | no | indexed | Opaque Entra object ID |
| `ActorDisplayName` | Single line text | no | no | Display-only actor name |
| `PerformedByName` | Single line text | no | indexed | Optional technician selected when a shared shop identity is used |
| `SourceClient` | Choice | yes | indexed | Same tokens as current list |
| `SourceAppVersion` | Single line text | no | no | Client version for support/audit |
| `Reason` | Multiple lines text, plain | no | no | Required for correction/regression |
| `RecordRevision` | Number, integer | yes | no | Resulting current-record revision |
| `CommitStatus` | Choice | yes | indexed | Infrastructure state: `pending`, `applied`, or `conflict` |
| `RecordSnapshotJson` | Multiple lines text, plain | yes | no | Complete intended current record for interrupted-write recovery |

An event is created as `pending`, changed once to `applied` after its current projection is safely
written, or to `conflict` when another revision won. Applied events are never updated or deleted
through normal application workflows; a correction creates a new event. The recovery snapshot is
backend-only and lets a retry finish a write interrupted between the two lists. Conflict attempts
remain available for administration but are not presented as accepted timeline events. V1 retains
the full applied-event history indefinitely. Any future scale-driven archival must remain lossless
and readable; it cannot silently delete vehicle history.

### List: `DTMOperationsRequests`

**Creation/display name:** `DTMOperationsRequests` (Builder label: DTM Operations Requests)
**Cardinality:** append-only, one item per phone status command
**Authority:** request/result transport only; never authoritative current state or history

| Internal name | Type | Required | Indexed/unique | Meaning |
|---|---|---:|---|---|
| `Title` | Single line text | yes | no | Display label; Power Apps sets this to the request UUID |
| `SchemaVersion` | Number, integer | yes | no | Phone request schema version, initially `1` |
| `RequestId` | Single line text | yes | indexed + unique | Client-generated UUID and idempotency key |
| `BuilderVehicleId` | Single line text | yes | indexed | Durable vehicle relationship |
| `ExpectedRevision` | Number, integer | yes | no | Revision shown to the phone when the user initiated the action |
| `Workstream` | Choice | yes | indexed | `shop`, `tray`, `programming_qc`, or `final_finish` |
| `RequestedStatus` | Choice | yes | no | One of the allowed forward target tokens; `not_ready` is deliberately absent |
| `PerformedByName` | Single line text | no | no | Optional technician selected under a shared account |
| `SourceAppVersion` | Single line text | no | no | Phone app version for support |
| `ProcessingStatus` | Choice | yes | indexed | `pending`, `processing`, `applied`, `unchanged`, `conflict`, `rejected`, or `failed` |
| `ProcessingStartedAtUtc` | Date/time | no | no | Time the flow claimed the request |
| `ProcessedAtUtc` | Date/time | no | indexed | Time the processor reached a terminal result |
| `ActorEntraId` | Single line text | no | indexed | Optional trusted object ID resolved from SharePoint's Created By identity; deferred in phone v1 |
| `ActorDisplayName` | Single line text | no | no | Trusted SharePoint Created By display name recorded by the processor |
| `ResultRevision` | Number, integer | no | no | Accepted current-row revision, including unchanged duplicates |
| `ResultEventId` | Single line text | no | no | Applied event relationship; normally the same UUID as `RequestId` |
| `ResultMessage` | Multiple lines text, plain | no | no | Short non-sensitive result suitable for phone display |
| `ProcessorRunId` | Single line text | no | no | Flow-run identifier for support and retry diagnosis |

Allowed `RequestedStatus` values are `in_progress`, `complete`, `ready`,
`ready_for_wash_clean_photos`, `ready_for_delivery`, and `delivered`. The processor validates the
workstream/status pair and the normal next-state table below; a choice existing in this union does
not make it valid for every workstream.

Phone users only create request rows with `ProcessingStatus=pending`. They do not edit or delete a
request after creation and receive no direct write path to `DTMVehicleOperations` or
`DTMVehicleEvents`. The processor owns every other processing/result field. A stale revision is a
normal `conflict`, not an overwrite. Backward/skipped transitions and corrections are rejected on
the phone and remain manager-only desktop actions with a required reason.

### Domain values and normal transitions

| Workstream | Initial | Normal next values |
|---|---|---|
| Parts | blank | blank -> ordered, partially_received, or received; ordered -> partially_received or received; partially_received -> received; received -> parts_ready |
| Shop | blank | blank -> in_progress; in_progress -> complete |
| Tray | not_ready | not_ready -> ready; ready -> complete |
| Programming & QC | not_ready | not_ready -> ready; ready -> complete |
| Final Finish | not_ready | not_ready -> ready_for_wash_clean_photos; ready_for_wash_clean_photos -> ready_for_delivery; ready_for_delivery -> delivered |

Identical-state requests are no-ops. Other transitions require correction permission and a reason.
No cross-workstream ordering is enforced.

Calendar and Operations share the existing acceptance fields. Manual corrections store the
selected Chicago business date as UTC and append an immutable acceptance-change event.
QBO AcceptedDate remains date-only evidence even if serialized at midnight UTC; observation
time never substitutes for acceptance. Business-date fields use ISO `YYYY-MM-DD`.

## Roles and capabilities

### Entra application roles

| App-role value | Intended user | Default workspace |
|---|---|---|
| `AppAdmin` | Application owner/administrator | All workspaces |
| `BuilderEditor` | Sales/build designer/estimator | Projects / Builder |
| `OperationsManager` | Production coordinator or trusted workflow corrector | Operations overview |
| `PartsEditor` | Parts staff and QuickBooks estimate-connection users | Parts queue |
| `ShopEditor` | Shop technicians/build staff | Shop queue |
| `ProgrammingQcEditor` | Programming and QC staff | Programming & QC queue |
| `OperationsViewer` | Read-only management/office user | Operations overview |

Role names never contain employee names. Assignment is administered in Entra, not in a local JSON
file. If the tenant has licensing for group-based enterprise-app assignment, security groups may be
assigned to app roles. Otherwise the small user population can receive direct user assignments.

### Backend capabilities

| Capability | Meaning |
|---|---|
| `operations.view` | Read current operations and timeline |
| `operations.availability.update` | Change vehicle availability/location and effective date |
| `operations.schedule.update` | Change scheduled week, planned start, or target finish |
| `operations.parts.update` | Change Parts status |
| `operations.shop.update` | Start/complete Build / Shop |
| `operations.tray.update` | Change Tray status |
| `operations.programming_qc.update` | Change Programming & QC status |
| `operations.final_finish.update` | Change Final Finish status |
| `operations.delivery.update` | Record or correct physical delivery |
| `operations.correct` | Regress/skip normal status flow with required reason |
| `operations.qbo.observe` | Refresh shared QBO observation fields |
| `projects.view` | Read Builder projects, vehicle details, build summaries, PDFs, folders, and photos |
| `projects.edit` | Create/edit Builder projects and vehicle facts |
| `projects.lifecycle.update` | Move projects Active/Inactive/Completed |
| `estimates.manage` | Link/create/update QBO Estimates with safeguards |
| `settings.general.manage` | General settings administration |
| `settings.advanced.manage` | Advanced catalog/layout administration |
| `roles.inspect` | View resolved session roles/capabilities for support |

### Initial role mapping

| Role | Capabilities |
|---|---|
| `AppAdmin` | all capabilities |
| `BuilderEditor` | `projects.view`, `projects.edit`, `projects.lifecycle.update`, `estimates.manage`, `operations.view`, `operations.availability.update`, `operations.parts.update`, `operations.qbo.observe` |
| `OperationsManager` | `projects.view`; all `operations.*`, including scheduling, delivery, and correction; `projects.lifecycle.update` |
| `PartsEditor` | `projects.view`, `estimates.manage`, `operations.view`, `operations.parts.update` |
| `ShopEditor` | `projects.view`, `operations.view`, `operations.shop.update`, `operations.tray.update`, `operations.final_finish.update` |
| `ProgrammingQcEditor` | `projects.view`, `operations.view`, `operations.programming_qc.update`, `operations.final_finish.update` |
| `OperationsViewer` | `projects.view`, `operations.view` |

Final Finish is editable by both Shop and Programming & QC because wash/clean/photos may cross team
ownership.
