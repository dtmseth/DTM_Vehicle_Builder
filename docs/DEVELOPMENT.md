# Development

## Setup (first time)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,hosted]"
```

Or double-click `Setup_DTM_VehicleBuilder.command`.

The optional `hosted` extra supplies the Azure Table SDK and Waitress for synthetic Stage 2
boundary tests; it does not activate cloud access or change desktop packaging. Existing
environments created by the desktop setup script can install this extra with the command above.

## Running

```bash
.venv/bin/python -m dtm_buildsheet                        # GUI on http://localhost:7655
.venv/bin/python -m dtm_buildsheet.generator_cli book.xlsx  # CLI build-sheet generation
```

Or double-click `Launch_DTM_VehicleBuilder.command` / `.bat`.

Port conflict on launch → old instance still running: `lsof -ti :7655 | xargs kill`

## Testing

```bash
.venv/bin/python -m pytest tests/test_<target>.py --maxfail=1  # iterative work: one relevant file
.venv/bin/python tools/verify.py changed --skip-smoke  # explicit owner pre-commit request only
.venv/bin/python tools/verify.py release       # pre-release checks only
```

Tests auto-redirect workspace to temp dirs. `PYTEST_CURRENT_TEST` guards prevent real cloud
I/O — never bypass these guards.

During iterative work, run only the single relevant pytest file. Documentation/ignore-only edits
need no pytest run. Never autonomously run browser smoke tests during normal editing or small
feature additions, including through wrappers. Report compact counts and the first actionable
failure, not individual passing tests or browser JSON.

Reserve `tools/verify.py changed` for an explicit owner request for pre-commit verification and
pass `--skip-smoke`. It selects from all staged/unstaged changes against `HEAD` plus untracked
files; staging alone does not narrow that selection. A baseline commit preserves current work
while resetting the diff for subsequent edits. The bare command also runs selected browser flows.
Full browser runs and the `release` profile are strictly pre-release checks. GitHub CI keeps
the complete suite and coverage floor as the authoritative always-on safety net.

This policy is mandatory for automated coding sessions. The repository-root `AGENTS.md` contains
the canonical session instructions so a fresh agent receives them before making changes.

Add tests with every new system-level behavior. Focus: domain logic, config validation,
rule evaluation, planning, preview overrides, export services.

## Guardrail checks

Import boundaries are enforced by [import-linter](https://import-linter.readthedocs.io/)
(contracts live in `pyproject.toml` under `[tool.importlinter]`):

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
.venv/bin/bandit -r src/dtm_buildsheet -lll   # enforcing high-severity security scan
```

## CI

GitHub Actions:

`.github/workflows/checks.yml` — triggered on every PR and push to `main`:
- **import-linter**: import-boundary contracts (fails on any new violation)
- **pip-audit**: known-vulnerability audit of resolved dependencies
- **bandit**: enforcing high-severity static security scan; the reviewed medium/low baseline is
  tracked in `docs/audit/LEDGER.md` FINDING-020

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

Semantic versioning (`bump-my-version`). See `docs/VERSIONING.md`. Current: `v3.5.0`.

## Release checklist

The current published release baseline and test totals are recorded in `CURRENT_STATE.md`. Treat
`CURRENT_STATE.md` as the live baseline rather than copying these totals into new planning docs.

The manual release workflow creates the tagged GitHub release and uploads versioned installers plus
release metadata to SharePoint `/Releases/` for the in-app updater.

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
