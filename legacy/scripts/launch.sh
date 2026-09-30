#!/usr/bin/env bash
# Launch the v1 prototype (Flash/Vox) in the tray. Prevents duplicate instances.
LEGACY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(dirname "$LEGACY_DIR")"
cd "$LEGACY_DIR"

if pgrep -f "python3.*flash_copilot" > /dev/null 2>&1; then
    echo "Flash Copilot already running. Not starting duplicate."
    exit 0
fi

export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}

# v1 talks to Ollama; start it if it isn't running
if ! curl -s http://localhost:11434 > /dev/null 2>&1; then
    ollama serve > /tmp/ollama.log 2>&1 &
    sleep 4
fi

source "$REPO_DIR/venv/bin/activate"
exec python3 "$LEGACY_DIR/flash_copilot.py" --tray "$@"
