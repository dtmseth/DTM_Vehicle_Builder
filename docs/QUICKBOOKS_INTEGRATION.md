# QuickBooks Online Integration — Design Document

**Status**: Phase 1 complete — relay ready to deploy  
**Last updated**: 2026-06-15  
**Scope**: Internal app only (DTM Vehicle Builder ↔ single QBO company)

---

## Overview

This document describes the planned integration between DTM Vehicle Builder and QuickBooks Online (QBO). The integration serves two purposes:

1. **Parts catalog sync** — QBO Items become the authoritative source for part numbers, pricing, and active/inactive status. The Vehicle Builder layers categorization data (placement rules, build types, vehicle compatibility) on top that QBO does not track.
2. **Project / time-tracking bridge** — VB projects are pushed to QBO as Customer + Project records so technician time can be logged against specific builds in QuickBooks.

End users of the Vehicle Builder app never interact with QuickBooks auth. A one-time setup flow (performed by the app owner) produces long-lived encrypted tokens stored locally. After that, the connection is fully automatic.

---

## Prerequisites and QBO Account Setup

### Production Keys Are Required

QuickBooks Online has two key environments:

| Environment | Access | Use case |
|-------------|--------|----------|
| Development (Sandbox) | Connects only to Intuit's fake sandbox companies | Testing during development |
| **Production** | Connects to real QBO companies | **Required for live data** |

Development keys cannot connect to a real company. Even for an internal unlisted app, Production keys are required.

**To obtain Production keys:**
1. Go to the [Intuit Developer Dashboard](https://developer.intuit.com)
2. Select your app → navigate to the **Production** tab
3. Complete the **App Assessment Questionnaire** (see `docs/QUICKBOOKS_QUESTIONNAIRE.md` for prepared answers)
4. Once approved, copy the Production **Client ID** and **Client Secret**
5. Register the hosted relay URI as the redirect URI (see OAuth Redirect section below)

The app does not need to be listed on the QuickBooks App Store. It remains private/unlisted.

### Required OAuth Scope

```
com.intuit.quickbooks.accounting
```

This covers Items, Customers, Projects, and Time Activity.

---

## OAuth Redirect URI — Hosted Relay Required

Intuit Production keys require an **HTTPS redirect URI on a real domain**. `http://localhost` is only accepted for sandbox/development keys. This means the app needs a hosted relay endpoint to act as the OAuth landing page before handing control back to the local server.

### How the Relay Works

```
QuickBooks authorization page
  │
  └─ redirects to → https://[your-domain.com]/qb-callback?code=...&state=...&realmId=...
                         │
                         └─ server issues HTTP 302 → http://localhost:7655/api/quickbooks/callback
                                                           ?code=...&state=...&realmId=...
                                                                │
                                                                └─ local app captures tokens
```

The relay page does nothing except issue a 302 redirect. It never reads, stores, or logs the authorization code. It is a dumb pass-through. The authorization code itself is short-lived (minutes) and is only useful in combination with the client secret, which never leaves the local machine.

### Relay Implementation (Netlify or Vercel function)

A minimal serverless function is the cleanest option — it issues a proper HTTP 302 (not a JavaScript redirect, which would not comply with Intuit's redirect security requirement). Deploy to Netlify or Vercel under a domain you control:

```javascript
// netlify/functions/qb-callback.js  (or vercel equivalent)
export default function handler(req, res) {
  const params = new URLSearchParams(req.query).toString();
  res.writeHead(302, {
    Location: `http://localhost:7655/api/quickbooks/callback?${params}`
  });
  res.end();
}
```

Register `https://[your-domain.com]/.netlify/functions/qb-callback` (or equivalent) in the Intuit Developer Dashboard as the Production redirect URI.

### During Development (Sandbox Only)

For development against sandbox companies, register `http://localhost:7655/api/quickbooks/callback` separately under the Development tab. Development keys do not require HTTPS.

---

## Authentication Design

### OAuth 2.0 One-Time Setup Flow

