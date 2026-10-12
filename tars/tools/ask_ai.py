"""
Ask a web AI (ChatGPT, then Gemini, Claude, AI Studio) the way you would, in your
Firefox, instead of a paid API. Personal details are swapped for placeholders before
anything is typed (tars/privacy.py) and swapped back in the answer.
"""

import json
import re

from tars import profile
from tars.agent.tools import Context, Registry, Tier, obj
from tars.privacy import redact, restore
from tars.tools import browser, desktop

ORDER = ["chatgpt", "gemini", "claude", "aistudio"]
SKIP_FIELDS = ("upload", "search", "file", "image", "photo", "camera", "attach")
LAST_ANSWER_JS = {
    "chatgpt": "() => ([...document.querySelectorAll('[data-message-author-role=assistant]')].pop()?.innerText || '')",
}
BOILERPLATE = re.compile(
    r"(ChatGPT can make mistakes.*|Gemini can make mistakes.*|Claude can make mistakes.*)", re.S
)


def _answer_after(question: str, page: str) -> str:
    """Generic: the page text after the last copy of the question."""
    at = page.rfind(question[:60])
    text = page[at + len(question[:60]) :] if at >= 0 else page[-3000:]
    return BOILERPLATE.sub("", text).strip()


async def _ask_on(ctx: Context, key: str, url: str, question: str) -> str:
    await desktop.open_url(ctx, url)
    await browser.web_read(ctx)  # finds the chat box (also the ones snapshots miss)
    box = next((f for f in browser._fields if not any(w in f.lower() for w in SKIP_FIELDS)), None)
    if box:
        await browser.web_fill(ctx, box, question)
    else:
        await browser.web_type(ctx, question)
    await browser.web_key(ctx, "Enter")
    page = await browser.web_read(ctx, "text")  # waits for the answer to finish
    if key in LAST_ANSWER_JS:
        out = await (await browser._ready()).call_tool(
            "evaluate_script", {"function": LAST_ANSWER_JS[key]}
        )
        m = re.search(r"```json\s*(.*?)\s*```", out, re.S)
        try:
            answer = str(json.loads(m.group(1))) if m else ""
        except json.JSONDecodeError:
            answer = ""
        if answer.strip():
            return answer.strip()
    return _answer_after(question, page)


async def ask_ai(ctx: Context, question: str, site: str = "") -> str:
    safe, mapping = redact(question, profile.load())
    ctx.actions.append(f"ask ai {site or 'chatgpt'}: {safe[:60]!r}")
    if not ctx.desktop:
        return f"chatgpt says: (answer, dry run){' (personal details removed)' if mapping else ''}"
    if not browser.connected():
        # Otherwise open_url falls back to the user's own Firefox and each site opens
        # there as a tab that TARS then can't read.
        if browser._normal_firefox_running():
            return ("error: Firefox is open normally (not as Firefox (TARS)), so TARS can't use "
                    "it. Ask the user to close Firefox and try again; TARS then starts it itself.")  # fmt: skip
        return "error: TARS's browser driver isn't running; the user should restart TARS"
    chosen = ctx.sites.resolve(site) if site else None
    wanted = chosen.key if chosen else ""
    order = [wanted, *[k for k in ORDER if k != wanted]] if wanted else ORDER
    tried = []
    for key in order:
        s = ctx.sites.sites.get(key)
        if s is None or not s.web_ai:
            continue
        try:
            answer = await _ask_on(ctx, key, s.url, safe)
        except ConnectionError as e:
            # Firefox itself isn't usable (open normally, not starting, not responding):
            # every site would fail the same way, so say why instead of trying them all.
            return f"error: couldn't use Firefox: {e}"
        except Exception as e:  # site down, signed out, changed layout: try the next one
            tried.append(f"{key} ({type(e).__name__}: {str(e)[:80]})")
            continue
        if len(answer) < 2:
            tried.append(f"{key} (no answer)")
            continue
        note = (
            f" [{len(mapping)} personal detail(s) were replaced before sending]" if mapping else ""
        )
        return f"{key} says: {restore(answer, mapping)[:3000]}{note}"
    return f"error: no web AI answered ({', '.join(tried) or 'none configured'})"


def register(reg: Registry):
    reg.tool(
        "ask_ai",
        "Ask a web AI (ChatGPT by default, else Gemini or Claude) a question in the user's Firefox and "
        "return its answer. For hard questions or when the user asks an AI site. Personal details "
        "are removed before sending.",
        obj(["question"], question={"type": "string"}, site={"type": "string", "description": "chatgpt, gemini or claude"}),
        tier=Tier.T1,
        speak="Asking",
    )(ask_ai)  # fmt: skip
