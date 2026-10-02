"""
Research in a hidden browser: web_search (DuckDuckGo) and read_page, in a headless
Firefox with its own empty profile, so the user's Firefox (TARS) is never touched.

The headless Firefox is started by Mozilla's firefox-devtools-mcp on first use and
quit after a few idle minutes. Snap Firefox has a private /tmp, so the driver's
temporary profile goes under ~/snap/firefox/common instead.
"""

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from tars.agent.tools import Context, Denied, Registry, obj
from tars.mcp.client import MCPServer

TMP = Path.home() / "snap/firefox/common/tars-tmp"
IDLE_SECONDS = 300
TEXT_JS = "() => ((document.querySelector('main, article') || document.body).innerText || '').slice(0, 8000)"
RESULTS_JS = """() => [...document.querySelectorAll('.result')].slice(0, 8).map(r => ({
  title: r.querySelector('.result__a')?.innerText || '',
  href: r.querySelector('.result__a')?.href || '',
  snippet: r.querySelector('.result__snippet')?.innerText || ''}))"""

_server: MCPServer | None = None
_idle: asyncio.TimerHandle | None = None
_lock = asyncio.Lock()


async def _browser() -> MCPServer:
    global _server
    async with _lock:
        if _server is None or _server.proc is None or _server.proc.returncode is not None:
            TMP.mkdir(parents=True, exist_ok=True)
            TMP.chmod(0o700)
            _server = MCPServer(
                "firefox-bg", "npx",
                ["-y", "@mozilla/firefox-devtools-mcp@0.10.4", "--headless", "--toolPreset", "basic"],
                {"GECKODRIVER_CACHE_DIR": str(Path.home() / ".local/share/tars/opt/geckodriver"), "TMPDIR": str(TMP)},
            )  # fmt: skip
            await _server.start()
    _touch()
    return _server


def _touch() -> None:
    """(Re)start the idle timer that quits the hidden browser."""
    global _idle
    if _idle:
        _idle.cancel()
    loop = asyncio.get_running_loop()
    _idle = loop.call_later(IDLE_SECONDS, lambda: loop.create_task(shutdown()))


async def shutdown() -> None:
    """Quit the headless Firefox (the driver won't on its own) and the driver."""
    global _server
    server, _server = _server, None
    if server is None:
        return
    try:
        await server.call_tool("close_firefox_session", {}, timeout=10)
    except Exception:
        pass
    await server.close()


def _json(out: str):
    m = re.search(r"```json\s*(.*?)\s*```", out, re.S)
    try:
        return json.loads(m.group(1) if m else out)
    except json.JSONDecodeError:
        return None


def _real_url(href: str) -> str:
    """DuckDuckGo links go through /l/?uddg=<real url>."""
    q = parse_qs(urlparse(href).query)
    return q["uddg"][0] if "uddg" in q else href


async def _goto(url: str) -> None:
    s = await _browser()
    out = await s.call_tool("navigate_page", {"url": url}, timeout=45)
    if out.lstrip().lower().startswith("error") and "no page" in out.lower():
        out = await s.call_tool("new_page", {"url": url}, timeout=45)
    if out.lstrip().lower().startswith("error"):
        raise ConnectionError(out[:200])


async def web_search(ctx: Context, query: str) -> str:
    if not ctx.desktop:
        return ("1. Interstellar Wiki: TARS: https://interstellarfilm.fandom.com/wiki/TARS\n"
                "   TARS is a former U.S. Marine Corps tactical robot... (dry run)")  # fmt: skip
    await _goto(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
    results = (
        _json(await (await _browser()).call_tool("evaluate_script", {"function": RESULTS_JS})) or []
    )
    lines = []
    for i, r in enumerate(results, 1):
        url = _real_url(r.get("href", ""))
        if not url or not ctx.sites.check(url, "read").allowed:
            continue  # e.g. the college sites
        lines.append(
            f"{i}. {r.get('title', '').strip()}: {url}\n   {r.get('snippet', '').strip()[:220]}"
        )
    return "\n".join(lines) or f"no results for {query!r}"


async def read_page(ctx: Context, url: str) -> str:
    if not re.match(r"^https?://", url):
        url = "https://" + url
    decision = ctx.sites.check(url, "read")
    if not decision.allowed:
        raise Denied(decision.reason)
    if not ctx.desktop:
        return f"{url}\n(page text, dry run)"
    await _goto(url)
    s = await _browser()
    text, prev = "", None
    for _ in range(6):  # wait for script-built pages to settle
        text = str(_json(await s.call_tool("evaluate_script", {"function": TEXT_JS})) or "")
        if text and text == prev:
            break
        prev = text
        await asyncio.sleep(1.0)
    return f"{url}\n{text.strip()[:6000] or '(no readable text)'}"


def register(reg: Registry):
    reg.tool(
        "web_search",
        "Search the web (DuckDuckGo) in a hidden browser; returns titles, links and snippets. "
        "For research and questions needing current information. Doesn't touch the user's Firefox.",
        obj(["query"], query={"type": "string"}),
        speak="Searching",
    )(web_search)
    reg.tool(
        "read_page",
        "Read a web page's text in the hidden browser (e.g. a web_search result).",
        obj(["url"], url={"type": "string"}),
        speak="Reading",
    )(read_page)
