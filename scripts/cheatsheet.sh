#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  FLASH COPILOT — QUICK REFERENCE
# ═══════════════════════════════════════════════════════════════

cat << 'EOF'

  ███████╗██╗      █████╗ ███████╗██╗  ██╗
  ██╔════╝██║     ██╔══██╗██╔════╝██║  ██║
  █████╗  ██║     ███████║███████╗███████║
  ██╔══╝  ██║     ██╔══██║╚════██║██╔══██║
  ██║     ███████╗██║  ██║███████║██║  ██║
  ╚═╝     ╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
  COPILOT  ─  QUICK REFERENCE

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FIRST TIME SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. bash scripts/install.sh          # Full install (~15 min)
  2. source venv/bin/activate
  3. python3 test_all.py              # Verify everything works
  4. python3 flash_copilot.py         # Launch!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DAILY USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  bash scripts/launch.sh              # Launch (activates venv auto)
  bash scripts/launch.sh --tray      # Start minimized to tray

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PUSH TO TALK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Hold [Right Ctrl]    ← Flash listens (orb turns BLUE)
  Speak naturally      ← Say anything — not commands
  Release [Right Ctrl] ← Flash thinks (orb turns AMBER)
                         then speaks back (orb turns GREEN)

  Change key: edit config/config.json  →  "hotkey": "f12"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WHAT YOU CAN SAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "open chrome"
  "search for rust async programming"
  "what's eating my memory right now"
  "check the nginx logs"
  "read my main.py and check for bugs"
  "how much disk space do I have"
  "draft an email to boss@company.com about the project delay"
  "type hello world in this terminal"
  "take a screenshot"
  "install vim"              ← asks for confirmation first
  "sudo apt update"          ← asks for confirmation first

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  AVATAR ORB STATES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Purple pulse  →  IDLE (ready, waiting for you)
  Blue wave     →  LISTENING (recording your voice)
  Amber spin    →  THINKING (LLM processing)
  Green bounce  →  SPEAKING (Piper TTS playing)
  Red flash     →  ERROR

  Drag orb to move it.  Right-click for menu.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CONFIG  (config/config.json)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  model     qwen2.5-coder:3b   (4GB VRAM)
            qwen2.5-coder:7b   (6GB VRAM)
  voice     en_US-ryan-high    (male, best quality)
            en_US-lessac-medium (female, faster)
  hotkey    ctrl_r / f12 / scroll_lock / pause / insert

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DIAGNOSTICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  python3 test_all.py                   # Test everything
  python3 test_all.py --component tts   # Test only TTS
  python3 test_all.py --component brain # Test only LLM
  python3 flash_copilot.py --test       # Quick smoke test
  watch -n2 nvidia-smi                  # Monitor VRAM live

  Log file: flash_copilot.log

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  COMMON FIXES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Ollama offline      → ollama serve &
  No microphone       → arecord -d 3 test.wav && aplay test.wav
  Piper silent        → python3 -m piper --model voices/en_US-ryan-high.onnx --output_file t.wav <<< "test" && aplay t.wav
  Qt xcb error        → sudo apt install libxcb-xinerama0 libxcb-cursor0
  Hotkey not working  → export DISPLAY=:0 before launching
  Out of VRAM         → use qwen2.5-coder:3b-instruct-q4_0 (~1.8GB)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EOF
