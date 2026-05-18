# Architecture

## Runtime Shape

- `dtm_buildsheet.gui_server`
  Compatibility entrypoint for the local GUI server (thin shim → `app.server.main`).
- `dtm_buildsheet.app.server`
  Local HTTP server on `127.0.0.1:7655`, static UI serving, and route dispatch.
- `dtm_buildsheet.app.routes`
  Thin API route modules. Each module exports one `route_xxx(handler, method, path, body, paths) → bool` function. Returns `True` if it handled the request.
- `dtm_buildsheet.app.services`
  Side effects and orchestration: agency CRUD, project CRUD, preset management, config save, assets, drafts, templates, exports, preview, generation, validation.
- `dtm_buildsheet.generator`
  Shared generation service used by both GUI routes and CLI.
- `dtm_buildsheet.inputs`
  Input adapters: Excel reader, GUI draft conversion, draft persistence, project record persistence.
- `dtm_buildsheet.domain`
  Shared dataclasses and geometry: `ProjectRecord`, `AgencyRecord`, `SalesRepRecord`, `BuildPlan`, `PlannedPart`, `PlannedPlacement`, geometry helpers, and rule dataclasses.
- `dtm_buildsheet.planning`
  Mapping project input to render placements through focused resolvers.
- `dtm_buildsheet.rules`
  Build validation/dependency rule engine.
- `dtm_buildsheet.render_ppt`
  PowerPoint rendering.
- `dtm_buildsheet.config`
  Mutable workspace config load/save with migration and validation.
- `dtm_buildsheet.ui`
  Browser UI served by the local app server.
- `dtm_buildsheet.paths`
  Separation between shipped resources and user workspace data.

## Workspace Model

Bundled defaults are stored in package resources.
On first run they are copied into `workspace/`, which becomes the mutable area for:

- config edits made through the GUI
- uploaded workbooks
- uploaded assets
- generated outputs
- saved GUI drafts (`workspace/drafts/`)
- project records (`workspace/projects/`)
- user-created presets (`workspace/presets/` — bundled app; dev writes to `resources/presets/`)
- agency database (`workspace/agencies.json`)
- sales rep database (`workspace/sales_reps.json`)

`workspace/` is git-ignored. It lives in `{repo}/workspace/` in dev mode and in the OS user
data folder in a packaged app.

`agencies.json` and `sales_reps.json` are seeded from `resources/default_data/` on first run
if the files do not yet exist. This lets the app ship a set of sample/starter records without
overwriting user edits on upgrade.

**Dev note**: `WORKSPACE_CONFIG_DIR`, `WORKSPACE_ASSETS_DIR`, and `WORKSPACE_PRESETS_DIR` all
collapse back into `src/dtm_buildsheet/resources/` in dev mode so every edit is immediately
visible to git without manual copying.

## Design Rules

The project-level engineering philosophy is maintained in `docs/REPOSITORY_PRINCIPLES.md`.
New work should preserve the central flow:

```text
Input adapter -> ProjectInput -> BuildPlan -> renderer/exporter
```

## UI Structure

The app has two main tabs: **Projects** and **Settings**.

**Projects tab** manages the full project lifecycle:
- `#proj-list-view` — scrollable list of all projects
- `#proj-detail-view` — detail view with Overview / Edit / Builds sub-tabs
- `#proj-editor` — 4-step wizard for new projects only
- `#proj-build-editor` — embedded build editor (in-place; no tab switch required)

**Settings tab** has ten sub-tabs: placements, fixtures, sizes, catalog, parts, vehicles, agencies, sales-reps, presets, tools. The "Tools" stab contains the standalone workbook-upload generator (formerly the main "Generate" tab).

## Route Module Pattern

```python
# module signature
def route_xxx(handler, method, path, body, paths) -> bool:
    ...
    return True   # if handled

# server.py registration
elif path == "/api/foo":
    if not foo_routes.route_foo(self, "GET", path, {}, self.paths):
        self._send(404, b"Not found", "text/plain")
```

## JS Patterns

**`api()` helper** (`ui/js/api.js`):
- `api(url)` → GET
- `api(url, payload)` → POST JSON
- DELETE → raw `fetch(url, {method:"DELETE"}).then(r => r.json())`

**Modal pattern**: `.modal-overlay` + `.modal` toggled via `classList.add/remove("open")`. Each modal's save button is owned by exactly one IIFE.

**`state.js` `initSettings()`**: called every time the Settings tab is activated. Lazy-loads config, then calls `initAgenciesTab()`, `initSalesRepsTab()`, `initPresetsTab()` if present.

## Packaging Direction

`PyInstaller` is the current packaging target for both Mac and Windows. CI handles parallel builds on the correct platform for each target.
