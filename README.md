# DTM Vehicle Builder

Desktop workflow for planning police and emergency vehicles. It manages shared projects, agencies,
sales reps, presets, per-unit build drafts, review/finalization, customer PDFs, editable PowerPoint
sources, and non-posting QuickBooks Online Estimates.

Runs as a native desktop app on macOS and Windows — no browser required.

Current production release: [v3.5.0](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/tag/v3.5.0).

---

## Installing

### Mac
[Download DTM_Vehicle_Builder.dmg](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/latest/download/DTM_Vehicle_Builder.dmg) — open it, drag the app to Applications.

### Windows
[Download DTM_Vehicle_Builder_Setup.exe](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/latest/download/DTM_Vehicle_Builder_Setup.exe) — run the installer.

---

## Running from source

**Mac:**
```bash
double-click Setup_DTM_VehicleBuilder.command    # first time only
double-click Launch_DTM_VehicleBuilder.command
```

**Windows:**
```bat
double-click Setup_DTM_VehicleBuilder.bat        # first time only
double-click Launch_DTM_VehicleBuilder.bat
```

The first launch copies default configs and assets into your workspace folder.

---

## Repo layout

```
src/dtm_buildsheet/       Python package — app server, domain, planning, rendering, UI, resources
workspace/                Local mirror/cache — configs, drafts, projects, outputs, assets (git-ignored)
samples/                  Sample input workbooks
packaging/
  pyinstaller/            PyInstaller spec + entrypoint
  windows/                Inno Setup installer script
  icons/                  app.icns (Mac), app.ico (Windows)
docs/                     Architecture, pipeline, config schema, repo principles, packaging notes
.github/workflows/        Checks, platform builds, and tagged release publication
```

---

## Building the app

**Mac** — double-click `Build_Mac_App.command`, or:
```bash
bash packaging/build_macos.sh
# output: dist/DTM Vehicle Builder.app
```

**Windows:**
```powershell
.\packaging\build_windows.ps1
# output: dist\DTM Vehicle Builder\  +  dist\DTM_Vehicle_Builder_Setup.exe
```

**CI** — both platforms are built automatically on every push to `main`. The manual release workflow
publishes a tagged GitHub release and stages the installers/release metadata in SharePoint. Download
ordinary build artifacts from the [Actions tab](https://github.com/dtmseth/DTM_Vehicle_Builder/actions).

---

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m dtm_buildsheet        # GUI
.venv/bin/python -m dtm_buildsheet.generator_cli /path/to/workbook.xlsx  # CLI
```

Run automated tests:
```bash
.venv/bin/python -m pytest
```

Versioning follows Semantic Versioning. See `docs/VERSIONING.md` before publishing a release.

If the app fails to launch with "Port 7655 is already in use", a previous instance is still running:
```bash
lsof -ti :7655 | xargs kill
```
