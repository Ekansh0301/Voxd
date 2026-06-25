#!/usr/bin/env bash
# scripts/ptt.sh
# ─────────────────────────────────────────────────────────────────────────────
# Push-to-Talk helper script.
# Bind this to a key in GNOME Settings → Keyboard → Custom Shortcuts.
#
# When the key is pressed: sends signal to Flash Copilot to start recording
# When the key is released: sends signal to stop recording
#
# Alternatively, the built-in pynput listener handles this automatically.
# Use this script only if you prefer OS-level hotkey binding.
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PIDFILE="$PROJECT_DIR/.flash_copilot.pid"
SIGNAL_FILE="$PROJECT_DIR/.ptt_signal"

ACTION="${1:-toggle}"

case "$ACTION" in
    start)
        echo "RECORD_START" > "$SIGNAL_FILE"
        notify-send "Flash Copilot" "🎤 Listening..." \
            --icon=audio-input-microphone \
            --urgency=low \
            --expire-time=10000 \
            2>/dev/null || true
        ;;
    stop)
        echo "RECORD_STOP" > "$SIGNAL_FILE"
        ;;
    toggle)
        if [ -f "$SIGNAL_FILE" ] && grep -q "RECORD_START" "$SIGNAL_FILE" 2>/dev/null; then
            echo "RECORD_STOP" > "$SIGNAL_FILE"
        else
            echo "RECORD_START" > "$SIGNAL_FILE"
            notify-send "Flash Copilot" "🎤 Listening..." \
                --icon=audio-input-microphone \
                --urgency=low \
                --expire-time=5000 \
                2>/dev/null || true
        fi
        ;;
    *)
        echo "Usage: $0 [start|stop|toggle]"
        exit 1
        ;;
esac
