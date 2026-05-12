#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "Run ./Setup_DTM_VehicleBuilder.command first."
  exit 1
fi

.venv/bin/python -m pip install -e ".[packaging]"
.venv/bin/python -m PyInstaller --clean "packaging/pyinstaller/DTM_VehicleBuilder.spec"

APP_VERSION=$(.venv/bin/python -c "import re; print(re.search(r'version\s*=\s*\"([^\"]+)\"', open('pyproject.toml').read()).group(1))")

mkdir -p /tmp/pkg_root/Applications
cp -r "dist/DTM Vehicle Builder.app" "/tmp/pkg_root/Applications/"
pkgbuild \
  --root /tmp/pkg_root \
  --identifier com.dtm.vehiclebuilder \
  --version "$APP_VERSION" \
  "dist/DTM_Vehicle_Builder.pkg"
rm -rf /tmp/pkg_root

echo ""
echo "Build complete."
echo "Installer: dist/DTM_Vehicle_Builder.pkg"
