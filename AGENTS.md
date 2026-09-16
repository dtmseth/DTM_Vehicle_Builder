# DTM Vehicle Builder

Desktop GUI app (Python/pywebview) that generates PowerPoint build sheets for police/emergency
vehicles. HTTP server + web UI in a native window. GitHub: `https://github.com/dtmseth/DTM_Vehicle_Builder`

## Package manager

pip (inside `.venv`): `pip install -e ".[dev,hosted]"` (hosted extra is needed for boundary tests)

## Key commands

```bash
.venv/bin/python -m dtm_buildsheet             # GUI (port 7655)
.venv/bin/python -m dtm_buildsheet.generator_cli book.xlsx  # CLI
.venv/bin/python -m pytest tests/test_<target>.py --maxfail=1  # one relevant file
.venv/bin/python tools/verify.py changed --skip-smoke  # only on explicit pre-commit request
.venv/bin/python tools/verify.py release       # pre-release checks only
bash packaging/build_macos.sh                  # package Mac app
```

## Mandatory verification workflow

This applies to every future agent/session working in this repository:

- During iterative work, run ONLY the single relevant test file, for example
  `.venv/bin/python -m pytest tests/test_<target>.py --maxfail=1`. Do not broaden the run
  because unrelated files are dirty. Documentation/ignore-only edits need no pytest run.
- Never run browser smoke tests (`tools/ui_smoke/run_smoke.py`) autonomously during normal
  editing or small feature additions, including indirectly through another tool or wrapper.
- Reserve `tools/verify.py changed` for an explicit owner request for a verification pass
  before committing. Use `--skip-smoke` for that pass; the bare command also launches browser
  flows. A request to commit alone does not authorize this verification pass.
- Reserve full browser runs and `tools/verify.py release` strictly for pre-release checks.
  A merge checkpoint, meaningful edit batch, or cross-cutting change is not an exception.
- Do not run full pytest, coverage, or multiple test files during the normal inner loop.
- Do not stream individual passing-test names or browser-flow JSON into the conversation. Successful
  verification should be reported as compact counts/summaries; show detailed output only for the
  first actionable failure.
- CI remains the authoritative full-suite/coverage gate.

These rules are a token and developer-time constraint, not merely a formatting preference.
They supersede older testing instructions in plans, handoffs, and other repository documents.

## Context footprint and local assets

- Do NOT delete or modify `workspace/reference_media/` or any images under `src/` during
  workflow cleanup. These are required application storage assets and must remain on disk.
- Exclude `workspace/`, `dist/`, `build/`, `output/`, `tmp/`, `.venv/`, and `venv/` from broad
  searches and context/indexing. Exclude `*.png`, `*.jpg`, `*.jpeg`, `*.mp4`, `*.sqlite3`,
  and `*.db` as well. Search named source/docs paths and read only relevant sections.
- `.claudeignore` records these context exclusions; tools that do not honor it must use
  explicit path/glob exclusions. Git ignore rules do not hide already tracked media.
- Ignore rules are not deletion instructions. Never use `git clean -fdx` for this cleanup.
- `tools/verify.py changed` includes staged and unstaged changes against `HEAD`, plus untracked
  files. Staging alone does not narrow it; establish a committed baseline or intentionally
  stash unrelated work before an owner-requested verification pass.

## Project docs

| Doc | When to read |
|-----|-------------|
| [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) | Scan only the "Next Work" section if context is needed |
| [docs/GOTCHAS.md](docs/GOTCHAS.md) | Only when debugging unexpected errors in specific modules |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Only when adding new system boundaries or services |
| [docs/DATA_MODELS.md](docs/DATA_MODELS.md) | Only when modifying dataclasses or serialization |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | System authority, core SharePoint schemas, and role/capability matrix |
| [docs/HOSTED_ARCHITECTURE.md](docs/HOSTED_ARCHITECTURE.md) | Hosted security boundary, container operations, cleanup, and recovery |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, test commands, CI, packaging |
| [docs/REPOSITORY_PRINCIPLES.md](docs/REPOSITORY_PRINCIPLES.md) | Engineering philosophy, do/don't |
| [docs/UI_STRUCTURE.md](docs/UI_STRUCTURE.md) | Tab layout, JS patterns, DOM singletons |
| [docs/PRESETS.md](docs/PRESETS.md) | Preset schema, cloud mirror |
| [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) | Config file schemas |
| [docs/PROJECT_WORKFLOW.md](docs/PROJECT_WORKFLOW.md) | Project → draft → output data flow |
| [docs/FEATURE_INVENTORY.md](docs/FEATURE_INVENTORY.md) | Every feature and non-obvious rule |
| [docs/PACKAGING.md](docs/PACKAGING.md) | PyInstaller builds |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Vision, pillars, and active critical-path backlog |
| [docs/PARTS_DB_AND_PICKER.md](docs/PARTS_DB_AND_PICKER.md) | parts_db schema, Part Picker, accessories, tracers/bars, pending-QB, data backlog |
| [docs/EXTERNAL_CONNECTION_SECURITY.md](docs/EXTERNAL_CONNECTION_SECURITY.md) | Security standards for API integrations |
| [docs/audit/LEDGER.md](docs/audit/LEDGER.md) | Findings ledger (FINDING-nnn) — check before treating a flaw as new |
| [docs/audit/PICKER_REDESIGN.md](docs/audit/PICKER_REDESIGN.md) | Part Picker redesign spec (browse tree, options-in-box, editor) |

## Current work (2026-09)

Production v3.7.0 is live. Per-vehicle Company/Shop folders, reference/completed-photo workflows,
finalized Shop publication, role-gated Operations workspaces, and the non-backend folder migration
are the production baseline. The
architectural backlog remains Phase 4's consumer migration, reviewed QuickBooks catalog-change
governance, and the visible parts-curation queue. See
`docs/CURRENT_STATE.md`. **Working norms:** run cloud-off (`DTM_CLOUD=0 python -m
dtm_buildsheet` or preview config "DTM App") unless intentionally testing SharePoint — cloud sync
can replace local `parts_db.json`. Pre-release safety pins are `pytest tests/golden tests/contract`
plus `tools/ui_smoke/run_smoke.py`; the testing rules above govern when they run.
Golden masters must not move merely to make
tests green; re-record intentional render changes only with focused behavioral coverage and a
representative export check. Re-record contract snapshots only for intended DB/route changes after review.
Render **size + image** data belongs in `parts_db` at the **part-type level**, not per SKU or in the
legacy catalog files (see LEDGER FINDING-035).

## QuickBooks (conditionally relevant)

If working on QuickBooks: read [docs/QUICKBOOKS.md](docs/QUICKBOOKS.md) (single hub — status,
design, security invariants, App Assessment answers).

Per-user QuickBooks tokens never touch disk/cloud — OS keychain only via `credential_store.py`.
The shared Intuit app secret is never shipped to desktops; it exists only as a protected Netlify
environment variable used by the stateless OAuth token broker.
