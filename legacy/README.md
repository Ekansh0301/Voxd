# Legacy: v1 prototype (Flash / Vox)

The original single-shot voice assistant: push-to-talk → faster-whisper → one
Ollama call with tools → Piper. It is kept runnable only as a baseline while
TARS (the rest of this repo) is built; delete this folder and the root `venv/`
once TARS reaches parity (Phase 2–3 in [docs/PLAN.md](../docs/PLAN.md)).

Phase 0 fixed its blocking bugs (startup import, first push-to-talk, broken
memory store, cross-thread Qt calls, the confirm dialog thread, a safety bypass
through chained commands, truncated replies, slow YouTube playback).

```bash
legacy/scripts/launch.sh            # tray mode; needs Ollama with qwen2.5:3b
venv/bin/python legacy/flash_copilot.py
```

- Config: `legacy/config/config.json` (copy from `config.json.example`).
  `voices_dir` points at `~/.local/share/tars/models/tts/piper`.
- Runtime files kept here and gitignored: `piper_bin/`, `data/`, `flash_copilot.log`.
- **Wayland caveat (Ubuntu 26.04):** v1's pynput push-to-talk and xdotool actions only reach XWayland apps; native Wayland windows don't see them. The chat window (Ctrl+Space) still works.
- Tests (need PyQt6, i.e. the v1 `venv/`): `venv/bin/python -m pytest legacy/tests`
