# DTM Vehicle Builder

Desktop GUI app (Python/pywebview) that generates PowerPoint build sheets for police/emergency
vehicles. HTTP server + web UI in a native window. GitHub: `https://github.com/dtmseth/DTM_Vehicle_Builder`

## Package manager

pip (inside `.venv`): `pip install -e ".[dev]"`

## Key commands

```bash
.venv/bin/python -m dtm_buildsheet             # GUI (port 7655)
.venv/bin/python -m dtm_buildsheet.generator_cli book.xlsx  # CLI
.venv/bin/python -m pytest                     # full test suite
bash packaging/build_macos.sh                  # package Mac app
```

## Project docs

| Doc | When to read |
|-----|-------------|
| [docs/GOTCHAS.md](docs/GOTCHAS.md) | Before any edit — footguns by module |
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
| [docs/audit/SESSION_HANDOFF_2026-07-13.md](docs/audit/SESSION_HANDOFF_2026-07-13.md) | **Current work** — what's shipped, what's open, where we're headed |

## Current work (2026-07)

Rebuilding the legacy name-based draft projects in the new Part Picker and fixing
picker/placement flaws (owner flaw list). Status + next steps live in the session handoff
above; findings in the ledger. **Working norms:** run cloud-off
(`DTM_CLOUD=0 python -m dtm_buildsheet` or preview config "DTM App") — cloud-on triggers the 60s
SharePoint sync that clobbers `parts_db.json`. Safety pins are `pytest tests/golden
tests/contract` + `tools/ui_smoke/run_smoke.py` (currently 16 smoke flows). Golden masters must
NOT move from authoring/DB changes; re-record contract snapshots only on intended DB/route
changes, diff eyeballed. Current dirty-tree note: contract tests and UI smoke are green, but
`pytest tests/golden tests/contract` has known golden digest drift pending owner review. Render
**size + image** data now belongs in `parts_db` at the **part-type level** (owner directive), not
the legacy `parts_library.json`/`part_catalog.json`/`asset_manifest.json`, and not per-SKU
(see LEDGER FINDING-035).

## QuickBooks (conditionally relevant)

If working on QuickBooks: read [docs/QUICKBOOKS.md](docs/QUICKBOOKS.md) (single hub — status,
design, security invariants, App Assessment answers).

Secrets never touch disk/cloud — OS keychain only via `credential_store.py`.
