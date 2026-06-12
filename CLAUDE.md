# DTM Vehicle Builder — Project Brief

## What it is
A desktop GUI app that generates PowerPoint build sheets for police/emergency vehicles. Users manage a project library, configure builds per individual unit, and export finished `.pptx` files. Runs as a local HTTP server with a web UI displayed in a native window (pywebview).

## Tech stack
- **Python 3.13+** (local dev uses 3.14 via Homebrew)
- **pywebview 5.x** — wraps WKWebView (Mac) / WebView2 (Windows) for native window
- **python-pptx** — PowerPoint output
- **openpyxl** — Excel parsing and template generation
- **Pillow, lxml** — image handling, XML
- **PyInstaller 6.x** — packaging
- **GitHub Actions** — CI builds Mac `.dmg` + Windows `.exe` installer on every push to `main`

## Repo layout
```
CLAUDE.md                          ← you are here
AGENTS.md                          ← same brief (for other AI tooling)
pyproject.toml                     ← package config, deps, entry points
README.md

src/dtm_buildsheet/                ← the Python package
  __main__.py                      ← entry point: python -m dtm_buildsheet
  gui_server.py                    ← compatibility shim → app.server.main()
  generator.py                     ← orchestrates a full CLI build-sheet run
  generator_cli.py                 ← CLI entry point
  paths.py                         ← all path logic; dev vs bundled app detection
  naming.py                        ← part/color name normalization
  template_builder.py              ← regenerates the Excel input template
  ppt_helpers.py                   ← python-pptx utilities
  render_ppt.py                    ← writes the .pptx
  reporting.py                     ← markdown summary alongside the .pptx

  app/                             ← HTTP server, routes, services
    server.py                      ← HTTP server on PORT 7655, static UI serving, route dispatch
    routes/                        ← thin route modules (parse request → call service → return JSON)
      agencies.py / assets.py / config.py / drafts.py / exports.py
      generation.py / preview.py / presets.py / projects.py
      sales_reps.py / templates.py / validation.py
    services/                      ← side effects and orchestration
      agency_service.py / asset_service.py / config_service.py / draft_service.py
      export_service.py / generation_service.py / preset_service.py / preview_service.py
      project_service.py / sales_rep_service.py / template_service.py / validation_service.py

  config/                          ← mutable workspace config load/save
    loader.py / store.py / schemas.py / migrations.py

  domain/                          ← shared dataclasses and geometry
    agency_models.py               ← AgencyRecord dataclass
    geometry.py                    ← shared placement math used by preview and PowerPoint
    input_models.py                ← ProjectInput, PartInput
    plan_models.py                 ← BuildPlan, PlannedPart, PlannedPlacement, PlannedInstance
    project_models.py              ← ProjectRecord, CustomerInfo, EquipmentPreferences, BuildUnit, IndividualUnit
    rules.py                       ← rule dataclasses
    sales_rep_models.py            ← SalesRepRecord dataclass

  planning/                        ← ProjectInput → BuildPlan
    planner.py / asset_resolver.py / color_resolver.py
    fixture_resolver.py / location_resolver.py
    override_applier.py / quantity_resolver.py

  rules/                           ← build validation and dependency rule engine
    engine.py

  inputs/                          ← input adapters
    excel_reader.py                ← Excel workbook → ProjectInput
    gui_entry.py                   ← GUI draft → ProjectInput
    project_drafts.py              ← BuildDraft persistence (workspace/drafts/)
    project_entry.py               ← ProjectRecord persistence (workspace/projects/)

  ui/                              ← browser UI served by the local server
    index.html                     ← full single-page app markup
    styles.css                     ← all CSS
    js/
      api.js                       ← fetch wrapper, shared utilities
      editor_mode.js               ← edit-mode toggle helpers
      main.js                      ← tab wiring, app init
      manifest_editor.js           ← draft manifest card (parts list editor)
      preview_canvas.js            ← build preview canvas, drag-and-drop, inspector, overrides
      projects_tab.js              ← full project manager UI (list, detail, wizard, build editor)
      state.js                     ← shared UI state
      tabs.js                      ← tab/stab switching
      canvas.js                    ← canvas helpers
      generate_tab.js              ← Standalone build-sheet generator (in Settings → Tools)
      settings/
        agencies.js / fixtures.js / part_types.js / parts_library.js
        placements.js / presets_mgr.js / sales_reps.js / size_rules.js / tools.js / vehicles.js

  resources/
    config/*.json                  ← bundled defaults (copied to workspace on first run)
    default_data/agencies.json     ← seed agency records (copied to workspace/agencies.json on first run)
    default_data/sales_reps.json   ← seed sales rep records (copied to workspace/sales_reps.json on first run)
    presets/*.json                 ← bundled default presets (dev writes here too; ships to users)
    templates/*.pptx / *.xlsx      ← bundled templates
    assets/**/*.png                ← bundled vehicle/equipment/light images

  # Compatibility shims (thin re-exports; keep until external callers are updated)
  config_loader.py / config_store.py / config_validation.py
  input_reader.py / models.py / planner.py

workspace/                         ← mutable user data (git-ignored)
  agencies.json                    ← agency database
  sales_reps.json                  ← sales rep database
  config/    ← user-edited config JSONs
  input/     ← uploaded workbooks
  output/    ← generated .pptx files
  assets/    ← uploaded images
  drafts/    ← individual build drafts (one JSON per unit)
  projects/  ← project records (one JSON per project)
  presets/   ← user presets (bundled app only; dev writes to resources/presets/)

packaging/
  pyinstaller/
    DTM_VehicleBuilder.spec        ← PyInstaller spec (handles both platforms)
    launch_gui.py                  ← entrypoint for bundled app
  windows/
    installer.iss                  ← Inno Setup script → DTM_Vehicle_Builder_Setup.exe
  icons/
    app.icns                       ← real multi-res ICNS (built via iconutil from PNG)
    app.ico                        ← 6-size ICO (built via Pillow from same PNG)
  build_macos.sh / build_windows.ps1

.github/workflows/build.yml        ← CI: parallel mac + windows builds, artifacts uploaded

samples/input/                     ← test .xlsx workbooks
tests/                             ← pytest suite
docs/
  ARCHITECTURE.md                  ← runtime shape and design rules
  REPOSITORY_PRINCIPLES.md        ← engineering philosophy and do/don't rules
  CONFIG_SCHEMA.md                 ← all config file schemas
  FEATURE_INVENTORY.md             ← every feature and non-obvious rule
  PROJECT_WORKFLOW.md              ← project → draft → output data flow and file ownership
  PACKAGING.md / PIPELINE.md
```

