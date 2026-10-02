"""
Screen tools: read the active window through the accessibility tree, click and
type into elements by the ids from the last read, and read terminal output
from tmux. Ids are only valid until the next read_screen.
"""

import asyncio
import shutil
import subprocess

from tars.agent.tools import Context, Denied, Registry, Tier, obj
from tars.perception.atspi import Atspi, Node

_last: dict[int, Node] = {}
_labels: dict[str, int] = {}
_last_window = ""
_last_text = ""  # what read_screen last showed, to report what an action changed


def _remember(a: Atspi, label: str, text: str) -> None:
    global _last_window, _last_text
    _last.clear()
    _last.update(a.refs)
    _labels.clear()
    _labels.update(a.labels)
    _last_window, _last_text = label, text


def _diff(before: str, after: str, limit: int = 12) -> str:
    import difflib

    strip = lambda t: [ln.split("] ", 1)[-1] for ln in t.splitlines()]  # noqa: E731  ids shift
    changed = [ln for ln in difflib.ndiff(strip(before), strip(after)) if ln[:2] in ("+ ", "- ")]
    if not changed:
        return "no visible change in the window"
    extra = f"\n… {len(changed) - limit} more changes" if len(changed) > limit else ""
    return "what changed:\n" + "\n".join(changed[:limit]) + extra


async def _after_action(wait: float = 0.6) -> str:
    """Re-read the window after a click/type and say what changed (or which new
    window, e.g. a dialog, took over). Element names stay valid for the next step."""
    await asyncio.sleep(wait)
    async with Atspi() as a:
        wins = await a.windows()
        if not wins:
            return ""
        app, win = wins[0]  # active window
        label = f"{app}: {win.name}"
        same = label == _last_window
        if not same:  # the old window may still be there, behind a dialog
            match = [(ap, w) for ap, w in wins if f"{ap}: {w.name}" == _last_window]
            if match and 1 not in win.states:
                app, win = match[0]
                label, same = _last_window, True
        await a.tree(win)
        text = a.render(win)
        before = _last_text
        _remember(a, label, text)
    if not same:
        return f"now active: {label!r}\n" + "\n".join(text.splitlines()[:25])
    return _diff(before, text)


async def read_screen(ctx: Context, window: str = "") -> str:
    async with Atspi() as a:
        wins = await a.windows()
        if not wins:
            return "error: no accessible windows found"
        if window:
            q = window.lower()
            match = [(app, w) for app, w in wins if q in app.lower() or q in w.name.lower()]
            if not match:
                return f"no window matching {window!r}; open windows: " + ", ".join(
                    f"{app}: {w.name!r}" for app, w in wins
                )
            app, win = match[0]
        else:
            app, win = wins[0]  # active window first
        await a.tree(win)
        url = await a.doc_url(win)
        if url and not ctx.sites.check(url, "read").allowed:
            raise Denied(ctx.sites.check(url, "read").reason)
        text = a.render(win)
        _remember(a, f"{app}: {win.name}", text)
    header = f"window {win.name!r} ({app}){', at ' + url if url else ''}"
    if len(_last) < 3:
        return (
            header
            + "\n(this app exposes almost nothing to accessibility; its contents can't be read this way yet)\n"
            + text
        )
    return header + "\n" + text


async def list_windows(ctx: Context) -> str:
    async with Atspi() as a:
        wins = await a.windows()
    return (
        "\n".join(
            f"{'* ' if i == 0 and 1 in w.states else '  '}{app}: {w.name!r}"
            for i, (app, w) in enumerate(wins)
        )
        or "no windows"
    )


def _node(element_id: int | None = None, name: str | None = None) -> tuple[int, Node]:
    """By [id], or by visible name (exact first, then case-insensitive, then contains)."""
    if element_id is not None:
        node = _last.get(int(element_id))
        if node is None:
            raise ValueError(
                f"no element [{element_id}] in the last read_screen; read the screen again"
            )
        return int(element_id), node
    if not name:
        raise ValueError("give the element's name")
    if name in _labels:  # exact display name, including "(2)" suffixes
        return _labels[name], _last[_labels[name]]
    items = list(_last.items())
    tests = (
        lambda n: n.name == name,
        lambda n: n.name.lower() == name.lower(),
        lambda n: name.lower() in n.name.lower(),
    )
    for test in tests:
        hits = [(i, n) for i, n in items if test(n)]
        if hits:  # prefer actionable elements over labels with the same text
            hits.sort(key=lambda h: "org.a11y.atspi.Action" not in h[1].interfaces)
            return hits[0]
    raise ValueError(f"nothing named {name!r} in the last read_screen; read the screen again")


