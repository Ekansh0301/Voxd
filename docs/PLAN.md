# TARS: A Local, Hands-Free Desktop Agent on a 4 GB GPU

> Status: design plan, written 2026-09-30. It replaces the v1 prototype architecture: v1 was single-shot voice commands, and v2 is a multi-agent system that operates the laptop.
> Decisions made (2026-09-30):
> - **Name:** TARS, after Interstellar's robot, on your laptop "tardis".
> - **Browser:** Firefox, with Outlook web for mail.
> - **Voice:** push-to-talk, English with an Indian accent.
> - **Avatar:** Live2D 2D.
> - **Cloud escalation:** allowed for hard and research tasks. Content may be sent with PII redacted; the provider is decided later.
>
> Target machine: HP Victus 16 · i5-11400H (6C/12T, AVX-512) · 16 GB RAM · GTX 1650 Mobile 4 GB · NVMe · **Ubuntu 26.04 LTS, GNOME 50 on Wayland** (upgraded 2026-10; X11 apps run via XWayland) · PRIME on-demand, with the desktop rendered on the Intel iGPU.

---

## 0. What we are building

A local assistant that you **talk to and that operates your laptop for you**. It can:

- **See** the screen through real UI structure (accessibility trees and browser DOM), not just OCR text.
- **Act** on the desktop, the browser, the terminal, files, mail and messages.
- **Work multi-step and recursively.** A conductor agent delegates to specialist agents, and those can spawn sub-tasks.
- **Speak, listen and show presence** through an animated avatar with lip-sync and state and emotion.
- **Watch things in the background** and speak up only when it matters.
- **Plug into everything through MCP.** It is an MCP client for any tool server, and an MCP server so other tools can use it.
- **Learn your routines.** Successful task traces become reusable skills, so repeated tasks get fast and reliable.
- **Keep you in control.** It uses permission tiers, confirmation before anything irreversible, a kill switch, and an audit log.

Everything runs locally by default. Optional cloud escalation is off unless you turn it on.

---

## 1. Hardware reality: the budget we design around

Measured on this machine:

| Resource | Value | Consequence |
|---|---|---|
| GPU | GTX 1650 Mobile (TU117), 4096 MiB, of which **CUDA can use 3714 MiB**; no tensor cores | One model of about 4B parameters at 4-bit fits, and one only. llama.cpp must be **built for the Pascal/MMQ kernel path** (`CMAKE_CUDA_ARCHITECTURES=61-virtual;80-virtual`, `GGML_CUDA_FORCE_MMQ=ON`). The default sm_75 build is 3.2× slower at prompt reading on this card. |
| GPU used at idle | **58 MiB**. The desktop runs on the Intel UHD iGPU (PRIME on-demand). | Almost the whole 4 GB is ours. **Keep on-demand mode.** Never switch to `prime-select nvidia`. |
| CPU | i5-11400H, 6 cores / 12 threads, **AVX-512** | Strong enough for STT, TTS, embeddings, OCR, a detector model, and a **second tiny LLM (0.8B) on CPU**, which gives real parallelism. |
| RAM | 16 GB | GGUF files stay in the page cache, so a model swap takes seconds, not tens of seconds. |
| Disk | NVMe, 83 GB free | Fine for several model variants. |

**Measured in Phase 0** (see [BENCHMARKS.md](BENCHMARKS.md)):

- **Qwen3.5-4B Q4_K_M:** decodes at **~36 tokens/s** and prefills at **~460 tokens/s**. It uses 3.06 GB of VRAM at an 8K context.
- **Prefill is the hidden cost.** A cold 2,500-token prompt takes about 6 s. **With the prefix cached it takes about 0.1 s**, with 2,499 of 2,500 tokens reused, so per-role prefix caching is mandatory.
- **Picking the right tool** from 15 tools, with no prompt tuning yet: **92%**, at about 1 s per decision.
- A novel 10-step task will take roughly 20–60 s. Repeated tasks run through skills (see §8.6) take a few seconds.

### 1.1 VRAM residency plan

```
┌──────────── GTX 1650 · 3714 MiB usable (measured: brain 3.06 GB) ─────┐
│ CUDA context + llama.cpp compute buffers           ~350–500 MiB     │
│ BRAIN: Qwen3.5-4B text weights, Q4_K_M / IQ4_XS    ~2.4–2.9 GiB     │
│ KV / recurrent state (hybrid attention = small)    ~150–400 MiB     │
│ headroom (avatar WebGL runs on the iGPU, not here)  ~200–600 MiB    │
└─────────────────────────────────────────────────────────────────────┘
CPU side (always on):  STT · VAD · TTS · embeddings · OCR/detector ·
                       vision projector (mmproj) · "Scout" Qwen3.5-0.8B
On-demand GPU swap:    GUI-grounding specialist (UI-Venus-1.5-2B / GUI-Actor-3B)
                       loaded only when structure-based perception fails
```

Rules:

1. **Exactly one GPU-resident LLM, the Brain.** Every agent role shares it. A role is a prompt, a tool subset and an output schema, not a separate model.
2. **Everything else runs on CPU by default.** STT moves off the GPU, which frees about 500 MiB compared with v1.
3. **Swaps are explicit and rare.** A GPU scheduler (see §4.3) unloads the Brain, runs the specialist, and reloads, at a cost of about 2–4 s from the page cache. `llama-swap` manages this.
4. **Vision is a projector, not a second model.** Qwen3.5 is natively multimodal. Its `mmproj` vision encoder can stay on CPU (`--no-mmproj-offload`), so the screen is described without extra VRAM. Measured on AC: with `--image-max-tokens 256` it reads a dialog screenshot correctly in **~1 s** once warm (3.6 s for the first), using no VRAM. At 1024 image tokens it takes 38 s, and putting the projector on the GPU runs out of memory next to the Q4_K_M brain. So TARS crops to the focused window and caps the image tokens. It's rarely needed, because structure comes first.

---

## 2. Design principles for small-model agents

These principles are what make a 4B model behave like a much larger one.

1. **Structure beats pixels.** Read the accessibility tree or DOM, which is exact, cheap and small, before any screenshot. Use vision only as a fallback.
2. **Constrain every output.** Every agent decision is decoded against a JSON schema (llama.cpp grammar / `response_format`). That removes parse failures, and with them "the model answered chat-style instead of calling the tool".
3. **Keep prompts small and stable.** Each role has a static prefix (persona, tools and examples) that is **cached**. The part that changes per step stays under about 1,500 tokens: the task card plus the last few observations.
4. **Deterministic first, LLM last.** A fast-path intent router and skills handle known requests. The LLM plans only when something is novel.
5. **Verify every action.** After acting, re-perceive and check that the expected change happened. Small models fail silently, and verification catches it.
6. **Pass references, not blobs.** Agents exchange short handoff notes plus IDs of blackboard artifacts (page snapshots, files, emails) instead of pasting content.
7. **Few tools per role.** No role sees more than about 12 tools. A `find_tool` meta-tool searches the rest by embedding.
8. **Learn from success.** Store successful traces as parameterized skills and replay them. Fine-tune on your own traces later (see §13.3).
9. **Use the CPU in parallel.** While the GPU Brain thinks, the CPU runs the Scout model (summarizing emails and pages), fetches, indexing and perception.
10. **The human is part of the loop.** Irreversible actions need confirmation, the agent pauses when you touch the mouse or keyboard, and one key stops everything.

---

## 3. System architecture

```
                                   ┌──────────────────────────────┐
     mic ─► PTT key ─► VAD ─► STT  │         VOICE SERVICE        │ TTS ─► speakers
                                   │  turn manager · barge-in·AEC │◄─ sentence stream
                                   └──────────────┬───────────────┘
                                                  │ utterances / speech events
┌────────────── UI (avatar overlay · chat · task tree · approvals) ───────────────┐
└──────────────────────────────────▲──────────────────────────────────────────────┘
                                   │ WebSocket (events, approvals, avatar state)
┌──────────────────────────────────┴──────────────────────────────────────────────┐
│                                 TARS CORE (asyncio)                             │
│                                                                                 │
│  Fast-path router ──► Skill replayer            Policy engine (permission tiers)│
│        │ (novel)                                         ▲                      │
│        ▼                                                 │ every tool call      │
│  CONDUCTOR ──delegate──► PLANNER                         │                      │
│      │                     │                             │                      │
│      ├──► DESKTOP operator ├──► WEB operator ──► RESEARCHER                     │
│      ├──► COMMS agent      ├──► CODER/DEBUGGER ──► VERIFIER                     │
│      └──► SENTINEL (monitor, mostly rules)                                      │
│                                                                                 │
│  Message bus + Blackboard (SQLite)   Task tree + budgets   Memory (episodic,    │
│  GPU scheduler (priority queue)      Tracing (JSONL)       facts, skills)       │
│                                                                                 │
│  MCP CLIENT MANAGER ── tool registry · tool retrieval · schema compaction       │
└───────┬─────────────┬───────────────┬──────────────┬──────────────┬─────────────┘
        │ stdio       │               │              │              │
  tars-desktop  firefox-devtools  tars-system    cloud-escalate  filesystem, git,
  (AT-SPI, input, -mcp (your real (metrics, logs, (provider-      github, searxng,
   vision SoM)    Firefox: Outlook services,shell) neutral, PII-   fetch, ...
                  + all sites)                     redacted)
        │
  ┌─────┴─────────────────────── MODEL SERVICES ─────────────────────────────┐
  │ llama-swap ─► llama-server: Brain (GPU) · Grounder (GPU, on demand)      │
  │               llama-server: Scout 0.8B (CPU)                             │
  │ faster-whisper / sherpa-onnx (CPU) · Kokoro/Piper (CPU) · embeddings(CPU)│
  └──────────────────────────────────────────────────────────────────────────┘
```

