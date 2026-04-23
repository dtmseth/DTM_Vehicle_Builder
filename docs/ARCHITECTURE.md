# Architecture

## Runtime Shape

- `dtm_buildsheet.gui_server`
  Local GUI server and API surface.
- `dtm_buildsheet.generator`
  Shared generation service used by both GUI and CLI.
- `dtm_buildsheet.input_reader`
  Workbook parsing.
- `dtm_buildsheet.planner`
  Mapping workbook data to render placements.
- `dtm_buildsheet.render_ppt`
  PowerPoint rendering.
- `dtm_buildsheet.config_store`
  Mutable workspace config load/save with validation.
- `dtm_buildsheet.paths`
  Separation between shipped resources and user workspace data.

## Workspace Model

Bundled defaults are stored in package resources.
On first run they are copied into `workspace/`, which becomes the mutable area for:

- config edits made through the GUI
- uploaded workbooks
- uploaded assets
- generated outputs

This is deliberate so future packaged apps can ship read-only resources while keeping user data writable.

## Packaging Direction

Near-term likely choices:

1. `PyInstaller`
   Fastest path to a packaged macOS/Windows app from the current codebase.
2. `Briefcase`
   Better long-term native-app story, but more structural work.

For this project, `PyInstaller` is the pragmatic first packaging target unless a native shell becomes a product requirement.
