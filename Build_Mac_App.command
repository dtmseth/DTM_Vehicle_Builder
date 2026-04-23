#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo "  DTM Vehicle Builder - Mac App Build"
echo "=========================================="
echo ""

if [ ! -x ".venv/bin/python" ]; then
    echo "Virtual environment not found."
    echo "Run Setup_DTM_VehicleBuilder.command first."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

echo "Installing dependencies..."
.venv/bin/python -m pip install -e ".[packaging]" -q

echo "Building app..."
rm -rf "dist/DTM Vehicle Builder.app" "dist/DTM Vehicle Builder"
.venv/bin/python -m PyInstaller -y "packaging/pyinstaller/DTM_VehicleBuilder.spec"

if [ $? -eq 0 ]; then
    echo ""
    echo "Build complete!"
    echo ""
    echo "  dist/DTM Vehicle Builder.app"
    echo ""
    open dist/
    read -p "Press Enter to close..."
    exit 0
fi

echo ""
echo "Build did not finish cleanly. Check the output above."
read -p "Press Enter to close..."
