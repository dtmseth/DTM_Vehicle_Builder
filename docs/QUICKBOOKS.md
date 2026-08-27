# QuickBooks Online Integration

**Single entry point for all QuickBooks work.** Merges the former
`QUICKBOOKS_STATUS.md` (handoff/status), `QUICKBOOKS_INTEGRATION.md` (design), and
`QUICKBOOKS_QUESTIONNAIRE.md` (Intuit App Assessment answers).

**Code location**: the QB foundation is in `main`; guarded QB settings and estimate controls are
enabled following the production catalog and customer migrations. The production
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
| **1 — OAuth + tokens** | One-click managed connect/disconnect/reconnect, keychain token storage, CSRF, 302 callback, hosted token broker | ✅ Built. Production app registration is bundled without its secret; users only sign in. |
| **2 — Parts sync** | Pull Items → cache (A), link items to parts (B), reconcile linked parts + 30-min background sync (C) | ✅ Production activated 2026-08-11. Production pull/reconciliation verified read-only against 1,335 active Items. |
| **3 — Customers ↔ Agencies + estimate customer flow** | Down-sync, agency→QB up-sync, top-level customer resolution, legacy job bridge | ✅ Production customer migration completed 2026-08-11: all 214 agencies linked to existing production Customers; reviewed duplicate Customers excluded. |
| **Estimates** | Non-posting Estimate per vehicle; validate/create/batch + Builds-tab UI | ✅ Production exercised. Blocks unless every part is QB-linked. Retail/Custom pricing and estimate numbering are calculated immediately before create. |
| **Production catalog preview** | Snapshot-pinned production Item pull, Name/SKU column comparison, intentional-exclusion carry-forward, exact-match plan | ✅ Migration plan reviewed and applied 2026-08-11. The duplicate preview token was retired locally without revoking the promoted standard production authorization. |
| **4 — Questionnaire submission** | Submit Intuit App Assessment for Production keys | ✅ Approved; Production keys obtained and stored through the isolated preview profile. |

**The standard QB connection now runs against the Production company using Production keys.** The
production Item cache is active for normal reconciliation. The separate production-preview profile
retains only its app-registration secret for audit/reconfiguration; its access token, refresh token,
and realm binding were removed locally after promotion so it cannot compete with the standard
profile's rotating refresh token.

**Write boundary**: the app writes **Customers and non-posting Estimates** —
never Invoices, Payments, or any posting transaction. (A sandbox-only Item-seeding tool exists,
hard-gated to `environment == "sandbox"`.)

Agency saves synchronously create/update their top-level QBO Customer and return the result to the
UI, so a rejected Customer write cannot disappear in a background thread. New agencies default to
non-taxable. Because this production company has Automated Sales Tax enabled, non-taxable Customer
writes include its established government/public-safety exemption reason ID `3`; the production
customer population uses that reason for 134 existing exempt agencies.
Every agency Customer written by the app is also assigned the active QBO **Retail** Customer Type.
The integration resolves that type's company-local ID by its exact name at write time; it never
persists or hard-codes the production ID. In this company, Retail activates the shared QBO price
rules when a user adds an Item in the QBO form.
Before estimate creation, the linked QBO Project's taxable flag is aligned with the agency Customer;
QBO Projects otherwise retain their own taxable default and can add tax even when the parent agency
is exempt.

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
  blob via `msal-extensions` (in-memory fallback). Stores per-user `access_token`,
  `refresh_token`, and `realm_id` (plus an optional owner-entered secret for sandbox/manual
  diagnostics). **Never plaintext on disk.**
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
- `relay/` — hosted HTTPS OAuth relay (Netlify primary, Vercel alt). The production relay is live at
  `dtmvehiclebuilder.netlify.app`. Its `qb-token` function holds the shared Intuit app secret only
  in Netlify's protected environment; it never persists user tokens. See `relay/DEPLOY.md`.
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

### Centralization Phase 3A — deferred and excluded from production

