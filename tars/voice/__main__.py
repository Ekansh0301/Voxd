"""
Talk to TARS (Phase 1, voice only):

    .venv/bin/python -m tars.voice              # push-to-talk via tars-pttd (Right Ctrl)
    .venv/bin/python -m tars.voice --ptt stdin  # Enter to start/stop, no install needed

Starts llama-swap (Brain + Scout) automatically if it isn't already running.
"""

import argparse
import asyncio
import contextlib
import logging
import os
import subprocess
import sys
from pathlib import Path

from tars.config import load
from tars.cuda import reexec_with_cuda_libs
from tars.llm.swap import ensure_llm, prime, warm_up
from tars.mcp.manager import MCPManager
from tars.tools import browser, research
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
        # The bus URL carries its token: pass it in the environment (readable only by you),
        # not on the command line (which every user can read in /proc).
        avatar = subprocess.Popen(
            [sys.executable, "-m", "tars.ui"], env={**os.environ, "TARS_WS": bus.url}
        )
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

        async def _prime():
            secs = await prime(cfg["llm"]["endpoint"], cfg["llm"]["brain"], service.system,
                               service.registry.schemas())  # fmt: skip
            logging.getLogger("tars.voice").info(f"prompt cache primed in {secs:.1f}s")

        primer = asyncio.create_task(_prime())
        mouth = asyncio.create_task(service.mouth_loop(bus.publish))
        source = args.ptt or cfg["voice"]["ptt"]["source"]
        events = stdin_events() if source == "stdin" else pttd_events(cfg["voice"]["ptt"]["socket"])
        runner = asyncio.create_task(service.run(events))
        service.on_event = bus.publish  # subtitles to the avatar window

        def from_window(msg: dict):
            if msg.get("type") == "text":
                service.submit_text(str(msg.get("text", "")))
            elif msg.get("type") == "stop":  # tray menu "Stop" (the kill switch)
                asyncio.get_running_loop().create_task(service.stop())
            elif msg.get("type") == "quit":  # tray menu "Quit TARS"
                logging.getLogger("tars.voice").info("quit from the TARS menu")
                runner.cancel()

        bus.on_message = from_window
        try:
            with contextlib.suppress(asyncio.CancelledError):
                await runner
        finally:
            mouth.cancel()
            primer.cancel()
            await mcp.close()
            await research.shutdown()  # the hidden browser, if it was used
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
