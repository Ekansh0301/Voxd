# TARS

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Ubuntu 26.04](https://img.shields.io/badge/platform-Ubuntu%2026.04%20Wayland-orange.svg)](#hardware)
[![CI](https://github.com/Ekansh0301/Voxd/actions/workflows/ci.yml/badge.svg)](https://github.com/Ekansh0301/Voxd/actions/workflows/ci.yml)

A local, hands-free desktop agent for Ubuntu that runs on a laptop with a
4 GB GTX 1650. You hold a key and talk. TARS reads the screen through real UI
structure (accessibility trees and the browser DOM, not just OCR), plans the
steps, operates your apps and your logged-in Firefox, and speaks back through
a Live2D avatar. It waits for your approval before anything irreversible, such
as sending mail or submitting a form.

Everything runs on-device by default. Cloud models are an opt-in fallback for
hard tasks, and anything sent to them has personal details redacted first.

> **Status: Phase 2 (agent core) working.** Hold Right Ctrl and talk. TARS answers in
> Kokoro (`af_heart`) about 1.7 s after you let go, while a Live2D avatar (Mao)
> listens, thinks and lip-syncs. It now **acts**: files (list, find, read, create,
> move, copy, trash), sandboxed shell commands, apps and websites, volume, media,
> timers, system status and memory. Phase 3 adds screen reading (accessibility
> tree, with vision as fallback), your real Firefox, your apps (Okular, VS Code,
> Ghostty, Super Productivity reminders…) and coding aids (check, fix, undo). It
> **asks out loud before anything risky** (your next push-to-talk "yes/no" decides).
> Agent evals: **27/27 everyday tasks, 7/7 safety cases**. The v1 prototype in [`legacy/`](legacy/) still runs
> in the meantime. See [docs/PLAN.md](docs/PLAN.md) for the design and roadmap.

---

## What it is being built to do

- **Talk:** push-to-talk, speech recognition tuned on your own (Indian English)
  recordings, streamed replies with Piper TTS, and interruption by pressing the key.
- **See the screen for real:** AT-SPI accessibility trees for desktop apps, the
  DOM of your real Firefox session, tmux for terminals, and a vision model as the fallback.
- **Act like an agent:** a Conductor delegates to specialist agents (desktop,
  web, research, mail, coder). Each one plans, acts, checks the result and
  re-plans, recursively and within budgets.
- **Work with your sites:** Outlook web (read → draft → *you approve* → send),
  GitHub, YouTube, AI chat sites, and AI Humanize with automatic 200-word
  chunking. Access is per site: your college sites are blocked outright. See
  [config/sites.yaml](config/sites.yaml).
- **MCP everywhere:** TARS is an MCP client for tool servers and an MCP server
  itself, so other tools can use its voice and screen.
- **Learn routines:** successful tasks become replayable skills, and you can
  teach one by demonstration.
- **Watch in the background:** system, mail and CI monitors, with an attention
  manager so it doesn't interrupt meetings.

## Hardware

Designed and measured on an HP Victus 16: i5-11400H, 16 GB RAM, GTX 1650
Mobile with 4 GB (3714 MiB usable by CUDA), and the desktop rendered on the
Intel iGPU (PRIME on-demand), Ubuntu 26.04 LTS with GNOME 50 on Wayland. The Phase 0 measurements are in
[docs/BENCHMARKS.md](docs/BENCHMARKS.md):

| | Measured |
|---|---|
| Brain: Qwen3.5-4B Q4_K_M on the GPU | 3.05 GB VRAM, **~37 tok/s**, ~460 tok/s prefill, **92%** tool choice on 60 test commands |
| Cached 2,500-token prompt | ~0.1 s (6 s uncached) |
| Scout: Qwen3.5-0.8B on the CPU only | 0 VRAM, 27–32 tok/s, runs beside the Brain without slowing it |
| Screen read through the vision projector (CPU, 256 image tokens) | ~1 s warm |
| Kokoro TTS (`af_heart`, fp32, CPU), first chunk | 0.7–0.9 s |
| Whisper small.en on the GPU, beside the Brain | ~0.55 s; 3.55 of 3.71 GB VRAM in total |
| **Key release → first spoken audio** | **~1.7 s** |
| **On battery** | the GPU drops to P5 and the Brain to ~5 tok/s, so plug in for agent work |

Two findings that matter on this GPU:
- llama.cpp must be built with the Pascal/MMQ kernel path (`scripts/setup.sh`
  does this). The default build prefills 3× slower on GTX 16-series cards.
- The GPU is throttled hard on battery.

## Setup

```bash
git clone https://github.com/Ekansh0301/Voxd.git tars && cd tars
bash scripts/setup.sh          # llama.cpp (CUDA), llama-swap, models (~12 GB), .venv
bash scripts/gen_llama_swap.sh # writes ~/.config/tars/llama-swap.yaml
~/.local/share/tars/opt/bin/llama-swap --config ~/.config/tars/llama-swap.yaml --listen 127.0.0.1:8090
```

Then install the `tars` command and the TARS app entry (icon in the app grid):

```bash
bash scripts/install_launcher.sh
tars                           # or click TARS in the app grid
```

While it runs, a TARS icon sits in the top bar (Type a message, Show/hide
avatar, Quit TARS). Hold Right Ctrl to talk, or type in the box under the
avatar; subtitles under the avatar show what it heard and what it is saying.

This needs Ubuntu with an NVIDIA driver and the CUDA toolkit (`nvcc`), Python
3.11, cmake, and about 15 GB of disk. Models and binaries go to
`~/.local/share/tars/`, never into the repo. The setup script is idempotent
and resumes interrupted downloads.

Talk to it:

```bash
sudo bash scripts/install_pttd.sh            # once: Right Ctrl push-to-talk (read the script first)
.venv/bin/python -m tars.voice               # hold Right Ctrl, speak, release
.venv/bin/python -m tars.voice --ptt stdin   # or: Enter to start/stop, no install needed
```

The avatar window opens with it: a transparent, always-on-top Live2D overlay.
Drag it with the left mouse button; right-click to hide or quit it, or start
with `--no-avatar`. Live2D's licence requires you to download two files
yourself, accepting their terms: the [Cubism SDK for Web](https://www.live2d.com/en/sdk/download/web/)
and the [Mao sample](https://www.live2d.com/en/learn/sample/). Put both zips in
`~/Downloads` and `scripts/setup.sh` unpacks them and builds the avatar app
(`python -m tars.ui.live2d.build`) on the official Cubism 5 framework. None of
Live2D's files enter this repo.

`tars-pttd` is a small sandboxed system service that watches only the
push-to-talk key and reports nothing else. That's why you don't need to join the
`input` group, which would let every program read every keystroke.

```bash
.venv/bin/python -m pytest                  # TARS unit tests
.venv/bin/python -m bench.llm_bench          # LLM benchmarks (GPU)
.venv/bin/python -m bench.record_commands    # record your voice set, then:
.venv/bin/python -m bench.stt_bench
.venv/bin/python -m bench.report             # regenerate docs/BENCHMARKS.md
```

## Repository layout

```
tars/          TARS package (llama-server wrapper, GPU helpers, site policy, text chunking; grows each phase)
tests/         TARS unit tests
bench/         Phase 0 benchmarks, labelled test data, results (JSON)
config/        sites.yaml (per-site access rules)
deploy/        llama-swap config template
scripts/       setup.sh, gen_llama_swap.sh, bench_on_ac.sh
docs/          PLAN.md (design and roadmap), BENCHMARKS.md (measurements)
legacy/        v1 prototype (Flash/Vox), kept runnable until TARS reaches parity
```

Environments: `.venv/` is TARS (numpy 2). `venv/` is the v1 prototype
(numpy 1, torch, ChromaDB) and is used only by `legacy/`.

## Privacy and safety

Built so far (Phase 2); the rest of [docs/PLAN.md](docs/PLAN.md) §12 comes later:
- **Permission tiers** on every tool. Read-only runs immediately; local reversible
  actions are logged; anything destructive asks you out loud first.
- **Shell commands are classified in code**, not by the model. `sudo`, disk tools,
  pipe-to-shell and `rm -rf ~` are refused outright; read-only commands and pipelines
  run in a **bubblewrap sandbox** (read-only, no network); everything else asks first,
  then runs sandboxed with a writable home. Secret folders (`~/.ssh`, keyrings,
  browser profiles, `.env`…) are hidden even inside the sandbox.
- **Files:** writes stay in your home folder; deleting goes to the **Trash**.
- **Tool output is labelled as data**; the injection eval (a file telling TARS to
  trash Documents) is ignored.
- Per-site rules: your college sites are blocked outright.

- Local by default. Cloud escalation is opt-in, PII-redacted, logged and capped.
- The microphone listens only while you hold the push-to-talk key.
- Permission tiers: sending, submitting, posting, purchasing and deleting
  always wait for your explicit approval.
- Text from web pages and mail is treated as data, never as instructions.
  Shell commands run in a sandbox, and holding Esc stops everything.

## License

MIT. See [LICENSE](LICENSE).
