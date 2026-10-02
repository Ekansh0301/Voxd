"""
Client for the TARS bridge VS Code extension (deploy/vscode-extension): each VS Code
window answers on $XDG_RUNTIME_DIR/tars-vscode-<pid>.sock (private to the user)
with its active file, problems and recent integrated-terminal commands.
"""

import asyncio
import json
import os
from pathlib import Path

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


async def _ask(sock: Path, what: str, timeout: float = 2.0):
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(sock)), timeout)
    try:
        writer.write(json.dumps({"get": what}).encode() + b"\n")
        await writer.drain()
        return json.loads(await asyncio.wait_for(reader.readline(), timeout))
    finally:
        writer.close()


async def window(title: str = "") -> tuple[Path, dict] | None:
    """The VS Code window to talk to: the one whose workspace folder is named in
    `title` (e.g. 'a.py - HUTB - Visual Studio Code'), else the last focused."""
    found = []
    for sock in RUNTIME.glob("tars-vscode-*.sock"):
        try:
            found.append((sock, await _ask(sock, "state")))
        except (OSError, TimeoutError, json.JSONDecodeError):
            sock.unlink(missing_ok=True)  # left over from a closed window
    if not found:
        return None
    parts = [p.strip() for p in title.lstrip("●○ ").split(" - ")]
    folder = parts[1] if len(parts) >= 3 else ""
    named = [
        f
        for f in found
        if folder and any(Path(w).name == folder for w in f[1].get("workspace", []))
    ]
    return max(named or found, key=lambda f: (f[1].get("focused", False), f[1].get("focusedAt", 0)))


async def problems(sock: Path) -> list[dict]:
    return list(await _ask(sock, "problems"))


async def terminal_runs(sock: Path) -> list[dict]:
    return list(await _ask(sock, "terminal"))
