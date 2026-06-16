# QuickBooks Integration — Session Handoff & Status

**Last updated**: 2026-06-16
**Branch**: `claude/quickbooks-integration-design-rcgula` (all QB work lives here; not yet merged to `main`)
**Read order for a new session**: this file → `docs/QUICKBOOKS_INTEGRATION.md` (design + per-phase detail) → `docs/QUICKBOOKS_QUESTIONNAIRE.md` (Intuit answers) → `docs/EXTERNAL_CONNECTION_SECURITY.md` (security standard) → `relay/DEPLOY.md` (relay deploy).

This document is the single entry point. It records where we are, what's left, what changed along the way, the Intuit questionnaire questions, the tests Intuit requires, and the things that must be in place before going live.

---

## 1. TL;DR — where we are

The QuickBooks Online integration is an **internal, single-company** integration for the DTM Vehicle Builder desktop app. It does three things: (1) one-time OAuth connect, (2) sync the parts catalog from QBO Items, (3) sync QBO Customers into the app's Agencies. A per-vehicle costing bridge is designed but not built.

| Phase | What | Status |
|-------|------|--------|
| **1 — OAuth + tokens** | Connect/disconnect/reconnect, keychain token storage, CSRF, 302 callback, hosted relay | ✅ Built. Connect/disconnect/reconnect **tested in sandbox by the owner.** |
| **2 — Parts sync** | Pull Items → cache (A), link items to parts (B), reconcile linked parts + 30-min background sync (C) | ✅ Built. Pull (A) **tested in sandbox** (returned sandbox placeholder items). B/C built + unit-tested, not yet exercised live. |
| **3 — Customers ↔ Agencies + vehicle bridge** | QB Customers → Agencies down-sync (Slice 1) | ✅ Slice 1 built + **tested in sandbox by the owner** ("customer import worked"). Slices 2 & 3 NOT built (see §4). |
| **4 — Questionnaire submission** | Submit Intuit App Assessment for Production keys | ⛔ Not done. Requires sandbox test cycle confirmation + relay deploy (see §5, §6). |

**Currently runs against the SANDBOX company using Development keys.** No Production keys, no relay deployed, questionnaire not submitted. Nothing is live against a real QBO company yet.

---

## 2. What's built and where it lives

### Phase 1 — OAuth + token management
- `src/dtm_buildsheet/app/adapters/quickbooks/credential_store.py` — `QuickBooksCredentialStore`: OS-keychain secret blob via `msal-extensions` (in-memory fallback when keychain unavailable). Stores `client_secret`, `access_token`, `refresh_token`, `realm_id`. **Never plaintext on disk.**
- `src/dtm_buildsheet/app/adapters/quickbooks/oauth_client.py` — `QuickBooksOAuthClient`: OIDC discovery (prod + sandbox), code exchange, refresh, revoke. Process-wide discovery cache, 10s timeout. Never logs token values.
- `src/dtm_buildsheet/app/services/quickbooks_service.py` — orchestration: `save_settings`, `generate_auth_url` (CSRF state), `validate_state` (single-use, constant-time), `complete_authorization`, `ensure_access_token` (refresh + **refresh-token rotation**), `disconnect`, `get_status`, `get_realm_id`, `set_last_sync`. `quickbooks_config.json` (non-secret metadata) lives in workspace root, managed **directly** (NOT via `config_service`/SharePoint mirror).
- `src/dtm_buildsheet/app/routes/quickbooks.py` — all routes; every response sets `Cache-Control: no-store`; callback is **302-only** (never echoes code/token).
- `src/dtm_buildsheet/ui/index.html` + `ui/js/settings/quickbooks.js` — Settings → General → QuickBooks tab: connection card, app-registration form (Client ID/Secret/env/redirect), Connect/Disconnect.
- `relay/` — hosted HTTPS OAuth relay (Netlify primary, Vercel alt). See `relay/DEPLOY.md`. **Not yet deployed.**
- Tests: `tests/test_quickbooks_service.py` (13, hermetic).