Processes run as `systemd --user` services:

- `tars-core` (Python, asyncio)
- `tars-voice` (Python; audio in its own process so glitches never block the core)
- `llama-swap` (model server front)
- `tars-ui` (Qt shell with a WebEngine avatar)
- `searxng` (podman container)

MCP servers are child processes of the core.

---

## 4. Model stack

### 4.1 Choices (LLMs confirmed by the Phase 0 benchmark)

| Role | Primary | Candidates to benchmark | Where |
|---|---|---|---|
| **Brain** (all agents) | **Qwen3.5-4B Q4_K_M** ✅ chosen: 92% tool accuracy, 36 tok/s, prefix cache hits, vision; f16 KV at 8K ctx (3.06 GB) | Rejected: IQ4_XS (−5 points accuracy, saves only 250 MB); Qwen3-4B-2507 (doesn't fit 8K with f16 KV, and 77% native tool accuracy with q8_0 KV); Qwen3.5-2B (fast at 66 tok/s, but only 72% accuracy) | GPU |
| **Scout** (untrusted-content reader, triage, summaries) | **Qwen3.5-0.8B Q4_K_M**, pure CPU (`--device none`): 0 VRAM, 27–32 tok/s on AC, and the Brain keeps ~37 tok/s while it runs | Qwen3.5-2B on CPU if its summaries need to be better | CPU |
| Vision (describe / verify) | Qwen3.5 `mmproj` F16, `--image-max-tokens 256`: ~1 s per read once warm, 3.6 s for the first, on AC | — | CPU |
| GUI grounding (fallback) | **UI-Venus-1.5-2B** | GUI-Actor-3B; BrowserVLM-0.5B once its weights are released | GPU swap |
| UI element detection | OmniParser v2 icon detector (YOLO) + RapidOCR boxes | Florence-2-base captions for unlabeled icons | CPU |
| STT | **faster-whisper `small.en` int8**, chosen by word error rate on **your Indian-English recordings** | `medium.en` int8 (more accurate on accents, about 2–3× slower on CPU), `distil-small.en`, sherpa-onnx Parakeet-TDT-0.6B | CPU |
| VAD | Silero VAD | — | CPU |
| Wake word | *later:* openWakeWord, custom "hey TARS" (PTT only for now) | — | CPU |
| TTS | Measured on AC: **Piper** first sentence 73 ms (lessac-medium) to 275 ms (ryan-high); **Kokoro-82M fp32** 0.7–0.9 s with RTF 0.32, and more natural. Pick by listening (`bench/results/tts/`). With Kokoro, the first chunk is cut at the first comma to keep first audio near 1.5 s | Kokoro int8 rejected: 3.5× slower than fp32 on this CPU (RTF 1.1) | CPU |
| Embeddings | bge-small-en-v1.5 / nomic-embed ONNX | EmbeddingGemma-300M | CPU |

Notes:

- Qwen3.5 small models ship vision as a separate `mmproj` file. Per Unsloth's docs, Qwen3.5 GGUFs with a separate mmproj don't run in Ollama. **We use llama.cpp's `llama-server` directly, behind `llama-swap`.** Ollama is kept only as a fallback.
- Qwen3.5 uses hybrid linear attention, so its KV memory stays small. That's why it fits an 8K context in f16 where Qwen3-4B does not. **Its prefix-cache reuse measured fine**: a warm 2,500-token prefix costs about 0.1 s. A q8_0 KV cache brings no benefit for it (saves 100 MB, but decode drops to 29 tok/s), so f16 stays.

### 4.2 Inference optimizations

| Technique | Win |
|---|---|
| **Per-role prefix caching**: `llama-server -np 2–3 --cache-reuse`, with each role pinned to a slot (`id_slot`) and slot save/restore (`--slot-save-path`) for the static role prefix | Turns 3–5 s of prefill per step into under 0.5 s |
| **Constrained decoding** (`response_format: json_schema` / GBNF) | Near-zero malformed tool calls |
| **Thinking only where it pays**: Planner and Debugger enable `enable_thinking` with a token cap; everything else runs without thinking | Keeps typical steps fast |
| **Two parallel slots** (`-np 2`): the foreground task and a background job share continuous batching | About 1.5× aggregate throughput, since decode is memory-bound |
| **Quantized KV cache** (`-ctk q8_0 -ctv q8_0`) | Halves the attention KV |
| **Speculative decoding** with 0.8B as a draft model, only if VRAM allows after measurement | Up to about 1.5–2× decode speed, but may not fit, so treat it as optional |
| **Compact tool schemas**: third-party MCP tool descriptions rewritten to one line each | Saves hundreds of prompt tokens per step |
| **Dynamic few-shot**: 2–3 examples retrieved by similarity from successful traces | Big accuracy gain for small models |

### 4.3 GPU scheduler

A single async priority queue in front of the Brain:

| Priority | Work |
|---|---|
| P0 | A live voice turn, where the user is waiting |
| P1 | The foreground task step |
| P2 | Background work (Sentinel triage, memory curation, indexing) |

Preemption happens at step boundaries. A swap request, such as loading the grounder, waits for the queue to drain, then calls `llama-swap`. The scheduler exposes live VRAM from NVML to the UI. It replaces v1's `GPU_LOCK`.

---

## 5. Voice and avatar

### 5.1 Voice pipeline (full-duplex-ish)

```
mic ─► PipeWire echo-cancel source (WebRTC AEC) ─► 30 ms frames ─► Silero VAD
   ├─ PTT key held = listening (wake word can be added later without redesign)
   └─ speech segment ─► STT (CPU) ─► transcript + confidence ─► Core

Core reply tokens ─► sentence chunker ─► TTS queue ─► playback (chunked, interruptible)
                                              └─► amplitude/visemes ─► avatar
```

- **Streaming out.** The LLM streams tokens. The first complete sentence goes to TTS at once, and the rest are pipelined. The target is under 1.5 s from end of speech to first audio on the fast path.
- **Barge-in.** While TARS speaks, VAD runs on the echo-cancelled mic. More than 300 ms of user speech pauses TTS and starts listening. "Stop", "wait" and "cancel" act as hard interrupts.
- **Progress narration** during long tasks: short cues like "Opening Outlook… found 3 unread from Rahul…", throttled so it doesn't chatter.
- **Hotwords.** Contact names, app names and project names are fed to faster-whisper `hotwords`, not `initial_prompt`. v1 learned that `initial_prompt` gets hallucinated back into the transcript.
- **Mode.** **Push-to-talk only for now.** The key release marks end of speech exactly, with no silence wait, which saves about 0.5 s per turn. Pressing PTT while TARS talks interrupts it. Wake word and follow-up listening are a later add-on.
  - **On Wayland** the key comes from the GlobalShortcuts portal, which reports press and release. GNOME may refuse a modifier on its own (v1's Right Ctrl) as a shortcut, so the likely default is a spare non-modifier key (Pause, Insert, ScrollLock, or an F-key). If you want Right Ctrl specifically, the evdev fallback can read it, but that needs you to add yourself to the `input` group.
- **Language: English, tuned for Indian English.**
  - Record about 100 of your real commands in Phase 0 and pick the STT model by word error rate on *your* voice, not on benchmarks.
  - Feed faster-whisper `hotwords` with Indian names, places and your vocabulary (contacts, IIIT, Hyderabad, app and project names).
  - Add a post-STT correction pass that fuzzy-matches transcripts against known entities (contacts, apps, sites), so "open outluk" resolves to Outlook.
  - Keep a small list of Indian-English phrasings for the fast path ("do one thing…", "kindly open…", "what is the time now").
  - If `small.en` misses too often on your accent, move up to `medium.en` int8 on CPU, still with no VRAM cost.

### 5.2 Avatar

- **Format: Live2D (Cubism 4/5)**, rendered with the official Live2D Cubism Web SDK. It is shown in a **transparent, always-on-top, click-through Qt WebEngine window**. On Wayland, Mutter doesn't let native clients stay on top or pick their position, so the overlay runs under **XWayland** (`QT_QPA_PLATFORM=xcb`), where both work. A small GNOME Shell extension is the fallback if that ever regresses. Rendering runs on the Intel iGPU, so it costs about 0 MB of NVIDIA VRAM and a few percent of CPU, and runs at 60 fps capped (30 fps when idle to save battery).
- **Model: Mao (Niziiro Mao PRO)**, an official Live2D sample. It is the default in Open-LLM-VTuber and ships with an emotion map (neutral/joy/anger/sadness/surprise…), idle and tap motions, and lip-sync parameters. Browse the alternatives in the [Live2D sample collection](https://www.live2d.com/en/learn/sample/); the terms are in the [sample data terms of use](https://www.live2d.com/en/learn/sample/model-terms/). Later, buy one (nizima, Booth) or commission a custom TARS-themed character; it's a drop-in file swap. The Live2D Cubism SDK is free for individuals and small-scale use.
- **States** (mapped to the model's motions and expressions): idle (breathing, blinking), listening (leans in), thinking (eyes up), **acting** (looks toward the window being operated, and an "agent has control" border is drawn around the screen), speaking (lip-sync), confirming (holds up a card with the action summary), error.
- **Lip-sync.** Audio RMS drives `ParamMouthOpenY`, and a cheap vowel estimate drives `ParamMouthForm`. Later, phoneme timings from the TTS front-end.
- **Emotion.** The Conductor may emit `{"emotion": "happy|concerned|focused|playful"}` in its schema, which maps to the Live2D model's expressions.
- **Reuse.** Open-LLM-VTuber already runs Live2D on the official Cubism 5 Web SDK with a desktop-pet overlay and lip-sync. Lift its frontend code rather than writing it from scratch.

### 5.4 Personality: TARS settings
Just like the film, the personality has sliders in `config/tars.yaml` that you can change by voice ("TARS, humor 60%"):
- `humor` (0–100, default 60): wit level in replies.
- `honesty` (default 90): how bluntly it reports failures and uncertainty. It never goes below telling you when an action failed.
- `verbosity` (default low): spoken reply length. Chat can always show more.

These are injected into the Conductor's cached prefix, so there's no per-turn token cost.

### 5.3 UI panels (Qt shell)

- **Chat:** typed input, history, and streaming output.
- **Task tree:** live view of the root task, delegated sub-tasks, step logs, and screenshots or snapshots as evidence.
- **Approvals queue:** Tier-2 and Tier-3 actions, showing a diff, email preview or form summary, with Approve, Edit and Reject buttons. Voice "yes, send it" also works.
- **Status:** VRAM, active model, tokens/s, and the monitors that are running.

---

## 6. Perception: real screen reading

A layered pipeline where the cheapest exact source wins:

| Layer | Source | Covers | Cost |
|---|---|---|---|
| **L1 Accessibility tree** | AT-SPI2 via `pyatspi` / D-Bus | GTK, Qt, **Firefox (including web content, which is also the fallback for Outlook)**, Chromium (with `--force-renderer-accessibility`), Electron/VS Code (accessibility on), LibreOffice, GNOME apps | ~20–150 ms, exact text, roles, states, bounds, actions |
| **L2 Browser DOM / AX** | **Mozilla `firefox-devtools-mcp --connect-existing`** snapshot (UIDs) over **your real Firefox session** (cookies, logins, open tabs) via WebDriver BiDi | Every web page, including forms and dynamic content | ~100–300 ms |
| **L3 Terminal** | Shells run inside `tmux`; `tmux capture-pane` / `send-keys` | Full terminal text, exact error output | ~10 ms |
| **L4 Editor** | Small VS Code extension exposing open file, selection and diagnostics over a local WebSocket | Exact file path, cursor and errors (replaces v1's window-title guess) | ~10 ms |
| **L5 Vision fallback** | Screenshot → YOLO icon detector + RapidOCR boxes → **Set-of-Mark** numbered overlay → LLM picks an element ID | Canvas apps, games, badly accessible apps | ~0.5–1.5 s on CPU |
| **L6 VLM** | Qwen3.5 projector (describe/verify), or the GUI grounder (swap) | "What is this chart", "click the gear icon" when nothing is labelled | 2–10 s |

**One-time setup:**

- `gsettings set org.gnome.desktop.interface toolkit-accessibility true` (currently `false` on this machine; TARS will ask before changing it)
- `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`
- Firefox launched with `--marionette --remote-debugging-port` by a TARS launcher, which replaces your Firefox shortcut. The port is localhost-only. Firefox shows its striped "remote control" address bar while it's on; that's expected.
- VS Code `"editor.accessibilitySupport": "on"`

**Compact snapshot format** (what the LLM actually sees):

```
window "Mail - Outlook — Mozilla Firefox"  (focused)
[3] searchbox "Search"
[7] button "New mail"
[12] row "Rahul Sharma · Report draft · 10:42"  (unread)
[13] row "GitHub · [tars] CI failed on main"  (unread)
… 38 more rows (say `expand 12-50`)
```

- Keep only visible, interactive or text-bearing nodes. Collapse wrapper containers and cap at about 120 lines.
- **Focus scoping:** by default only the active window is snapshotted, and others on request.
- **Change awareness:** AT-SPI events (focus, window open/close, text changed) and a perceptual hash of screenshots produce "what changed since the last step" diffs, so the agent doesn't re-read the whole screen every step.

**Answering "what's on my screen / explain this error":** send the focused window's L1/L3/L4 text to the Brain first. Add a cropped screenshot through the vision projector only when the text isn't enough.

**Existing code to evaluate before writing our own `tars-desktop` server:**

- `QwenLM/open-computer-use` (AT-SPI plus screenshots, MCP, cross-platform)
- `lotnikov/linux-desktop-mcp`
- `agent-sh/computer-use-linux` (Rust)
- `liufeicc/cc-computer-use`

Fork the best one, or wrap its core.

---

## 7. Action layer

Semantic actions come first and raw input is the fallback:

| Target | Preferred | Fallback |
|---|---|---|
| Native apps | AT-SPI `doAction`, `setTextContents`, `grabFocus`, selection (works the same on Wayland) | Pointer and keyboard through the **RemoteDesktop portal** (libei), at coordinates from a ScreenCast frame |
| Browser | firefox-devtools-mcp UIDs: click, fill, select, press, navigate, evaluate | AT-SPI actions on Firefox's accessible tree, then coordinates from the vision layer |
| Terminal | `tmux send-keys`; commands via the sandboxed `tars-shell` server | — |
| Windows | A tiny TARS **GNOME Shell extension** over D-Bus (list, focus, move, tile, workspace), since Wayland has no wmctrl/EWMH | AT-SPI frames: activate an app's window |
| Media | MPRIS D-Bus (`playerctl`) for play/pause/next on any player; `mpv ytdl://ytsearch1:…` for "play X" | — |
| System | `nmcli`, `pactl` (volume), `brightnessctl`, `systemctl --user`, notifications | — |

**Every action runs through this contract:**

1. **Pre-check:** the element exists, is enabled and is visible.
2. **Execute.**
3. **Post-verify:** the expected change happened, such as the text field containing the value, a new window, or a URL change.
4. **Record undo info** where possible.
5. **Retry once differently** (semantic ↔ coordinate) before reporting failure.

**Cooperative control:** real user input pauses the agent (detected through the extension's idle monitor / the InputCapture portal): "You took over — say 'continue' when ready."

**Wayland (the default since the 26.04 upgrade).** GNOME 50 has no X11 session, so every X11-era tool is replaced:

| Need | X11 tool (v1) | Wayland path in TARS |
|---|---|---|
| Push-to-talk key held/released | pynput (sees only XWayland apps now) | **GlobalShortcuts portal** (press and release signals, key bound once in GNOME's dialog). Fallback: evdev on `/dev/input`, which needs you to join the `input` group |
| Keyboard and mouse injection | xdotool | **RemoteDesktop portal** (libei). One consent prompt, then a restore token so it's remembered |
| Screenshots | scrot / gnome-screenshot | **Screenshot portal** for single shots, **ScreenCast** (PipeWire) when frames and injection coordinates must match |
| Window list, focus, move | wmctrl / xdotool | A TARS GNOME Shell extension (D-Bus), plus AT-SPI |
| Clipboard | xclip | `wl-clipboard`, or the portal clipboard in the RemoteDesktop session |
| Reading UI | AT-SPI | AT-SPI, unchanged. Element screen coordinates are often unavailable on Wayland, which is one more reason semantic actions come first |
| Browser | — | firefox-devtools-mcp (WebDriver BiDi), unaffected by the display server |

xdotool still works for XWayland windows (VS Code runs under XWayland by default), and TARS may use it there as a fast path.

---

## 8. Agent core

### 8.1 Roles

All roles run on the same Brain model. Each one gets its own cached prompt prefix, a tool subset of at most about 12 tools, and an output schema.

| Agent | Job | Key tools |
|---|---|---|
| **Conductor** | The only agent that talks to the user. It classifies each turn (chat / quick action / task), answers directly, runs a skill, or delegates. It owns the root task. | `delegate`, `ask_user`, `run_skill`, memory recall, quick tools |
| **Planner** (thinking on) | Breaks big goals into a step plan with success criteria and re-plans on failure | `delegate`, `find_skill`, read blackboard |
| **Desktop operator** | Native apps, windows, files in the GUI, system settings | `tars-desktop` (snapshot, act, find), `tars-system` |
| **Web operator** | Browsing, navigation, form filling, downloads, Outlook | firefox-devtools-mcp (compacted), vault lookup |
| **Researcher** | Web and local-document search and synthesis with citations; deep research by recursion | SearXNG, fetch + trafilatura, local index, Scout summaries |
| **Comms** | Mail and messages: triage, summarize, draft, send (gated) | mail MCP, chat MCPs / web operator, contacts memory |
| **Coder/Debugger** (thinking on) | Read the error on screen, find the cause, propose a patch, run tests | ripgrep, read-range, tmux, LSP/ruff/pyright, git, `tars-shell` sandbox |
| **Verifier** | Checks a child's result against its success criteria and evidence; cheap, often rule-based | Snapshots, diffs |
| **Sentinel** | Background monitoring and triage (see §11.6). Mostly rules, with Scout for language work. | `tars-system`, feeds |

### 8.2 The agent loop (every role)

```
while not done and budget_left:
    state   = perceive(scope)                  # compact snapshot / diff, ≤ ~800 tok
    prompt  = [cached role prefix] + task_card + last_3_observations + state
    action  = brain(prompt, schema=ActionUnion) # constrained JSON
    #   ActionUnion = tool_call | delegate | ask_user | finish | replan
    policy.check(action)                       # tiers, taint, approvals (§12)
    result  = execute(action)
    verdict = verify(action, result)           # expected-change check
    task_card.update(progress_note(result))    # 1–2 lines, not raw output
    detect_loops(); maybe_reflect_on_failure()
```

The **task card** is the agent's working memory, kept to at most about 300 tokens: goal, success criteria, plan with checkmarks, key facts found, and open questions. Raw tool output goes to the blackboard, and the card holds a reference plus a one-line summary.

### 8.3 Agent communication

This is an in-process typed message bus, persisted to SQLite so a task tree survives a crash or restart.

```python
class Msg(BaseModel):
    id: str
    ts: float
    task_id: str
    sender: str                  # "conductor" | "web" | ... | "user" | "system"
    recipient: str               # agent id | "parent" | "broadcast"
    kind: Literal["task", "result", "progress", "question", "answer", "event", "handoff"]
    body: str                    # ≤ ~150 tokens, natural-language handoff note
    refs: list[str] = []         # blackboard artifact ids: snapshot/2f9a, email/881, file/…
    data: dict | None = None     # structured payload (e.g. extracted fields)
```

- **Blackboard:** a shared artifact store (snapshots, extracted tables, drafts, files, URLs). Artifacts are content-addressed and passed by reference, and an agent loads only what it needs.
- **Questions bubble up.** A child asks its parent, and the parent can answer from context or escalate. Only the Conductor asks the user, so there is a single voice and no stream of interruptions.
- **Progress events** stream to the UI task tree and, throttled, to voice narration.
- **External agents:** the same message schema is exposed over MCP (see §9.3), and can be mapped onto the A2A protocol later if you want to talk to other agent systems.

### 8.4 Recursion and delegation

```json
{"type": "delegate",
 "agent": "web",
 "goal": "Find the refund policy page on example-shop.in and extract return window",
 "success_criteria": "a quoted sentence with the number of days + URL",
 "context_refs": ["email/881"],
 "budget": {"steps": 12, "seconds": 120}}
```

- A child returns `TaskResult{status: done|failed|needs_user, summary, refs, evidence}`. The parent (or the Verifier) checks the evidence before trusting it.
- **Guardrails:**
  - Depth ≤ 3.
  - A root budget of about 60 steps and 10 minutes by default, which you can extend by voice.
  - Loop detection: the same action, arguments and state hash seen 3 times means the agent must reflect or re-plan.
  - Failures are summarized upward, not raw.
- **Concurrency:** GPU calls are serialized by the scheduler, but children's I/O and CPU work (fetches, Scout summaries, indexing) run concurrently. A research fan-out of five pages therefore finishes about as fast as the slowest fetch plus one synthesis.
- **Plan-and-execute with re-planning:** the Planner writes a plan and reviews it after each completed step, adapting instead of blindly continuing.

### 8.5 Fast path (the v1 QuickRouter, grown up)

- An **embedding kNN intent classifier** on CPU (about 5 ms) over roughly 50 intents, each with 10–30 example utterances, plus slot filling. Examples: open app/site, media control, volume, time, weather, timers, "read my screen", "what's new in mail".
- Above a confidence threshold, the intent runs directly or makes a single LLM call. Below it, the request goes to the Conductor.
- New intents are added by writing example utterances into YAML. No regex.

### 8.6 Skills: procedural memory, the biggest win for a 4B model

- **Capture.** When a task succeeds, the trace is compressed into a **parameterized skill**:
  - intent description and embedding
  - parameters (for example `{recipient}`, `{query}`)
  - a step list with semantic selectors, such as `button name~"Compose"`, not raw coordinates
  - verification checks
- **Replay.** A similar request retrieves the skill. The Brain fills in the parameters (one call), and the replayer executes the steps deterministically with verification. A failed step falls back to the agent loop from that point.
- **Teach by demonstration.** Say "watch me". TARS records AT-SPI events, browser actions and your narration, then generalizes the recording into a skill and confirms it back to you.
- Skills are editable YAML in `~/.local/share/tars/skills/`, so you can review and share them.

---

## 9. MCP everywhere

### 9.1 TARS as an MCP client

- Uses the official `mcp` Python SDK. Servers are configured in `config/mcp.json`, in the same format Claude Desktop uses, so any community server drops in.
- The **tool registry** normalizes every tool: name, compact description, JSON schema, **permission tier** (derived from MCP tool annotations `readOnlyHint` / `destructiveHint` / `openWorldHint`, with manual overrides), and the roles allowed to use it.
- **Tool retrieval:** each role has a static core set. A `find_tool(query)` meta-tool searches the full registry by embedding and returns 3 compact schemas.
- **Schema compaction layer:** long third-party descriptions (browser MCP servers expose dozens of tools) are rewritten into one-liners and cached.

### 9.2 Servers

| Server | Source | Purpose |
|---|---|---|
| `tars-desktop` | **ours** (fork of an AT-SPI MCP; see §6) | Snapshot, find, act, windows, input, screenshot, Set-of-Mark |
| `tars-system` | **ours** | Metrics, processes, services, journald, battery/thermals, notifications feed, MPRIS, volume, network |
| `tars-shell` | **ours** | Sandboxed command execution (bubblewrap), tmux sessions, command AST risk parsing (bashlex) |
| `tars-memory` | **ours** | Recall, remember, facts, skills (also usable by other MCP clients) |
| Browser (your session) | `mozilla/firefox-devtools-mcp --connect-existing` | Drives **your real Firefox**: Outlook, logged-in sites, open tabs |
| Browser (background) | `microsoft/playwright-mcp` (headless, separate profile) | Research and fetch in an isolated browser that never touches your tabs or sessions |
| Filesystem, git, fetch, time | MCP reference servers | Files, repos, fetching |
| GitHub | `github/github-mcp-server` | Issues, PRs, CI status |
| Mail | **Outlook web in your Firefox, via the web operator** (no app, no API keys); Microsoft Graph is an optional upgrade later | Mail and calendar |
| Search | SearXNG MCP / our 30-line wrapper | Private meta-search |
| Messaging | *Deferred.* WhatsApp Web through the web operator, if wanted later | Chats |
| Cloud escalation | **ours**, `tars-cloud` (provider-neutral: Claude / OpenAI / Gemini / OpenRouter, chosen later) | Hard planning, coding and research. See §12.5 |

### 9.3 TARS as an MCP server

The core exposes `tars` as an MCP server with tools such as `ask_tars`, `speak`, `notify_user`, `request_approval`, `desktop_snapshot` and `run_skill`. That lets Claude Code, IDEs or other agents use your voice, screen and skills. Example: a long build in Claude Code finishes, and TARS says so out loud.

---

## 10. Memory and knowledge

This replaces ChromaDB, which fixes v1's broken DB and is lighter: **SQLite + FTS5 + `sqlite-vec`**, in one file.

| Store | Content | Used by |
|---|---|---|
| Working | Task cards, blackboard artifacts (with TTL) | Agents during a task |
| Episodic | Conversations, task traces, outcomes (hybrid BM25 + vector search) | "What did I ask yesterday about X", few-shot retrieval |
| Semantic / profile | Facts about you, with provenance and confidence (address, preferences, projects, style) | Personalization, form filling |
| People graph | Contacts ↔ emails ↔ chat handles ↔ relationship ↔ tone | Comms agent, STT hotwords |
| Procedural | Skills (see §8.6) | Replayer |
| Local knowledge | Index of ~/Documents, PDFs (PyMuPDF), notes, repos | Researcher, "find that PDF about…" |

- **Recall policy:** inject memory only above a relevance score, and cap it at about 200 tokens. Fact updates that change your profile are confirmed with you ("Should I remember you moved to Hyderabad?").
- **The memory curator** runs nightly on Scout on CPU. It extracts facts, merges duplicates and expires stale artifacts.
- **Viewable and editable** in the UI. You own your memory.

---

## 11. Capability modules

### 11.1 Browser control
- **Your real Firefox** through Mozilla's firefox-devtools-mcp (`--connect-existing`, WebDriver BiDi + Marionette), so tasks use the sessions you're already logged into, including an Outlook tab you already have open.
- **Background research** runs in a separate headless Playwright browser, so TARS never hijacks the tab you're reading.
- **Fallback:** if the BiDi connection is down, the Desktop operator reads and acts on Firefox through AT-SPI, which Firefox exposes fully.
- Navigation, multi-tab work, extraction to tables or markdown, downloads, uploads, waiting for page state, and shopping or booking research up to (not including) payment.
- Page-level skills for sites you use often (Outlook, YouTube, GitHub, ChatGPT/Gemini/Claude, AI Humanize).
- **Site registry** ([config/sites.yaml](../config/sites.yaml), enforced by `tars/sites.py`). Every browser action is checked against your per-site rules before it runs:

  | Access | Meaning | Your sites |
  |---|---|---|
  | `full` | Read and act; send/submit/post still need approval | Outlook, GitHub, YouTube, ChatGPT, Gemini, AI Studio, Claude, AI Humanize |
  | `navigate` | Open, read, click links; never types or submits | QuickRef cheatsheet, LeetCode, LinkedIn, any unlisted site |
  | `open_only` | Only open or focus the site | Monkeytype, keybr (your typing practice), WhatsApp Web |
  | `blocked` | Never opened, read or screenshotted; tabs skipped in snapshots | Moodle, IMS, Portals (college) |

  The registry also gives the fast path its spoken names ("open cheat sheet", "typing practice") and STT hotwords, and it tolerates slips like "outluk".

### 11.1b Writing helper: AI Humanize with its 200-word limit
"Humanize this" (the selected text, a file, or the last draft) works like this:
1. `tars/text_chunks.py` splits the text into chunks of at most ~190 words at sentence boundaries, keeping paragraphs intact.
2. The web operator opens aihumanize.io in a new Firefox tab. For each chunk, it pastes, runs the conversion, waits for the output, and copies it.
3. It joins the results in order and shows them next to the original for you to review. It copies the result to the clipboard only when you say so.

The site sits behind a Cloudflare check. If a challenge appears, TARS stops and hands it to you; it never tries to get past bot checks.

### 11.2 Form filling
- An **encrypted local vault** (key held in GNOME Keyring via `keyring`): profile fields (name, address, phone, education, IDs you choose to store), plus reusable documents (resume PDF).
- Field mapping: label, placeholder and `autocomplete` attributes, then an embedding match against vault keys, then LLM disambiguation for the leftovers.
- Flow: fill → **review card** (every field and value, with gaps highlighted) → you confirm → submit (Tier 3).
- Passwords stay in the browser's password manager, and the LLM never sees them. OTP, 2FA and CAPTCHA are handed to you, and the agent waits.

### 11.3 Debugging and coding
- "Why is this failing?" reads the exact error from tmux or the VS Code extension, finds the file and line, reads the surrounding code, runs the failing command in the sandbox, forms a hypothesis, and proposes a patch as a diff in VS Code. It applies the patch on approval and re-runs the tests.
- Tools: ripgrep, a tree-sitter repo map, read-range, LSP diagnostics (pyright/ruff), git, test runner.
- Honest limit: a 4B model is a junior debugger. It is good for stack traces, config errors, and missing imports or deps; weak on deep logic. **Delegation options:** Aider with the local model, or, if you opt in, an external coding agent (for example the Claude Code CLI) wrapped as an MCP tool.

### 11.4 Search and research
- SearXNG in a local container, with ddgs as fallback. Fetch → trafilatura extract → chunk → CPU embed and rerank → answer with numbered citations, read aloud briefly and shown fully in chat.
- **Deep research is recursive:** the Researcher splits a question into 3 sub-questions, children search and read in parallel (Scout summarizes each page on CPU), and the parent synthesizes, checks for gaps, and recurses once more if needed. Depth ≤ 2.
- Local search covers documents, PDFs, notes and past conversations.

### 11.5 Mail and messages: Outlook web, draft then approve

**The flow for "reply to Rahul's latest mail, say I'll send the report by Friday":**
1. The web operator attaches to your open Outlook tab in Firefox (college Microsoft 365 account, already logged in at `outlook.office365.com/mail/`), or opens it.
2. It snapshots the message list: sender, subject, preview, time and unread status, as structured elements, not OCR. It finds Rahul's latest thread and opens it.
3. It extracts the thread text into the blackboard, marked **untrusted**.
4. Scout (local, no tools) summarizes the thread and pulls out who is asking what and by when.
5. The Brain drafts the reply in your style, using few-shot examples from your Sent folder to this person, which are cached in the people graph.
6. The web operator clicks **Reply** and types the draft into Outlook's own compose box. **It stops here.**
7. The avatar holds up an approval card, and TARS says: "Draft ready for Rahul. Want me to read it?" You can:
   - say "shorter", "more formal" or "add that I'll call tomorrow", and it re-drafts in place
   - edit it yourself directly in Outlook
   - hold PTT and say "send it"
8. Only then does it click **Send** (Tier 3). It verifies the message appears in Sent, and reports.

**Also:**
- **Triage:** Scout classifies new mail (urgent / needs reply / FYI / promo) on CPU. The Sentinel speaks only for urgent mail or mail from people you mark important.
- **Summaries:** "What's new?" gives a 3-line digest, and "Tell me about Rahul's mail" gives a thread summary.
- **Drafting in your style:** few-shot from your own sent mail to that person. Drafts are read back or shown, and you can say "shorter", "more formal" or "add that I'll call tomorrow".
- **Sending is always Tier 3.** Voice confirmation reads back the recipient and a summary, then asks "send it?".
- **New-mail awareness:** Outlook web desktop notifications (enable them in Firefox) are picked up by the D-Bus notification monitor, plus a gentle periodic check of the open tab.
- **Skills:** after two or three runs, `outlook.reply`, `outlook.triage` and `outlook.search` become saved skills (about 8–15 s instead of 30–60 s). If Outlook's layout changes, a failed step falls back to the agent loop, which repairs the skill.
- **Messages (later, not in the current scope):** you use WhatsApp Web but don't need TARS replying there for now. When wanted, it would follow the same pattern: Incoming notification ("Rahul on WhatsApp: …") → "Reply: on my way" → draft typed into the chat box → you approve → send. Unofficial WhatsApp libraries risk account bans, so they are avoided.
- **Security:** all mail and message content is **untrusted** (see §12.3). Mail text goes to the cloud only in PII-redacted form, and only when a task is escalated (see §12.5).

### 11.6 Monitoring and proactive behaviour (Sentinel)

| Source | Example trigger |
|---|---|
| System (`psutil`, NVML, `upower`, sensors) | Disk above 90%, RAM pressure, **GPU or CPU thermal throttling**, battery below 15% while unplugged |
| journald / systemd | A new error burst, a failed unit, OOM kills |
| Notifications (D-Bus monitor) | Messages from important people |
| Mail (Outlook web notifications + periodic tab check) | Urgent mail |
| Calendar | Meeting in 10 min, with a join link on screen |
| GitHub (`gh`) | CI failed on your repo, PR review requested |
| Shell hook (tmux) | A long command finished or failed |
| Web watchers | Page-diff on a URL (results announced, price drop, slot open) |
| Schedules | "Every weekday 9 am: mail digest + calendar" |

- **Rules in YAML** (`condition → action`: notify, speak, run skill, open task), with Scout on CPU for language triage. The Brain is woken only when a rule asks for a real task.
- **Attention manager:**
  - Do-not-disturb.
  - Fullscreen or meeting detection (camera or mic in use), which means no speaking; queue it instead.
  - Batching into digests.
  - Per-source rate limits.
  - An "explain why you interrupted" log.

### 11.7 Everyday desktop
Apps, windows, workspaces, files ("move the PDFs I downloaded today into College/Sem5"), media via MPRIS, volume and brightness, Wi-Fi and Bluetooth, screenshots with annotation, clipboard history ("paste what I copied before this"), timers and reminders, and system Q&A ("why is the fan loud?" → the process using the CPU → offer to kill it, Tier 2).

---

## 12. Safety and control

This is non-negotiable for an agent that reads the web and your mail and holds your sessions.

### 12.1 Permission tiers (enforced by the policy engine on every tool call)

| Tier | Examples | Rule |
|---|---|---|
| T0 read | Snapshot, read file, search, list mail | Automatic |
| T1 local, reversible | Open app, type into a draft, create file, move a window | Automatic, logged, with undo |
| T2 local, destructive / system | Delete or overwrite files, kill process, install packages, change settings, sudo | Confirm (UI or voice) |
| T3 external / irreversible | **Send** mail or message, **submit** a form, post, purchase, delete remotely, git push | Confirm with an explicit readback, **always**, whatever the rules say |

Tiers come from MCP annotations plus our overrides. Unknown tools default to T2.

### 12.2 Shell sandbox
- `bubblewrap`: read-only `/`, a writable project dir and `/tmp`, network off unless the task needs it.
- Command risk from a **bash AST** (`bashlex`), not regex, so `cat x; rm -rf ~` is caught. v1's regex let exactly that through.

### 12.3 Prompt-injection defense
- **Taint tracking.** Content from the web, mail, messages or files not written by you is marked `untrusted` on the blackboard.
- **Dual-LLM pattern.** Untrusted content is first read by **Scout with no tools**, which returns structured, bounded data such as a summary, extracted fields and sender. The tool-using Brain sees that output, not raw attacker text, wherever possible.
- **Destinations come from you.** A T3 action's recipient or URL must come from your instruction or your contacts, never only from untrusted content.
- Instructions found inside content are shown to you, never executed.

### 12.4 Control
- **Kill switch:** hold `Esc` for 1 s, or say "TARS stop". This cancels all tasks, releases held keys and stops TTS.
- A visible "agent in control" screen border plus the avatar's acting state.
- A full **audit log** (every action, with its evidence), with replay in the UI.
- Secrets never go into prompts. Only vault references are used, and they are resolved at the tool boundary.

---

### 12.5 Cloud escalation (allowed: content with PII redacted)

**When it escalates:**
- The local agent fails a task twice.
- The Planner rates a task as hard: long-horizon work, deep coding, or research needing synthesis across many sources.
- You say "think hard" or "research this properly".

By default it asks first: "This one's tough. Use the cloud model?" You can switch that to automatic for specific task categories.

**What is sent: content with PII redacted, via a local redaction pipeline:**
1. Named entities are detected on CPU (Microsoft Presidio with a spaCy small model).
2. Regexes catch Indian formats: phone (+91), email, Aadhaar, PAN, IFSC, UPI IDs, PIN codes, and addresses.
3. Everyone in your people graph, and your own profile values, are masked.
4. Each PII item is replaced with a consistent placeholder (`<PERSON_1>`, `<EMAIL_2>`), and the mapping stays local.
5. The cloud's answer is de-pseudonymized locally before use.

**Never sent:** screenshots, raw files, vault or credential values, full mailboxes. Only the text needed for the current task is sent.

**How it's used:**
- **Planner mode (default):** the cloud returns a plan or a draft, and the local agents execute it and do all the clicking.
- **Research mode:** the cloud synthesizes from redacted, locally fetched page extracts.
- **Coding mode:** redacted code context and errors are sent; secrets are stripped by a secret scanner.

**Routes, tried in order (configurable):**
1. **An API provider, if a key is configured.** Recommended: a **free Gemini API key from AI Studio**, which you already use. It's official, fast and has a free tier, so it's the cleanest first route. Claude, OpenAI and OpenRouter keys also work.
2. **Web-AI route, if no API is available.** TARS does what you do by hand. It opens ChatGPT, Gemini, AI Studio or Claude in a **new tab** in your logged-in Firefox, pastes the redacted prompt, waits until the answer has finished streaming, reads it from the page, and closes the tab.
   - It's slower (about 15–60 s) and depends on each site's layout. Site skills handle this, with the agent loop as fallback when a layout changes.
   - It runs at human pace, one query at a time, with an hourly cap.
   - Login screens, CAPTCHAs and "are you human" checks are handed to you.
   - **Caveat:** the consumer terms of these AI apps generally disallow automated use of their web interfaces. Light personal use on your own account is a grey area, but an account could get flagged. That's why the API route comes first.
3. Otherwise, it asks you.

The same PII redaction applies on every route.

**Controls:**
- Provider-neutral adapter: API providers (Gemini / Claude / OpenAI / OpenRouter) plus the web-AI route.
- A daily spend cap.
- Every call is logged with exactly what was sent, viewable in the UI.
- A global "offline mode" switch disables it.

---

## 13. Observability, evaluation, self-improvement

### 13.1 Tracing
Every LLM call is logged to JSONL: role, prompt hash, tokens in and out, cache hit, latency, VRAM. So is every tool call: arguments, tier, result size, duration, verification verdict. A small trace viewer in the UI shows the task tree with timings. This is how you find what is slow or dumb.

### 13.2 Evaluation harness (`evals/`)
- **About 150 tasks** in categories: fast-path, desktop, browser, forms, research, mail, coding, recovery (injected failures), safety (injection attempts that must be refused).
- **Deterministic environments:**
  - A local test website with forms, logins and tables.
  - A local mail server with seeded mailboxes (for example `aiosmtpd` plus a Dovecot container).
  - A test GTK app.
  - Scripted repos with planted bugs.
- Success checkers assert end state (field values, sent mail content, file present), not model text.
- **Voice evals:** 100 of your own recorded commands measure STT word error rate and end-to-end latency.
- Runs nightly or on demand, and the report compares model, quant, prompt and skill versions.

### 13.3 Self-improvement loop
1. Collect successful traces, and your corrections of failed ones, as (state, action) pairs.
2. **QLoRA fine-tune** Qwen3.5-2B or 4B on them with Unsloth on free Colab/Kaggle T4s. The 1650 is too small to train a 4B model.
3. Export to GGUF, A/B it on the eval suite, and promote it if better.
4. Optional, opt-in: generate harder synthetic tasks and let a large teacher model label them. That is distillation into your local Brain.

**Latency targets (to be checked by evals):**

| Stage | Target |
|---|---|
| PTT press → listening cue (avatar + sound) | < 150 ms |
| End of speech → transcript (3 s utterance, CPU) | < 700 ms |
| Fast-path intent → action begins | < 250 ms |
| Brain first token (prefix cached) | < 600 ms |
| End of speech → first spoken audio (conversational) | < 1.5 s |
| Agent step (perceive → decide → act → verify) | 2–5 s |

---

## 14. New repo layout

*Current state (end of Phase 0):* `tars/`, `tests/`, `bench/`, `config/`, `deploy/`, `scripts/`, `docs/`, plus `legacy/` (the v1 prototype, kept runnable as a baseline until Phase 2–3). The tree below is the target the phases grow into.

```
tars/
  core/        bus.py tasks.py blackboard.py scheduler.py policy.py config.py tracing.py
  llm/         client.py gpu_scheduler.py structured.py prefix_cache.py fewshot.py
  agents/      base.py conductor.py planner.py desktop.py web.py research.py
               comms.py coder.py verifier.py sentinel.py   prompts/*.md  schemas.py
  router/      intents.yaml classifier.py slots.py
  skills/      capture.py replay.py demo_recorder.py store.py
  mcp/         manager.py registry.py retrieval.py compaction.py
  servers/     desktop/ (atspi.py snapshot.py actions.py som.py)  system/  shell/  memory/
  perception/  atspi.py browser.py terminal.py vscode.py vision/(detector.py ocr.py grounder.py)
  voice/       audio_io.py aec.py vad.py wakeword.py stt.py tts.py turn_manager.py visemes.py
  memory/      store.py episodic.py facts.py people.py index_docs.py curator.py
  monitor/     sources/*.py rules.py attention.py schedules.py
  ui/          shell.py (Qt) avatar_web/ (Live2D) chat/ tasks/ approvals/
  vault/       vault.py (keyring-backed)
vscode-ext/    minimal extension: open file, selection, diagnostics over WS
evals/         tasks/ envs/ checkers/ run.py report.py
config/        tars.yaml mcp.json intents.yaml rules.yaml
deploy/        systemd user units, llama-swap.yaml, searxng compose
docs/          PLAN.md (this) ARCHITECTURE.md SAFETY.md
tests/         unit tests (pytest) — fix pyproject testpaths
```

What carries over from v1: the persona and TTS formatting ideas from `brain.py`, weather and time helpers, the avatar state machine concept, monitor checks (these become Sentinel sources), and Piper voices. The rest is rewritten.

---

## 15. What to reuse from GitHub

| Need | Project | How we use it |
|---|---|---|
| LLM serving | `ggml-org/llama.cpp` (`llama-server`) | Brain, Scout, grounder; grammar, slots, cache |
| Model swapping | `mostlygeek/llama-swap` | One OpenAI-compatible endpoint that swaps models on demand |
| MCP | `modelcontextprotocol/python-sdk` (FastMCP) | Client manager and our servers |
| Browser | `mozilla/firefox-devtools-mcp` (`--connect-existing`); `microsoft/playwright-mcp` (headless, background) | Your real Firefox; isolated research browser |
| Desktop a11y | `QwenLM/open-computer-use`, `lotnikov/linux-desktop-mcp`, `agent-sh/computer-use-linux` | Evaluate, then fork or wrap for `tars-desktop` |
| UI detection | `microsoft/OmniParser` (icon detector), `RapidAI/RapidOCR` | Vision fallback, Set-of-Mark |
| GUI grounding | UI-Venus-1.5-2B, `microsoft/GUI-Actor` | On-demand grounder |
| STT | `SYSTRAN/faster-whisper`, `k2-fsa/sherpa-onnx` | CPU STT |
| VAD / wake | `snakers4/silero-vad`; `dscripka/openWakeWord` later | Speech trimming; wake word later |
| TTS | `OHF-Voice/piper1-gpl`, `thewh1teagle/kokoro-onnx` | CPU TTS |
| Avatar | Live2D Cubism Web SDK; frontend code from `Open-LLM-VTuber` (Cubism 5, desktop-pet mode, lip-sync); `moeru-ai/airi` as a reference | Live2D overlay and lip-sync |
| Search | `searxng/searxng`, `adbar/trafilatura` | Private search and extraction |
| Memory | `asg017/sqlite-vec` | Vectors in SQLite |
| Mail | Outlook web via the browser (no library needed) | Draft → approve → send |
| PII redaction | `microsoft/presidio` + spaCy `en_core_web_sm` | Redaction before cloud escalation |
| GitHub | `github/github-mcp-server` | CI and PR monitoring |
| Coding | `Aider-AI/aider` | Optional code-edit delegate |
| Sandbox | `containers/bubblewrap`, `idank/bashlex` | Safe shell |
| Fine-tuning | `unslothai/unsloth` | QLoRA on your traces |
| Scheduling | `agronholm/apscheduler` | Cron-like tasks |

Deliberately **not** used as the core: LangChain, CrewAI or AutoGen, because their prompt overhead and abstraction hurt a 4B model on a 4K–8K budget. LangGraph is acceptable if you want its checkpointing, but a thin custom core (about 2–3k lines) gives tighter control over every token.

---

## 16. Roadmap

This assumes part-time work at about 15–20 h/week. Every phase has **exit criteria measured by evals**, not vibes.

### Phase 0 — Foundation and measurement (1–2 weeks)
- Fix the v1 blockers so there is something working to compare against:
  - the import bug
  - the `_piper_proc` bug
  - the ChromaDB schema error
  - cross-thread Qt calls
  - the confirm dialog on the wrong thread
  - `_clean()` truncating replies
- Create the new repo skeleton, config, tracing, and a pytest setup.
- Install llama.cpp (CUDA build for sm_75) and llama-swap. Remove Ollama from the critical path.
- **Benchmark on your 1650:** Qwen3.5-4B (Q4_K_M, IQ4_XS), Qwen3-4B-2507, and Qwen3.5-2B. Measure VRAM, prefill and decode tok/s, prefix-cache hit latency, and tool-call accuracy on 60 labelled prompts. Also measure STT candidates on your recorded voice, and TTS latency and quality.
- **Exit:** a filled-in benchmark table (commit it as `docs/BENCHMARKS.md`), and the Brain, STT and TTS chosen.

### Phase 1 — Voice v2 and avatar v1 (2 weeks)

> **Progress (2026-10-01):**
> - Done: the voice loop (`python -m tars.voice`), `tars-pttd` for Right Ctrl on Wayland, the speech chunker, Kokoro `af_heart`, and interrupting with the key.
> - Measured from key release to first audio: **~2.8–3.2 s**. That's speech-to-text 1.5 s (CPU Whisper pads every clip to 30 s), the Brain's first token +0.3 s, and Kokoro's first chunk +1.0 s.
> - Whisper small.en on the GPU takes 0.47 s and fits next to the Brain (3550/3714 MiB). It needs cuDNN 9 in `.venv`. Parakeet on the CPU (no padding) is the alternative. Choose on your recordings.
> - **GPU Whisper adopted** (cuDNN 9 in `.venv`). Speech-to-text is now 0.55 s, and key release → first audio is **~1.7 s**. VRAM is 3.55 of 3.71 GB with the Brain, stable across turns.
> - **Live2D avatar done** (Mao PRO, head-and-shoulders framing). It's built on the **official Cubism 5 Web framework**, because pixi-live2d-display (2022, Cubism 4 framework) crashes on Cubism 5 models and Core 6. A build script patches the SDK's Demo from your local SDK copy, so none of Live2D's code is in the repo. It's served to an XWayland Qt WebEngine overlay through a private `tars://` scheme (no network port). State and mouth level stream over a token-protected localhost WebSocket.
> - **First real session (2026-10-01):** latency 1.4–2.0 s and push-to-talk interrupt worked. Whisper hit CUDA out-of-memory after a few turns: Brain 3.14 GB plus Whisper's 0.48 GB peak left only ~100 MB of slack. Fixed with Brain `-np 1 -ub 256` (−144 MiB, same prefill speed), a cap on CTranslate2's cache, temperature-0 decoding, and a session-long CPU fallback after any CUDA error. A soak test with interruptions peaked at 3538 of 3714 MiB. "TARS" was heard as "WhatsApp" because of over-broad hotwords; they're now a curated list in config. The persona no longer volunteers "can't do that yet". Personality voice commands ("humor 40%") are done, and `--save-audio` collects real utterances for the STT benchmark.
> - Left for Phase 1: interrupting while speaking needs echo cancellation once barge-in by voice is added (push-to-talk interrupt already works), and the STT model choice from your recordings.
- A separate voice process: PTT capture through the GlobalShortcuts portal (evdev fallback), Silero VAD trimming, turn manager, interrupt-on-PTT, sentence-streamed TTS, hotwords and entity correction for Indian English.
- The Qt shell (under XWayland, for always-on-top) with a transparent WebEngine **Live2D** avatar (sample model), the state machine, RMS lip-sync, TARS personality sliders, and chat.
- **Exit:** under 1.5 s to first audio on the fast path; STT word error rate ≤ 8% on your recorded commands; PTT interrupt stops speech in under 200 ms; no UI calls from worker threads (enforced by signals).

### Phase 2 — Agent core and MCP (3 weeks)

> **Progress (2026-10-01): core done.**
> - **Agent loop:** native tool calling, streamed so answers still start speaking early; up to 8 steps, loop detection, and tool output labelled as data.
> - **22 built-in tools with permission tiers:** files, sandboxed shell, desktop, media, volume, timers, system status, memory.
> - **Policy engine in code:** `shlex` command classification, secret paths, home-only writes, Trash instead of delete.
> - **Spoken approvals** with a "confirming" avatar state.
> - **Memory:** SQLite with FTS5 (facts and turns), with relevant facts injected per turn.
> - **Fast-path router** for unambiguous commands.
> - **Stdlib MCP client and manager** (tiers from tool annotations; unknown tools are T2).
> - **Evals** (`python -m evals.agent_eval`): **22/22 everyday, 7/7 safety**, median 1.7 s per task. They caught three real bugs, all fixed: move-into-new-folder lost files, read+write "copies" corrupted files, and the sandbox hid a home folder under /tmp.
> - **Deviations:** built-in tools instead of separate `tars-system`/`tars-shell` MCP servers (lower latency; they can still be exposed over MCP later). `find_tool` is deferred until the tool count needs it. `bashlex` is replaced by a conservative `shlex` classifier (anything with shell control operators asks first). Embeddings in memory are deferred.
- Bus, tasks, blackboard, GPU scheduler, and the single-agent loop with JSON-schema actions, task card and verification.
- MCP client manager, registry, compaction and `find_tool`.
- `tars-system` and `tars-shell` (sandbox, bashlex), plus reference filesystem and git servers.
- Policy engine, approvals UI and voice confirmation. Memory v2 in SQLite. Fast-path intent classifier.
- **Exit:** 30 multi-step shell/file/system evals at ≥ 75%; safety evals at 100% (no T3 action without approval).

### Phase 3 — Real screen reading and control (3 weeks)

> **Progress (2026-10-01):**
> - **Accessibility-tree reading and acting** over D-Bus (jeepney, no OCR). Concurrent breadth-first walk: 61 elements in about 85 ms. The model sees one compact line per element with **unique names instead of numeric ids** (`button 'OK (2)'`); with ids the 4B model clicked the wrong elements.
> - **Screen tools:** `read_screen`, `list_windows`, `click`/`click_sequence`/`type_into` by name. Send/Submit/Delete/Pay-like buttons need approval; password fields are refused; browser pages on blocked sites aren't read (DocURL check).
> - **Vision fallback:** the Screenshot portal (525 ms, permission remembered), with captures moved to a private temp file and deleted. The Brain's projector reads them, with optional region zoom: 14 px email text and a calculator display read correctly in 3–4 s.
> - **`read_terminal`** via tmux panes.
> - **Evals unchanged** with 29 tools: 22/22 + 7/7.
> - **Findings on this desktop:** Wayland gives every window the position (0, 0), so element→screen coordinates need the planned GNOME Shell extension. The GTK4 VTE terminal and GNOME Calculator 50's display aren't exposed via AT-SPI (vision covers them). Flutter (Spotube) and Electron (Claude desktop) expose almost nothing without flags.
> - **Weak spot:** multi-button GUI sequences with the 4B model (it typed 123×7 for 12×7) and verifying before claiming. Keyboard input via the RemoteDesktop portal ("type 12*7, Enter") and the browser driver are the better paths.
> - **Firefox:** your real Firefox via the "Firefox (TARS)" launcher and firefox-devtools-mcp. Its raw tools are hidden; `web_*` wrappers enforce sites.yaml, ask before Send/Submit-like clicks and never fill password fields.
> - **Your apps** (`config/apps.yaml`): open by name with the right flags (Electron apps get `--force-renderer-accessibility` so their buttons are readable), PDFs in Okular, VS Code at a file and line, Ghostty in a folder (commands run inside tmux so TARS can read the output), and Super Productivity tasks with reminders through its local REST API. Times like "tomorrow at 9" are parsed in code, not by the model, and each message carries the current time.
> - **Coding aids:** `check_code` (syntax check, then ruff / pylint / mypy from the project's .venv if present, in the sandbox), `edit_file` (replaces one exact snippet, shows the diff, asks first, keeps a backup) and `undo_edit`. A missing path answers "did you mean ~/code/app.py?", which fixed the 4B model dropping folders.
> - **Spotube** (Flutter: no accessibility tree at all): `play_music` matches the song against your own library (saved queue + history, read-only from Spotube's database, nothing searched online) and plays it through Spotube Connect's local WebSocket; "play some music" resumes over MPRIS. Connect is off by default and, when on, listens on all interfaces without a password, so on shared Wi-Fi it needs a firewall rule. Songs outside your library wait for keyboard input (RemoteDesktop portal) to use Spotube's search.
> - **Termius** (Electron, readable with `--force-renderer-accessibility`): `termius_connect` finds the saved host cards (Ada, Turing) and presses one. **Super Productivity:** reminders go in through its local REST API (no token; it only accepts title/notes/due time, not its own alarm), and TARS adds the alarm as a transient systemd user timer that pops a notification. Its header icons, Sync included, are unnamed for accessibility and hidden while the reminders dialog is up, so Sync waits for keyboard input (its shortcut is Ctrl+S).
> - **Screenshots:** TARS registers as `org.tars.TARS` with the portal and drops its permission after each capture. Before, the "Allow" was stored under the empty app id shared by all non-Flatpak apps, which made Flameshot take silent GNOME screenshots.
> - **Keyboard input** via the RemoteDesktop portal under `org.tars.TARS`: approved once, then a restore token (0600) starts later sessions with no dialog in about 0.1 s. `type_text` / `press_keys` check the focused window first: terminals, password fields and blocked sites are refused; Ctrl+Enter and closing shortcuts need approval. Live: typed 12*7 Enter into Calculator → 84; typing into Ghostty refused.
> - **Window focus is the gap:** GNOME gives windows started from the background a "ready" notification instead of focus, and AT-SPI GrabFocus is refused, so focusing an app needs the GNOME Shell extension (next). GNOME 50 also shows portal access dialogs only to the focused app, so the screenshot permission for `org.tars.TARS` is granted once with busctl.
> - **GNOME Shell extension "TARS windows"** (`deploy/gnome-extension`, `scripts/install_gnome_extension.sh`): D-Bus `org.tars.Windows` with only `List` (titles, app ids, geometry, focus) and `Activate`. `focus_window`, and `type_text`/`press_keys` with `window=` focus the app first and re-check before typing. `sync_tasks` = focus Super Productivity + Ctrl+S.
> - **Evals with 43 tools:** 30/30 everyday (incl. fix-a-bug, check-a-file, PDF, VS Code, reminder, play a song, Termius) + 7/7 safety, median 1.8 s.
> - **Pointer input** (same portal session, approved once): exact clicks without screen-casting by pushing the pointer into the top-left corner and moving relatively (virtual pointers get no acceleration); positions come from the GNOME extension.
> - **Spotube, any song:** focus → Search → type → right-click the top result → "Play next" → Next, confirmed over MPRIS (7.4 s; "Play next" keeps your queue, a plain click asks to clear it). Live: "Believer", "death bed by Powfu". **Super Productivity sync** verified live after re-login.
> - **Next: the kill switch and control border, and live Outlook drafting in Firefox (TARS).
- `tars-desktop`: AT-SPI snapshot, act, find and events; compact format; focus scoping; change diffs.
- firefox-devtools-mcp attached to your real Firefox (plus the launcher script), the headless Playwright browser for background work, the AT-SPI fallback for Firefox, tmux terminal, and the VS Code extension.
- Vision fallback: YOLO + OCR + Set-of-Mark, the projector path, and the grounder swap via llama-swap.
- The Wayland input path (RemoteDesktop portal with a restore token), screenshots via portal/ScreenCast, and the TARS GNOME Shell extension for windows.
- Cooperative control, the kill switch and the control border.
- **Exit:** desktop and browser evals ≥ 65%; "explain the error on my screen" works in the terminal, VS Code and Firefox.

### Phase 4 — Multi-agent, recursion, skills (3 weeks)
- The Conductor, Planner, specialists and Verifier; `delegate`; question bubbling; budgets; loop detection.
- Per-role prefix caching with slots.
- Skill capture, replay and fallback; teach-by-demonstration v1.
- A UI task-tree view.
- **Exit:** long tasks (8–15 steps) ≥ 55%; tasks that have a skill ≥ 90% and at least 3× faster than a first run.

### Phase 5 — Capabilities (4 weeks)
- Researcher: SearXNG, deep research, citations, local document index.
- Comms: **Outlook web** (college Microsoft 365) triage, summarize, draft in the compose box, approve, send, with skills for each.
- Site profiles: your list of websites and what you use each for becomes curated site skills.
- Cloud escalation: `tars-cloud` adapter, the redaction pipeline, spend cap and call log.
- Forms: the vault, field mapping and review card.
- Coder/Debugger with tmux, the VS Code extension, the sandbox and patch application.
- The dual-LLM injection defense on all untrusted content.
- **Exit:** category evals ≥ 65%; the injection suite is refused 100% of the time.

### Phase 6 — Proactive Sentinel (2 weeks)
- Sources, YAML rules, the attention manager, digests and schedules; `tars` as an MCP server.
- **Exit:** a week of daily use with fewer than 1 unwanted interruption a day and no missed urgent events from sources you configured.

### Phase 7 — Hardening and learning (ongoing)
- Fine-tune on traces, packaging (install script plus systemd units), backup and restore of memory, and optional cloud escalation behind a switch.

**Total:** about 18–20 weeks part-time to reach a genuinely useful daily-driver agent. Phases 0–3 (about 8 weeks) already beat v1 on every axis.

---

## 17. What it will feel like: example flows

**(hold PTT) "Reply to Rahul's latest mail saying I'll send the report by Friday."**

1. The fast path doesn't match, so the request goes to the Conductor, which delegates to **Comms**.
2. Comms has the web operator open your Outlook tab in Firefox and find Rahul's latest thread (T0). Rahul is resolved in the people graph, and the thread goes to the blackboard as `email/881`.
3. Scout summarizes the untrusted body on CPU, producing a 2-line summary and the reply-to address.
4. Comms retrieves your 3 past replies to Rahul as style examples, drafts the reply, and types it into Outlook's Reply box (T1).
5. The Conductor speaks: "Draft to Rahul: 'Hi Rahul, I'll share the report by Friday. Thanks!' Send it?" The approval card appears.
6. You hold PTT and say "send it". It clicks Send (T3), verifies the Sent folder, and the avatar nods.

About 30–60 s the first time, narrated as it goes. After it becomes a skill, about 8–15 s, mostly Outlook's own page loads.

**"Why is my build failing?"**
The Conductor delegates to the **Coder**. It reads the tmux pane and finds `ModuleNotFoundError: gpu_lock`, locates `core/voice_engine.py:25`, and runs the failing command in the sandbox. It proposes the diff `from core.gpu_lock import GPU_LOCK`, shows it in VS Code, applies it when you approve, and re-runs the command. "Fixed. It starts now."

**"Fill this internship form with my details."**
The Web operator snapshots the form in Firefox (element UIDs) and maps its 14 fields to vault keys. Two are ambiguous, so it asks "Which resume, the ML one or the general one?". It fills the fields and shows a review card with one missing field highlighted. You answer by voice, confirm, and it submits (T3) and saves a screenshot of the confirmation.

**"Research the best budget laptop cooling pads available in India, and give me the top 3."**
The Researcher runs 3 sub-queries, fetches 12 pages in parallel, and Scout summarizes each one on CPU. The Brain synthesizes a table with prices and citations. TARS speaks the top 3 and puts the table in chat.

**Unprompted, at 2:14 pm:**
"CI failed on tars main, a ruff error in brain.py. Want me to look?" This comes from the GitHub monitor, a Sentinel rule, and the attention manager deciding you aren't in a meeting.

**"Watch me, this is how I check CI and grab the build log on GitHub."**
TARS records your clicks through the browser and AT-SPI events, generalizes them into a skill, and confirms back to you. Next time, "get me the failing CI log" runs in about 5 s. (Your college sites are blocked, so demonstrations there are refused.)

---

## 18. Honest limits and risks

| Risk | Mitigation |
|---|---|
| A 4B model is unreliable on long, novel tasks | Structure-first perception, constrained outputs, verification, skills, re-planning, fine-tuning on your traces, optional cloud escalation |
| Speed: novel tasks take 30–90 s | Fast path, skills, prefix caching, progress narration so waiting feels OK |
| Poor accessibility coverage (canvas apps, games, some Electron apps, Google Docs canvas) | The vision fallback and the grounder; accept lower success there |
| VRAM is too tight for 4B plus vision | IQ4_XS quant, projector on CPU, or Qwen3.5-2B as the Brain; decide from Phase 0 numbers |
| **Battery power (measured):** unplugged, the GPU drops to P5 (660 of 1785 MHz) and the Brain decodes at **~5 tok/s instead of ~36** | The Sentinel detects AC/battery. **Battery mode:** fast path and skills first, shorter replies, the Scout (CPU) for summaries, and cloud escalation offered sooner for long tasks. A proper benchmark of this mode is still to do |
| WhatsApp or Instagram automation against terms of service | Web UI automation at human pace, always with approval; no bulk actions |
| Firefox remote-control port is a local attack surface while it's open | Localhost only; started only by the TARS launcher; TARS can close the port when idle; AT-SPI fallback |
| Redaction misses some PII before cloud calls | Conservative masking, call log review, per-category "ask me each time" option, offline switch |
| Accent-related STT misses | Model chosen on your voice, hotwords, entity correction, an easy "no, I said…" correction path |
| Prompt injection through mail and web | Taint tracking, dual-LLM, T3 always confirmed, destinations only from you |
| Wayland restrictions (no global input or window control without portals and consent prompts) | Portals are designed in from Phase 1 (PTT) and Phase 3 (input, screenshots). Consent is granted once and remembered with restore tokens. The GNOME extension covers windows. AT-SPI semantic actions need none of this |
| Scope creep | Phase exit criteria gated by evals; don't start Phase N+1 until Phase N passes |

---

## 19. Decisions

**Made (2026-09-30):**

| Topic | Decision |
|---|---|
| Name | **TARS**, with humor and honesty sliders; the repo becomes `tars` |
| Browser | **Firefox**, via Mozilla's firefox-devtools-mcp attached to your real session |
| Mail | **Outlook web in Firefox**: read → draft in the compose box → wait for approval → send |
| Listening | **Push-to-talk** (wake word later) |
| Language | **English, tuned for Indian English** |
| Avatar | **Live2D 2D**, starting from an official sample model |
| Cloud | **Allowed for hard and research tasks; content with PII redacted**; provider decided later |

| Outlook account | College Microsoft 365, already logged in (`outlook.office365.com/mail/`) |
| Messaging | WhatsApp Web is used, but TARS replying there is **out of scope for now** |
| Avatar model | **Mao (Niziiro Mao PRO)** Live2D sample; swap any time |

**Still open (none of these block Phase 0):**
1. Cloud provider and monthly budget. The adapter is provider-neutral, so this can wait.
2. **Your website list** (which sites you use for what). It becomes curated site skills and fast-path intents.
