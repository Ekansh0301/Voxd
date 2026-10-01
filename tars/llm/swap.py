"""Start (if needed) and warm up the llama-swap model server."""

import asyncio
import subprocess
import time
from pathlib import Path

from tars import BIN_DIR
from tars.llm.client import is_up, stream_chat

SWAP_CONFIG = Path.home() / ".config" / "tars" / "llama-swap.yaml"


async def warm_up(endpoint: str, model: str):
    """llama-swap loads a model on first use (~3-7 s); do that before the first turn."""
    async for _ in stream_chat(endpoint, model, [{"role": "user", "content": "hi"}], max_tokens=1):
        pass


async def prime(endpoint: str, model: str, system: str, tools: list[dict]) -> float:
    """Pre-fill llama.cpp's cache with the system prompt + tool list (~4k tokens, about
    10 s cold), so the first real turn only processes the new words. Returns seconds."""
    from tars.llm.client import stream_turn

    t = time.monotonic()
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": "hi"}]
    async for _ in stream_turn(endpoint, model, msgs, tools=tools, max_tokens=1):
        pass
    return time.monotonic() - t


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