**Owner decision, 2026-08-20:** table this phase. The production branch contains no centralized
QuickBooks backend, desktop central-mode flag, Entra Builder API integration, or server-side token
store. The existing per-user OS-keychain connection and stateless OAuth broker remain the only
supported path. Do not register, deploy, authorize, or migrate tokens for a central service unless
the owner explicitly resumes the work.

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
- The preview can create and immediately select a new immutable baseline from the current Builder
  catalog after each owner-reviewed cleanup pass. The button copies only `parts_db.json` and, when
  the standard profile is sandbox, its normalized Item cache. It never reads or copies credentials,
  OAuth tokens, or production connection metadata.
- QBO Items present in the sandbox cache but absent from the baseline Builder catalog are carried
  forward as **intentional exclusions** when their normalized Name or SKU appears in production.
  They remain outside the Builder catalog; unrecognized production-only Items still block the
  eventual mapping approval and remain untouched in the exact-match plan.
- Once the owner selects the proven identifier field, the app may prepare one exact-match plan for
  every unambiguous match. Ambiguous, missing, unexpected, or blank-key rows stay out of that plan
  for later review. **Prepared is not applied:** a later explicit owner-approved apply step is
  required before any catalog link changes.

#### Locked production lineage findings (2026-08-11)

Baseline `20260811T163517Z-post-part-cleanup` is the current migration anchor. The isolated
production preview contains 1,335 active Items and 281 inactive historical Items. Its
snapshot-and-cache-pinned historical plan is written to
`workspace/quickbooks_production_historical_link_plan.json` with status
`applied` after the owner-approved activation on 2026-08-11.

- All 1,222 previously linked Builder rows have a high-confidence production successor: 1,212
  literal Name matches, 6 retired `Name (deleted)` matches, 3 controlled `-B` renames, and 1 exact
  description match. There are zero unmatched prior links.
- The 1,222 rows resolve to 1,216 unique Items because six Builder rows intentionally share an Item
  link. Shared links are preserved rather than treated as duplicates.
- All matched production Items have a blank QBO `Sku`. This is compatible: Builder keeps its own
  `part_number` for selection/display and stores the production `qb_item_id` as the durable QBO
  reference. Estimate payloads use `ItemRef.value = qb_item_id`, not `Sku` or `Name`.
- Six matched production Items are inactive and remain linked with `qb_inactive=true`; estimate
  validation blocks them instead of deleting or silently substituting another Item.
- Ten matched Items changed QBO type (nine to Inventory, one to Service). Item type does not alter
  the estimate reference path; all are addressed through the same Item ID. The change is retained
  in the plan for audit.
- Production price and sales description are authoritative after activation. Normal production
  reconciliation refreshes those fields by Item ID, so price changes and whitespace/newline
  differences do not break Builder part selection.
- Estimate validation and creation each perform a fresh Item pull and reconciliation first. If
  current production prices cannot be refreshed, the estimate is blocked instead of using stale
  cached prices.

Activation stopped the running desktop process before the profile swap, promoted the keychain-held
production credentials into the standard profile, seeded the standard active Item cache, applied
only the plan's QB-owned fields, and retired the duplicate preview token without revocation. The
first standard production pull/reconciliation updated no reviewed links, incorrectly flagged zero
Items inactive, and linked one formerly pending part by an exact production Name match. That
activation checkpoint held 1,223 linked rows. The v3.4.0 catalog now holds **1,224 linked rows,
28 pending rows, and 6 intentionally inactive linked rows**.

The owner-facing entry is **Advanced Settings → QB Catalog Preview**. It appears only on a machine
that already has a valid local migration snapshot. Guarded QB sales/estimate controls are enabled;
all write operations still require their backend checks and explicit confirmation.

### Phase 3 — Customers ↔ Agencies + estimate customer flow
- **Production migration:** QBO Customer IDs are company-local, so the 211 stored sandbox IDs were
  never copied directly. A guarded migration snapshot ignored every old ID, relinked 207 agencies
  by one unique normalized production name, filled 671 blank profile fields, and required owner
  decisions for every exception. The reviewed finish linked Minnesota State Patrol to Customer 39,
  Cold Spring Fire Department to 240, and the Camp Ripley training agency to 104; deleted two
  owner-confirmed local sample agencies; and imported Baker Police Department, Custer County
  Sheriff, Dundas Police Department, and Camp Ripley Fire Department. All 214 remaining agencies
  now point to distinct, existing production Customers.
