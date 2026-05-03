#!/bin/bash

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  osascript -e 'display alert "Setup required" message "Please run Setup_DTM_VehicleBuilder.command first." as critical'
  exit 1
fi

echo "============================================"
echo "  DTM Vehicle Builder — Test Suite"
echo "============================================"
echo ""

echo "Regenerating test workbooks from live config..."
.venv/bin/python scripts/gen_test_workbooks.py
echo ""

echo "Running tests..."
echo ""
.venv/bin/python -m pytest tests/ -v --tb=short 2>&1

echo ""
echo "============================================"
echo "  Done. Press any key to close."
echo "============================================"
read -n 1