## Key entry points
| Script | Purpose |
|--------|---------|
| `Setup_DTM_VehicleBuilder.command` / `.bat` | Creates `.venv`, installs package |
| `Launch_DTM_VehicleBuilder.command` / `.bat` | Runs `python -m dtm_buildsheet` (GUI) |
| `Run_Last_Build.command` / `.bat` | Runs CLI generator, opens output .pptx |
| `Build_Mac_App.command` | One-click PyInstaller rebuild → `dist/DTM Vehicle Builder.app` |
| `packaging/build_windows.ps1` | Same for Windows (run on Windows machine or via CI) |

## How the app runs
`app/server.py:main()` starts an HTTP server on `127.0.0.1:7655`, then:
- **With pywebview installed**: server moves to background thread, pywebview opens a native window pointing at `http://localhost:7655` (must own main thread — macOS requirement)
- **Without pywebview**: falls back to `webbrowser.open()` (dev convenience)

`gui_server.py` is a compatibility shim that re-exports `app.server.main`. All new code should import from `app` directly.

Port conflict on launch = old instance still running. `lsof -ti :7655 | xargs kill` clears it.

## UI structure

The app has two main tabs: **Projects** and **Settings**.

### Projects tab
```
#proj-list-view      — scrollable project list
#proj-detail-view    — detail view with three sub-tabs:
    Overview         — read-only customer + prefs cards (2-col), fleet groups below
    Edit             — read-only by default; [✏️ Edit] enters edit mode with inputs
    Builds           — per-unit cards: [Setup/Edit Build] [📊 Preview/Edit in PowerPoint] [📄 Export PDF] [📑 View PDF (when present)] [📂 Show in folder] + per-card author tags
#proj-editor         — 4-step wizard (new projects only: Customer → Preferences → Fleet → Review)
#proj-build-editor   — embedded build editor (in-place; replaces switching to a separate tab)
    #pbe-header      — unit context bar + "← Back to Project" button
    #pbe-preview-section  — preview canvas (pvLoad / pvReload)
    #pbe-manifest-section — draft manifest editor (loadDraftManifest)
    #pbe-footer      — "💾 Save & Return to Project" button
```

