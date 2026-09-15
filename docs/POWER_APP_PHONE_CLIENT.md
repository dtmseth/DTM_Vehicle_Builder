# DTM Operations Phone Client

**Status:** Request list live; processor flow assembled, saved Off, and pre-pilot; Canvas app not created
**Last updated:** 2026-09-09

This is the build and recovery contract for the minimal phone Power App. It deliberately keeps the
Canvas app small and keeps production rules out of Power Fx.

## Fixed production identities

- Power Platform environment: `dtmfleet.com (default)` / `Default-ae8e001a-ccac-4c38-8bd6-580ffcb9668f`
- SharePoint site: `DTM Fleet` / `https://netorgft11566699.sharepoint.com/sites/DTMOperations`
- Current list: `DTMVehicleOperations` / `18021fb7-40fb-4fc6-904e-2b86a8fb2382`
- Timeline list: `DTMVehicleEvents` / `a1c3d845-bcc9-427d-8482-e7f66cf82ada`
- Phone queue: `DTMOperationsRequests` / `3a821086-93b0-45ca-97fc-4b4a4caeb940`
- Processor flow: `DTM Process Operations Request` / `b882a0d9-0ad0-4d90-ac7a-b3b459954a51`

Names above are machine contracts. Friendly labels belong in the app. Always bind lists by GUID
where Power Platform permits it.

## Phone write boundary

The phone creates exactly one queue row per tapped status action:

| Field | Value |
|---|---|
| `Title` | the same fresh `GUID()` used for `RequestId` |
| `SchemaVersion` | `1` |
| `RequestId` | fresh UUID generated once before `Patch` |
| `BuilderVehicleId` | selected vehicle's durable ID |
| `ExpectedRevision` | selected vehicle revision currently displayed |
| `Workstream` | `shop`, `tray`, `programming_qc`, or `final_finish` |
| `RequestedStatus` | exact stable target token |
| `PerformedByName` | optional technician display name |
| `SourceAppVersion` | phone app version constant |
| `ProcessingStatus` | `pending` |

The app never sends identity, project, previous-status, timestamp, or milestone fields as trusted
facts. SharePoint's Created By is the actor source. The flow resolves the actor and processing time.

## Processor flow contract

The SharePoint **When an item is created** trigger points to `DTMOperationsRequests`. Trigger
concurrency is enabled with degree `1`; do not disable it or increase it without a concurrency
review. The default SharePoint retry policy stays enabled.

The flow follows these terminal branches:

1. Claim the request by setting `ProcessingStatus=processing`, `ProcessingStartedAtUtc=utcNow()`,
   and `ProcessorRunId=workflow().run.name`.
2. Treat the trigger item's immutable SharePoint Created By identity as the actor source. The v1
   flow writes its display name into the event/current audit fields; `ActorEntraId` remains optional
   and blank until an object-ID lookup is added and pilot-tested.
3. Find the current row by exact `BuilderVehicleId`; zero or multiple matches is `rejected`.
4. Reject unless the request schema is `1`, initial processing state was `pending`, the current
   project is `active`, the vehicle is `accepted`, and the workstream/status pair is supported.
5. If the current value already equals the target, finish `unchanged` at the existing revision and
   create no event.
6. Compare `ExpectedRevision` with current `Revision`; a mismatch finishes `conflict` and performs
   no current/event write.
7. Accept only these normal forward triples:

   - `shop`: blank → `in_progress` → `complete`
   - `tray`: `not_ready` → `ready` → `complete`
   - `programming_qc`: `not_ready` → `ready` → `complete`
   - `final_finish`: `not_ready` → `ready_for_wash_clean_photos` →
     `ready_for_delivery` → `delivered`

8. Build the complete intended current snapshot. Set the chosen status, its Changed timestamp, the
   reached milestone timestamp, `Revision + 1`, `LastEventId=RequestId`, `UpdatedAtUtc=utcNow()`,
   trusted actor fields, and `SourceClient=power_apps_mobile`. Delivered uses the processing date
   for `DeliveredDate`.
9. Create a `DTMVehicleEvents` item with `EventId=RequestId`, `RequestId=RequestId`, the current
   project/vehicle IDs, `EventType=status_changed`, old/new values, actor, optional technician,
   resulting revision, `CommitStatus=pending`, and the complete intended snapshot. Unique IDs on
   both lists prevent a second request/event from reusing the same UUID.
