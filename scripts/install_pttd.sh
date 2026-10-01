#!/usr/bin/env bash
# Install (or remove) tars-pttd, the push-to-talk key watcher. Run it yourself:
#
#   sudo bash scripts/install_pttd.sh                    # Right Ctrl
#   sudo bash scripts/install_pttd.sh KEY_RIGHTCTRL,BTN_SIDE   # + mouse side button
#   sudo bash scripts/install_pttd.sh --uninstall
#
# What it does: copies tars/voice/pttd.py to a root-owned path (so nothing in
# your home folder can swap the code that sees keyboard input), installs a
# hardened systemd service + socket, and starts it. It does NOT add you to the
# `input` group. Read tars/voice/pttd.py and deploy/tars-pttd.* first.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "run with sudo"; exit 1; fi
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:?run via sudo from your own account}"
UNITS=/etc/systemd/system

if [[ "${1:-}" == "--uninstall" ]]; then
    systemctl disable --now tars-pttd.socket tars-pttd.service 2>/dev/null || true
    rm -f "$UNITS/tars-pttd.socket" "$UNITS/tars-pttd.service" /usr/local/lib/tars/tars-pttd.py
    rmdir /usr/local/lib/tars 2>/dev/null || true
    systemctl daemon-reload
    echo "tars-pttd removed"
    exit 0
fi

TRIGGER="${1:-KEY_RIGHTCTRL}"
[[ "$TRIGGER" =~ ^[A-Z_,]+$ ]] || { echo "bad trigger: $TRIGGER"; exit 1; }

install -D -o root -g root -m 0755 "$REPO/tars/voice/pttd.py" /usr/local/lib/tars/tars-pttd.py
sed "s|@USER@|$USER_NAME|g" "$REPO/deploy/tars-pttd.socket.in" > "$UNITS/tars-pttd.socket"
sed "s|@TRIGGER@|$TRIGGER|g" "$REPO/deploy/tars-pttd.service.in" > "$UNITS/tars-pttd.service"
systemctl daemon-reload
systemctl enable --now tars-pttd.socket
systemctl restart tars-pttd.service 2>/dev/null || true
echo "tars-pttd installed (trigger: $TRIGGER). Socket: /run/tars-pttd.sock (owner $USER_NAME)."
echo "Test:  python3 -c \"import socket; s=socket.socket(socket.AF_UNIX); s.connect('/run/tars-pttd.sock'); [print(l) for l in s.makefile()]\""
