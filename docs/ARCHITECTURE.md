# Architecture

## Runtime Shape

- `dtm_buildsheet.gui_server`
  Compatibility entrypoint for the local GUI server.
- `dtm_buildsheet.app.server`
  Local HTTP server, static UI serving, and route dispatch.
- `dtm_buildsheet.app.routes`
  Thin API route modules.
- `dtm_buildsheet.app.services`
  Side effects and orchestration: generation, config save, assets, drafts, preview, templates, exports, validation.
- `dtm_buildsheet.generator`
  Shared generation service used by both GUI and CLI.
- `dtm_buildsheet.inputs`
  Excel reader, GUI draft conversion, and draft persistence.
- `dtm_buildsheet.domain`
  Shared input/plan models, geometry, and rule dataclasses.
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
- saved GUI drafts

This is deliberate so future packaged apps can ship read-only resources while keeping user data writable.

## Design Rules

The project-level engineering philosophy is maintained in `docs/REPOSITORY_PRINCIPLES.md`.
New work should preserve the central flow:

```text
Input adapter -> ProjectInput -> BuildPlan -> renderer/exporter
```

## Packaging Direction

Near-term likely choices:

1. `PyInstaller`
   Fastest path to a packaged macOS/Windows app from the current codebase.
2. `Briefcase`
   Better long-term native-app story, but more structural work.

For this project, `PyInstaller` is the pragmatic first packaging target unless a native shell becomes a product requirement.
