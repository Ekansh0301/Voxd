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

from tars.config import load
from tars.cuda import reexec_with_cuda_libs
from tars.llm.swap import ensure_llm, warm_up
from tars.mcp.manager import MCPManager
from tars.tools import browser
from tars.ui.bus import UiBus
from tars.voice.ptt import pttd_events, stdin_events
from tars.voice.service import VoiceService

RECORDINGS = Path.home() / ".local" / "share" / "tars" / "recordings"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ptt", choices=["pttd", "stdin"], default=None)
    ap.add_argument("--no-avatar", action="store_true", help="don't open the Live2D window")
    ap.add_argument(
        "--save-audio",
        action="store_true",
        help=f"keep each utterance + transcript in {RECORDINGS} (local only) to benchmark STT",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S",
    )  # fmt: skip
    if not args.verbose:  # per-request chatter from libraries
        for name in ("httpx", "faster_whisper", "websockets.server", "phonemizer"):
            logging.getLogger(name).setLevel(logging.ERROR)
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
            cfg,
            on_state=lambda state, info: bus.publish({"type": "state", "state": state, **info}),
            save_audio=RECORDINGS if args.save_audio else None,
        )
        mcp = MCPManager()
        browser.register(service.registry, lambda: mcp.servers.get("firefox"))
        if added := await mcp.start(service.registry):
            logging.getLogger("tars.mcp").info(f"MCP tools: {', '.join(added)}")
        mouth = asyncio.create_task(service.mouth_loop(bus.publish))
        source = args.ptt or cfg["voice"]["ptt"]["source"]
        events = stdin_events() if source == "stdin" else pttd_events(cfg["voice"]["ptt"]["socket"])
        try:
            await service.run(events)
        finally:
            mouth.cancel()
            await mcp.close()
    finally:
        if avatar:
            avatar.terminate()
        await bus.close()
        if swap:
            swap.terminate()


if __name__ == "__main__":
    # Only when run as a program (never on import): re-exec once with the CUDA
    # library path set, before anything loads CTranslate2 (Whisper loads later).
    reexec_with_cuda_libs("tars.voice")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
