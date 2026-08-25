# UI Structure

Server: `app/server.py` on `127.0.0.1:7655`. UI: `src/dtm_buildsheet/ui/` — single-page
app served as static files.

## Tab layout

Two main tabs: **Projects** and **Settings**.

### Projects tab
```
#proj-list-view        — scrollable project list
#proj-detail-view      — detail view with two sub-tabs:
    Overview           — customer + prefs cards (2-col), fleet/build cards below; long unit notes open in a modal
    Edit               — read-only by default; [✏️ Edit] enters edit mode with inputs
                         Build cards expose [📊 Preview/Edit in PowerPoint] [📄 Export PDF]
                         [📑 View PDF] [◆ Set up/Manage QB Project] [📋 QB Estimate]
                         [📂 Show in folder] [✓ Final review] + per-card author tags
#proj-editor           — 4-step wizard (new projects only: Customer → Preferences → Fleet → Review)
#proj-build-editor     — embedded build editor (in-place, no tab switch)
    #pbe-header        — unit context bar + "← Back to Project" button
    #pbe-preview-section — preview canvas (pvLoad / pvReload)
    #pbe-manifest-section — draft manifest editor (loadDraftManifest)
    #pbe-footer        — Load Preset / Save as New Preset / Apply to Group actions + Return button
```

**There is no Generate button** on build cards. Preview and Export both auto-regenerate when
source changed since `last_rendered_at`; a manual-edit-detection modal warns before discarding
PowerPoint edits.

### Settings tab

Two header tabs: **General** and **Advanced**, each with their own outer stabs.

**General Settings**: `projects-defaults | agencies | sales-reps | presets | quickbooks`

**Advanced Settings**: `placements | sizes | part-manager | vehicles | workbook-tools`

Two Advanced stabs group inner stabs (rendered as a thin inner-stab-bar above content):
- `placements` → inner stabs: `placements | fixtures`
- `part-manager` → inner stabs: `catalog (Part Types) | parts (Parts Library) | parts-db (Database v2)`

The **Database (v2)** inner stab is the visual editor for `parts_db.json` (Phase 3).

The **Workbook Tools** stab contains the standalone build-sheet generator (upload workbook → `.pptx`),
formerly the main "Generate" tab.

## Key JS files
```
ui/js/
  api.js                 — fetch wrapper, shared utilities, template save helpers
  editor_mode.js         — edit-mode toggle helpers
  main.js                — tab wiring, app init
  manifest_editor.js     — draft manifest card (parts list editor)
  preview_canvas.js      — build preview canvas, drag-and-drop, inspector, overrides
  projects_tab.js        — full project manager UI (list, detail, wizard, build editor)
  state.js               — shared UI state; initSettings() lazy-loads config on tab switch
  tabs.js                — tab/stab switching
  canvas.js              — canvas helpers
  generate_tab.js        — Standalone build-sheet generator (in Settings → Tools)
  settings/
    agencies.js / fixtures.js / part_types.js / parts_library.js
    placements.js / presets_mgr.js / quickbooks.js / sales_reps.js
    size_rules.js / tools.js / vehicles.js
  projects/              — additional project modules
```

## JS patterns

**api() helper** (`api.js`):
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

**Modal pattern**: `.modal-overlay` + `.modal` toggled via `classList.add/remove("open")`.
Each modal's save button is owned by exactly ONE IIFE. Never add a second listener from
another file.

**`state.js` initSettings()** is called every time the user switches to the Settings tab. It
lazy-loads config, then calls `initAgenciesTab()`, `initSalesRepsTab()`, `initPresetsTab()` if
they exist.

## DOM singletons

- `#card-preview` and `#card-manifest` live exclusively inside `#proj-build-editor`.
  They are NOT duplicated anywhere else in the DOM. The standalone generate tool in
  Settings → Workbook Tools does not render them.

## Inline style policy

`style="display:none"` in initial HTML is acceptable for JS-toggled elements. All other inline
styles (colors, spacing, font sizes, layouts) belong in `styles.css` as named classes.

`projects_tab.js` and `ui/js/projects/*.js` contain ~100 inline style attributes embedded in JS
template literals. Extracting these to CSS classes is a bounded cleanup but has regression risk
(dynamic conditional styles, shared fragments). Only do it when the module is already being
substantially modified:
- Move layout structure (`display:flex`, `gap`, `margin`, `padding`) to `.proj-*` classes
- Move typography variants (`font-size:11px`, `font-weight:700`, `letter-spacing`) to utility classes
- Leave `display:none` and inline conditional styles (`style="${flag ? '' : 'display:none'}"`) as-is
