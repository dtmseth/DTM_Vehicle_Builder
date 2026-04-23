# DTM Vehicle Builder — Project Brief

## What it is
A desktop GUI app that generates PowerPoint build sheets for police/emergency vehicles. User uploads an Excel workbook → app parses it, applies part configs and layout rules, produces a `.pptx`. Runs as a local HTTP server with a web UI displayed in a native window (pywebview).

## Tech stack
- **Python 3.13+** (local dev uses 3.14 via Homebrew)
- **pywebview 5.x** — wraps WKWebView (Mac) / WebView2 (Windows) for native window
- **python-pptx** — PowerPoint output
- **openpyxl** — Excel parsing
- **Pillow, lxml** — image handling, XML
- **PyInstaller 6.x** — packaging
- **GitHub Actions** — CI builds Mac `.dmg` + Windows `.exe` installer on every push to `main`

## Repo layout
```
CLAUDE.md                          ← you are here
pyproject.toml                     ← package config, deps, entry points
README.md

src/dtm_buildsheet/                ← the Python package
  gui_server.py                    ← HTTP server + all API routes (PORT 7655)
  gui_ui.html                      ← entire frontend (single file)
  paths.py                         ← all path logic; dev vs bundled app detection
  generator.py                     ← orchestrates a full build-sheet run
  input_reader.py                  ← Excel workbook → Project model
  planner.py                       ← decides slide layout per vehicle type
  render_ppt.py                    ← writes the .pptx (output: VehicleBuilder_{id}_v7.pptx)
  reporting.py                     ← markdown summary alongside the .pptx
  config_loader.py / config_store.py / config_validation.py
  models.py                        ← dataclasses: Project, Part, Placement
  naming.py                        ← part/color name normalization
  template_builder.py              ← regenerates the Excel input template
  ppt_helpers.py                   ← python-pptx utilities
  resources/
    config/*.json                  ← bundled defaults (copied to workspace on first run)
    templates/*.pptx / *.xlsx      ← bundled templates
    assets/**/*.png                ← bundled vehicle/equipment/light images

workspace/                         ← mutable user data (git-ignored)
  config/   input/   output/   assets/

packaging/
  pyinstaller/
    DTM_VehicleBuilder.spec        ← PyInstaller spec (handles both platforms)
    launch_gui.py                  ← entrypoint for bundled app
  windows/
    installer.iss                  ← Inno Setup script → DTM_Vehicle_Builder_Setup.exe
  icons/
    app.icns                       ← real multi-res ICNS (built via iconutil from PNG)
    app.ico                        ← 6-size ICO (built via Pillow from same PNG)
  build_macos.sh / build_windows.ps1

.github/workflows/build.yml        ← CI: parallel mac + windows builds, artifacts uploaded

samples/input/                     ← test .xlsx workbooks
docs/                              ← ARCHITECTURE.md, PACKAGING.md, PIPELINE.md
```

## Key entry points
| Script | Purpose |
|--------|---------|
| `Setup_DTM_VehicleBuilder.command` / `.bat` | Creates `.venv`, installs package |
| `Launch_DTM_VehicleBuilder.command` / `.bat` | Runs `python -m dtm_buildsheet` (GUI) |
| `Run_Last_Build.command` / `.bat` | Runs CLI generator, opens output .pptx |
| `Build_Mac_App.command` | One-click PyInstaller rebuild → `dist/DTM Vehicle Builder.app` |
| `packaging/build_windows.ps1` | Same for Windows (run on Windows machine or via CI) |

## How the app runs
`gui_server.py:main()` starts an HTTP server on `127.0.0.1:7655`, then:
- **With pywebview installed**: server moves to background thread, pywebview opens a native window pointing at `http://localhost:7655` (must own main thread — macOS requirement)
- **Without pywebview**: falls back to `webbrowser.open()` (dev convenience)

Port conflict on launch = old instance still running. `lsof -ti :7655 | xargs kill` clears it.

## Workspace vs bundled resources
`paths.py` detects dev vs bundled via presence of `pyproject.toml`:
- **Dev**: workspace is `{repo}/workspace/`, resources from `src/dtm_buildsheet/resources/`
- **Bundled app**: workspace is `~/Library/Application Support/DTM Vehicle Builder` (Mac) or `%APPDATA%\DTM Vehicle Builder` (Windows)

On first run, bundled default configs/assets are copied into the workspace. User edits live in workspace and are never overwritten.

## Packaging
**Mac** (run on Mac):
```bash
bash packaging/build_macos.sh        # or double-click Build_Mac_App.command
# output: dist/DTM Vehicle Builder.app
```
**Windows** (run on Windows or via CI):
```powershell
.\packaging\build_windows.ps1
# output: dist\DTM Vehicle Builder\  →  then Inno Setup → DTM_Vehicle_Builder_Setup.exe
```
**CI** (GitHub Actions — both built automatically on push to `main`):
- Mac job: PyInstaller → `.app` → `.dmg` (drag-to-Applications)
- Windows job: PyInstaller → Inno Setup → `DTM_Vehicle_Builder_Setup.exe`
- Artifacts downloadable from the Actions run page

## pyproject.toml quick ref
```toml
name = "dtm-buildsheet"          # internal package name (Python import: dtm_buildsheet)
version = "0.7.0"
dependencies = [lxml, openpyxl, Pillow, python-pptx, pywebview]
[packaging] extras = [pyinstaller, pyinstaller-hooks-contrib]
```

## Gotchas
- **Python package name** is still `dtm_buildsheet` / `dtm-buildsheet` — only the *app* name changed to "DTM Vehicle Builder". Don't rename the `src/dtm_buildsheet/` directory without updating all imports.
- **ICNS must be real ICNS** — the source icon was a PNG renamed to `.icns`. It was converted properly via `iconutil`. Don't replace it with a raw PNG or PyInstaller will silently fall back to the Python icon.
- **pywebview owns the main thread** on macOS — the HTTP server must run in a daemon thread when pywebview is active. Don't move `webview.start()` off the main thread.
- **PyInstaller cannot cross-compile** — Mac builds must run on Mac, Windows builds must run on Windows (CI handles this).
- **GitHub repo**: `https://github.com/dtmseth/DTM_Vehicle_Builder` — push to `main` triggers both builds.
