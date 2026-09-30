#!/usr/bin/env bash
# Wait until the charger is connected, then rerun the power-sensitive benchmarks
# (resident Brain+Scout, CPU-only Scout, TTS) and regenerate docs/BENCHMARKS.md.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
until [[ "$(cat /sys/class/power_supply/ADP1/online 2>/dev/null)" == "1" ]]; do sleep 30; done
echo "AC connected at $(date +%H:%M); letting clocks settle"; sleep 20
.venv/bin/python -m bench.resident_bench
.venv/bin/python -m bench.llm_bench -m qwen3.5-0.8b-cpu -t speed,cache,tools,json
.venv/bin/python -m bench.tts_bench
.venv/bin/python -m bench.report
