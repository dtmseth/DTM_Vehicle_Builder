# Operations Data Schema

**Status:** Exact live core schema v4 validated; phone request schema v1 approved for provisioning
**Schema version:** 4 (current/events), 1 (phone requests)
**Last updated:** 2026-09-09

This document freezes the machine-facing names for the DTM operations data layer. The display
names shown to users may be friendlier, but Python, Graph, Power Apps, tests, and future migrations
use the internal names below.

The executable source of this contract is
`app/adapters/cloud/operations_list_schema.py`. The offline manifest and provisioner must match this
document before any live creation.

## 1. Naming rules

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

## 2. List: `DTMVehicleOperations`

**Creation/display name:** `DTMVehicleOperations` (Builder label: DTM Vehicle Operations)
**Cardinality:** exactly one current item per Builder vehicle ID
**Authority:** current operations projection

### Identity and display projection

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

### Acceptance

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `AcceptanceStatus` | Choice | yes | yes | `not_accepted` or `accepted` per vehicle |
| `AcceptedAtUtc` | Date/time | no | no | First/latest valid acceptance for the current accepted cycle |
| `AcceptanceSource` | Choice | no | no | `qbo`, `manual`, or `migration` |
| `AcceptanceChangedAtUtc` | Date/time | no | no | Most recent acceptance correction/change |

`partially_accepted` is a project-card summary and is not stored on a vehicle row.

### Vehicle availability

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `VehicleAvailabilityStatus` | Choice | yes | yes | `awaiting_details`, `waiting_on_dealer`, `waiting_on_agency`, `ready_for_pickup`, `at_dtm`; legacy `delivered` remains accepted for existing history |
| `VehicleAvailabilityStatusChanged` | Date/time | no | no | Audit time of latest availability-status change (stored in UTC) |
| `VehicleAvailableDate` | Date only | no | yes | Business-effective date vehicle became available to DTM |
| `VehicleAtDtmDate` | Date only | no | no | Business date vehicle physically arrived at DTM |

Build progress, Ready for Delivery, and new delivery actions are intentionally not duplicated in
the availability choice. At DTM is this workstream's completed state. The retained `delivered`
choice is compatibility-only and is no longer presented by the Builder UI.

### Scheduling and commitment

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `ScheduledWeekOf` | Date only | no | yes | Monday of planned production week |
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

### Parts

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `PartsStatus` | Choice | no | yes | blank, `ordered`, `partially_received`, `received`, `parts_ready` |
| `PartsStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `PartsOrderedAtUtc` | Date/time | no | no | Current-cycle ordering milestone |
| `PartsPartiallyReceivedAtUtc` | Date/time | no | no | Current-cycle milestone |
| `PartsReceivedAtUtc` | Date/time | no | no | Current-cycle milestone |
| `PartsReadyAtUtc` | Date/time | no | no | Current-cycle milestone; pallet/staging implied |

### Build / Shop

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `ShopStatus` | Choice | no | yes | blank, `in_progress`, `complete` |
| `ShopStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `ShopStartedAtUtc` | Date/time | no | no | Current-cycle start |
| `ShopCompletedAtUtc` | Date/time | no | no | Current-cycle completion |

### Tray

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `TrayStatus` | Choice | yes | yes | `not_ready`, `ready`, `complete` |
| `TrayStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `TrayReadyAtUtc` | Date/time | no | no | Current-cycle ready milestone |
| `TrayCompletedAtUtc` | Date/time | no | no | Current-cycle completion |

### Programming & QC

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `ProgrammingQcStatus` | Choice | yes | yes | `not_ready`, `ready`, `complete` |
| `ProgrammingQcStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `ProgrammingQcReadyAtUtc` | Date/time | no | no | Current-cycle ready milestone |
| `ProgrammingQcCompletedAtUtc` | Date/time | no | no | Current-cycle completion |

### Final Finish

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `FinalFinishStatus` | Choice | yes | yes | `not_ready`, `ready_for_wash_clean_photos`, `ready_for_delivery`, `delivered` |
| `FinalFinishStatusChangedAtUtc` | Date/time | no | no | Current status entry time |
| `FinalFinishReadyAtUtc` | Date/time | no | no | Ready for wash/clean/photos |
| `ReadyForDeliveryAtUtc` | Date/time | no | no | Current-cycle delivery readiness |

### Delivery

| Internal name | Type | Required | Indexed | Meaning |
|---|---|---:|---:|---|
| `DeliveredDate` | Date only | no | yes | Business-effective delivery/customer-pickup date |
| `DeliveryMethod` | Choice | no | no | blank, `dtm_delivery`, or `customer_pickup` |

Ready for Delivery and Delivered are consecutive `FinalFinishStatus` values; entering Delivered
also stamps `DeliveredDate`. A separate closeout workflow is deferred.

### QBO read-only observation

| Internal name | Type | Required | Meaning |
|---|---|---:|---|
| `QboProjectId` | Single line text | no | Known QBO Project ID projected from Builder |
| `QboProjectName` | Single line text | no | Last known QBO Project display name |
| `QboEstimateId` | Single line text | no | QBO internal Estimate ID |
| `QboEstimateNumber` | Single line text | no | User-facing QBO document number |
| `QboEstimateStatus` | Single line text | no | Raw normalized QBO transaction status |
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

