#!/bin/bash
# Removes the macOS quarantine flag set on downloaded files, then opens the app.
# Double-click this once after downloading — you won't need it again.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$SCRIPT_DIR/DTM Vehicle Builder.app"
if [ ! -d "$APP" ]; then
  osascript -e 'display alert "App not found" message "Make sure this script is in the same folder as \"DTM Vehicle Builder.app\"."'
  exit 1
fi
xattr -rd com.apple.quarantine "$APP" 2>/dev/null
open "$APP"
