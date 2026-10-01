"""
Shell commands, always inside a bubblewrap sandbox.

  read-only (T0): / mounted read-only, home read-only, no network
  approved  (T2): home writable, network on (installs, git pull, builds)
Either way secret folders are hidden (empty tmpfs) and nothing can gain root:
the sandbox sets no_new_privs, so sudo and setuid binaries cannot elevate.
"""

import asyncio
import shutil
from pathlib import Path

from tars.agent.policy import SECRETS, classify_command
from tars.agent.tools import Context, Registry, Tier, obj

MAX_OUTPUT = 3500


def sandbox_argv(cmd: str, home: Path, writable: bool) -> list[str]:
    argv = [
        "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
        "--tmpfs", "/tmp", "--die-with-parent", "--new-session",
        "--unshare-pid", "--unshare-ipc", "--unshare-uts",
    ]  # fmt: skip
    # Mount home explicitly (after the empty /tmp, in case home lives under /tmp).
    argv += ["--bind" if writable else "--ro-bind", str(home), str(home)]
    if not writable:
        argv += ["--unshare-net"]
    for s in SECRETS:  # defence in depth: hide secrets even from read-only commands
        p = home / s
        if p.is_dir():
            argv += ["--tmpfs", str(p)]
        elif p.exists():
            argv += ["--ro-bind", "/dev/null", str(p)]
    return argv + ["--chdir", str(home), "/bin/sh", "-c", cmd]


async def run_command(ctx: Context, command: str, timeout: int = 30) -> str:
    tier, reason = classify_command(command, ctx.home)  # raises Denied for never-allowed
    if tier >= Tier.T2:
        await ctx.require(tier, f"run `{command}` ({reason})")
    if not shutil.which("bwrap"):
        return "error: bubblewrap (bwrap) is not installed, so commands cannot run safely"
    proc = await asyncio.create_subprocess_exec(
        *sandbox_argv(command, ctx.home, writable=tier >= Tier.T2),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=min(timeout, 300))
    except TimeoutError:
        proc.kill()
        return f"error: timed out after {timeout}s"
    text = out.decode("utf-8", errors="replace").strip()
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n… ({len(text) - MAX_OUTPUT} more characters)"
    return f"exit code {proc.returncode}\n{text or '(no output)'}"


def register(reg: Registry):
    reg.tool(
        "run_command",
        "Run a bash command in a sandbox. Read-only commands run immediately; anything that "
        "changes files or the system asks the user first. sudo is never available.",
        obj(["command"], command={"type": "string"},
            timeout={"type": "integer", "description": "seconds, default 30"}),
        speak="Running that",
    )(run_command)  # fmt: skip
