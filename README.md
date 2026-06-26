# Vox

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/platform-Ubuntu%2022.04%2B-orange.svg)](#hardware-requirements)
[![Ollama](https://img.shields.io/badge/LLM-Ollama%20%2F%20Qwen2.5-informational.svg)](https://ollama.com)
[![CI](https://github.com/Ekansh0301/Voxd/actions/workflows/ci.yml/badge.svg)](https://github.com/Ekansh0301/Voxd/actions/workflows/ci.yml)
[![Status: Active Development](https://img.shields.io/badge/status-active%20development-brightgreen.svg)](#roadmap)

A fully local, hands-free voice assistant for Ubuntu. Speech recognition, language reasoning, and voice synthesis all run on-device, on a 4 GB consumer GPU. No cloud calls, no API keys, no subscriptions.

```bash
ollama pull qwen2.5:3b
git clone https://github.com/Ekansh0301/Voxd.git && cd Voxd
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 flash_copilot.py
```

Hold Right Ctrl, speak, release. See [Installation](#installation) for the full setup, including system dependencies and CUDA-specific PyTorch.

---

## Contents

- [Why local-first](#why-local-first)
- [Features](#features)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Hardware requirements](#hardware-requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Available tools](#available-tools)
- [PyGPT plugin convention](#pygpt-plugin-convention)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)
- [License](#license)

---

## Why local-first

Most assistant projects are thin wrappers around a cloud API. Every utterance leaves the machine, latency depends on a network round trip, and the assistant stops working the moment a subscription lapses.

Vox takes the opposite constraint as the starting point: how far can a fully local pipeline be pushed on hardware a developer is likely to already own? It was built and tuned against a single GTX 1650 with 4 GB of VRAM, not a workstation GPU. That budget shaped real design decisions throughout the project, model size, request routing, and where computation happens, documented in [Architecture](#architecture) and [Hardware requirements](#hardware-requirements).

---

## Features

- **Push-to-talk control.** Hold a hotkey, speak, release. No always-listening microphone and no wake-word false positives.
- **Local reasoning.** Ollama running Qwen2.5, with separate model routing for conversational queries and code-related ones.
- **Natural local speech.** Piper neural TTS, interruptible mid-sentence.
- **Real desktop actions.** Opens URLs, runs shell commands, launches applications, creates files, and sends keyboard shortcuts, not just chat replies.
- **Screen awareness.** Captures a screenshot and reads on-screen text with OCR when asked what is currently displayed.
- **Live context.** Real-time weather (Open-Meteo, no key required) and local time, answered in a single turn rather than a multi-step exchange.
- **Typed interaction.** A floating chat window with full history, for sessions where typing is preferable to speaking.
- **Extensible.** Drop a Python file into `plugins/custom/` and it is discovered and hot-reloadable from the tray menu without restarting.
- **Proactive monitoring.** A background thread watches CPU, RAM, and disk, and raises an alert unprompted when something needs attention.

---

## Architecture

Vox resolves every request through three layers, in order, rather than sending everything to the LLM. This followed directly from an earlier version that tried to handle all requests through hand-written regex patterns and ran into the obvious ceiling: natural language has effectively unbounded phrasing, and a pattern list can never be complete.

```
input --> Quick Router --> Atomic Execution --> LLM + Tool Calling --> Tool Execution --> Speech
        (deterministic)   (inline data calls)   (Ollama, structured    (desktop_control)  (formatted,
                                                   tool_calls, not                          then Piper)
                                                   parsed free text)
```

**Quick Router.** A small set of high-confidence, zero-ambiguity patterns, explicit site names, weather, time, are matched and resolved instantly with no model call involved. This layer exists deliberately for the highest-frequency commands, not as a general-purpose parser.

**Atomic execution.** Weather, time, and system specs are fetched and answered in one turn. An earlier version split this into a "checking..." acknowledgment followed by a separate "done?" exchange; the data is now fetched inline so the answer arrives complete the first time.

**LLM with tool calling.** Everything the router does not confidently resolve goes to Ollama through its native `tools` parameter on `/api/chat`, which returns a structured `tool_calls` array in the response rather than text the application has to parse. An earlier iteration asked the model to emit `TOOL_CALL: {json}` inside a free-text reply and parsed that manually; general-purpose and code-tuned models frequently ignored the instruction and answered conversationally instead ("Sure, I'll open that for you") rather than emitting a structured call. Native tool calling removed that failure mode by construction rather than by prompt tuning.

Tool results are also written back into conversation history, so a follow-up such as "did it work?" resolves against what actually happened rather than producing a non-sequitur, which was a separate failure mode in the free-text version.

A process-wide GPU mutex (`core/gpu_lock.py`) serializes Whisper transcription and Ollama inference against the background monitoring thread, which is the one place in the system with genuine concurrency. The main voice loop itself is already sequential by construction.

---

## Tech stack

| Layer | Technology | Rationale |
|---|---|---|
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper), Small model, CUDA fp16 | Roughly four times more accurate than the Tiny model on accented or non-native English, while remaining well within the VRAM budget |
| Language model | [Ollama](https://ollama.com) with Qwen2.5 3B and Qwen2.5-Coder 3B | Native structured tool calling, with separate models for conversational and code-related queries |
| Text-to-speech | [Piper](https://github.com/rhasspy/piper), CPU | Natural offline synthesis with no GPU cost and interruptible playback |
| Desktop control | `xdotool`, `scrot`, `tesseract-ocr` | Keyboard and window control, screen capture, and OCR for screen-reading |
| Interface | PyQt6 | Avatar widget, floating chat window, system tray |
| Memory | ChromaDB with sentence-transformers (MiniLM) | Local vector store for conversational recall |
| Weather | [Open-Meteo](https://open-meteo.com) | No key, no rate limit |

---

## Hardware requirements

| | Minimum | Recommended |
|---|---|---|
| GPU | 4 GB VRAM (GTX 1650 / 1660 class) | 6 GB or more, for headroom toward larger models |
| CPU | 4-core, x86_64 | 6-core or better; Piper and OCR both run on CPU |
| RAM | 8 GB | 16 GB |
| Disk | About 6 GB free | 10 GB or more, SSD preferred |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 or 24.04 LTS |
| GPU driver | NVIDIA driver with CUDA 12.1 | Same, kept current |

The minimum row above is the configuration Vox was developed and tuned against, not a lower bound that happens to work. Measured VRAM at runtime, with Whisper Small and Qwen2.5 3B both loaded:

| Component | VRAM |
|---|---|
| Qwen2.5 3B (Q4) | ~2.1 GB |
| Whisper Small (fp16) | ~0.5 GB |
| System and interface overhead | ~0.2 GB |
| **Total** | **~2.8 GB** |
| **Free on a 4 GB card** | **~1.2 GB** |

---

## Installation

Setup takes roughly 10 to 20 minutes, most of it spent downloading the Ollama models (about 2 GB each) and the Piper voice (about 115 MB), not the Python environment itself.

```bash
# System dependencies
sudo apt update
sudo apt install -y xdotool scrot tesseract-ocr python3-venv python3-pip

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b
ollama pull qwen2.5-coder:3b

# Clone and set up the environment
git clone https://github.com/Ekansh0301/Voxd.git
cd voxd
python3 -m venv venv
source venv/bin/activate

# PyTorch first, matched to your installed CUDA version (check with nvidia-smi)
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121

# Remaining dependencies
pip install -r requirements.txt

# Piper TTS binary and default voice (~115 MB)
bash scripts/install.sh

# Optional: start automatically on login
bash scripts/setup_autostart.sh
```

PyTorch is intentionally absent from `requirements.txt`. CUDA-enabled wheels are distributed from PyTorch's own index rather than PyPI, and the correct build depends on the installed driver version; a plain `pip install -r requirements.txt` risks silently resolving a CPU-only or mismatched build.

```bash
source venv/bin/activate
python3 flash_copilot.py
```

An avatar widget appears in the corner of the screen and an icon appears in the system tray.

---

## Configuration

All settings live in `config/config.json`.

```json
{
  "assistant_name": "Vox",
  "user_name": "Your Name",
  "user_city": "Your City",
  "user_timezone": "America/New_York",
  "user_lat": 40.7128,
  "user_lon": -74.006,
  "hotkey": "ctrl_r",
  "model": "qwen2.5:3b",
  "model_code": "qwen2.5-coder:3b",
  "voice": "en_US-ryan-high",
  "type_responses": false
}
```

| Key | Description |
|---|---|
| `assistant_name`, `user_name` | How Vox refers to itself and to you |
| `user_city`, `user_lat`, `user_lon` | Used for weather and time-of-day reasoning |
| `hotkey` | Push-to-talk key; see below |
| `model`, `model_code` | Ollama models for conversational versus code-related queries |
| `voice` | Piper voice filename without extension; see below |
| `type_responses` | When `true`, also types replies into the currently focused window |

**Voices.** Any Piper-compatible ONNX model works. Three ship by default: `en_US-ryan-high` (male, high quality, default), `en_US-lessac-high` (female, high quality), `en_US-lessac-medium` (female, smaller and faster). Additional voices can be downloaded from the [Piper voice samples page](https://rhasspy.github.io/piper-samples/) into `voices/` and referenced by filename.

**Hotkey.** Accepts any key supported by the listener: `ctrl_r` (default), `ctrl_l`, `alt_r`, or a function key such as `f9`. Avoid keys already bound to window-manager shortcuts.

**VRAM tuning.** On a card tighter than 4 GB, set `"model": "qwen2.5:1.5b"` (~1.1 GB instead of ~2.1 GB) and `"whisper_model_size": "base"` (~150 MB instead of ~500 MB). Tool-calling reliability and conversational quality both degrade below the 3B class, this is a genuine accuracy trade, not a free reduction. With 6 GB or more available, `"model": "qwen2.5:7b"` (~4.7 GB) gives noticeably stronger reasoning instead.

---

## Usage

| Said aloud | Result |
|---|---|
| "What's the weather like?" | Live weather for the configured location, answered in one turn |
| "Is it good weather for a walk?" | Weather and time of day combined into a direct recommendation |
| "Open YouTube and search for X" | Browser opens, navigates, and types the query |
| "What are my system specs?" | CPU, RAM, disk, and GPU stats, spoken as sentences rather than read out as raw numbers |
| "What's on my screen right now?" | Screenshot, OCR, and a summary of the content |
| "Open a terminal and run git status" | Command executes, result is reported |
| "Create a file called notes.txt" | File created in the home directory |
| "Close this tab" | Corresponding keyboard shortcut sent |
| "What time is it?" | Current local time, no model call required |
| "Search cons of X on ChatGPT" | chatgpt.com opens and the query is typed directly into the page |

Ctrl+Space toggles the floating chat window. The tray icon's context menu exposes plugin reload, conversation clearing, and settings.

---

## Available tools

Exposed to the LLM through Ollama's `tools` schema:

| Tool | Purpose |
|---|---|
| `open_url` | Open a website or search query in the default browser |
| `run_command` | Execute a shell command and return its output |
| `get_system_info` | CPU, RAM, disk, and GPU usage, converted to natural language |
| `open_app` | Launch a desktop application |
| `create_file` | Create a file with specified content |
| `read_screen` | Screenshot plus OCR for screen-reading queries |
| `keyboard_shortcut` | Send shortcuts such as closing a tab or opening a new window |
| `type_text` | Type into the currently focused window |
| `get_active_window` | Identify which application currently has focus |

---

## PyGPT plugin convention

Two bundled plugins, `plugins/plugin_piper_tts/` and `plugins/plugin_flash_avatar/`, follow the file layout used by [PyGPT](https://github.com/szczyglis-dev/py-gpt) (`__init__.py` plus `plugin.py`, with a `Plugin` class exposing handler methods). Vox does not depend on or run inside PyGPT; only the file convention is shared, so that custom plugins placed in `plugins/custom/` have a consistent, documented shape to follow.

These two bundled plugins are experimental and outside the actively maintained core path. Neither is required to run Vox.

---

## Project structure

```
Voxd/
├── flash_copilot.py              Entry point: UI, tray, worker thread
├── core/
│   ├── brain.py                  LLM reasoning, intent routing, tool calling
│   ├── voice_engine.py           Whisper STT and Piper TTS
│   ├── desktop_control.py        Desktop actions, weather, OCR, system info
│   ├── memory_engine.py          ChromaDB conversational memory
│   ├── hotkey_listener.py        Push-to-talk listener
│   ├── safety.py                 Command risk classification
│   ├── monitor.py                Background system monitoring
│   ├── gpu_lock.py               Process-wide GPU mutex
│   └── plugin_loader.py          Plugin discovery
├── plugins/
│   ├── custom/                   Drop-in plugins, auto-discovered
│   ├── plugin_piper_tts/         Bundled, experimental
│   └── plugin_flash_avatar/      Bundled, experimental
├── voices/                       Piper voice models
├── config/config.json            User configuration
└── scripts/                      Install, launch, and autostart helpers
```

---

## Known limitations

- **Tool-call reliability tracks model size.** 3B-class models occasionally answer conversationally instead of emitting a structured call. The Quick Router exists specifically to route the highest-frequency commands around this, not to eliminate it for arbitrary phrasing.
- **No wake word.** Push-to-talk only, by design, for privacy and to avoid false triggers.
- **Screen-reading is OCR only.** Text is read; images, diagrams, and layout are not interpreted.
- **Editor integration is shallow.** The open file in VS Code is inferred from the window title, not from an extension or language server.
- **Single user, single machine.** No profiles, no remote access.
- **English only**, including non-native accents, but not other languages.

---

## Roadmap

- [ ] Lightweight on-device vision model for screen understanding beyond OCR
- [ ] Optional wake-word activation
- [ ] Proper editor integration in place of window-title heuristics
- [ ] Conversation export and session summaries

---

## License

MIT. See [LICENSE](LICENSE).