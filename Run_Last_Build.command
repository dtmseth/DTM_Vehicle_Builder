#!/bin/bash

cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo "  DTM Build Sheet v7"
echo "=========================================="
echo ""

if [ ! -x ".venv/bin/python" ]; then
    echo "Local v7 virtual environment not found."
    echo "Run Setup_DTM_VehicleBuilder.command first."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

.venv/bin/python -m dtm_buildsheet.generator_cli

if [ $? -eq 0 ]; then
    OUTPUT_FILE=$(ls -t workspace/output/*_v7.pptx 2>/dev/null | head -1)
    if [ -n "$OUTPUT_FILE" ]; then
        echo ""
        echo "Opening: $OUTPUT_FILE"
        echo ""
        open "$OUTPUT_FILE"
        exit 0
    fi
fi

echo ""
echo "The v7 generator did not finish cleanly."
read -p "Press Enter to close..."
