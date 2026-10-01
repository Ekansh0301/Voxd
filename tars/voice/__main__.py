"""
Talk to TARS (Phase 1, voice only):

    .venv/bin/python -m tars.voice              # push-to-talk via tars-pttd (Right Ctrl)
    .venv/bin/python -m tars.voice --ptt stdin  # Enter to start/stop, no install needed

Starts llama-swap (Brain + Scout) automatically if it isn't already running.
"""

import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from tars.cuda import reexec_with_cuda_libs

reexec_with_cuda_libs("tars.voice")  # before anything loads CTranslate2

from tars import BIN_DIR
from tars.config import load
from tars.llm.client import is_up, stream_chat
from tars.ui.bus import UiBus
from tars.voice.ptt import pttd_events, stdin_events
from tars.voice.service import VoiceService

SWAP_CONFIG = Path.home() / ".config" / "tars" / "llama-swap.yaml"


async def warm_up(endpoint: str, model: str):
    """llama-swap loads a model on first use (~3-7 s); do that before the first turn."""
    async for _ in stream_chat(endpoint, model, [{"role": "user", "content": "hi"}], max_tokens=1):
        pass


async def ensure_llm(endpoint: str) -> subprocess.Popen | None:
    if await is_up(endpoint):
        return None
    if not SWAP_CONFIG.exists():
        raise SystemExit("No LLM server: run `bash scripts/gen_llama_swap.sh` first.")
    listen = endpoint.split("//")[1].split("/")[0]
    log_file = open(Path.home() / ".local" / "share" / "tars" / "llama-swap.log", "w")
    proc = subprocess.Popen(
        [str(BIN_DIR / "llama-swap"), "--config", str(SWAP_CONFIG), "--listen", listen],
        stdout=log_file, stderr=subprocess.STDOUT,
    )  # fmt: skip
    for _ in range(60):
        if await is_up(endpoint):
            return proc
        await asyncio.sleep(0.5)
    proc.terminate()
    raise SystemExit("llama-swap did not start; see ~/.local/share/tars/llama-swap.log")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ptt", choices=["pttd", "stdin"], default=None)
    ap.add_argument("--no-avatar", action="store_true", help="don't open the Live2D window")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S",
    )  # fmt: skip
    cfg = load()
    swap = await ensure_llm(cfg["llm"]["endpoint"])
    bus = UiBus()
    await bus.start()
    avatar = None
    if cfg["voice"].get("avatar", True) and not args.no_avatar:
        avatar = subprocess.Popen([sys.executable, "-m", "tars.ui", "--ws", bus.url])
    try:
        await warm_up(cfg["llm"]["endpoint"], cfg["llm"]["brain"])
        service = VoiceService(
            cfg, on_state=lambda state, info: bus.publish({"type": "state", "state": state, **info})
        )
        mouth = asyncio.create_task(service.mouth_loop(bus.publish))
        source = args.ptt or cfg["voice"]["ptt"]["source"]
        events = stdin_events() if source == "stdin" else pttd_events(cfg["voice"]["ptt"]["socket"])
        await service.run(events)
        mouth.cancel()
    finally:
        if avatar:
            avatar.terminate()
        await bus.close()
        if swap:
            swap.terminate()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
