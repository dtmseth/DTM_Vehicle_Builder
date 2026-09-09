# DTM Vehicle Builder

Desktop GUI app (Python/pywebview) that generates PowerPoint build sheets for police/emergency
vehicles. HTTP server + web UI in a native window. GitHub: `https://github.com/dtmseth/DTM_Vehicle_Builder`

## Package manager

pip (inside `.venv`): `pip install -e ".[dev]"`

## Key commands

```bash
.venv/bin/python -m dtm_buildsheet             # GUI (port 7655)
.venv/bin/python -m dtm_buildsheet.generator_cli book.xlsx  # CLI
.venv/bin/python tools/verify.py changed       # focused, compact local verification
.venv/bin/python tools/verify.py release       # full release gate only
bash packaging/build_macos.sh                  # package Mac app
```

## Mandatory verification workflow

This applies to every future agent/session working in this repository:

- During implementation, run `.venv/bin/python tools/verify.py changed`. It selects tests and
  browser flows from the current Git diff and captures successful output.
- After tiny intermediate edits, prefer syntax checks or one directly relevant test; run the
  changed gate after a meaningful batch, not after every line-level adjustment.
- Do not run bare full `pytest`, all 28 browser flows, or coverage during the normal inner loop.
- Do not stream individual passing-test names or browser-flow JSON into the conversation. Successful
  verification should be reported as compact counts/summaries; show detailed output only for the
  first actionable failure.
- Run `.venv/bin/python tools/verify.py release` once at an actual release/merge checkpoint, when the
  user explicitly requests it, or after a genuinely cross-cutting core contract change. State why a
  full gate is warranted before running it. CI remains the authoritative full-suite/coverage gate.

These rules are a token and developer-time constraint, not merely a formatting preference.

## Project docs

| Doc | When to read |
|-----|-------------|
| [docs/GOTCHAS.md](docs/GOTCHAS.md) | Before any edit — footguns by module |
| [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) | **Start here** — live release, verification baseline, roadmap position, next work |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, test commands, CI, packaging |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Runtime shape, design rules, central flow |
| [docs/REPOSITORY_PRINCIPLES.md](docs/REPOSITORY_PRINCIPLES.md) | Engineering philosophy, do/don't |
| [docs/DATA_MODELS.md](docs/DATA_MODELS.md) | Dataclasses, storage layout |
| [docs/UI_STRUCTURE.md](docs/UI_STRUCTURE.md) | Tab layout, JS patterns, DOM singletons |
| [docs/PRESETS.md](docs/PRESETS.md) | Preset schema, cloud mirror |
| [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) | Config file schemas |
| [docs/PROJECT_WORKFLOW.md](docs/PROJECT_WORKFLOW.md) | Project → draft → output data flow |
| [docs/FEATURE_INVENTORY.md](docs/FEATURE_INVENTORY.md) | Every feature and non-obvious rule |
| [docs/PACKAGING.md](docs/PACKAGING.md) | PyInstaller builds |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases, critical path, QB-as-foundation framing |
| [docs/PARTS_DB_AND_PICKER.md](docs/PARTS_DB_AND_PICKER.md) | parts_db schema, Part Picker, accessories, tracers/bars, pending-QB, data backlog |
| [docs/EXTERNAL_CONNECTION_SECURITY.md](docs/EXTERNAL_CONNECTION_SECURITY.md) | Security standards for API integrations |
| [docs/AUDIT_REFACTOR_ROADMAP.md](docs/AUDIT_REFACTOR_ROADMAP.md) | Audit/refactor meta-plan, working method, model allocation |
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
can replace local `parts_db.json`. Safety pins are `pytest tests/golden tests/contract` plus
`tools/ui_smoke/run_smoke.py` (currently 28 smoke flows). Golden masters must not move merely to make
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
