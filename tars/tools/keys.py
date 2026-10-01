"""
Keyboard tools: type text and press shortcuts in the focused window, through the
RemoteDesktop portal (tars/perception/keyboard.py).

Keystrokes go wherever the focus is, so every call first checks what has it:
  - terminals are refused (typed commands would skip the shell policy; use
    run_command or terminal_open)
  - password fields are refused
  - Firefox pages on sites that may not be typed into are refused
  - Ctrl+Enter (often "send") needs approval; closing shortcuts need approval
  - `window` (optional) must match the active window, or nothing is typed
"""

from tars.agent.tools import Context, Denied, Registry, Tier, obj
from tars.perception.atspi import ACTIVE, FOCUSED, Atspi, Node
from tars.perception.keyboard import InputError, Keyboard, parse_combo

TERMINALS = ("ghostty", "gnome-terminal", "kgx", "ptyxis", "konsole", "xterm", "alacritty",
             "kitty", "wezterm", "tilix", "terminator", "termius")  # fmt: skip
SENDING = {"ctrl+enter", "control+enter", "ctrl+return", "control+return", "meta+enter"}
CLOSING = {"alt+f4", "ctrl+w", "ctrl+q", "control+w", "control+q", "ctrl+shift+w", "ctrl+shift+q"}


def _walk(n: Node):
    yield n
    for c in n.children:
        yield from _walk(c)


async def _target(ctx: Context, window: str) -> str:
    """Check the focused window/element; returns 'app: title' for the reply."""
    async with Atspi() as a:
        wins = [(app, w) for app, w in await a.windows() if ACTIVE in w.states]
        if not wins:
            if window:
                raise Denied(f"can't tell which window has focus, so not typing into {window!r}")
            return "the focused window"
        app, win = wins[0]
        label = f"{app}: {win.name}" if win.name else app
        if window and window.lower() not in label.lower():
            raise Denied(f"the focused window is {label!r}, not {window!r}; open or focus it first")
        if any(t in app.lower() or t in win.name.lower() for t in TERMINALS):
            raise Denied(
                "the focused window is a terminal; use run_command or terminal_open instead"
            )
        await a.tree(win, max_nodes=1500, max_depth=40)
        focused = next((n for n in _walk(win) if FOCUSED in n.states and n is not win), None)
        if focused is not None:
            if focused.role == "password text":
                raise Denied("the focused field is a password field; please type it yourself")
            if focused.role == "terminal":
                raise Denied("the focus is in a terminal; use run_command instead")
        url = await a.doc_url(win)
        if url and not ctx.sites.check(url, "type").allowed:
            raise Denied(ctx.sites.check(url, "type").reason)
    return label


async def _guard_combo(ctx: Context, combo: str) -> None:
    k = combo.lower().replace(" ", "")
    if k in SENDING:
        await ctx.require(Tier.T3, f"press {combo} (often sends)")
    elif k in CLOSING:
        await ctx.require(Tier.T2, f"press {combo} (closes a window or tab)")


async def type_text(ctx: Context, text: str, then_key: str = "", window: str = "") -> str:
    if then_key:
        parse_combo(then_key)  # validate before typing anything
        await _guard_combo(ctx, then_key)
    ctx.actions.append(f"type {len(text)} chars" + (f" + {then_key}" if then_key else ""))
    if not ctx.desktop:
        return f"typed {len(text)} characters (dry run)"
    where = await _target(ctx, window)
    try:
        async with Keyboard() as kb:
            await kb.type(text)
            if then_key:
                await kb.combo(then_key)
    except InputError as e:
        return f"error: {e}"
    return f"typed {len(text)} characters into {where}" + (f", then {then_key}" if then_key else "")


async def press_keys(ctx: Context, keys: str, window: str = "") -> str:
    combos = [c.strip() for c in keys.split(",") if c.strip()]
    for c in combos:
        parse_combo(c)
        await _guard_combo(ctx, c)
    ctx.actions.append(f"keys {', '.join(combos)}")
    if not ctx.desktop:
        return f"pressed {', '.join(combos)} (dry run)"
    where = await _target(ctx, window)
    try:
        async with Keyboard() as kb:
            for c in combos:
                await kb.combo(c)
    except InputError as e:
        return f"error: {e}"
    return f"pressed {', '.join(combos)} in {where} (not verified: read_screen to check)"


def register(reg: Registry):
    window = {
        "type": "string",
        "description": "app expected to have focus, e.g. spotube; nothing is typed otherwise",
    }
    reg.tool(
        "type_text",
        "Type text with the keyboard into the focused window (for apps whose fields "
        "type_into can't reach), optionally then a key like Enter.",
        obj(["text"], text={"type": "string"}, then_key={"type": "string"}, window=window),
        tier=Tier.T1,
    )(type_text)  # fmt: skip
    reg.tool(
        "press_keys",
        "Press keyboard shortcuts in the focused window, e.g. 'ctrl+s', 'Enter', "
        "'ctrl+k, Escape' (comma-separated, in order).",
        obj(["keys"], keys={"type": "string"}, window=window),
        tier=Tier.T1,
    )(press_keys)  # fmt: skip
