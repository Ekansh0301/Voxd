# TARS

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Ubuntu 26.04](https://img.shields.io/badge/platform-Ubuntu%2026.04%20Wayland-orange.svg)](docs/SETUP.md)
[![CI](https://github.com/Ekansh0301/Voxd/actions/workflows/ci.yml/badge.svg)](https://github.com/Ekansh0301/Voxd/actions/workflows/ci.yml)

A local, hands-free assistant for an Ubuntu laptop with a 4 GB GTX 1650. Hold a key
and talk, or type. TARS reads your screen through real UI structure (accessibility
trees, your browser's page, your terminal), works out the steps, operates your apps
and your logged-in Firefox, and answers out loud through a Live2D avatar. It asks
before anything risky, and everything runs on the laptop.

**Status:** Phases 0–4 of the [plan](docs/PLAN.md) are done, and Phase 5 apart from Outlook ([STATUS.md](docs/STATUS.md)).
On real apps it completes 11 of 12 live test tasks; first speech comes ~1.6 s after
you let go of the key.

## What it can do now

- **Talk or type:** push-to-talk on Right Ctrl, Whisper speech recognition on the GPU,
  Kokoro voice, subtitles, a text box, a top-bar menu.
- **See your screen:** accessibility trees, your Firefox's page, tmux terminals, VS Code
  through its own extension; OCR and vision for apps that expose nothing.
- **Use your computer:** files (deleting goes to the Trash), sandboxed commands,
  keyboard and mouse, windows, volume, media, timers, memory.
- **Your apps:** VS Code, Okular, Ghostty, Termius ("connect to ada"), Super Productivity
  (reminders, tasks, sync), Spotube (any song, your playlists).
- **The web:** your Firefox (open, read, fill, click, with per-site rules), shortcuts
  for your sites (YouTube, GitHub, LeetCode, QuickRef), ChatGPT and other AI sites with
  your personal details removed, cited research in a hidden browser, form filling.
- **Your documents:** search your notes and PDFs.
- **Coding:** "explain the error on my screen", check code with linters, fix with a
  shown diff and approval, undo.
- **Learn routines:** a multi-step task that worked is replayed next time (about 3×
  faster for desktop tasks), and you can teach named routines ("study mode").
- **Stay in control:** tap Right Ctrl to stop at once; an orange border shows whenever
  TARS is clicking or typing, and the window lists each step as it happens.

Coming next: Outlook drafting (read → draft → you approve → send) and proactive
monitoring. See the [roadmap](docs/PLAN.md#16-roadmap).

## Quick start

```bash
git clone https://github.com/Ekansh0301/Voxd.git tars && cd tars
bash scripts/setup.sh                    # llama.cpp, models (~4.5 GB), Python env
bash scripts/gen_llama_swap.sh
bash scripts/install_launcher.sh         # the `tars` command and app icon
sudo bash scripts/install_pttd.sh        # Right Ctrl push-to-talk
bash scripts/install_gnome_extension.sh  # window focus; log out and in once
tars
```

A few one-time permissions (screenshots, keyboard and mouse, VS Code) are in
**[docs/SETUP.md](docs/SETUP.md)**, each with how to undo it.

## Documentation

| | |
|---|---|
| [SETUP.md](docs/SETUP.md) | Installing, and every permission TARS needs |
| [USAGE.md](docs/USAGE.md) | Talking, typing, stopping, and what to ask |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works: processes, a turn, seeing and acting |
| [SAFETY.md](docs/SAFETY.md) | What it refuses, what asks first, how to revoke access |
| [TOOLS.md](docs/TOOLS.md) | All 67 tools the model can use (generated) |
| [TESTING.md](docs/TESTING.md) | Unit tests, the three evals, benchmarks |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Problems met and their fixes |
| [TODO.md](docs/TODO.md) | **Decisions and to-dos waiting on you**, and the work queued next |
| [STATUS.md](docs/STATUS.md) | Progress against the plan |
| [PLAN.md](docs/PLAN.md) | The full design and roadmap |
| [BENCHMARKS.md](docs/BENCHMARKS.md) | Model, speech and voice measurements |

## Hardware

Built and measured on an HP Victus 16: i5-11400H, 16 GB RAM, GTX 1650 Mobile 4 GB
(3714 MiB usable), Ubuntu 26.04 with GNOME 50 on Wayland.

| | Measured |
|---|---|
| Brain: Qwen3.5-4B Q4_K_M on the GPU | ~37 tok/s, 92% tool choice on 60 commands, 3.05 GB VRAM |
| Speech recognition: Whisper small.en on the GPU | ~0.5 s |
| Voice: Kokoro `af_heart` on the CPU, first chunk | 0.7–0.9 s |
| First word of a reply (prompt cached) | ~0.35 s |
| Key release → first speech | ~1.6 s |

Plug in for agent work: on battery the GPU slows to about 5 tok/s.

## Repository layout

```
tars/          the assistant
  agent/       tool registry, permission tiers, command policy, agent loop
  tools/       the tools (files, shell, screen, apps, browser, research, ...)
  perception/  accessibility (AT-SPI), screenshots, keyboard/mouse, windows, VS Code
  voice/       push-to-talk, speech recognition and synthesis, the turn loop
  ui/          avatar window (subtitles, text box, top-bar icon, control border), Live2D build
  skills/      learned and taught routines
  llm/ mcp/ memory/  model server, MCP clients, long-term memory
config/        tars.yaml (voice, models, personality), sites.yaml, apps.yaml, mcp.json
deploy/        GNOME Shell extension, VS Code extension, pttd systemd units, templates
scripts/       setup and install scripts, the `tars` launcher, Firefox (TARS) launcher
evals/         agent, screen and live desktop evals
tests/         unit tests
bench/         model, speech and voice benchmarks (results in docs/BENCHMARKS.md)
docs/          documentation
```

`.venv/` is TARS's Python environment. The v1 prototype (Flash/Vox) was removed; it's in git
history at the tag `v1-prototype` (`git checkout v1-prototype -- legacy/` brings it back).
Models, binaries, memory and logs live in `~/.local/share/tars/`.

## License

MIT. See [LICENSE](LICENSE). Live2D's SDK and models are not included and have
their own licence.