### Phase 2 — Parts sync
- `src/dtm_buildsheet/app/adapters/quickbooks/api_client.py` — `QuickBooksApiClient` (read-only Data API): `fetch_active_items()`, `fetch_active_customers()` (top-level only), normalizers. Environment-aware base URL (`sandbox-quickbooks.api.intuit.com` vs `quickbooks.api.intuit.com`). Never logs bodies.
- `src/dtm_buildsheet/app/services/qb_sync_service.py`:
  - `sync_items()` — pull active Items → `quickbooks_items_cache.json` (git-ignored, workspace root). **Reads** parts_db only to flag linked items; never writes it (Slice A).
  - `link_item()` / `unlink_item()` — attach/detach a QB item to a VB product via `save_config_file("parts_db.json", …)` (proper mirror path). Additive, one-to-one (Slice B).
  - `reconcile_linked_parts()` — push QBO `sku`/`unit_price`/active status onto **linked** parts only; flag missing items `qb_inactive` (never delete); writes only on change (Slice C).
  - `run_full_sync()` = pull + reconcile. `start_background_sync()` = daemon, app-start + every 30 min, only when connected, no-ops under pytest. Wired in `server.py:main()`.
- UI: Parts Sync card (pull button, summary, item list with linked/unlinked badges + Link/Unlink) + link-picker modal in `quickbooks.js` / `index.html`.
- Tests: `tests/test_qb_sync_service.py` (22).

### Phase 3 — Customers → Agencies (Slice 1 only)
- `AgencyRecord.qb_customer_id` added (`domain/agency_models.py`).
- `agency_service.preview_qb_customer_import()` (dry run) + `upsert_agencies_from_qb()`. Match precedence: `qb_customer_id` → normalized name → create. Linking fills only EMPTY contact fields; never overwrites the agency name or existing user data. Bulk cloud propagation via `save_settings_to_cloud_batch_in_background` (one thread).
- `qb_sync_service.preview_customer_import()` / `import_customers()`.
- Routes: `GET /api/quickbooks/customers/preview`, `POST /api/quickbooks/customers/import`.
- UI: "⬇️ Pull customers from QuickBooks" → preview → confirm (`N new, M updated`) → import; refreshes Agencies tab.
- Tests: `tests/test_qb_customer_sync.py` (12).

### Full route list (`/api/quickbooks/*`)
`GET status` · `GET auth-url` · `GET callback` (302) · `GET items` · `GET customers/preview` · `POST settings` · `POST disconnect` · `POST sync` · `POST link-item` · `POST unlink-item` · `POST customers/import`

---

## 3. Bugs found & fixed along the way (don't regress these)

