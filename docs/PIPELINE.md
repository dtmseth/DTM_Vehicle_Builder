# Pipeline

## High-Level Flow

1. GUI upload or CLI selection picks a workbook.
2. `dtm_buildsheet.input_reader.load_input()`
   Parses workbook metadata, parts, notes, and normalizes naming.
3. `dtm_buildsheet.config_loader.load_configs()`
   Loads active workspace config through `config_store`, which validates and normalizes JSON before use.
4. `dtm_buildsheet.planner.build_plan()`
   Resolves workbook parts into planned placements and render instances.
5. `dtm_buildsheet.reporting.render_markdown_summary()`
   Produces the debug/inspection summary.
6. `dtm_buildsheet.render_ppt.render_plan_to_ppt()`
   Produces the final PowerPoint build sheet.

## Module Dependencies

```text
gui_server
  -> generator
  -> input_reader
  -> config_store
  -> template_builder
  -> paths

generator
  -> input_reader
  -> config_loader
  -> planner
  -> reporting
  -> render_ppt
  -> paths

config_loader
  -> config_store
  -> paths

config_store
  -> config_validation
  -> paths

planner
  -> config_loader
  -> models
  -> naming

render_ppt
  -> ppt_helpers
  -> paths

template_builder
  -> config_store
  -> paths
```

## Mutable vs Bundled Data

Bundled app resources:

- `src/dtm_buildsheet/resources/config/`
- `src/dtm_buildsheet/resources/templates/`
- `src/dtm_buildsheet/resources/assets/`

Mutable runtime data:

- `workspace/config/`
- `workspace/assets/`
- `workspace/input/`
- `workspace/output/`

In development, `workspace/` lives in the repo.
In a packaged app, the workspace will live in the user data folder for the OS.

## Where To Change Things

- Change parsing behavior:
  `src/dtm_buildsheet/input_reader.py`
- Change part/config matching:
  `src/dtm_buildsheet/planner.py`
- Change GUI/API behavior:
  `src/dtm_buildsheet/gui_server.py`
- Change page layout/UI:
  `src/dtm_buildsheet/gui_ui.html`
- Change output rendering:
  `src/dtm_buildsheet/render_ppt.py`
- Change default config data:
  `src/dtm_buildsheet/resources/config/`

## Why Packaging Won't Freeze Development

The packaging files only define how the app is bundled.
They do not own the GUI logic or pipeline logic.

That means we can keep doing normal development in `src/dtm_buildsheet/`, and the packaging layer just rebuilds the current app state.
