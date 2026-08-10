# Development

## Setup (first time)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Or double-click `Setup_DTM_VehicleBuilder.command`.

## Running

```bash
.venv/bin/python -m dtm_buildsheet                        # GUI on http://localhost:7655
.venv/bin/python -m dtm_buildsheet.generator_cli book.xlsx  # CLI build-sheet generation
```

Or double-click `Launch_DTM_VehicleBuilder.command` / `.bat`.

Port conflict on launch → old instance still running: `lsof -ti :7655 | xargs kill`

## Testing

```bash
.venv/bin/python -m pytest                    # full suite
.venv/bin/python -m pytest tests/test_foo.py  # single file
```

Tests auto-redirect workspace to temp dirs. `PYTEST_CURRENT_TEST` guards prevent real cloud
I/O — never bypass these guards.

Add tests with every new system-level behavior. Focus: domain logic, config validation,
rule evaluation, planning, preview overrides, export services.

## Guardrail checks

Import boundaries are enforced by [import-linter](https://import-linter.readthedocs.io/)
(contracts live in `pyproject.toml` under `[tool.importlinter]` — see
`docs/AUDIT_REFACTOR_ROADMAP.md` §4 / §8.1 Step 2):

```bash
.venv/bin/lint-imports                        # import-boundary contracts
```

The grandfathered baseline in `pyproject.toml` may only shrink — never add a new
`BASELINE` entry to satisfy the lint; fix the import instead. When a baselined
import is fixed, delete its entry (the linter errors on unmatched ignores).

Security scans (run in CI; locally install once with
`.venv/bin/pip install pip-audit bandit`):

```bash
.venv/bin/pip-audit --skip-editable           # dependency vulnerabilities
.venv/bin/bandit -r src/dtm_buildsheet        # static security scan (report-only)
```

## CI

GitHub Actions:

`.github/workflows/checks.yml` — triggered on every PR and push to `main`:
- **import-linter**: import-boundary contracts (fails on any new violation)
- **pip-audit**: known-vulnerability audit of resolved dependencies
- **bandit**: static security scan, report-only first pass

`.github/workflows/build.yml` — triggered on every push to `main`:
- **Mac job**: PyInstaller → `.app` → `.dmg` (drag-to-Applications)
- **Windows job**: PyInstaller → Inno Setup → `.exe` installer

Artifacts downloadable from the Actions run page. PyInstaller cannot cross-compile — each
platform must build on its own OS.

## Packaging

**Mac:**
```bash
bash packaging/build_macos.sh
# → dist/DTM Vehicle Builder.app
```

**Windows:**
```powershell
.\packaging\build_windows.ps1
# → dist\DTM Vehicle Builder\ + dist\DTM_Vehicle_Builder_Setup.exe
```

Or use the convenience scripts: `Build_Mac_App.command`, `packaging/build_windows.ps1`.

## Versioning

Semantic versioning (`bump-my-version`). See `docs/VERSIONING.md`. Current: `v3.0.0`.

## Release checklist

Do not ship:
- `workspace/` drafts, inputs, or outputs
- `.DS_Store`, `__pycache__/`, generated build folders
- Obsolete duplicate implementations
- Undocumented config fields
- Tests that pass only because coverage silently collapsed

Before merging: confirm package data and PyInstaller data include every runtime asset.

## Repo layout

```
src/dtm_buildsheet/          ← Python package
  app/                       ← HTTP server, routes, services
  domain/                    ← shared dataclasses, geometry
  planning/                  ← ProjectInput → BuildPlan resolvers
  rules/                     ← validation/dependency engine
  inputs/                    ← input adapters (Excel, GUI draft, persistence)
  config/                    ← workspace config load/save/migrate
  ui/                        ← browser UI (static files)
  resources/                 ← bundled defaults (config, templates, assets)
workspace/                   ← mutable user data (git-ignored)
tests/                       ← pytest suite
docs/                        ← project documentation
packaging/                   ← PyInstaller spec, icons, Inno Setup
samples/                     ← test input workbooks
.github/workflows/           ← CI
```
