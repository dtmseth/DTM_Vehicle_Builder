# Strategic Refactoring & Audit Roadmap (Meta-Plan)

> **Purpose**: The process plan for a full-repo audit and refactor of DTM Vehicle Builder.
> This is a *meta-plan*: it defines how the audit and refactor will be executed, sequenced,
> and validated — not what any specific line of code should become.
>
> **Audience**: the project owner, the executing agent(s), and a secondary peer-review agent.
> Section 9 contains explicit instructions for the reviewing agent.
>
> **Prime directive**: zero functional regression. The user-visible feature set and UX must
> remain identical or improve at every merge point. Documented-but-unbuilt features are
> first-class constraints: the refactored architecture must leave load-bearing seams for them.

---

## 0. Ground Truth (repo snapshot at plan time)

Facts the plan is built on — the reviewing agent should re-verify these before approving:

- **Scale**: ~20K LOC Python (`src/dtm_buildsheet/`), ~12.5K LOC JS (`src/dtm_buildsheet/ui/js/`),
  ~12.7K LOC tests (60 files), plus a serverless relay (`relay/`), packaging scripts, and a large
  docs suite. Too big to hold in one context window; small enough that every module can be
  visited once.
- **Legacy/modern pairs already exist** (strangler-fig migration mid-flight):
  | Legacy (top-level module) | Modern replacement (package) |
  |---|---|
  | `planner.py` | `planning/` (resolver-per-concern) |
  | `config_loader.py`, `config_store.py`, `config_validation.py` | `config/` (loader, store, schemas, migrations) |
  | `models.py` | `domain/` (split model modules) |
  | `input_reader.py` | `inputs/` (excel_reader, project_entry, drafts) |
  | `gui_server.py` | `app/server.py` + `app/adapters/` |
  **Production still runs through these modules** — they are active compatibility surface, not
  dead code: `generator.py` imports `config_loader`, `input_reader`, and `planner`;
  `template_builder.py` imports `config_store`; and `pyproject.toml` `[project.scripts]`
  installs `dtm_buildsheet.gui_server:main` as the app entry point. Several are thin delegating
  shims, but nothing may be deleted until the §2 protocol's production-cutover step repoints
  these imports and packaging entries. *(Corrected in review round 1 — an earlier draft
  wrongly claimed only tests import them.)*
- **Docs are unusually complete** and already function as contracts: `FEATURE_INVENTORY.md`
  (behavior catalog), `GOTCHAS.md` (known-footgun registry), `ARCHITECTURE.md` +
  `REPOSITORY_PRINCIPLES.md` (design rules), `ROADMAP.md` (phases + decision log),
  `EXTERNAL_CONNECTION_SECURITY.md` (security standard), `QUICKBOOKS.md`, `PARTS_DB_AND_PICKER.md`.
- **Cloud is SHIPPED, not future**: Phase 2/2.5 went live — cloud (SharePoint via Graph) is the
  source of truth as of v2.2.9+, with direct-SP-write alongside the proposal/PR flow, the
  outbound-queue junk guard, and the 60s periodic sync (`ROADMAP.md` §"Phase 2 as shipped").
  For this plan, cloud is a **preserve** obligation (don't break shipped adapters/sync
  semantics), not a seam to create.
- **Committed future features the architecture must hold space for** (per `ROADMAP.md`
  near-term critical path, updated 2026-06-30): the picker + placement cluster (NEXT), kit
  SKUs, QB Pass-2 import, finishing the Part Picker (Chunks 8–9 + non-light coverage), Phase 4
  consumer migration onto parts_db, extensible views (not "exactly four"), inventory/serial
  tracking, a sibling parts-manager app sharing the DB, and customer-facing / external-sale
  variants (the reason `app/adapters/` ports-and-adapters exists).
- **Hard invariants that survive any refactor**: secrets never touch disk/cloud (OS keychain via
  `credential_store.py` only); workbook is a renderer, not a database; GitHub layer is invisible
  to end users.

---

## 1. Navigating Scale — the audit method for a repo that exceeds context

**Principle: never scan; always traverse.** The repo is explored along its dependency structure,
one bounded chunk at a time, with findings externalized to disk so no pass depends on a prior
pass being in context.

