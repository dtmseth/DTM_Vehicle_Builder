# -*- mode: python ; coding: utf-8 -*-

import re
import sys as _sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path.cwd()
APP_NAME = "DTM Vehicle Builder"
ICON_DIR = ROOT / "packaging" / "icons"
MAC_ICON = ICON_DIR / "app.icns"
WIN_ICON = ICON_DIR / "app.ico"

# Read version from pyproject.toml — single source of truth.
_pyproject = ROOT / "pyproject.toml"
_version_match = re.search(r'^version\s*=\s*"([^"]+)"', _pyproject.read_text(), re.MULTILINE)
APP_VERSION = _version_match.group(1) if _version_match else "0.0.0"

datas = collect_data_files("dtm_buildsheet")

# Explicitly bundle resources so they're always present regardless of
# how collect_data_files resolves the editable install in CI.
_res = ROOT / "src" / "dtm_buildsheet" / "resources"
_ui  = ROOT / "src" / "dtm_buildsheet" / "ui"
if _res.exists():
    datas += [( str(_res), "dtm_buildsheet/resources" )]
if _ui.exists():
    datas += [( str(_ui), "dtm_buildsheet/ui" )]

hiddenimports = collect_submodules("dtm_buildsheet")

# Windows PDF export uses PowerPoint COM via comtypes (runtime import — not
# detected by static analysis). Must be explicit or the frozen app crashes.
if _sys.platform != "darwin":
    hiddenimports += [
        "comtypes",
        "comtypes.client",
        "comtypes.server",
        "comtypes.server.factory",
        "comtypes.typeinfo",
    ]

icon_path = str(MAC_ICON) if _sys.platform == "darwin" and MAC_ICON.exists() else \
            str(WIN_ICON) if _sys.platform != "darwin" and WIN_ICON.exists() else None

_manifest = ROOT / "packaging" / "windows" / "DTM_VehicleBuilder.manifest"
manifest_path = str(_manifest) if _sys.platform != "darwin" and _manifest.exists() else None

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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    manifest=manifest_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=icon_path,
    bundle_identifier="com.dtm.vehiclebuilder",
    info_plist={
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "NSHighResolutionCapable": True,
    },
)
