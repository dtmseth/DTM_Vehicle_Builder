#!/bin/bash

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  osascript -e 'display alert "Setup required" message "Please run Setup_DTM_VehicleBuilder.command before using the app." as critical'
  exit 1
fi

# Dev mode: don't let the cloud pull overwrite local config edits (parts_db.json,
# vehicle_layouts.json, etc.) on launch. Saves still mirror UP to the cloud.
# Remove this line to go back to normal cloud-synced launches.
export DTM_DEV_NO_SETTINGS_PULL=1

.venv/bin/python -m dtm_buildsheet
