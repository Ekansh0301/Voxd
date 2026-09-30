#!/usr/bin/env bash
# Write ~/.config/tars/llama-swap.yaml from deploy/llama-swap.yaml.in.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARS_HOME="${TARS_HOME:-$HOME/.local/share/tars}"
OUT="${XDG_CONFIG_HOME:-$HOME/.config}/tars/llama-swap.yaml"
mkdir -p "$(dirname "$OUT")"
sed "s|@TARS_HOME@|$TARS_HOME|g" "$PROJECT_DIR/deploy/llama-swap.yaml.in" > "$OUT"
echo "wrote $OUT"
echo "run:  $TARS_HOME/opt/bin/llama-swap --config $OUT --listen 127.0.0.1:8090"
