# QuickBooks Online Integration

**Single entry point for all QuickBooks work.** Merges the former
`QUICKBOOKS_STATUS.md` (handoff/status), `QUICKBOOKS_INTEGRATION.md` (design), and
`QUICKBOOKS_QUESTIONNAIRE.md` (Intuit App Assessment answers).

**Branch**: `claude/quickbooks-integration-design-rcgula` (all QB work; not yet merged to `main`).
**Related**: [EXTERNAL_CONNECTION_SECURITY.md](EXTERNAL_CONNECTION_SECURITY.md) (security standard),
[PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md) (the parts catalog QB feeds), `relay/DEPLOY.md` (relay deploy).

> **Why QB matters strategically:** the QBO Item catalog is the *foundation* of the parts
> system, not a side integration. `parts_db.json` now references parts at SKU granularity
> (real vendor part numbers + QB pricing). See [ROADMAP.md](ROADMAP.md) §"QB-as-foundation".

---

## 1. TL;DR — where we are

An **internal, single-company** integration for the DTM Vehicle Builder desktop app. It does:
(1) one-time OAuth connect, (2) sync the parts catalog from QBO Items, (3) sync QBO Customers
into the app's Agencies **and** mirror agencies back up, (4) a per-vehicle sub-customer/job
bridge, and (5) draft **non-posting Estimates** per vehicle from the chosen parts.

| Phase | What | Status |
|-------|------|--------|
| **1 — OAuth + tokens** | Connect/disconnect/reconnect, keychain token storage, CSRF, 302 callback, hosted relay | ✅ Built. Connect/disconnect/reconnect **tested in sandbox by the owner.** |
| **2 — Parts sync** | Pull Items → cache (A), link items to parts (B), reconcile linked parts + 30-min background sync (C) | ✅ Built. Pull (A) **tested in sandbox**. B/C built + unit-tested. |
| **3 — Customers ↔ Agencies + vehicle bridge** | Down-sync (Slice 1), agency→QB up-sync (Slice 2), per-vehicle job bridge (Slice 3) | ✅ All three built. Slice 1 sandbox-tested; Slices 2 & 3 built + unit-tested, not yet exercised live. |
| **Estimates** | Non-posting Estimate per vehicle; validate/create/batch + Builds-tab UI | ✅ Backend + UI built. Blocks unless every part is QB-linked. Not yet exercised live. |
| **4 — Questionnaire submission** | Submit Intuit App Assessment for Production keys | ⛔ Not done. Requires sandbox test cycle confirmation + relay deploy (§5–6). |

**Currently runs against the SANDBOX company using Development keys.** No Production keys, no
relay deployed, questionnaire not submitted. Nothing is live against a real QBO company yet.

**Write boundary**: the app writes **Customers, sub-customers/jobs, and non-posting Estimates** —
never Invoices, Payments, or any posting transaction. (A sandbox-only Item-seeding tool exists,
hard-gated to `environment == "sandbox"`.)

**Parts-import effort — FULL import done (2026-07-01).** The whole synced QBO item cache is now in
`parts_db`. `tools/qb_import_all.py` bulk-created **+670 products** (262→932) for every item not
already present — one product per SKU, each carrying its real QB linkage (id / sku / price) + the QB
description as sales description. Manufacturer inferred from the description; 136 un-inferrable items
landed under a holding **"Unassigned (QB Import)"** manufacturer for triage. New products have **no
part-type home** (fits_part_types=[]) → they show as "Needs: home" in the SKU grid, filterable via the
new **"— No part-type —"** tree filter. These items ARE in QB, so they're QB-linked (not pending-QB).
*(Earlier incremental path — Pass 1 manufacturers, Pass 2 per-manufacturer proposer
`tools/qb_inventory_import_pass2.py`, Gamber pilot — is superseded for bulk visibility; the
pending-QB mechanism remains for parts not yet in QB.)* Next: curate the queue (assign part-types,
merge SKU variants, reassign the holding bucket) via the SKU grid.

---

## 2. What's built and where it lives

### Phase 1 — OAuth + token management
- `app/adapters/quickbooks/credential_store.py` — `QuickBooksCredentialStore`: OS-keychain secret
  blob via `msal-extensions` (in-memory fallback). Stores `client_secret`, `access_token`,
  `refresh_token`, `realm_id`. **Never plaintext on disk.**
- `app/adapters/quickbooks/oauth_client.py` — OIDC discovery (prod + sandbox), code exchange,
  refresh, revoke. Process-wide discovery cache, 10s timeout. Never logs token values.
