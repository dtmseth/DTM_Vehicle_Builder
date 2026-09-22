#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "Run ./Setup_DTM_VehicleBuilder.command first."
  exit 1
fi

if [ -n "${DTM_MAC_CODESIGN_IDENTITY:-}" ] && [ -n "${DTM_INTERNAL_CODESIGN_IDENTITY:-}" ]; then
  echo "Set only one of DTM_MAC_CODESIGN_IDENTITY or DTM_INTERNAL_CODESIGN_IDENTITY."
  exit 1
fi

if [ -n "${DTM_MAC_CODESIGN_IDENTITY:-}" ]; then
  export PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR=1
  export PYINSTALLER_VERIFY_BUNDLE_SIGNATURE=1
fi

.venv/bin/python -m pip install -e ".[packaging]"
.venv/bin/python -m PyInstaller --clean "packaging/pyinstaller/DTM_VehicleBuilder.spec"

if [ -n "${DTM_INTERNAL_CODESIGN_IDENTITY:-}" ]; then
  codesign --force --deep --sign "$DTM_INTERNAL_CODESIGN_IDENTITY" "dist/DTM Vehicle Builder.app"
  codesign --verify --deep --strict --verbose=2 "dist/DTM Vehicle Builder.app"
fi

echo ""
echo "Build complete."
echo "App bundle:"
echo "  dist/DTM Vehicle Builder.app"
