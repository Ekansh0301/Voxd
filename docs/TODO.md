# Decisions and to-dos

Everything that's waiting on you, plus the work queued next. Updated 2026-10-23.
Tick things off here as you go; progress against the plan is in [STATUS.md](STATUS.md).

## Decisions to take

| # | Decision | Options | Notes |
|---|---|---|---|
| 1 | **Cloud model for hard tasks** | a provider (Anthropic, OpenAI, Google, …) with an API key, or keep using web AIs only | Web AIs (`ask_ai`) already cover this with personal details removed. An API would add a spending cap, a call log and redaction ([PLAN.md](PLAN.md) §12.5). |
| 2 | **AI Humanize** | sign in and let TARS try again, or drop it | Signed out, the site only inserted typos ("Reneuwable", "heolp") instead of rewriting, so it wasn't automated. The 200-word splitter is ready (`tars/text_chunks.py`). |
| 3 | **Helper agents (Phase 4)** | skip (proposed), or build anyway | Switching between specialist prompts costs ~10 s each on this GPU; the single agent already meets the long-task target. |
| 4 | **Teach-by-demonstration (Phase 4)** | defer (proposed), or build | Routines taught by voice cover most of it; watching your clicks only works in apps that report them. |
| 5 | **Spotube Connect** | leave off (current), or turn on | On: faster for liked songs, but Spotube then listens on the whole network with no password, so it needs a firewall rule on hostel Wi-Fi. Off works fine via search. |
| 6 | **Microphone level** | keep 100% (your choice for now), or lower to ~45% | At 100% the built-in mic clips (16% of samples in the 2026-10-12 session) and speech gets misheard ("Demogorgon", "Stay London"); TARS warns at start-up. `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 45%` |
| 7 | **What to build next** | Outlook drafting, or Phase 6 (proactive alerts) | Outlook was deferred by you; Phase 6 is the last new phase. |

## Things to do (once)

- [ ] **Write your profile** for forms and redaction: `~/.config/tars/profile.yaml` (name,
      email, phone, roll_number, college…; never passwords). Format in [SETUP.md](SETUP.md) §10.
- [ ] **Record your voice set** for choosing the speech model:
      `.venv/bin/python -m bench.record_commands`, then `.venv/bin/python -m bench.stt_bench`.
      Only 8 test clips exist so far.
- [ ] **Reload open VS Code windows** (Command Palette → *Developer: Reload Window*) so the
      TARS bridge extension starts in them. New windows load it by themselves.

- [ ] **Restore your Firefox tabs** if you haven't: *History → Restore Previous Session* (they
      were dropped when Firefox was closed for a test on 2026-10-12; TARS now restores them
      itself whenever it starts Firefox).
- [ ] **Empty the Trash** to get back ~6.5 GB (unused models and the v1 prototype's files).
- [ ] Optional: once you're happy with GitHub's history, delete the backups
      `git branch -D backup/before-message-rewrite` and
      `git tag -d backup/v1-prototype-before-rewrite`; and `git branch -f main tars-phase0`.

Already done: push-to-talk service, GNOME extension, screenshot permission, keyboard and
mouse approval, VS Code extension, `tars` command and app icon, Super Productivity's REST API,
accessibility on, Flameshot's own screenshot permission, CUDA 12 libraries in `.venv`,
TARS published on GitHub `main` (v1 kept at tag `v1-prototype`).

## Things to try and report back

- [ ] **Tap Right Ctrl** while TARS is in the middle of a task: it should stop at once and
      say "Stopped". (Only the menu and typed "stop" were tested; I can't press your key.)
- [ ] **"Connect to ada in Termius"**: does one press connect, or only select the host?
- [ ] **A taught routine**, e.g. "make a routine called study mode that opens my project in
      VS Code and plays my phonk playlist", then "study mode".
- [ ] **"Fill in this form"** on a real form, after writing your profile.
- [ ] **Ask ChatGPT something** with your normal Firefox open: TARS should offer to restart it
      (say yes; your tabs come back). If ChatGPT shows "verify you are human", complete it
      yourself, then ask again. The full ask-and-read path is still untested since ChatGPT
      started showing that check.
- [ ] **Spotube "play Believer"** with Spotube maximised: the click on the result missed once;
      say yes when you're happy for me to test it live (it plays music briefly).
- [ ] **Files and lines:** "explain line 40 to 45 of …", "and line 60?". TARS now reads the
      lines before answering; tell me if it still guesses.
- [ ] Anything TARS mishears or gets wrong: paste the terminal lines (`you : …`, `· tool(…)`),
      or run `tars --save-audio` for a few phrases.

## Queued work (for me)

1. **Outlook web** (Phase 5, deferred): triage, summarise, draft in the compose box, wait for
   your approval, send.
2. **Phase 6, proactive monitoring:** new important mail, CI failures, low battery or disk,
   reminders; rules for when not to interrupt; TARS as an MCP server.
3. **Phase 7, polish:** one-step installer, backup and restore of memory and routines,
   tuning on your own usage.
4. **Leftovers:** speech model choice (after your recordings), voice barge-in (needs echo
   cancellation), cloud API (after decision 1), AI Humanize (after decision 2).

## Known limits to keep in mind

- The 4B model sometimes misreads an ambiguous follow-up ("and YouTube") or follows text
  planted in a file (about 1 run in 11); the approval question still catches the second.
- Spotube automation needs its window maximised; GTK 4 popup menus aren't readable.
- Reminder alarms don't survive a reboot (they're systemd user timers).
- The system prompt and 68 tool descriptions take ~6,100 of the model's 10,240 tokens, so a
  turn has ~3,700 left for history and file contents; every new tool shrinks that.
- ChatGPT can sit on Cloudflare's "verify you are human" page in Firefox (TARS); TARS reports
  it and never completes it for you.
- After an NVIDIA driver update the first answer is slow once (~1 min) while GPU code is
  recompiled.