```
Owner opens Settings → QuickBooks → clicks "Connect to QuickBooks"
  │
  ├─ Server generates cryptographically random state value, stores it temporarily
  │
  ├─ App opens system browser to Intuit OAuth URL:
  │    https://appcenter.intuit.com/connect/oauth2
  │      ?client_id=...
  │      &redirect_uri=https://[your-domain.com]/.netlify/functions/qb-callback
  │      &scope=com.intuit.quickbooks.accounting
  │      &response_type=code
  │      &state=[random-state-value]
  │
  ├─ Owner logs into QBO, selects their company, clicks Authorize
  │
  ├─ QBO → relay (302) → http://localhost:7655/api/quickbooks/callback?code=...&state=...&realmId=...
  │
  ├─ Server validates state parameter (CSRF check — reject if mismatch)
  │
  ├─ Server exchanges code for access_token + refresh_token via POST to Intuit token endpoint
  │
  ├─ Server encrypts refresh_token and realm_id using AES key from quickbooks_key.bin
  │
  ├─ Server saves encrypted values to quickbooks_config.json
  │
  └─ Server issues 302 redirect to /settings (never echoes tokens or code in HTML)
       (connection status badge turns green)
```

After this, the owner never needs to interact with QuickBooks auth again under normal conditions.

### Token Lifecycle

| Token | Lifetime | Behavior |
|-------|----------|----------|
| `access_token` | 1 hour | Used for every API call |
| `refresh_token` | 100 days of inactivity | **Rotates on every use** — new token issued and must be saved on every refresh |
| Hard maximum | 5 years | After 5 years, one-time re-authorization required |

Every time `quickbooks_service` calls the token refresh endpoint, QBO issues a **new** refresh token. The old one is immediately invalidated. The service must decrypt the stored token, refresh, then re-encrypt and save the new token atomically. Missing one rotation permanently invalidates the connection.

The token refresh cycle runs automatically before any API call when `access_token` is within 5 minutes of expiry.

---

## Token Storage — OS Keychain via `msal-extensions`

This integration reuses the exact credential-storage mechanism the existing M365/SharePoint integration already uses for its token cache (`adapters/cloud/msal_client.py`): `msal-extensions` encrypted persistence, backed by the OS-native credential store. This adds **zero new dependencies** (`msal-extensions` is already shipped) and keeps both integrations on one proven, PyInstaller-tested path. See `docs/EXTERNAL_CONNECTION_SECURITY.md` for the full standard.

Intuit's security requirements mandate AES encryption of tokens at rest with the key stored separately. The OS keychain satisfies this — the OS manages AES encryption and key storage natively, at the hardware security layer on supported platforms.

| Platform | Storage |
|----------|---------|
| macOS | Keychain |
| Windows | Windows Credential Locker (DPAPI) |
| Linux | libsecret / Secret Service (in-memory fallback if absent) |

### Credential Blob

All sensitive QB values are stored as a single encrypted JSON blob at
`<app-data>/quickbooks_credentials.bin` (same app-data dir as the M365
`msal_token_cache.bin`). The plaintext never touches the filesystem. The blob holds:

| key | Value |
|-----|-------|
| `access_token` | Current access token |
| `refresh_token` | Current refresh token |
| `realm_id` | QBO company ID (Intuit requires realmID encrypted at rest) |
| `client_secret` | OAuth client secret |

Implemented by `app/adapters/quickbooks/credential_store.py` (`QuickBooksCredentialStore`).

### quickbooks_config.json

Non-sensitive metadata only — stored as plain JSON in the workspace root (git-ignored; never written to the config-store or SharePoint mirror):

```json
{
  "client_id": "ABxxxx",
  "environment": "production",
  "redirect_uri": "https://your-domain.com/.netlify/functions/qb-callback",
  "token_expiry_utc": "2026-06-15T17:30:00Z",
  "refresh_expiry_utc": "2026-09-24T14:00:00Z",
  "hard_expiry_utc": "2031-06-15T14:00:00Z",
  "last_sync_utc": null,
  "connection_status": "connected"
}
```

