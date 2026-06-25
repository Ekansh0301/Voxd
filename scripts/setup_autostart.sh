#!/usr/bin/env bash
# Sets up Flash Copilot to start automatically on login
# Run once: bash scripts/setup_autostart.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
USER_HOME="$HOME"

echo "Setting up Flash Copilot autostart..."

# 1. Create the launcher script (handles venv activation automatically)
cat > "$PROJECT_DIR/scripts/launch.sh" << EOF
#!/usr/bin/env bash
cd "$PROJECT_DIR"
export DISPLAY=\${DISPLAY:-:0}
export XAUTHORITY=\${XAUTHORITY:-\$HOME/.Xauthority}

# Start Ollama if not running
if ! curl -s http://localhost:11434 > /dev/null 2>&1; then
    ollama serve > /tmp/ollama.log 2>&1 &
    sleep 4
fi

# Activate venv and launch
source "$PROJECT_DIR/venv/bin/activate"
exec python3 "$PROJECT_DIR/flash_copilot.py" --tray "\$@"
EOF
chmod +x "$PROJECT_DIR/scripts/launch.sh"
echo "✓ launch.sh updated"

# 2. GNOME autostart entry (starts on login, no terminal needed)
mkdir -p "$USER_HOME/.config/autostart"
cat > "$USER_HOME/.config/autostart/flash-copilot.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Flash Copilot
Exec=$PROJECT_DIR/scripts/launch.sh
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Flash AI Copilot — starts in system tray on login
EOF
echo "✓ GNOME autostart entry created"

# 3. Application launcher (shows in app grid)
mkdir -p "$USER_HOME/.local/share/applications"
cat > "$USER_HOME/.local/share/applications/flash-copilot.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Flash Copilot
Comment=Your local AI assistant
Exec=$PROJECT_DIR/scripts/launch.sh
Terminal=false
Categories=Utility;
Keywords=AI;assistant;voice;
EOF
update-desktop-database "$USER_HOME/.local/share/applications" 2>/dev/null || true
echo "✓ App launcher entry created"

# 4. Optional: keyboard shortcut to toggle show/hide (GNOME)
echo ""
echo "Optional: set a keyboard shortcut to show/hide Flash:"
echo "  Settings → Keyboard → Custom Shortcuts → Add:"
echo "  Name: Toggle Flash Copilot"
echo "  Command: $PROJECT_DIR/scripts/toggle.sh"
echo "  Key: Super+Space (or your preference)"

# 5. Create toggle script
cat > "$PROJECT_DIR/scripts/toggle.sh" << EOF
#!/usr/bin/env bash
# Toggle Flash Copilot visibility
PID=\$(pgrep -f "python3.*flash_copilot" | head -1)
if [ -z "\$PID" ]; then
    "$PROJECT_DIR/scripts/launch.sh" &
else
    # Flash is running — bring it to front via tray
    echo "Flash is running. Use the tray icon."
fi
EOF
chmod +x "$PROJECT_DIR/scripts/toggle.sh"
echo "✓ toggle.sh created"

echo ""
echo "Done! Flash Copilot will now start automatically on next login."
echo "To start it right now without rebooting:"
echo "  bash $PROJECT_DIR/scripts/launch.sh &"
