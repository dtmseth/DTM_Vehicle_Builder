# DTM Vehicle Builder — Long-Term Roadmap

> **Purpose**: Direction-setting document for sustained work on this codebase. Read this before proposing structural changes. Captures the destination, the major moves to get there, and the decisions that have already been made so future work doesn't drift back to old patterns.
>
> **Audience**: future contributors, future agents, and the project owner.
>
> **Status**: living document. Update it when a phase completes, when a decision changes, or when a new direction is set. Don't quietly contradict it — if you disagree, change it first, then act.

---

## 1. Vision

Two ideas drive everything below:

1. **The workbook is a renderer, not a database.** Historically the Excel "build sheet" was both the input and the source of truth for what parts/manufacturers/locations/colors exist. We are phasing this out. Domain data lives in a clean canonical database. The workbook becomes one of several outputs (alongside PowerPoint and PDF), built from the same domain data.
2. **The app is a tool, not a silo.** Today the app runs locally with a per-user workspace. The destination is a tool that runs locally but reads/writes a shared team workspace, so a sales rep, a builder, and a project manager all see the same projects, presets, and inventory. **Cloud platform is decided** (see §9 Decision Log): users sign in with their M365 account, and the app talks only to SharePoint via Microsoft Graph API. GitHub is the review backend — invisible to users — where the owner reviews settings change proposals as pull requests. GitHub Actions is the sync glue between the two clouds. Power Automate handles team-wide notifications for merged setting changes and new app releases. Getting team collaboration live is prioritized — the cloud-go-live phase comes *before* the parts-DB schema migration, so the team can start collaborating on the existing data structure while later phases deliver schema improvements through reviewed PRs.

Around those two ideas, five thematic pillars:

1. **One canonical parts database.** Manufacturers, models, locations, colors, brackets, inventory — all in one place, queryable from any UI or export path.
2. **Free-form, smart building.** Users add a part to a location with a visual preview, not a slot from a fixed list. The app handles naming, bracket recommendations, validation.
3. **Lights are a model, not a permutation table.** Colors are derived. Power outputs and bracket needs are data fields, not implicit knowledge.
4. **Views are extensible.** Today there are four external views per vehicle. Tomorrow there are interior views, top-down views, whatever the work needs. Nothing should hardcode "exactly four."
5. **Inventory is a first-class concept.** Parts have prices, quantities, and friendly names. Some parts get tracked by serial number on a per-project basis. The builder app and a future parts-manager app share one database.

---

## Current Direction & Critical Path (set 2026-06-29)

Live "what are we doing right now and why" — read it before §4's phase list. Detail lives in
[PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md) and [QUICKBOOKS.md](QUICKBOOKS.md).

**QuickBooks is the *foundation* of the parts system, not a side integration.** `parts_db.json` now
references parts at **SKU granularity** — real vendor part numbers + QB pricing — a fundamentally
different basis than the old "product name / part type" model. The Part Picker and every downstream
consumer depend on real QB data being in the DB, so the QB Item import sits *under* Phase 3 (it feeds
the canonical DB), not beside it. Finalizing the picker against pre-QB data means building against
data that's being deprecated. *Food on the shelves before the doors open.*

**The Part Picker is ~80% built, not blocked.** Chunks 1–7 are done and working for Whelen lights.
Remaining: Chunk 8 (search), Chunk 9 (polish + remove the flat modal), and non-light/no-color
coverage. The old "Chunk 5 JS bug / blocked" notes are stale — that was a server-side `AttributeError`,
fixed.

**The real bottleneck was data-review throughput** — now addressed: the **Parts Manager SKU Review grid
is shipped** (brand-sorted, every-field-inline-editable, QB-source read-only view, light/unbilled tags,
accessory roles, readiness + reviewed flags; full detail in [PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md)
§2.5). The owner can now curate SKUs self-service.

### Near-term critical path (in order, updated 2026-06-30)
1. ✅ **Parts Manager SKU Review grid** — *shipped* ("Phase 8 editing-UI brought forward"). Owner curates
   SKUs/tags/accessories/readiness without prompting Claude per item.
2. ✅ **Picker + placement cluster** — *shipped 2026-07-01* (this list lagged; reconciled 2026-07-07).
   Location model rebuilt at the part_type level (`location_mode` placement/text + `location_options`),
   scene no-color filter fixed server-side, SKU descriptions rendering. Detail:
   [PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md) §"Picker + placement cluster — SHIPPED".
   Only #7(a) (auto-skip empty location step) remains, low priority.
3. ⭐ **Kit SKUs** *(NEXT — scope before building)* — mark a SKU as a kit that includes other SKUs (data + UI +
   estimate behavior). Gated on the parts-DB repository extraction (Stage A of
   [AUDIT_REFACTOR_ROADMAP.md](AUDIT_REFACTOR_ROADMAP.md) §8.1 Step 4) so composability lands on the
   repository seam, not on route-layer logic; owner decisions logged in
   `docs/audit/PARTS_DB_REPOSITORY_SPEC.md` §5.
4. **QB Pass-2 import** *(parallel/feeding)* — reviewed through the Parts Manager grid. Fills the shelves.
5. **Finish the Part Picker** *(then)* — Chunks 8–9 + non-light coverage, against final SKU data.
6. **Phase 4 consumer migration** *(then)* — strip domain fields from `workbook_rules.json`.

**QB go-live** (deploy relay + submit the Intuit questionnaire — see [QUICKBOOKS.md](QUICKBOOKS.md))
is a discrete, externally-gated track. Run it when the owner chooses; it is *not* advanced by the
import grind and must not block it.

**Audit & refactor track (adopted 2026-07-06)**: a codebase-wide audit/refactor runs *interleaved*
with the critical path above — see [AUDIT_REFACTOR_ROADMAP.md](AUDIT_REFACTOR_ROADMAP.md) §8.1 for
the ordered steps. In short: regression pins + import guardrails land *before* the picker cluster;
a parts-DB repository extraction gates kit SKUs (the one place refactor precedes feature); legacy
shim cutover/retirement and the breadth audit are interstitial work between feature turns. It never
reorders this critical path — if the two documents disagree, this file wins and the audit roadmap
gets revised.

---

## 2. Guiding Principles

These are constraints on **how** we move toward the vision. Override them only with stated reason.

- **Domain data has one home.** If a manufacturer or location appears in two files, one of them is wrong. Don't paper over duplication with sync logic — pick a home and update consumers.
- **Persisted records are portable.** No absolute filesystem paths inside JSON records. Store relative-to-workspace paths so a project authored on User A's machine works when User B opens it from a shared folder.
- **Per-record JSON files beat monolithic collection JSONs.** Concurrency-safe, merge-friendly, sync-friendly. New collections should follow this pattern; existing monolithic ones (`agencies.json`, `sales_reps.json`, the 8 config files) are candidates for migration when their next big change lands.
- **Schemas evolve with explicit migrations.** Every schema change carries a version bump and a migration step that runs on read. We do not silently mutate data when a user opens a file.
- **Refactor in small, testable passes.** Each change makes two-similar-things-that-aren't-quite-the-same become one shared concept, and only when the conceptual identity is real. "Similar but different" stays separate.
- **Behavior changes are flagged, never sneaked.** If a UI changes what a user sees or how a build is named, call it out in the commit and the release notes.
- **The workbook is an edge adapter, not the spine** *(revised 2026-07-06, superseding "the workbook input path keeps working through every phase")*. Canonical data is domain/parts_db-shaped end to end; no core consumer (planner, preview, build sheet) may assume workbook-era data shape — the owner has hit real bugs where better parts_db data broke consumers still expecting workbook shape, and each such assumption is a defect, not a compatibility feature. The workbook *import* path is demoted to a best-effort backup adapter confined to `inputs/`: it converts to domain shape at the boundary, is expected to see near-zero use, is kept only while it costs little, and full retirement is on the table. Workbook *export* (workbook-as-renderer) is unaffected. Domain logic authored in the workbook era — rules, naming, placement handling — is ported into domain/planning code via parity proofs: the logic survives, the format dependency doesn't.

---

## 3. Current State (Snapshot)

As of the time this document is being authored:

- **8 consumers depend on `workbook_rules.json`** for domain data: `template_builder.py`, `manifest_editor.js`, `part_types.js`, `placements.js`, `projects/api.js`, `state.js`, plus validation/route plumbing. `excel_reader.py` does **not** — it parses by header position.
- **`workbook_rules.json` is ~3,300 lines, ~95% domain data**: manufacturers, models, per-part locations, colors, quantities, lens types. The other 5% is layout (`template_sections`, `_row` indexes).
- **Colors live only in `workbook_rules.json`.** Nowhere else.
- **Per-part location validity is split-brain**: vehicle_layouts defines what locations exist on each vehicle; workbook_rules defines which of those locations are valid for which part type. They overlap ~38%.
- **Per-record JSON storage exists for**: projects (`workspace/projects/{id}/project.json` — subdirectory layout, intentional), drafts, presets.
- **Monolithic JSON storage exists for**: agencies, sales reps, all 8 config files in `workspace/config/`.
- **Absolute paths get persisted in records**: `ProjectRecord.export_dir`, `BuildUnit.output_path`, `IndividualUnit.output_path`.
- **`paths.py` has one workspace root**, no separation between user-local and shared-team data.
- **The vehicle wizard** today is preset-driven. The build editor exposes "slots" (Forward Warning 1, 2, 3, etc.) that reflect the workbook's row layout, not a natural user mental model.
- **Light color choice** today is one selection from an enumerated combo list (e.g., "Red/White", "Red/Blue/Amber"). Every combination is its own row.
- **Views**: four external views per vehicle in `vehicle_layouts.json`. The structure is already a dictionary keyed by view name, but several UI assumptions still hardcode the four.

---

## 4. The Phased Plan

Phases are ordered by dependency. Phase 0 must come first. Phase 1 (cloud prep) and Phase 2 (cloud go-live) are prioritized so the team can start collaborating before the parts-DB migration begins. Subsequent schema changes (Phases 3–6) then propagate through the team via the cloud's PR review flow — which is great for change management.

Each phase has a goal, an exit condition, and a list of work items. Phases can overlap when their work doesn't touch the same files.

**Status snapshot** (2026-06-17):
- ✅ **Phase 0** — complete. Released as v1.1.3.
- ✅ **Phase 1** — complete. Released as v1.2.0 (per-record agency/sales-rep storage) and v1.2.1 (paths.py scope annotations + audits).
- ✅ **Phase 2 / 2.5** — cloud go-live and hardening shipped (cloud is the source of truth as of v2.2.9+).
- 🟡 **Phase 3** — schema + service + migration landed; **Intelligent Part Picker ~80% built** (Chunks 1–7 done, working for Whelen lights; Chunks 8–9 + non-light coverage remain). The QB Item import is the *foundation* feeding this (see Current Direction above). Full status: `docs/PARTS_DB_AND_PICKER.md`.
  - PR-1/2a/2b (service + schema + migration + Part Manager seed): commits `cbc18d4`, `5f4189b`, `befb52d`, `368c040`, `6b68847`, `7157c13`, `01ada6d`.
  - parts_db.json populated: 5 types · 2 sections · 8 zones · 2 sub-zones · 61 manufacturers · 227 products · 106 part_types · 59 placements; 417+ QB-linked SKUs (Setina, Whelen, Arctic Start; Gamber pilot pending).
  - **Next** (critical path): **Parts Manager revamp** for self-service data review → continue QB Pass-2 import → finish picker Chunks 8–9 + non-light coverage → Phase 4 consumer migration.
- 🟢 **Phase 8 MVP brought forward** (out of order): the read-only tree + edit-modal Part Manager (Settings → Advanced → Part Manager → Database v2). **Being revamped now** into a two-view editor (SKU grid + hierarchy) — see §Phase 8. Inventory/pricing/separate-app questions still deferred to the full Phase 8.

### Phase 0 — Foundation Refactor

**Goal**: clean baseline for everything that follows. Truth up docs, kill silent failures, fix the path-portability problem before any feature work invents new bad patterns on top of it.

**Exit condition**: tests green, the four silent `except Exception: pass` blocks log, persisted paths are workspace-relative, docs reflect actual code.