`client_id` is not a secret (it appears in every OAuth URL). Expiry timestamps are for display only. No credential values appear in this file.

### Implementation

No new dependency. The store mirrors the M365 pattern:

```python
# app/adapters/quickbooks/credential_store.py (abridged)
from msal_extensions import build_encrypted_persistence

class QuickBooksCredentialStore:
    def save(self, secrets: dict) -> None:
        self._persistence().save(json.dumps(secrets))   # OS-keychain encrypted

    def load(self) -> dict:
        return json.loads(self._persistence().load())   # {} when absent
```

When the keychain backend is unavailable (e.g. headless Linux without libsecret), the store falls back to a process-lifetime in-memory map — never plaintext on disk. Losing it on restart forces re-authorization, which is the correct secure behavior.

On disconnect, call `_delete` for all four credential keys. On token refresh, call `_store("qb_refresh_token", new_token)` and `_store("qb_access_token", new_access_token)` immediately — never skip this step.

---

## Security Compliance

The following security controls must be implemented to meet Intuit's requirements. These apply to an internal/unlisted app; the subset that is relevant to a single-user local desktop app is marked.

### OAuth Callback — 302 Redirect Required

The `/api/quickbooks/callback` endpoint must **never return HTML that echoes the authorization code or any token back to the browser**. After exchanging the code and saving encrypted tokens, it must issue a `302 Found` redirect to a clean URL. This prevents the code from leaking via HTTP Referer headers.

```python
# In routes/quickbooks.py — callback handler
def _handle_callback(self, query_params):
    code = query_params.get("code")
    state = query_params.get("state")
    realm_id = query_params.get("realmId")

    if not quickbooks_service.validate_state(state):
        self._send(400, b"Invalid state", "text/plain")
        return

    quickbooks_service.exchange_code(code, realm_id)  # encrypts and saves tokens

    # 302 redirect — never echo code or tokens in HTML
    self.send_response(302)
    self.send_header("Location", "/")
    self.end_headers()
```

### CSRF Protection (OAuth State Parameter)

Before opening the browser for OAuth, generate a random state value and store it temporarily (in-memory or a temp file). Reject any callback where the returned `state` does not match. This prevents CSRF attacks against the OAuth flow.

```python
import secrets
_pending_state: str | None = None

def generate_auth_url() -> str:
    global _pending_state
    _pending_state = secrets.token_urlsafe(32)
    # include _pending_state in the OAuth URL &state= parameter

def validate_state(state: str) -> bool:
    global _pending_state
    valid = secrets.compare_digest(state or "", _pending_state or "")
    _pending_state = None  # consume once
    return valid
```

### Logging — No QB Data in Logs

The application logger must never write:
- `access_token` or `refresh_token` values
- `realm_id`
- Raw QB API response bodies (which contain Item names, prices, customer data)