`#card-preview` and `#card-manifest` live exclusively inside `#proj-build-editor`. They are singletons — not duplicated anywhere else in the DOM.

### Settings tab
Two header tabs (General / Advanced) each surface their own set of outer stabs:

- **General Settings**: `projects-defaults | agencies | sales-reps | presets`
- **Advanced Settings**: `placements | sizes | part-manager | vehicles | workbook-tools`

Two of the Advanced outer stabs group multiple inner stabs (rendered as a thin inner-stab-bar above the content):

- `placements` → inner stabs: `placements | fixtures`
- `part-manager` → inner stabs: `catalog (Part Types) | parts (Parts Library) | parts-db (Database v2)`

The **Workbook Tools** stab contains the standalone build-sheet generator (generate a `.pptx` by uploading a workbook directly), which was formerly the main "Generate" tab.

The **Database (v2)** inner stab is the visual editor for `parts_db.json` (Phase 3). It walks `part_types[*].tree_positions[]` to render Type › Section › Zone › Sub-zone › Part Type, with catalog buckets for Products / Manufacturers / Tags. Edits go through `POST /api/parts-db` → `save_config_file` → SharePoint direct-mirror.

## Project data model

```python
@dataclass
class CustomerInfo:
    name: str = ""
    agency: str = ""          # display name
    agency_id: str = ""       # FK → agencies.json
    sales_rep_id: str = ""    # FK → sales_reps.json
    quote_number: str = ""
    build_year: str = ""
    notes: str = ""

@dataclass
class EquipmentPreferences:
    lighting: str = ""
    camera: str = ""
    bumper: str = ""
    cage: str = ""
    slick_top: bool = False
    notes: str = ""

@dataclass
class BuildUnit:
    vehicle_model: str = ""
    build_type: str = ""
    quantity: int = 1
    preset_id: str = ""
    individuals: list = field(default_factory=list)

@dataclass
class IndividualUnit:
    unit_number: str = ""
    vin: str = ""
    year: str = ""
    color: str = ""
    draft_id: str = ""
    output_path: str = ""     # set when build sheet is generated

@dataclass
class ProjectRecord:
    project_id: str = ""
    customer: CustomerInfo = ...
    preferences: EquipmentPreferences = ...
    build_units: list[BuildUnit] = ...
    export_dir: str = ""      # empty = default output location
    created_at: str = ""
    updated_at: str = ""
```

Projects are stored in `workspace/projects/{project_id}/project.json` (one subdirectory per project). The subdirectory layout is intentional — future artifacts (generated PPTX, draft snapshots) can be dropped alongside the record without polluting the flat projects list.

## Agency and Sales Rep databases

Per-record JSON files under workspace subdirectories, each mirroring a SharePoint `/Settings/` folder:
- `workspace/agencies/{agency_id}.json` ↔ `Settings/agencies/{agency_id}.json`
- `workspace/sales_reps/{rep_id}.json` ↔ `Settings/sales_reps/{rep_id}.json`

The legacy flat-file form (`workspace/agencies.json`, `workspace/sales_reps.json`) exists only as a one-shot migration source for older installs; on first read, `agency_service` / `sales_rep_service` rewrite each entry into the per-record dir and forget the flat file.

