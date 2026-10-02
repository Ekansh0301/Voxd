"""
Shortcuts for your sites (config/sites.yaml `shortcuts:`): "search YouTube for lofi",
"play lofi on YouTube", "open my GitHub notifications", "LeetCode two sum",
"QuickRef for git". One reliable step instead of several clicks; the site's access
rules still apply.
"""

import asyncio
import json
import re
from urllib.parse import quote_plus

from tars.agent.tools import Context, Registry, Tier, obj
from tars.tools import browser, desktop

FIRST_VIDEO_JS = "() => { const a = document.querySelector('a#video-title[href*=\"/watch\"], a[href*=\"/watch?v=\"]'); return a ? [a.href, (a.title || a.innerText || '').trim()] : null }"


def slug(text: str) -> str:
    """'Two Sum' -> 'two-sum'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


async def _play_first_video(ctx: Context) -> str:
    s = await browser._ready()
    for _ in range(10):  # results are built by scripts
        await asyncio.sleep(0.8)
        out = await s.call_tool("evaluate_script", {"function": FIRST_VIDEO_JS})
        m = re.search(r"```json\s*(.*?)\s*```", out, re.S)
        found = json.loads(m.group(1)) if m else None
        if found:
            await s.call_tool("navigate_page", {"url": found[0]})
            await asyncio.sleep(1.5)
            out = await s.call_tool("evaluate_script", {"function": "() => document.title"})
            m = re.search(r'"(.*)"', out)
            title = (m.group(1) if m else found[1]).removesuffix(" - YouTube").strip()
            return f"playing {title or 'the first result'} on YouTube"
    return "opened the YouTube results, but couldn't find a video to play"


async def open_site(ctx: Context, site: str, action: str = "", query: str = "") -> str:
    s = ctx.sites.resolve(site)
    if s is None:
        return f"error: {site!r} isn't one of the user's sites; use open_url for others"
    if not action:
        return await desktop.open_url(ctx, s.url)
    template = s.shortcuts.get(action.lower().strip())
    if template is None:
        return (
            f"error: {s.key} has no shortcut {action!r}; it has: {', '.join(s.shortcuts) or 'none'}"
        )
    if ("{q}" in template or "{slug}" in template) and not query.strip():
        return f"error: {s.key} {action} needs a query"
    url = template.replace("{q}", quote_plus(query)).replace("{slug}", slug(query))
    out = await desktop.open_url(ctx, url)
    if s.key == "youtube" and action == "play" and ctx.desktop and not out.startswith("error"):
        return await _play_first_video(ctx)
    return out


def register(reg: Registry):
    reg.tool(
        "open_site",
        "Open one of the user's sites, optionally at a shortcut: youtube search/play/subscriptions, "
        "github notifications/repo/search/pulls/issues, leetcode problem/search, cheatsheet topic "
        "(QuickRef, e.g. 'git'), linkedin notifications/messages/search/jobs.",
        obj(["site"], site={"type": "string"}, action={"type": "string"}, query={"type": "string"}),
        tier=Tier.T1,
        speak="Opening",
    )(open_site)
