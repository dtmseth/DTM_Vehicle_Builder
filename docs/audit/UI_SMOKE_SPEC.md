# Browser Smoke-Harness Specification (§8.1 Step 1c — design)

> **Status**: design + validated feasibility prototype (this session). The prototype at
> `tools/ui_smoke/` boots the app hermetically and runs flow 1 (tab load) end to end —
> three consecutive clean runs recorded. The other five flows are **specified here, not
> built**; implementation is the follow-up Sonnet session — see §8.
>
> **What this pins**: the six highest-risk UI flows from roadmap §3.1, driven through a
> real browser against the live app (not pytest). This suite is also the enforcement
> mechanism for the §4 rule "UI talks only to the HTTP contract" — Step 2 confirmed
> import-linter cannot express that rule for classic-script JS.

---

## 1. Empirical boot findings (deliverable 1 — verified, not assumed)

**Question**: can the HTTP server run and serve the UI to a plain browser without the
native pywebview window? **Answer: yes**, verified by the prototype.

- `app/server.py` `main()` builds the server as plain composable pieces:
  `Handler.paths = <AppPaths>` → `_ReuseHTTPServer(("127.0.0.1", PORT), Handler)` →
  `serve_forever()` in a daemon thread. The webview window is just a client of that
  server; nothing in the request path touches pywebview. The harness boots
  `Handler` + `_ReuseHTTPServer` directly, in-process, and Chromium renders the full UI.
- **No server-only mode exists in `main()` itself**: with pywebview installed it always
  opens the native window; the `ImportError` fallback opens the system browser and binds
  the fixed port 7655. Neither is automatable as-is. Per the Step 1c constraint the
  prototype does **not** touch production code; instead the harness replicates `main()`'s
  boot (see §3.3 for the exact deltas). *Follow-up for the implementation session
  (optional)*: extract a `serve(paths, *, port=PORT, open_window=True)` helper from
  `main()` so the harness and production share one boot path. Low priority — the harness
  boot is six lines against stable internals, and if those internals ever change the
  smoke suite fails loudly at boot, not silently.
- **Port**: the harness binds port 0 (OS-assigned ephemeral). Verified: the UI uses
  relative URLs everywhere (`api.js` `fetch(path)`), so the port is invisible to it, and
  a developer's live instance on 7655 can never collide with a smoke run. The two
  "7655" strings in `index.html` are cosmetic text.

## 2. Isolation design (deliverable 2)

### 2.1 The threat model

The pytest cloud guard (`PYTEST_CURRENT_TEST` in `wiring.py` et al.) does **not**
protect this harness — the app runs live. Worse, two dev-mode facts make naïve launches
actively dangerous:

1. The repo's live `workspace/cloud_config.json` has `enabled: true` — a default launch
   enters cloud mode and syncs against the team SharePoint.
2. `cloud/config.py` `cloud_config_path()` reads the **module-level `WORKSPACE_DIR`
   constant**, not the injected `AppPaths` — so a hermetic workspace *alone* does not
   disable cloud. (Same class of leak as any other module-constant path use; the
   netguard in §4 is the backstop for all of them.)
3. `ensure_workspace()` deliberately **seeds `cloud_config.json` into any fresh
   workspace** from `resources/default_data/` (teammate first-launch convenience). The
   harness therefore must never call it.

### 2.2 Isolation layers (all three, always)

| Layer | Mechanism | What it stops |
|---|---|---|
| 1. Env | `DTM_CLOUD=0` set before any app import | Cloud mode entirely — env wins over any `cloud_config.json` anywhere (`cloud_enabled()` checks env first) |
| 2. Workspace | Throwaway tmp workspace per flow via `dataclasses.replace(AppPaths(), …)` — the same hermetic-AppPaths concept as `GOLDEN_MASTER_SPEC.md` §5.3, shared not reinvented. Seeded like a bundled install (`resources/config/*.json`, assets, presets), **no `cloud_config.json`**, `ensure_workspace()` never called | Mutation of the live `workspace/` (QB curation is in flight there; the SKU-grid flow writes `parts_db.json`) and of the dev-mode `resources/config/` (which in dev *is* the workspace config dir) |
| 3. Netguard | Process-wide `socket.getaddrinfo` + `socket.connect` tripwire: any non-loopback host → recorded + raised (§4) | Everything the first two layers might miss, including module-constant path leaks and any future code that ignores injected paths |

