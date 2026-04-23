# Packaging

## Goal

Package the GUI-first app for macOS and Windows without changing how the core code is developed.

## Approach

- Keep application code in `src/dtm_buildsheet/`
- Keep packaging-specific files in `packaging/`
- Keep icons in `packaging/icons/`
- Keep the writable workspace outside the bundled app when packaged

## Current Choice

`PyInstaller` is the first packaging target because it is the shortest path to a real distributable app for both platforms.

## Build Entry

- macOS build script:
  `packaging/build_macos.sh`
- Windows build script:
  `packaging/build_windows.ps1`
- Shared PyInstaller spec:
  `packaging/pyinstaller/DTM_VehicleBuilder.spec`

## Icons

Place the app icons here:

- `packaging/icons/app.icns` for macOS
- `packaging/icons/app.ico` for Windows

You can replace them later at any time without touching the app code.
Just overwrite those files and rebuild.

## Output

PyInstaller outputs will be created under:

- `build/`
- `dist/`

Those are ignored by git.