- `app/services/quickbooks_service.py` — orchestration: `save_settings`, `generate_auth_url`
  (CSRF state), `validate_state` (single-use, constant-time), `complete_authorization`,
  `ensure_access_token` (refresh + **refresh-token rotation**), `disconnect`, `get_status`,
  `get_realm_id`, `set_last_sync`. `quickbooks_config.json` (non-secret metadata) lives in
  workspace root, managed **directly** (NOT via `config_service`/SharePoint mirror).
- `app/routes/quickbooks.py` — all routes; every response sets `Cache-Control: no-store`;
  callback is **302-only** (never echoes code/token).
- `ui/index.html` + `ui/js/settings/quickbooks.js` — Settings → General → QuickBooks tab.
- `relay/` — hosted HTTPS OAuth relay (Netlify primary, Vercel alt). See `relay/DEPLOY.md`.
  **Not yet deployed.**
- Tests: `tests/test_quickbooks_service.py` (13, hermetic).

### Phase 2 — Parts sync
- `app/adapters/quickbooks/api_client.py` — `QuickBooksApiClient` (read-only Data API):
  `fetch_active_items()`, `fetch_active_customers()`, normalizers. Environment-aware base URL.
- `app/services/qb_sync_service.py`:
  - `sync_items()` — pull active Items → `quickbooks_items_cache.json` (git-ignored, workspace
    root). **Reads** parts_db only to flag linked items; never writes it (Slice A).
  - `link_item()` / `unlink_item()` — attach/detach a QB item to a VB product via
    `save_config_file("parts_db.json", …)` (proper mirror path). Additive, one-to-one (Slice B).
  - `reconcile_linked_parts()` — push QBO `sku`/`unit_price`/active status onto **linked** parts
    only; flag missing items `qb_inactive` (never delete); writes only on change. Also reconciles
    **pending-QB** parts (see [PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md)) (Slice C).
  - `run_full_sync()` = pull + reconcile. `start_background_sync()` = daemon, app-start + every
    30 min, only when connected, no-ops under pytest. Wired in `server.py:main()`.
- UI: Parts Sync card + link-picker modal in `quickbooks.js` / `index.html`.
- Tests: `tests/test_qb_sync_service.py` (22).

### Phase 3 — Customers ↔ Agencies + vehicle bridge
- **Slice 1 (down-sync):** `AgencyRecord.qb_customer_id`; `agency_service.preview_qb_customer_import()`
  + `upsert_agencies_from_qb()`. Match precedence: `qb_customer_id` → normalized name → create.
  Linking fills only EMPTY contact fields; never overwrites the agency name. Routes
  `GET /customers/preview`, `POST /customers/import`. Tests: `tests/test_qb_customer_sync.py` (12).
