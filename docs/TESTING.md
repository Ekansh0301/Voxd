# Testing TARS

Five suites, from fast and fake to slow and real.

| Command | What it checks | Needs | Time |
|---|---|---|---|
| `.venv/bin/python -m pytest` | unit tests: policy, parsing, tools in dry-run, matching, budgets | nothing | ~10 s |
| `.venv/bin/python -m evals.agent_eval` | the real model on 51 everyday tasks (6 of them long, 5–9 steps) and 7 safety tasks, in a throwaway home folder; desktop actions are recorded, not done | GPU | ~3 min |
| `.venv/bin/python -m evals.screen_eval` | "explain the error on my screen" in a terminal, a VS Code file, VS Code's terminal and Firefox | GPU, your desktop | ~1 min |
| `.venv/bin/python -m evals.skill_eval` | learned routines: each task once (learned), then variants that replay it; correctness and speed-up | GPU, your desktop | ~3 min |
| `.venv/bin/python -m evals.live_eval` | 12 real-app tasks checked on the real result (Calculator, Okular, VS Code, Super Productivity, volume, ChatGPT, research, Spotube…) | GPU, your desktop, the apps | ~5 min |

The three desktop evals open windows on your screen, ask ChatGPT a few questions,
and play a song briefly. They put things back afterwards (volume, paused music,
Super Productivity's view) and close only windows they opened. Add `-k name` to run
some tasks only. Results are written to `evals/results/` (git-ignored).

The evals start the model server themselves. Run them **plugged in**.

## Latest results

| Suite | Result |
|---|---|
| Unit tests | all pass |
| Agent eval | 49–51/51 everyday across runs (long tasks 6/6), 7/7 safety, median 2.2 s per task |
| Screen eval | 4/4 |
| Live eval | 11/12 (92%); target ≥ 65% |
| Routine replays | 4/4 correct; desktop task 3.4–3.5× faster, ChatGPT questions 1.3–1.5× (its own answer time dominates) |

The 4B model isn't perfectly consistent, so a single run can drop a task (for
example a one-off injection slip, about 1 run in 11, which the approval question
still catches). Tasks that fail repeatedly point to a real bug.

## Benchmarks

The model comparisons need the candidates: `bash scripts/setup.sh --bench-models`.
`bench/on_ac.sh` waits for the charger, then reruns the power-sensitive benchmarks.

```bash
.venv/bin/python -m bench.llm_bench          # models: VRAM, speed, tool-choice accuracy
.venv/bin/python -m bench.record_commands    # record your own voice set, then:
.venv/bin/python -m bench.stt_bench          # speech recognition word error rate
.venv/bin/python -m bench.tts_bench
.venv/bin/python -m bench.report             # regenerates docs/BENCHMARKS.md
```

## CI

GitHub Actions runs ruff, black, mypy and the unit tests on every push
([.github/workflows/ci.yml](../.github/workflows/ci.yml)). The evals can't run there:
they need the GPU, the models and a desktop. Before committing:

```bash
.venv/bin/ruff check . && .venv/bin/black --check . && .venv/bin/mypy tars bench tests && .venv/bin/python -m pytest
```

After changing a tool, regenerate its reference: `.venv/bin/python scripts/gen_tools_doc.py`.
