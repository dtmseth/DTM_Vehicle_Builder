# QuickBooks Online Integration — Design Document

**Status**: Design / Pre-implementation  
**Last updated**: 2026-06-15  
**Scope**: Internal app only (DTM Vehicle Builder ↔ single QBO company)

---

## Overview

This document describes the planned integration between DTM Vehicle Builder and QuickBooks Online (QBO). The integration serves two purposes:

1. **Parts catalog sync** — QBO Items become the authoritative source for part numbers, pricing, and active/inactive status. The Vehicle Builder layers categorization data (placement rules, build types, vehicle compatibility) on top that QBO does not have.
2. **Project / time-tracking bridge** — VB projects and individual units are reflected as QBO Customers and QBO Projects so technician time can be logged against specific vehicles in QuickBooks.

End users of the Vehicle Builder app never interact with QuickBooks auth. A one-time setup flow (run by the app owner) produces long-lived tokens stored in the workspace config.

---

## Prerequisites and QBO Account Setup

### ⚠️ Production Keys Are Required

QuickBooks Online has two key environments:

| Environment | Access | Use case |
|-------------|--------|----------|
| Development (Sandbox) | Connects only to Intuit's fake sandbox companies | Testing against dummy data |
| **Production** | Connects to real QBO companies | **This is what we need** |

Development keys **cannot** connect to a live company. Even for an internal/unlisted app, Production keys are required to access real data.