### 1.1 Build the map before reading code
1. **Machine-generated import graph** (Python: AST/import walk; JS: script-tag order +
   cross-file global usage, since the UI uses classic scripts, not modules). Output: one
   DOT/JSON graph checked into an `audit/` working directory. This is cheap, exact, and
   context-free — it comes from tooling, not from reading.
2. **Entry-point census.** Every behavior is reachable from a finite set of roots:
   `__main__` (GUI), `generator_cli`, the HTTP route table in `app/server.py`, the JS event
   handlers per tab, the `relay/` functions, `scripts/`/`tools/`, **and the packaging roots** —
   `pyproject.toml` `[project.scripts]` (`gui_server:main`, `generator_cli:main`) and the
   PyInstaller launcher `packaging/pyinstaller/launch_gui.py` (which imports `gui_server`
   directly; the installed app boots through it, so it can keep legacy modules alive even when
   dev-mode code paths don't). Anything *not* reachable from a root is a deletion candidate by
   construction.
3. **Module manifest.** One table (path, LOC, layer, imports-in/out, owning feature, legacy/modern
   flag, audit status). This is the audit's working memory and progress tracker.

### 1.2 Chunking strategy
- **Unit of audit = architectural layer slice**, not folder: (a) domain models, (b) planning
  resolvers, (c) config/storage, (d) HTTP surface, (e) rendering (`ppt_helpers`, `render_ppt`,
  `template_builder`), (f) UI JS per tab, (g) relay + external connections, (h) packaging/scripts.
  Each slice fits comfortably in one session with its docs and tests.
- **Docs-first orientation per slice**: read the relevant doc section and `GOTCHAS.md` entry
  *before* the code (the project already mandates this). The doc states intended behavior; the
  audit's job in that slice is to find where code diverges from doc, duplicates itself, or
  hides an island.
- **Findings ledger, not memory.** Every session appends structured findings
  (`FINDING-nnn: location, category [duplication|legacy|fragile|security|island|doc-drift],
  severity, proposed disposition`) to a single ledger file. Sessions are stateless and
  resumable; the ledger is the only cross-session state, and it doubles as the peer-review
  artifact.
- **Two-pass discipline**: Pass 1 (breadth) touches every module once, only classifying and
  ledgering — no fixes. Pass 2 (depth) works the ledger by severity. This prevents the classic
  failure mode of deep-diving the first ugly file found and never finishing the map.

---

## 2. Legacy Deprecation & Feature Parity

**Principle: strangler fig, already half-grown — finish it deliberately.**

### 2.1 Identification
- A module is *legacy* when it satisfies any of: (a) a modern package covers the same concern
  (table in §0); (b) unreachable from any entry point; (c) documented as superseded in
  `ROADMAP.md`/memory (e.g., workbook-as-input paths superseded by `parts_db.json`);
  (d) only tests import it.
- For each legacy unit, record in the ledger: modern replacement, **capability diff** (anything
  the legacy code does that the replacement doesn't), and which tests pin it.

### 2.2 Retirement protocol (per legacy unit, in order — no step may be skipped)
1. **Parity proof**: enumerate the legacy unit's observable behaviors against
   `FEATURE_INVENTORY.md`; confirm each is covered by the replacement *and by a test against
   the replacement*. Any uncovered behavior is either ported or explicitly sentenced in the
   decision log ("dropped because X") — never silently lost.
2. **Test migration**: rewrite legacy-pinning tests to target the modern API. Tests that
   encode legacy-only behavior become characterization tests on the replacement first.
3. **Production cutover**: repoint every remaining production consumer — currently
   `generator.py` (config_loader/input_reader/planner), `template_builder.py` (config_store),
   and the `pyproject.toml` `[project.scripts]` entry (`gui_server:main`) — to the modern
   packages, under the golden-master pins. Packaging entry points count as consumers, **for
   every target OS**: after an entry-point change, smoke-launch the macOS artifact
   (`packaging/build_macos.sh`) locally *and* verify the Windows installer
   (`packaging/build_windows.ps1` / Inno Setup EXE) via the `build-windows` CI job in
   `build.yml` — the Windows artifact only builds in CI, so a green local Mac launch proves
   nothing about it.
4. **Shim window**: legacy module becomes a thin delegating shim (or is confirmed already
   dead), one release/validation cycle passes with real usage.
5. **Delete**, update docs (`FEATURE_INVENTORY.md`, `ARCHITECTURE.md`, `GOTCHAS.md` entries
   that referenced it), record in `ROADMAP.md` decision log.
- **Workbook phase-out is the special case**: it is a documented strategic direction, not a
  cleanup. Retire *input/source-of-truth* roles only; the workbook-as-renderer output path is
  a keeper and a future feature. The Excel *reading* path stays until parts_db/projects fully
  replace it (ROADMAP Phase 4 consumer migration).

---

## 3. Zero-Regression & Validation

**Principle: pin behavior before touching it; the pin, not the reviewer, is the safety net.**

### 3.1 Before (per slice, mandatory gate)
- **Golden-master (characterization) tests on the terminal outputs.** The app's ultimate output
  is deterministic files: `.pptx` build sheets and JSON stores. Establish a corpus of
  representative inputs (`samples/`, real projects) → generate outputs → snapshot a normalized
  structural digest (shape tree, text, positions — not raw zip bytes, which contain
  timestamps). Any refactor of planner/renderer must reproduce digests bit-for-bit.
- **HTTP contract snapshots.** Freeze the route table of `app/server.py`: for each endpoint, a
  recorded request/response pair. This catches backend-side contract drift, but is **not**
  sufficient for the UI: the classic-script JS layer holds its own state and logic and can
  regress even against an unchanged contract.
- **Automated browser smoke suite** (driven through the preview/browser tooling against the
  running app) covering the highest-risk UI flows: every tab loads without console errors;
  Part Picker open → filter → select → place; manifest add/remove
  (`manifest_editor.js`); SKU grid edit + save round-trip (`sku_grid.js`); project open/edit/save;
  cloud status refresh. These flows sit exactly where the near-term roadmap work lands
  (`part_picker.js` ~1,600 LOC, `app/routes/parts_db.py` ~1,240 LOC), so they must be pinned
  before that code is touched. **Isolation between flows is mandatory**: the UI is
  classic-script with DOM-singleton state (`UI_STRUCTURE.md`), so each smoke flow starts from
  a hard page reload against a fresh app workspace — no flow may depend on or inherit DOM/JS
  state from a previous one. Flaky-by-state-bleed is a suite defect, not a retry candidate.
- **No test suite may touch production cloud.** The codebase already hard-guards pytest:
  `PYTEST_CURRENT_TEST` without `DTM_ALLOW_CLOUD_IN_TESTS=1` blocks cloud paths in
  `app/adapters/wiring.py`, `shared_work_service.py`, `exports_upload_service.py`, and
  `qb_sync_service.py` (a guard earned from a real incident — see ROADMAP's outbound-queue
  junk-guard entry). Two obligations follow: (1) that guard is a **preserve-invariant** — no
  Phase E refactor may weaken or bypass it, and golden-master runs stay under pytest so they
  inherit it; (2) the browser smoke suite runs the *live app*, where the pytest guard does not
  apply and a dev workspace auto-enters cloud mode via `workspace/cloud_config.json` — so the
  smoke suite must launch the app against an isolated workspace with cloud disabled (no
  `DTM_CLOUD`, no `cloud_config.json`), and assert zero Graph/SharePoint traffic during the
  run. Cloud-path behavior itself is tested only against mocked adapters or a sandbox site,
  never the team SharePoint.
- **Coverage floor per slice**: a slice may not enter Pass-2 refactoring until its behavior is
  pinned (golden masters + contract tests + existing unit tests green). "Untested" is a
  finding, not an excuse.

### 3.2 During
- **Small, reversible increments**: one ledger finding (or one coherent cluster) per branch;
  full pytest suite + golden masters green before merge; refactor commits never mixed with
  behavior-change commits (mechanical moves reviewable as moves).
- **Behavior changes are opt-in only**: if a refactor *improves* behavior (per the "same or
  better" allowance), the golden master is updated in its own commit with a decision-log
  entry — an intentional diff, never an incidental one.

### 3.3 After
- **Manual GUI verification pass** per completed slice using the `verify`/`run` workflow:
  drive the real app through the affected tab(s) against a checklist derived from
  `FEATURE_INVENTORY.md`. Automated pins catch backend drift; only the live app catches
  DOM/JS integration drift (the UI is classic-script + DOM-singleton, the least
  statically-checkable part of the system).
- **CI enforces the ratchet**: full suite + golden masters on every PR; coverage may not
  decrease; import-boundary rules (§4) enforced by lint so consolidation can't silently erode.

---

## 4. Architecture & Consolidation

**Principle: the target architecture is already chosen — converge on it, don't invent a new one.**
`ARCHITECTURE.md` + `app/adapters/` define it: layered core
(**domain → planning/rules → services (config/storage/inputs) → app/HTTP → UI**) with
ports-and-adapters at the boundary, explicitly to serve the future customer-facing and
external-sale variants.

- **Codify the layer rules as lint** (import-linter or equivalent): domain imports nothing
  app-ward; planning imports domain only; UI talks only to the HTTP contract; all external
  I/O (Graph, QB, filesystem, keychain) behind `app/adapters/interfaces.py`-style ports.
  **The lint launches with a grandfathered-exception baseline** — the target rules are
  violated today (known case: `planning/planner.py` lazy-imports
  `app.services.parts_db_service` as a catalog fallback, an upward dependency from planning
  into app). Phase A enforces "no *new* violations"; each baselined exception becomes a
  ledger finding whose fix (here: move parts-DB access behind a lower-level repository that
  both planning and app consume) is scheduled in Phase E. The baseline may only shrink.
  In addition to the baseline, one rule is **absolute from day one**: no newly written or
  modernized code may import a legacy shim (`planner`, `models`, `config_loader`,
  `config_store`, `config_validation`, `input_reader`, `gui_server`) — enforced as a
  forbidden-import contract with the current consumers (§0 table) as the only allowed
  callers. Otherwise ongoing feature work quietly extends shim lifetimes and Phase D never
  converges.
- **Duplication hunt is structural, not textual.** Textual clone detection (jscpd/PMD-CPD)
  is run once for cheap wins, but the important duplicates are *conceptual*: two code paths
  answering the same question (e.g., SKU/color/location resolution living in both a legacy
  module and a `planning/` resolver; JS re-deriving logic the server already exposes). The
  per-slice audit explicitly asks: "what question does this answer, and who else answers it?"
  Each concept gets exactly one home; everyone else calls it.
- **Island detection**: features reachable from an entry point but importing none of the shared
  domain/services (own file formats, own persistence, own duplicated models) are islands.
  Disposition per island: integrate behind existing ports, rebuild on the core, or retire via
  §2 — decided in the ledger, executed in Pass 2. Candidate zones to check first: `relay/`,
  `scripts/`, `tools/`, older tabs' JS, any per-feature JSON sidecar files.
- **DRY with judgment**: consolidate *knowledge* (schemas, business rules, name-formatting,
  vehicle-zone math), tolerate benign repetition in glue. No speculative abstraction — an
  abstraction must be demanded by two real call sites or one documented future feature (§7),
  per `REPOSITORY_PRINCIPLES.md`.

---

## 5. Resilience & Technical Debt

**Principle: measure fragility, rank it, and fix it where change pressure is highest.**

- **Fragility signals collected mechanically during Pass 1**: LOC/complexity outliers —
  ranked by change pressure, the top of the list is **not** the old renderer:
  `app/routes/parts_db.py` (~1,240 LOC, placement/category/product logic living in the route
  layer) and `ui/js/part_picker.js` (~1,600 LOC) sit directly under the picker-cluster and
  kit-SKU work and outrank `ppt_helpers.py` (~1,750 LOC, large but stable) for early
  attention. Also: functions with mixed abstraction levels, stringly-typed dict plumbing where `domain/` dataclasses exist, broad
  `except:`s, hidden global state (the JS DOM-singleton pattern documented in
  `UI_STRUCTURE.md`), and every `GOTCHAS.md` entry — a gotcha is, by definition, debt that has
  already bitten someone.
- **Rank by (fragility × change pressure)**: cross-reference against git churn and against the
  planned-feature list (§7). Fragile code that the picker cluster, kit SKUs, or shipped cloud sync
  will have to modify gets fixed *first*; fragile-but-frozen code is ledgered and left alone.
  Debt in the way of the roadmap is the only debt worth paying down now.
- **Recode standard** (definition of done for any rewritten unit): single responsibility;
  typed inputs/outputs from `domain/`; effects behind ports; failure modes explicit (validated
  at boundaries, impossible-by-construction inside); pinned by tests written *before* the
  rewrite; the corresponding `GOTCHAS.md` entry deleted because the footgun no longer exists.
  A rewrite that still needs its gotcha entry isn't done.
- **Scaling posture**: the stress vectors are data volume (thousands of QB SKUs), team
  concurrency (shared SharePoint workspace), and surface growth (more views, more tabs, second
  app). Rewrites must avoid O(all-parts-in-memory-per-request) patterns, avoid
  last-writer-wins file semantics where the cloud layer will need merge/conflict behavior, and
  avoid any new "exactly four views"-style hardcoding.

---

## 6. Security & Stability

**Principle: audit the trust boundaries first; harden the parsers second; fuzz the rest.**
`EXTERNAL_CONNECTION_SECURITY.md` is the binding standard — the audit checks conformance to it
rather than inventing new policy.

- **Boundary inventory** (each gets a dedicated audit session): (1) the local HTTP server
  (port 7655) — bind address, absence of auth, CORS/DNS-rebinding exposure, path handling on
  file-serving routes; (2) the QuickBooks OAuth flow *including the deployed `relay/`
  functions* (token handling, redirect validation, what transits/persists in Netlify);
  (3) Microsoft Graph/SharePoint (scopes vs. least privilege, localhost redirect URI flow);
  (4) `credential_store.py` — verify the "secrets never touch disk/cloud" invariant with a
  repo-wide taint check (no token/secret ever passed to a write path, logger, or cloud payload);
  (5) the GitHub Actions sync glue (what a malicious/compromised settings PR could inject).
- **Untrusted-input hardening**: every parser that consumes user- or cloud-supplied bytes —
  `excel_reader`, `project_codec`, config/preset/parts_db JSON loaders, HTTP request bodies —
  gets schema-validation-at-the-boundary review plus property-based/fuzz tests (hypothesis)
  for crash-freedom and error-message quality. Internal breakage hunting focuses on the same
  spots: partial writes (verify `storage/safety.py` covers all mutation paths, atomically),
  concurrent GUI actions, and stale-draft/migration edge cases in `config/migrations.py`.
- **Standing tooling, not one-off effort**: dependency audit (`pip-audit`) and static scanning
  (`bandit`, `semgrep`) wired into CI during Phase A so the floor ratchets; a `/security-review`
  pass is mandatory on any PR touching a boundary module.
- **Stability triage rule**: any crash found is fixed with a regression test in the same PR —
  bugs found during audit don't go to a backlog to die.

---

## 7. Documentation Alignment & Future-Proofing

**Principle: docs are the spec; drift is a defect in whichever side is wrong.**

- **Three-way reconciliation per slice**: code vs. docs vs. tests. Four outcomes, all ledgered:
  code wrong (fix code), doc stale (fix doc), feature documented-but-unbuilt (register as a
  *seam requirement*, below), feature built-but-undocumented (document or sentence to §2).
  `FEATURE_INVENTORY.md` is the parity master list for the whole engagement — §3's checklists
  and §2's parity proofs both key off it.
- **Seam-requirement register**: every planned feature is translated into a concrete
  architectural obligation the refactor must satisfy, and each is checked as a review item on
  refactors in its area. Initial register:
  | Feature (status) | Seam the refactor must preserve/create |
  |---|---|
  | Cloud sync (SHIPPED v2.2.9+) | **preserve**: all persistence through the `StorageProvider`/adapter ports; the dual write path (direct SP write *and* proposal enqueue) and its ordering; outbound-queue junk guards; eTag-based 60s sync; no direct `open()` in feature code; file formats merge-tolerant |
  | GitHub invisible review layer (SHIPPED) | **preserve**: settings changes remain serializable, diffable proposals; audit record still fires even though SP is authoritative |
  | QB Pass-2 / kit SKUs | parts_db access behind one repository module; SKU model composable (a SKU can reference SKUs); **preserve the shipped three-axis model** (`part_type.category` = what it is · zone = where on the vehicle · build section = how it groups) — never conflate the axes |
  | Parts-DB conventions (SHIPPED, load-bearing) | **preserve**: `location_mode` + `location_options` on every part_type; accessory roles/categories; pending-QB parts flow; light/unbilled tags; warning-light single-home semantics; the "no part-type home" curation queue (~673 of 932 products still unhomed — refactors must not strand or reset curation state) |
  | Picker/placement cluster (NEXT on critical path) | placement data lives in domain models, not workbook remnants or JS state; route-layer placement logic in `app/routes/parts_db.py` extracted to services so the cluster lands on clean ground |
  | Extensible views | no "exactly four" constants; views iterated from data |
  | Inventory/serial tracking, parts-manager app | parts_db read/write importable without the GUI app (library-first packaging) |
  | Customer/external-sale variants | capability flags via `app/adapters/` wiring, not scattered conditionals |
- **Future-fit test for every consolidation decision**: "does this make the next documented
  phase easier, neutral, or harder?" *Harder* requires an explicit `ROADMAP.md` decision-log
  entry before proceeding — silent contradiction of the roadmap is prohibited (its own rule).
- **Exit criterion**: at engagement end, `ARCHITECTURE.md`, `DATA_MODELS.md`, and
  `FEATURE_INVENTORY.md` describe the actual repo with zero known drift, and this document is
  archived into `docs/archive/` with its ledger.

---

## 8. Execution Sequence (phases with entry/exit gates)

| Phase | Work | Exit gate |
|---|---|---|
| **A. Instrument** | Import graph, entry-point census, module manifest, findings ledger; CI ratchets (coverage floor, layer lint, bandit/pip-audit); golden-master corpus + HTTP contract snapshots | Pins green on unmodified code; ledger infrastructure in place |
| **B. Breadth audit (Pass 1)** | Every slice visited once, docs-first; classify + ledger only; textual clone scan; boundary inventory | Manifest 100% visited; ledger triaged by severity; peer agent reviews ledger |
| **C. Security & stability hotfixes** | Boundary findings and crash bugs from B, each with regression test. **Exemption**: findings located inside legacy modules already slated for Phase D retirement are fixed by that retirement, not patched twice — unless externally reachable/exploitable *now*, in which case a minimal hotfix lands immediately regardless of pending deletion | No open high-severity security/stability findings (retirement-slated ones dispositioned in the ledger as "fixed-by-D") |
| **D. Legacy retirement** | §2 protocol over the legacy/modern pairs; test migration; workbook-input phase-out per the Phase 4 consumer-migration plan | Legacy modules deleted or shimmed-with-date; parity proofs on record |
| **E. Consolidation & recode (Pass 2)** | Ledger-driven: duplicates merged, islands integrated, fragility hot-spots rewritten to §5 standard — ordered by roadmap change-pressure so the picker cluster / kit SKUs / QB Pass-2 phases land on clean ground | Layer lint fully green; ledger empty or explicitly deferred |
| **F. Reconcile & hand forward** | Doc updates, gotcha pruning, seam-register verification, archive ledger | §7 exit criterion met |

Phases C–E interleave with ongoing feature work by design: the roadmap's live critical path
(picker + placement cluster → kit SKUs → QB Pass-2 → finish the Part Picker → Phase 4
consumer migration onto parts_db; cloud is already live) continues, and each feature turn
lands on already-audited ground because E is ordered by that same critical path. Concretely,
that puts `app/routes/parts_db.py` + `part_picker.js` pinning and cleanup at the *front* of
E, and renderer-side work at the back.

**Rollback stance**: every phase-D/E branch is revertible in one command; nothing is deleted in
the same PR that replaces it; golden masters are the arbiter of any "did this change behavior?"
dispute.

### 8.1 Concrete execution plan — decided now, not deferred to the ledger

The ledger schedules *unknowns*. Everything below is already fully determined by verified
ground truth (three review rounds' worth) and starts without waiting for Phase B. Steps are
ordered against the live feature critical path; feature turns are marked ⭐.

**Step 0 — Audit workspace** *(Phase A, ~1 session)*
Create `docs/audit/` containing: `MANIFEST.md` (module inventory: path, LOC, layer,
imports in/out, legacy flag, audit status — generated by a new `tools/audit_scan.py` that
AST-walks imports) and `LEDGER.md` (findings template per §1.2).
*Done when*: every `src/` module and `ui/js` file appears in the manifest; regenerating is one
command.

**Step 1 — Pins** *(Phase A; hard prerequisite for the picker cluster turn)*
- **1a** Golden masters: `tests/golden/` — digest helper (normalized PPTX shape-tree/text/
  positions + canonical JSON), corpus drawn from `samples/` + one real project per vehicle
  type. *Done when*: two consecutive clean runs produce identical digests.
- **1b** Contract snapshots: `tests/contract/` — one recorded request/response per route in
  `app/routes/` (start with `parts_db.py` routes; they're first under the knife).
- **1c** Browser smoke suite: `tools/ui_smoke/` — the six §3.1 flows; launches the app against
  a throwaway workspace, cloud disabled, asserts zero Graph traffic; hard reload between
  flows. Not part of default pytest (needs a running app); one script to run all six.
  *Done when*: three consecutive clean runs.

**Step 2 — Guardrails** *(Phase A, lands with Step 1)*
import-linter config in `pyproject.toml`: layer contracts (§4), the absolute
forbidden-shim-imports contract, and the grandfathered baseline (currently:
`planning/planner.py` → `app.services.parts_db_service`; `generator.py` →
`config_loader`/`input_reader`/`planner`; `template_builder.py` → `config_store`). CI adds
`pip-audit`, `bandit`, and the coverage floor.
*Done when*: CI fails on a deliberately introduced new violation and passes on the baseline.

**Step 3 ⭐ — Picker + placement cluster** *(feature turn, scope per ROADMAP / PARTS_DB_AND_PICKER §7 — unchanged)*
Runs on the Step-1 pins. Boy-scout rule only: placement/category logic the cluster must touch
in `app/routes/parts_db.py` moves into `app/services/` in separate mechanical-move commits;
no wholesale route rewrite.
*Done when*: cluster items #4/#7/#5/#8b ship; `parts_db.py` route file is no larger than
before the turn; smoke suite green.

**Step 4 — Parts-DB repository extraction** *(the one refactor that gates a feature)*
One repository module for parts_db read/write (final name/home decided at implementation, but
it lives *below* `app/` so both `planning/` and `app/services/parts_db_service.py` consume
it), replacing the lazy upward import at `planning/planner.py:152`. Must be importable without
the GUI app (this is also the parts-manager-app seam, §7).
*Done when*: the lint-baseline entry for planning→app is deleted; golden masters unchanged;
curation state untouched.

**Step 5 ⭐ — Kit SKUs** *(feature turn, on the Step-4 seam)*
Composable SKU model lands in the repository/domain layer, not in routes.

**Step 6 — Legacy cutover + retirement** *(interstitial work between feature turns; §2.2 protocol per unit)*
- **6a** `generator.py` → consume `planning/`, `config/`, `inputs/` directly.
- **6b** `template_builder.py` → consume `config/`.
- **6c** Entry points: `pyproject.toml` `[project.scripts]` and
  `packaging/pyinstaller/launch_gui.py` repointed off `gui_server` to the modern app entry;
  both OS artifacts verified (macOS locally, Windows via `build-windows` CI).
- **6d** Migrate the legacy-pinning tests (`test_planner.py`, `test_input_reader.py`, etc.)
  to modern APIs; **6e** shim window, then delete the shims and their doc references.
*Done when*: the seven legacy modules are gone and the forbidden-import contract has no
allowed callers left.

**Step 7 — Phase B breadth audit** *(fills the gaps from Step 1 onward)*
Read-only, ledger-driven, stateless — pick up and drop between feature turns. Its output
populates the Phase E queue, which runs *after* kit SKUs.

**Still genuinely waiting on the ledger** (cannot be decided now): island dispositions,
duplication merges beyond the known legacy pairs, security-boundary findings (§6 sessions),
and whether renderer cleanup (`ppt_helpers.py`) ever earns a slot.

**QB Pass-2 runs throughout** as data work through `tools/qb_import_all.py` + the SKU grid;
no step above may touch the SKU-grid save path or parts_db schema outside the pins while
curation is in flight.

---

## 9. Instructions to the Peer-Review Agent

You are reviewing a *process plan*, not code. Evaluate:

1. **Ground-truth check** — re-verify §0 claims against the repo (especially: are legacy
   modules truly production-dead? is the entry-point census in §1.1 complete? `relay/` and
   `scripts/` are easy to miss).
2. **Regression-net sufficiency** — is §3 airtight for a GUI app whose UI layer is
   classic-script JS with no type system? Propose additional pins if you see a gap
   (e.g., JS-side smoke automation via the preview/driving tooling).
3. **Sequencing risk** — does any phase-D deletion plausibly precede its parity proof? Does
   phase-E ordering actually match `docs/ROADMAP.md`'s current critical path?
4. **Seam register completeness** — diff §7's table against `docs/ROADMAP.md` §1/§4 and
   `docs/PARTS_DB_AND_PICKER.md`; add any documented future feature lacking a seam obligation.
5. **Scope discipline** — flag anything in this plan that drifts into line-level prescription
   or invents policy that contradicts `docs/REPOSITORY_PRINCIPLES.md`.

Deliver findings as numbered objections with severity (blocking / should-fix / note), so they
can be dispositioned in this document's next revision.

---

## 10. Revision Log

| Rev | Date | Change |
|---|---|---|
| 1.0 | 2026-07-06 | Initial plan. |
| 1.1 | 2026-07-06 | Peer review round 1 — all six findings verified against the repo and accepted. **Blocking #1** (legacy modules still production-imported via `generator.py`, `template_builder.py`, and the `pyproject.toml` entry point): §0 corrected, explicit production-cutover step added to the §2.2 protocol. **Blocking #2** (cloud go-live already shipped v2.2.9+): §0, §7 seam register, and §8 critical-path ordering updated; cloud reclassified from create-seam to preserve-obligation. **Should-fix #3** (layer lint violated today by `planning/planner.py` → `app.services` lazy import): §4 lint now launches with a shrink-only grandfathered baseline. **Should-fix #4** (UI regression net too weak): §3.1 claim softened; automated browser smoke suite added for tab load, picker flow, manifest add/remove, SKU grid save, project open/edit, cloud status refresh. **Should-fix #5** (hotspot ranking stale): §5 reprioritizes `app/routes/parts_db.py` (~1,240 LOC) and `part_picker.js` (~1,600 LOC) above `ppt_helpers.py`. **Note #6** (seam register too generic): §7 now names the shipped parts-DB conventions to preserve (three-axis model, `location_mode`, accessory roles, pending-QB, unbilled tags, warning-light single-home, curation queue). |
| 1.2 | 2026-07-06 | Peer review round 2 — no blockers; two should-fixes applied. §1.1 entry-point census now includes the packaging roots (`pyproject.toml` `[project.scripts]` and `packaging/pyinstaller/launch_gui.py`, which the installed app boots through). Stale phase wording purged: "Phase 2 UI cutover" / "Phase-2 cutover plan" → Phase 4 consumer migration (§2.2, Phase D); "cloud go-live" / "cloud phases" → shipped cloud sync / QB Pass-2 (§5, Phase E). **Plan is execution-ready**; next step is Phase A (Instrument). |
| 1.3 | 2026-07-06 | Peer review round 3 (fresh reviewer) — five findings, all accepted after repo verification, one reframed. **#1 cloud-mutation risk (filed blocking)**: partially stale — pytest cloud paths are already hard-guarded by `PYTEST_CURRENT_TEST`/`DTM_ALLOW_CLOUD_IN_TESTS` in wiring + three services (existing code, from a real incident); the genuine gap was the browser smoke suite driving the live app on a cloud-enabled dev workspace. §3.1 now: guard is a preserve-invariant; smoke suite runs cloud-disabled in an isolated workspace and asserts zero Graph traffic; cloud behavior tested only via mocks/sandbox. **#2**: Phase C now exempts retirement-slated legacy modules (fixed-by-D disposition) unless exploitable now. **#3**: smoke flows mandated to hard-reload between boundaries (DOM-singleton state bleed). **#4**: absolute forbidden-import contract on legacy shims for new/modernized code, alongside the shrink-only baseline. **#5**: verified Windows target exists (`build_windows.ps1`, `build-windows` CI job, Inno EXE); §2.2 cutover gate generalized to all target-OS artifacts, Windows verified via CI. |
| 1.4 | 2026-07-06 | Added §8.1 concrete execution plan: the phases converted into ordered, real steps with file targets and definitions of done (audit workspace → pins → guardrails → ⭐picker cluster → parts-DB repository extraction → ⭐kit SKUs → legacy cutover → breadth audit in the gaps). Rationale: the near-term work is dominated by knowns verified in review rounds 1–3; only islands/duplication/security findings still wait on the Phase B ledger. QB Pass-2 curation declared always-in-flight; SKU-grid save path and parts_db schema untouchable outside the pins. |
