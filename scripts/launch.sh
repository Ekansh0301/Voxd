#!/usr/bin/env bash
# Flash Copilot launcher — prevents duplicate instances

PROJECT_DIR="$HOME/Downloads/flash-copilot"
cd "$PROJECT_DIR"

# If already running, do nothing
if pgrep -f "python3.*flash_copilot" > /dev/null 2>&1; then
    echo "Flash Copilot already running. Not starting duplicate."
    exit 0
fi

export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}

# Start Ollama if not running
if ! curl -s http://localhost:11434 > /dev/null 2>&1; then
    ollama serve > /tmp/ollama.log 2>&1 &
    sleep 4
fi

# Launch Flash in tray mode
source "$PROJECT_DIR/venv/bin/activate"
exec python3 "$PROJECT_DIR/flash_copilot.py" --tray "$@"
