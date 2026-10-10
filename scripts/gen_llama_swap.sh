#!/usr/bin/env bash
# Write ~/.config/tars/llama-swap.yaml from deploy/llama-swap.yaml.in.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARS_HOME="${TARS_HOME:-$HOME/.local/share/tars}"
OUT="${XDG_CONFIG_HOME:-$HOME/.config}/tars/llama-swap.yaml"
mkdir -p "$(dirname "$OUT")"
# llama-server was built against CUDA 12; its runtime and cuBLAS come from NVIDIA's wheels
# in .venv, whatever CUDA the system has.
NV="$PROJECT_DIR/.venv/lib/python3.11/site-packages/nvidia"
CUDA_LIBS="$NV/cuda_runtime/lib:$NV/cublas/lib"
sed -e "s|@TARS_HOME@|$TARS_HOME|g" -e "s|@CUDA_LIBS@|$CUDA_LIBS|g" "$PROJECT_DIR/deploy/llama-swap.yaml.in" > "$OUT"
echo "wrote $OUT"
echo "run:  $TARS_HOME/opt/bin/llama-swap --config $OUT --listen 127.0.0.1:8090"
