#!/bin/bash

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  osascript -e 'display alert "Setup required" message "Please run Setup_DTM_VehicleBuilder.command before using the app." as critical'
  exit 1
fi

.venv/bin/python -m dtm_buildsheet
