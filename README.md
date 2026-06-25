# Vox

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/platform-Ubuntu%2022.04%2B-orange.svg)](#hardware-requirements)
[![Ollama](https://img.shields.io/badge/LLM-Ollama%20%2F%20Qwen2.5-informational.svg)](https://ollama.com)
[![CI](https://github.com/Ekansh0301/Voxd/actions/workflows/ci.yml/badge.svg)](https://github.com/Ekansh0301/Voxd/actions/workflows/ci.yml)
[![Status: Active Development](https://img.shields.io/badge/status-active%20development-brightgreen.svg)](#roadmap)

**A fully local, hands-free voice assistant for Ubuntu — no cloud, no API keys, no subscriptions.**

Vox listens for a push-to-talk hotkey, transcribes speech with Whisper, reasons with a local LLM via Ollama, executes real actions on your desktop (open apps, browse the web, run commands, check system stats, read your screen), and replies out loud with a natural local TTS voice. Everything — speech recognition, language model, and voice synthesis — runs on-device. No request ever leaves the machine except the page loads it triggers in your browser.

> Built as a personal systems project to explore local-first AI agent design: deterministic routing, LLM tool-calling, and voice I/O under real consumer GPU constraints (4GB VRAM).

---

## Table of Contents

- [Demo](#demo)
- [Why Local-First](#why-local-first)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Hardware Requirements](#hardware-requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Available Tools](#available-tools)
- [PyGPT Plugin Integration](#pygpt-plugin-integration)
- [Project Structure](#project-structure)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [License](#license)

---

## Demo

> 🎥 _Demo video / GIF coming soon._

---

## Why Local-First

Most "AI assistant" projects are thin wrappers around a cloud API — OpenAI, Gemini, or similar — which means every word you say is sent to a third-party server, latency depends on your internet connection, and the assistant stops working entirely without a subscription.

Vox was built to answer a different question: **how far can you push a fully local pipeline on consumer hardware before it becomes genuinely usable day-to-day?** Every component — speech-to-text, the language model, and text-to-speech — runs on a single GTX 1650 (4GB VRAM). The tradeoffs that come with that constraint (model size, VRAM budgeting, latency) are part of what makes this an interesting systems problem, not just a chatbot wrapper.

---

## Features

- 🎙️ **Push-to-talk voice control** — hold a hotkey, speak, release. No always-listening microphone, no wake-word false positives, no privacy concerns from background audio capture.
- 🧠 **Local LLM reasoning** — Ollama running Qwen2.5 (3B for conversation, Coder 3B for code-related queries), fully offline.
- 🗣️ **Natural local TTS** — Piper neural voice synthesis, interruptible mid-sentence.
- 🌐 **Real desktop actions** — opens URLs, runs shell commands, launches apps, creates files, presses keyboard shortcuts — not just chat.
- 🖥️ **Screen awareness** — takes a screenshot and reads on-screen text via OCR (Tesseract) when asked "what's on my screen."
- 🌦️ **Live weather & time** — pulls real-time weather (Open-Meteo, no API key) and local time, answered in a single conversational turn.
- 💬 **Floating chat window** — full conversation history, typed input, draggable, toggled with a hotkey — for when you'd rather type than talk.
- 🧩 **Plugin system** — drop a Python file in `plugins/custom/` and it's auto-discovered and hot-reloadable from the tray menu. Also ships with two starter plugins built on the PyGPT plugin convention (see [PyGPT Plugin Integration](#pygpt-plugin-integration)).
- 📊 **Proactive monitoring** — background thread watches CPU/RAM/disk and speaks up if something needs attention, without being asked.
- 🎯 **Hybrid routing** — a small set of deterministic high-confidence patterns (e.g. "open chatgpt and ask X") bypass the LLM entirely for instant, 100%-reliable execution; everything else goes through proper LLM tool-calling.

---

## Architecture

Vox uses a **three-layer decision pipeline** rather than relying on the LLM for every single request. This was a deliberate design choice after an earlier prototype tried to route 100% of requests through regex pattern-matching and discovered the obvious failure mode: natural language has effectively infinite phrasings, and a hand-written pattern list can never be complete or precise enough on its own.

```
                         ┌─────────────────────┐
   voice / typed input → │   1. Quick Router     │ → high-confidence, zero-ambiguity
                         │   (deterministic)     │   patterns only (explicit site names,
                         └──────────┬───────────┘   weather, time) — instant, no LLM call
                                    │ no match
                                    ▼
                         ┌─────────────────────┐
                         │  2. Atomic Execution  │ → weather / time / specs fetched
                         │   (inline data calls) │   inline, full answer in ONE turn —
                         └──────────┬───────────┘   no "checking... / done?" round trip
                                    │ needs reasoning
                                    ▼
                         ┌─────────────────────┐
                         │ 3. LLM + Tool Calling │ → Ollama native /api/chat with
                         │   (Ollama, qwen2.5)   │   structured tools=[] schema —
                         └──────────┬───────────┘   model returns real tool_calls[],
                                    │                not parsed free-text
                                    ▼
                         ┌─────────────────────┐
                         │   Tool Execution      │ → run_command, open_url, read_screen,
                         │   (desktop_control)    │   create_file, keyboard_shortcut, etc.
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Speech Formatting    │ → raw data converted to natural
                         │   + Piper TTS          │   spoken sentences before synthesis
                         └─────────────────────┘
```

**Why this matters:** an earlier iteration used free-text prompting (asking the LLM to emit `TOOL_CALL: {json}` inside its response) and parsing that out manually. This is unreliable — general-purpose and code-tuned models frequently ignore the instruction and respond conversationally instead ("Sure, I'll open that for you...") rather than emitting a structured call. Switching to Ollama's native `tools=` parameter on `/api/chat` (which returns a proper `tool_calls` array in the response, not embedded text) made execution deterministic rather than best-effort.

A second early failure mode: tool results weren't being fed back into conversation history, so asking "did it work?" immediately after a command produced a non-sequitur. The current pipeline injects every tool result into the rolling conversation context, so follow-up references ("done?", "what did it say?", "play it") resolve correctly.

A `core/gpu_lock.py` process-wide mutex serializes GPU-bound calls (Whisper transcription and Ollama inference) against the background system-monitoring thread, preventing CUDA memory contention on a 4GB card when the proactive monitor fires concurrently with a voice interaction. The main voice loop itself is naturally sequential (record → transcribe → reason → speak), so this primarily protects the one genuine concurrency path in the system.

---

## Tech Stack

| Layer              | Technology                                                                     | Why                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| Speech-to-Text     | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Small, CUDA fp16) | ~4x more accurate than Tiny on accented/non-native English speech, still fits comfortably in VRAM budget |
| Language Model     | [Ollama](https://ollama.com) + Qwen2.5 3B / Qwen2.5-Coder 3B                   | Native structured tool-calling support, dual-model routing (chat vs. code intent)                        |
| Text-to-Speech     | [Piper](https://github.com/rhasspy/piper) (neural TTS, CPU)                    | Natural-sounding offline voice, no GPU cost, interruptible playback                                      |
| Desktop Automation | `xdotool`, `scrot`, `tesseract-ocr`                                            | Keyboard/window control, screenshot capture, OCR for screen-reading                                      |
| UI                 | PyQt6                                                                          | Animated avatar widget, floating chat window, system tray integration                                    |
| Memory             | ChromaDB + sentence-transformers (MiniLM)                                      | Local vector store for long-term conversational recall                                                   |
| Weather            | [Open-Meteo](https://open-meteo.com)                                           | Free, no API key, no rate-limit hassle                                                                   |

---

## Hardware Requirements

|                | Minimum                              | Recommended                                                                            |
| -------------- | ------------------------------------ | -------------------------------------------------------------------------------------- |
| **GPU**        | 4GB VRAM (GTX 1650 / 1660 class)     | 6GB+ VRAM (RTX 3050 or better) — headroom for larger models or future on-device vision |
| **CPU**        | 4-core, x86_64                       | 6-core+ — Piper TTS and OCR both run CPU-side                                          |
| **RAM**        | 8GB system RAM                       | 16GB — leaves comfortable headroom alongside Chrome/VS Code etc.                       |
| **Disk**       | ~6GB free (models + voices + deps)   | 10GB+ free, SSD recommended for model load times                                       |
| **OS**         | Ubuntu 22.04 LTS                     | Ubuntu 22.04 / 24.04 LTS — other GNOME-based distros likely work but are untested      |
| **Microphone** | Any working input device             | Headset mic — reduces echo/feedback during TTS playback                                |
| **GPU driver** | NVIDIA driver with CUDA 12.1 support | Same, kept current                                                                     |

Vox was developed and tuned against the **minimum** spec above — a 4GB card was the design constraint, not an afterthought. See [Architecture](#architecture) and the VRAM budget table below for how that constraint shaped specific decisions (model size, sequential GPU access, CPU-side TTS).

**Approximate VRAM usage at runtime** (Whisper Small + Qwen2.5 3B both loaded):

| Component                    | VRAM        |
| ---------------------------- | ----------- |
| Qwen2.5 3B (Q4)              | ~2.1 GB     |
| Whisper Small (fp16)         | ~0.5 GB     |
| System / PyQt overhead       | ~0.2 GB     |
| **Total used**               | **~2.8 GB** |
| **Free headroom (4GB card)** | **~1.2 GB** |

---

## Installation

**Estimated time: 10–20 minutes**, depending on internet speed — most of that time is the Ollama model pulls (~2GB each) and the Piper voice model download (~115MB), not the Python setup itself.

### Prerequisites

```bash
# System dependencies
sudo apt update
sudo apt install -y xdotool scrot tesseract-ocr python3-venv python3-pip

# Ollama (local LLM runtime)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b          # ~2GB download
ollama pull qwen2.5-coder:3b    # ~2GB download
```

### Setup

```bash
git clone https://github.com/<your-username>/voxd.git
cd voxd

python3 -m venv venv
source venv/bin/activate


# Install it first, matched to your CUDA version:
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121

# Then the rest of the dependencies:
pip install -r requirements.txt

# Download Piper TTS binary + voice model (~115MB)
bash scripts/install_piper.sh

# Optional: install as a background service that starts on login
bash scripts/setup_autostart.sh
```

### Run

```bash
source venv/bin/activate
python3 vox.py
```

A small avatar widget appears in the corner of your screen and an icon appears in the system tray. Hold the configured hotkey (default: **Right Ctrl**) to speak.

---

## Configuration

All settings live in `config/config.json`.

### Base example

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

| Key                                   | Description                                                                                   |
| ------------------------------------- | --------------------------------------------------------------------------------------------- |
| `assistant_name` / `user_name`        | Personalizes how Vox refers to itself and you                                                 |
| `user_city` / `user_lat` / `user_lon` | Used for weather and time-of-day reasoning                                                    |
| `hotkey`                              | Push-to-talk key — see options below                                                          |
| `model` / `model_code`                | Ollama model names for conversational vs. code-related queries                                |
| `voice`                               | Piper voice model filename (without extension) — see options below                            |
| `type_responses`                      | If `true`, types Vox's replies into the currently focused window in addition to speaking them |

### Switching voices

Any Piper-compatible ONNX voice model works. Three are bundled by default:

```json
"voice": "en_US-ryan-high"       // default — male, US English, high quality
"voice": "en_US-lessac-high"     // female, US English, high quality
"voice": "en_US-lessac-medium"   // female, US English, smaller/faster model
```

To add a new voice, download the `.onnx` + `.onnx.json` pair from the [Piper voice samples page](https://rhasspy.github.io/piper-samples/) into `voices/`, then reference the filename (without extension) in `config.json`.

### Hotkey options

`hotkey` accepts any single key supported by the underlying listener:

```json
"hotkey": "ctrl_r"    // default — right Ctrl
"hotkey": "ctrl_l"    // left Ctrl
"hotkey": "alt_r"     // right Alt
"hotkey": "f9"         // any function key, e.g. f9
```

Avoid keys already bound to common OS/window-manager shortcuts to prevent conflicts.

### VRAM tuning

If you're on a card tighter than 4GB, or want more headroom for other GPU work:

```json
{
  "model": "qwen2.5:1.5b", // smaller model, ~1.1GB instead of ~2.1GB
  "whisper_model_size": "base" // smaller STT model, ~150MB instead of ~500MB
}
```

Trade-off: smaller models respond faster and leave more VRAM free, but tool-calling reliability and conversational quality both degrade noticeably below the 3B class — this is a real accuracy/footprint tradeoff, not a free lunch. If you have 6GB+ VRAM available, you can instead size _up_:

```json
{
  "model": "qwen2.5:7b" // ~4.7GB — noticeably stronger reasoning
}
```

---

## Usage Examples

| You say                                  | What Vox does                                                                    |
| ---------------------------------------- | -------------------------------------------------------------------------------- |
| _"What's the weather like?"_             | Fetches live weather for your configured location, answers in one turn           |
| _"Is it good weather for a walk?"_       | Combines current weather + time of day into a direct recommendation              |
| _"Open YouTube and search for [X]"_      | Opens browser, navigates, types your query                                       |
| _"What are my system specs?"_            | Reads CPU/RAM/disk/GPU stats, speaks them as natural sentences (not raw numbers) |
| _"What's on my screen right now?"_       | Screenshots + OCRs the screen, summarizes the content                            |
| _"Open a terminal and run `git status`"_ | Executes the command, reports the result                                         |
| _"Create a file called notes.txt"_       | Creates the file in your home directory                                          |
| _"Close this tab"_                       | Sends the appropriate keyboard shortcut                                          |
| _"What time is it?"_                     | Answers with current local time, no LLM round-trip needed                        |
| _"Search cons of [X] on ChatGPT"_        | Opens chatgpt.com and types the query directly into the page                     |

Press **Ctrl+Space** to toggle the floating chat window for typed interaction, or right-click the tray icon for plugin reload, conversation clearing, and settings.

---

## Available Tools

The LLM has access to the following structured tools (via Ollama's `tools=` schema):

| Tool                | Purpose                                                          |
| ------------------- | ---------------------------------------------------------------- |
| `open_url`          | Open any website or search query in the default browser          |
| `run_command`       | Execute a shell command and return its output                    |
| `get_system_info`   | CPU, RAM, disk, GPU usage — converted to natural spoken language |
| `open_app`          | Launch a desktop application                                     |
| `create_file`       | Create a file with specified content                             |
| `read_screen`       | Screenshot + OCR for screen-reading queries                      |
| `keyboard_shortcut` | Send keyboard shortcuts (close tab, new window, etc.)            |
| `type_text`         | Type text into the currently focused window                      |
| `get_active_window` | Identify which application currently has focus                   |

---

## PyGPT Plugin Integration

Vox's plugin system follows the [PyGPT](https://github.com/szczyglis-dev/py-gpt) plugin convention (`__init__.py` + `plugin.py`, with a `Plugin` class exposing handler methods) rather than a fully custom format. Two plugins ship built-in under this convention:

- **`plugins/plugin_piper_tts/`** — wraps the Piper TTS binary as a PyGPT-style plugin, exposing voice synthesis as a discrete, swappable component.
- **`plugins/plugin_flash_avatar/`** — the animated avatar widget, packaged the same way so it can be disabled/replaced independently of the core voice loop.

This is **not** a full embedding of the PyGPT framework — Vox does not depend on or run inside PyGPT itself. It only borrows PyGPT's plugin file convention so that the two bundled plugins (and any custom ones you write) follow a consistent, documented shape. Drop additional plugins into `plugins/custom/` using the same `__init__.py` + `plugin.py` pattern, and they'll be auto-discovered and hot-reloadable from the tray menu without restarting Vox.

---

## Project Structure

```
voxd/
├── vox.py                      # Main application entry point (UI, tray, worker thread)
├── core/
│   ├── brain.py                 # LLM reasoning, intent routing, tool-calling logic
│   ├── voice_engine.py           # Whisper STT + Piper TTS
│   ├── desktop_control.py        # Desktop actions, weather, OCR, system info
│   ├── memory_engine.py          # ChromaDB long-term conversational memory
│   ├── hotkey_listener.py        # Push-to-talk key listener
│   ├── safety.py                 # Command risk classification (blocks destructive ops)
│   ├── monitor.py                # Proactive background system monitoring
│   ├── gpu_lock.py                # Process-wide GPU resource mutex
│   └── plugin_loader.py          # Dynamic plugin discovery
├── plugins/
│   ├── custom/                   # Drop-in plugin directory (auto-discovered)
│   ├── plugin_piper_tts/          # Bundled PyGPT-style TTS plugin
│   └── plugin_flash_avatar/       # Bundled PyGPT-style avatar plugin
├── voices/                       # Piper voice models
├── config/config.json            # User configuration
└── scripts/                      # Install / launch / autostart helper scripts
```

---

## Known Limitations

Being upfront about where this stands:

- **Tool-calling reliability depends on model choice.** Smaller local models (3B class) occasionally fail to emit a structured tool call and respond conversationally instead. The deterministic Quick Router layer exists specifically to route the highest-value, highest-frequency commands around this weakness, but it doesn't eliminate it for arbitrary phrasing.
- **No wake-word detection.** Push-to-talk only — by design, for privacy and to avoid false triggers, but it does mean a key press is always required.
- **Screen-reading is OCR-only, not vision-based.** It can read text on screen but can't interpret images, diagrams, or UI layout — it doesn't "see" the screen the way a multimodal model would.
- **VS Code / IDE integration is shallow.** Currently relies on window-title parsing to guess the open file rather than a proper extension/LSP integration.
- **Single-user, single-machine.** No multi-user profiles, no remote/mobile access — this runs as a local desktop daemon for one person on one machine.
- **English only.** STT and the conversational prompting are tuned for English (including non-native accents), not multilingual.

---

## Roadmap

- [ ] Lightweight on-device vision model for true screen understanding (not just OCR)
- [ ] Optional wake-word activation
- [ ] Proper VS Code extension integration instead of window-title heuristics
- [ ] Conversation export / session summaries

---

## License

MIT — see [LICENSE](LICENSE).

---

_Built solo as a hands-on exploration of local-first AI agent architecture: balancing LLM tool-calling against deterministic routing, and real-time voice I/O against consumer GPU VRAM constraints._
