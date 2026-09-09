# UI Structure

Server: `app/server.py` on `127.0.0.1:7655`. UI: `src/dtm_buildsheet/ui/` — single-page
app served as static files.

## Tab layout

Three workspace families: **Projects**, **Operations**, and **Settings**. Operations is hidden until
the session API confirms `operations.view`; General and Advanced remain separate Settings header
tabs.

### Operations tab

```
#tab-operations          — shared production backlog grouped by project
    summary counts       — Active / Unscheduled / Scheduled / Must Deliver
    local filters        — Active / Unscheduled / Scheduled / Not accepted / Completed
    search               — agency, label, unit number, full VIN, or Estimate number
    project groups       — common/mixed statuses; collapsed by default; search opens matches
      one-click statuses — project-wide status steps; correction modal only when required
      vehicle cards      — detail plus collapsible one-click individual overrides
    schedule editor      — independent optional dates; project or vehicle patch
    history modal        — complete applied event timeline for one vehicle
    Add Builder vehicle  — legacy/import fallback for unsynchronized Builder vehicles
```

`ui/js/operations.js` owns access discovery, loading, filtering, and rendering. The header button
starts hidden and is revealed only after `/api/operations/session` confirms both capability and
repository readiness. The vehicle route repeats that check on the server. Users with
`projects.edit` can also call `/api/operations/projection-preview`; it reads local Builder projects
and the current Operations list once, reports new/changed/current mappings, and never invokes a
repository mutation or repair path. The temporary `/api/operations/projection-pilot` POST accepts
one opaque vehicle ID, an exact confirmation token, and a one-use request ID. It re-derives every
stored field from server-side Builder data and uses a create-only command, so it cannot refresh an
existing row or alter production state. The browser shows the full VIN in a native confirmation
before calling it. Once an Operations row exists, the header action loads the preview only when
clicked instead of issuing a second SharePoint list query on every tab open. Ordinary project saves
automatically upsert only the narrow Builder-owned projection; production statuses and dates are
preserved. The bulk control is now a legacy/import fallback and includes only new Active and
Completed projections,
uses the same create-only POST once per vehicle, shows progress, and stops on the first failure.
Completed Builder projects enter the Completed tab without invented historical workstream dates.
Project status updates are browser orchestration over `/api/operations/status`: one vehicle and
expected revision per request, processed sequentially, with a separate request ID and immutable
event for each vehicle. Visible status steps are buttons: a normal forward transition saves
immediately, while a reversal or skipped step opens the existing correction editor. A collapsible
set of the same buttons handles individual vehicle exceptions. The sequence stops on the first
failure and refreshes current data. The browser offers only workstreams allowed by the session
capabilities; the route and service independently enforce authorization, legal forward transitions,
revision concurrency, and correction-note requirements. Optional effective dates are available for
Ready for Pickup and At DTM; Final Finish Delivered stamps the delivery date automatically. All
status changes receive automatic actor and entry timestamps.
Unstarted/not-ready cells remain white, intermediate states are light yellow, and each workstream's
finished state is green: At DTM completes Vehicle Availability, while Delivered completes Final
Finish. Inactive records retain history in SharePoint but have no Operations filter or visible row
until the Builder project is reactivated. Marking every project vehicle Final Finish Delivered
automatically moves the Builder project and its Operations rows to Completed.
Every vehicle also exposes **View history**, including for read-only Operations viewers. The history
route returns newest-first applied events with friendly values, actor/time, optional performed-by
name, business-effective date, correction note, and revision. Event IDs remain available as stable
UI keys, while actor object IDs and idempotency request IDs are not sent to the browser.
Users with `operations.schedule.update` can edit the schedule for an entire Active project or one
vehicle exception. All four inputs are optional: Scheduled Week, Planned Start, Target Finish, and a
manual Must Deliver On override. Editing sends only changed fields, so existing values need not be
re-entered. The date inputs have no dependency or Monday requirement and may be captured before
acceptance; acceptance plus Scheduled Week still derives Prospective/Unscheduled/Scheduled. Clearing
the manual deadline restores the automatic 60-day date. Like project status updates, project
scheduling calls the one-vehicle route sequentially and retains one immutable event per vehicle.

### Projects tab
```
#proj-list-view        — scrollable project list
    status tabs         — Started / Active / Inactive / Completed with live project counts
    status search       — searches only the selected tab and remembers one query per tab
    Started             — durable-active projects whose current Operations vehicles are not all accepted
    Active              — all current vehicles accepted; arrived projects first, then Must Deliver On
    Inactive            — optional note plus a three-dot Reactivate/Delete menu
    Completed           — Agency → Build Year tree, galleries/folders, Open/Reopen
#proj-detail-view      — detail view with two sub-tabs:
    Overview           — customer + prefs cards (2-col), fleet/build cards below; long unit notes open in a modal
    Edit               — read-only by default; [✏️ Edit] enters edit mode with inputs
                         Unit-group headers own Build Reference Photos.
                         Build cards expose [PDF Options] [QuickBooks] [Folder options]
                         [View completed photos] only when files exist, then [Finalize design].
#proj-editor           — 4-step wizard (new projects only: Customer → Preferences → Fleet → Review)
#proj-build-editor     — embedded build editor (in-place, no tab switch)
    #pbe-header        — unit context bar + "← Back to Project" button
    #pbe-preview-section — preview canvas (pvLoad / pvReload)
    #pbe-manifest-section — draft manifest editor (loadDraftManifest)
    #pbe-footer        — Load Preset / Save as New Preset / Apply to Group actions + Return button
```

The durable project lifecycle remains `active`, `inactive`, or `completed`; `started` is a derived
list view, not a fourth stored state. A durable-active project stays in Started until every current
vehicle's Operations row is accepted, then appears in Active. Active projects whose every vehicle
has Parts Received/Parts Ready and is At DTM sort first; each group then sorts by its earliest
effective Must Deliver On date, with undated projects last. The selected list tab is preserved when
opening and returning from a project. Marking a project inactive accepts an optional note in an app
modal; it never deletes the project, builds, files, or lifecycle history. Each tab's search text is
independent, and a Completed search expands matching agency/year groups. Completed projects retain
the existing grouped archive presentation inside the Completed tab rather than navigating to a
separate archive screen. Projects opens on Started. Selected tabs use lifecycle tones: light yellow
Started, light green Active, light red Inactive, and solid green Completed.
Started/Active workflow badges are derived, not separately edited: Estimate Sent, Estimate Accepted,
combined Parts/Vehicle progress, Ready to Build, Build in Progress, Ready to Deliver, and Delivered.
Project saves create/update their Operations projections; project deletion also removes the exact
project's Operations rows and immutable status history after explicit confirmation.

Both new-project and existing-project vehicle selectors include **+ New vehicle**. The in-app dialog
requires only Make and Model, saves a shared `vehicle_layouts.json` placeholder with no image files,
marks it **artwork pending**, and immediately selects it for that unit. Artwork can be completed later
through Vehicle Manager.

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
