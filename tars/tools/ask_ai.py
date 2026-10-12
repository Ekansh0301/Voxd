"""
Ask a web AI (ChatGPT, then Gemini, Claude, AI Studio) the way you would, in your
Firefox, instead of a paid API. Personal details are swapped for placeholders before
anything is typed (tars/privacy.py) and swapped back in the answer.
"""

import asyncio
import json
import re

from tars import profile
from tars.agent.tools import Context, Registry, Tier, obj
from tars.privacy import redact, restore
from tars.tools import browser, desktop

ORDER = ["chatgpt", "gemini", "claude", "aistudio"]
SKIP_FIELDS = ("upload", "search", "file", "image", "photo", "camera", "attach")
LOAD_SECONDS = 25
# Is the chat box there yet, or is the site showing a "verify you are human" page?
PAGE_STATE_JS = """() => {
  const head = document.title + ' ' + (document.body?.innerText || '').slice(0, 400);
  return JSON.stringify({
    box: !!document.querySelector('#prompt-textarea, textarea, [contenteditable=true]'),
    check: /just a moment|verify you are human|checking your browser|attention required|are you a robot/i.test(head),
  });
}"""


class HumanCheck(Exception):
    """The site wants the user to prove they're human; TARS never does that for them."""


async def _eval(js: str) -> dict:
    out = await (await browser._ready()).call_tool("evaluate_script", {"function": js})
    m = re.search(r"```json\s*(.*?)\s*```", out, re.S)
    try:
        value = json.loads(m.group(1)) if m else {}
        return json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return {}


async def _wait_for_chat_box(key: str) -> None:
    """Sites take a while to load (and Firefox to start): don't type before the box exists."""
    state: dict = {}
    for _ in range(LOAD_SECONDS * 2):
        state = await _eval(PAGE_STATE_JS)
        if state.get("box"):
            return
        await asyncio.sleep(0.5)
    if state.get("check"):
        raise HumanCheck(key)
    raise RuntimeError(f"its chat box didn't appear within {LOAD_SECONDS} s")


def _junk(answer: str) -> bool:
    """Not an answer: empty, or only a link (the page's own address once came back)."""
    return len(answer.strip()) < 2 or bool(re.fullmatch(r"\s*https?://\S+\s*", answer))


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
    await _wait_for_chat_box(key)
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
        if not browser._normal_firefox_running():
            return "error: TARS's browser driver isn't running; the user should restart TARS"
        out = await browser.restart_firefox(ctx)  # asks the user first
        if not out.startswith("restarted"):
            return f"error: Firefox is open normally, so TARS can't use it ({out})"
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
        except HumanCheck:
            return (f"error: {key} is showing a 'verify you are human' check in Firefox. TARS "
                    "doesn't do those: ask the user to complete it in the Firefox window, then "
                    "ask again.")  # fmt: skip
        except ConnectionError as e:
            # Firefox itself isn't usable (open normally, not starting, not responding):
            # every site would fail the same way, so say why instead of trying them all.
            return f"error: couldn't use Firefox: {e}"
        except Exception as e:  # site down, signed out, changed layout: try the next one
            tried.append(f"{key} ({type(e).__name__}: {str(e)[:80]})")
            continue
        if _junk(answer):
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