Log only operation names, HTTP status codes, and timestamps. For QB API errors, log the `intuit_tid` header value (Intuit's trace ID) for troubleshooting — not the full response body.

```python
# Good:
logger.info("QB items sync: status=200, intuit_tid=%s", response.headers.get("intuit_tid"))
# Bad:
logger.debug("QB response: %s", response.json())   # may contain customer data
logger.error("Token refresh failed, token=%s", refresh_token)  # never
```

### Cache-Control Headers on QB Data Routes

Any route that returns QuickBooks-sourced data must include:
```
Cache-Control: no-store
```

Add this header in `server.py`'s `_send()` helper for all `/api/quickbooks/*` responses.

### HTTP Method Restriction

The local server must return `405 Method Not Allowed` for TRACE and any other HTTP method not explicitly handled. Verify `server.py` rejects unexpected methods on all routes.

### Input Sanitization — XSS

QBO Item names and descriptions are rendered in the categorization UI. All QB-sourced strings must be HTML-escaped before being inserted into the DOM. Use `textContent` (not `innerHTML`) when displaying QB data in JavaScript, or escape server-side before returning in JSON that feeds innerHTML.

### QB Data Usage Boundaries

- The app reads Items and Customers from QBO.
- The app writes Customers and Projects to QBO only.
- The app never writes to Invoices, Transactions, Payments, or any financial record.
- QB data is stored only on the local machine in `parts_db.json` and `quickbooks_config.json`. It is never transmitted to any server other than Intuit's own API endpoints.
- QB data is used only to operate the parts catalog and project management features of this app. It is never shared with third parties or used for secondary purposes.

---

## Architecture

### New Files

```
src/dtm_buildsheet/
  app/
    routes/
      quickbooks.py              ← /api/quickbooks/* route handler

    services/
      quickbooks_service.py      ← QBO API client, OAuth flow, token lifecycle,
                                    AES encryption/decryption, CSRF state management
      qb_sync_service.py         ← sync orchestration (parts, projects)

  ui/js/settings/
    quickbooks.js                ← Settings → QuickBooks tab UI

workspace/
  quickbooks_config.json         ← non-sensitive metadata + sync state (git-ignored, never synced)
                                    Credentials stored in OS keychain via msal-extensions — not in this file

src/dtm_buildsheet/app/
  adapters/quickbooks/
    credential_store.py          ← OS-keychain secret blob (msal-extensions encrypted persistence)
    oauth_client.py              ← Intuit OAuth endpoints (discovery, exchange, refresh, revoke)
```

### Existing Files Modified

| File | Change |
|------|--------|
| `domain/project_models.py` | Add `qb_customer_id`, `qb_project_id` to `ProjectRecord` |
| `app/server.py` | Register `/api/quickbooks/*` routes; add `Cache-Control: no-store` to QB responses |
| `ui/index.html` | Add QuickBooks stab to General Settings |
| `ui/js/main.js` | Wire QuickBooks tab init |
| `config/schemas.py` | Add `quickbooks_config` schema + migration |
| `parts_db.json` | Add `qb_item_id`, `qb_sku` fields per part entry |
| `pyproject.toml` | No new dependency — reuses the existing `msal-extensions` |
| `.gitignore` | Add `workspace/config/quickbooks_config.json` |

---

## Parts Catalog Sync

### QBO → Vehicle Builder Flow

```
qb_sync_service.sync_items()
  │
  ├─ GET /v3/company/{realmId}/query
  │    SELECT * FROM Item WHERE Active = true
  │    (realm_id decrypted in-memory for the request, never logged)
  │
  ├─ For each QBO Item:
  │    ├─ Look up qb_item_id in local parts_db.json
  │    │
  │    ├─ MATCHED → update name, sku, price, active status on VB part record
  │    │
  │    └─ UNMATCHED → add to "pending_qb_items" list in quickbooks_config.json
  │                    (surfaces in Settings → QuickBooks as "Uncategorized Items")
  │
  └─ For each local part with qb_item_id not returned by QBO:
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

QBO is the source of truth for `sku`, `unit_price`, and `active` status. Vehicle Builder owns everything else.

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

---

## Project / Customer Bridge

### Data Model

```python
# domain/project_models.py
@dataclass
class ProjectRecord:
    ...
    qb_customer_id: str = ""   # QBO Customer.Id for the agency
    qb_project_id: str = ""    # QBO Project Id (Customer with Job=true)
```

### QBO Structure for a Build

QBO does not have a separate Project object in the v3 API. Projects are Customers with `Job=true` and a `ParentRef`:

```
QBO Customer: Lakeville Police Department       ← matches VB agency
  └─ QBO Project: 2025 Tahoe Fleet #26-043      ← matches VB ProjectRecord
       (Job=true, ParentRef → Customer.Id)
```

Per-vehicle tracking is done via time entries tagged to the QBO Project with the unit number in the description — not a sub-project per unit. One project per build; time entries carry the unit context.

### Push Flow (VB → QBO)

Triggered by "Push to QuickBooks" on the Builds tab, or automatically on Export (configurable):

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

VB does not manage time entries — it only creates the project scaffold. Technicians log time directly in QuickBooks against the created project.

---

## API Route Map

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/quickbooks/status` | Connection status, last sync, token expiry dates |
| GET | `/api/quickbooks/auth-url` | Returns OAuth URL; generates + stores CSRF state |
| GET | `/api/quickbooks/callback` | OAuth relay target — validates state, exchanges code, stores encrypted tokens, issues 302 |
| POST | `/api/quickbooks/disconnect` | Clears encrypted tokens, sets status to disconnected |
| POST | `/api/quickbooks/sync` | Trigger manual parts sync |
| GET | `/api/quickbooks/pending-items` | List unmatched QBO Items (for categorization queue) |
| POST | `/api/quickbooks/link-item` | Link a QBO item_id to a VB part |
| POST | `/api/quickbooks/push-project` | Push VB project to QBO as Customer + Project |

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

When `connection_status` is `disconnected` or the tokens are expired/missing, the tab shows a "Connect to QuickBooks" button and hides the sync UI.

---

## Implementation Phases

### Phase 1 — OAuth + Token Management ✅ Complete

Implemented:
- `adapters/quickbooks/credential_store.py`: OS-keychain secret blob via `msal-extensions` (in-memory fallback)
- `adapters/quickbooks/oauth_client.py`: discovery document, code exchange, refresh, revoke — no token logging
- `services/quickbooks_service.py`: settings save (secret→keychain, metadata→json), OAuth URL with CSRF state, callback completion (validate state → exchange → store), `ensure_access_token` with refresh-token rotation, disconnect, status
- `routes/quickbooks.py`: `/status`, `/auth-url`, `/callback` (302-only), `/settings`, `/disconnect` — all `Cache-Control: no-store`
- Server wiring; `.gitignore` entries
- `tests/test_quickbooks_service.py` (hermetic: fake store + fake OAuth client)
- Settings UI: `ui/js/settings/quickbooks.js` + `#stab-quickbooks` card (Connect / Disconnect / status + collapsible app-registration form). OAuth return handled by `qbConsumeReturnTab()` in `main.js`.
- Hosted HTTPS relay: `relay/` — Netlify Serverless Function (`relay/netlify/functions/qb-callback.js`) + Vercel alternative (`relay/api/qb-callback.js`). See `relay/DEPLOY.md` for deployment steps.

**Done when**: Full OAuth round-trip works against a sandbox company, tokens are stored in the keychain (never on disk), CSRF state validation rejects mismatched states, callback issues 302 (not HTML), token refresh correctly saves the rotated refresh token.

### Phase 2 — Parts Sync

Built in safe, non-destructive slices:

**Slice A — read-only pull ✅ implemented**
- `adapters/quickbooks/api_client.py`: read-only QBO Data API client (`fetch_active_items`, paginated, environment-aware base URL, no body logging)
- `services/qb_sync_service.py`: `sync_items()` pulls active Items into `quickbooks_items_cache.json` (workspace root, git-ignored) and stamps `last_sync_utc`. Reads `parts_db.json` only to flag already-linked items; **never writes it**. `get_cached_items()` returns the cache with no network.
- `quickbooks.py` routes: `POST /sync`, `GET /items` (both `Cache-Control: no-store`)
- Settings UI: Parts Sync card (pull button, last-sync/counts summary, item list with linked/unlinked badges) inside the connected panel
- `tests/test_qb_sync_service.py` (hermetic; asserts parts_db is byte-for-byte untouched by a sync)

**Slice B — linking ✅ implemented**
- `qb_sync_service.link_item()` / `unlink_item()`: write `qb_item_id` / `qb_sku` / `qb_unit_price` / `qb_last_synced` onto a chosen product (or strip them). Saves through `save_config_file("parts_db.json", …)` — the normal config pipeline with SharePoint direct-mirror, never a raw write. Additive: touches one product, nothing else. Enforces a one-to-one item↔product mapping.
- `quickbooks.py` routes: `POST /link-item`, `POST /unlink-item`
- Settings UI: per-item 🔗 Link / Unlink buttons; link picker modal with a searchable product list. Linked items show the part label.
- Cache item carries `linked` + `linked_product_id` so the UI reflects state without a re-pull.
- Tests assert linking goes through `save_config_file` (not a raw write), enforces one-to-one, and that unlink strips only QB fields.

  *Deferred:* "create new VB part from this item" (pre-fill Part Manager) — link-to-existing is the shipped path.

**Slice C — reconciliation + background sync ✅ implemented**
- `qb_sync_service.reconcile_linked_parts()`: pushes QBO's `sku` / `unit_price` / active status onto LINKED parts only. Bounded — writes only QB-owned fields (`qb_sku`, `qb_unit_price`, `qb_inactive`, `qb_last_synced`); never touches the owner's categorization, never creates/deletes parts, never touches unlinked parts. Items missing from QBO's active set are flagged `qb_inactive=true` (and un-flagged if they return). Writes `parts_db.json` only when something changed, only via `save_config_file`.
- `run_full_sync()`: `sync_items()` + `reconcile_linked_parts()`. The `/sync` route and the background poller both call this.
- `start_background_sync()`: daemon thread, full sync at app start + every 30 min, guarded to run only when connected and to no-op under pytest. Wired in `server.py` `main()`.
- Skips reconciliation entirely if the cache was never synced (won't flag everything inactive on an empty cache).
- UI: sync toast reports `N parts updated, M flagged inactive`.
- Tests cover update, inactive-flag, reactivate, idempotent no-double-write, unlinked-untouched, never-synced-skip, and full-sync orchestration.

**Done when**: ✅ New QBO Items surface in the list, linking persists, linked parts auto-update from QBO, deactivated QBO Items get flagged `qb_inactive`.

  *Deferred:* "create new VB part from this item" (pre-fill Part Manager) — link-to-existing is the shipped path.

### Phase 3 — Project Bridge

- `qb_sync_service.push_project()`: Customer lookup/create, Project create, write-back IDs
- `ProjectRecord` additions
- `quickbooks.py` route: `/push-project`
- Builds tab: "Push to QuickBooks" button per project

**Done when**: Pushing creates the correct QBO Customer + Project, IDs written back to project record, re-pushing is idempotent.

### Phase 4 — Questionnaire Submission

- Run full connect / disconnect / reconnect test cycle against sandbox
- Confirm all Phase 1 security controls are in place
- Submit the App Assessment Questionnaire using `docs/QUICKBOOKS_QUESTIONNAIRE.md` as the answer guide

---

## Known Constraints and Gotchas

- **Production redirect URI must be HTTPS on a real domain**: `localhost` is rejected by Intuit for Production keys. The hosted relay is required.
- **Refresh token rotation is mandatory**: Save the newly issued refresh token (encrypted) on every refresh call. One missed rotation permanently breaks the connection.
- **Credentials live in OS keychain, not in files**: `quickbooks_config.json` contains only non-sensitive metadata. All credential values (`access_token`, `refresh_token`, `realm_id`, `client_secret`) are stored as an encrypted blob via `msal-extensions` (same mechanism as the M365 token cache). This satisfies Intuit's AES encryption requirement — the OS keychain handles encryption and key management natively.
- **Callback must 302 redirect**: Never return HTML that contains the authorization code or any token. Issue a server-side 302 to a clean URL after saving tokens.
- **No QB data in logs**: Item names, prices, customer names, realm ID, and all token values must never appear in any log file.
- **5-year hard expiry**: Set a calendar reminder. After 5 years, a one-time browser re-authorization is required.
- **QBO Projects = Customers with Job flag**: There is no separate Project object in the QBO v3 API.
- **`quickbooks_key.bin` loss = loss of connection**: If the key file is deleted, stored tokens cannot be decrypted. The only recovery is to re-run the OAuth setup flow. Back up the key to a password manager.
- **Inactive QBO items are not deleted in VB**: Old builds may reference discontinued parts. `qb_inactive: true` flags the part without deleting the record.
- **This app accesses one realm only**: The Production key is connected to a single QBO company. It is not a multi-tenant app. This must be stated accurately in the questionnaire.