**Work**:
- Fix stale docs: project storage is `workspace/projects/{id}/project.json` (subdirectory), not flat. Update `CLAUDE.md`, `AGENTS.md`, `docs/PROJECT_WORKFLOW.md`.
- **Audit all silent `except Exception` blocks across persistence and service layers.** Add `logging.exception()` to unexpected catch-alls; keep expected not-found/validation responses quiet. Known sites include `agency_service`, `sales_rep_service`, `project_service`, plus `inputs/project_drafts.py:266` and `inputs/project_entry.py:85` (both silently swallow corruption when iterating directories — broken records vanish from the UI). Don't limit to the originally-counted four.
- **Standardize all file writes through atomic helpers.** `agency_service.py:78`, `sales_rep_service.py:43`, and `preset_service.py:323` currently use direct `Path.write_text` — these can corrupt files if the process is killed mid-write. Route them through `LocalStorageProvider().write_text()` (temp-file + atomic rename), same pattern as `config/store.py`. Doing this in Phase 0 (rather than Phase 1) means the per-record migration in Phase 1 inherits safe writes for free.
- Make persisted output paths portable. **Important nuance**: the existing architecture already separates the local-only absolute root (`app_settings.json.project_output_root` consumed by `inputs/project_dirs.py:resolve_project_output_dir`) from the computed output directory. That separation is correct and stays. What needs to change is the per-record fields that store *resolved* paths:
  - `IndividualUnit.output_path` (set when a build sheet is generated) — migrate to workspace-relative; resolve to absolute at read time via `paths.resolve_output_path(stored_value)`.
  - `BuildUnit.output_path` — same.
  - `ProjectRecord.export_dir` — strongly consider dropping this from the persisted record. Today it's empty in the default case (output dir is computed from `app_settings.project_output_root` + agency + year). A per-project custom output override is better expressed as a local-only setting (e.g., `app_settings.local_project_overrides[project_id]`), not baked into a record that will be shared cross-user via SharePoint.
  - `app_settings.project_output_root` itself stays absolute and is explicitly designated as **local-only, non-synced** in the path classification (see Phase 1).
- Replace `mtime`-based draft ordering in `project_drafts.py` with the explicit `created_at` / `updated_at` fields.
- Extract `send_json(handler, payload, status=200)` to `app/routes/http.py`. Replace the six byte-identical `_json` helpers. Keep `presets._xlsx` local — it's a different MIME concern.
- Move `project_options.json` into `REQUIRED_CONFIG_FILES`; add a validator; route it through `config_routes.GET_ROUTES`. Delete the special-case dispatch in `server.py`.
- Add cross-reference comments in `canvas.js` and `preview_canvas.js` pointing to `domain/geometry.py` as the canonical source for placement math.

### Phase 1 — Cloud-Readiness Prep

**Goal**: the codebase is structurally ready for the hybrid GitHub + SharePoint deployment. No actual cloud calls happen yet; this phase makes the local code shape such that Phase 2 is a thin layer on top.

**Exit condition**: `paths.py` has explicit classification of each path constant as **local-only**, **shared-settings** (will live on GitHub), or **shared-work** (will live on SharePoint). Monolithic collections that will be shared are migrated to per-record JSON. All file writes go through atomic temp+rename. mtime is not load-bearing anywhere.

**Work**:
- Annotate every constant in `paths.py` with intended scope via comments. Don't add new roots yet — when Phase 2 wires up cloud, adding `SETTINGS_DIR` and `SHARED_WORK_DIR` becomes a one-place change.
- Migrate `agencies.json` → `workspace/agencies/{id}.json`. Same for `sales_reps.json`. Each is one PR with read-side compat (load from old monolithic file if new per-record dir is empty; write going forward only to per-record).
- **Add an in-memory cache to `agency_service` and `sales_rep_service`** before or during the per-record split. The live fuzzy-search endpoints (`/api/agencies/search`, `/api/sales-reps/search`) fire every 220ms while the user types. Today's mechanism calls `load_agencies()` → `read_text` + `json.loads` on every keystroke; that's fast (~1-5ms) with one monolithic file, but becomes a real problem if we naïvely split to per-record files (hundreds of `stat` + `open` + `read` per keystroke). The cache pattern: load directory once at startup into a dict keyed by id; invalidate the relevant entry on save/delete. Fuzzy search runs against the in-memory dict, never disk.
- Determine which `workspace/config/*.json` files are "shared settings" (part DB, presets references, vehicle layouts, build rules, color palette, naming rules, workbook template config) vs. "local-only" (app_settings.json, last-build cache). Mark them in the path annotations.
- Audit all `Path.stat().st_mtime` usages. Replace with explicit `created_at`/`updated_at` fields wherever they drive ordering or staleness checks.
- Confirm every persistence layer uses the atomic-write helpers in `storage/local.py`. Any direct `Path.write_text` on a shared collection is a bug.

### Phase 2 — Cloud Go-Live (M365-only for users, GitHub-as-review-backend)

**Goal**: team collaboration is live. Users sign in with their M365 account and never see GitHub. Settings changes flow through PR review on GitHub behind the scenes. Project data syncs to SharePoint. The app auto-checks for updates on launch.

**Exit condition**: a teammate on a fresh install can sign in with their M365 account, see all team projects, edit a preset, have that edit show up as a PR for the owner to review within ~5 minutes, and see a banner if a newer app version is available. The app never asks the user for any non-M365 credential.

**Pre-work completed (2026-05-21)** — all three cloud connections were validated end-to-end before any Phase 2 code was written:
- ✓ Python (MSAL) → Azure AD → Microsoft Graph API → SharePoint read/write (proven via throwaway test script)
- ✓ GitHub Actions → Azure AD service principal → Graph API → SharePoint write (proven via manual `workflow_dispatch` run)
- ✓ Power Automate → SharePoint `/Settings/` trigger → email notification (proven live)

Infrastructure already in place:
- `dtm-shared-settings` repo created (public, classic branch protection on `main`, 1 reviewer required)
- Two Azure AD app registrations: "DTM Vehicle Builder" (delegated, user auth) and "DTM Vehicle Builder CI" (application permissions, `Sites.ReadWrite.All`, admin consent granted)
- SharePoint document library "DTM Vehicle Builder" on the DTM Fleet site (`/sites/DTMOperations`) with all seven folders created: `/Settings/`, `/PendingChanges/`, `/Projects/`, `/Drafts/`, `/Exports/`, `/Assets/`, `/Releases/`
- GitHub Actions secrets added to `dtm-shared-settings`: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `SHAREPOINT_SITE_ID`, `SHAREPOINT_DRIVE_ID`
- Power Automate Flow A (settings update → email) live and tested

**Architecture overview**:

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER'S APP                                │
│  M365 OAuth → Microsoft Graph API token (cached in OS keychain)  │
└─────────────────────────────────────────────────────────────────┘
        │ All app reads/writes go through Graph API
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                  SHAREPOINT (single backend for app)             │
│   /Settings/         ← READ-ONLY for app (written by CI)         │
│   /PendingChanges/   ← WRITE by app (proposals awaiting review)  │
│   /Projects/         ← READ+WRITE (per-record JSON, conflict-safe)│
│   /Drafts/           ← READ+WRITE                                │
│   /Exports/          ← READ+WRITE (PPTX/PDF)                     │
│   /Assets/           ← READ+WRITE (vehicle/equipment images)     │
│   /Releases/         ← READ-ONLY for app (written by CI)         │
└─────────────────────────────────────────────────────────────────┘
        ▲                              │
        │ (3) push merged settings,    │ (1) pickup pending changes
        │     publish installers       ▼     (2) open PRs in settings repo
┌─────────────────────────────────────────────────────────────────┐
│         GITHUB (review backend — owner-facing only)              │
│   dtm-shared-settings repo   ← source of truth for settings      │
│   dtm-vehicle-builder repo   ← app code + CI (DMG/EXE builds)    │
│                                                                  │
│   GitHub Actions (free, code-defined glue):                      │
│    (1) pickup-pending-changes.yml   — cron every 5 min           │
│    (2) publish-settings-on-merge.yml — on PR merge               │
│    (3) build-and-publish-release.yml — on push to main of app    │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  POWER AUTOMATE (Standard, included with M365 — notifications)   │
│   Flow A: new file in /Settings/  → send email                   │
│   Flow B: new file in /Releases/  → send email                   │
└─────────────────────────────────────────────────────────────────┘
```

**Why this and not other architectures**:
- *Why not GitHub-direct from app?* App users don't have GitHub accounts. Embedding a shared GitHub PAT in the app means rotating secrets and exposes a credential. M365 OAuth gives per-user attribution and existing identity.
- *Why not OS-level SharePoint sync?* Unreliable. We've experienced staleness and out-of-date issues. Microsoft Graph API is the reliable path.
- *Why GitHub Actions and not Power Automate for the sync glue?* HTTP-to-GitHub is a premium Power Automate connector (~$15/user/mo). GitHub Actions does the same thing for free, with the workflow files version-controlled alongside the code.
- *Why Power Automate for notifications?* SharePoint trigger + Office 365 Outlook action are both standard connectors (included with M365). The flows are simple, visual, and don't need to live in code. (Teams is not in use; email is the notification channel.)

**This is the first set of adapters, not the backbone.** Per §6 (Architectural Boundaries), Phase 2 builds these capabilities behind four interfaces — `SharedStorageProvider`, `IdentityProvider`, `ChangeProposalGateway`, `NotificationGateway` — with the M365/SharePoint/GitHub/Power Automate implementations as the *first* adapter set. The app's services depend on the interfaces, not on Graph API directly. This makes future variants (customer-facing web product, external sale to other upfitters) a matter of writing new adapter classes, not rewriting the app. See §6 for the rationale and the cost/benefit of doing this up-front.

**Work — 2.0: Interface definitions (do this first)**:
- **Extend the existing `storage.base.StorageProvider`** rather than inventing a new `SharedStorageProvider`. It already has `read_text`, `write_text`, `delete`, `list_files`. Add to the abstract interface:
  - `read_bytes(path: str) -> bytes` (for PPTX/PDF/installer downloads — `LocalStorageProvider` already has `write_bytes` as a concrete method; pull it into the interface and add the read counterpart).
  - Existing `list_files` covers folder listing; no need for separate `list_folder`.
  - `file_exists` is unnecessary — callers either use `list_files` results or try/except. Don't add it.
- Define the three remaining interfaces in `app/adapters/interfaces.py` (or split into one file per interface). Each is a small Python `Protocol` or `ABC`:
  - `IdentityProvider`: `signin()`, `current_user() -> UserIdentity`, `signout()`, `is_signed_in()`.
  - `ChangeProposalGateway`: `submit_proposal(target_file, new_content, summary, user)`, `list_my_proposals(user) -> list[ProposalStatus]`.
  - `NotificationGateway`: `notify_settings_updated(filename, summary)`, `notify_release_published(version, platform)`. No-op implementations are valid — variants that don't have notifications use `NoOpNotifier`.
- Add `app/adapters/wiring.py` — a single module that imports the concrete adapters and constructs the right set for this build. Internal-team build = `SharePointGraphProvider` (implementing extended `StorageProvider`) + `M365IdentityProvider` + `SharePointPendingChangesGateway` + `PowerAutomateNotifier`. The wiring choice is build-time, not runtime user config.
- All services in Phase 2 (2a, 2b, 2c, 2d, 2e) accept adapter instances via constructor injection. They never import a concrete adapter class.

**Work — 2a: SharePoint backend + Graph API client (first adapter set)**:
- Set up an Azure AD app registration (free, no Azure compute charges). Two app registrations actually:
  - **App-user registration** — used by each user's app instance. Delegated permissions: `Files.ReadWrite` scoped to a specific SharePoint site. User signs in with their M365 account.
  - **Service-principal registration** — used by GitHub Actions. **Auth via OIDC federated credentials, not client secrets** (GitHub→Azure passwordless authentication is now the recommended path; avoids rotating long-lived secrets). Client secret only as fallback if OIDC setup blocks. Permissions: prefer **`Sites.Selected`** scoped only to the DTM SharePoint site over `Sites.ReadWrite.All` — least-privilege review with tenant admin before implementation.
- Create the SharePoint document library with the structure: `/Settings/`, `/PendingChanges/`, `/Projects/`, `/Drafts/`, `/Exports/`, `/Assets/`, `/Releases/`.
- Build `app/services/sharepoint_client.py`:
  - `signin_with_m365()` — OAuth flow on first launch. Token cached in OS keychain (macOS Keychain / Windows Credential Manager).
  - Generic file CRUD methods that wrap Graph API: `read_file(path)`, `write_file(path, content)`, `list_folder(path)`, `delete_file(path)`.
- Build `app/services/shared_settings_service.py` (consumes SharePoint client):
  - `read_settings(filename)` — reads from `/Settings/`. Caches locally so the app works briefly offline.
  - `propose_settings_change(target_filename, new_content, summary, user_name)` — writes a JSON to `/PendingChanges/{uuid}.json` with the proposed change, summary, user name, and timestamp. GitHub Actions picks it up.
  - `list_my_pending_proposals(user_name)` — reads `/PendingChanges/` and filters to the current user's proposals so they can see what's awaiting review.
- Build `app/services/shared_work_service.py`:
  - `list_projects()`, `read_project(id)`, `save_project(record)`, `delete_project(id)` — same shape as today's local project service but backed by Graph API.
  - Similarly for drafts and exports.
  - Local cache layer so opening a project doesn't hit the network on every keystroke.
- Migration of existing local data: a one-time "Migrate to cloud" button in Settings that uploads the user's current `workspace/projects/` and `workspace/drafts/` to SharePoint.

**Work — 2b: GitHub settings repo + Actions**:
- Create `dtm-shared-settings` as a **public** repo. Seed it with current `resources/config/*.json` (the bundled defaults). Public because: (a) the settings files are not sensitive — secrets live in GitHub Secrets and Azure AD, never in these JSON files; (b) GitHub Free does not enforce branch protection rules on private repos (requires GitHub Pro/Team); (c) a public config repo is standard practice and makes settings transparently reviewable by the team.
- Enable branch protection on `main`: require pull request review (1 reviewer = you), require linear history, no direct pushes to main. **Use classic branch protection rules, not Rulesets** — Rulesets on private repos also require GitHub Team and show the same enforcement warning.
- Three GitHub Actions workflows in this repo:
  - **`pickup-pending-changes.yml`** — `schedule: cron '*/5 * * * *'`. Uses the service-principal credential to call Graph API, lists files in `/PendingChanges/`, for each file:
    1. Reads the proposal JSON
    2. Creates a feature branch `change/{user-slug}/{timestamp}` in this repo
    3. Writes the proposed new file content to the target settings file on that branch
    4. Opens a PR titled `[{user_name}] {summary}` with the proposal's summary as body
    5. Deletes the source file from `/PendingChanges/` in SharePoint
  - **`publish-settings-on-merge.yml`** — `on: pull_request: types: [closed]`, condition `merged == true`. Uses Graph API to overwrite the corresponding file in `/Settings/` on SharePoint with the merged version from `main`.
  - **`build-and-publish-release.yml`** — extends existing CI. After building DMG + EXE, uploads them to `/Releases/` on SharePoint via Graph API.
