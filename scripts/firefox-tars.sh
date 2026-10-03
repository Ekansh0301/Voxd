#!/usr/bin/env bash
# "Firefox (TARS)": your normal Firefox profile with remote control switched on,
# so TARS can open tabs, read pages, click and type in it (Mozilla's
# firefox-devtools-mcp). Firefox listens on localhost only and shows a striped
# address bar while remote control is on. Your normal Firefox launcher is unchanged.
if pgrep -x firefox >/dev/null && ! pgrep -af "firefox.*--marionette" >/dev/null; then
    notify-send -a TARS "Firefox (TARS)" "Firefox is already open normally. Close it, then start it from this launcher." 2>/dev/null
    echo "Firefox is already running without remote control; close it first." >&2
    exit 1
fi
# Remote control would otherwise switch on Firefox's test settings (password saving and
# popup blocker off...), which stay in your profile if Firefox is ever killed.
if ! pgrep -x firefox >/dev/null; then
    python3 "$(dirname "$(readlink -f "$0")")/firefox_prefs_fix.py" >/dev/null
fi
exec firefox --marionette --remote-debugging-port 9222 "$@"
