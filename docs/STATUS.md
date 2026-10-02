# Status

Where TARS stands against the roadmap in [PLAN.md](PLAN.md) §16. Updated 2026-10-02 (night).

| Phase | | |
|---|---|---|
| 0. Foundation and measurement | ✅ done | models chosen by benchmark ([BENCHMARKS.md](BENCHMARKS.md)) |
| 1. Voice and avatar | ✅ done (one item open) | key release → first speech ~1.6 s; STT model choice waits for your recordings |
| 2. Agent core and MCP | ✅ done | tools, policy, approvals, memory |
| 3. Screen reading and control | ✅ done | live eval 11/12 (target ≥ 65%) |
| 4. Multi-agent, recursion, skills | ✅ routines done; helper agents proposed to skip | long tasks 6/6, routine replays 4/4 |
| 5. Capabilities (mail, forms, cloud) | ✅ mostly done; Outlook later | web AIs, research, documents, site shortcuts, forms, patches |
| 6. Proactive monitoring | not started | |
| 7. Hardening and learning | ongoing | |

## Phase 0: foundation

- The v1 blockers fixed; repo, config, tests and CI set up; llama.cpp and llama-swap
  installed, with Ollama off the critical path.
- **Brain: Qwen3.5-4B Q4_K_M** on the GPU (~37 tok/s, 92% tool choice on 60 commands).
  llama.cpp needs the Pascal/MMQ kernel build on this GPU (3× faster prefill).
- **Speech:** Whisper `small.en` on the GPU (0.5 s); **voice:** Kokoro `af_heart`.

## Phase 1: voice and avatar

- Push-to-talk on Wayland through `tars-pttd` (Right Ctrl only), streamed speech,
  interrupting with the key, personality commands ("humor 40%").
- Live2D avatar (Mao) on the official Cubism 5 framework in a transparent overlay,
  with lip-sync, subtitles and a text box.
- **Open:** choosing the speech model from your own recordings; voice barge-in
  (needs echo cancellation).

## Phase 2: agent core

- Native tool calling, streamed so speech starts early; loop detection; context
  budgeting for long tasks; prompt-cache priming (first token ~0.35 s).
- Permission tiers and a policy engine in code; bubblewrap sandbox; spoken approvals.
- SQLite memory with full-text search; a fast path for unambiguous commands; an MCP client.
- Built-in tools instead of separate MCP servers (lower latency); embeddings deferred.

## Phase 3: screen reading and control

- **Reading:** accessibility trees with unique element names, change reports after
  actions, screenshots with vision, OCR, tmux terminals, VS Code through its own
  extension, your Firefox's DOM.
- **Acting:** AT-SPI actions; keyboard and mouse through the RemoteDesktop portal;
  window focus through the TARS GNOME extension; exact clicks without screen-casting.
- **Firefox:** your real Firefox (TARS) with site rules; ChatGPT and other AI sites
  (type, send, read the answer); a hidden headless Firefox for research.
- **Your apps:** Spotube (songs and playlists), Super Productivity (reminders, tasks,
  sync), Termius, VS Code, Okular, Ghostty.
- **Control:** kill switch (tap Right Ctrl), orange control border, top-bar menu.
- **"Explain the error on my screen"** works in the terminal, VS Code (editor and
  terminal) and Firefox: the phase's exit test.
- **Not done, by choice:** the Playwright browser (the headless Firefox does the job
  with no new install), YOLO/Set-of-Mark detection (OCR + vision boxes were enough),
  and a separate `tars-desktop` MCP server.

## Phase 4: learned routines

- **Learned routines:** a successful multi-step task is saved with the words of the
  request as slots, and replayed for a matching request: the steps run directly
  (same policy and approvals), the model only writes the answer or takes over after
  a failed step. Saved only when safe: no paraphrased or request-derived values, no
  content edits. Retired after repeated failures.
- **Taught routines:** "make a routine called study mode that…", run by saying its name.
- **Task view:** the window lists each step live (running, done, failed, replayed).
- **Results:** long tasks 6/6 (target ≥ 55%); routine replays 4/4 correct (target ≥ 90%),
  3.4–3.5× faster for a desktop task (target ≥ 3×), 1.3–1.5× for ChatGPT questions,
  where ChatGPT's own answer time dominates.
- **Proposed to skip** (your call): the Conductor with specialist agents, and per-role
  prompt caches. On this GPU there is one prompt cache, and each role's ~4k-token prompt
  takes ~10 s to load, so switching roles would cost far more than it saves; the single
  agent already passes the long-task target. Teach-by-demonstration (recording your
  clicks) is also deferred: taught-by-voice routines cover most of it, and recording
  only works in apps that expose accessibility events.

## Phase 5: capabilities (Outlook later, by choice)

- **Web AIs instead of an API:** `ask_ai` types the question into ChatGPT (then Gemini,
  Claude, AI Studio) in your Firefox and returns the answer. Personal details are
  swapped for placeholders before sending and swapped back after (`tars/privacy.py`).
- **Research:** `deep_research` reads the top results (plain HTTP first, the hidden
  browser for script-built pages, in parallel) and returns cited passages; ~12 s.
  `search_documents` searches your notes and PDFs (SQLite full-text index).
- **Site shortcuts** in `config/sites.yaml`: YouTube search/play, GitHub, LeetCode,
  QuickRef, LinkedIn; "play X on YouTube" is on the fast path.
- **Forms:** `fill_form` from `profile.yaml`, review, never submits or fills secrets.
- **Coding:** `apply_patch` (multi-file, dry run, approval, grouped undo) and
  `search_code` for renames across files.
- **Results:** agent eval 51 tasks, 96–100% across runs, every Phase 5 area covered
  (target ≥ 65% per area).
- **Not done:** Outlook (later); a cloud model API (needs your choice of provider; web
  AIs cover it for now); AI Humanize (signed out, the site only inserted typos, so
  automating it would hurt your text); a pattern-based injection detector.

## Waiting on you

The decisions and one-time steps waiting on you are kept in [TODO.md](TODO.md).

## Known limits

- The 4B model sometimes slips on long button sequences or follows planted text;
  typing instead of clicking and the "careful" approval cover the main cases.
- Spotube automation depends on its window layout (maximised).
- GTK 4 popup menus and some apps' contents aren't exposed to accessibility.
