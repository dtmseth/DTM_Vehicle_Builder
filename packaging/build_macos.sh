#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "Run ./Setup_DTM_VehicleBuilder.command first."
  exit 1
fi

.venv/bin/python -m pip install -e ".[packaging]"
.venv/bin/python -m PyInstaller --clean "packaging/pyinstaller/DTM_VehicleBuilder.spec"

echo ""
echo "Build complete."
echo "App bundle:"
echo "  dist/DTM Vehicle Builder.app"
