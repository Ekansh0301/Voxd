"""
"Explain the error on my screen": one tool that looks at the window the user is
working in and gathers what matters for that kind of app, so the model doesn't
have to pick among five readers:
  - terminals: the output of the tmux pane the user last typed in
  - VS Code: the open file (from the window title and VS Code's own saved
    window state), its code-check results, and a look at the window if the
    checks find nothing (errors in its terminal or popups)
  - Firefox: the page address and its visible text (site rules apply)
  - anything else: the accessibility tree, or a look at the window
If the request was typed in TARS's own box, TARS has the focus, so the window
just below it (the one the user was in) is used.
"""

import io
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

from tars.agent.tools import Context, Denied, Registry, obj
from tars.perception.windows import NoExtension, Window, list_windows

TERMINALS = (
    "ghostty",
    "gnome-terminal",
    "kgx",
    "ptyxis",
    "konsole",
    "kitty",
    "alacritty",
    "wezterm",
)
VSCODE_STATE = Path.home() / ".config/Code/User/globalStorage/storage.json"


def kind_of(w: Window) -> str:
    key = f"{w.app} {w.wm_class}".lower()
    if any(t in key for t in TERMINALS):
        return "terminal"
    if "code" in key and ("vscode" in key or w.title.endswith("Visual Studio Code")):
        return "vscode"
    if "firefox" in key:
        return "firefox"
    return "other"


async def _working_window() -> Window | None:
    """The focused window, or the topmost one when TARS's own box has the focus
    (the extension lists windows bottom to top and leaves TARS's out)."""
    wins = await list_windows()
    return next((w for w in wins if w.focused), None) or next(
        (w for w in reversed(wins) if not w.minimized), None
    )


def tmux_output(lines: int = 60) -> str:
    """The active pane of the tmux client the user typed in last."""
    if not shutil.which("tmux"):
        return ""
    clients = subprocess.run(["tmux", "list-clients", "-F", "#{client_activity} #{client_session}"],
                             capture_output=True, text=True, timeout=5).stdout.split("\n")  # fmt: skip
    clients = sorted((c for c in clients if c.strip()), reverse=True)
    if not clients:
        return ""
    session = clients[0].split(" ", 1)[1]
    info = subprocess.run(["tmux", "display", "-p", "-t", session, "#{pane_id} #{pane_current_command} #{pane_current_path}"],
                          capture_output=True, text=True, timeout=5).stdout.strip()  # fmt: skip
    pane, _, rest = info.partition(" ")
    out = subprocess.run(["tmux", "capture-pane", "-p", "-J", "-t", pane, "-S", f"-{lines}"],
                         capture_output=True, text=True, timeout=5).stdout.rstrip()  # fmt: skip
    return f"terminal output (tmux {pane}, {rest}):\n{out}"


def _find_dirs(home: Path, name: str, depth: int = 4) -> list[Path]:
    found: list[Path] = []
    level = [home]
    for _ in range(depth):
        nxt: list[Path] = []
        for d in level:
            try:
                for c in d.iterdir():
                    if (
                        c.is_dir()
                        and not c.name.startswith(".")
                        and c.name not in ("node_modules", "snap")
                    ):
                        (found if c.name == name else nxt).append(c)
            except OSError:
                continue
        if found:
            return found
        level = nxt
    return found


def vscode_file(title: str, home: Path) -> tuple[Path | None, str]:
    """'● a.py - HUTB - Visual Studio Code' -> the file's path (via VS Code's state)."""
    parts = [p.strip() for p in title.lstrip("●○ ").split(" - ")]
    if len(parts) < 2:
        return None, ""
    name, folder_name = parts[0], parts[1] if len(parts) >= 3 else ""
    folders: list[Path] = []
    try:
        state = json.loads(VSCODE_STATE.read_text()).get("windowsState", {})
        for w in [state.get("lastActiveWindow", {}), *state.get("openedWindows", [])]:
            if uri := w.get("folder"):
                folders.append(Path(unquote(urlparse(uri).path)))
    except (OSError, json.JSONDecodeError):
        pass
    named = [f for f in folders if folder_name and f.name == folder_name]
    if folder_name and not named:  # VS Code's saved state can lag behind a new window
        named = _find_dirs(home, folder_name)
    folders = named or folders
    for folder in folders:
        if not folder.is_dir():
            continue
        hits = [p for p in folder.rglob(name) if p.is_file() and ".git" not in p.parts
                and "node_modules" not in p.parts and ".venv" not in p.parts][:5]  # fmt: skip
        if len(hits) == 1:
            return hits[0], str(folder)
        if hits:  # same name in several places: newest is likeliest the one being edited
            return max(hits, key=lambda p: p.stat().st_mtime), str(folder)
    return None, ", ".join(map(str, folders))


def _excerpts(path: Path, checks: str, around: int = 2, limit: int = 3) -> list[str]:
    """The code at the lines the checks point to, so the answer can quote it."""
    import re

    try:
        src = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    name = re.escape(path.name)  # "a.py:3:" (checks, Problems) or 'a.py", line 3' (tracebacks)
    nums = sorted({int(n) for n in re.findall(rf'{name}(?::|", line )(\d+)', checks)})[:limit]
    out = []
    for n in nums:
        lo, hi = max(1, n - around), min(len(src), n + around)
        body = "\n".join(f"{i:>4}{'>' if i == n else ' '} {src[i - 1]}" for i in range(lo, hi + 1))
        out.append(f"{path.name} around line {n}:\n{body}")
    return out


