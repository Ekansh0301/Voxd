"""
Browser tools over Mozilla's firefox-devtools-mcp, driving your real Firefox
(started from the "Firefox (TARS)" launcher).

The driver's 34 raw tools are not given to the model. These wrappers expose a
small set and add TARS's rules on every call:
  - config/sites.yaml per tab: blocked sites are never read or touched,
    open-only sites can't be read, navigate-only sites can't be typed into
  - buttons like Send / Submit / Pay, and Ctrl+Enter, need approval
  - password and hidden fields are never filled (checked in the page, since
    snapshots don't show input types)
Elements are addressed by their visible name, as with the desktop screen tools.
"""

import asyncio
import json
import re
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path

from tars.agent.tools import Context, Denied, Registry, Tier, obj
from tars.mcp.client import MCPServer
from tars.perception.atspi import RISKY_WORDS

INTERACTIVE = {"input", "textarea", "select", "button", "a", "link", "checkbox", "radio",
               "combobox", "option", "menuitem", "tab", "switch", "searchbox", "textbox",
               "listbox", "slider", "spinbutton", "treeitem", "gridcell"}  # fmt: skip
TEXTUAL = {
    "h1",
    "h2",
    "h3",
    "h4",
    "heading",
    "p",
    "li",
    "td",
    "th",
    "label",
    "img",
    "dialog",
    "alert",
}
LINE = re.compile(r'^\s*uid=(\S+) (\S+)(?: "((?:[^"\\]|\\.)*)")?(.*)$')

_names: dict[str, str] = {}  # display name -> uid, from the last web_read
_fields: list[str] = []  # text fields found by script that the snapshot missed

# Visible text fields with a usable label. Snapshots skip some (e.g. ChatGPT's prompt).
FIELD_JS = """
const FIELDS = 'input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=file])'
  + ':not([type=button]), textarea, [contenteditable=""], [contenteditable=true], [role=textbox], [role=searchbox]';
const shown = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
const label = e => (e.getAttribute('aria-label') || e.placeholder || e.dataset.placeholder
  || (e.labels && e.labels[0] && e.labels[0].innerText) || e.querySelector?.('[data-placeholder]')?.dataset.placeholder
  || e.name || e.id || '').trim().slice(0, 80);
const fields = () => Array.from(document.querySelectorAll(FIELDS)).filter(shown).filter(e => label(e));
"""


def _no_server() -> MCPServer | None:
    return None


_get_server: Callable[[], MCPServer | None] = _no_server


MARIONETTE = ("127.0.0.1", 2828)
LAUNCHER = Path(__file__).resolve().parent.parent.parent / "scripts" / "firefox-tars.sh"


def _firefox_listening() -> bool:
    try:
        with socket.create_connection(MARIONETTE, timeout=0.3):
            return True
    except OSError:
        return False


def _normal_firefox_running() -> bool:
    return subprocess.run(["pgrep", "-x", "firefox"], capture_output=True).returncode == 0


async def ensure_firefox(url: str = "") -> bool:
    """Start Firefox (TARS) if it isn't running (on `url`, so the first tab isn't the
    home page); fail clearly if normal Firefox is open. True if it was started."""
    if _firefox_listening():
        return False
    if _normal_firefox_running():
        raise ConnectionError(
            "Firefox is open normally, so TARS can't read or type in it. Ask the user to close "
            "Firefox; then open_url starts Firefox (TARS) by itself."
        )
    subprocess.Popen([str(LAUNCHER), *([url] if url else [])], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)  # fmt: skip
    for _ in range(40):
        await asyncio.sleep(0.5)
        if _firefox_listening():
            await asyncio.sleep(1.0)  # let the first window finish opening
            return True
    raise ConnectionError("Firefox (TARS) didn't start within 20 seconds")


def _server() -> MCPServer:
    server = _get_server()
    if server is None or server.proc is None or server.proc.returncode is not None:
        raise ConnectionError("TARS's browser driver isn't running; restart TARS")
    return server


async def _ready() -> MCPServer:
    await ensure_firefox()
    return _server()


