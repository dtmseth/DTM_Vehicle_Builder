# Repository Principles

This document is the working compact between people, AI assistants, and future maintainers. The goal is not ceremony. The goal is to keep DTM Vehicle Builder understandable as it grows.

## The Center Of The App

The stable path is:

```text
Input adapter -> ProjectInput -> BuildPlan -> renderer/exporter
```

Excel, GUI drafts, presets, and future imports are input adapters. PowerPoint, PDF, preview canvases, and reports are renderers/exporters. New features should plug into this path instead of building side pipelines.

## Do Not Hide Product Logic

Product behavior belongs in one of these places:

- `domain/` for shared concepts, geometry, and dataclasses.
- `planning/` for translating project input into a build plan.
- `rules/` for validation and dependency logic.
- `config/` plus `resources/config/*.json` for editable data and schema rules.
- `app/services/` for side effects such as saving configs, assets, drafts, templates, and exports.
- `ui/js/` for browser interactions only.

Avoid adding important behavior inside event handlers, route handlers, or rendering code unless that behavior is truly local to that layer.

## One Source Of Truth

When behavior must be shared, extract it before extending it.

- Placement math belongs in geometry helpers, not separately in preview and PowerPoint code.
- Config saves go through config services and validators.
- Template regeneration is a server-side consequence of saving template-feeding configs.
- Validation rules live in `build_rules.json` and the rule engine, not in comments or operator memory.
- New views are config-driven; do not hardcode a future view list in isolated code.

Duplication is allowed only when it is explicitly a compatibility shim or a small UI convenience. Compatibility shims should say so at the top of the file.

## Inputs Are Adapters

Excel is still supported, but it is not the app's architecture. GUI drafts should convert into the same `ProjectInput` model that Excel uses. Any future import format should do the same.

Do not make the planner know where data came from.

## Outputs Are Renderers

PowerPoint is one renderer, not the owner of layout truth. Preview and PDF export should consume the same `BuildPlan` and shared geometry concepts.

Renderer-specific code may decide how to draw, size, group, or export shapes, but it should not invent different placement rules.

## Config Is A Contract

Every config file should be:

- documented in `docs/CONFIG_SCHEMA.md`
- validated in `config/schemas.py`
- migrated in `config/migrations.py` when fields change
- covered by tests when it affects behavior

If a config references another config or asset, add a cross-reference check or an intentional warning. Silent broken references are not acceptable baseline behavior.

## Tests Are Part Of The Design

Before release, run:

```bash
.venv/bin/python -m pytest
```

Add tests with every new system-level behavior. Prefer focused tests around domain logic, config validation, rule evaluation, planning, preview overrides, and export services. Human-eye tests are still required for final PowerPoint/PDF layout review.

## GUI Code Rules

The browser UI is allowed to manage interaction state and rendering state. It should not be the only place where business rules exist.

Each substantial UI module should keep a predictable shape:

```text
load -> render -> read form/state -> validate -> save
```

Avoid adding new all-purpose globals when shared state belongs in `state.js` or a feature module.

### Inline Style Policy

`style="display:none"` in initial HTML is acceptable for JS-toggled elements. All other inline styles (colors, spacing, font sizes, layout) belong in `styles.css` as named classes.

`projects_tab.js` and `ui/js/projects/*.js` contain ~100 inline style attributes embedded in JS template literals — layout values, muted-color spans, responsive flex wrappers. Extracting these to CSS classes is a bounded, worthwhile cleanup but has real regression risk (dynamic conditional styles, shared component fragments). Do it only when the module is already being substantially modified:

- Move layout structure (`display:flex`, `gap`, `margin`, `padding`) to `.proj-*` classes in `styles.css`.
- Move typography variants (`font-size:11px`, `font-weight:700`, `letter-spacing`) to utility classes already present in `styles.css`.
- Leave `display:none` and inline conditional styles (`style="${flag ? '' : 'display:none'}"`) as-is — they are programmatic state, not CSS drift.

## Route And Service Rules

Route modules should be thin. They should parse the request, call a service, and return a response.

Services own side effects. If a route starts doing file writes, subprocess calls, config normalization, or multi-step orchestration, move that behavior to a service.

## Backward Compatibility

Keep compatibility shims while external scripts, docs, or tests may still import old module names. Shims should remain small and clearly labeled. New internal imports should use the new package areas directly.

## Release Hygiene

Do not ship:

- `workspace/` drafts, inputs, or outputs
- `.DS_Store`
- `__pycache__/`
- generated build folders
- obsolete duplicate implementations
- undocumented config fields
- tests that pass only because sample coverage silently collapsed to one file

Before merging a baseline branch, confirm package data and PyInstaller data include every runtime asset the app serves.