- Production Customer IDs 38, 88, and 407 are reviewed duplicate records. Future customer import
  previews and imports exclude them so they cannot replace the selected State Patrol/Cold Spring
  links. The local migration plan and immutable agency snapshot remain in the ignored `workspace/`
  recovery area; credentials are never included.
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
the app does not create a sub-customer. This local link can be previewed and saved before the unit
has a configured build draft; only Estimate validation waits for configuration. Project names are
stable per vehicle. The generated/copied format is `Unit {number} | Build {build year}`; QBO already
shows the parent Customer, so the agency is intentionally omitted. When a unit number is unavailable,
the app uses a deterministic build-type label such as `Patrol #1 | Build {build year}`.
The fallback is derived from the vehicle's stable `individual_id`, so adding a unit number later
does not lose its stored Project, Estimate, PPTX, or PDF associations. Removing the redundant agency
prefix from new generated names, plus migrating stored display names, is planned in
`NEXT_FEATURE_PLAN.md`.
The app requires agency name, contact name/email/phone, and billing street/city/state/postal code
before it can create an estimate. If the agency is not linked, it first reuses an exact top-level
Customer name match; otherwise it asks the user to confirm the complete customer profile before
creating one. A confirmed profile update is a sparse Customer-only write. The vehicle's
stable project name is written into `CustomerMemo` and `PrivateNote`, and persisted with
`IndividualUnit.qb_project_id`; no new sub-customer is created.

