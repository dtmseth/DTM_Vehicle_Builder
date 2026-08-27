# Pipeline

## High-Level Flow

1. An input adapter produces `ProjectInput`.
   Current adapters are Excel (`dtm_buildsheet.inputs.excel_reader`) and GUI draft conversion (`dtm_buildsheet.inputs.gui_entry` / `project_drafts`).
2. `dtm_buildsheet.config.loader.load_configs()`
   Loads active workspace config through `config.store`, applies migrations, validates JSON, and reports cross-reference warnings.
3. `dtm_buildsheet.planning.planner.build_plan()`
   Resolves project parts into planned placements and render instances using shared domain/rule/geometry helpers.
4. Optional preview override application adjusts a `BuildPlan` for per-build placement changes.
5. `dtm_buildsheet.reporting.render_markdown_summary()`
   Produces the debug/inspection summary.
6. Renderers/exporters consume the `BuildPlan`.
   Current outputs include PowerPoint, PDF export service, preview JSON, and reports.

## Module Dependencies

```text
gui_server (compatibility shim)
  -> app.server

app.server
  -> app.routes/*
  -> app.services/*
  -> paths

generator
  -> inputs.excel_reader
  -> config.loader
  -> planning.planner
  -> reporting
  -> render_ppt
  -> paths

config.loader
  -> config.store
  -> paths

config.store
  -> config.migrations
  -> config.schemas
  -> paths

planning.planner
  -> domain
  -> planning resolvers
  -> rules.engine
  -> naming

render_ppt
  -> domain.geometry
  -> ppt_helpers
  -> paths

template_builder
  -> config.store
  -> paths
```

## Mutable vs Bundled Data

Bundled app resources:

- `src/dtm_buildsheet/resources/config/`
- `src/dtm_buildsheet/resources/templates/`
- `src/dtm_buildsheet/resources/assets/`
- `src/dtm_buildsheet/ui/`

Mutable runtime data:

- `workspace/config/`
- `workspace/assets/`
- `workspace/input/`
- `workspace/output/`
- `workspace/drafts/`
- `workspace/projects/`
- `workspace/presets/` (bundled app only; dev writes to `resources/presets/`)
- `workspace/agencies/{agency_id}.json`
- `workspace/sales_reps/{rep_id}.json`

`workspace/` is git-ignored. In development it lives in the repo root; in a packaged app it
lives in the OS user data folder (`~/Library/Application Support/DTM Vehicle Builder` on Mac,
`%APPDATA%\DTM Vehicle Builder` on Windows).

SharePoint is the shared source of truth for agencies, sales reps, presets, projects, and drafts.
The old flat `agencies.json` and `sales_reps.json` files are migration inputs only. Generated
customer PDFs use the visible agency/year export tree; editable PPTX sources use the internal
`_DTM Internal PowerPoint Sources` tree and can be hydrated by another workstation.

## Where To Change Things

- Change parsing behavior:
  `src/dtm_buildsheet/inputs/excel_reader.py` or `src/dtm_buildsheet/inputs/gui_entry.py`
- Change part/config matching:
  `src/dtm_buildsheet/planning/`
- Change GUI/API behavior:
  `src/dtm_buildsheet/app/routes/` and `src/dtm_buildsheet/app/services/`
- Change page layout/UI:
  `src/dtm_buildsheet/ui/`
- Change output rendering:
  `src/dtm_buildsheet/render_ppt.py`
- Change default config data:
  `src/dtm_buildsheet/resources/config/`
- Change repo-wide engineering rules:
  `docs/REPOSITORY_PRINCIPLES.md`

## Why Packaging Won't Freeze Development

The packaging files only define how the app is bundled.
They do not own the GUI logic or pipeline logic.

That means we can keep doing normal development in `src/dtm_buildsheet/`, and the packaging layer just rebuilds the current app state.