async def _current_url() -> str:
    out = await (await _ready()).call_tool("list_pages", {})
    m = re.search(r"^>\[\d+\] .*\((\S+)\)\s*$", out, re.M)
    return m.group(1) if m else ""


def short(url: str) -> str:
    """For spoken approvals: 'outlook.office365.com', not the whole URL."""
    m = re.match(r"^https?://(?:www\.)?([^/:]+)", url)
    return m.group(1) if m else "this page"


async def _check(ctx: Context, action: str) -> str:
    url = await _current_url()
    if not url or url.startswith(("about:", "chrome:", "moz-extension:")):
        # Firefox's own pages (home, settings, about:config): never touched
        raise Denied("this tab is one of Firefox's own pages; open_url a website first")
    if not url.startswith("data:"):
        decision = ctx.sites.check(url, action)
        if not decision.allowed:
            raise Denied(decision.reason)
    return url


def compact_snapshot(raw: str, max_lines: int = 120) -> tuple[str, dict[str, str]]:
    """Driver snapshot -> 'role "name"' lines for useful elements + name->uid map."""
    names: dict[str, str] = {}
    lines: list[str] = []
    text_buf: list[str] = []  # pages that split words into per-letter spans
    for raw_line in raw.splitlines():
        m = LINE.match(raw_line)
        if not m:
            continue
        uid, role, name, rest = m.group(1), m.group(2), m.group(3) or "", m.group(4)
        text = re.search(r'text="((?:[^"\\]|\\.)*)"', rest)
        value = re.search(r'value="((?:[^"\\]|\\.)*)"', rest)
        tag = re.search(r"tag=(\S+)", rest)
        shown = name or (text.group(1) if text else "")
        if role in ("span", "div", "b", "i", "em", "strong") and text and len(text.group(1)) <= 2:
            text_buf.append(text.group(1))
            continue
        if text_buf:
            lines.append(f'text "{"".join(text_buf)[:200]}"')
            text_buf = []
        if role in INTERACTIVE or (tag and tag.group(1) == "div" and role == "button"):
            label = shown or f"unnamed {role}"
            key, k = label, 2
            while key in names:
                key, k = f"{label} ({k})", k + 1
            names[key] = uid
            extra = (
                f" = {value.group(1)!r}"
                if value and role in ("input", "select", "textarea")
                else ""
            )
            lines.append(f'{role} "{key}"{extra}')
        elif role in TEXTUAL and shown:
            lines.append(f'{role} "{shown[:160]}"')
        if len(lines) >= max_lines:
            lines.append("… (more not shown; use mode=text for the page text)")
            break
    if text_buf:
        lines.append(f'text "{"".join(text_buf)[:200]}"')
    return "\n".join(lines), names


def _uid(name: str) -> str:
    if name in _names:
        return _names[name]
    low = name.lower()
    for key, uid in _names.items():
        if key.lower() == low:
            return uid
    for key, uid in _names.items():
        if low in key.lower():
            return uid
    raise ValueError(f"nothing named {name!r} on the page; web_read again")


async def web_tabs(ctx: Context) -> str:
    out = await (await _ready()).call_tool("list_pages", {})
    shown = []
    for line in out.splitlines():
        m = re.search(r"\((\S+)\)\s*$", line)
        if m and not ctx.sites.check(m.group(1), "read").allowed:
            line = re.sub(r"\] .*$", "] (blocked site)", line)
        shown.append(line)
    return "\n".join(shown)


async def web_switch(ctx: Context, tab: int) -> str:
    return await (await _ready()).call_tool("select_page", {"pageIdx": tab})


async def web_read(ctx: Context, mode: str = "elements") -> str:
    url = await _check(ctx, "read")
    s = await _ready()
    if mode == "text":
        return f"{url}\n" + await s.call_tool("get_page_text", {})
    raw = await s.call_tool("take_snapshot", {})
    text, names = compact_snapshot(raw)
    _names.clear()
    _names.update(names)
    _fields.clear()
    out = await s.call_tool(
        "evaluate_script", {"function": "() => {" + FIELD_JS + "return fields().map(label) }"}
    )
    m = re.search(r"\[.*\]", out, re.S)
    for label in json.loads(m.group(0)) if m else []:
        if label and label not in _names and label not in _fields:
            _fields.append(label)
    extra = "".join(f'\nfield "{f}"' for f in _fields[:15])
    return f"{url}\n{text or '(no readable elements)'}{extra}"


