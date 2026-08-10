# QuickBooks Online Integration

**Single entry point for all QuickBooks work.** Merges the former
`QUICKBOOKS_STATUS.md` (handoff/status), `QUICKBOOKS_INTEGRATION.md` (design), and
`QUICKBOOKS_QUESTIONNAIRE.md` (Intuit App Assessment answers).

**Code location**: the QB foundation is in `main`; public QB controls remain hidden. The production
catalog preview is a separate, read-only owner workflow — not a switch that enables routine sync.
**Related**: [EXTERNAL_CONNECTION_SECURITY.md](EXTERNAL_CONNECTION_SECURITY.md) (security standard),
[PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md) (the parts catalog QB feeds), `relay/DEPLOY.md` (relay deploy).

> **Why QB matters strategically:** the QBO Item catalog is the *foundation* of the parts
> system, not a side integration. `parts_db.json` now references parts at SKU granularity
> (real vendor part numbers + QB pricing). See [ROADMAP.md](ROADMAP.md) §"QB-as-foundation".

---

## 1. TL;DR — where we are

An **internal, single-company** integration for the DTM Vehicle Builder desktop app. It does:
(1) one-time OAuth connect, (2) sync the parts catalog from QBO Items, (3) sync QBO Customers
into the app's Agencies **and** mirror agencies back up, and (4) draft **non-posting Estimates**
per vehicle from the chosen parts under the agency's top-level Customer and its linked true QBO
Project. Older estimates may still point at legacy vehicle sub-customers/jobs.

| Phase | What | Status |
|-------|------|--------|
| **1 — OAuth + tokens** | Connect/disconnect/reconnect, keychain token storage, CSRF, 302 callback, hosted relay | ✅ Built. Connect/disconnect/reconnect **tested in sandbox by the owner.** |
| **2 — Parts sync** | Pull Items → cache (A), link items to parts (B), reconcile linked parts + 30-min background sync (C) | ✅ Built. Pull (A) **tested in sandbox**. B/C built + unit-tested. |
| **3 — Customers ↔ Agencies + estimate customer flow** | Down-sync, agency→QB up-sync, top-level customer resolution, legacy job bridge | ✅ Customer sync and estimate flow built + unit-tested. New estimates do not create jobs. |
| **Estimates** | Non-posting Estimate per vehicle; validate/create/batch + Builds-tab UI | ✅ Backend + UI built. Blocks unless every part is QB-linked. Not yet exercised live. |
| **Production catalog preview** | Snapshot-pinned production Item pull, Name/SKU column comparison, intentional-exclusion carry-forward, exact-match plan | ✅ Built locally. Production credentials, relay deployment, and the first read-only pull remain pending. It cannot reconcile or change `parts_db`. |
| **4 — Questionnaire submission** | Submit Intuit App Assessment for Production keys | ⛔ Not done. Requires sandbox test cycle confirmation + relay deploy (§5–6). |

**The standard QB connection still runs against the SANDBOX company using Development keys.** No
routine production sync is configured. The separate production-preview profile has its own local
metadata, encrypted keychain store, and Item cache; it is not connected until the owner supplies
Production credentials and a deployed HTTPS relay.

**Write boundary**: the app writes **Customers and non-posting Estimates** —
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
- `reconcile_linked_parts()` — push QBO `sku`/`unit_price`/sales description/active status onto **linked** parts
    only; flag missing items `qb_inactive` (never delete); writes only on change. Also reconciles
    **pending-QB** parts (see [PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md)) (Slice C).
  - `run_full_sync()` = pull + reconcile. `start_background_sync()` = daemon, app-start + every
    30 min, only when connected, no-ops under pytest. Wired in `server.py:main()`.
- UI: Parts Sync card + link-picker modal in `quickbooks.js` / `index.html`.
- Tests: `tests/test_qb_sync_service.py` (22).

### Production catalog preview — read-only migration gate

The production company may organize Items differently from sandbox. Therefore production does not
use `run_full_sync()` or the 30-minute poller. The preview is deliberately isolated:

