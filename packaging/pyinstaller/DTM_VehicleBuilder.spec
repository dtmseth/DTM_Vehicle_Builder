# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path.cwd()
APP_NAME = "DTM Vehicle Builder"
ICON_DIR = ROOT / "packaging" / "icons"
MAC_ICON = ICON_DIR / "app.icns"
WIN_ICON = ICON_DIR / "app.ico"

datas = collect_data_files("dtm_buildsheet")
hiddenimports = collect_submodules("dtm_buildsheet")

import sys as _sys
if _sys.platform == 'darwin':
    icon_path = str(MAC_ICON) if MAC_ICON.exists() else None
else:
    icon_path = str(WIN_ICON) if WIN_ICON.exists() else None

a = Analysis(
    [str(ROOT / "packaging" / "pyinstaller" / "launch_gui.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=icon_path if MAC_ICON.exists() else None,
    bundle_identifier="com.dtm.vehiclebuilder",
)
