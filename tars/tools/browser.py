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

import re
from collections.abc import Callable

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


def _no_server() -> MCPServer | None:
    return None


_get_server: Callable[[], MCPServer | None] = _no_server


def _server() -> MCPServer:
    server = _get_server()
    if server is None or server.proc is None or server.proc.returncode is not None:
        raise ConnectionError(
            "Firefox isn't connected. Open it with the 'Firefox (TARS)' launcher "
            "(close any normal Firefox window first)."
        )
    return server


async def _current_url() -> str:
    out = await _server().call_tool("list_pages", {})
    m = re.search(r"^>\[\d+\] .*\((\S+)\)\s*$", out, re.M)
    return m.group(1) if m else ""


def short(url: str) -> str:
    """For spoken approvals: 'outlook.office365.com', not the whole URL."""
    m = re.match(r"^https?://(?:www\.)?([^/:]+)", url)
    return m.group(1) if m else "this page"


async def _check(ctx: Context, action: str) -> str:
    url = await _current_url()
    if url and not url.startswith(("about:", "data:")):
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
    out = await _server().call_tool("list_pages", {})
    shown = []
    for line in out.splitlines():
        m = re.search(r"\((\S+)\)\s*$", line)
        if m and not ctx.sites.check(m.group(1), "read").allowed:
            line = re.sub(r"\] .*$", "] (blocked site)", line)
        shown.append(line)
    return "\n".join(shown)


async def web_switch(ctx: Context, tab: int) -> str:
    return await _server().call_tool("select_page", {"pageIdx": tab})


async def web_read(ctx: Context, mode: str = "elements") -> str:
    url = await _check(ctx, "read")
    s = _server()
    if mode == "text":
        return f"{url}\n" + await s.call_tool("get_page_text", {})
    raw = await s.call_tool("take_snapshot", {})
    text, names = compact_snapshot(raw)
    _names.clear()
    _names.update(names)
    return f"{url}\n{text or '(no readable elements)'}"


async def web_click(ctx: Context, name: str) -> str:
    url = await _check(ctx, "click")
    uid = _uid(name)
    label = next((k for k, v in _names.items() if v == uid), name)
    if any(w in label.lower() for w in RISKY_WORDS):
        await ctx.require(Tier.T3, f'click "{label}" on {short(url)}')
    ctx.actions.append(f"web click {label!r}")
    out = await _server().call_tool("click_by_uid", {"uid": uid})
    return f"{out} (not verified: web_read to see the result)"


async def _field_type(uid: str) -> str:
    out = await _server().call_tool(
        "evaluate_script",
        {"function": "(el) => (el.type || el.tagName).toLowerCase()", "args": [{"uid": uid}]},
    )
    m = re.search(r'"([a-z-]+)"', out)
    return m.group(1) if m else ""


async def web_fill(ctx: Context, name: str, text: str) -> str:
    url = await _check(ctx, "fill")
    uid = _uid(name)
    if await _field_type(uid) in ("password", "hidden"):
        raise Denied("TARS never types passwords; please enter it yourself")
    ctx.actions.append(f"web fill {name!r}")
    return (
        await _server().call_tool("fill_by_uid", {"uid": uid, "value": text}) + f" on {short(url)}"
    )


async def web_type(ctx: Context, text: str, then_key: str = "") -> str:
    await _check(ctx, "type")
    focused = await _server().call_tool(
        "evaluate_script", {"function": "() => (document.activeElement?.type || '').toLowerCase()"}
    )
    if '"password"' in focused:
        raise Denied("the focused field is a password field; please type it yourself")
    if then_key.lower().replace(" ", "") in ("control+enter", "ctrl+enter", "meta+enter"):
        await ctx.require(Tier.T3, "type and press Ctrl+Enter (often sends)")
    ctx.actions.append(f"web type {len(text)} chars")
    args = {"text": text, **({"submitKey": then_key} if then_key else {})}
    return await _server().call_tool("type_text", args)


async def web_key(ctx: Context, key: str) -> str:
    await _check(ctx, "type")
    k = key.lower().replace(" ", "")
    if k in ("control+enter", "ctrl+enter", "meta+enter"):
        await ctx.require(Tier.T3, f"press {key} (often sends)")
    return await _server().call_tool("press_key", {"key": key})


async def web_back(ctx: Context) -> str:
    return await _server().call_tool("navigate_history", {"direction": "back"})


async def web_open(url: str) -> str:
    """Used by open_url when Firefox (TARS) is connected."""
    return await _server().call_tool("new_page", {"url": url})


def connected() -> bool:
    server = _get_server()
    return server is not None and server.proc is not None and server.proc.returncode is None


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