async def look(win: Window, question: str) -> str:
    """Ask the vision model about just this window."""
    from PIL import Image

    from tars.perception.screenshot import take_screenshot
    from tars.tools.vision import ask_image

    path = await take_screenshot()
    try:
        img = Image.open(path).crop((win.x, win.y, win.x + win.width, win.y + win.height))
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, "PNG")
    finally:
        path.unlink(missing_ok=True)
    return await ask_image(buf.getvalue(), question)


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


async def _vscode(ctx: Context, win: Window, head: str, q: str) -> str:
    """Via the TARS bridge extension when it runs in that window (exact file, cursor,
    Problems, integrated-terminal output); else the title and VS Code's saved state."""
    from tars.agent.policy import check_read
    from tars.perception import vscode as bridge
    from tars.tools.code import check_code

    lines = [head]
    path: Path | None = None
    found_problem = False
    try:
        w = await bridge.window(win.title)
    except OSError:
        w = None
    if w:
        sock, st = w
        if st.get("file"):
            path = Path(st["file"])
            lines.append(f"open file: {path} (cursor at line {st.get('line')})")
        if st.get("selection"):
            lines.append(f"selected text:\n{st['selection'][:1500]}")
        probs = await bridge.problems(sock)
        if probs:
            found_problem = True
            lines.append("Problems panel:\n" + "\n".join(
                f"  {p['severity']}: {Path(p['file']).name}:{p['line']}: {p['message']}"
                + (f" ({p['source']})" if p.get("source") else "") for p in probs[:12]))  # fmt: skip
        runs = await bridge.terminal_runs(sock)
        if runs:
            failed = [r for r in runs if r.get("exitCode") not in (0, None)]
            run = (failed or runs)[-1]
            out = ANSI.sub("", run.get("output", "")).strip()[-2500:]
            found_problem = found_problem or bool(failed)
            lines.append(
                f"integrated terminal, last command: {run.get('command')} (exit code {run.get('exitCode')})\n{out}"
            )
    else:
        path, folder = vscode_file(win.title, ctx.home)
        lines.append(
            f"open file: {path}"
            if path
            else f"open file: couldn't locate it (workspace {folder or 'unknown'})"
        )
    if path is not None and path.is_file():
        check_read(path, ctx.home)
        checks = await check_code(ctx, str(path)) if path.suffix == ".py" else ""
        if checks and not (
            "syntax: ok" in checks and "no issues" in checks and "line(s)" not in checks
        ):
            found_problem = True
            lines.append(checks)
        lines += _excerpts(path, "\n".join(lines))
    if not found_problem:
        lines.append("on screen: " + await look(win, q))
    return "\n".join(lines)


async def screen_context(ctx: Context, question: str = "") -> str:
    if not ctx.desktop:  # evals: never read the real screen into their results
        return ("the user is in: com.mitchellh.ghostty: tmux (terminal) (dry run)\nterminal output:\n"
                "$ python3 fetch.py\nTraceback (most recent call last):\n  File \"fetch.py\", line 7, in <module>\n"
                "    config = load(\"settings.json\")\nFileNotFoundError: [Errno 2] No such file or directory: 'settings.json'")  # fmt: skip
    q = question or "What error, warning or problem is shown? Quote it exactly."
    try:
        win = await _working_window()
    except NoExtension as e:
        return f"error: {e}"
    if win is None:
        return "error: no open window found"
    kind = kind_of(win)
    head = f"the user is in: {win.label} ({kind})"

    if kind == "terminal":
        out = tmux_output()
        if out:
            return f"{head}\n{out}"
        return f"{head}\n(not inside tmux, so read from the screen)\n{await look(win, q)}"

    if kind == "vscode":
        return await _vscode(ctx, win, head, q)

    if kind == "firefox":
        from tars.tools import browser

        if browser.connected():
            url = await browser._current_url()
            if url and not ctx.sites.check(url, "read").allowed:
                raise Denied(ctx.sites.check(url, "read").reason)
            text = await browser._read_text(browser._server())
            return f"{head}\npage: {url}\n{text[-4000:]}"

    # anything else (and Firefox not under TARS's control): accessibility, then vision
    from tars.perception.atspi import Atspi

    async with Atspi() as a:
        found = next(((app, w) for app, w in await a.windows()
                      if w.name and (w.name in win.title or win.title in w.name)), None)  # fmt: skip
        if found:
            await a.tree(found[1])
            doc = await a.doc_url(found[1])
            if doc and not ctx.sites.check(doc, "read").allowed:
                raise Denied(ctx.sites.check(doc, "read").reason)
            text = a.render(found[1], max_lines=80)
            if text.count("\n") > 5:
                return f"{head}\n{text}"
    return f"{head}\non screen: {await look(win, q)}"


def register(reg: Registry):
    reg.tool(
        "screen_context",
        "What the user is looking at right now, gathered for its app (terminal output, the "
        "open file and its errors in VS Code, the page in Firefox). Use first for 'explain "
        "this error', 'what's on my screen', 'why did this fail'.",
        obj([], question={"type": "string", "description": "what to look for, if specific"}),
        speak="Looking",
    )(screen_context)
