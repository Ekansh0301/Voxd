#!/usr/bin/env bash
# The `tars` command (~/.local/bin/tars) and the TARS app entry with its icon.
# The entry's id, org.tars.TARS, is also the app id TARS's screenshot and
# keyboard permissions are stored under, so keep it.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
mkdir -p "$BIN" "$APPS"
ln -sf "$REPO/scripts/tars" "$BIN/tars"
sed -e "s|@BIN@|$BIN|" -e "s|@REPO@|$REPO|" "$REPO/deploy/org.tars.TARS.desktop.in" > "$APPS/org.tars.TARS.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
echo "installed: $BIN/tars and the TARS app entry"