10. PATCH the current SharePoint item through **Send an HTTP request to SharePoint** using its ETag
    in `IF-MATCH`. A 412 finishes both event and request as `conflict`; it never retries as an
    unconditional overwrite.
11. Mark the event `applied`, then finish the queue item `applied` with result revision/event ID.
    If event finalization is interrupted after the current PATCH, the desktop repository can recover
    the pending event from its complete snapshot.
12. Any validation failure is `rejected`. Exhausted connector/network failure is `failed`; keep the
   diagnostic short and never copy tokens, full connector bodies, or stack traces to the list.

### Saved pre-pilot flow state (2026-09-09)

The production-environment flow is assembled and saved **Off**. Flow checker reports zero errors;
its only warning is that the flow is off. Trigger concurrency is one. The configured branches cover
missing/duplicate vehicles, eligibility rejection, unchanged requests, stale revision, invalid
forward transition, the event-first happy path, and an ETag failure between the event and current
write. That mid-flight failure marks both the pending event and request as `conflict` and does not
overwrite the winning current row.

The SharePoint connection still displays the account's historical sign-in label
`sales@dtmfleet.com`, but Power Automate shows its permission identity as `seth@dtmfleet.com` and
the flow's primary owner as Seth Miller. `sales@dtmfleet.com` is now a shared mailbox; do not replace
or reauthenticate this connection merely because the old display label remains.

Before enabling the flow, finish these intentionally deferred pilot items:

1. Decide and implement a terminal `failed` handler for exhausted connector/network failures after
   a request has been claimed. The current draft can otherwise leave such a request in `processing`.
2. Confirm the intended recovery procedure for a flow interrupted after creating a pending event.
   The complete snapshot supports desktop recovery, but automated replay is not yet implemented.
3. Run the owner-approved pilot matrix below and inspect the actual SharePoint rows, especially the
   serialized `RecordSnapshotJson` produced by Power Automate.
4. Only then enable the flow and begin the Canvas app in a fresh session.

The processor does not perform corrections, skipped steps, project completion, scheduling,
availability, Parts, or QBO work. Final Finish `delivered` project completion remains a deliberate
post-pilot extension because Power Automate must compare every exact project vehicle safely.

## Canvas v1

Use one responsive screen and one inline detail container:

- selected **Active** queue by default; searchable agency, vehicle, unit, and full VIN;
- collapsed project groups with vehicles inside;
- read-only Builder summary, current shop document/photo links, freshness, and newest-first timeline;
- only the large next-step buttons allowed for the signed-in app variant;
- optional technician selector prominently shown before Ready for Delivery and Delivered;
- after request creation, poll that exact `RequestId` until a terminal result, then refresh current
  and events; conflicts explain that someone else changed the vehicle and refresh automatically;
- explicit offline/error state; never display an optimistic success before the queue result is
  `applied` or `unchanged`.

The app has no QBO connection, project/build editing, schedule editor, catalog/settings surfaces,
offline write queue, Dataverse, custom connector, gateway, or premium connector.

## Pilot gate

Before sharing the app:

1. Save the flow turned off or with no phone users while assembling it.
2. Validate missing vehicle, inactive/completed project, unaccepted vehicle, invalid target, stale
   revision, duplicate request ID, and unchanged target without a current-row mutation.
3. Run one owner-approved forward transition on a disposable/current pilot vehicle.
4. Verify request terminal result, current revision/status/timestamp, and exactly one applied event.
5. Resubmit/retry the same request and prove no second event or revision.
6. Share the Canvas app and request-list create access only with intended phone users.

## Fresh-session starting point

Do not recreate the request list or processor. Open the existing flow by the fixed ID above, keep it
Off, add the failure/recovery handling, and perform the pilot gate. After that, create the Canvas app
from blank using the `Canvas v1` scope in this document. The blank-app creation dialog was opened
once and closed without creating an app, so there is no abandoned Canvas app to clean up.

The authoritative field list is [OPERATIONS_SCHEMA.md](OPERATIONS_SCHEMA.md); roles and the shared
account policy are [OPERATIONS_ROLES.md](OPERATIONS_ROLES.md).