**True QBO Projects are a separate capability:** Intuit documents a Project API, but it requires
the company's Projects feature plus the premium/restricted `project-management.project` scope.
That scope is unavailable to the current no-charge **Builder** developer tier; it requires the
Intuit workspace to subscribe to **Silver or higher** (Silver is currently US$300/month). The QBO
company must also be Plus, Advanced, or Intuit Enterprise Suite; project estimates through the new
Project API require Advanced or Enterprise Suite. The current desktop OAuth scope is the regular
accounting scope, so the app does not create or list Projects programmatically. The standard
Estimate REST request does accept a known `ProjectRef`, which is why manually created Projects can
be linked without the premium scope. The premium API is only needed to automate Project
creation/listing. See Intuit's
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
  A vehicle with a stored `qb_estimate_id` cannot silently create another form. The review asks the
  user to either **update the existing Estimate** (read current `SyncToken`, then sparse-update the
  complete Builder-owned line array and header fields) or deliberately **create a separate new
  Estimate**. The new ID replaces the vehicle's current local Estimate link; the older QBO form is
  retained in QuickBooks. After every successful create or update, the vehicle stores a canonical
  snapshot of the Builder-owned Estimate header and material lines. Validation and update read the
  current QBO form and compare it with that snapshot. If QBO was edited, the review raises a loud
  conflict warning, exposes the field/line differences, and requires an explicit choice to
  **overwrite the QBO changes** or **create a separate new Estimate**. The update service repeats
  the comparison immediately before writing, so a change made after the review cannot be silently
  overwritten. Older linked estimates without a baseline are visibly marked untracked and still
  require an explicit choice.
  The standard Accounting-only connection deliberately does not write
  sales-form custom fields: modern QuickBooks fields require their paid Custom
  Fields API to resolve the company-specific field IDs. This keeps a custom
  form mismatch from blocking the non-posting estimate create. The optional
  phone, vehicle, sales-ID, and unit header fields therefore remain managed in
  QuickBooks unless that paid scope is enabled later.
  Production QBO `Item.UnitPrice` is treated as list price. Before validation or creation, the app
  applies the shared **Retail** manufacturer rule: Gamber-Johnson 40%, Havis 20%, PAC Tool 5%,
  Santa Cruz 25%, Setina 20%, Westin 15%, and Whelen 38% off list. An Agency stores only sparse
  manufacturer exceptions in `pricing_overrides`; these prefill Custom pricing but never silently
  replace Retail. The create dialog defaults to **Retail pricing** and offers explicit, temporary
  **Custom pricing** for that estimate, with live list/savings/customer totals.
  After material pricing, `estimate_charges_service.py` appends a separate **Additional charges**
  block. Patrol, Undercover, Admin, and Custom presets supply total labor and install-supplies
  amounts; the reviewer can override them for one vehicle and optionally add delivery. The app then
  calculates a 4% card fee from materials + labor + supplies + delivery (never fee-on-fee). These
  lines resolve the active QBO Service items named `LABOR INSTALL`, `INSTALL SUPPLIES`,
  `Convenience Fee`, and `TRAVEL` from the freshly pulled company cache. A missing item or a zero
  required amount blocks creation with a visible reason. Shared defaults live in
  `estimate_charges.json` and are edited under Settings → Projects. An older manually selected
  install-supplies draft row stays on the shop manifest but is removed from estimate materials so
  the managed Additional charges line cannot bill it twice.
  The Estimate payload sends the calculated `UnitPrice` and `Amount` explicitly, so QBO's internal
  item/rule formatting cannot change the reviewed price. Production estimate inspection confirms
  these discounted values are stored as each line's raw `UnitPrice`/`Amount`; QBO does not add a
  second discount layer over app-supplied rates. Catalog reconciliation still refreshes
  list prices only and never writes customer prices back into Item data.
  This production company has `SalesFormsPrefs.CustomTxnNumbers` enabled. QBO therefore leaves
  API-created Estimate numbers blank unless `DocNumber` is supplied. Immediately before each new
  create (never an update), the app reads the complete Estimate number set, advances the highest
  numeric value, and sends it. If no safe numeric sequence can be determined, creation blocks with
  a visible error instead of producing an unnumbered form.
  The Accounting API does not expose QBO's price-rule tables, so these reviewed local rules are
  deliberately authoritative for Vehicle Builder estimates. See Intuit's
  [platform release notes](https://developer.intuit.com/app/developer/qbo/docs/release-notes/platform-release-notes).
  The QBO Estimate form has a separate **Discounts and fees → Bank transfer — 1% per transaction,
  max $20** switch. It is not the Invoice entity's `AllowOnlineACHPayment` field. The Accounting API
  does not return or document a writable field for this Estimate-form switch (including on existing
  production Estimates), so estimate creation cannot set or verify it. The create review explicitly
  instructs the user to turn it on in QBO after creation; the app must not send an invented field.
  QBO's standard Accounting API supports attaching the generated build-sheet PDF to an
  existing Estimate. This is a second request after Estimate creation: multipart `POST /upload`
  with `application/pdf` content and Attachable metadata whose `EntityRef` type is `Estimate` and
  value is the returned Estimate ID. QBO requires the Estimate to exist first and permits up to
  100 MB total per upload request. The estimate review now offers **Attach build PDF**, shows the
  exact filename, verifies a readable PDF inside an approved output directory, and skips an
  already-linked file with the same name and byte size. Upload failure is reported separately—the
  successfully created or updated Estimate is never represented as failed or retried merely
  because its subsequent attachment upload failed.
  A PDF path stored by another app instance is treated as a portable export identity, not as a
  usable local path. Before attachment, the app retrieves the agency/year/filename from the shared
  Microsoft export library and validates the downloaded PDF. Estimate routes always return a safe
  JSON reason; unexpected failures include a short support reference written with the full
  exception to the local log, without exposing credentials or third-party response detail.
  Pending-QB parts post as a `DescriptionOnly` line (flagged, non-blocking).
- UI: per-vehicle **📋 QB Estimate** + footer **Prepare QB Estimates** on the Builds tab. Estimate
  preparation requires a current PDF and offers the export operation in the Estimate flow, with a
  visible progress state while the PDF is generated; batch creation carries the resulting PDF path
  into each Estimate request.
  A blocked per-vehicle attempt raises a copyable error toast naming the Project/customer/catalog
  issue instead of failing silently. Missing Project links open a numbered manual-QBO walkthrough;
  if the unit number is missing, its first action opens that vehicle's Details form directly.
  The batch screen first checks every configured vehicle, lets the user set up missing Projects,
  and creates only the ready estimates after an explicit confirmation. Project setup includes a
  **Back to vehicle checklist** action; returning or saving a valid Project link reloads the project,
  reruns every vehicle's validation, moves the linked vehicle to **Ready**, and leaves the next
  setup action available. The price-refresh notice is a toast, and any unexpected review-modal
  rendering failure is surfaced instead of silently stopping.
  (`detail_builds.js`, `#qb-est-modal`). Tests: `tests/test_qb_estimate_service.py` (52),
  `tests/test_estimate_charges_service.py` (4), and `tests/test_customer_pricing_service.py`.
- The header **Connections** modal shows Microsoft 365 and QuickBooks Online together. QuickBooks
  status is checked when the modal opens; disconnected users can start OAuth there, while connected
  users can open the full QuickBooks settings panel. Credentials remain in the isolated OS keychain.

### Full route list (`/api/quickbooks/*`)
`GET status` · `GET auth-url` · `GET callback` (302) · `GET items` · `GET pricing-status` · `GET customer-pricing` · `GET customers/preview` ·
`POST settings` · `POST disconnect` · `POST sync` · `POST link-item` · `POST unlink-item` ·
`POST customer-pricing/default` · `POST customers/import` · `POST push-vehicle-job` (legacy) · `POST estimates/validate` ·
`POST projects/preview` · `POST projects/bind` ·
`POST estimates/customer-preview` · `POST estimates/create` · `POST estimates/create-batch`

**Release verification (v3.4.0):** full suite 2,077 passed, 1 skipped, 1 sandbox-only deselected;
hermetic browser smoke 28/28. See `CURRENT_STATE.md` for the live baseline and coverage summary.
QB-specific: service (15), sync (24), customer-sync (14), agency-push (13), estimate (54),
customer-pricing (4), seed-sandbox (5).

---

## 3. Architecture & design

### OAuth redirect — hosted relay required for Production
Intuit Production keys require an **HTTPS redirect URI on a real domain**; `http://localhost` is
only accepted for sandbox/development. Netlify provides a 302-only callback plus a stateless token
broker (`relay/netlify/functions/qb-callback.js` and `qb-token.js`):

```
QBO auth page → https://<domain>/.netlify/functions/qb-callback?code=...&state=...&realmId=...
             → HTTP 302 → http://localhost:7655/api/quickbooks/callback?... → local app captures tokens
```

The callback never reads, stores, or logs the code. The desktop forwards the one-time code over
HTTPS to `qb-token`; that function exchanges it using the Intuit secret held only in Netlify's
protected environment and never persists/logs either code or tokens. For sandbox, register
`http://localhost:7655/api/quickbooks/callback` under the Development tab.

### Token storage — OS keychain via `msal-extensions`
Reuses the exact mechanism the M365/SharePoint integration uses (`adapters/cloud/msal_client.py`):
`msal-extensions` encrypted persistence backed by the OS-native credential store. **Zero new
dependencies.** Per-user sensitive values (`access_token`, `refresh_token`, `realm_id`)
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
Holds `client_id` (not a secret), `environment`, `redirect_uri`, `token_broker_url`, expiry timestamps, `last_sync_utc`,
`connection_status`. No credential values.

---

## 4. Security & architecture invariants (must not regress)

These are enforced today (see [EXTERNAL_CONNECTION_SECURITY.md](EXTERNAL_CONNECTION_SECURITY.md) and
GOTCHAS):

- **Per-user tokens only in the OS keychain.** `access_token`, `refresh_token`, `realm_id`
  via `credential_store.py`. The shared Intuit app secret is only a protected Netlify environment
  variable and is never shipped. No secret is in a repo/file/log. `quickbooks_config.json` = non-secret
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

## 7. Production operations and remaining improvements

Production go-live is complete. The relay, App Assessment, Production credentials, catalog and
customer migrations, representative Estimate comparison, normal reconciliation, and Estimate UI
are active. Connected installations reconcile linked Item data at startup and every 30 minutes;
each Estimate preparation also refreshes prices and blocks rather than using stale values if the
refresh fails.

Operationally, users still create true QBO Projects manually, paste the Project page URL/ID into
the Builder, review every Estimate, and turn on **Bank transfer — 1% per transaction, max $20** in
QBO after creation when required. Those are explicit product/API constraints, not incomplete
connection setup.

**Deferred niceties:** Estimate→Invoice conversion (explicit user step today); "create new VB part
from this QB item" (link-to-existing is the shipped path); customer down-sync on the 30-min poll
(manual button today, owner chose reviewed-first); automatic QBO Project creation after a future
Silver+ developer-tier upgrade.

**Planned multi-user identity/audit migration:** keep one owner/admin-authorized company OAuth
connection in a protected backend rather than distributing rotating refresh tokens to workstations.
Employees authenticate to the Builder backend with their existing Microsoft 365/Entra identities;
they do not sign in to Intuit or know the owner's QBO credentials. Only an authorized Builder Admin
can complete initial Intuit consent or emergency reconnection. The backend validates tenant,
audience, user, and app role, serializes refresh-token rotation, makes narrowly scoped QBO calls, and
keeps its own append-only user/action/entity audit trail. QBO records third-party API writes as
`System Administration`, so the Builder audit supplies employee attribution that QBO does not.

This applies to operations inside Vehicle Builder. Manual creation or renaming of true QBO Projects
still requires an employee's own QBO access or owner/admin handling until the app is eligible for the
restricted Projects API scope.

The currently deployed stateless Netlify token broker is not an Accounting API backend and cannot
solve the multi-workstation refresh race by itself. No centralized Accounting API adapter is
included in the production branch. The target cutover sequence, role model, failure behavior, and
acceptance tests remain future design work in `NEXT_FEATURE_PLAN.md` Phase 3A. Until that work is
explicitly resumed, the existing per-user OS-keychain connection remains the live behavior.

The next QuickBooks architecture improvement is the reviewed catalog-change queue described above.
Routine reconciliation may update QB-owned fields on already-linked SKUs, but must not silently
create or materially reshape Builder products.

---

## 8. Appendix — App Assessment Questionnaire (prepared answers)

Reference when completing the questionnaire in the Intuit Developer Dashboard (organized by its tab
order). Complete the §5 sandbox test cycle first — Intuit rejects submissions where testing isn't done.

**Info to have ready:** App name `DTM Vehicle Builder`; category Accounting/Internal business tool;
country US; **1 realm** (our company only); Intuit Single Sign-on **No**; scope
`com.intuit.quickbooks.accounting`; hosting US (runs locally on user machines); no fixed IP
(desktop app). Deploy the relay before entering any Production URL. Use the provider-assigned HTTPS
origin exactly; do not invent a host domain.

The verified deployed origin is `https://dtmvehiclebuilder.netlify.app`:

| Intuit field | Value |
|---|---|
| App host domain | `dtmvehiclebuilder.netlify.app` (hostname only) |
| Launch URL | `https://dtmvehiclebuilder.netlify.app/` |
| Connect URL | `https://dtmvehiclebuilder.netlify.app/connect/` |
| Reconnect URL | `https://dtmvehiclebuilder.netlify.app/reconnect/` |
| Disconnect URL | `https://dtmvehiclebuilder.netlify.app/disconnect/` |
| Production redirect URI (Netlify) | `https://dtmvehiclebuilder.netlify.app/.netlify/functions/qb-callback` |
| Production redirect URI (Vercel alternative) | `https://<verified-vercel-host>/api/qb-callback` |
| Development redirect URI | `http://localhost:7655/api/quickbooks/callback` |

The hostname above is the live DTM Netlify site and must not be substituted without a reviewed
deployment change. The public connect/reconnect pages are
instructions for this non-SSO internal desktop app; OAuth itself starts only from the isolated
**QB Catalog Preview** profile on the authorized workstation.

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

**§4 Authorization:** OAuth 2.0 auth-code; one-time browser authorization; user tokens in OS keychain via
`msal-extensions`; **refresh-token rotation** on every refresh (new token re-encrypted + saved
atomically); **CSRF** via `state` (`secrets.token_urlsafe(32)` + `compare_digest`, rejected on
mismatch with 400); shared client secret only in the protected stateless Netlify token-broker
environment, never in the desktop installer; connect/disconnect/reconnect tested in sandbox.

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
> Per-user token values live ONLY in the keychain; the shared Intuit app secret lives only in the
> protected Netlify environment; `quickbooks_config.json` is non-secret metadata.
