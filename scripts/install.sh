#!/usr/bin/env bash
# =============================================================================
# Flash Copilot - Full Installation Script
# Ubuntu 22.04+ | NVIDIA GTX 1650/1660 | Low VRAM Optimized
# Run as your normal user (NOT root). Will sudo only when needed.
# =============================================================================

set -e  # Exit on any error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VOICES_DIR="$PROJECT_DIR/voices"
CONFIG_DIR="$PROJECT_DIR/config"

log_step()  { echo -e "\n${CYAN}${BOLD}[ STEP ]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[  OK  ]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[ WARN ]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR ]${NC} $1"; }
log_info()  { echo -e "${BLUE}[ INFO ]${NC} $1"; }

echo -e "\n${BOLD}${CYAN}"
echo "  ███████╗██╗      █████╗ ███████╗██╗  ██╗"
echo "  ██╔════╝██║     ██╔══██╗██╔════╝██║  ██║"
echo "  █████╗  ██║     ███████║███████╗███████║"
echo "  ██╔══╝  ██║     ██╔══██║╚════██║██╔══██║"
echo "  ██║     ███████╗██║  ██║███████║██║  ██║"
echo "  ╚═╝     ╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝"
echo -e "${NC}${BOLD}  COPILOT INSTALLER — Ubuntu + GTX 1650/1660${NC}\n"

# ── Guard: must not be root ──────────────────────────────────────────────────
if [ "$EUID" -eq 0 ]; then
    log_error "Do NOT run this script as root. Run as your normal user."
    exit 1
fi

# ── Check Ubuntu version ─────────────────────────────────────────────────────
log_step "Checking system requirements"
UBUNTU_VERSION=$(lsb_release -rs 2>/dev/null || echo "unknown")
if [[ "$UBUNTU_VERSION" < "22.04" ]]; then
    log_warn "Ubuntu $UBUNTU_VERSION detected. Recommended: 22.04+. Proceeding anyway."
else
    log_ok "Ubuntu $UBUNTU_VERSION — good"
fi

# ── Check GPU ─────────────────────────────────────────────────────────────────
if command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    log_ok "GPU: $GPU_NAME — ${VRAM_MB}MB VRAM"
    if [ "$VRAM_MB" -lt 4000 ]; then
        log_error "Less than 4GB VRAM detected. This stack requires at least 4GB."
        exit 1
    fi
else
    log_warn "nvidia-smi not found. NVIDIA drivers may not be installed."
    log_warn "Continuing — some features will run on CPU only."
fi

# ── STEP 1: System dependencies ───────────────────────────────────────────────
log_step "Installing system dependencies"
sudo apt-get update -qq

sudo apt-get install -y \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    portaudio19-dev ffmpeg git curl wget \
    espeak-ng libespeak-ng1 \
    libsndfile1 libsndfile1-dev \
    build-essential cmake pkg-config \
    libxcb-xinerama0 libxcb-cursor0 \
    libxkbcommon-x11-0 libgl1 \
    xdotool wmctrl \
    libnotify-bin notify-osd \
    alsa-utils pulseaudio-utils \
    jq \
    2>/dev/null

log_ok "System packages installed"

# ── STEP 2: Install Ollama ────────────────────────────────────────────────────
log_step "Installing Ollama"
if command -v ollama &>/dev/null; then
    log_ok "Ollama already installed: $(ollama --version 2>/dev/null | head -1)"
else
    curl -fsSL https://ollama.com/install.sh | sh
    log_ok "Ollama installed"
fi

# Enable and start Ollama service
sudo systemctl enable ollama 2>/dev/null || true
sudo systemctl start ollama 2>/dev/null || true
sleep 2

# Verify Ollama is running
if curl -s http://localhost:11434 &>/dev/null; then
    log_ok "Ollama service running on port 11434"
else
    log_warn "Ollama service not responding. Trying to start manually..."
    ollama serve &>/dev/null &
    sleep 3
fi

# ── STEP 3: Pull LLM model ────────────────────────────────────────────────────
log_step "Pulling AI model (Qwen2.5-Coder 3B — optimized for your VRAM)"
log_info "This downloads ~2GB. Please wait..."

VRAM_MB_VAL=${VRAM_MB:-4000}
if [ "$VRAM_MB_VAL" -ge 6000 ]; then
    MODEL="qwen2.5-coder:7b"
    log_info "6GB+ VRAM detected — using 7B model for better quality"
else
    MODEL="qwen2.5-coder:3b"
    log_info "4-6GB VRAM — using 3B model (fast, fits perfectly)"
fi

ollama pull "$MODEL"
log_ok "Model $MODEL ready"

# Pull embedding model for memory
log_info "Pulling embedding model for memory system..."
ollama pull nomic-embed-text
log_ok "Embedding model ready"

# Save model choice to config
echo "$MODEL" > "$CONFIG_DIR/model.txt"

# ── STEP 4: Python virtual environment ───────────────────────────────────────
log_step "Setting up Python virtual environment"
cd "$PROJECT_DIR"

if [ -d "venv" ]; then
    log_warn "venv exists — removing and recreating for clean state"
    rm -rf venv
fi

python3.11 -m venv venv
source venv/bin/activate
log_ok "Python venv created and activated"

# Upgrade pip
pip install --quiet --upgrade pip setuptools wheel

# ── STEP 5: Install PyTorch with CUDA ────────────────────────────────────────
log_step "Installing PyTorch with CUDA support"
log_info "Detecting CUDA version..."

CUDA_VER=$(nvidia-smi 2>/dev/null | grep "CUDA Version" | awk '{print $9}' | cut -d. -f1,2 || echo "none")
log_info "CUDA version: $CUDA_VER"