**To obtain Production keys:**
1. Go to the [Intuit Developer Dashboard](https://developer.intuit.com)
2. Select your app → navigate to the **Production** tab
3. Complete the **App Assessment Questionnaire** (internal/unlisted apps do not need App Store review or marketing approval — just the questionnaire)
4. Once approved, copy the Production **Client ID** and **Client Secret**
5. In the Production tab, register `http://localhost:7655/api/quickbooks/callback` as an allowed redirect URI

The app does not need to be listed on the QuickBooks App Store. It can remain private/unlisted.

### Required OAuth Scopes

```
com.intuit.quickbooks.accounting
```

This single scope covers Items, Customers, Projects, and Time Activity — everything needed.

---

## Authentication Design

### OAuth 2.0 One-Time Setup Flow

```
Owner opens Settings → QuickBooks → clicks "Connect to QuickBooks"
  │
  ├─ App opens browser tab to Intuit OAuth URL
  │    https://appcenter.intuit.com/connect/oauth2?
  │      client_id=...&redirect_uri=http://localhost:7655/api/quickbooks/callback
  │      &scope=com.intuit.quickbooks.accounting&response_type=code&state=...
  │
  ├─ Owner logs into QBO, selects their company, clicks Authorize
  │
  ├─ Browser redirects to http://localhost:7655/api/quickbooks/callback?code=...&realmId=...
  │
  ├─ App exchanges code for access_token + refresh_token via POST to Intuit token endpoint
  │
  └─ App saves tokens + realm_id to workspace/config/quickbooks_config.json
       (connection status badge turns green)
```

After this, the owner never needs to interact with QuickBooks auth again under normal conditions.

### Token Lifecycle

QuickBooks tokens behave as follows:

| Token | Lifetime | Notes |
|-------|----------|-------|
| `access_token` | 1 hour | Used for every API call |
| `refresh_token` | 100 days of inactivity | **Rotates on every use** — must be saved after every refresh |
| Hard maximum | 5 years | After 5 years, user must click "Reconnect" once |

**Critical implementation detail**: Every time `quickbooks_service` calls the token refresh endpoint to get a new access token, QBO issues a **new** refresh token in the response. The old refresh token is immediately invalidated. The service must overwrite the saved refresh token on every refresh or the integration will break within 24 hours.

The token refresh cycle runs automatically before any API call when `access_token` is within 5 minutes of expiry.

### Token Storage

`workspace/config/quickbooks_config.json`:

```json
{
  "client_id": "ABxxxx",
  "client_secret": "xxxx",
  "realm_id": "1234567890",
  "access_token": "eyJ...",
  "refresh_token": "AB11...",
  "token_expiry_utc": "2026-06-15T17:30:00Z",
  "refresh_expiry_utc": "2026-09-24T14:00:00Z",
  "hard_expiry_utc": "2031-06-15T14:00:00Z",
  "last_sync_utc": null,
  "connection_status": "connected"
}
```

`client_secret` is stored in the workspace config (local machine only, git-ignored). The workspace is never synced to SharePoint — this file stays local.

---

## Architecture

### New Files

```
src/dtm_buildsheet/
  app/
    routes/
      quickbooks.py              ← /api/quickbooks/* route handler

    services/
      quickbooks_service.py      ← QBO API client, OAuth flow, token lifecycle
      qb_sync_service.py         ← sync orchestration (parts, projects)

  ui/js/settings/
    quickbooks.js                ← Settings → QuickBooks tab UI

workspace/config/
  quickbooks_config.json         ← tokens, realm_id, sync state (git-ignored, local only)
```

### Existing Files Modified

| File | Change |
|------|--------|
| `domain/project_models.py` | Add `qb_customer_id`, `qb_project_id` to `ProjectRecord` |
| `app/server.py` | Register `/api/quickbooks/*` routes |
| `ui/index.html` | Add QuickBooks stab to General Settings |
| `ui/js/main.js` | Wire QuickBooks tab init |
| `config/schemas.py` | Add `quickbooks_config` schema + migration |
| `parts_db.json` | Add `qb_item_id`, `qb_sku` fields per part entry |

---

## Parts Catalog Sync

### QBO → Vehicle Builder Flow

```
qb_sync_service.sync_items()
  │
  ├─ GET /v3/company/{realmId}/query
  │    SELECT * FROM Item WHERE Active = true
  │
  ├─ For each QBO Item:
  │    ├─ Look up qb_item_id in local parts_db.json
  │    │
  │    ├─ MATCHED → update name, sku, price, active status on VB part record
  │    │
  │    └─ UNMATCHED → add to "pending_qb_items" list in quickbooks_config.json
  │                    (surfaces in Settings → QuickBooks as "Uncategorized Items")
  │
  └─ For each local part with qb_item_id not in QBO response:
       mark as qb_inactive: true (do not delete — may be referenced by old builds)
```

### Parts Data Model Addition

Each entry in `parts_db.json` gains optional QB fields:

```json
{
  "part_type_id": "...",
  "name": "Whelen Liberty II",
  "qb_item_id": "847",
  "qb_sku": "WL-LIB2-RBW",
  "qb_unit_price": 1249.00,
  "qb_inactive": false,
  "qb_last_synced": "2026-06-15T14:00:00Z"
}
```

QBO is the source of truth for `sku`, `unit_price`, and `active` status. Vehicle Builder owns everything else (placement rules, compatible vehicles, build types, etc.).

### Categorization UI ("Uncategorized QB Items" Queue)

When new QBO Items arrive without a matching VB part, they appear in a review queue in Settings → QuickBooks:

```
┌─────────────────────────────────────────────────────────────┐
│  Uncategorized QuickBooks Items (12)                        │
│                                                             │
│  SKU: WL-LIB2-RED    "Whelen Liberty II Red/White"          │
│  Link to existing part: [  search parts...  ▼ ]            │
│  — or —  [ Create new VB part from this item ]             │
│                                                             │
│  SKU: DTM-CAGE-F150  "Prisoner Partition F150"              │
│  Link to existing part: [  search parts...  ▼ ]            │
│  — or —  [ Create new VB part from this item ]             │
│  ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

Once linked, the `qb_item_id` is written to the VB part record and that item never appears in the queue again. "Create new VB part" opens the Part Manager form pre-filled with the QBO Item data, then auto-links on save.

### Sync Triggers

- App start (background, non-blocking)
- Periodic background poll every 30 minutes while app is running
- Manual "Sync Now" button in Settings → QuickBooks
- (Optional, Phase 2) QBO Webhook push — see Webhooks section below

---

## Project / Customer Bridge

### Data Model

```python
# domain/project_models.py
@dataclass
class ProjectRecord:
    ...
    qb_customer_id: str = ""   # QBO Customer.Id for the agency
    qb_project_id: str = ""    # QBO Project (Customer with IsProject=true) Id
```

### QBO Structure for a Build

QBO does not have a native "Project" object at the API level. Projects are represented as Customers with `Job=true` (V2 API) linked to a parent Customer. The structure mirrors VB naturally:

```
QBO Customer: Lakeville Police Department       ← matches VB agency
  └─ QBO Project: 2025 Tahoe Fleet #26-043      ← matches VB ProjectRecord
       (IsProject=true, linked to parent Customer)
```

Per-vehicle tracking at the `IndividualUnit` level is done via time entries tagged to the parent QBO Project with the unit number in the description/memo field, rather than creating a sub-project per vehicle. This keeps QBO clean — one project per build, time entries carry the unit context.

### Push Flow (VB → QBO)

Triggered by "Push to QuickBooks" button on the Builds tab (or auto on Export, configurable):

```
qb_sync_service.push_project(project_record)
  │
  ├─ Look up agency by qb_customer_id
  │    MISSING → search QBO Customers by name, prompt to confirm match or create new
  │    FOUND   → use existing Customer.Id
  │
  ├─ Create QBO Project linked to Customer
  │    POST /v3/company/{realmId}/customer
  │    { "DisplayName": "2025 Tahoe Fleet #26-043",
  │      "Job": true, "ParentRef": {"value": qb_customer_id} }
  │
  ├─ Save returned QBO Project.Id → project_record.qb_project_id
  │
  └─ Save project record
```

After this, technicians open QuickBooks and log time against the project normally. VB does not manage time entries — it only creates the project scaffold.

---

## API Route Map

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/api/quickbooks/status` | `quickbooks.py` | Connection status, last sync, token expiry |
| GET | `/api/quickbooks/auth-url` | `quickbooks.py` | Returns OAuth URL to open in browser |
| GET | `/api/quickbooks/callback` | `quickbooks.py` | OAuth redirect target — exchanges code for tokens |
| POST | `/api/quickbooks/disconnect` | `quickbooks.py` | Clears tokens, sets status to disconnected |
| POST | `/api/quickbooks/sync` | `quickbooks.py` | Trigger manual sync now |
| GET | `/api/quickbooks/pending-items` | `quickbooks.py` | List unmatched QBO Items |
| POST | `/api/quickbooks/link-item` | `quickbooks.py` | Link QBO item_id to VB part |
| POST | `/api/quickbooks/push-project` | `quickbooks.py` | Push VB project to QBO |

---

## Settings UI

**Settings → General → QuickBooks** (new outer stab)

```
┌──────────────────────────────────────────────────────────────┐
│  QuickBooks Online                         ● Connected        │
│  Company: DTM Emergency Vehicles                             │
│  Last synced: 2026-06-15 at 10:42 AM   [ Sync Now ]        │
│  Token renews: 2026-09-23  Hard expiry: 2031-06-15          │
│                                          [ Disconnect ]      │
├──────────────────────────────────────────────────────────────┤
│  Uncategorized Items (12)                [ Review Items ]    │
├──────────────────────────────────────────────────────────────┤
│  Sync Log                                                    │
│  2026-06-15 10:42  Parts sync: 214 active, 3 new, 1 inactive│
│  2026-06-15 09:00  Parts sync: 214 active, 0 new, 0 inactive│
│  ...                                                         │
└──────────────────────────────────────────────────────────────┘
```

If `connection_status` is `disconnected` or `expired`, the tab shows a "Connect to QuickBooks" button instead.

---

## Optional Phase 2: QBO Webhooks

Instead of polling every 30 minutes, QBO can push a notification to the app the moment an Item or Customer changes. This requires:

1. A publicly accessible webhook endpoint (not `localhost`) — this means either:
   - A cloud relay (e.g., a small hosted endpoint that forwards to the running local app), or
   - Only useful if/when the app is ever deployed as a hosted service rather than a local desktop app
2. Webhook signature verification (HMAC-SHA256 with a verifier token from QBO)
3. Registering the endpoint in the Intuit Developer Dashboard

**Recommendation**: Defer webhooks. Polling every 30 minutes is sufficient for a desktop app used by one team. Webhooks become relevant if the app moves to a hosted/cloud deployment.

---

## Implementation Phases

### Phase 1 — OAuth + Token Management
- `quickbooks_service.py`: OAuth URL generation, callback handler, token exchange, token refresh with rotation save, connection status
- `quickbooks.py` routes: `/status`, `/auth-url`, `/callback`, `/disconnect`
- `quickbooks_config.json` schema + migration
- Settings UI: connection card only

**Done when**: Can connect to live QBO company, access token auto-refreshes, refresh token rotation is correctly saved.

### Phase 2 — Parts Sync
- `qb_sync_service.sync_items()`: pull Items, match by `qb_item_id`, write `pending_qb_items`
- `parts_db.json` schema additions (`qb_item_id`, `qb_sku`, `qb_unit_price`, `qb_inactive`)
- `quickbooks.py` routes: `/sync`, `/pending-items`, `/link-item`
- Settings UI: sync status card, uncategorized items queue, review/link UI
- Background sync on app start + 30-min poll

**Done when**: New QBO Items surface in the queue, linking a QBO item to a VB part persists and removes it from the queue, deactivated QBO items flag `qb_inactive`.

### Phase 3 — Project Bridge
- `qb_sync_service.push_project()`: Customer lookup/create, Project create, write-back IDs
- `ProjectRecord` additions (`qb_customer_id`, `qb_project_id`)
- `quickbooks.py` route: `/push-project`
- Builds tab: "Push to QuickBooks" button per project

**Done when**: Pushing a project creates the correct QBO Customer + Project, IDs are saved back to the project record, re-pushing is idempotent.

---

## Known Constraints and Gotchas

- **Refresh token rotation is mandatory**: Save the new refresh token on every API call that triggers a refresh. Missing even one rotation permanently invalidates the token.
- **Production keys, not development**: Development (sandbox) keys cannot connect to a real QBO company. The App Assessment Questionnaire must be completed to get Production credentials.
- **`localhost` redirect URI must be registered**: Add `http://localhost:7655/api/quickbooks/callback` in the Intuit Developer Dashboard under Production → Redirect URIs.
- **5-year hard expiry**: Schedule a calendar reminder. After 5 years, a one-time re-authorization is required regardless of refresh activity.
- **QBO Projects = Customers with Job flag**: There is no separate Project object in the QBO v3 API. Projects are Customers where `Job=true` with a `ParentRef`.
- **`quickbooks_config.json` stays local**: This file contains credentials and must never be pushed to git or synced to SharePoint. Confirm it is in `.gitignore` and excluded from the SharePoint mirror logic.
- **Inactive QBO items are not deleted in VB**: Old builds may reference parts that have since been discontinued. `qb_inactive: true` flags the part but preserves the record.
