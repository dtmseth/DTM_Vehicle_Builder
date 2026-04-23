# DTM Build Sheet v7

DTM Build Sheet v7 is the cleaned-up app-first rebuild of the original v5 one-off workspace.

The GUI is the primary product surface.
The workbook parser, planning pipeline, and PowerPoint renderer now live in a Python package under `src/dtm_buildsheet`, while editable user data lives in `workspace/`.

## Layout

- `src/dtm_buildsheet/`
  The application package, GUI server, generation pipeline, templates, and bundled defaults.
- `workspace/`
  User-editable config, uploaded workbooks, generated outputs, and mutable asset copies.
- `samples/`
  Sample input workbooks kept out of the live workspace.
- `docs/`
  Project and packaging notes.

## Getting Started

```bash
cd /Users/skreev/Desktop/DTM_BuildSheet_POC_v7
./Setup_DTM_VehicleBuilder.command
./Launch_DTM_VehicleBuilder.command
```

The first launch will copy default config and assets into `workspace/`.

## Development

```bash
cd /Users/skreev/Desktop/DTM_BuildSheet_POC_v7
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m dtm_buildsheet
```

CLI generation remains available for verification:

```bash
.venv/bin/python -m dtm_buildsheet.generator_cli /path/to/workbook.xlsx
```

## Packaging Direction

This repo is now structured so it can later be packaged as a desktop application:

- Python code is in a package instead of loose scripts.
- GUI resources are bundled with the package.
- Mutable files are separated from shipped app resources.
- `pyproject.toml` is the source of truth for dependencies and entry points.

The likely next packaging step is:

1. Build and stabilize the GUI-only workflow.
2. Add a thin desktop shell for macOS and Windows.
3. Bundle with a Python app packager such as PyInstaller or Briefcase.
