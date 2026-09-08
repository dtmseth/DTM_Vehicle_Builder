# Operations Roles and Capabilities

**Status:** Approved V1 authorization contract
**Last updated:** 2026-09-04

The same DTM Vehicle Builder installer can expose different workspaces after Microsoft 365 sign-in.
Microsoft Entra app roles are stable bundles, and backend capabilities enforce those roles within
DTM applications. Users may hold multiple roles.

## 1. Entra application roles

| App-role value | Intended user | Default workspace |
|---|---|---|
| `AppAdmin` | Application owner/administrator | All workspaces |
| `BuilderEditor` | Sales/build designer/estimator | Projects / Builder |
| `OperationsManager` | Production coordinator or trusted workflow corrector | Operations overview |
| `PartsEditor` | Parts staff | Parts queue |
| `ShopEditor` | Shop technicians/build staff | Shop queue |
| `ProgrammingQcEditor` | Programming and QC staff | Programming & QC queue |
| `OperationsViewer` | Read-only management/office user | Operations overview |

Role names never contain employee names. Assignment is administered in Entra, not in a local JSON
file. If the tenant has licensing for group-based enterprise-app assignment, security groups may be
assigned to app roles. Otherwise the small user population can receive direct user assignments.

## 2. Backend capabilities

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
| `projects.edit` | Create/edit Builder projects and vehicle facts |
| `projects.lifecycle.update` | Move projects Active/Inactive/Completed |
| `estimates.manage` | Link/create/update QBO Estimates with safeguards |
| `settings.general.manage` | General settings administration |
| `settings.advanced.manage` | Advanced catalog/layout administration |
| `roles.inspect` | View resolved session roles/capabilities for support |

## 3. Initial role mapping

| Role | Capabilities |
|---|---|
| `AppAdmin` | all capabilities |
| `BuilderEditor` | `operations.view`, `operations.availability.update`, `operations.qbo.observe`, `projects.edit`, `projects.lifecycle.update`, `estimates.manage` |
| `OperationsManager` | all `operations.*`, including scheduling, delivery, and correction; `projects.lifecycle.update` |
| `PartsEditor` | `operations.view`, `operations.parts.update` |
| `ShopEditor` | `operations.view`, `operations.shop.update`, `operations.tray.update`, `operations.final_finish.update` |
| `ProgrammingQcEditor` | `operations.view`, `operations.programming_qc.update`, `operations.final_finish.update` |
| `OperationsViewer` | `operations.view` |

Final Finish is editable by both Shop and Programming & QC because wash/clean/photos may cross team
ownership.

## 4. Enforcement rules

- The browser requests a safe session description containing identity, roles, and capabilities.
- The browser uses capabilities to select the default workspace and hide unavailable navigation.
- Every mutating route independently requires its capability.
- UI visibility is never treated as authorization.
- Unknown roles grant nothing.
- No verified roles means deny mutations; an explicitly configured local-development profile may
  use a documented synthetic admin identity only outside production bundles.
- Role resolution failure never falls back to a more privileged role.
- Cached roles expire and are re-evaluated after account switch or token refresh.
- Audit events store the actor's Entra object ID and display name, not just email.
- Corrections require `operations.correct` and a non-empty reason.

Current rollout state: the Operations header, read routes, projection creation route, and status
route enforce this contract. The browser shows only status workstreams granted by the session, and
the backend repeats the capability check for every vehicle mutation. The existing Projects and
Settings routes retain their production behavior until each is migrated behind its documented
capability; assigning an Operations role does not yet reduce access to those older screens.

## 5. Shared shop identity

V1 must work with the existing shared Microsoft 365 shop account. That account receives only the
`ShopEditor` role. Its Entra object ID remains the authenticated actor on every event. Selecting an
individual technician is normally optional and is stored separately as `PerformedByName`; it must
never pretend that the manually selected name was the authenticated user. Under a shared account,
the phone UI prominently offers the selection when marking Final Finish Ready for Delivery and for
future issue/comment entries, but a blank selection remains allowed.

When technicians later receive individual Microsoft accounts, assign the same app role to those
accounts and leave `PerformedByName` blank. No list or event migration is required.

## 6. SharePoint boundary

Entra app roles govern behavior inside DTM applications. They do not replace SharePoint access
control. Delegated Graph access is the intersection of the app's granted scopes and the signed-in
user's SharePoint permissions.

For V1, both operations lists inherit the existing SharePoint site's permissions. This lets the
current, less-privileged users continue using the app without maintaining a second permissions
scheme. DTM's role and capability checks still hide irrelevant workspaces and reject unauthorized
actions through DTM routes, which protects the normal workflow from accidental edits.

This is deliberately a simple operational guard, not a strict security boundary against a user who
already has SharePoint permission and deliberately opens or calls the lists directly. The list UI
remains an administrative recovery surface. If stronger isolation becomes necessary later, use
separate list permissions or a trusted hosted service rather than relying on hidden client controls.
Builder project and draft libraries remain separately permissioned.

## 7. Workspace behavior

- Users with one role land directly in that role's workspace.
- Users with several operational roles may switch between their allowed workspaces.
- Builder users retain the existing Projects experience and may open Operations if permitted.
- Phone users receive only the minimal shared Power App; Power App sharing and SharePoint access
  are limited to the intended Entra users/groups.
- A Shop user's package may still contain desktop Builder code, so unavailable local API routes
  must remain protected even when their JavaScript controls are absent.

## 8. Test matrix

Every capability-changing release must prove:

- each role receives exactly its documented capabilities;
- multiple roles produce the union of capabilities;
- unknown roles produce no capabilities;
- AppAdmin receives the complete known capability set;
- each operations workstream accepts its authorized role and rejects the others;
- corrections fail without both permission and reason;
- account switching invalidates the old capability session;
- direct local API calls cannot bypass hidden navigation.