1. **OAuth discovery re-fetched every call** → cached process-wide; timeout 30s→10s (`oauth_client.py`). (The owner's "QB consent page spun once" was Intuit-side embedded-webview session state, not our code — a fluke cleared by restart.)
2. **Bulk-import mirror race** → a snapshot thread re-uploaded agencies the user deleted mid-import, resurrecting them. Fixed: `save_settings_to_cloud_batch_in_background` now takes `(target_file, local_path)`, re-reads at upload time, and **skips files deleted in the meantime** (`shared_work_service.py`).
3. **Silent cloud-delete failures** → throttled (429) deletes were swallowed and reported success. Fixed: `delete_setting_from_cloud` retries with backoff and returns `True` for the no-cloud case; `handle_delete_agency` surfaces a `cloud_warning` the UI shows.
4. **Undeletable records whose names contain apostrophes** (THE actual "can't delete imported agencies" cause). Inline `onclick="agencyDelete('id','Sheriff's Office')"` — `esc()` doesn't escape quotes, so the apostrophe broke the handler. Fixed in BOTH `agencies.js` and `sales_reps.js`: switched to `data-*` attributes + a delegated click listener. Tests: `tests/test_settings_mirror.py` (5).

**Test totals**: 52 QB-specific tests pass. Full suite: 1562 pass, 1 pre-existing unrelated failure (`test_asset_manifest_asset_files_exist` — missing `Push Bumper Alone_side.png`, nothing to do with QB).

---

## 4. What's left to build

### Phase 3 Slice 2 — Agency → QB push (up-sync) [DECIDED, not built]
Owner chose **auto-mirror on save**: when an agency is created/edited and QB is connected, create/update the matching QB Customer in the background (same fire-and-forget pattern as the SharePoint mirror), and write `qb_customer_id` back. Skip silently if disconnected. NOTE: the owner asked to do the **down-sync first** (done); this up-sync is the agreed next step.

### Phase 3 Slice 3 — Per-vehicle job bridge [DESIGNED, not built; owner doesn't use sub-customers yet]
**Critical QBO fact (verified):** the QBO v3 API **cannot create Projects** — `Customer.IsProject` is read-only. Per-unit costing must use **sub-customers (jobs)**: a `Customer` with `Job=true` + `ParentRef` to the agency's Customer. Time/costs log against those; they can be batch-converted to Projects in the QBO UI later. Plan: `push_vehicle_job()` ensures the agency Customer exists → creates one sub-customer/job per `IndividualUnit` → writes `qb_job_id` back to the unit. Needs `IndividualUnit`/`ProjectRecord` fields + a Builds-tab "Push to QuickBooks" per unit. Owner wants per-vehicle costing, NOT whole-VB-project costing.

### Deferred niceties
- "Create new VB part from this item" (pre-fill Part Manager from a QB item) — Phase 2 link-to-existing is the shipped path.
- Customer down-sync is currently a manual button only; could be added to the 30-min background poll later (owner chose reviewed/manual first).

### Before Production go-live (Phase 4)
- **Deploy the hosted relay** (`relay/DEPLOY.md`) and register its HTTPS URL as the Production redirect URI in the Intuit dashboard.
- **Run the sandbox test cycle** (§5) and **submit the questionnaire** (`docs/QUICKBOOKS_QUESTIONNAIRE.md`).
- Obtain Production Client ID/Secret after approval; enter them in the app with `environment=production` and the relay redirect URI.

---

## 5. Tests Intuit requires before submitting the questionnaire

Intuit's most common rejection is "connect/disconnect/reconnect not tested." Do these against the **sandbox** company (Development keys, `environment=sandbox`, redirect `http://localhost:7655/api/quickbooks/callback`) and confirm:

1. **Connect** — full OAuth round-trip; status badge → green; token expiry dates populate. ✅ done by owner.
2. **Disconnect** — tokens cleared; badge → not connected; subsequent API calls rejected. ✅ done by owner.
3. **Reconnect** — full OAuth again from disconnected state; new tokens stored. ✅ done by owner.
4. **CSRF** — a mismatched `state` is rejected (covered by unit tests; can demo by tampering the callback URL).
5. **Refresh-token rotation** — after a token refresh, the NEW refresh token is saved (unit-tested; happens automatically near expiry).
6. **Parts pull** — `POST /sync` returns sandbox items. ✅ done by owner.
7. **Customer import** — `POST /customers/import` creates agencies. ✅ done by owner.
8. **Log review** — confirm the app log contains no tokens/realm IDs/QB data (only `intuit_tid`, status, timestamps).

The questionnaire's full pre-submission checklist is at the bottom of `docs/QUICKBOOKS_QUESTIONNAIRE.md` (updated to reflect the keychain implementation — ignore any lingering mention of `quickbooks_key.bin`, that design was dropped).

---

## 6. The Intuit App Assessment Questionnaire — what they ask

Full prepared answers are in **`docs/QUICKBOOKS_QUESTIONNAIRE.md`**, organized by the dashboard's tab order. Summary of the sections and the key answers:

- **Info to have ready**: app name, category (Accounting/Internal), countries (US), # realms (**1**), host domain, Launch/Disconnect URLs, **Production redirect URI = the relay HTTPS URL**, dev redirect = localhost, scope `com.intuit.quickbooks.accounting`.
- **§1 How your app operates**: internal-only desktop app; build sheets for emergency-vehicle upfits; syncs parts + customers; **1 company**; **does** integrate with other platforms (Microsoft SharePoint, GitHub) — *(the owner corrected this; if the questionnaire asks "integrate with other platforms," answer YES: SharePoint, GitHub)*; not public/app-store.
- **§2 Data management**: QB data stored locally only (parts cache JSON); not shared with third parties; used only to operate the app; retained locally; user can disconnect (clears tokens).
- **§3 API usage**: reads Items + Customers; writes Customers + Projects(=sub-customer jobs) only; **never** writes invoices/transactions/payments; minimum scope; handles errors; logs `intuit_tid` only.
- **§4 Authorization**: OAuth 2.0 auth-code; tokens in OS keychain via `msal-extensions`; **refresh-token rotation** on every refresh; **CSRF** via `state` (`secrets.token_urlsafe(32)` + `compare_digest`); connect/disconnect/reconnect tested in sandbox.
- **§5 Error handling**: graceful API error messages; captures `intuit_tid`; structured local log, no secrets.
- **§6 Legal**: no complaints/lawsuits; reviewed obligations; will comply with Intuit ToS; sanctions/export compliant; data used only for own company.
- **§7 Security**: tokens encrypted at rest in OS keychain (OS-managed AES); HTTPS for all external traffic (relay for redirect); no secrets in logs; CSRF; no third-party access; OS-level access control; assessed for XSS (textContent), CSRF (state), SQLi (n/a), XML injection (sanitized), TRACE (405).

**Q2 note** (raised by owner): the "How often does your app call the API / store data" question was a dropdown — our honest answer is roughly **"More than once a day"** (30-min background poll when connected), not "every API call."

---

## 7. Things that MUST stay in place (security & architecture invariants)

These are enforced today and must not regress (see `docs/EXTERNAL_CONNECTION_SECURITY.md` and CLAUDE.md gotchas):

- **Secrets only in the OS keychain.** `client_secret`, `access_token`, `refresh_token`, `realm_id` via `credential_store.py`. Never in any file, never logged. `quickbooks_config.json` = non-secret metadata only, managed directly by `quickbooks_service` (NOT `config_service`; NOT in `REQUIRED_CONFIG_FILES` or any cloud-mirror set — it's per-machine connection state).
- **OAuth callback is 302-only.** Never echo the code/token in HTML (Referer-leak prevention).
- **`Cache-Control: no-store`** on every `/api/quickbooks/*` response.
- **Refresh-token rotation**: save the NEW refresh token on every refresh, or the connection dies.
- **No QB data in logs**: only `intuit_tid`, HTTP status, timestamps.
- **QB data is read-only for the catalog except linked parts**: `sync_items` never writes parts_db; only explicit `link_item`/`unlink_item`/`reconcile_linked_parts` touch it, and reconcile only writes QB-owned fields on already-linked products.
- **Customer import never clobbers user data**: fills only empty contact fields; never overwrites agency names.
- **Bulk settings mirror re-reads from disk + skips deleted files**: do NOT revert `save_settings_to_cloud_batch_in_background` to uploading a captured snapshot, or deletions resurrect.
- **List action buttons use data-attributes + delegation, never inline `onclick` with interpolated names**: `esc()` does not escape quotes; apostrophes in names break inline handlers.
- **`.gitignore`** covers `quickbooks_config.json` and `quickbooks_items_cache.json` (and the resources/config defensive paths).

---

## 8. How to run / test in sandbox (for the next session or the owner)

1. `git checkout claude/quickbooks-integration-design-rcgula && git pull`
2. Launch the dev app from the repo (`python -m dtm_buildsheet`), not the installed bundle.
3. Intuit dashboard → **Development** tab → register redirect `http://localhost:7655/api/quickbooks/callback`.
4. App → Settings → General → QuickBooks → App registration: Development Client ID/Secret, **Environment = sandbox**, redirect = the localhost URL → Save.
5. Connect → sign in with the Intuit **developer account** → authorize the auto-provisioned sandbox company.
6. Pull items, link a couple to parts, pull customers → agencies. Sandbox data is fake; clean up afterward if desired.

For Production later: deploy the relay (`relay/DEPLOY.md`), register the relay HTTPS URL under the **Production** tab, submit the questionnaire, then switch the app to `environment=production` with Production keys + the relay redirect URI.

---

## 9. Commit trail (this branch, newest first)

```
dbe12de Fix undeletable agencies/reps whose names contain apostrophes
893711b Fix imported agencies that resurrect after deletion
a22a04e Phase 3 Slice 1: import QuickBooks Customers as agencies
77c897c Phase 2 Slice C: reconcile linked parts + background sync
e31f474 Phase 2 Slice B: link QuickBooks items to Vehicle Builder parts
cf2cee6 Phase 2 Slice A: read-only QuickBooks parts pull
814f14f Cache QuickBooks OIDC discovery process-wide; tighten OAuth timeout
fa23474 Add QuickBooks OAuth HTTPS relay for Production redirect URI
985d640 Add QuickBooks Settings UI (connection card + app-registration form)
927c6a6 Implement QuickBooks Phase 1 backend: OAuth + token management
a4a3692 Add external connection security standard; upgrade QB token storage to OS keychain
f259351 Rewrite QB integration design doc; add questionnaire answer guide
a6d4152 Add QuickBooks Online integration design document
```
(Plus the docs commit that adds this file.)
