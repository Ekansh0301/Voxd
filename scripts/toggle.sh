#!/usr/bin/env bash
# Toggle Vox visibility
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID=$(pgrep -f "python3.*flash_copilot" | head -1)
if [ -z "$PID" ]; then
    "$SCRIPT_DIR/launch.sh" &
else
    # Vox is running — bring it to front via tray
    echo "Vox is running. Use the tray icon."
fi