async def web_click(ctx: Context, name: str) -> str:
    url = await _check(ctx, "click")
    uid = _uid(name)
    label = next((k for k, v in _names.items() if v == uid), name)
    if any(w in label.lower() for w in RISKY_WORDS):
        await ctx.require(Tier.T3, f'click "{label}" on {short(url)}')
    ctx.actions.append(f"web click {label!r}")
    out = await _act("click_by_uid", {"uid": uid})
    return f"{out} (not verified: web_read to see the result)"


async def _field_type(uid: str) -> str:
    out = await (await _ready()).call_tool(
        "evaluate_script",
        {"function": "(el) => (el.type || el.tagName).toLowerCase()", "args": [{"uid": uid}]},
    )
    m = re.search(r'"([a-z-]+)"', out)
    return m.group(1) if m else ""


async def _act(name: str, args: dict, timeout: float = 20) -> str:
    """An input action with a short timeout; driver errors and hangs become ConnectionError."""
    s = await _ready()
    try:
        out = await s.call_tool(name, args, timeout=timeout)
    except TimeoutError as e:
        raise ConnectionError(f"Firefox didn't respond to {name} within {timeout:.0f}s") from e
    if out.lstrip().lower().startswith("error"):
        raise ConnectionError(out[:300])
    return out


async def _fill_by_label(ctx: Context, url: str, label: str, text: str) -> str:
    """Focus a script-found field by its label and type into it with real keystrokes."""
    s = await _ready()
    focus = ("() => {" + FIELD_JS + f"const want = {json.dumps(label.lower())};"
             "const e = fields().find(f => label(f).toLowerCase() === want)"
             " || fields().find(f => label(f).toLowerCase().includes(want));"
             "if (!e) return 'missing'; e.focus(); return (e.type || 'text').toLowerCase(); }")  # fmt: skip
    kind = await s.call_tool("evaluate_script", {"function": focus})
    if '"missing"' in kind:
        raise ValueError(f"nothing named {label!r} on the page; web_read again")
    if '"password"' in kind:
        raise Denied("TARS never types passwords; please enter it yourself")
    ctx.actions.append(f"web fill {label!r}")
    await _act("press_key", {"key": "Control+a"})
    await _act("type_text", {"text": text}, timeout=10 + len(text) / 20)
    return f"typed into {label!r} on {short(url)}"


async def web_fill(ctx: Context, name: str, text: str) -> str:
    url = await _check(ctx, "fill")
    if name not in _names and any(name.lower() in f.lower() for f in _fields):
        return await _fill_by_label(ctx, url, name, text)
    uid = _uid(name)
    if await _field_type(uid) in ("password", "hidden"):
        raise Denied("TARS never types passwords; please enter it yourself")
    ctx.actions.append(f"web fill {name!r}")
    return (
        await _act("fill_by_uid", {"uid": uid, "value": text}, timeout=10 + len(text) / 20)
        + f" on {short(url)}"
    )


async def web_type(ctx: Context, text: str, then_key: str = "") -> str:
    await _check(ctx, "type")
    focused = await (await _ready()).call_tool(
        "evaluate_script", {"function": "() => (document.activeElement?.type || '').toLowerCase()"}
    )
    if '"password"' in focused:
        raise Denied("the focused field is a password field; please type it yourself")
    if then_key.lower().replace(" ", "") in ("control+enter", "ctrl+enter", "meta+enter"):
        await ctx.require(Tier.T3, "type and press Ctrl+Enter (often sends)")
    ctx.actions.append(f"web type {len(text)} chars")
    args = {"text": text, **({"submitKey": then_key} if then_key else {})}
    return await _act("type_text", args, timeout=10 + len(text) / 20)


