# DTM Vehicle Builder

Generates PowerPoint build sheets for police and emergency vehicles. Upload an Excel workbook, configure parts and layout, export a finished `.pptx`.

Runs as a native desktop app on macOS and Windows — no browser required.

---

## Installing

### Mac
[Download DTM_Vehicle_Builder.dmg](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/download/latest/DTM_Vehicle_Builder.dmg) — open it, drag the app to Applications.

### Windows
[Download DTM_Vehicle_Builder_Setup.exe](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/download/latest/DTM_Vehicle_Builder_Setup.exe) — run the installer.

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
src/dtm_buildsheet/       Python package — server, pipeline, bundled resources
workspace/                User data — configs, inputs, outputs, assets (git-ignored)
samples/                  Sample input workbooks
packaging/
  pyinstaller/            PyInstaller spec + entrypoint
  windows/                Inno Setup installer script
  icons/                  app.icns (Mac), app.ico (Windows)
docs/                     Architecture, pipeline, and packaging notes
.github/workflows/        CI — builds Mac .dmg and Windows .exe on every push to main
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

**CI** — both are built automatically on every push to `main`. Download artifacts from the [Actions tab](https://github.com/dtmseth/DTM_Vehicle_Builder/actions).

---

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m dtm_buildsheet        # GUI
.venv/bin/python -m dtm_buildsheet.generator_cli /path/to/workbook.xlsx  # CLI
```

If the app fails to launch with "Port 7655 is already in use", a previous instance is still running:
```bash
lsof -ti :7655 | xargs kill
```
