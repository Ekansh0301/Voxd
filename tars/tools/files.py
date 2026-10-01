"""Files in your home folder: list, read, find, create, move, and trash (reversible)."""

import os
import shutil
import subprocess
import time
from pathlib import Path

from tars.agent.policy import check_read, check_write, resolve
from tars.agent.tools import Context, Denied, Registry, Tier, obj

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", ".cache", "snap", ".local"}
MAX_READ = 6000


def _rel(p: Path, ctx: Context) -> str:
    try:
        return "~/" + p.relative_to(ctx.home).as_posix()
    except ValueError:
        return str(p)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def list_dir(ctx: Context, path: str = "~", show_hidden: bool = False) -> str:
    p = resolve(path, ctx.home)
    check_read(p, ctx.home)
    if not p.is_dir():
        return f"error: {_rel(p, ctx)} is not a folder"
    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    if not show_hidden:
        entries = [e for e in entries if not e.name.startswith(".")]
    lines = []
    for e in entries[:80]:
        if e.is_dir():
            lines.append(f"{e.name}/")
        else:
            st = e.stat()
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            lines.append(f"{e.name}  {_size(st.st_size)}  {when}")
    more = f"\n… and {len(entries) - 80} more" if len(entries) > 80 else ""
    return f"{_rel(p, ctx)} ({len(entries)} items):\n" + ("\n".join(lines) or "(empty)") + more


def read_file(ctx: Context, path: str) -> str:
    p = resolve(path, ctx.home)
    check_read(p, ctx.home)
    if not p.is_file():
        return f"error: {_rel(p, ctx)} is not a file"
    data = p.read_bytes()[: MAX_READ * 4]
    if b"\x00" in data[:2048]:
        return f"{_rel(p, ctx)} is a binary file ({_size(p.stat().st_size)})"
    text = data.decode("utf-8", errors="replace")
    cut = f"\n… (truncated, {len(text) - MAX_READ} more characters)" if len(text) > MAX_READ else ""
    return text[:MAX_READ] + cut


def find_files(ctx: Context, pattern: str, under: str = "~", limit: int = 30) -> str:
    """Case-insensitive glob on file names, e.g. '*.pdf' or '*report*'."""
    root = resolve(under, ctx.home)
    check_read(root, ctx.home)
    pat, hits, deadline = pattern.lower(), [], time.monotonic() + 5
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if Path(name.lower()).match(pat):
                hits.append(Path(dirpath) / name)
        if len(hits) >= limit or time.monotonic() > deadline:
            break
    hits.sort(key=lambda h: h.stat().st_mtime, reverse=True)
    if not hits:
        return f"no files matching {pattern} under {_rel(root, ctx)}"
    return "\n".join(_rel(h, ctx) for h in hits[:limit])


