#!/usr/bin/env bash
# Install and enable the "TARS windows" GNOME Shell extension (list/focus windows).
# On Wayland GNOME loads new extensions only at login: log out and back in once.
# Remove: gnome-extensions disable tars-windows@tars.local && rm -r ~/.local/share/gnome-shell/extensions/tars-windows@tars.local
set -euo pipefail
UUID=tars-windows@tars.local
SRC="$(cd "$(dirname "$0")/.." && pwd)/deploy/gnome-extension/$UUID"
DST="$HOME/.local/share/gnome-shell/extensions/$UUID"
mkdir -p "$DST"
cp "$SRC/metadata.json" "$SRC/extension.js" "$DST/"
gnome-extensions enable "$UUID" 2>/dev/null || \
  gsettings set org.gnome.shell enabled-extensions \
    "$(python3 -c "import ast,sys; l=ast.literal_eval(sys.argv[1]); l+=[] if '$UUID' in l else ['$UUID']; print(l)" "$(gsettings get org.gnome.shell enabled-extensions)")"
echo "installed to $DST and enabled; log out and back in once to load it"