async def web_key(ctx: Context, key: str) -> str:
    await _check(ctx, "type")
    k = key.lower().replace(" ", "")
    if k in ("control+enter", "ctrl+enter", "meta+enter"):
        await ctx.require(Tier.T3, f"press {key} (often sends)")
    return await _act("press_key", {"key": key})


async def web_back(ctx: Context) -> str:
    return await (await _ready()).call_tool("navigate_history", {"direction": "back"})


def _tab_for(pages: str, host: str) -> int | None:
    """Newest tab (highest index) whose URL is on `host`, from list_pages output."""
    found = [int(m.group(1)) for m in re.finditer(r"^>?\s*\[(\d+)\] .*\((\S+)\)\s*$", pages, re.M)
             if short(m.group(2)) == host]  # fmt: skip
    return max(found) if found else None


async def _select(s: MCPServer, url: str) -> None:
    """Make the tab showing `url` the selected one, so web_read reads it."""
    host = short(url)
    for _ in range(10):
        pages = await s.call_tool("list_pages", {})
        idx = _tab_for(pages, host)
        if idx is not None:
            await s.call_tool("select_page", {"pageIdx": idx})
            return
        await asyncio.sleep(0.5)


async def web_open(url: str) -> str:
    """Used by open_url when Firefox (TARS) is usable; starts it if needed."""
    started = await ensure_firefox(url)
    s = _server()
    if started:  # its first tab already shows url
        await _select(s, url)
        return f"opened {url}"
    pages = await s.call_tool("list_pages", {})
    if (idx := _tab_for(pages, short(url))) is not None and url.rstrip("/").count("/") <= 2:
        # that site is already open (and no particular page was asked for): switch to it
        await s.call_tool("select_page", {"pageIdx": idx})
        return f"switched to the open {short(url)} tab"
    if "URL unavailable" in pages:
        # Firefox's home page is selected, and the driver can't see past it: reuse that tab.
        out = await s.call_tool("navigate_page", {"url": url})
    else:
        out = await s.call_tool("new_page", {"url": url})
    if out.lstrip().lower().startswith("error"):
        raise ConnectionError(out[:300])
    await _select(s, url)
    return out


def connected() -> bool:
    """Driver running and Firefox (TARS) usable, now or after starting it."""
    server = _get_server()
    if server is None or server.proc is None or server.proc.returncode is not None:
        return False
    return _firefox_listening() or not _normal_firefox_running()


def register(reg: Registry, get_server: Callable[[], MCPServer | None]):
    global _get_server
    _get_server = get_server
    from tars.tools import desktop

    desktop.BROWSER = (connected, web_open)  # open_url uses Firefox (TARS) when it's connected
    name = {"type": "string", "description": "the element's name as web_read shows it"}
    reg.tool("web_tabs", "List the tabs open in Firefox.")(web_tabs)
    reg.tool("web_switch", "Switch to a Firefox tab by its index.", obj(["tab"], tab={"type": "integer"}),
             tier=Tier.T1)(web_switch)  # fmt: skip
    reg.tool("web_read", "Read the current Firefox tab: mode 'elements' (buttons, links, fields by name) or 'text'.",
             obj([], mode={"type": "string", "enum": ["elements", "text"]}), speak="Reading")(web_read)  # fmt: skip
    reg.tool("web_click", "Click a link/button on the page by its name from web_read.",
             obj(["name"], name=name), tier=Tier.T1)(web_click)  # fmt: skip
    reg.tool("web_fill", "Fill a form field on the page by its name from web_read.",
             obj(["name", "text"], name=name, text={"type": "string"}), tier=Tier.T1)(web_fill)  # fmt: skip
    reg.tool("web_type", "Type into the focused field on the page, optionally then a key like Enter.",
             obj(["text"], text={"type": "string"}, then_key={"type": "string"}), tier=Tier.T1)(web_type)  # fmt: skip
    reg.tool("web_key", "Press a key on the page, e.g. Enter, Escape, Tab, ArrowDown, Control+a.",
             obj(["key"], key={"type": "string"}), tier=Tier.T1)(web_key)  # fmt: skip
    reg.tool("web_back", "Go back in the current tab.", tier=Tier.T1)(web_back)