- `tools/qb_create_migration_snapshot.py` creates an immutable local baseline containing the
  installed `parts_db.json` and, when available, the normalized sandbox Items cache. It never reads
  or copies connection metadata, OAuth tokens, or keychain data.
- `quickbooks_production_preview_config.json` and
  `quickbooks_production_preview_credentials.bin` are separate from the standard sandbox profile.
  The production preview accepts Production credentials only; its redirect URI must be HTTPS.
- `qb_production_preview_service.py` writes only a separate production Items cache, report, and
  prepared plan. It has no `save_config_file()` call and cannot update `parts_db.json`.
- The report compares the Builder `part_number` against **both** QBO `Name` and QBO `Sku`, reports
  the exact-match totals for each column, and lets the owner select the correct field once. The
  sandbox baseline currently demonstrates why this matters: vendor identifiers there are held in
  QBO `Name`, while `Sku` is often blank.
- QBO Items present in the sandbox cache but absent from the baseline Builder catalog are carried
  forward as **intentional exclusions** when their normalized Name or SKU appears in production.
  They remain outside the Builder catalog; unrecognized production-only Items still block the
  eventual mapping approval and remain untouched in the exact-match plan.
- Once the owner selects the proven identifier field, the app may prepare one exact-match plan for
  every unambiguous match. Ambiguous, missing, unexpected, or blank-key rows stay out of that plan
  for later review. **Prepared is not applied:** a later explicit owner-approved apply step is
  required before any catalog link changes.

The owner-facing entry is **Advanced Settings → QB Catalog Preview**. It appears only on a machine
that already has a valid local migration snapshot; public QB sales/estimate controls remain hidden.

### Phase 3 — Customers ↔ Agencies + estimate customer flow
- **Slice 1 (down-sync):** `AgencyRecord.qb_customer_id`; `agency_service.preview_qb_customer_import()`
  + `upsert_agencies_from_qb()`. Match precedence: `qb_customer_id` → normalized name → create.
  The pull stores the full operational customer profile (contact/title, phones, email, website,
  notes, taxable flag, and billing/shipping addresses). Linking fills only EMPTY local fields;
  it never overwrites the agency name or a populated app field. Routes
  `GET /customers/preview`, `POST /customers/import`. Tests: `tests/test_qb_customer_sync.py` (14).