async def click(ctx: Context, name: str | None = None, element_id: int | None = None) -> str:
    return await _click(ctx, name, element_id, observe=True)


async def _click(ctx: Context, name: str | None, element_id: int | None, observe: bool) -> str:
    element_id, node = _node(element_id, name)
    if node.risky:  # Send / Submit / Delete / Pay ... always asks
        await ctx.require(Tier.T3, f'click "{node.name}" in {_last_window}')
    ctx.actions.append(f"click [{element_id}] {node.role} {node.name!r}")
    if not ctx.desktop:
        return f"clicked {node.role} {node.name!r} (dry run)"
    async with Atspi() as a:
        result = await a.click(node)
    return f"{result}\n{await _after_action()}" if observe else result


async def click_sequence(ctx: Context, names: list[str]) -> str:
    """Press several elements in order, e.g. calculator keys or a menu path."""
    done: list[str] = []
    names = [str(n) for n in names[:30]]
    for i, name in enumerate(names):
        result = await _click(ctx, name, None, observe=i == len(names) - 1)
        if result.startswith("error") or "failed" in result:
            return f"stopped at {name!r}: {result}; clicked so far: {done}"
        done.append(name)
    return f"clicked in order: {done}\n{result.split(chr(10), 1)[-1]}"


async def type_into(
    ctx: Context, text: str, name: str | None = None, element_id: int | None = None
) -> str:
    element_id, node = _node(element_id, name)
    if node.role == "password text":
        raise Denied("TARS never types passwords; please enter it yourself")
    ctx.actions.append(f"type into [{element_id}] {node.name!r}")
    if not ctx.desktop:
        return f"typed into {node.role} {node.name!r} (dry run)"
    async with Atspi() as a:
        result = await a.set_text(node, text)
    return f"{result}\n{await _after_action(0.3)}"


def read_terminal(ctx: Context, lines: int = 80) -> str:
    if not shutil.which("tmux"):
        return "error: tmux is not installed"
    panes = subprocess.run(
        ["tmux", "list-panes", "-a", "-F", "#{window_activity} #{pane_id} #{pane_current_command} #{pane_current_path}"],
        capture_output=True, text=True, timeout=5,
    )  # fmt: skip
    if panes.returncode != 0 or not panes.stdout.strip():
        return ("no tmux session is running, so terminal output can't be read. "
                "Terminals started inside tmux can be read exactly.")  # fmt: skip
    _, pane, cmd, path = sorted(panes.stdout.split("\n")[:-1] or [""], reverse=True)[0].split(
        " ", 3
    )
    out = subprocess.run(["tmux", "capture-pane", "-p", "-J", "-t", pane, "-S", f"-{min(lines, 500)}"],
                         capture_output=True, text=True, timeout=5).stdout.rstrip()  # fmt: skip
    return f"terminal (tmux {pane}, running {cmd} in {path}):\n{out}"


def register(reg: Registry):
    reg.tool("read_screen", "Read what is in the active window (or a named one): buttons, fields, text, with [ids].",
             obj([], window={"type": "string", "description": "app or window title; empty = active window"}),
             speak="Looking")(read_screen)  # fmt: skip
    reg.tool("list_windows", "List open windows.")(list_windows)
    name = {
        "type": "string",
        "description": "the element's name exactly as read_screen shows it, e.g. '7', '×', 'Send'",
    }
    reg.tool("click", "Click one button/link/item shown by the last read_screen, by its name.",
             obj(["name"], name=name), tier=Tier.T1)(click)  # fmt: skip
    reg.tool("click_sequence", "Click several elements in order, by name, e.g. ['1', '2', '×', '7', '='].",
             obj(["names"], names={"type": "array", "items": {"type": "string"}}), tier=Tier.T1)(click_sequence)  # fmt: skip
    reg.tool("type_into", "Replace the text of a field shown by the last read_screen, by its name.",
             obj(["name", "text"], name=name, text={"type": "string"}), tier=Tier.T1)(type_into)  # fmt: skip
    reg.tool("read_terminal", "Read the latest output of the terminal (tmux).",
             obj([], lines={"type": "integer"}))(read_terminal)  # fmt: skip