Agency search uses `difflib.get_close_matches` after normalizing common abbreviations (PD→police department, SO→sheriff's office, St.→saint, etc.). The project wizard has live-search combos for both fields; contact info comes from the agency record (no separate contact field on the project).

Saves and deletes hit SharePoint directly via `save_setting_to_cloud_in_background` and `delete_setting_from_cloud` so other devices see the change within the next 60s sync cycle — see `docs/ROADMAP.md` § Phase 2.5 for why the proposal pipeline alone isn't enough.

## Preset system

Presets are JSON files (schema_version 2) cached in `workspace_presets_dir` — `workspace/presets/` in the bundled app, `src/dtm_buildsheet/resources/presets/` in dev mode. **The cache is a local mirror of SharePoint `/Settings/presets/`, not a source.** Bundled presets were removed in v2.2.10; `resources/presets/*.json` is gitignored.

```json
{
  "preset_id": "...",
  "label": "St. Cloud PD Patrol PIU/Tahoe",
  "agency_ids": ["..."],   // [] = universal
  "build_types": ["Patrol"],
  "vehicle_types": ["PIU", "TAHOE"],
  "tag": "",               // optional suffix for General presets
  "parts": [...]
}
```

Label is auto-generated from agency + build_type + vehicle_types. The preset manager (Settings → Presets) supports import from workbook, export to workbook, clone, and delete. `blank_custom` is hardcoded in `preset_service` (no file) and is the only preset that survives a fresh-install-with-no-cloud.

## Workspace vs bundled resources
`paths.py` detects dev vs bundled via presence of `pyproject.toml`:
- **Dev**: workspace is `{repo}/workspace/`, config/assets written directly to `src/dtm_buildsheet/resources/` so changes are immediately visible to git
- **Bundled app**: workspace is `~/Library/Application Support/DTM Vehicle Builder` (Mac) or `%APPDATA%\DTM Vehicle Builder` (Windows)

On first run, bundled default configs/assets are seeded into the workspace. User edits live in workspace and are never overwritten by a version upgrade.

## Packaging
**Mac** (run on Mac):
```bash
bash packaging/build_macos.sh        # or double-click Build_Mac_App.command
# output: dist/DTM Vehicle Builder.app
```
**Windows** (run on Windows or via CI):
```powershell
.\packaging\build_windows.ps1
# output: dist\DTM Vehicle Builder\  →  then Inno Setup → DTM_Vehicle_Builder_Setup.exe
```
**CI** (GitHub Actions — both built automatically on push to `main`):
- Mac job: PyInstaller → `.app` → `.dmg` (drag-to-Applications)
- Windows job: PyInstaller → Inno Setup → `DTM_Vehicle_Builder_Setup.exe`
- Artifacts downloadable from the Actions run page

## pyproject.toml quick ref
```toml
name = "dtm-buildsheet"          # internal package name (Python import: dtm_buildsheet)
version = "0.7.0"
dependencies = [lxml, openpyxl, Pillow, python-pptx, pywebview]
[packaging] extras = [pyinstaller, pyinstaller-hooks-contrib]
```

## Workbook template auto-regen

`template_builder.py` reads three config files to build the Excel input template:

| Config file | What it provides |
|-------------|-----------------|
| `workbook_rules.json` | Section/part structure, per-part location dropdowns |
| `parts_library.json` | Manufacturer and model number dropdowns |
| `vehicle_layouts.json` | Full set of location names across all vehicles/views |

**Mechanism**: `app/services/config_service.py` defines `TEMPLATE_REGEN_FILES`. Whenever `save_config_file()` is called for one of those files, it spins up a background thread to call `template_service.generate_template()` and sets `"template_regen": "triggered"` in the JSON response. The frontend's `apiSave()` in `ui/js/api.js` watches for `res.template_regen` and calls `loadTemplateInfo()` to refresh the template timestamp display.

**If you add a new config file that feeds `template_builder.py`**, add its filename to `TEMPLATE_REGEN_FILES` in `config_service.py`. The manual "Regenerate" button in Settings → Tools calls `/api/template/generate` directly as a recovery option.

## Config files
Eight JSON config files live in `workspace/config/` (editable) and `src/dtm_buildsheet/resources/config/` (bundled defaults). All schemas are documented in `docs/CONFIG_SCHEMA.md`.

| File | Purpose |
|------|---------|
| `part_catalog.json` | Part types, render rules, co-part rules, quantity policies |
| `vehicle_layouts.json` | Per-vehicle view layouts, location keys, slot positions |
| `parts_library.json` | Manufacturer and model number dropdowns |
| `workbook_rules.json` | Excel template structure (sections, parts, dropdowns) |
| `build_rules.json` | Validation and dependency rules evaluated by `rules/engine.py` |
| `asset_manifest.json` | Maps asset keys to image filenames |
| `app_settings.json` | User preferences (template save dir, etc.) |
| `project_options.json` | Project wizard dropdown lists (build types, brands) |

## Route module pattern

Every route module follows: `route_xxx(handler, method, path, body, paths) → bool`. Returns `True` if handled.

```python
elif path == "/api/foo":
    if not foo_routes.route_foo(self, "GET", path, {}, self.paths):
        self._send(404, b"Not found", "text/plain")
```

## JS api() helper (api.js)

```js
const api = (path, body) =>
  fetch(path, body !== undefined
    ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}
    : undefined
  ).then(r => r.json());
```
- `api(url)` → GET
- `api(url, payload)` → POST with JSON body
- DELETE must use raw `fetch(url, { method: "DELETE" })` then `.json()`

## Modal pattern

`.modal-overlay` + `.modal` toggled with `classList.add/remove("open")`. Single-listener pattern: each modal's save button is owned by exactly one IIFE. Never add a second listener from another file.

## Gotchas
- **Python package name** is still `dtm_buildsheet` / `dtm-buildsheet` — only the *app* name changed to "DTM Vehicle Builder". Don't rename the `src/dtm_buildsheet/` directory without updating all imports.
- **Compatibility shims** (`gui_server.py`, `config_loader.py`, `input_reader.py`, `models.py`, `planner.py`) re-export from the new package areas. New internal imports should use `app`, `config`, `domain`, `planning`, `inputs` directly.
- **ICNS must be real ICNS** — the source icon was a PNG renamed to `.icns`. It was converted properly via `iconutil`. Don't replace it with a raw PNG or PyInstaller will silently fall back to the Python icon.
- **pywebview owns the main thread** on macOS — the HTTP server must run in a daemon thread when pywebview is active. Don't move `webview.start()` off the main thread.
- **PyInstaller cannot cross-compile** — Mac builds must run on Mac, Windows builds must run on Windows (CI handles this).
- **GitHub repo**: `https://github.com/dtmseth/DTM_Vehicle_Builder` — push to `main` triggers both builds.
- **Placement math is shared** — `domain/geometry.py` is the one source of truth for slot positioning. Preview canvas JS mirrors this logic; if you change it server-side, update the JS too.
- **#card-preview and #card-manifest are singletons** — they exist only inside `#proj-build-editor`. The standalone generate tool in Settings → Tools does not render them.
- **`state.js` initSettings()** is called every time the user switches to the Settings tab. It lazy-loads config, then calls `initAgenciesTab()`, `initSalesRepsTab()`, and `initPresetsTab()` if they exist.
- **Cloud is source of truth** for per-record entities (agencies, sales reps, presets, projects, drafts) as of v2.2.9+. Saves direct-mirror to SharePoint via `save_setting_to_cloud_in_background` / `mirror_*_to_cloud_in_background` alongside the proposal pipeline; deletes go through `delete_setting_from_cloud`. The dtm-shared-settings GitHub repo is audit-only — its publish workflow is cron-throttled and is no longer the canonical write path. See `docs/ROADMAP.md` § Phase 2.5 for the full hardening pass.
- **Auto-update** is silent on both Windows (.exe) and Mac (.dmg) as of v2.2.11. `update_check_service` exposes `_expected_installer_suffix()` — DO NOT hard-code `sys.platform.startswith("win")` in update-state code; that's how the Mac "platform_unsupported" bug shipped.
- **Per-build buttons**: there is no Generate button. The Builds tab has `[Edit Build] [📊 Preview / Edit in PowerPoint] [📄 Export PDF] [📑 View PDF] [📂 Show in folder]`. Both Preview and Export auto-regenerate when source changed since `last_rendered_at`; a manual-edit-detection modal warns before discarding PowerPoint edits.
- **Tests must NEVER write to the real workspace queue**. `tests/conftest.py` blocks real cloud I/O, and `wiring.save_via_proposal` also refuses to enqueue when `PYTEST_CURRENT_TEST` is set. Tests that needed to assert queueing behavior have been updated to assert `"queued" not in result`. Bypassing these guards reintroduces the abc.json resurrection bug (root cause documented in v2.2.12 commit).
- **parts_db.json is populated but not yet wired into production reads**. Phase 3 PR-2b seeded `parts_db.json` (5/106/186/48: types/part_types/products/manufacturers) and `legacy_workbook_index.json` (102/186 entries). Today only the Part Manager UI (Settings → Advanced → Part Manager → Database (v2)) and the schema validator read from these files. The build sheet generator, planner, manifest editor, rule engine, and excel reader all still drive off `workbook_rules.json` / `parts_library.json` / `vehicle_layouts.json` / `part_catalog.json`. PR-3 (manifest_editor dual-read) is the first consumer swap.
- **Migration script has --push-to-cloud**. `tools/migrate_workbook_to_parts_db.py --write` writes via `Path.write_text()` which bypasses `save_config_file` and therefore SharePoint direct-mirror — meaning the next 60s shared-settings sync will silently overwrite the migration with whatever (older) copy SharePoint has. The `--push-to-cloud` flag re-saves the output through `save_config_file` to fire direct-mirror. Always use `--write --push-to-cloud` when you actually want the data to stick.