async def write_file(ctx: Context, path: str, content: str, overwrite: bool = False) -> str:
    p = resolve(path, ctx.home)
    check_write(p, ctx.home)
    if p.exists():
        if not overwrite:
            return f"error: {_rel(p, ctx)} already exists (set overwrite to replace it)"
        await ctx.require(Tier.T2, f"overwrite {_rel(p, ctx)}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {_rel(p, ctx)} ({len(content)} characters)"


def make_dir(ctx: Context, path: str) -> str:
    p = resolve(path, ctx.home)
    check_write(p, ctx.home)
    p.mkdir(parents=True, exist_ok=True)
    return f"folder ready: {_rel(p, ctx)}"


def _target(src: Path, dst: Path, destination: str) -> Path:
    """Where src ends up. A destination that is (or looks like) a folder keeps src's name:
    an existing directory, a trailing slash, or a missing path without an extension when
    src has one ("move s0.png to Pictures/screens" must not rename it to "screens")."""
    looks_like_dir = destination.endswith("/") or (
        not dst.exists() and not dst.suffix and src.is_file() and bool(src.suffix)
    )
    return dst / src.name if dst.is_dir() or looks_like_dir else dst


async def move_path(ctx: Context, source: str, destination: str) -> str:
    src, dst = resolve(source, ctx.home), resolve(destination, ctx.home)
    check_write(src, ctx.home)
    check_write(dst, ctx.home)
    if not src.exists():
        return f"error: {_rel(src, ctx)} does not exist"
    dst = _target(src, dst, destination)
    if dst.exists():
        await ctx.require(Tier.T2, f"replace {_rel(dst, ctx)} with {_rel(src, ctx)}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"moved {_rel(src, ctx)} -> {_rel(dst, ctx)}"


async def copy_path(ctx: Context, source: str, destination: str) -> str:
    src, dst = resolve(source, ctx.home), resolve(destination, ctx.home)
    check_read(src, ctx.home)
    check_write(dst, ctx.home)
    if not src.exists():
        return f"error: {_rel(src, ctx)} does not exist"
    dst = _target(src, dst, destination)
    if dst.exists():
        await ctx.require(Tier.T2, f"replace {_rel(dst, ctx)} with a copy of {_rel(src, ctx)}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)  # exact bytes and timestamps
    return f"copied {_rel(src, ctx)} -> {_rel(dst, ctx)}"


async def trash_path(ctx: Context, path: str) -> str:
    p = resolve(path, ctx.home)
    check_write(p, ctx.home)
    if not p.exists():
        return f"error: {_rel(p, ctx)} does not exist"
    if p.resolve() == ctx.home.resolve():
        raise Denied("refusing to trash the whole home folder")
    what = (
        f"folder {_rel(p, ctx)} ({sum(1 for _ in p.rglob('*'))} items)"
        if p.is_dir()
        else _rel(p, ctx)
    )
    await ctx.require(Tier.T2, f"move {what} to the Trash")
    if ctx.desktop and shutil.which("gio"):
        subprocess.run(["gio", "trash", str(p)], check=True, timeout=30)
    else:  # evals: a local trash folder keeps it reversible
        trash = ctx.home / ".trash-tars"
        trash.mkdir(exist_ok=True)
        shutil.move(str(p), str(trash / p.name))
    return f"moved {what} to the Trash (restorable)"


def register(reg: Registry):
    path = {"type": "string", "description": "path; relative paths start in the home folder"}
    reg.tool("list_dir", "List a folder's contents with sizes and dates.",
             obj([], path=path, show_hidden={"type": "boolean"}))(list_dir)  # fmt: skip
    reg.tool("read_file", "Read a text file.", obj(["path"], path=path))(read_file)
    reg.tool("find_files", "Find files by name pattern (e.g. '*.pdf', '*invoice*'), newest first.",
             obj(["pattern"], pattern={"type": "string"}, under=path), speak="Searching")(find_files)  # fmt: skip
    reg.tool("write_file", "Create a text file (overwriting needs overwrite=true and approval).",
             obj(["path", "content"], path=path, content={"type": "string"},
                 overwrite={"type": "boolean"}), tier=Tier.T1)(write_file)  # fmt: skip
    reg.tool("make_dir", "Create a folder.", obj(["path"], path=path), tier=Tier.T1)(make_dir)
    dest = {"type": "string", "description": "a folder (the name is kept) or a new full path"}
    reg.tool("move_path", "Move or rename a file or folder (one item per call).",
             obj(["source", "destination"], source=path, destination=dest), tier=Tier.T1)(move_path)  # fmt: skip
    reg.tool("copy_path", "Copy a file or folder exactly (use this for backups, never read+write).",
             obj(["source", "destination"], source=path, destination=dest), tier=Tier.T1)(copy_path)  # fmt: skip
    reg.tool("trash_path", "Move a file or folder to the Trash (restorable; asks first).",
             obj(["path"], path=path), tier=Tier.T1)(trash_path)  # fmt: skip
