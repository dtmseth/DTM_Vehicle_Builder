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

## QuickBooks (conditionally relevant)

If working on QuickBooks: read [docs/QUICKBOOKS.md](docs/QUICKBOOKS.md) (single hub — status,
design, security invariants, App Assessment answers).

Secrets never touch disk/cloud — OS keychain only via `credential_store.py`.
