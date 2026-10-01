"""Push-to-talk event sources: tars-pttd (Right Ctrl) or the Enter key for testing."""

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator

log = logging.getLogger("tars.ptt")


async def pttd_events(path: str) -> AsyncIterator[str]:
    """Yields "down" / "up" / "cancel" from tars-pttd, reconnecting if it restarts."""
    warned = False
    while True:
        try:
            reader, _ = await asyncio.open_unix_connection(path)
            log.info(f"push-to-talk connected ({path})")
            warned = False
            while line := await reader.readline():
                event = json.loads(line).get("ptt")
                if event in ("down", "up", "cancel"):
                    yield event
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as e:
            if not warned:
                log.warning(f"tars-pttd not reachable at {path} ({e}); install it with "
                            "`sudo bash scripts/install_pttd.sh`, or run with --ptt stdin")  # fmt: skip
                warned = True
        await asyncio.sleep(2)


async def stdin_events() -> AsyncIterator[str]:
    """Enter starts recording, Enter again stops. For testing without tars-pttd."""
    loop = asyncio.get_running_loop()
    recording = False
    print("Press Enter to talk, Enter again to stop (Ctrl+C quits).", flush=True)
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:  # stdin closed
            return
        recording = not recording
        yield "down" if recording else "up"