### Concurrency and audit projection

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

## 3. List: `DTMVehicleEvents`

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

## 4. List: `DTMOperationsRequests`

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

## 5. Domain values and normal transitions

| Workstream | Initial | Normal next values |
|---|---|---|
| Parts | blank | blank -> ordered, partially_received, or received; ordered -> partially_received or received; partially_received -> received; received -> parts_ready |
| Shop | blank | blank -> in_progress; in_progress -> complete |
| Tray | not_ready | not_ready -> ready; ready -> complete |
| Programming & QC | not_ready | not_ready -> ready; ready -> complete |
| Final Finish | not_ready | not_ready -> ready_for_wash_clean_photos; ready_for_wash_clean_photos -> ready_for_delivery; ready_for_delivery -> delivered |

Identical-state requests are no-ops. Other transitions require correction permission and a reason.
No cross-workstream ordering is enforced.

## 6. Provisioning checklist

The owner elected not to maintain a separate SharePoint test site. The provisioner is therefore
tested against mocked Graph responses and uses a read-only live preflight before creating the two
empty final lists. Existing mismatched lists are never patched, renamed, or deleted automatically.

Production provisioning completed on 2026-09-04. The completed checklist was:

1. Approve every internal name and choice token in this document.
2. Use delegated Graph `Sites.Read.All` during the read-only rollout. Add `Sites.Manage.All` only for
   one-time creation. Foreground vehicle creation and status actions acquire `Sites.ReadWrite.All`
   interactively only after an authorized user acts. Do not add an application permission or
   client secret.
3. Confirm the provisioning user can manage lists in the already configured SharePoint site.
4. Print the offline manifest with `.venv/bin/python tools/provision_operations_lists.py`.
5. Run the read-only preflight with `.venv/bin/python tools/provision_operations_lists.py --inspect`.
6. Run `--apply` only with its exact printed confirmation phrase.
7. Let the tool re-read every column and save both resulting list GUIDs into `cloud_config.json`.
8. Keep all operations clients disabled if post-create validation reports any mismatch.

The separately confirmation-gated recovery upgrade was completed on 2026-09-04. It added only
`CreatedAtUtc`, `CreatedByEntraId`, `CreatedByName`, `CommitStatus`, and `RecordSnapshotJson`.
The read-only inspector then confirmed that both empty lists exactly match this document and the
executable manifest. The Phase 3 create-one desktop pilot is implemented behind its separate
foreground write scope. Its first owner-confirmed production creation completed on 2026-09-07. A
read-only Graph verification found one current row at revision 0 and one matching applied creation
event; `LastEventId`, vehicle/project IDs, full VIN, actor, and timestamp agree across the pair. The
reviewed import then brought the production total to 78 current rows across 44 projects and 78
unique applied creation events (30 Active and 48 Completed), with no duplicate vehicle, event, or
request IDs. Status updates continue to use the same paired current-row/event repository contract.
The confirmation-gated 2026-09-08 deadline upgrade completed successfully and added only
`MustDeliverOverrideDate`. The inspector then validated both live lists with no mismatch. Its
permanent machine name was reviewed before creation so SharePoint rename behavior cannot make it
stale.

The confirmation-gated schema-v3 Parts Ordered upgrade completed successfully on 2026-09-08. It
added only the permanent `PartsOrderedAtUtc` date/time column and extended the existing
`PartsStatus` choices with the stable `ordered` token. The upgrader accepts only the exact reviewed
pre-v3 choice list and refuses any other schema mismatch. Its post-write inspection validated both
live lists with no mismatch.

Schema v4 moves the user-facing Delivered action from Vehicle Availability to Final Finish. It
adds no SharePoint columns and renames nothing. Its confirmation-gated upgrader extends only the
existing `FinalFinishStatus` choice list from the exact reviewed v3 values by appending
`delivered`; it refuses every other mismatch. The legacy availability `delivered` choice remains in
place so existing records and events stay readable. The production upgrade completed on 2026-09-08,
and its post-write inspection validated both live lists with no mismatch.

## 7. Phone request provisioning

The phone architecture is resolved: the Power App appends to `DTMOperationsRequests`, and a
standard-connector Power Automate flow validates and projects accepted requests into the existing
current/event pair. The request list has its own narrow provisioning command so the validated core
lists cannot be recreated, renamed, or patched accidentally:

```bash
.venv/bin/python tools/provision_operations_lists.py --inspect-phone-requests
.venv/bin/python tools/provision_operations_lists.py \
  --provision-phone-requests --confirm 'CREATE DTMOperationsRequests'
```

The provisioner first revalidates both core lists, creates only the missing exact request list, then
re-reads every request column before saving its GUID. Existing mismatches stop without mutation.

### Calendar acceptance-date corrections (unreleased)

Operations and Calendar share the existing AcceptedAt/source fields; there is no new column.
Manual corrections store the selected Chicago business date as UTC and append an immutable
acceptance-change event. The QBO date is date-only evidence even when SharePoint serializes it
as midnight UTC. QBO observation time remains separate and never substitutes for AcceptedDate.