- Settings UI in the app changes its save semantics: instead of writing directly, it opens a "Propose change" modal showing the diff, with a summary field (defaults to a system-generated description; user can edit) and an optional comment. Confirms → `propose_settings_change()` → success toast: "Submitted for review. You'll see this update once approved (usually within a few minutes after merge)."

**Work — 2c: App auto-update via SharePoint**:
- Add `app/services/update_check_service.py`. On launch, calls `sharepoint_client.list_folder("/Releases/")`, finds the highest-version installer for the current platform (DMG for Mac, EXE for Windows), compares against the embedded app version.
- If newer, the app shows a top-banner: "Update available — vX.Y.Z" with a "Download" button.
- Click → either downloads the installer via Graph API and reveals it in Finder/Explorer, or opens the SharePoint file URL in the default browser (M365 auth carries over). User installs manually.
- Banner is dismissible per-version (don't pester the user every launch about the same update).

**Work — 2d: Power Automate notifications**:
- **Flow A — Settings update notification** ✓ live and tested (2026-05-21):
  - Trigger: "When a file is created or modified in a folder" → `/Settings/`
  - Action: Office 365 Outlook → "Send an email (V2)"
  - Subject: "DTM Settings Updated: `{file name}`"
  - Body: file name, modified-by, instruction to restart the app.
  - Optional: include the commit message / PR title by also reading from a small metadata file the GitHub Action writes alongside the settings file.
- **Flow B — App release notification** (not yet built):
  - Trigger: "When a file is created in a folder" → `/Releases/`
  - Action: Office 365 Outlook → "Send an email (V2)"
  - Body: "App update available: `{file name}`. Open your app to download, or grab it directly from the Releases folder in SharePoint."
- Both flows use Standard connectors (SharePoint + Office 365 Outlook). No premium needed. Free with M365.

**Work — 2e: paths.py wires up the new roots**:
- `SETTINGS_DIR` resolves to a local cache directory populated by `shared_settings_service.read_settings()`. Cache invalidates on app launch.
- `SHARED_WORK_DIR` resolves to a local cache of the SharePoint library, with write-through to SharePoint on save.
- Local-only paths (`app_settings.json`, etc.) keep their current resolution.

**Online vs offline**:
Online-first is the starting model. Every save calls Graph API; if the network is down, the app queues the save in a local outbox and retries on next launch. The UI shows a "Working offline" badge when the network is unavailable. Full offline-first (long-lived local cache + background sync) is a polish-later upgrade.

**What gets reviewed**:
- Part DB changes (`parts_db.json` once it exists; until then, the relevant fields in `workbook_rules.json` / `parts_library.json` / `vehicle_layouts.json`)
- Preset changes (the file in `presets/{id}.json`)
- Placement / vehicle layout changes (`vehicle_layouts.json`)
- Build rules changes (`build_rules.json`)
- Color palette and naming rules (once they exist in `parts_db.json`)
- Workbook template config (`workbook_rules.json` — its layout fields)

**What doesn't get reviewed**:
- Project records and drafts (SharePoint `/Projects/`, `/Drafts/`, last-writer-wins per record)
- Generated outputs (SharePoint `/Exports/`, immutable after generation)
- User-uploaded assets (SharePoint `/Assets/`)
- Local-only files (`app_settings.json`)

**Honest tradeoffs of this architecture**:
- **~5-minute delay between user proposing a change and the PR appearing in GitHub.** Acceptable for a review workflow; can be reduced later with a SharePoint webhook → GitHub Actions `workflow_dispatch` if it becomes annoying.
- **Service principal credential** in GitHub Secrets needs rotation every ~6 months (Azure AD client secret expiry). Calendar reminder.
- **App users must have M365 accounts** with access to the SharePoint site. Already true for your team.
- **First-launch M365 sign-in adds a step** users don't have today. Worth it for the cleaner auth story.
- **Two PRs touching the same settings file** before either is merged → standard Git merge conflict, resolved at review time on github.com.

**Cost**: Expected $0 marginal *if* the workflows stay within included GitHub Actions quotas (2,000 free min/month for private repos on GitHub Free) and Power Automate flows use only Standard connectors (SharePoint + Teams; no Premium HTTP). Monitor usage; if either creeps past free-tier limits, costs are predictable but no longer zero.

---

#### Phase 2 — Shipped (originally as of v2.2.2; extended through v2.2.13)

Phase 2's exit condition — *"a teammate on a fresh install can sign in with M365, see all team projects, edit a preset, have that edit show up as a PR within ~5 minutes, see an update banner, and never be asked for any non-M365 credential"* — is met. What actually shipped maps to the original sub-phases plus a meaningful pile of extras that surfaced during testing.

**Sub-phases against the spec:**

| Sub-phase | Status | Released in |
|-----------|--------|-------------|
| 2.0 Interface definitions (`StorageProvider`, `IdentityProvider`, `ChangeProposalGateway`, `NotificationGateway`) | ✅ shipped | 1.x (Phase 2 pre-work) |
| 2a SharePoint backend + Graph client + first adapter set | ✅ shipped | 1.x |
| 2b Settings repo + three GitHub Actions workflows (pickup / publish / build-release) | ✅ shipped | 1.x |
| 2c App auto-update via SharePoint `/Releases/` (banner, dismiss, download) | ✅ shipped | 1.3.0 |
| 2d Power Automate Flow A (settings-updated email) | ✅ shipped (Flow B punted — no dependents need it) | 1.x |
| 2e periodic sync wires `WORKSPACE_*_DIR` to cloud (60s loop, eTags, lazy boot) | ✅ shipped | 2.1.x |
| 2-α General/Advanced Settings UI split | ✅ shipped | commit 9cb6689 |
| 2-β Save-becomes-propose cutover (schema v2 with category) | ✅ shipped | 2.0.0 |

**Extras that grew out of Phase 2** (none of these were in the original §Phase 2 spec but all proved necessary):

| Item | Released in | Why it landed |
|------|-------------|----------------|
| Schema v3 (`action: upsert \| delete`) + delete-via-proposal pipeline (pickup `git rm`, publish Graph `DELETE`) | 2.2.0 | Phase 2 close — closes the asymmetric save-works-but-delete-doesn't gap for per-record entities |
| Settings subdir inbound sync (`/Settings/agencies/`, `/sales_reps/`, `/presets/`) with deletion propagation via per-cache eTag manifest | 2.2.0 | Per-record entities had outbound proposals but no return-path sync — teammates' agency changes never reached other devices |
| Cloud-is-source-of-truth reconciliation for projects + drafts (state-tracked deletion propagation, first-launch upload of legacy local-only files) | 2.1.5 | Pull-only sync left every device with subtly different data; the manifest pattern converges them |
| eTag-aware sync (extends `StorageProvider` with `list_files_with_metadata`, `FileMetadata` dataclass) — skips content fetches when cloud copy is provably unchanged | 2.1.5 | First implementation fetched every file's content every cycle; sync took minutes for non-trivial data sets. After eTag short-circuit, typical sync is ~3 list calls and zero reads |
| Cloud connection indicator (header chip, profile photo via Graph `/me/photo`, modal with Switch User / Force Sync / Sign In) | 2.0.3, 2.2.1 | No visible signal whether cloud mode was working without saving and watching for the proposal toast |
| Switch User actually switches accounts (`prompt=select_account` plumbed through MSAL when force_account_picker=True) | 2.2.1 | Modal's Switch User silently reused the browser's existing Microsoft session — clicking it appeared to do nothing |
| Bundled `cloud_config.json` in `resources/default_data/` so first-launch on a fresh install seeds it into the workspace | 2.0.1 | Without this, every teammate had to manually drop a config file before cloud mode would engage |
| Boot-time `ensure_signed_in_for_cloud()` so a fresh install with no cached MSAL token actually triggers OAuth (was silently falling through to local mode) | 2.0.2 | Discovered when the first Windows install never engaged cloud despite having `cloud_config.json` |
| Inno installer `[InstallDelete]` for `_internal/` directory + uninstaller-dir-poll in `InitializeSetup()` | 2.0.x, 2.1.1 | Over-installs left stale `dtm_buildsheet-{old-version}.dist-info` alongside the new one; `importlib.metadata` returned the wrong version and the update banner kept pestering about a version the user just installed |
| Sync lock + `_data_version` counter so UI auto-refreshes project lists on cloud changes | 2.1.5 | Force Sync said "done" while the periodic loop was still working (race condition); UI showed stale lists until app restart |
| Per-record entity (agencies / sales-reps / presets) cloud mirror integration (`save_via_proposal` from each service handler) | 2.0.0 | Original Phase 2-β spec only covered the eight flat config files |
| Test-isolation guards (`tests/conftest.py` autouse fixture disables cloud + installs local bundle; `PYTEST_CURRENT_TEST` short-circuits in `_cloud_storage` / `save_via_proposal` / `ensure_signed_in_for_cloud`; `DTM_ALLOW_CLOUD_IN_TESTS=1` opt-in) | 2.1.6 | Pytest runs were silently mirroring fixtures to the real SharePoint via transitive `save_project` / `save_via_proposal` calls — Test PD agencies, sales reps, presets, and ~700 projects/drafts ended up on production |
| Cleanup scripts: `scripts/cleanup_test_projects.py` (local + cloud delete with conservative pattern matchers); `scripts/cleanup_sharepoint_test_data.py` (direct Graph DELETE for /Settings/agencies/ etc.) | 2.1.x | One-shot recovery from the test-pollution incident |
| Lazy cloud bootstrap — sign-in + initial sync moved off the main thread into the periodic loop's first iteration | 2.1.x | First launch was blocking on OAuth before the webview window appeared |
| Cron-throttle workaround: pickup workflow runs `gh workflow run publish-settings-on-merge.yml` after successful auto-merge | 1.x (settings repo PR #35) | GitHub Actions deprioritizes scheduled workflows on low-traffic public repos to 2–5 hour cadence; auto-merged general PRs also don't trigger `publish-settings-on-merge` because `GITHUB_TOKEN`-initiated events don't fire other workflows (the dispatch route does) |
| Auto-upload PPTX exports to a separate company SharePoint library (`Company Files / Vehicle Builder Projects / {agency} / {year} /`) via Graph upload sessions for files >4 MiB | 2.2.1 | Build sheets need to be browsable by the whole company via normal SharePoint, not just the app's users |
| Persistent outbound retry queue (`workspace/.pending_outbound/{proposals,exports}/`) + yellow warning toast + modal pending count | 2.2.2 | Offline saves silently lost their cloud-side step; users had to manually re-save when network came back. Queue drains on every sync iteration + at boot |

**Deliberately deferred from Phase 2** (architectural decisions, not bugs):

- **Power Automate Flow B (release-published email)**: Has no dependents — release notifications were nice-to-have, not blocking. Existing `/Releases/` sync handles the actual update propagation.
- **SharePoint webhook → workflow_dispatch for pickup**: Would speed settings PR creation from "2–5 hour cron" to "~10 seconds". Requires Power Automate Premium ($15/user/mo) for the HTTP connector, OR an Office Scripts workaround. Punted — settings change infrequently enough that the cron cadence is acceptable, and projects/drafts (the frequent path) don't go through GitHub at all.
- **Code signing certificate** ($300+/year for EV): Reduces Windows SmartScreen friction. Owner opted to skip the cost; silent auto-update (next section) reduces SmartScreen exposure organically over time.
- **Mac silent auto-update**: DMG auto-mount + `.app` replacement is a different pattern (Sparkle framework or manual mount/copy). Mac users keep the existing "download + reveal in Finder" flow until/unless we revisit.

**End-to-end latency achieved** (vs. Phase 2 spec's "~5 minutes"):

- Project edits: ~60s typical, hard ceiling ~120s (direct SharePoint mirror, no GitHub round-trip)
- Draft edits: ~60s typical
- Settings edits (general/auto-merge): ~3 minutes worst case (cron + workflow + publish + 60s sync poll)
- Settings edits (advanced/review): cron-bound (the manual merge step is owner-paced anyway)
- Project deletes / draft deletes / general-entity deletes: same as their save counterparts

#### Phase 2.5 — Cloud + Distribution Hardening (v2.2.3 → v2.2.13)

Phase 2 was declared "shipped" at v2.2.2 but the next 11 patch releases tightened the rough edges that surfaced when teammates actually used it day-to-day. Documenting these here because several change the assumptions Phases 3+ are written against — anyone reading this roadmap from scratch should not assume the v2.2.2 architecture.

| Item | Released in | What changed structurally |
|------|-------------|---------------------------|
| **Silent auto-update (Windows)** — kind-cuddling-canyon plan implemented in full. `consume_queued_installer` at boot + `download_pending_update_if_any` on the 60s sync loop + `pending_update` field in cloud-status + `POST /api/update/install-now` for the Restart button | 2.2.3 | Releases now reach users at sync cadence, not click-through cadence. |
| **Silent auto-update (Mac)** — DMG mount + .app copy + xattr quarantine strip + relaunch via detached shell script | 2.2.11 | Mac is no longer a manual-download outlier. The "platform_unsupported" branch now only applies to Linux. |
| **Install-loop fix** (the v2.2.4 incident) — `consume_queued_installer` version-checks before relaunching the installer; stale installers self-delete | 2.2.6 | Boot-time consume can never re-run the same installer that produced the current version. Without this, every restart re-launched the queued installer indefinitely. |
| **`update_state` single source of truth** — `up_to_date / downloading / ready / available / platform_unsupported` returned by cloud-status; banner + cloud modal both drive off it | 2.2.6, 2.2.13 | UI never shows a stale "Download" banner while the background sync is already fetching the same DMG/EXE. |
| **Direct SP write on save** (alongside `save_via_proposal`) | 2.2.6 (delete), 2.2.9 (save) | The dtm-shared-settings publish-workflow is cron-throttled by GitHub on low-traffic repos; per-record entities (agencies, sales reps, presets) saved on one device routinely never reached SharePoint. Direct mirror via `save_setting_to_cloud_in_background` / `delete_setting_from_cloud` makes SharePoint authoritative within seconds. Proposals still fire for the repo audit record, but the canonical state lives on SP. |
| **PendingChanges auto-clean** — 12-hour age cutoff on `/PendingChanges/` runs every sync, capped at 50/cycle | 2.2.13 | Without it the folder grew forever because the pickup workflow reads but doesn't delete. |
| **Bundled-preset concept removed** — `blank_custom` hardcoded in `preset_service`; all other presets sync from `/Settings/presets/` | 2.2.10 | The "delete preset locally → it comes back labelled 'bundled'" UX bug. Resources/presets/ is now strictly a dev-mode workspace mirror; `resources/presets/*.json` is gitignored. |
| **cloud_config key auto-merge** on every launch | 2.2.2 (in this hardening pass) | Pre-2.2.1 installs were silently missing `exports_library_name` etc. because the seeder only ran when the file didn't exist. Now new top-level keys backfill into the existing workspace copy. |
| **Outbound-queue junk guard** — `enqueue_proposal` and the drain step reject empty `{}` upserts; cleanup script sweeps `/PendingChanges/` for the same pattern | 2.2.9, 2.2.12 | The "abc.json agency keeps reappearing" bug. Root cause: a `cloud_on` test fixture using `DTM_ALLOW_CLOUD_IN_TESTS=1` called `enqueue_proposal(AppPaths(), ...)` against the REAL workspace, dropping `agencies/abc.json` payloads with content `{"name":"x"}` that the dev app would later submit to SP. Wiring now refuses to enqueue from pytest, period. |
| **Sync-state UX** — periodic syncs are quiet (no spinner during check), but a 3-second spinner flash fires when transfers actually land; modal shows a `🔄 N agencies updated · M projects uploaded · ...` change list for 10s | 2.2.10, 2.2.12 | Pre-2.2.10 the chip spun for every 60s check-and-find-nothing cycle, training users to ignore it. Post-2.2.10 quiet meant transfers were invisible. Current design surfaces only signal, not noise. |
| **Settings tab post-sync refresh** — agencies / sales reps / presets tabs re-fetch after `data_version` bumps | 2.2.12 | A teammate's deletion landed locally but the rendered list stayed stale until the user restarted. `_refreshVisibleDataAfterSync` now drives `window.refreshAgenciesTab` / `refreshSalesRepsTab` / `refreshPresetsTab` along with the projects refresh. |
| **Project + draft mirrors are async** | 2.2.6 | `save_project` / `save_draft` no longer block the HTTP response on a Graph roundtrip. Cut ~1-2s off every generate (the UI saved the project right after) and every draft edit. `sync_work_data` is the safety net for any mirror that failed silently. |
| **"Author/timestamp on builds"** — `last_rendered_by`, `last_exported_at`, `last_exported_by` per-IndividualUnit / BuildUnit; rendered as `📊 Seth · 3h ago · 📄 Alice · 2d ago` per card | 2.2.6 | Teammates can see what's been built and by whom without opening the file. Synced via the project record. |
| **UX rewrite: Generate button removed** — `[Edit Build] [📊 Preview / Edit in PowerPoint] [📄 Export PDF] [📑 View PDF] [📂 Show in folder]`. Smart auto-regen if source changed; modal asks to discard vs keep manual PowerPoint edits | 2.2.6 | Generate-then-Export was a two-step ritual that confused users. Both buttons now produce the right artifact on demand. |
| **Show-in-folder** — Graph-resolved drive `webUrl` (Windows browser path was 404'ing) + targeted OneDrive mount probe (no per-library TCC prompts on Mac) | 2.2.6 | Was either wrong URL or many permission prompts. |

**Cumulative impact**:
- Cloud is now strictly source of truth for per-record entities (agencies / sales reps / presets / projects / drafts). The dtm-shared-settings GitHub repo holds the audit trail, not the live data.
- Auto-update is fully unattended on both Windows and Mac.
- The "save on one device, see it on another" latency is bounded by the 60s sync interval, not the GitHub Actions cron throttle.
- The dev workspace and the test suite no longer pollute production SharePoint.

**Still loose** (called out so Phase 3+ planning doesn't trip on them):
- **dtm-shared-settings repo cleanup** — 5 old bundled preset files (`patrol_piu_standard.json`, the Saint Cloud pair, Stearns, Sartell) still sit in `resources/config/presets/`. Functionally dead because the publish workflow's bulk path is no longer the canonical source, but git-rm'ing them is the cleanest end state. Not blocking.
- **Real-customer agency dedup** — Stearns / St. Cloud / Sartell each have ~11 duplicate records on SP from before direct save. Needs a UI "merge duplicates" tool (proposed but not built). Customer data, not pollution — left untouched.
- **Code signing certificate** — still opted out. Silent auto-update reduces SmartScreen exposure but the very first install still hits the unsigned-EXE warning.
- **Power Automate Flow B** (release-published email) — still deferred. No dependents.
- **SharePoint webhook → workflow_dispatch** for instant settings PR creation — still deferred. Cron cadence is acceptable.
- **dtm-shared-settings publish workflow** still doesn't auto-clean `/PendingChanges/`. Our 12-hour sweep covers it from the app side, but if anyone ever rebuilds that workflow, deleting the consumed proposal would be cleaner.

---

### Phase 3 — `parts_db.json` (Schema, Migration, Intelligent Part Picker)

**Current status (2026-06-17)** — read this first if you're picking up Phase 3 work:

- ✅ `domain/parts_db_models.py` — 13 dataclasses.
- ✅ `app/services/parts_db_service.py` — 23 typed queries + 3-tier fallback.
- ✅ `app/routes/parts_db.py` — 13 REST endpoints under `/api/parts-db/*`.
- ✅ `config/schemas.py::_validate_parts_db` — top-level validation.
- ✅ `tools/migrate_workbook_to_parts_db.py` — one-shot migration script.
- ✅ `parts_db.json` seeded (5 types · 2 sections · 8 zones · 2 sub-zones · 61 manufacturers · 227 products · 106 part_types · 59 placements). 417 QB-linked SKUs.
- ✅ Part Manager UI (`ui/js/settings/part_manager.js`) — admin read-only tree browser.
- 🟢 **Intelligent Part Picker — ~80% built.** Chunks 1–7 done and working for Whelen lights (data foundation, rewired modal, picker shell, smart nav, products grid, color configurator, SKU resolver/translation). Remaining: Chunk 8 (search), Chunk 9 (polish + remove the flat modal), and non-light/no-color coverage. Full design + chunk status: `docs/PARTS_DB_AND_PICKER.md`. (The old "Chunk 5 JS bug" was a server-side `AttributeError`, fixed.)

**Goal**: `parts_db.json` is the authoritative data source for the build flow. The QB-linked part catalog is visible and usable when adding parts to builds.

**Exit condition**: A user clicks "Add Part" and gets an intelligent picker — not a flat form. They can browse by hierarchy, search by SKU/name, see prices and QB linkage, configure colors for multi-lighthead placements, and have their selection resolved into correct PartInput records.

**Why this comes after the cloud go-live**: the schema migration is large enough to warrant team-wide review and visibility before it lands. With the cloud already live, the parts_db.json bootstrap goes through a normal PR — everyone sees it land, the owner reviews it carefully, and any subsequent additions take the same review path.

**Work**:
- Lock the schema (see §7). Adjust if needed before writing the migration script.
- Write `tools/migrate_workbook_to_parts_db.py` — a one-shot script. Reads `workbook_rules.json` + `parts_library.json` + `vehicle_layouts.json` and emits `parts_db.json`. Run it locally; review the diff manually; open a PR with the result. The script is throwaway after that.
- Add `app/services/parts_db_service.py` with typed queries:
  - `list_parts_by_category(category) -> list[Part]`
  - `list_manufacturers_for_part(part_id) -> list[Manufacturer]`
  - `list_models_for_part(part_id) -> list[Model]`
  - `list_compatible_locations(part_id, vehicle_type) -> list[Location]`
  - `list_compatible_colors(part_id) -> list[Color]`
  - `bracket_requirement(part_id) -> BracketRequirement | None`
  - `list_compatible_brackets(part_id, location) -> list[Part]` (brackets are parts too)
- Add a thin REST endpoint set (`/api/parts-db/*`) for the frontend, or extend manifest-editor bootstrap to include the merged data.
- **Do not** delete anything from `workbook_rules.json` yet. Consumers keep reading the old structure as fallback until Phase 4 swaps them over.

### Phase 4 — Migrate Remaining Consumers; Workbook Template Becomes a Consumer

**Goal**: every consumer of domain data reads from `parts_db.json`. `workbook_rules.json` is stripped to layout-only (`template_sections` + `_row`).

**Note**: Consumer #1 (`manifest_editor.js`) is being replaced by the Intelligent Part Picker (Phase 3, Chunks 2-9). The Part Picker reads from `parts_db.json` natively. The flat modal is removed in the final chunk. The remaining 5 consumers follow the original plan.

**Exit condition**: removing `manufacturer`/`models`/`locations`/`colors`/`quantities`/`lens` fields from `workbook_rules.json.part_rules` does not break the app or the regenerated template. The workbook export still produces a fully-populated blank template with all current dropdowns, but pulling from `parts_db.json`.

**Work**:
- One PR per consumer. Order matters — start with the leaves, end with `template_builder.py`. Consumer #1 is handled by the Part Picker (Phase 3):
  1. ~~`manifest_editor.js`~~ — replaced by Intelligent Part Picker (Phase 3). Already reads from parts_db.
  2. `projects/api.js` — switch lighting-brand derivation to query `parts_db_service`.
  3. `state.js` — drop the workbook-rules fetch for domain data; keep it only for `template_sections`.
  4. `part_types.js` — when adding a new part type, propose a PR adding it to `parts_db.json`. The new part appears in both the manifest editor and the regenerated workbook template automatically once merged.
  5. `placements.js` — when adding/removing per-part locations, propose a PR to `parts_db.json`.
  6. `template_builder.py` — read part dropdowns from `parts_db_service` instead of `workbook_rules.part_rules`. Still reads `template_sections` for row order.
- After all six are flipped, run the regenerated workbook template through a manual diff against a pre-migration version. Confirm dropdowns match. Then strip the now-unused fields from `workbook_rules.json` and bump its schema version.
- **Add `parts_db.json` to `TEMPLATE_REGEN_FILES`** in `config_service.py:9-14`. Today the set is `{"part_catalog.json", "vehicle_layouts.json", "parts_library.json", "workbook_rules.json"}` — without this line, edits to `parts_db.json` won't trigger the background Excel template rebuild.
- **Delete hardcoded brand fallbacks** in `ui/js/projects/detail_edit.js` (lines 81-84: bumper_brands and cage_brands fallback to `["SETINA", "WESTIN", "GO RHINO", "PRO-GARD"]` etc.). After parts_db is the source, the data is always available; fallbacks are clutter. Also simplify `_ptLightingBrandsFromConfig` in `projects/api.js:29-49` — it currently cross-references catalog + workbook_rules; after migration it's a direct parts_db query.
- **Critical invariant** during this phase: any newly-added part type in the UI must be exportable to the workbook template the next time it regenerates. The workbook should never be "missing" a part the UI knows about.

### Phase 5 — Light Model Overhaul (Colors + Power Outputs + Two-Tier Naming)

**Goal**: replace enumerated color combos with a small color palette + derivation rules. Track power outputs as a data field per model. Split light naming into two tiers: a **part name** (model + colors) and a **role name** (derived from location zone and color pattern).

**Exit condition**: A user adding a light picks 1–3 colors from a palette. The app determines the graphic asset, the part name (e.g., "ION Blue/White"), and the role name (e.g., "Forward Warning" or "Front Side Scene") from the part model, color set, and location zone. Combo enumeration is gone from configs and UI. **Rules in `build_rules.json` continue to evaluate correctly without modification.**

**CRITICAL design constraint — name stability** (this almost broke the roadmap):

Today `rules/engine.py:37-39` normalizes part names with `_norm(value) = value.strip().upper()` and matches rules by exact-name string comparison (`engine.py:61`: `key = _norm(part.name); included_names.add(key)`). The rule file `build_rules.json` references parts by display name string ("Forward Warning 1", "2-Lamp Tracer", etc.). `excel_reader.py:138` reads the Part column from uploaded workbooks verbatim into `PartInput.name`. The entire validation chain — workbook import, draft persistence, rule evaluation — currently keys off this one `part.name` field.

If Phase 5 lets the dynamic "ION Blue/White" become the value in `part.name`, **every rule in `build_rules.json` breaks instantly** and old workbooks fail to validate. That's not acceptable.

**The rule for Phase 5**: do not change the semantics of `PartInput.name` / `DraftPart.name` / however the planner-facing identifier is currently spelled. Instead, **add new fields** alongside it:

- `part.name` (existing, stable) — the role+type label as it appears today: "Forward Warning 1", "Push Bumper", "5-Lamp Tracer", etc. Rules engine continues to match on this. Workbook reader continues to populate this from the Part column.
- `part.part_id` (new) — foreign key into `parts_db.json.parts`. Stable identifier, never changes.
- `part.model_id` (new) — foreign key into `parts_db.parts.{part_id}.models`. Identifies the specific model variant.
- `part.colors` (new) — `["red", "white"]` etc., for lights. Stored on the placement, not the model.
- `part.display_name` (new) — derived presentation string, e.g., "ION Blue/White" for lights. Used in the parts picker UI and the inventory list. Never used for rule matching.

The new wizard (Phase 7) populates all of these when adding a part; the workbook import path (`excel_reader.py`) populates `name` from the workbook and leaves `part_id` / `model_id` unset for now, with a separate lookup-by-name layer to enrich legacy imports going forward.

**This decision keeps backward compatibility intact and lets Phase 5 land without rewriting the rule engine in the same PR.** A future phase can migrate rules from name-keyed to id-keyed; for now, names stay stable.

**Work**:
- **Color palette in `parts_db.json`**: red, blue, white, amber, green, purple. Each with hex, naming token (R/B/W/A/G/P), and display label.
- **Per-model fields in `parts_db.parts.{id}.models[]`**: `supported_colors: ["red", "blue", "white", "amber"]` and `power_outputs: int`. Color count derived from selection.
- **Graphic asset resolution**: introduce `app/services/light_asset_service.py`. Given `(model_id, selected_colors)`, returns the asset key. Lookup table is data-driven (`parts_db.parts.{id}.color_asset_map`) so new combinations don't need code changes.
- **Domain model additions**: extend `PartInput` / `DraftPart` (or whichever dataclasses persist parts on a draft) with the four new fields (`part_id`, `model_id`, `colors`, `display_name`). `name` stays as it is.
- **Two-tier naming** (lives in `parts_db.naming_rules`):
  - **`display_name`** (the new field): `{model_friendly_name} {colors_joined_by_slash}` → e.g., "ION Blue/White". Used in the parts picker UI and inventory lists.
  - **`name`** (the existing field, used by rules engine): derived from location zone + color pattern, equivalent to today's role labels:
    - Colors = `["white"]` only → scene light prefix
    - Colors include any non-white → warning light prefix
    - Location zone determines the prefix root (`primary_front` → "Forward", `front_corner` → "Front Corner", etc.)
    - Sequence number appended within the zone (e.g., "Forward Warning 1", "Forward Warning 2")
  - This derivation must produce the same labels the workbook uses today, so existing rules continue to match. Validate against `build_rules.json` after migration.
- **Migration**: read existing draft data, convert old combo selections (e.g., color string "Red/White") to the new `colors: ["red", "white"]` array. Populate `display_name` from existing model + new colors. **Leave `name` field unchanged** in the migration — it's already correct.
- **UI work**: replace the color combo dropdown with a 1–3 chip picker. Live preview updates as colors are selected. Show both `display_name` (parts picker) and `name` (manifest editor / role label) in the UI.

**Future sub-phase** (not in Phase 5 itself): migrate `build_rules.json` to reference `part_id` instead of `name` strings. This unlocks renaming workflows and removes the name-stability requirement. Schedule when it becomes valuable; not a blocker for Phase 5.

### Phase 6 — View Extensibility

**Goal**: nothing in the codebase assumes "exactly four views" or "external only." Adding a fifth view (e.g., interior) is a `vehicle_layouts.json` edit, not a code change.

**Exit condition**: a new view added to `vehicle_layouts.json` appears in the preview canvas, the placement settings UI, and the rendered PowerPoint without code modifications.

**Work**:
- Audit JS for hardcoded view names or view counts. Likely candidates: `canvas.js`, `preview_canvas.js`, settings UI for placements, the PPT renderer.
- Make the preview canvas a view-switcher: tabs or a dropdown driven by the vehicle's view list.
- Make `render_ppt.py` iterate the vehicle's view collection rather than hardcoded names. Per-view slide layout is config-driven — a slide template keyed by view name with a default fallback.
- Add `view_kind: "exterior" | "interior" | "top_down" | "console"` to each view in `vehicle_layouts.json`. Some part categories may filter by view_kind (e.g., interior-only equipment).

### Phase 6.5 — Interior Light Bar Enhancements

Captured from owner feedback during the Whelen catalog + accessories work (2026-06).

**Two-piece front interior light bar.** Front interior light bars are physically two
pieces (driver + passenger). The builder should let the user choose **one, the other,
or both** — and when only one, **which side** it mounts on. Today a front interior bar
is a single placement; this needs the placement/picker to model the left/right split and
the preview/PPT to render only the chosen side(s).

**Auto-populated lighthead rendering for interior bars.** Replace the static front/rear
interior-light-bar image assets with an **auto-generated group of small lightheads** —
the same mechanism used for Tracers, just much smaller. This makes the bar's **colors
visible** in the preview and lets the renderer draw **one side or the other** (ties into
the two-piece capability above). Driven by the bar's selected color config rather than a
fixed image.

*Related fix already shipped:* the `front_interior_light_bar` / `rear_interior_light_bar`
part_types had the ambiguous shared label "Interior Light Bar", which broke catalog +
location-rule matching (interior bars couldn't be placed). Labels are now
"Front Interior Light Bar" / "Rear Interior Light Bar".

### Phase 7 — Free-Form Vehicle Wizard

**Goal**: a guided multi-step wizard for building a vehicle from scratch with no preset. Replaces "fit parts into named slots" with "add part to location, app figures out the rest."

**Exit condition**: a user can complete a full build for a vehicle by walking through part categories (lights, cameras, bumpers, ...) with the app auto-naming parts (Phase 5's two-tier naming), recommending brackets, and rendering a live preview. The resulting draft is interchangeable with preset-driven drafts.

**Dependencies**: Phases 3, 5, 6 must be complete. The wizard relies on `parts_db.json`, the new light naming, and view-flexible rendering.

**Work**:
- **Category navigation**: drawn from `parts_db.json.part_categories`. The wizard's left-rail is data-driven.
- **Agency preference filtering**: when a project ties to an agency with `preferences.lighting = "whelen"`, the wizard filters parts to that manufacturer unless the user explicitly broadens. Preferences come from `EquipmentPreferences` already on the project record.
- **Free-form light addition** (the big UX change):
  - User clicks "Add Light." Picks a location on the preview (e.g., grill, push-bumper-top, A-pillar-driver). Picks a light type. Picks 1–3 colors.
  - App computes the part name ("ION Blue/White") and the role name ("Forward Warning 1") automatically.
  - App detects bracket needs (from `parts_db.parts.{id}.bracket_required`) and surfaces a recommendation. User accepts or declines.
  - User can override either name if they want.
- **Live preview integration**: existing `preview_canvas.js` shows placements. The wizard hooks into it.
- **Validation surfaces immediately**: rule engine (`rules/engine.py`) runs on every add. Violations show inline.
- **Auto-naming rules** live in `parts_db.json.naming_rules`, not in code, so the convention can change without a release.
- **Backwards compatibility**: existing presets (slot-based) still work. The slot model becomes an export convention, not a data-model invariant. Drafts authored in the new wizard export cleanly to the slot-based workbook by deriving slot assignments at export time.
- **No "Forward Warning 1/2/3" exposed in the wizard UI as a slot to fit into.** The build still produces those labels in the exported PowerPoint and workbook (because customers expect them), but they're derived from location + sequence, not authored.

### Phase 8 — Parts Manager (Same DB, Separate App or Tab)

**MVP slice shipped early (2026-06-12)**: the read-only tree + edit-modal slice was brought forward as part of Phase 3 PR-2b (4/4) so the owner could review the migration output (~165 model→manufacturer mappings, ~106 part_type tree positions) through a UI instead of by hand. Lives at Settings → Advanced → Part Manager → Database (v2); see `src/dtm_buildsheet/ui/js/settings/part_manager.js`. The remaining Phase 8 work below — inventory, pricing, low-stock indicators, the storage-split decision — is still open and depends on Phases 4–7.

**Editing-UI revamp brought forward (2026-06-29, on the critical path)**: the read-only MVP can't do
fast self-service review of the ~1,200-item QB import — and that review throughput is the current
bottleneck (see Current Direction). The revamp replaces today's three-tab Part Manager with **two
complementary views**:
- **SKU Review Grid** — brand-sorted, spreadsheet-style; expand a product to see all its SKUs inline;
  every field editable (each value-set field is a selector populated from `parts_db.json` with a
  "+ Create new…" option + a validating modal when more than a name is needed — never type-and-guess);
  move SKUs between products; add/delete; bulk actions; filters to target "what still needs attention."
- **Hierarchy editor** — the editable tree that controls how products sort/place in the Part Picker
  (`tree_positions`, `fits_part_types`, ordering).

Backend: granular PATCH-style endpoints (replacing today's whole-document POST), all routed through
`save_config_file` (SharePoint-mirror invariant). The two legacy tabs (Part Types, Parts Library)
stay until the Phase 4 consumer cutover. This is the *editing* slice of Phase 8; inventory/pricing/
low-stock remain the later full-Phase-8 work.

**Goal**: a UI for managing the parts database itself — friendly names, model numbers, sub-models, inventory quantities, prices. May be its own app; will share the same `parts_db.json`.

**Exit condition**: `parts_db.json` is editable through a dedicated UI, not by hand. The builder app reads inventory/price data and surfaces it on the build sheet.

**Decisions to make before starting**:
- Separate app vs. tab in this app? Separate app justifies SQLite or a backend service; tab is fine with extended JSON. Probably tab first, separate app later if it grows.
- **Inventory storage checkpoint**: `parts_db.json` is good for reviewed settings (low edit frequency, schema-style changes). It is *not* good for high-frequency operational data like inventory counts and price updates. If inventory will be edited many times per day by multiple users, **split inventory out of `parts_db.json`** into a separate `inventory.json` stored under SharePoint `/SharedWork/` (last-writer-wins per record, no PR review). Make this call before implementing inventory editing — moving it later is more painful than picking the right home up front.
- Storage evolution: at what scale does `parts_db.json` need to graduate from JSON-in-Git to SQLite or Postgres? Probably around 500+ parts or when concurrent edits start being common. The schema in §7 is designed to translate cleanly to relational tables.

**Work**:
- ✅ **MVP UI slice done** — tree view + edit modals for part_type/product/manufacturer/tag (commits `7157c13`, `01ada6d`).
- ⏳ Inventory and price fields added to each model entry in `parts_db.json` (they're already in the schema sketch; this phase fills them in).
- ⏳ Expose `qty_on_hand` / `price_usd` columns in the Part Manager product editor (the field is already in the `PartNumber` dataclass and the modal has a price input — needs polish + qty input).
- ⏳ Build sheet output includes part numbers, quantities required, and (optionally) prices.
- ⏳ Low-stock indicator: when adding a part to a build, if `qty_on_hand < quantity_required`, surface a warning.
- ⏳ Nice-to-have UI gaps the MVP didn't cover: drag-and-drop tree reorganization, bulk edit, add/delete entity buttons, type-to-filter, validation panel, service/preference-filter/build-attribute editors.

### Phase 9 — Per-Project Serial Number Tracking

**Goal**: track serial numbers for specific physical units of parts on specific projects. Used when reusing a radar antenna from an existing vehicle, etc.

**Exit condition**: each `IndividualUnit` (or each instance of a part on an individual unit) can optionally hold a serial number. The build sheet output includes the serial number when present.

**Work**:
- Add `serial_number: Optional[str]` to the per-instance part placement data on a draft.
- UI: serial number input in the manifest editor / wizard for parts flagged as `serialized: true` in `parts_db.json`.
- Validation: serial-number-tracked parts surface a "missing serial" warning when generating the build sheet, but don't block generation.
- This data is per-project — it lives on the draft / project record (in SharePoint), not in `parts_db.json` (in GitHub).

---

## 5. Cross-Cutting Concerns

### Schema versioning

Every persisted JSON file carries `schema_version`. When schema changes, bump the version and add a migration function. Migrations run on read, never on write. Old files in a shared workspace must continue to load on a new app version.

### Test coverage before refactor

Before a refactor that touches a data structure or a regex, write tests that pin the current behavior. Examples of things that need pinning before they get touched:
- The `_[A-Z][a-z]{2}\d+_\d{4}_\d+-\d+-\d+[AP]M$` filename regex.
- The merge behavior of workbook_rules + parts_library dropdowns (so the Phase 2 swap is verifiable).
- The four behavioral differences between group drafts and individual drafts (UNIT ID, vehicle_model derivation, pref_notes inclusion, draft_id writeback target).

### Compatibility shims

The codebase has several compatibility re-export modules (`gui_server.py`, `config_loader.py`, etc.). Audit periodically — any shim with zero callers outside its own module can be deleted. Don't pre-emptively delete shims that docs or external scripts still reference.

### What lives in `domain/`, `planning/`, `rules/`, `app/services/`

Stays consistent with `docs/REPOSITORY_PRINCIPLES.md`:
- `domain/` — pure data shapes, no I/O, no side effects.
- `planning/` — input → BuildPlan transformations.
- `rules/` — declarative validation/dependency rules.
- `app/services/` — orchestration with side effects (file I/O, multi-step flows).
- `app/routes/` — request parsing → service call → response. No business logic.

New cross-cutting concepts (e.g., parts_db queries) live in `app/services/` because they're orchestration over file-stored data. If we later add an ORM, `domain/` grows to include model classes.

### The workbook input path stays alive

Even after Phase 2, `excel_reader.py` and the `/parse` endpoint continue to accept user-uploaded workbooks. Some customers ship workbooks; we don't break that. The workbook input becomes one of multiple adapters that converge on `ProjectInput`, exactly as it does today.

---

## 6. Architectural Boundaries (For Future Variants)

The cloud architecture in Phase 2 is the *first* implementation, not the only possible one. Two future variants drive this section:

1. **Customer-facing view of projects.** Possibly hosted on the company website. Customers sign in (some non-M365 method) and see only their own projects, with the ability to propose changes that come back to the internal team for confirmation. Read-mostly. One customer organization can see only its own projects.
2. **Sale of the app to other upfitters.** A fork would become its own product. Buyers won't be on the company's M365 tenant; they may use Google Workspace, a different cloud, or want a simple paid backend. They may also want on-premises deployment.

Neither of these is planned in this roadmap. This section exists to make sure current work doesn't *block* them.

### The principle

Build M365/SharePoint/GitHub/Power Automate as the *first* set of adapters behind well-defined interfaces, not as the backbone the app directly calls. Swapping the cloud later — for the customer-facing version, for an external sale, or just because we want a different backend — should be a config change plus a new adapter class. Not a rewrite.

This is the **ports-and-adapters** pattern (sometimes called hexagonal architecture). Core domain logic depends on abstract interfaces; concrete implementations live in adapter classes that get wired in at startup. Common synonyms: "the adapter pattern," "dependency inversion," informally "plugin." We're not building a runtime plugin system (no dynamic discovery, no entry points) — just a clean compile-time adapter boundary.

### What gets a port-and-adapter boundary

Four boundaries matter for variant-readiness. The first implementation of each is what Phase 2 builds; the interface is what makes future implementations possible.

| Boundary | Interface | First implementation (Phase 2) | Future variants |
|---|---|---|---|
| Shared file storage | `StorageProvider` (already exists at `storage/base.py`; extend with `read_bytes` + declared `write_bytes`) | `SharePointGraphProvider` (Graph API). `LocalStorageProvider` already exists for tests and bundled-only mode. | `S3Provider`, `GoogleDriveProvider`, custom REST API |
| User identity | `IdentityProvider` | `M365IdentityProvider` (M365 OAuth) | `GoogleIdentityProvider`, `EmailPasswordProvider`, `MagicLinkProvider`, custom OAuth |
| Settings change proposal | `ChangeProposalGateway` | `SharePointPendingChangesGateway` (writes to `/PendingChanges/`; GitHub Actions picks up) | `DirectBackendGateway` (POSTs to a custom API), `LocalApprovalQueueGateway` |
| Team notification | `NotificationGateway` | `PowerAutomateNotifier` (writes marker files that trigger flows) | `WebhookNotifier`, `EmailNotifier`, `SlackNotifier`, `NoOpNotifier` |

Each interface is small. The storage interface already exists at `storage/base.py` with `read_text`/`write_text`/`delete`/`list_files`; Phase 2 extends it with `read_bytes` and pulls `write_bytes` from `LocalStorageProvider` into the abstract interface. The SharePoint adapter wraps Graph API; a future S3 adapter wraps boto3. The app's services read from the interface, never from a specific cloud SDK.

### What does NOT get a boundary

Over-abstracting kills clarity. We're not building a generic plugin system. The boundaries above are the ones we know we'll cross. Things that stay direct (no abstraction):

- **Domain logic** (`domain/`, `planning/`, `rules/`) — these are the app's value. Clean Python; no interfaces needed.
- **Local file I/O** for app settings — local is local. No adapter.
- **The HTTP server itself** — `BaseHTTPRequestHandler` is fine as-is.
- **The web UI** — vanilla JS. No JS-side adapter pattern needed; the JS calls the local server, the server uses the adapters.
- **Domain schemas** (`parts_db.json` shape, `BuildPlan` structure) — adapters translate to/from these, but the schemas themselves are app-internal.

Four boundaries is the right number for this app. Don't add a fifth without a concrete need.

### How Phase 2 changes given this section

Phase 2's earlier spec assumed direct calls to SharePoint + Graph API + GitHub + Power Automate throughout. Under this section's principle, that becomes:

1. **Build the interfaces first.** A short sub-step at the start of Phase 2 defines the four interfaces above as Python protocols / ABCs. Each interface is small enough to fit on one screen.
2. **Build the first implementations second.** `SharePointGraphProvider`, `M365IdentityProvider`, `SharePointPendingChangesGateway`, `PowerAutomateNotifier` — each in `app/adapters/`.
3. **Services depend on the interfaces, not the adapters.** `shared_settings_service` doesn't import `SharePointGraphProvider` — its constructor takes a `SharedStorageProvider` and a `ChangeProposalGateway`. The service is portable to any future variant.
4. **Build-time wiring, not runtime config.** A single `app/adapters/wiring.py` file constructs the right adapter set for the current build. Internal-team builds wire SharePoint + M365 + GitHub Actions + Power Automate. A hypothetical external build would wire different adapters. The choice is at compile/package time, not in user-facing config.

Cost: ~1-2 extra days at the start of Phase 2 to define interfaces and wire DI. Benefit: every future variant is localized work, not a rewrite. Worth it.

### Customer-facing version: what current decisions enable, and what they block

This product is not planned in this roadmap. But current decisions affect whether it's achievable.

**Already compatible** (don't need changes):
- `ProjectRecord.customer.agency_id` exists. Filtering projects by customer is a query, not a schema change.
- Domain logic is UI-agnostic. A web UI can call the same `project_service`, `build_plan_service`, etc.
- Per-record JSON storage means a customer querying their projects doesn't need a different backend layout.

**Compatible if Phase 2 is built behind interfaces**:
- Customer-facing version needs a different `IdentityProvider` (probably email + magic link, or Google sign-in). The interface makes this swappable.
- Customer-facing version needs a different `ChangeProposalGateway` (their proposals go into an in-app approval queue, not a GitHub PR). The interface makes this swappable.

**Would block, if done wrong**:
- Embedding M365 SSO assumptions in domain logic (e.g., a service that hard-codes "look up user via Graph API").
- Hard-coding SharePoint folder structures in services that don't need them (the adapter knows the structure; the service doesn't).
- Tightly coupling the HTTP server to pywebview — for a web-hosted customer version, the same server needs to run headless on a real web server.
- Building authorization implicitly ("the user is logged in, they see everything"). Authorization needs to be explicit and queryable from the start, even if today the only rule is "internal users see all projects."

### External sale: what current decisions enable, and what they block

Even less planned. Same principle applies.

**Already compatible**:
- Open-source-friendly tech stack (Python + JS, no proprietary frameworks).
- Domain logic separated from infrastructure (per existing repo principles).

**Compatible if Phase 2 is built behind interfaces**:
- A buyer can substitute their own storage (S3, Postgres, on-prem file share) by writing an adapter.
- A buyer can substitute their own identity provider, notification system, and review workflow.

**Would block, if done wrong**:
- Hard-coding GitHub repo names, SharePoint site URLs, Azure AD tenant IDs as Python constants in service code rather than as adapter configuration.
- Building the review flow such that PRs in a *specific* repo are the only way to approve a change. (Mitigated by `ChangeProposalGateway` interface — a buyer's variant might use a different review queue entirely.)
- Coupling the desktop app to anything proprietary to the company's environment (e.g., assuming Microsoft Graph is available, assuming a specific Teams channel exists).

### What NOT to do for variant-readiness

Over-engineering for variants we haven't planned is a real risk. Guardrails:

- **Don't try to support every possible backend now.** Build SharePoint and M365 well. Define the interfaces narrowly around what those adapters need. Future adapters can extend the interfaces if and when they're built.
- **Don't add config flags for unfinished alternative paths.** A `storage_provider` setting should accept one value today: `"sharepoint_graph"`. Adding `"s3"` as a stub that throws "not implemented" is clutter that promises something we haven't built.
- **Don't write a dynamic plugin loader.** No runtime discovery, no entry-point registration, no class-name strings in config. Adapters are classes in `app/adapters/`. Adding a new one is a code change to `wiring.py`, not runtime magic.
- **Don't pretend to be cloud-agnostic in marketing or docs while being cloud-coupled in code.** Either the interfaces are clean, or they aren't. If the SharePoint adapter is leaking implementation details into the service layer, fix that — don't paper over it with optimistic README copy.
- **Don't fight YAGNI.** If a boundary doesn't have a concrete second implementation on the horizon, don't add it. The four boundaries above are justified because we have at least one named future variant for each. A fifth boundary needs the same justification.

## 7. Domain Schema: `parts_db.json`

> **This is the original sketch (kept for design rationale). The schema as actually built has
> diverged — the live shape (Type → Section → Zone → Part Type → Product → Part Number, plus
> manufacturers/tags/placements/accessory_categories) is documented in
> [PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md) §1, which is the single source of truth.**

Sketched schema (early draft):

**Three orthogonal axes** (this was the schema's biggest mistake in the first draft — they were conflated):

1. **Part category** — what the part *is* (lights, cameras, brackets, decals, etc.). Brackets are parts in the same category sense; they just have `compatible_part_ids` relationships with the parts they support.
2. **Location zone** — *where on the vehicle* the part goes. Each location belongs to a zone, and the zone drives role naming for lights (primary_front → "Forward Warning", front_corner → "Front Corner Warning", etc.).
3. **Build section** — *how* the part groups in the exported build sheet / PowerPoint (front, side, rear, console, equipment_tray, interior). This is presentation, not data.

```json
{
  "schema_version": 1,
  "metadata": {
    "last_updated": "2026-05-20T00:00:00Z",
    "updated_by": "system"
  },

  "part_categories": {
    "lights":      { "label": "Lights" },
    "cameras":     { "label": "Cameras" },
    "radar":       { "label": "Radar" },
    "bumpers":     { "label": "Push Bumpers" },
    "cages":       { "label": "Cages" },
    "audio":       { "label": "Audio (Sirens, Speakers)" },
    "controllers": { "label": "Controllers" },
    "brackets":    { "label": "Brackets" },
    "decals":      { "label": "Decals" },
    "k9":          { "label": "K-9 Equipment" },
    "accessories": { "label": "Accessories" }
  },

  "location_zones": {
    "primary_front": { "label": "Primary Front" },
    "front_corner":  { "label": "Front Corner" },
    "front_side":    { "label": "Front Side" },
    "side":          { "label": "Side" },
    "rear_side":     { "label": "Rear Side" },
    "rear_corner":   { "label": "Rear Corner" },
    "rear":          { "label": "Rear" },
    "rear_interior": { "label": "Rear Interior" },
    "console":       { "label": "Console" },
    "interior":      { "label": "Interior" }
  },

  "locations": {
    "GRILL":              { "label": "Grill",             "zone": "primary_front" },
    "PUSH_BUMPER_TOP":    { "label": "Push Bumper Top",   "zone": "primary_front" },
    "PUSH_BUMPER_LOWER":  { "label": "Push Bumper Lower", "zone": "primary_front" },
    "A_PILLAR_DRIVER":    { "label": "A-Pillar (Driver)", "zone": "front_corner" },
    "A_PILLAR_PASSENGER": { "label": "A-Pillar (Pass.)",  "zone": "front_corner" },
    "FRONT_FENDER":       { "label": "Front Fender",      "zone": "front_side" },
    "REAR_DECK":          { "label": "Rear Deck",         "zone": "rear" },
    "INSIDE_REAR_GLASS":  { "label": "Inside Rear Glass", "zone": "rear_interior" },
    "DASH":               { "label": "Dash",              "zone": "interior" }
  },

  "build_sections": {
    "front":          { "label": "Front",          "order": 1 },
    "side":           { "label": "Side",           "order": 2 },
    "rear":           { "label": "Rear",           "order": 3 },
    "interior":       { "label": "Interior",       "order": 4 },
    "console":        { "label": "Console",        "order": 5 },
    "equipment_tray": { "label": "Equipment Tray", "order": 6 }
  },

  "manufacturers": {
    "whelen":  { "label": "Whelen",  "website": "https://www.whelen.com" },
    "setina":  { "label": "Setina" },
    "havis":   { "label": "Havis" },
    "stalker": { "label": "Stalker Radar" }
  },

  "color_palette": {
    "red":    { "label": "Red",    "hex": "#E10600", "naming_token": "R" },
    "blue":   { "label": "Blue",   "hex": "#003DA5", "naming_token": "B" },
    "white":  { "label": "White",  "hex": "#FFFFFF", "naming_token": "W" },
    "amber":  { "label": "Amber",  "hex": "#FFA500", "naming_token": "A" },
    "green":  { "label": "Green",  "hex": "#00853E", "naming_token": "G" },
    "purple": { "label": "Purple", "hex": "#8B5CF6", "naming_token": "P" }
  },

  "parts": {
    "whelen_ion_t": {
      "friendly_name": "Whelen ION T-Series",
      "category": "lights",
      "build_section": "front",
      "manufacturer_id": "whelen",
      "models": [
        {
          "model_id": "wh_ion_t_single",
          "model_number": "ION-T-1",
          "submodel": "single-color",
          "color_count": 1,
          "power_outputs": 1,
          "supported_colors": ["red", "blue", "white", "amber"],
          "price_usd": 95.00,
          "qty_on_hand": 24
        },
        {
          "model_id": "wh_ion_t_tri",
          "model_number": "ION-T-T-T",
          "submodel": "tri-color",
          "color_count": 3,
          "power_outputs": 3,
          "supported_colors": ["red", "blue", "white", "amber", "green", "purple"],
          "price_usd": 245.00,
          "qty_on_hand": 11
        }
      ],
      "color_asset_map": {
        "R":   "lights/ion_t_red.png",
        "B":   "lights/ion_t_blue.png",
        "RB":  "lights/ion_t_red_blue.png",
        "RWB": "lights/ion_t_red_white_blue.png"
      },
      "compatible_vehicles": ["TAHOE", "PIU", "EXPLORER", "F150"],
      "compatible_locations_by_vehicle": {
        "TAHOE":    ["GRILL", "PUSH_BUMPER_TOP", "PUSH_BUMPER_LOWER", "A_PILLAR_DRIVER", "A_PILLAR_PASSENGER"],
        "PIU":      ["GRILL", "PUSH_BUMPER_TOP"],
        "EXPLORER": ["GRILL"],
        "F150":     ["GRILL", "PUSH_BUMPER_TOP"]
      },
      "bracket_required": true,
      "compatible_bracket_part_ids": ["whelen_bracket_universal"],
      "serialized": false
    },

    "whelen_bracket_universal": {
      "friendly_name": "Whelen Universal Mounting Bracket",
      "category": "brackets",
      "build_section": "front",
      "manufacturer_id": "whelen",
      "models": [
        { "model_number": "BRK-UNIV", "price_usd": 35.00, "qty_on_hand": 50 }
      ],
      "compatible_part_ids": ["whelen_ion_t", "whelen_liberty_ii"],
      "compatible_locations": ["GRILL", "PUSH_BUMPER_TOP", "PUSH_BUMPER_LOWER"],
      "serialized": false
    },

    "stalker_dsr_radar": {
      "friendly_name": "Stalker DSR 2X Radar",
      "category": "radar",
      "build_section": "equipment_tray",
      "manufacturer_id": "stalker",
      "models": [
        {
          "model_number": "DSR-2X",
          "submodel": "dual-antenna",
          "power_outputs": 2,
          "price_usd": 2400.00,
          "qty_on_hand": 3
        }
      ],
      "compatible_vehicles": ["TAHOE", "PIU", "EXPLORER", "F150"],
      "compatible_locations_by_vehicle": {
        "TAHOE": ["DASH", "WINDSHIELD"],
        "PIU":   ["DASH"]
      },
      "bracket_required": false,
      "serialized": true
    }
  },

  "naming_rules": {
    "light_part_name": {
      "template": "{model_friendly_name} {colors_joined}",
      "color_joiner": "/",
      "color_canonical_order": ["red", "blue", "white", "amber", "green", "purple"],
      "color_display_form": "label"
    },
    "light_role_name": {
      "scene_predicate":   { "colors_exact": ["white"] },
      "warning_predicate": { "colors_any_not": ["white"] },
      "templates_by_zone": {
        "primary_front":  { "scene": "Forward Scene {n}",       "warning": "Forward Warning {n}" },
        "front_corner":   { "scene": "Front Corner Scene {n}",  "warning": "Front Corner Warning {n}" },
        "front_side":     { "scene": "Front Side Scene {n}",    "warning": "Front Side Warning {n}" },
        "side":           { "scene": "Side Scene {n}",          "warning": "Side Warning {n}" },
        "rear_side":      { "scene": "Rear Side Scene {n}",     "warning": "Rear Side Warning {n}" },
        "rear_corner":    { "scene": "Rear Corner Scene {n}",   "warning": "Rear Corner Warning {n}" },
        "rear":           { "scene": "Rear Scene {n}",          "warning": "Rear Warning {n}" },
        "rear_interior":  { "scene": "Rear Interior Scene {n}", "warning": "Rear Interior Warning {n}" }
      },
      "sequence_scope": "per_zone_per_role"
    }
  }
}
```

**Notes on the schema**:

- **Three orthogonal axes**:
  - `parts.{id}.category` answers *what is this part*. Brackets are category `"brackets"`. Decals are `"decals"`. They're all parts.
  - A *placement* (which lives on a draft, not in `parts_db.json`) references a location ID. The location belongs to a zone via `locations.{id}.zone`. The zone drives role naming.
  - `parts.{id}.build_section` answers *which group does this part appear in on the exported build sheet*. This is presentation, not data — two parts in the same category can have different build sections.
- **Brackets are parts with relationships**. `brackets.{id}.compatible_part_ids` lists the parts it supports; `parts.{id}.compatible_bracket_part_ids` is the inverse. Slightly redundant but makes queries cheap in either direction. The roadmap notes "brackets are their own part in the part DB" — this honors that.
- **Two-tier light naming**:
  - **Part name** (`light_part_name`) is shown in the parts picker and inventory. Format: `{model_friendly_name} {colors_joined}` → e.g., "ION T-Series Red/White".
  - **Role name** (`light_role_name`) is shown on the build sheet and in the manifest editor. Derived from zone + color pattern (scene if white-only, warning otherwise) + sequence within zone+role.
  - The user can override either, but the default is fully derived.
- `parts.{id}.color_asset_map` keys are derived color tokens (e.g., `"RWB"` for Red+White+Blue in canonical order). Frontend builds the lookup key from selected colors using `light_part_name.color_canonical_order`.
- `compatible_locations_by_vehicle` is nested rather than two flat lists because the dimension matters: a light may fit a TAHOE's grill but not an EXPLORER's grill.
- `serialized: true` flags parts that need per-instance serial number tracking (Phase 9).
- `power_outputs` and pricing/inventory live on the model entry, not the part, because different models of the same part have different values.
- Color palette includes **red, blue, white, amber, green, purple**.

**Open questions to resolve in Phase 3**:

- Bracket compatibility nuance: do we need `bracket_required_by_location` (some locations don't need a bracket even if the part usually does)? Probably yes for grill-mount cases. Add as a per-location override on `parts.{id}.bracket_required` if needed.
- Should `location_zones` differ per vehicle? Probably not — zones are abstract categories ("primary front") that apply across vehicles. Per-vehicle differences are in which locations exist, not which zones exist.
- Does `build_sections` need per-vehicle override? Probably not — sections are presentation, and the workbook template wants the same sections everywhere. Per-vehicle variability lives in which locations show up, which is already in `compatible_locations_by_vehicle`.

---

## 8. What Not To Do

Explicit non-goals and anti-patterns to avoid:

- **Don't add new dependencies on `workbook_rules.json.part_rules` outside of `template_builder.py`.** Read from `parts_db_service` instead. Workbook rules is on its way to being layout-only.
- **Don't enumerate light color combinations** in any new code or config. Combinations are derived from a 1–3-color selection (Phase 5).
- **Don't conflate the three orthogonal axes** (part category / location zone / build section). They answer different questions about a part and should never be merged into one taxonomy.
- **Don't hardcode "four views"** anywhere. Iterate the vehicle's view collection.
- **Don't build a generic `BaseCollectionService`** to share code between agency_service and sales_rep_service. Their differences (validation rules, normalization, migration) are not edge cases. Extract small utility functions if needed; do not unify the services.
- **Don't store absolute filesystem paths in persisted JSON records.** Use workspace-relative paths and resolve at runtime.
- **Don't have the app talk to GitHub directly.** The app only talks to SharePoint via Graph API with M365 OAuth. GitHub is the review backend, invisible to users. All GitHub interaction happens via GitHub Actions running in CI.
- **Don't embed a GitHub PAT or GitHub App credential in the app binary.** App users authenticate only with M365. The GitHub Actions service principal credential lives in GitHub Secrets, never in the app.
- **Don't expose GitHub mechanics in the app UI.** Users see "Propose change" and "Awaiting review" — they don't see "branches," "PRs," or "GitHub." GitHub is plumbing.
- **Don't sync settings synchronously on every keystroke.** Settings changes are user-initiated proposals, not auto-saves. Project data syncs differently (last-writer-wins per record), but the user understands a project save = a network write.
- **Don't use Power Automate's HTTP/Premium connectors for sync.** Premium connectors cost ~$15/user/month. GitHub Actions does the SharePoint↔GitHub sync for free.
- **Don't use OS-level SharePoint file sync** (the OneDrive client) as the app's storage layer. We've experienced staleness and out-of-date issues. The app calls Microsoft Graph API directly.
- **Don't import concrete cloud adapters from services.** Services depend on the four interfaces in `app/adapters/interfaces.py` (`SharedStorageProvider`, `IdentityProvider`, `ChangeProposalGateway`, `NotificationGateway`). The wiring at `app/adapters/wiring.py` is the only module that knows which adapter is in use.
- **Don't hardcode SharePoint folder paths, GitHub repo names, or Azure tenant IDs in service code.** These are adapter configuration. If a service knows the path `/PendingChanges/`, the abstraction has leaked.
- **Don't add stub adapters for unbuilt variants.** A `storage_provider` config slot that accepts `"s3"` but throws "not implemented" is clutter. Only ship adapters that work.
- **Don't build a dynamic plugin system.** No runtime discovery, no entry-point registration, no class-name strings in config. Adapters are classes; adding one is a code change.
- **Don't add code signing certificates as a hard requirement** for app updates. The notify-and-link flow works without signing; users dismiss OS warnings on install. Code signing is a polish upgrade, not a prerequisite.
- **Don't break the workbook input path** (`excel_reader.py`, `/parse` endpoint) while phasing out the workbook as a data source. They are independent concerns.
- **Don't introduce a routing framework** in `server.py`. The current dispatch is deliberate layering, not chaos.
- **Don't expose "Forward Warning 1/2/3" slots** in the new wizard UI. The slot model is a workbook-export convention, not a user-facing concept. Role names are derived from zone + colors (Phase 5).
- **Don't combine the two light names** (part name and role name). They serve different UI surfaces and answer different questions.
- **Don't change the semantics of `PartInput.name` / `DraftPart.name`.** The rule engine (`rules/engine.py`) matches on `_norm(part.name)` string equality; `build_rules.json` references parts by name. Renaming this field's contents breaks every rule. New naming concepts go in new fields (`display_name`, `part_id`, etc.).
- **Don't invent a new `SharedStorageProvider`.** Extend the existing `storage.base.StorageProvider`. The interface already covers most of what's needed; only `read_bytes` and a declared `write_bytes` are missing.
- **Don't split monolithic collections to per-record files without adding an in-memory cache.** Live fuzzy-search endpoints fire every 220ms; hundreds of disk reads per keystroke will tank performance.
- **Don't put string predicates in config that look like code.** No `"colors == ['white']"` strings. Use declarative JSON: `{"colors_exact": ["white"]}`. Evaluating string predicates means writing a parser or using `eval()` — both are bad.
- **Don't use `model_number` as a persisted foreign key.** Use a stable `model_id` slug. Model numbers change, get duplicated by vendor, or need friendly variants.
- **Don't use client secrets for GitHub Actions → Azure auth when OIDC is available.** Federated credentials are now the recommended path.

---

## 9. Decision Log

Decisions that are locked in. Don't relitigate without an explicit reason.

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-20 | Single `parts_db.json` for domain data, not three enriched files (part_catalog/parts_library/vehicle_layouts) | User preference for "one clean DB, not data spread everywhere." Vehicle_layouts.json retained for geometry. |
| 2026-05-20 | Workbook becomes a renderer/output, not a data source | Lighter ongoing maintenance; aligns with user goal. Excel input still supported via `excel_reader.py`. |
| 2026-05-20 | Future direction: shared-folder cloud (likely SharePoint) | No extra cost; uses existing company infrastructure. Architecture must not block this. |
| 2026-05-20 | Per-record JSON storage for shared collections, not monolithic | Required for concurrent multi-user access on shared storage. |
| 2026-05-20 | Lights modeled with 1–3 color selection + derivation, not enumerated combos | Massive simplification of UI and data. |
| 2026-05-20 | Vehicle setup wizard is free-form (add part to location), not slot-based | "Forward Warning 1/2/3" is an export convention, not a user mental model. |
| 2026-05-20 | Parts manager shares the parts DB with the builder | One source of truth for inventory/pricing. May or may not be a separate app. |
| 2026-05-20 | Project storage layout is subdirectory (`{id}/project.json`), not flat | Implementation already does this; docs were wrong. Subdirectory enables per-project artifacts (drafts, snapshots, etc.). |
| 2026-05-20 | Cloud architecture: M365-only for users, SharePoint as the app's only backend, GitHub as invisible review layer | Cleanest auth story (one credential per user, the M365 account they already have). Zero marginal cost on existing M365 + free private GitHub. |
| 2026-05-20 | App auto-update: notify-and-link via SharePoint `/Releases/` (installers published by CI) | App reads installers from SharePoint using user's M365 token. No GitHub access needed for users. CI publishes both to GitHub Releases (for owner) and to SharePoint (for users). No code signing required at first. |
| 2026-05-20 | All four settings categories require review before propagating | Part DB, presets, placements/vehicle layouts, build rules. Bad changes in any of these cascade into every build. |
| 2026-05-20 | App auth: M365 OAuth only. GitHub Actions auth: Azure AD service principal stored in GitHub Secrets | App users never see GitHub. The service principal credential lives only in CI, never in the app binary. Rotates every ~6 months (Azure AD client secret lifetime). |
| 2026-05-20 | Sync glue: GitHub Actions, not Power Automate, for SharePoint↔GitHub | HTTP-to-GitHub is a premium Power Automate connector (~$15/user/mo). GitHub Actions does the same work for free, code-defined, version-controlled. |
| 2026-05-20 | Proposal→PR latency: 5-minute cron via GitHub Actions | Simplest reliable mechanism. Acceptable for a review workflow. Can be upgraded later to webhook-driven (~15s) if it becomes annoying. |
| 2026-05-20 | Power Automate used for two team notifications (Standard connectors only) | Settings update notification and app release notification. SharePoint + Office 365 Outlook connectors are both standard, included with M365. Teams is not in use — email is the notification channel. Flow A (settings update → email) is live and tested as of 2026-05-21. |
| 2026-05-20 | Cloud integration built behind ports-and-adapters boundaries, not as a direct dependency | Two future variants (customer-facing web app, external sale to other upfitters) are explicit constraints. Swapping the cloud stack later should be a localized adapter change, not a rewrite. Cost: ~1-2 days up front in Phase 2 to define interfaces and wire DI. |
| 2026-05-20 | Four port-and-adapter boundaries: storage, identity, change-proposal, notification | These are the boundaries we know we'll cross. No fifth boundary without a concrete second implementation on the horizon. |
| 2026-05-20 | Build-time adapter selection via `app/adapters/wiring.py`, not runtime config | No dynamic plugin loader. No entry-point discovery. Adapter choice is a code change to one file at build time. Avoids accidental drift between supported and "supposedly supported" backends. |
| 2026-05-20 | Customer-facing version and external-sale variants are not planned in this roadmap | Their existence as future possibilities shapes current decisions (the four boundaries above); they do not get phases of their own here. When/if they happen, they get their own roadmaps. |
| 2026-05-20 | `PartInput.name` / `DraftPart.name` semantics stay stable in Phase 5 | Rule engine (`rules/engine.py:61`) matches on `_norm(part.name)` strings; `build_rules.json` references parts by name. New light naming goes in new fields (`display_name`, `part_id`, `model_id`, `colors`); existing `name` field continues to hold role labels ("Forward Warning 1" etc.). Rules and Excel import keep working without modification. |
| 2026-05-20 | Storage interface: extend existing `storage.base.StorageProvider`, do not invent new | Already has `read_text`/`write_text`/`delete`/`list_files`. Add `read_bytes` and pull `write_bytes` from `LocalStorageProvider` into the interface. Avoids parallel abstractions. |
| 2026-05-20 | In-memory cache required for agency/sales-rep services before or during per-record file split | Live fuzzy-search at 220ms debounce currently re-reads JSON on each keystroke. Cheap with monolithic file; expensive with per-record. Cache invalidates on save/delete. |
| 2026-05-20 | Path portability: `app_settings.project_output_root` stays absolute (local-only); record-side `output_path` fields become workspace-relative; `ProjectRecord.export_dir` may be dropped entirely | The existing architecture already separates the local root from the computed dir (`inputs/project_dirs.py:resolve_project_output_dir`). What changes is per-record stored paths, not the resolution logic. |
| 2026-05-20 | `dtm-shared-settings` repo is public, not private | GitHub Free does not enforce branch protection rules on private repos (requires Pro/Team). Settings files are non-sensitive (secrets live in GitHub Secrets and Azure AD). Public repos get full enforcement for free. Making it public is the right call, not a workaround. |
| 2026-05-20 | Cloud go-live prioritized before parts-DB schema migration | Team collaboration on the existing structure is more valuable than a clean schema in isolation. Schema migration becomes a normal PR after cloud is live. |
| 2026-05-20 | Light color palette: red, blue, white, amber, green, purple | Six colors cover stated needs. Combinations derived (not enumerated). |
| 2026-05-20 | Light naming is two-tier: part name (model + colors) and role name (zone + color pattern) | Different UI surfaces need different names. Part name for picker/inventory; role name for build sheet. Both derived by default. |
| 2026-05-20 | Three orthogonal axes for parts: category / location zone / build section | First schema draft conflated category and location-zone, which created confusion. They answer different questions and must stay separate. |
| 2026-05-20 | Brackets are parts in the `brackets` category, not a separate top-level collection | Brackets get tracked, priced, inventoried like any other part. Relationships are expressed via `compatible_part_ids`. |
| 2026-07-06 | Workbook import demoted from guaranteed input format to optional backup adapter; retirement on the table | Spreadsheets will see near-zero real use, and workbook-shape assumptions in core consumers are causing live bugs when parts_db supplies better data. Canonical pipeline is domain/parts_db-shaped; the workbook converts at the `inputs/` boundary or not at all. Workbook-era domain logic is ported into domain/planning via parity proofs, not lost. Workbook-as-renderer (export) unaffected. |
| 2026-07-07 | Kit estimate behavior mirrors QuickBooks | One QB item → one line; QB bundle/group → component lines. Kit support exists only to represent kits present in QB inventory — no app-invented kit semantics. Right-sizes the kit-SKU phase. |
| 2026-07-07 | Sibling parts-manager app deferred; starts read-only if/when built | The parts_db repository seam (importable without the GUI) is the only prerequisite and lands anyway, so deferral costs nothing. No speculative Graph-capable writer adapter for a second app. |
| 2026-07-07 | SKU-grid save path frozen until curation queue (~673 unhomed products) is complete | Owner declares curation done before Stage C2 touches the save path; full backup checkpoint precedes it. Non-save-path stages proceed independently. |

---

## 10. How To Use This Document

**For future agents**:
1. Read this before proposing any structural change.
2. If your change advances a phase, say which phase and which work item.
3. If your change contradicts a guiding principle or a decision in §9, surface the contradiction explicitly. Don't quietly do it.
4. If you discover that a stated current-state fact in §3 is wrong, fix the doc and proceed.

**For the project owner**:
1. When direction changes, update §1 and §9.
2. When a phase completes, mark it complete and move work items into a "done" section if useful.
3. When schema-level decisions land (e.g., the final shape of `parts_db.json`), update §7 to match what was actually built.

**For pull requests**:
- Reference the phase and work item being addressed in the PR description.
- Reference any §9 decision the PR depends on.
- If the PR introduces a new pattern that doesn't exist in this doc, propose adding it under §5, §6, or §8.