The SKU-grid flow's mutations land only in the throwaway copy of `parts_db.json`; the
repo's schema and save path are untouched, and the live curation state can't be
stranded or reset.

### 2.3 Reset model: one subprocess per flow

Roadmap §3.1 mandates that each flow start from a hard page reload against a fresh app
workspace. The harness goes one step stronger: **each flow runs in its own child
process** (`run_smoke.py --child <flow>`), which builds its own workspace, boots its own
server on its own ephemeral port, launches a fresh headless browser context, runs
exactly one flow, and exits. This resets all four state layers at once:

- DOM/JS state (fresh page + context — the UI is classic-script with DOM singletons),
- browser state (cookies/cache — fresh context),
- server-side module state (`wiring._active_bundle`, agency/sales-rep/parts_db service
  caches, `server.py` sync globals — fresh interpreter),
- filesystem state (fresh workspace).

State bleed between flows is structurally impossible, and per §3.1 any flakiness that
smells like state bleed is a **suite defect to fix, not retry**.

### 2.4 Harness boot vs production boot (faithfulness deltas)

`hermetic.boot_server()` replicates `main()` except:

| Delta | Why acceptable |
|---|---|
| No pywebview window / system browser | The window is a client; the suite substitutes Chromium |
| No queued-installer check | Update-install machinery, irrelevant to UI flows, and it can `sys.exit(0)` |
| No periodic-sync thread | With cloud off, every iteration is an inert no-op chain; excluding it removes a 60s background tick from smoke timing. Flow 6 exercises the same code path deterministically via the Force-sync button (`run_sync_now` directly) |
| No QuickBooks background sync | No-op without a connected company (none in the throwaway workspace), and the dev machine's keychain **does** hold live QB tokens — the harness must never give live code a reason to use them. The netguard would catch any attempt (intuit.com is non-loopback) |
| Port 0 instead of fixed 7655 | §1; no `_port_is_busy` SystemExit, no collision with a dev instance |

Kept identical: `_setup_logging` (app log lands in the throwaway workspace for
debugging), `agency_service`/`sales_rep_service` cache warmup, `Handler` +
`_ReuseHTTPServer` construction, single-threaded HTTPServer semantics.

### 2.5 Fixture data (sufficient for all six flows)

- **Config** (flows 1, 4): seeded at run time from `resources/config/*.json` — same glob
  `ensure_workspace()` uses for a bundled install (top-level JSON only; the 20 MB
  `history/` subtree is not copied). This includes the real `parts_db.json` (~930
  products), so the SKU grid and Part Picker exercise production-shaped data with zero
  fixture maintenance. Flows make **content-agnostic** assertions (first visible
  product, round-trip of a value the flow itself wrote) so ongoing QB curation never
  breaks them.
- **Assets / presets**: copied from `resources/assets/` (46 MB, ~1–2 s) and
  `resources/presets/`. Fully hermetic — even an accidental asset write can't touch the
  repo.
- **Projects / drafts** (flows 2, 3, 5): committed fixture overlay at
  `tools/ui_smoke/fixtures/workspace/` (`projects/{id}/project.json`,
  `drafts/{id}.json`), copied onto the throwaway workspace after seeding. *Recorded in
  the implementation session*: export one real PIU project + its draft, sanitize
  (project id `SMOKE-PIU-001`, agency/customer "Smoke Test PD", strip real contact
  data), commit. One project with one build unit and a small manifest is sufficient for
  all three stateful flows.
- **Cloud** (flow 6): needs nothing — the absence of cloud is the fixture.

## 3. Driver choice (deliverable 3)

**Playwright (Python, sync API), headless Chromium.** Dev-dependency only — not in
`[project.dependencies]`; the implementation session adds an optional extra
(`ui-smoke = ["playwright>=1.61"]`) plus `python -m playwright install chromium`
(one-time ~100 MB, cached in `~/Library/Caches/ms-playwright` / CI cache).