if [[ "$CUDA_VER" == "12"* ]]; then
    pip install --quiet torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
elif [[ "$CUDA_VER" == "11"* ]]; then
    pip install --quiet torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
else
    log_warn "CUDA not found — installing CPU-only PyTorch"
    pip install --quiet torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
fi

# Verify CUDA
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"None\"}')"
log_ok "PyTorch installed"

# ── STEP 6: Install Python packages ──────────────────────────────────────────
log_step "Installing Python dependencies"

pip install --quiet \
    faster-whisper \
    piper-tts \
    sounddevice soundfile \
    numpy scipy \
    requests \
    duckduckgo-search \
    pynput \
    pyperclip \
    psutil \
    Pillow \
    rich \
    PyQt6 \
    pygpt-net \
    openai \
    chromadb \
    sentence-transformers \
    2>/dev/null

log_ok "Python packages installed"

# ── STEP 7: Download Piper voice models ──────────────────────────────────────
log_step "Downloading Piper TTS voice models"

mkdir -p "$VOICES_DIR"

VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

download_voice() {
    local lang="$1"
    local speaker="$2"
    local quality="$3"

    local family="${lang%%_*}"               # en
    local base_name="${lang}-${speaker}-${quality}"

    local onnx_url="${VOICE_BASE}/${family}/${lang}/${speaker}/${quality}/${base_name}.onnx"
    local json_url="${VOICE_BASE}/${family}/${lang}/${speaker}/${quality}/${base_name}.onnx.json"

    if [[ -f "$VOICES_DIR/${base_name}.onnx" && \
          -f "$VOICES_DIR/${base_name}.onnx.json" ]]; then
        log_ok "Voice '$base_name' already exists"
        return 0
    fi

    log_info "Downloading '$base_name'..."

    if ! wget --show-progress \
        -O "$VOICES_DIR/${base_name}.onnx" \
        "$onnx_url"; then
        log_error "Failed to download ${base_name}.onnx"
        rm -f "$VOICES_DIR/${base_name}.onnx"
        return 1
    fi

    if ! wget \
        -O "$VOICES_DIR/${base_name}.onnx.json" \
        "$json_url"; then
        log_error "Failed to download ${base_name}.onnx.json"
        rm -f "$VOICES_DIR/${base_name}.onnx" \
              "$VOICES_DIR/${base_name}.onnx.json"
        return 1
    fi

    log_ok "Downloaded '$base_name'"
}

# Primary voice
download_voice "en_US" "ryan" "high"

# Backup voice
download_voice "en_US" "lessac" "medium"

# Save default voice
echo "en_US-ryan-high" > "$CONFIG_DIR/voice.txt"
log_ok "Default voice set to en_US-ryan-high"

# ── STEP 8: Install faster-whisper model ─────────────────────────────────────
log_step "Pre-downloading Whisper Tiny model"
python3 -c "
from faster_whisper import WhisperModel
print('Downloading Whisper Tiny model...')
model = WhisperModel('tiny', device='cpu', compute_type='int8')
print('Whisper Tiny ready.')
"
log_ok "Whisper model cached"

# ── STEP 9: Install PyGPT ─────────────────────────────────────────────────────
log_step "Installing and configuring PyGPT"
pip install --quiet pygpt-net
log_ok "PyGPT installed"

# ── STEP 10: Create plugin directory in PyGPT user data ───────────────────────
log_step "Setting up PyGPT plugin directory"
PYGPT_PLUGIN_DIR="$HOME/.config/pygpt-net/plugins"
mkdir -p "$PYGPT_PLUGIN_DIR"
log_ok "Plugin directory: $PYGPT_PLUGIN_DIR"

# ── STEP 11: Create desktop entry ────────────────────────────────────────────
log_step "Creating desktop launcher"
cat > "$HOME/.local/share/applications/flash-copilot.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Flash Copilot
Comment=Your local AI desktop companion
Exec=$PROJECT_DIR/scripts/launch.sh
Icon=$PROJECT_DIR/assets/icon.png
Terminal=false
Categories=Utility;AI;
StartupNotify=true
EOF

chmod +x "$HOME/.local/share/applications/flash-copilot.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
log_ok "Desktop entry created"

# ── STEP 12: Create autostart entry ──────────────────────────────────────────
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/flash-copilot.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Flash Copilot
Exec=$PROJECT_DIR/scripts/launch.sh --tray
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Flash Copilot AI starts minimized to tray
EOF
log_ok "Autostart entry created"

# ── STEP 13: Set up keyboard shortcut instructions ───────────────────────────
log_step "Keyboard shortcut setup"
log_info "After installation, set your push-to-talk key in:"
log_info "  Settings → Keyboard → Custom Shortcuts"
log_info "  Name: Flash Copilot PTT"
log_info "  Command: $PROJECT_DIR/scripts/ptt.sh"
log_info "  Key: Choose any key (e.g. Right Ctrl, ScrollLock, etc.)"

# ── DONE ──────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║   INSTALLATION COMPLETE!                 ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}\n"

log_ok "Model: $(cat $CONFIG_DIR/model.txt)"
log_ok "Voice: $(cat $CONFIG_DIR/voice.txt)"
log_ok "Voices: $VOICES_DIR"

echo -e "\n${BOLD}Next steps:${NC}"
echo "  1. Run:  cd $PROJECT_DIR && source venv/bin/activate"
echo "  2. Test: python3 flash_copilot.py --test"
echo "  3. Run:  python3 flash_copilot.py"
echo "  4. Or launch PyGPT with plugins: python3 launch_pygpt.py"
echo ""
echo -e "${CYAN}Hold your configured hotkey → speak → release = Flash responds${NC}\n"
