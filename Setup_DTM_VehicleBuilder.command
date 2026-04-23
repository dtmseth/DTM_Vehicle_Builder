#!/bin/bash

cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo "  DTM Build Sheet v7 Setup"
echo "=========================================="
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found on this machine."
    read -p "Press Enter to close..."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating local virtual environment..."
    python3 -m venv .venv
fi

echo "Installing v7 into .venv..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

if [ $? -eq 0 ]; then
    echo ""
    echo "v7 setup complete."
    echo "You can now run Launch_DTM_VehicleBuilder.command"
    exit 0
fi

echo ""
echo "v7 setup did not finish cleanly."
read -p "Press Enter to close..."