| Requirement | Playwright answer |
|---|---|
| Console-error capture | First-class: `page.on("console")` + `page.on("pageerror")` — both wired in the prototype; catches JS exceptions *and* failed-resource errors (404'd assets) |
| Network interception | First-class: `context.route("**/*")` with per-request abort/continue and full request metadata — used for the browser-side egress capture (§4) |
| Determinism | Auto-waiting locators, pinned browser build per Playwright version (no system-Chrome drift), explicit `wait_for_selector` on state transitions |
| Fit for this suite | Sync API keeps flow scripts linear and readable for the implementation session; headless Chromium runs fine on macOS dev machines and Linux CI without pywebview |

Rejected: **Selenium** (console log + network capture require CDP bolt-ons and a
system-browser/driver version dance — exactly the flake source a smoke suite can't
afford); **pyppeteer** (unmaintained); **driving the real pywebview window** via OS
automation (slow, macOS-only, permission-gated, and §1 shows the webview adds nothing —
the server is the contract).

## 4. Zero-Graph assertion (deliverable 4)

**Decision: both layers — app-side netguard (primary) + driver-level capture
(secondary).** The key fact forcing this design: **Graph/SharePoint traffic originates
in the Python server process** (`requests`/`msal` inside the app), *not* in the browser.
Driver-level network capture alone can never see it, so an app-side hook is mandatory.

- **Primary — process-wide socket tripwire** (`hermetic.install_netguard()`), installed
  before any app import: patches `socket.getaddrinfo` (hostname level — everything that
  resolves `graph.microsoft.com` / `login.microsoftonline.com` / any other external host
  goes through it: requests, msal, urllib) and `socket.socket.connect` (IP level —
  backstop for direct-to-IP dials). Non-loopback → the attempt is **recorded** in
  `NETGUARD_VIOLATIONS` **and raised**, so the flow both fails the assertion and never
  actually egresses. This is deny-all-egress, deliberately stronger than zero-Graph: with
  cloud off and a hermetic workspace, the app process has no legitimate reason to reach
  *any* external host (also covers QB/intuit.com, update checks, telemetry).
  Blind spot (accepted, documented): traffic from a *separate* process the app might
  spawn wouldn't be caught — no such path exists today.
- **Secondary — browser-side capture**: `context.route("**/*")` aborts and records any
  request whose host isn't loopback. Catches what the netguard can't see (the browser is
  a separate process): CDN references, absolute external URLs in the UI, third-party
  fonts. Doubles as a partial enforcement of "UI talks only to the HTTP contract".
- Playwright itself is unaffected by the netguard: its driver is a subprocess reached
  over stdio pipes, and the browser talks back only to 127.0.0.1.

**Assertion**: a flow passes only if `NETGUARD_VIOLATIONS == []` **and**
`external_browser_requests == []`. Both lists are printed in the per-flow JSON verdict.

## 5. The six flows (deliverable 5 — step-and-selector level)

Common to every flow: runs in its own subprocess (§2.3), starts with `page.goto(base_url)`
(a hard load against a fresh workspace), and inherits the universal assertions —
**zero console errors, zero page errors, zero external browser requests, zero netguard
violations** — on top of its own listed assertions. Selectors below were read from
`index.html` / the JS modules this session; the implementation session re-verifies each
against the running app (marked ⚠ where a selector is inferred rather than confirmed).

Empirical baseline from the prototype: the app currently produces **zero** console
errors across every tab/stab — the known-benign allowlist starts **empty**, and any
future entry requires a comment justifying it (e.g. if the cloud photo 404-fallback ever
surfaces; it does not under cloud-off, where no photo fetch is attempted).

### Flow 1 — `tab_load` (BUILT — prototype)

Every tab, stab, and inner-stab activates cleanly.

1. `goto` → wait `.htab[data-tab='projects']`.
2. Click `.htab[data-tab='projects']` → wait `#tab-projects:not([hidden])`.
3. Click `.htab[data-tab='general-settings']` → wait `#stab-bar-general:not([hidden])`;
   click each `.stab[data-stab=…]` of `projects-defaults, agencies, sales-reps, presets,
   quickbooks`.
4. Click `.htab[data-tab='advanced-settings']` → wait `#stab-bar-advanced:not([hidden])`;
   `placements` → inner stabs `placements, fixtures`; `sizes`; `part-manager` → inner
   stabs `sku-grid, parts-db, catalog, parts`; `vehicles`; `workbook-tools`.
5. `wait_for_load_state("networkidle")` so late fetch failures are captured.

Assertions: universal only (that's the point of this flow).

### Flow 2 — `part_picker` (open → filter → select → place)

Precondition: fixture project + draft (§2.5).

1. Projects tab → click `.proj-row-clickable` (fixture project) → wait
   `#proj-detail-view:not([hidden])`.
2. Open the Builds sub-tab → click the unit card's **Setup/Edit Build** button ⚠ →
   wait `#proj-build-editor` visible with `#pbe-manifest-section` rendered.
3. Click the first `.me-cat-add-btn` in the manifest (manifest add opens the picker —
   `manifest_editor.js:231` → `openPicker()`) → wait `#picker-panel.open`.
4. **Filter**: in `#picker-filters`, select a part-type filter ⚠ (first available
   option) → assert `#picker-products` re-renders with ≥1 product card.
5. **Select**: click the first product card in `#picker-products` → assert the picker
   advances (Location tab `#picker-tab-btn-location` becomes active / enabled).
6. **Place**: in `#picker-pane-location`, click the first placement dot in
   `#picker-loc-dots` (or location button in `#picker-loc-btns` for `location_mode:
   options` part types) → assert `#picker-add-btn` becomes enabled.
7. Click `#picker-add-btn` → assert panel closes and the manifest gains one row.

Assertions: manifest row count +1; the draft-save POST (`/api/draft/…`) returned 200
(via driver response capture); picker footer never showed an error state.

### Flow 3 — `manifest_add_remove` (`manifest_editor.js`)

Precondition: fixture project + draft. Steps 1–2 as flow 2.

1. Record manifest row count (`tr.me-parent-row` count).
2. **Add**: minimal picker completion (flow 2 steps 3–7).
3. Assert row count +1 and the new row shows the selected part's name.
4. **Persistence across hard reload**: `page.reload()` → renavigate to the build editor
   (steps 1–2) → assert the added row is still present (draft round-tripped through
   `/api/draft/` storage, not just DOM state).
5. **Remove**: click the added row's `.me-del-btn` → confirm dialog if present ⚠ →
   assert row count back to baseline.
6. Hard reload + renavigate again → assert the row stayed gone.

### Flow 4 — `sku_grid_roundtrip` (`sku_grid.js`, against the throwaway parts_db)

1. Advanced Settings → `part-manager` → inner stab `sku-grid`; wait `#skg-body` has ≥1
   `.skg-prod`.
2. Expand the first product: click its `.skg-prod-head`.
3. Edit: fill `input[data-skg="pfield"][data-field="model"]` with
   `SMOKE-EDIT-<runid>`, dispatch `change` (grid saves immediately via
   `/api/parts-db/edit/product-update`).
4. Wait for the save flash: `#skg-meta` text becomes `Saved ✓`.
5. Round-trip: click `#skg-reload` → wait re-render → search `#skg-search` for
   `SMOKE-EDIT-<runid>` → assert exactly one matching `.skg-prod` shows the value.
6. Server-side confirmation: harness reads `<workspace>/config/parts_db.json` from the
   throwaway workspace and asserts the value landed on disk.

Note: mutations touch only the throwaway copy (§2.2 layer 2); the repo's `parts_db.json`
and the live curation state are unreachable by construction.

### Flow 5 — `project_open_edit_save`

1. Projects tab → click the fixture `.proj-row-clickable` → wait `#proj-detail-view`.
2. Open the Edit sub-tab (`#proj-ptab-edit`) → click the **✏️ Edit** button
   (`detail_edit.js` `PT_enterEditMode`) → assert inputs become editable.
3. Change one low-risk field (e.g. contact name ⚠ exact input selector at
   implementation) to `Smoke Edited <runid>`.
4. Click **💾 Save Changes** (`PT_saveEditForm`) → assert success toast / detail view
   re-renders with the new value.
5. Hard reload → reopen the project → assert the edited value persisted
   (`/api/project/save` round-trip through `workspace/projects/{id}/project.json`).

### Flow 6 — `cloud_status_offline` (cloud-OFF is the assertion, not a skip)

The harness runs cloud-disabled by design, so this flow pins the **graceful
local-mode behavior** — the exact state every refactor must preserve for offline/
disabled installs:

1. `goto` → wait for the header chip to leave its loading state: `#cloud-status-text`
   text becomes **"Local mode"** and `#cloud-status` has class `cloud-status-local`
   (per `api.js` `refreshCloudStatus()` when `cloud_enabled` is false). It must never
   show "Offline" (server unreachable) or an error state.
2. API contract: GET `/api/cloud/status` (driver request) → assert
   `{"cloud_enabled": false, "signed_in": false, "user": null}` and `data_version` is an
   int.
3. Click `#cloud-status` → assert `#cloud-modal.open` with the signed-out section
   (`#cloud-modal-signed-out`) visible.
4. Click `#cloud-modal-sync` (**Force sync now** — drives `run_sync_now` directly,
   covering the code path the harness's boot skips per §2.4) → assert the POST returns
   an `ok` report, the chip still reads "Local mode", and — the core of this flow —
   **the netguard recorded nothing**: a full forced sync cycle with cloud disabled must
   produce zero egress.

Universal assertions do the rest: zero console errors proves the UI degrades cleanly
with cloud off.

## 6. Failure semantics & flake policy

- A flow **fails** if any of: a step raises (missing selector / timeout), any console
  error or page error, any external browser request, any netguard violation. All four
  are reported in the per-flow JSON verdict; the throwaway workspace (including the app
  log inside it) is **kept and its path printed** on failure, deleted on success.
- **No retries, ever.** Per roadmap §3.1, flaky-by-state-bleed is a suite defect; the
  per-flow-subprocess model removes the state-bleed cause, so any remaining flake is
  either a missing readiness wait in the flow (fix the wait — prefer
  `wait_for_selector` on a concrete state transition over `wait_for_timeout`) or a real
  app bug (file it / fix it). CI must not wrap the suite in a retry action.
- Suite exit code: nonzero if any flow failed; flows are independent, so all flows run
  even after a failure (one report per run, not fail-fast).
- **Done-gate** (per §8.1 Step 1c): three consecutive fully-clean runs of all six flows.
- The suite is **not part of default pytest** and must not run under pytest: pytest
  would set `PYTEST_CURRENT_TEST`, engaging the cloud guards and making the run
  unrepresentative of the live app the suite exists to pin. It lives in `tools/`, run as
  one script: `.venv/bin/python tools/ui_smoke/run_smoke.py`.

## 7. Prototype validation results (this session)

- Hermetic boot verified: in-process `Handler` + `_ReuseHTTPServer` on an ephemeral
  port serves the full UI to headless Chromium; `DTM_CLOUD=0` + throwaway workspace +
  netguard active.
- Flow 1 (`tab_load`, all 3 tabs / 10 stabs / 6 inner stabs): **three consecutive clean
  runs** — zero console errors, zero page errors, zero external browser requests, zero
  netguard violations, on a dev machine whose live workspace is cloud-enabled and whose
  keychain holds live QB tokens (i.e. the isolation was genuinely load-bearing, not
  vacuous).
- Full pytest suite green after the session (1666 passed, 1 skipped) — zero
  production-code changes were made.

## 8. Handoff — implementation session (Sonnet, per §8.2)

1. **Fixtures**: record + sanitize the PIU project/draft overlay into
   `tools/ui_smoke/fixtures/workspace/` (§2.5).
2. **Flows 2–6** in `tools/ui_smoke/flows.py` per §5, resolving the ⚠ selectors against
   the running app; replace `flow_tab_load`'s fixed `_SETTLE_MS` waits with per-panel
   readiness waits if they ever flake.
3. **Dependency**: add `ui-smoke = ["playwright>=1.61"]` optional extra to
   `pyproject.toml`; document the `playwright install chromium` step in
   `docs/DEVELOPMENT.md`.
4. **CI (Step 1d)**: separate job (or step after the pytest job) in `checks.yml`:
   install `.[dev]` + playwright, cache the browser download
   (`~/.cache/ms-playwright`), run `python tools/ui_smoke/run_smoke.py`. Headless
   Chromium on `ubuntu-latest` is fine — the harness never imports pywebview. Upload
   the kept-workspace dir + JSON verdicts as an artifact on failure. No retry wrapper
   (§6).
5. **Done-gate**: three consecutive clean full-suite runs locally, then green in CI.
6. **Optional, separate commit**: the `serve()` launch-hook extraction in
   `app/server.py` (§1) so harness and production share one boot path.
