#!/bin/bash
# Run this once after mounting the DMG.
# It removes the macOS download quarantine flag so the app opens without a security block.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$SCRIPT_DIR/DTM Vehicle Builder.app"
if [ ! -d "$APP" ]; then
  osascript -e 'display alert "App not found" message "Make sure you are running this from inside the mounted DMG, next to \"DTM Vehicle Builder.app\"."'
  exit 1
fi
xattr -rd com.apple.quarantine "$APP" 2>/dev/null
open "$APP"