- **Slice 2 (up-sync):** `api_client.create_customer()` / `update_customer()` (sparse) /
  `read_customer()` / `find_customer_by_display_name()`. `agency_service.set_qb_customer_id()`
  writes the link back WITHOUT `handle_save_agency` (can't re-trigger a push).
  `qb_sync_service.push_agency()` + `push_agency_in_background()`. Tests: `tests/test_qb_agency_push.py` (12).
- **Slice 3 (per-vehicle job bridge):** `IndividualUnit` gains `qb_job_id` / `qb_estimate_id` /
  `qb_invoice_id`. `api_client.create_job(parent_id, display_name)` (Customer with `Job=true` +
  `ParentRef`). `qb_sync_service.push_vehicle_job(project_id, individual_id)` — ensures the agency
  Customer exists, creates/reuses a uniquely-named job, writes `qb_job_id` back. Idempotent.

**Critical QBO fact:** the v3 API cannot create Projects (`Customer.IsProject` is read-only).
We use **sub-customers/jobs** as the durable per-vehicle container. (Intuit has heavily restricted
job→Project conversion; treat the sub-customer as durable, not a stepping stone.)

### Estimates
- `api_client.create_estimate()` + `fetch_income_accounts()` + `create_item()` (last two
  sandbox-seeder only).
- `qb_estimate_service.py`: `resolve_build_lines()` (part→QB-item by part number),
  `validate_estimate()` (offline dry-run), `create_estimate()` (BLOCKS unless every part is
  linked/active/priced; ensures the job; writes `qb_estimate_id` back), `create_estimates_batch()`.
  Pending-QB parts post as a `DescriptionOnly` line (flagged, non-blocking).
- UI: per-vehicle **📋 QB Estimate** + footer **Create QB Estimates** on the Builds tab
  (`detail_builds.js`, `#qb-est-modal`). Tests: `tests/test_qb_estimate_service.py` (13).

### Full route list (`/api/quickbooks/*`)
`GET status` · `GET auth-url` · `GET callback` (302) · `GET items` · `GET customers/preview` ·
`POST settings` · `POST disconnect` · `POST sync` · `POST link-item` · `POST unlink-item` ·
`POST customers/import` · `POST push-vehicle-job` · `POST estimates/validate` ·
`POST estimates/create` · `POST estimates/create-batch`

**Test totals**: full suite ~1593 pass, 1 skipped. QB-specific: service (13), sync (22),
customer-sync (12), agency-push (12), estimate (13), seed-sandbox (5).

---

## 3. Architecture & design

### OAuth redirect — hosted relay required for Production
Intuit Production keys require an **HTTPS redirect URI on a real domain**; `http://localhost` is
only accepted for sandbox/development. The relay is a dumb serverless 302 pass-through (Netlify
function `relay/netlify/functions/qb-callback.js`, Vercel alt `relay/api/qb-callback.js`):

```
QBO auth page → https://<domain>/.netlify/functions/qb-callback?code=...&state=...&realmId=...
             → HTTP 302 → http://localhost:7655/api/quickbooks/callback?... → local app captures tokens
```

The relay never reads, stores, or logs the code. The code is short-lived and useless without the
client secret, which never leaves the local machine. For sandbox, register
`http://localhost:7655/api/quickbooks/callback` under the Development tab.

### Token storage — OS keychain via `msal-extensions`
Reuses the exact mechanism the M365/SharePoint integration uses (`adapters/cloud/msal_client.py`):
`msal-extensions` encrypted persistence backed by the OS-native credential store. **Zero new
dependencies.** All sensitive values (`access_token`, `refresh_token`, `realm_id`, `client_secret`)
live as one encrypted blob; plaintext never touches disk. Fallback to a process-lifetime in-memory
map when the keychain backend is unavailable (losing it on restart forces re-auth — correct secure
behavior). Satisfies Intuit's AES-at-rest requirement (OS manages encryption + key natively).

| Platform | Storage |
|----------|---------|
| macOS | Keychain |
| Windows | Windows Credential Locker (DPAPI) |
| Linux | libsecret / Secret Service (in-memory fallback if absent) |

### Token lifecycle
| Token | Lifetime | Behavior |
|-------|----------|----------|
| `access_token` | 1 hour | Refreshed automatically within 5 min of expiry |
| `refresh_token` | 100 days inactivity | **Rotates on every use** — new token must be saved each refresh |
| Hard maximum | 5 years | One-time re-authorization required after 5 years |

Missing one rotation permanently invalidates the connection.

### Parts catalog sync (QBO → VB)
QBO is the source of truth for `sku`, `unit_price`, and `active` status; Vehicle Builder owns all
categorization (placement rules, build types, vehicle compatibility). Each linked `part_number`
entry gains `qb_item_id`, `qb_sku`, `qb_unit_price`, `qb_inactive`, `qb_last_synced`. Inactive QBO
items are flagged, never deleted (old builds may reference discontinued parts). Triggers: app start
(background), 30-min poll, manual "Sync Now".

### Customer/estimate bridge (VB → QBO)
Agency = QBO Customer; per-vehicle build = sub-customer/job (Customer `Job=true` + `ParentRef`);
estimate = non-posting Estimate attached to the job. Estimate→Invoice conversion is intentionally
an explicit user step in the QBO UI (a guarded in-app convert is a future extension).

### `quickbooks_config.json` (non-secret metadata only)
Plain JSON in workspace root, git-ignored, never written to the config-store or SharePoint mirror.
Holds `client_id` (not a secret), `environment`, `redirect_uri`, expiry timestamps, `last_sync_utc`,
`connection_status`. No credential values.

---

## 4. Security & architecture invariants (must not regress)

These are enforced today (see [EXTERNAL_CONNECTION_SECURITY.md](EXTERNAL_CONNECTION_SECURITY.md) and
GOTCHAS):

- **Secrets only in the OS keychain.** `client_secret`, `access_token`, `refresh_token`, `realm_id`
  via `credential_store.py`. Never in any file, never logged. `quickbooks_config.json` = non-secret
  metadata only, managed directly by `quickbooks_service` (NOT `config_service`; NOT in
  `REQUIRED_CONFIG_FILES` or any cloud-mirror set).
- **OAuth callback is 302-only.** Never echo the code/token in HTML (Referer-leak prevention).
- **`Cache-Control: no-store`** on every `/api/quickbooks/*` response.
- **Refresh-token rotation**: save the NEW refresh token on every refresh, or the connection dies.
- **No QB data in logs**: only `intuit_tid`, HTTP status, timestamps.
- **QB data is read-only for the catalog except linked parts**: `sync_items` never writes parts_db;
  only explicit `link_item`/`unlink_item`/`reconcile_linked_parts` touch it, and reconcile only
  writes QB-owned fields on already-linked products.
- **Customer import never clobbers user data**: fills only empty contact fields; never overwrites
  agency names.
- **Bulk settings mirror re-reads from disk + skips deleted files**: do NOT revert
  `save_settings_to_cloud_batch_in_background` to uploading a captured snapshot, or deletions resurrect.
- **List action buttons use data-attributes + delegation, never inline `onclick` with interpolated
  names**: `esc()` does not escape quotes; apostrophes in names break inline handlers.
- **`.gitignore`** covers `quickbooks_config.json` and `quickbooks_items_cache.json`.
- **Estimates are non-posting; never create posting transactions.** The app may write Customers,
  sub-customer jobs, and Estimates only — never Invoices/Payments/journal entries.
- **Item creation is sandbox-only.** `tools/qb_seed_sandbox.py` HARD-REFUSES unless
  `get_status().environment == "sandbox"`. Never create Items in a production realm.
- **Estimate write-back can't re-trigger pushes.** `agency_service.set_qb_customer_id` and the unit
  `qb_*_id` write-backs persist directly, NOT through `handle_save_agency`.
- **Tool writes to `parts_db.json` must use `--push-to-cloud`.** A direct `Path.write_text` (or the
  tool without the flag) is reverted by the next 60s SharePoint sync.

### Bugs found & fixed (don't regress)
1. OAuth discovery re-fetched every call → cached process-wide; timeout 30s→10s.
2. Bulk-import mirror race resurrected deleted agencies → `save_settings_to_cloud_batch_in_background`
   re-reads at upload time and skips files deleted in the meantime.
3. Silent cloud-delete failures (429 swallowed) → retry with backoff; surfaces a `cloud_warning`.
4. Undeletable records whose names contain apostrophes → switched to `data-*` attributes + delegated
   click listener in both `agencies.js` and `sales_reps.js`. Tests: `tests/test_settings_mirror.py` (5).

---

## 5. Sandbox test cycle Intuit requires before submitting

Intuit's most common rejection is "connect/disconnect/reconnect not tested." Do these against the
**sandbox** company (Development keys, `environment=sandbox`, redirect
`http://localhost:7655/api/quickbooks/callback`):

1. **Connect** — full OAuth round-trip; status badge → green; token expiry dates populate. ✅ done.
2. **Disconnect** — tokens cleared; badge → not connected; subsequent API calls rejected. ✅ done.
3. **Reconnect** — full OAuth again from disconnected state; new tokens stored. ✅ done.
4. **CSRF** — a mismatched `state` is rejected (unit-tested; demo by tampering the callback URL).
5. **Refresh-token rotation** — the NEW refresh token is saved after a refresh (unit-tested).
6. **Parts pull** — `POST /sync` returns sandbox items. ✅ done.
7. **Customer import** — `POST /customers/import` creates agencies. ✅ done.
8. **Log review** — confirm no tokens/realm IDs/QB data in the app log (only `intuit_tid`, status, timestamps).

### How to run in sandbox
1. `git checkout claude/quickbooks-integration-design-rcgula && git pull`
2. Launch the dev app from the repo (`python -m dtm_buildsheet`), not the installed bundle.
3. Intuit dashboard → **Development** tab → register redirect `http://localhost:7655/api/quickbooks/callback`.
4. App → Settings → General → QuickBooks → App registration: Development Client ID/Secret,
   **Environment = sandbox**, redirect = the localhost URL → Save.
5. Connect → sign in with the Intuit **developer account** → authorize the sandbox company.
6. Pull items, link a couple to parts, pull customers → agencies.

For Production later: deploy the relay (`relay/DEPLOY.md`), register the relay HTTPS URL under the
**Production** tab, submit the questionnaire, then switch the app to `environment=production` with
Production keys + the relay redirect URI.

---

## 6. What's left before Production go-live (Phase 4)

- **Deploy the hosted relay** (`relay/DEPLOY.md`) and register its HTTPS URL as the Production
  redirect URI in the Intuit dashboard.
- **Run the sandbox test cycle** (§5) and **submit the questionnaire** (§7).
- Obtain Production Client ID/Secret after approval; enter them with `environment=production`.

**Deferred niceties:** Estimate→Invoice conversion (explicit user step today); "create new VB part
from this QB item" (link-to-existing is the shipped path); customer down-sync on the 30-min poll
(manual button today, owner chose reviewed-first).

> **Go-live is externally gated** (relay + questionnaire + Intuit approval). It is *not* advanced by
> the parts-import grind and should not block it. Run it as its own track when ready.

---

## 7. Appendix — App Assessment Questionnaire (prepared answers)

Reference when completing the questionnaire in the Intuit Developer Dashboard (organized by its tab
order). Complete the §5 sandbox test cycle first — Intuit rejects submissions where testing isn't done.

**Info to have ready:** App name `DTM Vehicle Builder`; category Accounting/Internal business tool;
country US; **1 realm** (our company only); Launch/Disconnect URL `https://<domain>`; Production
redirect `https://<domain>/.netlify/functions/qb-callback`; dev redirect
`http://localhost:7655/api/quickbooks/callback`; scope `com.intuit.quickbooks.accounting`; hosting
US (runs locally on user machines); no fixed IP (desktop app).

**§1 How your app operates:** internal desktop app generating vehicle build sheets for law
enforcement / emergency-vehicle upfits; QB integration syncs the parts catalog (Items) and creates
Customer/sub-customer/Estimate records; **internal use only**; **1 company**; not public/app-store.
*(If the live form asks "integrate with other platforms," answer YES — Microsoft SharePoint + GitHub.
The merged-doc text above said "No"; the owner corrected this to YES.)*

**§2 Data management:** QB data stored **locally only** (parts cache JSON on the user's US
workstation); never transmitted to any server other than Intuit's API; not shared with third
parties; used only to operate the app; retained locally; user can disconnect (clears tokens).

**§3 API usage:** reads **Items + Customers**; writes **Customers, sub-customer jobs, and
non-posting Estimates**; **never** writes Invoices/Payments/journal entries or any posting
transaction; minimum scope `com.intuit.quickbooks.accounting`; handles HTTP errors with
user-visible messages; logs `intuit_tid` only.

**§4 Authorization:** OAuth 2.0 auth-code; one-time browser authorization; tokens in OS keychain via
`msal-extensions`; **refresh-token rotation** on every refresh (new token re-encrypted + saved
atomically); **CSRF** via `state` (`secrets.token_urlsafe(32)` + `compare_digest`, rejected on
mismatch with 400); connect/disconnect/reconnect tested in sandbox.

**§5 Error handling:** graceful plain-language API error messages (no raw responses/stack traces);
captures `intuit_tid` from every response header into a structured local log with operation name +
status + timestamp; no secrets in logs.

**§6 Legal:** no complaints/lawsuits/investigations; reviewed obligations as an internal tool; will
comply with Intuit Developer ToS + security policies; sanctions/export compliant; QB data used only
for our own company, never shared/sold/secondary-purpose.

**§7 Security:** OAuth tokens AES-encrypted at rest in the OS keychain (OS-managed, hardware security
layer); HTTPS for all external traffic (relay for redirect; local UI on localhost exempt); logger
excludes credentials/tokens/realm IDs/QB data; CSRF via `state`; no third-party access; single-user
desktop app, OS-level access control; assessed for **XSS** (`textContent` not `innerHTML`), **CSRF**
(`state`), **SQLi** (n/a — no SQL DB), **XML injection** (PPTX layer input sanitized), **HTTP TRACE**
(rejected with 405).

**Q2 note** (owner): the "how often does your app call the API / store data" dropdown — honest answer
is roughly **"More than once a day"** (30-min background poll when connected).

### Submission checklist
- [ ] Phase 1 complete and tested against sandbox; connect/disconnect/reconnect all pass
- [ ] Token storage confirmed in OS keychain (Keychain / DPAPI) — NOT a plaintext file
- [ ] OAuth callback issues HTTP 302 (not HTML); CSRF state mismatch rejected; refresh-token rotation confirmed
- [ ] App logs reviewed — no tokens/realm IDs/QB data (only `intuit_tid`, status, timestamps)
- [ ] `Cache-Control: no-store` on all `/api/quickbooks/*` routes; HTTP TRACE rejected
- [ ] Production redirect URI registered; hosted relay deployed and tested end-to-end (`relay/DEPLOY.md`)
- [ ] `quickbooks_config.json` + `quickbooks_items_cache.json` in `.gitignore`, absent from SharePoint mirror

> **Implementation note:** earlier drafts referenced a manual AES key file (`quickbooks_key.bin`).
> That was replaced before implementation with the OS-native credential store via `msal-extensions`.
> All secret values live ONLY in the keychain; `quickbooks_config.json` is non-secret metadata.
