#!/usr/bin/env bash
# TARS setup: llama.cpp (CUDA, GTX 16xx code path), llama-swap, GGUF models,
# faster-whisper models, Piper voices, Kokoro TTS, and the TARS Python env (.venv).
#
# Idempotent and resumable: re-run it after an interruption and it skips
# what is done and resumes partial downloads.
#
# Everything lives outside the repo under $TARS_HOME (default ~/.local/share/tars).
# Downloads are forced over IPv4 because IPv6 is broken on this network
# (connections over v6 time out instead of failing fast).
set -euo pipefail

TARS_HOME="${TARS_HOME:-$HOME/.local/share/tars}"
OPT="$TARS_HOME/opt"
BIN="$OPT/bin"
MODELS="$TARS_HOME/models"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LLAMA_SWAP_VERSION="260"
KOKORO_TAG="model-files-v1.0"

mkdir -p "$BIN" "$MODELS/llm" "$MODELS/stt" "$MODELS/tts/piper"

step() { echo -e "\n=== $* ==="; }

fetch() { # url dest
    local url="$1" dest="$2"
    if [[ -f "$dest" && ! -f "$dest.part" ]]; then
        echo "have  $(basename "$dest")"
        return
    fi
    echo "get   $(basename "$dest")"
    touch "$dest.part"
    curl -4 -fL --retry 5 --retry-delay 3 -C - -o "$dest" "$url"
    rm -f "$dest.part"
}

hf_file() { # repo file dest_dir
    fetch "https://huggingface.co/$1/resolve/main/$2" "$3/$(basename "$2")"
}

hf_repo() { # repo dest_dir  — every file in the repo root (small repos only)
    local repo="$1" dest="$2"
    mkdir -p "$dest"
    local files
    files=$(curl -4 -fsS --retry 3 "https://huggingface.co/api/models/$repo/tree/main" |
        python3 -c 'import json,sys; [print(f["path"]) for f in json.load(sys.stdin) if f["type"]=="file" and not f["path"].startswith(".") and not f["path"].endswith(".md")]')
    for f in $files; do hf_file "$repo" "$f" "$dest"; done
}

# ── llama.cpp ────────────────────────────────────────────────────────────────
step "llama.cpp (CUDA build for GTX 1650: Pascal/MMQ code path)"
if [[ ! -d "$OPT/llama.cpp/.git" ]]; then
    git clone --depth 1 https://github.com/ggml-org/llama.cpp "$OPT/llama.cpp"
fi
# GTX 16xx is Turing *without* tensor cores. The default sm_75 build takes the
# tensor-core path and prefills ~3x slower (152 vs 483 tok/s on Qwen3.5-4B).
# llama.cpp recommends forcing the Pascal/MMQ kernels for these cards.
BUILD="$OPT/llama.cpp/build-mmq"
if [[ ! -x "$BUILD/bin/llama-server" ]]; then
    export CUDACXX=/usr/local/cuda/bin/nvcc
    cmake -S "$OPT/llama.cpp" -B "$BUILD" \
        -DGGML_CUDA=ON "-DCMAKE_CUDA_ARCHITECTURES=61-virtual;80-virtual" -DGGML_CUDA_FORCE_MMQ=ON \
        -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF
    cmake --build "$BUILD" --config Release -j "$(nproc)" \
        --target llama-server llama-bench llama-cli
fi
for b in llama-server llama-bench llama-cli; do
    ln -sf "$BUILD/bin/$b" "$BIN/$b"
done
"$BIN/llama-server" --version 2>&1 | head -2 || true

# ── llama-swap ───────────────────────────────────────────────────────────────
step "llama-swap v$LLAMA_SWAP_VERSION"
if [[ ! -x "$BIN/llama-swap" ]]; then
    tgz="$OPT/llama-swap_${LLAMA_SWAP_VERSION}.tar.gz"
    fetch "https://github.com/mostlygeek/llama-swap/releases/download/v${LLAMA_SWAP_VERSION}/llama-swap_${LLAMA_SWAP_VERSION}_linux_amd64.tar.gz" "$tgz"
    tar -xzf "$tgz" -C "$BIN" llama-swap
fi
"$BIN/llama-swap" --version 2>&1 | head -1 || true

# ── LLM candidates ───────────────────────────────────────────────────────────
step "GGUF models"
hf_file unsloth/Qwen3.5-0.8B-GGUF Qwen3.5-0.8B-Q4_K_M.gguf "$MODELS/llm"
hf_file unsloth/Qwen3.5-4B-GGUF Qwen3.5-4B-Q4_K_M.gguf "$MODELS/llm"
mkdir -p "$MODELS/llm/qwen3.5-4b-mmproj"
hf_file unsloth/Qwen3.5-4B-GGUF mmproj-F16.gguf "$MODELS/llm/qwen3.5-4b-mmproj"
hf_file unsloth/Qwen3-4B-Instruct-2507-GGUF Qwen3-4B-Instruct-2507-Q4_K_M.gguf "$MODELS/llm"
hf_file unsloth/Qwen3.5-2B-GGUF Qwen3.5-2B-Q4_K_M.gguf "$MODELS/llm"
hf_file unsloth/Qwen3.5-4B-GGUF Qwen3.5-4B-IQ4_XS.gguf "$MODELS/llm"

# ── STT candidates (CTranslate2 format for faster-whisper) ──────────────────
step "faster-whisper models"
hf_repo Systran/faster-whisper-small.en "$MODELS/stt/small.en"
hf_repo Systran/faster-distil-whisper-small.en "$MODELS/stt/distil-small.en"
hf_repo Systran/faster-whisper-medium.en "$MODELS/stt/medium.en"

# ── Piper voices ─────────────────────────────────────────────────────────────
step "Piper voices"
for v in en_US/ryan/high en_US/lessac/high en_US/lessac/medium; do
    name="${v%%/*}-$(echo "$v" | cut -d/ -f2)-${v##*/}"
    for ext in onnx onnx.json; do
        hf_file rhasspy/piper-voices "en/$v/$name.$ext" "$MODELS/tts/piper"
    done
done

# ── Kokoro TTS ───────────────────────────────────────────────────────────────
step "Kokoro TTS"
fetch "https://github.com/thewh1teagle/kokoro-onnx/releases/download/$KOKORO_TAG/kokoro-v1.0.int8.onnx" "$MODELS/tts/kokoro-v1.0.int8.onnx"
fetch "https://github.com/thewh1teagle/kokoro-onnx/releases/download/$KOKORO_TAG/kokoro-v1.0.onnx" "$MODELS/tts/kokoro-v1.0.onnx"
fetch "https://github.com/thewh1teagle/kokoro-onnx/releases/download/$KOKORO_TAG/voices-v1.0.bin" "$MODELS/tts/voices-v1.0.bin"

# ── TARS v2 Python env (.venv) ──────────────────────────────────────────────
# Separate from v1's venv/: v2 needs numpy 2 (kokoro-onnx), v1's chromadb pins 1.x.
step "TARS v2 Python environment (.venv)"
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    python3.11 -m venv "$PROJECT_DIR/.venv"
fi
"$PROJECT_DIR/.venv/bin/pip" install --quiet --timeout 30 -e "$PROJECT_DIR[bench,dev]"

step "Done"
du -sh "$MODELS"/* 2>/dev/null