- **Slice 2 (up-sync):** `api_client.create_customer()` / `update_customer()` (sparse) /
  `read_customer()` / `find_customer_by_display_name()`. `agency_service.set_qb_customer_id()`
  writes the link back WITHOUT `handle_save_agency` (can't re-trigger a push). A new app agency
  first reuses an exact top-level QB Customer name match to avoid a duplicate; otherwise it creates
  only a Customer record. No Customer save can create a financial transaction.
  `qb_sync_service.push_agency()` + `push_agency_in_background()`. Tests: `tests/test_qb_agency_push.py` (13).
- **Legacy Slice 3 (per-vehicle job bridge):** `IndividualUnit.qb_job_id` and
  `push_vehicle_job()` remain only so older records can be read and older estimates are not
  orphaned. New estimate creation does not call this path.

**Current estimate customer rule:** an estimate always uses the agency's top-level `CustomerRef`
and the vehicle's true QBO `ProjectRef`. The free-tier workflow creates the Project manually in
QuickBooks, then stores its Project ID (or a Project page URL) on the individual vehicle through `POST /projects/bind`;
the app does not create a sub-customer. Project names are stable and self-identifying:
`Agency | Build {build year} | Unit {number}`. A unit number is required before binding a Project.
The app requires agency name, contact name/email/phone, and billing street/city/state/postal code
before it can create an estimate. If the agency is not linked, it first reuses an exact top-level
Customer name match; otherwise it asks the user to confirm the complete customer profile before
creating one. A confirmed profile update is a sparse Customer-only write. The vehicle's
stable project name is written into `CustomerMemo` and `PrivateNote`, and persisted with
`IndividualUnit.qb_project_id`; no new sub-customer is created.

**True QBO Projects are a separate capability:** Intuit documents a Project API, but it requires
the company's Projects feature plus a premium/restricted Project Management scope. The current
desktop OAuth scope is the regular accounting scope, so the app does not create or list Projects
programmatically. The standard Estimate REST request does accept a known `ProjectRef`, which is
why manually created Projects can be linked at no additional API-tier cost. The premium API is
only needed to automate Project creation/listing. See Intuit's
[Project API getting started](https://developer.intuit.com/app/developer/qbo/docs/workflows/manage-projects/get-started)
and [Project API use cases](https://developer.intuit.com/app/developer/qbo/docs/workflows/manage-projects/use-cases).

### Estimates
- `api_client.create_estimate()` + `fetch_income_accounts()` + `create_item()` (last two
  sandbox-seeder only).
- `qb_estimate_service.py`: `resolve_build_lines()` (part→QB-item by part number),
  `validate_estimate()` (offline dry-run), `bind_project()` (local link to a manually created QBO
  Project), `create_estimate()` (BLOCKS unless every part is
  linked/active/priced; uses QB sales descriptions, consolidates duplicate SKUs, sorts by brand,
  resolves the top-level customer, requires a true QBO Project, writes `ProjectRef`, and writes
  `qb_estimate_id` back), `create_estimates_batch()`.
  The standard Accounting-only connection deliberately does not write
  sales-form custom fields: modern QuickBooks fields require their paid Custom
  Fields API to resolve the company-specific field IDs. This keeps a custom
  form mismatch from blocking the non-posting estimate create. The optional
  phone, vehicle, sales-ID, and unit header fields therefore remain managed in
  QuickBooks unless that paid scope is enabled later.
  The create dialog reports when QB customer price levels are enabled. The accounting API does
  not expose custom price-level rates, so the estimate uses the synced sandbox item rates until
  the user reviews/adjusts them in QuickBooks. See Intuit's
  [platform release notes](https://developer.intuit.com/app/developer/qbo/docs/release-notes/platform-release-notes).
  Pending-QB parts post as a `DescriptionOnly` line (flagged, non-blocking).
- UI: per-vehicle **📋 QB Estimate** + footer **Prepare QB Estimates** on the Builds tab.
  The batch screen first checks every configured vehicle, lets the user set up missing Projects,
  and creates only the ready estimates after an explicit confirmation.
  (`detail_builds.js`, `#qb-est-modal`). Tests: `tests/test_qb_estimate_service.py` (25).

### Full route list (`/api/quickbooks/*`)
`GET status` · `GET auth-url` · `GET callback` (302) · `GET items` · `GET pricing-status` · `GET customers/preview` ·
`POST settings` · `POST disconnect` · `POST sync` · `POST link-item` · `POST unlink-item` ·
`POST customers/import` · `POST push-vehicle-job` (legacy) · `POST estimates/validate` ·
`POST projects/bind` ·
`POST estimates/customer-preview` · `POST estimates/create` · `POST estimates/create-batch`

**Test totals**: full suite ~1593 pass, 1 skipped. QB-specific: service (13), sync (22),
customer-sync (14), agency-push (13), estimate (25), seed-sandbox (5).

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

**Production exception:** those triggers belong only to the standard connection. They must never
use the production-preview profile. The preview reads active production Items into its own local
cache and produces a mapping report; it has no reconciliation, background polling, customer import,
or estimate capability.

### Future: reviewed QBO catalog-change queue (owner decision)

The recurring catalog sync must become **reviewed-first** before it automatically creates or
materially changes Vehicle Builder catalog records. This is intentionally documented now, but is
not part of the current go-live scope.

**Current behavior, until this is built:** reconciliation automatically updates the QB-owned fields
(`sku`, price, sales description, active flag) of an already linked SKU. A QBO item that is added
later is only present in the local item cache; it is not automatically made into a new Builder
product. A QBO item that disappears from the active-item pull is retained in Builder and marked
inactive; it is never physically deleted. A pre-added `qb_pending` SKU is the one exception: it can
link itself automatically when its matching QBO item becomes available.

**Required future behavior:** every sync detects, records, and presents these event types: **new
item**, **changed linked item**, **newly inactive/missing item**, and **pending item matched**. A
durable, team-visible `quickbooks_catalog_changes.json` record (not the disposable item cache and
not an application log) must retain the QBO item ID/SKU, detection time, before/after field diff,
raw QBO snapshot, proposal source, review status, reviewer, decision time, and any edited metadata.
The QuickBooks settings area should show a count and a review screen with **Approve**, **Approve with
edits**, and **Dismiss/keep current metadata** actions. Resolved rows remain in the history so the
team has an audit trail.

Approval is the only path that applies a proposal to `parts_db.json`; it must use the normal
`save_config_file(...)`/shared-settings proposal path. The sync remains read-only toward QuickBooks:
the app must never create, edit, or delete a production QBO Item. A missing/inactive item should
offer **mark inactive** only — never delete an app SKU that historical builds may reference.

**Whelen auto-enrichment for a new QBO item:** when the item can be matched exactly by normalized
SKU against `docs/reference/WHELEN_PRICE_LIST_PL26.md`, create a *proposed* Builder record and
pre-fill only high-confidence metadata: manufacturer, model/friendly sales description, known light
classification, color fields, and lens where the reference data supports them. Leave a part-type
home, placement, render asset, and any uncertain field for the reviewer. The log must identify the
reference source and each inferred field; reviewer edits always win. An unmatched or low-confidence
Whelen SKU still becomes a review proposal, but with no guessed metadata.

### Customer/estimate bridge (VB → QBO)
Agency = QBO Customer; per-vehicle build = a true QBO Project under that Customer (manually
created and locally bound until premium Project API access is enabled); estimate = non-posting
Estimate attached to both the agency Customer and Project. Estimate→Invoice conversion is
intentionally an explicit user step in the QBO UI (a guarded in-app convert is a future extension).

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
- **Customer import never clobbers user data**: fills only empty local customer-profile fields;
  never overwrites agency names or populated app values.
- **Bulk settings mirror re-reads from disk + skips deleted files**: do NOT revert
  `save_settings_to_cloud_batch_in_background` to uploading a captured snapshot, or deletions resurrect.
- **List action buttons use data-attributes + delegation, never inline `onclick` with interpolated
  names**: `esc()` does not escape quotes; apostrophes in names break inline handlers.
- **`.gitignore`** covers `quickbooks_config.json` and `quickbooks_items_cache.json`.
- **Estimates are non-posting; never create posting transactions.** The app may write Customers
  and Estimates; a project bind is a local-only link to a Project created in QBO's UI. The legacy
  job endpoint remains available for old/manual compatibility but is not used by new estimate
  creation — never write Invoices/Payments/journal entries.
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

For the first Production catalog comparison: deploy the relay (`relay/DEPLOY.md`), register the
relay HTTPS URL under the **Production** tab, and use the separate **QB Catalog Preview** profile
with Production keys. Do **not** switch the standard QuickBooks connection to production; it remains
the sandbox integration until the reviewed migration is approved.

---

## 6. Production inventory transition — owner safeguard

**Owner decision (2026-08-10):** The production QBO company uses a different inventory layout from
the sandbox company that seeded the Builder catalog. Treat the first production connection as a
reviewed catalog-mapping migration, never as a routine sync. It must not overwrite, deactivate, or
otherwise "clean up" existing Builder parts merely because the production company is organized
differently.

**Baseline checkpoint complete (2026-08-10):** an immutable local pre-production mapping snapshot
was created from the installed Builder catalog: 785 products, 1,353 part-number entries, 1,222
currently linked entries, and 29 pending-QB entries. It also preserves the 1,291-item normalized
sandbox cache used to recognize intentionally excluded QBO Items. The snapshot is local-only and
is not a cloud mirror or an automatic rollback mechanism.

The sandbox and production companies have different QBO Item IDs even where the underlying vendor
SKU is the same. Before enabling any production reconciliation or background polling:

1. Take a recoverable snapshot of the current `parts_db.json` and the existing QB links.
2. Pull the production item catalog into an isolated preview/cache, with automatic reconciliation
   and the 30-minute background sync disabled for this first pass.
3. Produce a reviewable mapping report for every existing QB-linked SKU: compare exact normalized
   Builder part number against both production QBO `Name` and `Sku`, select the proven identifier
   field once, then report candidate production Item ID, description/price/active-state differences,
   and the result (`safe match`, `needs owner choice`, `production-only`, or `Builder-only`). Do not
   accept a Name-based match until its column-level match rate and exceptions have been reviewed.
4. Require explicit owner approval before replacing a sandbox Item ID, accepting production-owned
   price/description changes, or marking a linked Builder part inactive. Preserve Builder-owned
   metadata such as part type, placement, render asset, compatibility, and manifest grouping.
5. Verify approved mappings by category and SKU count, then make a small representative test build
   and create **one non-posting estimate** for manual comparison in QBO.
6. Enable the normal background sync only after the owner signs off on that result. Keep the
   snapshot until the first routine production sync has been reviewed.

The current sync is safe against physical deletion, but it can update QB-owned fields for already
linked SKUs and mark missing items inactive. Therefore this reviewed first-production workflow must
be implemented and tested (or performed with an equivalently documented, isolated manual process)
before connecting the real company. The later reviewed catalog-change queue (§3) complements this;
it does not replace the initial migration review.

---

## 7. What's left before Production go-live (Phase 4)

- **Deploy the hosted relay** (`relay/DEPLOY.md`) and register its HTTPS URL as the Production
  redirect URI in the Intuit dashboard.
- Enter Production Client ID/Secret in the isolated **QB Catalog Preview** profile, connect the
  production company, and pull its Items into the separate preview cache. This is a read-only
  catalog comparison — do not use the standard QuickBooks connection or its Sync button.
- Review the Name-versus-SKU exact-match totals, select the production field that represents the
  vendor identifier, and verify that intentional exclusions are correctly recognized. Unexpected
  production-only or Builder-only rows are exceptions, not automatic imports.
- After reviewing the column totals, prepare one plan for every unambiguous exact match. Any
  ambiguous, Builder-only, pending, or unexpected production item remains an exception and is not
  touched. The plan still does not apply links; owner approval plus a separate apply feature are
  required.
- **Run the sandbox test cycle** (§5) and **submit the questionnaire** (§8).
- Obtain Production Client ID/Secret after approval; enter them only in the isolated production
  preview profile.
- Complete and approve the protected production inventory-transition review (§6) before any
  production reconciliation, background sync, or estimate creation.

**Deferred niceties:** Estimate→Invoice conversion (explicit user step today); "create new VB part
from this QB item" (link-to-existing is the shipped path); customer down-sync on the 30-min poll
(manual button today, owner chose reviewed-first).

> **Go-live is externally gated** (relay + questionnaire + Intuit approval). It is *not* advanced by
> the parts-import grind and should not block it. Run it as its own track when ready.

---

## 8. Appendix — App Assessment Questionnaire (prepared answers)

Reference when completing the questionnaire in the Intuit Developer Dashboard (organized by its tab
order). Complete the §5 sandbox test cycle first — Intuit rejects submissions where testing isn't done.

**Info to have ready:** App name `DTM Vehicle Builder`; category Accounting/Internal business tool;
country US; **1 realm** (our company only); Launch/Disconnect URL `https://<domain>`; Production
redirect `https://<domain>/.netlify/functions/qb-callback`; dev redirect
`http://localhost:7655/api/quickbooks/callback`; scope `com.intuit.quickbooks.accounting`; hosting
US (runs locally on user machines); no fixed IP (desktop app).

**§1 How your app operates:** internal desktop app generating vehicle build sheets for law
enforcement / emergency-vehicle upfits; QB integration syncs the parts catalog (Items) and creates
Customer/Estimate records; **internal use only**; **1 company**; not public/app-store.
*(If the live form asks "integrate with other platforms," answer YES — Microsoft SharePoint + GitHub.
The merged-doc text above said "No"; the owner corrected this to YES.)*

**§2 Data management:** QB data stored **locally only** (parts cache JSON on the user's US
workstation); never transmitted to any server other than Intuit's API; not shared with third
parties; used only to operate the app; retained locally; user can disconnect (clears tokens).

**§3 API usage:** reads **Items + Customers + Preferences**; writes **Customers and
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
